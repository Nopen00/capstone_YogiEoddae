"""
YouTube 영상에서 촬영 장소를 추출해 DB에 저장하는 개발자용 관리 명령.

사용 예시:
  # Claude로 추론 (기본값)
  python manage.py fetch_youtube_place \
      --url "https://www.youtube.com/watch?v=VIDEO_ID" \
      --media-title "이태원 클라쓰" \
      --media-type drama \
      --scene "박새로이가 처음 이태원을 걷는 장면"

  # Gemini로 추론
  python manage.py fetch_youtube_place \
      --url "..." --media-title "..." --ai gemini

  # 저장 없이 분석 결과만 보기
  python manage.py fetch_youtube_place --url "..." --media-title "..." --dry-run

흐름:
  1. YouTube Data API  → 제목/설명/태그/댓글 수집
  2. youtube-transcript-api → 자막 수집
  3. Claude 또는 Gemini → 촬영 장소 JSON 추론 (--ai 옵션으로 선택)
  4. KTO API 1차 검색 → Place 저장 (is_verified=True)
  5. KTO 결과 없으면 AI 추론 결과로 저장 (is_verified=False, 좌표=0)
  6. Media get_or_create → MediaPlace 연결
"""

import json
import re

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from googleapiclient.discovery import build

from places.models import Media, MediaPlace, Place


# ── 유틸리티 함수 ──────────────────────────────────────────────────────────────

def _extract_video_id(url: str):
    patterns = [
        r'youtu\.be/([a-zA-Z0-9_-]{11})',
        r'youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def _fetch_video_info(youtube, video_id: str) -> dict:
    resp = youtube.videos().list(part='snippet', id=video_id).execute()
    items = resp.get('items', [])
    if not items:
        return {}
    snippet = items[0]['snippet']
    return {
        'title': snippet.get('title', ''),
        'description': snippet.get('description', ''),
        'tags': snippet.get('tags', []),
        'channel_title': snippet.get('channelTitle', ''),
    }


def _fetch_comments(youtube, video_id: str, max_results: int = 20) -> list:
    try:
        resp = youtube.commentThreads().list(
            part='snippet',
            videoId=video_id,
            order='relevance',
            maxResults=max_results,
            textFormat='plainText',
        ).execute()
        return [
            item['snippet']['topLevelComment']['snippet']['textDisplay']
            for item in resp.get('items', [])
        ]
    except Exception:
        return []


def _fetch_transcript(video_id: str) -> tuple:
    """(full_text, segments) 반환. segments = [{'start': float, 'text': str}, ...]"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:
            api = YouTubeTranscriptApi()
            transcript = api.fetch(video_id, languages=['ko', 'en'])
            segments = [{'start': s.start, 'text': s.text} for s in transcript]
        except (AttributeError, TypeError):
            items = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
            segments = [{'start': s['start'], 'text': s['text']} for s in items]
        return ' '.join(s['text'] for s in segments), segments
    except Exception:
        return '', []


def _parse_chapters(description: str) -> list:
    """설명에서 챕터 타임스탬프 추출. [{'time_secs', 'time_str', 'title'}, ...]"""
    chapters = []
    for m in re.finditer(r'(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)', description):
        time_str = m.group(1).strip()
        title = m.group(2).strip()
        parts = [int(p) for p in time_str.split(':')]
        secs = parts[-1] + parts[-2] * 60 + (parts[-3] * 3600 if len(parts) == 3 else 0)
        chapters.append({'time_secs': secs, 'time_str': time_str, 'title': title})
    return chapters


def _build_chapter_transcript(segments: list, chapters: list) -> str:
    """챕터가 있으면 챕터별로 묶어서, 없으면 전체 이어붙여서 반환."""
    if not segments:
        return ''
    if not chapters:
        return ' '.join(s['text'] for s in segments)

    result = []
    for i, chapter in enumerate(chapters):
        start = chapter['time_secs']
        end = chapters[i + 1]['time_secs'] if i + 1 < len(chapters) else float('inf')
        texts = [s['text'] for s in segments if start <= s['start'] < end]
        if texts:
            result.append(f"[{chapter['time_str']} {chapter['title']}]")
            result.append(' '.join(texts))
    return '\n'.join(result)


def _kto_search(keyword: str, num_rows: int = 5) -> list:
    """KTO API로 장소 검색 후 DB 저장, Place 목록 반환."""
    url = "http://apis.data.go.kr/B551011/KorService2/searchKeyword2"
    params = {
        'serviceKey': settings.TOUR_API_KEY,
        'MobileApp': 'YogiEoddae',
        'MobileOS': 'ETC',
        'keyword': keyword,
        '_type': 'json',
        'numOfRows': num_rows,
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        items_data = data.get('response', {}).get('body', {}).get('items')
        if not items_data or not items_data.get('item'):
            return []
        items = items_data['item']
        if isinstance(items, dict):
            items = [items]
        places = []
        for item in items:
            place, _ = Place.objects.update_or_create(
                content_id=item['contentid'],
                defaults={
                    'name': item['title'],
                    'address': item.get('addr1', ''),
                    'latitude': item['mapy'],
                    'longitude': item['mapx'],
                    'image_url': item.get('firstimage', ''),
                    'category': item.get('contenttypeid', ''),
                    'is_verified': True,
                },
            )
            places.append(place)
        return places
    except Exception:
        return []


# ── AI 추론 공통 ───────────────────────────────────────────────────────────────

def _build_location_prompt(context: dict) -> str:
    """Claude / Gemini 공용 프롬프트."""
    comments_text = '\n'.join(context['comments'][:15])[:800]

    chapters = context.get('chapters', [])
    chapter_transcript = context.get('chapter_transcript', '')
    transcript = context.get('transcript', '')

    if chapters:
        chapter_list = '\n'.join(f"  {c['time_str']} {c['title']}" for c in chapters)
        transcript_section = f"""## 영상 챕터
{chapter_list}

## 챕터별 자막 (전체 — 챕터 이동 시 장소 변화 가능)
{chapter_transcript or '(없음)'}"""
    else:
        transcript_section = f"""## 자막 (전체)
{transcript or '(자막 없음)'}"""

    return f"""아래 유튜브 영상 정보를 분석해서 영상에 등장하는 한국의 실제 방문 가능한 촬영 장소를 추론해주세요.

## 영상 제목
{context['title']}

## 영상 설명 (전체)
{context['description']}

## 영상 태그
{', '.join(context['tags'])}

{transcript_section}

## 인기 댓글 (일부)
{comments_text if comments_text else '(댓글 없음)'}

---

위 정보에서 실제 방문 가능한 한국의 구체적인 장소(관광지, 음식점, 거리, 공원, 카페 등)를 최대 {context.get("max_locations", 10)}개까지 추론하세요.
챕터가 있는 경우 챕터 단위로 장소 변화를 분석하세요.
장소를 특정할 수 없으면 locations를 빈 배열로 반환하세요.
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 쓰지 마세요.

{{
  "locations": [
    {{
      "name": "장소명 (예: 광화문광장)",
      "address_hint": "주소 힌트 (예: 서울 종로구)",
      "confidence": 0.75,
      "reason": "추론 이유 한 줄"
    }}
  ]
}}"""


def _parse_locations(text: str) -> list:
    """AI 응답 텍스트에서 locations JSON 파싱."""
    try:
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return data.get('locations', [])
    except (json.JSONDecodeError, AttributeError):
        pass
    return []


def _claude_infer(api_key: str, context: dict, stdout) -> list:
    """Claude API (claude-opus-4-7) 스트리밍 추론."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_location_prompt(context)

    stdout.write('    Claude (claude-opus-4-7) 분석 중 (스트리밍)...')
    parts = []
    with client.messages.stream(
        model='claude-opus-4-7',
        max_tokens=1024,
        messages=[{'role': 'user', 'content': prompt}],
    ) as stream:
        for text in stream.text_stream:
            parts.append(text)
            stdout.write(text, ending='')
    stdout.write('')

    return _parse_locations(''.join(parts))


def _gemini_infer(api_key: str, context: dict, stdout) -> list:
    """Gemini API (gemini-2.5-flash) 스트리밍 추론."""
    from google import genai

    client = genai.Client(api_key=api_key)
    prompt = _build_location_prompt(context)

    stdout.write('    Gemini (gemini-2.5-flash) 분석 중 (스트리밍)...')
    parts = []
    for chunk in client.models.generate_content_stream(
        model='gemini-2.5-flash',
        contents=prompt,
    ):
        if chunk.text:
            parts.append(chunk.text)
            stdout.write(chunk.text, ending='')
    stdout.write('')

    return _parse_locations(''.join(parts))


# ── Command ────────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'YouTube 영상에서 촬영 장소를 추출해 DB에 저장합니다 (개발자용).'

    def add_arguments(self, parser):
        parser.add_argument('--url', required=True, help='YouTube 영상 URL')
        parser.add_argument('--media-title', required=True, dest='media_title',
                            help='연결할 미디어 제목 (드라마명, 영화명 등)')
        parser.add_argument('--media-type', default='youtube', dest='media_type',
                            choices=['drama', 'movie', 'youtube', 'etc'],
                            help='미디어 유형 (기본값: youtube)')
        parser.add_argument('--scene', default='', help='장면 설명 (예: 주인공이 걷던 거리)')
        parser.add_argument('--ai', default='claude', choices=['claude', 'gemini'],
                            help='장소 추론에 사용할 AI (기본값: claude)')
        parser.add_argument('--dry-run', action='store_true', dest='dry_run',
                            help='DB에 저장하지 않고 분석 결과만 출력')
        parser.add_argument('--debug', action='store_true',
                            help='수집된 원본 데이터와 AI 프롬프트 전체 출력')

    def handle(self, *args, **options):
        url = options['url']
        media_title = options['media_title']
        media_type = options['media_type']
        scene = options['scene']
        ai_choice = options['ai']
        dry_run = options['dry_run']
        debug = options['debug']

        # API 키 사전 확인
        if not settings.YOUTUBE_API_KEY:
            self.stderr.write(self.style.ERROR(
                'YOUTUBE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.'))
            return

        if ai_choice == 'claude' and not settings.ANTHROPIC_API_KEY:
            self.stderr.write(self.style.ERROR(
                'ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.'))
            return

        if ai_choice == 'gemini' and not settings.GEMINI_API_KEY:
            self.stderr.write(self.style.ERROR(
                'GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.'))
            return

        # 1. video_id 추출
        video_id = _extract_video_id(url)
        if not video_id:
            self.stderr.write(self.style.ERROR(f'유효한 YouTube URL이 아닙니다: {url}'))
            return

        ai_label = 'Claude' if ai_choice == 'claude' else 'Gemini'
        header = f'\n[YouTube 장소 추출 / {ai_label}] {url}'
        if dry_run:
            header += ' (dry-run)'
        self.stdout.write(self.style.MIGRATE_HEADING(header + '\n'))

        # 2. YouTube Data API 초기화
        youtube = build('youtube', 'v3', developerKey=settings.YOUTUBE_API_KEY)

        # 3. 영상 메타데이터
        self.stdout.write('  [1/4] 영상 메타데이터 수집 중...')
        video_info = _fetch_video_info(youtube, video_id)
        if not video_info:
            self.stderr.write(self.style.ERROR(
                '영상 정보를 가져올 수 없습니다. video_id를 확인하세요.'))
            return
        self.stdout.write(f'        제목: {video_info["title"]}')

        # 4. 댓글 수집
        self.stdout.write('  [2/4] 댓글 수집 중...')
        comments = _fetch_comments(youtube, video_id)
        self.stdout.write(f'        댓글 {len(comments)}개 수집')

        # 5. 자막 수집
        self.stdout.write('  [3/4] 자막 수집 중...')
        transcript, segments = _fetch_transcript(video_id)
        chapters = _parse_chapters(video_info['description'])
        chapter_transcript = _build_chapter_transcript(segments, chapters)
        self.stdout.write(
            f'        자막 {"수집됨" if transcript else "없음"} ({len(transcript)}자)'
            + (f' / 챕터 {len(chapters)}개' if chapters else ''))

        # 6. AI 장소 추론
        self.stdout.write(f'  [4/4] {ai_label} 장소 추론 중...')
        context = {
            'title': video_info['title'],
            'description': video_info['description'],
            'tags': video_info['tags'],
            'transcript': transcript,
            'segments': segments,
            'chapters': chapters,
            'chapter_transcript': chapter_transcript,
            'comments': comments,
        }

        if debug:
            import os
            debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'debug_context.txt')
            debug_path = os.path.normpath(debug_path)
            sep = '─' * 60
            lines = [
                sep,
                '[DEBUG] 수집된 원본 데이터',
                sep,
                f'[제목]\n{video_info["title"]}\n',
                f'[채널명]\n{video_info.get("channel_title", "")}\n',
                f'[설명 전체]\n{video_info["description"]}\n',
                f'[태그]\n{", ".join(video_info["tags"]) or "(없음)"}\n',
                f'[챕터 {len(chapters)}개]\n' + '\n'.join(
                    f'  {c["time_str"]} {c["title"]}' for c in chapters) + '\n',
                f'[자막 전체 ({len(transcript)}자)]\n{chapter_transcript or transcript or "(없음)"}\n',
                f'[댓글 {len(comments)}개]',
            ]
            for i, c in enumerate(comments, 1):
                lines.append(f'  {i}. {c}')
            lines += [
                f'\n{sep}',
                '[DEBUG] AI에 전달되는 프롬프트',
                sep,
                _build_location_prompt(context),
                sep,
            ]
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            self.stdout.write(f'  [DEBUG] 원본 데이터와 프롬프트를 파일에 저장: {debug_path}')

        if ai_choice == 'claude':
            inferred = _claude_infer(settings.ANTHROPIC_API_KEY, context, self.stdout)
        else:
            inferred = _gemini_infer(settings.GEMINI_API_KEY, context, self.stdout)

        if not inferred:
            self.stdout.write(self.style.WARNING('\n추론된 장소가 없습니다.'))
            return

        self.stdout.write(f'\n  추론 결과: {len(inferred)}개 장소')
        for loc in inferred:
            self.stdout.write(
                f'    - {loc.get("name","")} ({loc.get("address_hint","")}) '
                f'confidence={float(loc.get("confidence", 0)):.2f}')
            self.stdout.write(f'      이유: {loc.get("reason","")}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[dry-run] DB에 저장하지 않습니다.'))
            return

        # 7. Media get_or_create
        media, created = Media.objects.get_or_create(
            title=media_title,
            defaults={
                'media_type': media_type,
                'thumbnail_url': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
                'description': video_info.get('description', '')[:500],
            },
        )
        status = '✓ 생성' if created else '- 기존'
        self.stdout.write(
            f'\n  {status}: 미디어 [{media.get_media_type_display()}] {media.title}')

        # 8. 각 추론 장소 처리
        saved_count = 0
        for loc in inferred:
            loc_name = loc.get('name', '').strip()
            loc_address = loc.get('address_hint', '').strip()
            confidence = float(loc.get('confidence', 0.5))
            if not loc_name:
                continue

            self.stdout.write(f'\n  장소 처리: {loc_name}')

            # Step 1: KTO API
            self.stdout.write(f'    KTO API 검색 중: {loc_name}')
            kto_places = _kto_search(loc_name)

            if kto_places:
                place = kto_places[0]
                self.stdout.write(
                    self.style.SUCCESS(
                        f'    ✓ KTO 확인: {place.name} ({place.address})'))
            else:
                # Step 2: AI 추론 결과로 미확정 Place 저장
                self.stdout.write(
                    self.style.WARNING('    KTO 결과 없음 → AI 추론 결과로 저장 (미확정)'))
                safe_name = re.sub(r'[^a-zA-Z0-9가-힣]', '_', loc_name)[:20]
                synthetic_id = f'yt_{video_id}_{safe_name}'
                place, p_created = Place.objects.get_or_create(
                    content_id=synthetic_id,
                    defaults={
                        'name': loc_name,
                        'address': loc_address,
                        'latitude': 0,
                        'longitude': 0,
                        'is_verified': False,
                    },
                )
                verb = '저장' if p_created else '기존'
                self.stdout.write(f'    {verb}: {place.name} (미확정, 좌표 미입력)')

            # MediaPlace 연결
            mp, mp_created = MediaPlace.objects.get_or_create(
                media=media,
                place=place,
                defaults={
                    'scene_description': scene or loc.get('reason', ''),
                    'confidence_score': confidence,
                    'is_confirmed': place.is_verified and confidence >= 0.9,
                },
            )
            if mp_created:
                saved_count += 1
                self.stdout.write(f'    연결 완료: {media.title} → {place.name}')
            else:
                self.stdout.write(f'    이미 연결됨: {media.title} → {place.name}')

        self.stdout.write(self.style.SUCCESS(f'\n완료! MediaPlace {saved_count}개 생성\n'))

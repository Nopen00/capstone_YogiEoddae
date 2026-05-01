import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from places.models import MediaPlace, Media, Place


SEED_DATA = [
    {
        'media': {
            'title': '이태원 클라쓰',
            'media_type': 'drama',
            'year': 2020,
            'description': '이태원을 배경으로 한 청춘 성장 드라마. JTBC 방영.',
        },
        'places': [
            {'keyword': '이태원',  'scene': '박새로이의 포차 거리',          'confidence': 0.9},
            {'keyword': '노량진',  'scene': '박새로이 고시원 시절 거리',      'confidence': 0.7},
        ],
    },
    {
        'media': {
            'title': '도깨비',
            'media_type': 'drama',
            'year': 2016,
            'description': '쓸쓸하고 찬란하神 도깨비. tvN 방영.',
        },
        'places': [
            {'keyword': '강릉',     'scene': '도깨비와 은탁이 걷던 해변길',   'confidence': 0.9},
            {'keyword': '인천 송도', 'scene': '은탁의 등굣길',                'confidence': 0.85},
        ],
    },
    {
        'media': {
            'title': '기생충',
            'media_type': 'movie',
            'year': 2019,
            'description': '봉준호 감독. 아카데미 4관왕 수상작.',
        },
        'places': [
            {'keyword': '마포',    'scene': '기택네 반지하 골목 일대',        'confidence': 0.8},
        ],
    },
    {
        'media': {
            'title': '사랑의 불시착',
            'media_type': 'drama',
            'year': 2019,
            'description': '남북한 로맨스 드라마. tvN 방영.',
        },
        'places': [
            {'keyword': '춘천',    'scene': '리정혁과 윤세리의 산책로',       'confidence': 0.75},
        ],
    },
    {
        'media': {
            'title': '응답하라 1988',
            'media_type': 'drama',
            'year': 2015,
            'description': '쌍문동 골목을 배경으로 한 청춘 드라마. tvN 방영.',
        },
        'places': [
            {'keyword': '도봉구',  'scene': '쌍문동 골목 주택가',            'confidence': 0.85},
        ],
    },
]


def _fetch_places_from_kto(keyword, num_rows=3):
    """관광공사 API에서 키워드로 장소를 가져와 DB에 저장 후 Place 목록 반환."""
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
                },
            )
            places.append(place)
        return places

    except Exception as e:
        return []


class Command(BaseCommand):
    help = '미디어 성지순례 샘플 데이터 생성 (Media + Place + MediaPlace)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('\n샘플 데이터 생성 시작...\n'))

        media_created = 0
        place_processed = 0
        link_created = 0

        for entry in SEED_DATA:
            media, created = Media.objects.get_or_create(
                title=entry['media']['title'],
                defaults={k: v for k, v in entry['media'].items() if k != 'title'},
            )

            status = '✓ 생성' if created else '- 기존'
            self.stdout.write(f"  {status}: [{media.get_media_type_display()}] {media.title}")
            if created:
                media_created += 1

            for place_cfg in entry['places']:
                self.stdout.write(f"      키워드 '{place_cfg['keyword']}' 검색 중...")
                places = _fetch_places_from_kto(place_cfg['keyword'])
                place_processed += len(places)

                for place in places:
                    _, mp_created = MediaPlace.objects.get_or_create(
                        media=media,
                        place=place,
                        defaults={
                            'scene_description': place_cfg['scene'],
                            'confidence_score': place_cfg['confidence'],
                            'is_confirmed': place_cfg['confidence'] >= 0.9,
                        },
                    )
                    if mp_created:
                        link_created += 1
                        self.stdout.write(f"        → {place.name} 연결 완료")

        self.stdout.write(self.style.SUCCESS(
            f'\n완료! 미디어 {media_created}개 생성 | '
            f'장소 {place_processed}개 처리 | '
            f'연결 {link_created}개 생성\n'
        ))

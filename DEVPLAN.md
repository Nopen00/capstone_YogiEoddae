# 요기어때? — 개발 로드맵

> 이 문서는 개발자(이태용)와 Claude 둘 다 참고하는 개발 방향 지표입니다.
> 매일 개발이 어려운 환경을 감안해, 어디서 멈췄든 이 문서를 보면 다음 할 일을 바로 알 수 있도록 작성했습니다.

---

## 프로젝트 개요

**앱 이름:** 요기어때?  
**핵심 컨셉:** 드라마·영화·유튜브 속 촬영 장소를 테마별로 묶어 실제 방문 코스로 안내하는 여행 앱  
**팀:** 이태용 (백엔드/Django), 강혜진 (프론트/React Native)  
**목표 발표:** 캡스톤 디자인 + 한이음 공모전

### 기술 스택

| 영역 | 기술 |
|---|---|
| 백엔드 | Python 3.x, Django, Django REST Framework |
| DB | MySQL |
| 프론트 | React Native (팀원 담당) |
| 지도 | Kakao Maps JS API (Naver Maps 오류로 임시 대체, Naver 복구 시 전환 예정) |
| 외부 API | 한국관광공사(KorService2), YouTube Data API, Kakao/Naver Maps |

---

## 현재 구현 완료 상태 (2026-05-16 기준)

### DB 모델

| 모델 | 주요 필드 | 상태 |
|---|---|---|
| `Place` | name, address, lat/lng, content_id, image_url, category, is_verified | ✅ 완료 |
| `Media` | title, media_type(drama/movie/youtube/etc), year, thumbnail_url, description | ✅ 완료 |
| `MediaPlace` | media FK, place FK, scene_description, confidence_score(0.0~1.0), is_confirmed | ✅ 완료 |

### API 엔드포인트

```
GET  /api/places/              전체 장소 목록 (keyword/category/unverified 필터)
GET  /api/places/{id}/         장소 상세
GET  /api/places/map/          지도용 좌표 + 연결 미디어 (media_id 필터)
GET  /api/media/               전체 미디어 목록 (type 필터)
GET  /api/media/{id}/          미디어 상세 + 촬영지 목록
GET  /api/media/{id}/places/   특정 미디어의 촬영지만 조회

GET  /places/fetch/            KTO API → DB 저장 (keyword 파라미터)
GET  /places/list/             DB 장소 목록 JSON (name 검색)
GET  /places/map-test/         지도 테스트 페이지 (Kakao)
GET  /places/demo/             데모 페이지
```

### 기타

- `python manage.py seed_data` — 샘플 미디어/장소 데이터 생성 (KTO API 호출 포함)
- `python manage.py fetch_youtube_place` — YouTube 영상 → Claude API 장소 추론 → DB 저장
- KTO API 연동: 키워드 검색 → Place 자동 저장
- Kakao 지도 마커 표시: MediaPlace로 연결된 장소만 지도에 표시

---

## 개발 우선순위 및 순서

아래 순서대로 진행하는 것을 권장합니다. 각 Phase는 독립적으로 완결되도록 설계해서, 중간에 멈춰도 이전 Phase까지는 작동하는 상태로 유지됩니다.

---

### ✅ Phase 1 — Tag 시스템 (완료 2026-05-15)


**왜 먼저 해야 하나:**  
앱의 핵심 차별점이 "테마별 성지 연결"인데, Tag 없이는 필터링이 불가합니다.  
또한 이후 YouTube 장소 추출, 퀴즈, 일정 기능 모두 Tag와 연결되므로 기반 작업입니다.

**구현할 것:**

1. `Tag` 모델 추가
   - 대분류 (예: 드라마, 영화, 로맨스, 액션, 힐링, 서울, 지방 ...)
   - 소분류 (예: tvN드라마, 봉준호영화, 해안선, 골목길 ...)

2. `Place`와 `Media`에 Tag 연결 (ManyToMany)

3. API에 Tag 필터 추가
   - `GET /api/places/?tag=로맨스`
   - `GET /api/media/?tag=드라마`

**목표 모델 구조:**
```python
class Tag(models.Model):
    category = models.CharField(max_length=50)   # 대분류
    name = models.CharField(max_length=50)        # 소분류

# Place, Media에 tags = ManyToManyField(Tag) 추가
```

---

### ✅ Phase 2 — YouTube API 장소 추출 (완료 2026-05-16)

**구현 완료:**

1. `fetch_youtube_place` management command (`places/management/commands/fetch_youtube_place.py`)
   - YouTube URL → 영상 제목/설명/태그/댓글/자막 수집
   - Claude API (`claude-opus-4-7`, 스트리밍) → 촬영 장소 JSON 추론
   - KTO API 1차 검색 → `Place` 저장 (`is_verified=True`)
   - KTO 결과 없으면 AI 추론 결과로 저장 (`is_verified=False`, 좌표=0)
   - `Media` get_or_create + `MediaPlace` 연결

2. `confidence_score` 초기값 로직
   - KTO 확인 + confidence ≥ 0.9 → `is_confirmed=True`
   - 나머지 → `is_confirmed=False`

**사용법:**

```bash
# 기본 사용
python manage.py fetch_youtube_place \
    --url "https://www.youtube.com/watch?v=VIDEO_ID" \
    --media-title "이태원 클라쓰" \
    --media-type drama \
    --scene "박새로이가 처음 이태원을 걷는 장면"

# 저장 없이 분석 결과만 확인
python manage.py fetch_youtube_place \
    --url "..." --media-title "..." --dry-run
```

**사전 준비:**
- `.env`에 `ANTHROPIC_API_KEY`, `YOUTUBE_API_KEY` 실제 값 입력 필요
- 설치된 패키지: `anthropic`, `google-api-python-client`, `youtube-transcript-api`

**알려진 한계:**
- KTO에 없는 장소는 좌표가 0,0으로 저장됨 (Phase 3 또는 관리자 수동 입력 필요)
- 자막이 없는 영상은 제목/설명/댓글만으로 추론 (정확도 낮을 수 있음)

---

### Phase 3 — Quiz + 신뢰도 계산

**왜 세 번째인가:**  
퀴즈는 앱의 핵심 UX이자 위치 확정의 유일한 수단입니다.  
`MediaPlace.confidence_score` 필드는 이미 있지만, 올라가는 로직이 전혀 없는 상태입니다.

**구현할 것:**

1. `Photo` 모델 추가
   - 장소의 실제 사진 (퀴즈에 사용)
   - `place` FK, `image_url`, `description`

2. `Quiz` 모델 추가
   - `media_place` FK (어떤 미디어-장소 쌍에 대한 퀴즈인지)
   - `photo` FK (힌트 사진)
   - 정답 집계 필드 (`correct_count`, `total_count`)

3. 퀴즈 API
   - `GET /api/quiz/` — 미확정 장소(`is_confirmed=False`) 중 랜덤 퀴즈 반환
   - `POST /api/quiz/{id}/answer/` — 정답 제출 → `confidence_score` 업데이트

4. 신뢰도 계산 로직
   - 정답률이 일정 기준(예: 80%) 이상이고 응답 수가 N개 이상이면 `is_confirmed=True`로 자동 전환

---

### Phase 4 — 일정 기능 (Schedule / DailyPlace)

**왜 네 번째인가:**  
사용자 편의 기능으로, 앞의 3개가 완성된 후 붙이는 것이 자연스럽습니다.  
이 기능은 앱의 "내 일정" 탭에 해당합니다.

**구현할 것:**

1. `Schedule` 모델 — 사용자가 만드는 여행 일정 (제목, 날짜 범위)
2. `DailyPlace` 모델 — 일정 내 하루별 장소 목록 (day 번호, place FK, 방문 순서)
3. API: 일정 CRUD, 일정에 장소 추가/제거/순서 변경

**주의:** User(사용자) 모델이 없으면 일정을 저장할 주체가 없습니다.  
이 Phase 전에 Django 기본 User 또는 간단한 인증(JWT 등) 구현이 필요합니다.

---

### Phase 5 — 지도 고도화 (낮은 우선순위)

**현황:** Naver Maps API 오류로 Kakao Maps로 임시 전환, 마커 표시는 작동 중

**추후 할 것:**
- 장소 간 경로 안내 (현재 위치 → 촬영지)
- 내 위치 기반 주변 촬영지 탐색
- Naver Maps 오류 원인 재확인 후 전환 여부 결정

---

## 목표 DB 스키마 (최종)

발표 슬라이드의 목표 스키마를 현재 구현과 맞춰 정리한 버전입니다.  
개발 여건에 따라 세부 필드는 바뀔 수 있지만, 이 구조를 지향합니다.

```
Place ──── Tag (ManyToMany)
  │
  └── MediaPlace ── Media ── Tag (ManyToMany)
        │
        └── Quiz ── Photo

Place ──── DailyPlace ── Schedule ── User
```

| 모델 | 현재 상태 | 목표 |
|---|---|---|
| Place | ✅ 있음 | Tag 연결 추가 |
| Media | ✅ 있음 (Media로 구현) | Tag 연결 추가 |
| MediaPlace | ✅ 있음 | Quiz 연결 추가 |
| Tag | ❌ 없음 | Phase 1 |
| Photo | ❌ 없음 | Phase 3 |
| Quiz | ❌ 없음 | Phase 3 |
| Schedule | ❌ 없음 | Phase 4 |
| DailyPlace | ❌ 없음 | Phase 4 |
| User/Auth | ❌ 없음 | Phase 4 전에 |

---

## 알려진 이슈

| 이슈 | 상태 | 비고 |
|---|---|---|
| Naver Maps API 작동 안 함 | 미해결 | Kakao로 임시 대체, 우선순위 낮음 |
| YouTube API 미연동 | ✅ 구현 완료 | Phase 2 완료, API 키 입력 필요 |
| confidence_score 업데이트 로직 없음 | 필드만 있음 | Phase 3 |
| 사용자 인증 없음 | 미구현 | Phase 4 전 선행 필요 |

---

## 개발 재개 체크리스트

오랜만에 돌아왔을 때 이것만 확인하면 됩니다:

```bash
# 서버 실행
python manage.py runserver

# DB 마이그레이션 확인
python manage.py showmigrations

# 샘플 데이터 재생성 (DB 비어있을 때)
python manage.py seed_data
```

그리고 이 문서의 **Phase 순서**에서 체크되지 않은 가장 앞 단계부터 시작하면 됩니다.

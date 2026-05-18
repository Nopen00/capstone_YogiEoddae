import requests
from django.conf import settings
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Place, Media, MediaPlace, Tag
from .serializers import (
    PlaceSerializer, PlaceMapSerializer,
    MediaSerializer, MediaDetailSerializer, MediaPlaceSerializer,
    TagSerializer,
)


def place_map_test(request):
    places = Place.objects.all()
    return render(request, 'places/map_test.html', {
        'places': places,
        'naver_client_id': settings.NAVER_CLIENT_ID,
    })


def demo_view(request):
    media_list = Media.objects.all().order_by('media_type', 'title')
    return render(request, 'places/demo.html', {
        'media_list': media_list,
        'kakao_js_key': settings.KAKAO_JS_KEY,
    })

def fetch_and_save_places(request):
    # 1. API 호출 설정
    keyword = request.GET.get('keyword', '잠수교')  # 검색어 (기본값: 잠수교)
    url = "http://apis.data.go.kr/B551011/KorService2/searchKeyword2"
    
    params = {
        'serviceKey': settings.TOUR_API_KEY, # .env에서 가져온 키
        'MobileApp': 'YogiEoddae',
        'MobileOS': 'ETC',
        'keyword': keyword,
        '_type': 'json',
        'numOfRows': 10, # 일단 10개만 가져와보자
    }

    try:
        # 2. API 데이터 가져오기
        response = requests.get(url, params=params)
        data = response.json()
        
        # [수정 포인트] 아이템이 있는지 안전하게 확인
        body = data.get('response', {}).get('body', {})
        items_data = body.get('items')
        
        # 검색 결과가 아예 없는 경우 (items가 공백이거나 None일 때)
        if not items_data or not items_data.get('item'):
            return JsonResponse({'status': 'success', 'new_saved': 0, 'message': '검색 결과가 없습니다.'}, json_dumps_params={'ensure_ascii': False})

        items = items_data['item']
        
        # 만약 결과가 딱 1개면 리스트가 아니라 딕셔너리로 올 때가 있어서 리스트로 통일
        if isinstance(items, dict):
            items = [items]

        
        saved_count = 0
        for item in items:
            # 3. 데이터 중복 체크 및 저장 (이미 있으면 업데이트, 없으면 생성)
            place, created = Place.objects.update_or_create(
                content_id=item['contentid'], # 고유 ID 기준
                defaults={
                    'name': item['title'],
                    'address': item.get('addr1', ''),
                    'latitude': item['mapy'],
                    'longitude': item['mapx'],
                    'image_url': item.get('firstimage', ''),
                    'category': item.get('contenttypeid', ''),
                }
            )
            if created:
                saved_count += 1

        return JsonResponse({'status': 'success', 'new_saved': saved_count})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    


def get_place_list(request):
    # 1. DB에서 모든 장소 데이터를 가져오기
    # 주소창에서 검색어 가져오기 (예: ?name=박물관)
    search_name = request.GET.get('name', '')

    if search_name:
        # 이름에 검색어가 포함된 것만 가져오기
        places = Place.objects.filter(name__icontains=search_name).order_by('-created_at')
    else:
        # 검색어 없으면 전체 가져오기
        places = Place.objects.all().order_by('-created_at')

    place_list = []
    
    # 2. 데이터를 파이썬 리스트/딕셔너리 형태로 변환
    place_list = []
    for p in places:
        place_list.append({
            'id': p.id,
            'name': p.name,
            'address': p.address,
            'latitude': float(p.latitude),   # Decimal은 JSON으로 바로 못 보내서 숫자로 변환
            'longitude': float(p.longitude),
            'image_url': p.image_url,
        })
    
    # 3. JSON으로 응답 (한글 깨짐 방지 옵션 추가!)
    return JsonResponse(
        {'status': 'success', 'data': place_list},
        json_dumps_params={'ensure_ascii': False}
    )


# ── 관리자 포털 뷰 ───────────────────────────────────────────────────────────

def index_view(request):
    pending  = MediaPlace.objects.filter(status=MediaPlace.STATUS_INFERRED).count()
    approved = MediaPlace.objects.filter(status=MediaPlace.STATUS_ADMIN_APPROVED).count()
    quiz     = MediaPlace.objects.filter(status=MediaPlace.STATUS_QUIZ_CONFIRMED).count()
    return render(request, 'places/index.html', {
        'pending_count':  pending,
        'approved_count': approved,
        'quiz_count':     quiz,
        'media_count':    Media.objects.count(),
    })


def admin_media_list_view(request):
    media_list = Media.objects.annotate(
        inferred_count=Count('media_places', filter=Q(media_places__status=MediaPlace.STATUS_INFERRED)),
        approved_count=Count('media_places', filter=Q(media_places__status=MediaPlace.STATUS_ADMIN_APPROVED)),
        rejected_count=Count('media_places', filter=Q(media_places__status=MediaPlace.STATUS_REJECTED)),
        quiz_count=Count('media_places', filter=Q(media_places__status=MediaPlace.STATUS_QUIZ_CONFIRMED)),
    ).order_by('-created_at')
    return render(request, 'places/admin_media_list.html', {'media_list': media_list})


def admin_extract_view(request):
    if request.method == 'POST':
        from places.services import run_extraction
        url           = request.POST.get('url', '').strip()
        media_title   = request.POST.get('media_title', '').strip()
        media_type    = request.POST.get('media_type', 'youtube')
        max_locations = int(request.POST.get('max_locations') or 10)
        ai_choice     = request.POST.get('ai_choice', 'gemini')
        scene         = request.POST.get('scene', '').strip()

        result = run_extraction(url, media_title, media_type, max_locations, ai_choice, scene)
        if result['error']:
            return render(request, 'places/admin_extract.html', {
                'error': result['error'],
                'form': request.POST,
            })
        return redirect('admin_review', media_id=result['media'].pk)

    prefill = {}
    media_id = request.GET.get('media_id')
    if media_id:
        from .models import Media as _Media
        try:
            m = _Media.objects.get(pk=media_id)
            prefill = {
                'url':         m.source_url,
                'media_title': m.title,
                'media_type':  m.media_type,
                'max_locations': '10',
            }
        except _Media.DoesNotExist:
            pass
    return render(request, 'places/admin_extract.html', {'form': prefill} if prefill else {})


def admin_revoke_approval_view(request, mp_id):
    """승인된 장소를 다시 검토 대기 상태로 되돌리기."""
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    mp = get_object_or_404(MediaPlace, pk=mp_id, status=MediaPlace.STATUS_ADMIN_APPROVED)
    mp.status       = MediaPlace.STATUS_INFERRED
    mp.is_confirmed = False
    mp.save(update_fields=['status', 'is_confirmed'])
    return JsonResponse({'ok': True})


def admin_geocode_media_view(request, media_id):
    """미디어에 연결된 장소 중 주소가 불명확한 것을 카카오로 일괄 보완."""
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    from .services import kakao_search, _has_precise_address
    media = get_object_or_404(Media, pk=media_id)
    places = Place.objects.filter(media_places__media=media).distinct()

    updated, skipped = 0, 0
    for place in places:
        if _has_precise_address(place.address):
            skipped += 1
            continue
        kakao = kakao_search(place.name)
        if kakao and _has_precise_address(kakao['address']):
            place.address   = kakao['address']
            place.latitude  = kakao['lat']
            place.longitude = kakao['lng']
            place.save(update_fields=['address', 'latitude', 'longitude'])
            updated += 1
        else:
            skipped += 1

    return JsonResponse({'ok': True, 'updated': updated, 'skipped': skipped})


def admin_place_search_view(request):
    """장소명으로 KTO → Kakao 순서로 검색, 후보 목록 반환."""
    keyword = request.GET.get('q', '').strip()
    if not keyword:
        return JsonResponse({'results': []})

    # 1차: KTO 관광공사 검색
    from places.management.commands.fetch_youtube_place import _kto_search
    from places.services import kakao_search, _has_precise_address
    candidates = _kto_search(keyword, num_rows=5)
    results = []
    for p in candidates:
        if not p.address:
            continue
        addr = p.address
        lat  = float(p.latitude)
        lng  = float(p.longitude)
        # KTO 주소가 불명확하면 카카오로 보완
        if not _has_precise_address(addr):
            kakao = kakao_search(p.name)
            if kakao and _has_precise_address(kakao['address']):
                addr = kakao['address']
                lat  = kakao['lat']
                lng  = kakao['lng']
        results.append({
            'name': p.name, 'address': addr,
            'lat': lat, 'lng': lng, 'source': 'kto',
        })

    # 2차: KTO 결과 없으면 카카오 키워드 검색으로 폴백
    if not results and settings.KAKAO_REST_KEY:
        try:
            resp = requests.get(
                'https://dapi.kakao.com/v2/local/search/keyword.json',
                params={'query': keyword, 'size': 5},
                headers={'Authorization': f'KakaoAK {settings.KAKAO_REST_KEY}'},
                timeout=5,
            )
            for doc in resp.json().get('documents', []):
                results.append({
                    'name':    doc['place_name'],
                    'address': doc.get('road_address_name') or doc.get('address_name', ''),
                    'lat':     float(doc['y']),
                    'lng':     float(doc['x']),
                    'source':  'kakao',
                })
        except Exception:
            pass

    return JsonResponse({'results': results})


def admin_place_update_view(request, place_id):
    """장소 이름/주소 수정 (추가 확인 필요 섹션에서 인라인 편집용)."""
    import json
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    place = get_object_or_404(Place, pk=place_id)
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({'ok': False, 'error': '잘못된 요청'}, status=400)

    name    = data.get('name', '').strip()
    address = data.get('address', '').strip()
    lat     = data.get('lat')
    lng     = data.get('lng')

    update_fields = []
    if name:
        place.name = name
        update_fields.append('name')
    if address:
        place.address = address
        update_fields.append('address')

    if lat is not None and lng is not None:
        # KTO 검색 결과에서 좌표를 직접 받은 경우
        try:
            place.latitude    = float(lat)
            place.longitude   = float(lng)
            place.is_verified = True
            update_fields += ['latitude', 'longitude', 'is_verified']
        except (ValueError, TypeError):
            pass
    elif address and (float(place.latitude) == 0 or float(place.longitude) == 0):
        # 좌표가 없고 주소가 있으면 카카오 지오코딩으로 자동 변환
        from .services import kakao_geocode
        coords = kakao_geocode(address)
        if not coords and name:
            coords = kakao_geocode(name)
        if coords:
            place.latitude    = coords[0]
            place.longitude   = coords[1]
            place.is_verified = True
            update_fields += ['latitude', 'longitude', 'is_verified']

    if update_fields:
        place.save(update_fields=update_fields)
    return JsonResponse({
        'ok': True,
        'name': place.name,
        'address': place.address,
        'lat': float(place.latitude),
        'lng': float(place.longitude),
        'has_coords': float(place.latitude) != 0 and float(place.longitude) != 0,
    })


def admin_review_view(request, media_id):
    media = get_object_or_404(Media, pk=media_id)

    if request.method == 'POST':
        approved_ids = set(request.POST.getlist('approved'))
        form_pks     = set(request.POST.getlist('form_pks'))
        if not form_pks:
            return redirect('admin_review', media_id=media_id)
        qs = MediaPlace.objects.filter(
            media=media,
            status=MediaPlace.STATUS_INFERRED,
            pk__in=form_pks,
        )
        for mp in qs:
            if str(mp.pk) in approved_ids:
                mp.status = MediaPlace.STATUS_ADMIN_APPROVED
                mp.is_confirmed = True
            else:
                mp.status = MediaPlace.STATUS_REJECTED
            mp.save()
        return redirect('admin_review', media_id=media_id)

    all_inferred = MediaPlace.objects.filter(media=media, status=MediaPlace.STATUS_INFERRED).select_related('place')
    inferred_verified  = [mp for mp in all_inferred if mp.place.is_verified]
    inferred_uncertain = [mp for mp in all_inferred if not mp.place.is_verified]
    approved = MediaPlace.objects.filter(media=media, status=MediaPlace.STATUS_ADMIN_APPROVED).select_related('place')
    rejected = MediaPlace.objects.filter(media=media, status=MediaPlace.STATUS_REJECTED).select_related('place')
    return render(request, 'places/admin_review.html', {
        'media':               media,
        'inferred_verified':   inferred_verified,
        'inferred_uncertain':  inferred_uncertain,
        'approved':            approved,
        'rejected':            rejected,
    })


# ── DRF ViewSets ────────────────────────────────────────────────────────────

class PlaceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/places/                     전체 장소 목록
    GET /api/places/{id}/                장소 상세
    GET /api/places/?keyword=이태원      이름 검색
    GET /api/places/?category=12         관광공사 카테고리 필터
    GET /api/places/?unverified=true     위치 미확정 장소 (퀴즈 대상)
    """
    queryset = Place.objects.all().order_by('-created_at')
    serializer_class = PlaceSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        keyword = self.request.query_params.get('keyword')
        category = self.request.query_params.get('category')
        unverified = self.request.query_params.get('unverified')

        if keyword:
            qs = qs.filter(name__icontains=keyword)
        if category:
            qs = qs.filter(category=category)
        if unverified == 'true':
            qs = qs.filter(is_verified=False)
        tag = self.request.query_params.get('tag')
        if tag:
            qs = qs.filter(tags__name__icontains=tag)
        return qs

    @action(detail=False, methods=['get'], url_path='map')
    def map_data(self, request):
        """
        GET /api/places/map/             전체 촬영지 좌표 + 연결 미디어
        GET /api/places/map/?media_id=1  특정 미디어 촬영지만
        """
        media_id = request.query_params.get('media_id')
        base_filter = dict(
            media_places__status=MediaPlace.STATUS_ADMIN_APPROVED,
        )
        if media_id:
            base_filter['media_places__media_id'] = media_id

        qs = (Place.objects
              .filter(**base_filter)
              .exclude(latitude=0, longitude=0)
              .prefetch_related('media_places__media')
              .distinct())
        serializer = PlaceMapSerializer(qs, many=True)
        return Response(serializer.data)


class MediaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/media/                      전체 미디어 목록
    GET /api/media/{id}/                 미디어 상세 + 촬영지 목록
    GET /api/media/?type=drama           타입 필터 (drama/movie/youtube/etc)
    GET /api/media/{id}/places/          해당 미디어의 촬영지만 조회
    """
    queryset = Media.objects.all().order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return MediaDetailSerializer
        return MediaSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        media_type = self.request.query_params.get('type')
        if media_type:
            qs = qs.filter(media_type=media_type)
        tag = self.request.query_params.get('tag')
        if tag:
            qs = qs.filter(tags__name__icontains=tag)
        return qs

    @action(detail=True, methods=['get'])
    def places(self, request, pk=None):
        media = self.get_object()
        media_places = MediaPlace.objects.filter(media=media).select_related('place')
        return Response(MediaPlaceSerializer(media_places, many=True).data)


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/tags/                   전체 태그 목록
    GET /api/tags/?category=genre    대분류 필터 (media_type / genre / place_type)
    """
    queryset = Tag.objects.all()
    serializer_class = TagSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)
        return qs
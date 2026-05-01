import requests
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Place, Media, MediaPlace
from .serializers import (
    PlaceSerializer, PlaceMapSerializer,
    MediaSerializer, MediaDetailSerializer, MediaPlaceSerializer,
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
        return qs

    @action(detail=False, methods=['get'], url_path='map')
    def map_data(self, request):
        """
        GET /api/places/map/             전체 촬영지 좌표 + 연결 미디어
        GET /api/places/map/?media_id=1  특정 미디어 촬영지만
        """
        qs = Place.objects.prefetch_related('media_places__media').filter(media_places__isnull=False).distinct()
        media_id = request.query_params.get('media_id')
        if media_id:
            qs = qs.filter(media_places__media_id=media_id)
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
        return qs

    @action(detail=True, methods=['get'])
    def places(self, request, pk=None):
        media = self.get_object()
        media_places = MediaPlace.objects.filter(media=media).select_related('place')
        return Response(MediaPlaceSerializer(media_places, many=True).data)
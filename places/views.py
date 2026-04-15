import requests
from django.conf import settings
from django.http import JsonResponse
from .models import Place

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
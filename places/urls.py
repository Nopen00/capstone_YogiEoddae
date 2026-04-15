from django.urls import path
from .views import fetch_and_save_places, get_place_list # get_place_list 추가

urlpatterns = [
    path('fetch/', fetch_and_save_places, name='fetch_places'),
    path('list/', get_place_list, name='place_list'), # 새로운 조회 주소!
]
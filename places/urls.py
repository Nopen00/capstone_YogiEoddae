from django.urls import path
from .views import fetch_and_save_places, get_place_list, place_map_test, demo_view

urlpatterns = [
    path('fetch/', fetch_and_save_places, name='fetch_places'),
    path('list/', get_place_list, name='place_list'),
    path('map-test/', place_map_test, name='map_test'),
    path('demo/', demo_view, name='demo'),
]
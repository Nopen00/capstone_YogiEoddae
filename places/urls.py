from django.urls import path
from .views import (
    fetch_and_save_places, get_place_list, place_map_test, demo_view,
    index_view, admin_media_list_view, admin_extract_view, admin_review_view,
    admin_place_update_view, admin_place_search_view,
    admin_geocode_media_view, admin_revoke_approval_view,
)

urlpatterns = [
    path('fetch/',  fetch_and_save_places, name='fetch_places'),
    path('list/',   get_place_list,        name='place_list'),
    path('map-test/', place_map_test,      name='map_test'),
    path('demo/',   demo_view,             name='demo'),

    # 관리자 포털
    path('extract/',                        admin_extract_view,    name='admin_extract'),
    path('extract/history/',                admin_media_list_view, name='admin_media_list'),
    path('extract/review/<int:media_id>/',  admin_review_view,     name='admin_review'),
    path('place/<int:place_id>/update/',    admin_place_update_view, name='admin_place_update'),
    path('place/search/',                   admin_place_search_view,  name='admin_place_search'),
    path('extract/review/<int:media_id>/geocode/', admin_geocode_media_view,   name='admin_geocode_media'),
    path('mediaplace/<int:mp_id>/revoke/',         admin_revoke_approval_view, name='admin_revoke_approval'),
]

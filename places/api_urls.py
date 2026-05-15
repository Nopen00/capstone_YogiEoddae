from rest_framework.routers import DefaultRouter
from .views import PlaceViewSet, MediaViewSet, TagViewSet

router = DefaultRouter()
router.register(r'places', PlaceViewSet, basename='place')
router.register(r'media', MediaViewSet, basename='media')
router.register(r'tags', TagViewSet, basename='tag')

urlpatterns = router.urls

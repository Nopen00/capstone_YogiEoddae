from rest_framework.routers import DefaultRouter
from .views import PlaceViewSet, MediaViewSet

router = DefaultRouter()
router.register(r'places', PlaceViewSet, basename='place')
router.register(r'media', MediaViewSet, basename='media')

urlpatterns = router.urls

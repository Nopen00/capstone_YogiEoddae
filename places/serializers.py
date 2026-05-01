from rest_framework import serializers
from .models import MediaPlace, Place, Media


class PlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = [
            'id', 'content_id', 'name', 'address',
            'latitude', 'longitude', 'image_url',
            'category', 'is_verified', 'created_at',
        ]


class MediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Media
        fields = ['id', 'title', 'media_type', 'year', 'thumbnail_url', 'description', 'created_at']


class MediaPlaceSerializer(serializers.ModelSerializer):
    place = PlaceSerializer(read_only=True)

    class Meta:
        model = MediaPlace
        fields = ['id', 'place', 'scene_description', 'confidence_score', 'is_confirmed', 'created_at']


class MediaBriefSerializer(serializers.Serializer):
    """지도 마커용 — 장소에 연결된 미디어 요약 정보."""
    media_id = serializers.IntegerField(source='media.id')
    title = serializers.CharField(source='media.title')
    media_type = serializers.CharField(source='media.media_type')
    scene_description = serializers.CharField()
    confidence_score = serializers.FloatField()


class PlaceMapSerializer(serializers.ModelSerializer):
    """지도 마커용 — 좌표 + 연결된 미디어 목록."""
    media = serializers.SerializerMethodField()

    class Meta:
        model = Place
        fields = ['id', 'name', 'address', 'latitude', 'longitude', 'image_url', 'media']

    def get_media(self, obj):
        media_places = obj.media_places.select_related('media').all()
        return MediaBriefSerializer(media_places, many=True).data


class MediaDetailSerializer(serializers.ModelSerializer):
    """미디어 상세 조회 시 촬영지 목록까지 포함."""
    places = serializers.SerializerMethodField()

    class Meta:
        model = Media
        fields = ['id', 'title', 'media_type', 'year', 'thumbnail_url', 'description', 'places', 'created_at']

    def get_places(self, obj):
        media_places = obj.media_places.select_related('place').all()
        return MediaPlaceSerializer(media_places, many=True).data

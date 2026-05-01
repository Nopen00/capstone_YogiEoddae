from django.db import models


class Place(models.Model):
    CONTENT_TYPES = [
        ('12', '관광지'),
        ('14', '문화시설'),
        ('15', '축제공연행사'),
        ('25', '여행코스'),
        ('28', '레포츠'),
        ('32', '숙박'),
        ('38', '쇼핑'),
        ('39', '음식점'),
    ]

    name = models.CharField(max_length=200)
    address = models.CharField(max_length=500)
    latitude = models.DecimalField(max_digits=20, decimal_places=14)
    longitude = models.DecimalField(max_digits=20, decimal_places=14)
    content_id = models.CharField(max_length=50, unique=True)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    # 관광공사 콘텐츠 타입 (12=관광지, 14=문화시설 등)
    category = models.CharField(max_length=5, choices=CONTENT_TYPES, blank=True, default='')
    # KTO 공식 데이터 = True, YouTube 파싱 등 미확정 = False
    is_verified = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Media(models.Model):
    MEDIA_TYPES = [
        ('drama', '드라마'),
        ('movie', '영화'),
        ('youtube', '유튜브'),
        ('etc', '기타'),
    ]

    title = models.CharField(max_length=200)
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPES)
    year = models.IntegerField(null=True, blank=True)
    thumbnail_url = models.URLField(max_length=500, blank=True, null=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'[{self.get_media_type_display()}] {self.title}'


class MediaPlace(models.Model):
    """미디어 작품과 촬영 장소를 연결하는 테이블."""
    media = models.ForeignKey(Media, on_delete=models.CASCADE, related_name='media_places')
    place = models.ForeignKey(Place, on_delete=models.CASCADE, related_name='media_places')
    scene_description = models.TextField(blank=True)  # "주인공이 걷던 골목길"
    # 0.0(미확정) ~ 1.0(확정): 퀴즈 정답이 쌓일수록 올라감
    confidence_score = models.FloatField(default=1.0)
    # 퀴즈를 통해 위치가 최종 확정됐는지 여부
    is_confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('media', 'place')

    def __str__(self):
        return f'{self.media.title} → {self.place.name}'
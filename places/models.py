from django.db import models

class Place(models.Model):
    # 장소 이름 (title)
    name = models.CharField(max_length=200)
    # 도로명 주소 (addr1)
    address = models.CharField(max_length=500)
    # 위도 (mapy) - 소수점이 많으므로 DecimalField 사용
    latitude = models.DecimalField(max_digits=20, decimal_places=14)
    # 경도 (mapx)
    longitude = models.DecimalField(max_digits=20, decimal_places=14)
    # 관광공사 고유 ID (contentid)
    content_id = models.CharField(max_length=50, unique=True)
    # 대표 이미지 URL (firstimage)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    # 등록일
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import QRCodeView, ShortenedURLViewSet

app_name = 'shortener'

router = SimpleRouter()
router.register('urls', ShortenedURLViewSet, basename='url')

urlpatterns = [
    path('qr/<str:short_code>/', QRCodeView.as_view(), name='qr'),
    *router.urls,
]

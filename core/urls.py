from django.urls import path

from .views import HealthView, ReadinessView

app_name = 'core'

urlpatterns = [
    path('health/', HealthView.as_view(), name='health'),
    path('health/ready/', ReadinessView.as_view(), name='ready'),
]

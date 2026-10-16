import django_filters
from django.db.models import Q
from django.utils import timezone

from .models import ShortenedURL


class ShortenedURLFilter(django_filters.FilterSet):
    expired = django_filters.BooleanFilter(method='filter_expired')
    created_after = django_filters.IsoDateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.IsoDateTimeFilter(field_name='created_at', lookup_expr='lte')
    min_clicks = django_filters.NumberFilter(field_name='clicks', lookup_expr='gte')

    class Meta:
        model = ShortenedURL
        fields = ['is_active']

    def filter_expired(self, queryset, name, value):
        expired = Q(expires_at__isnull=False, expires_at__lte=timezone.now())
        return queryset.filter(expired) if value else queryset.exclude(expired)

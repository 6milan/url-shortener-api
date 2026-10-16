from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.negotiation import BaseContentNegotiation
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.idempotency import idempotent

from .analytics import build_stats
from .filters import ShortenedURLFilter
from .models import ClickEvent, ShortenedURL
from .serializers import ShortenedURLSerializer, SummarySerializer, URLStatsSerializer
from .utils import make_qr_png


class ShortenedURLViewSet(viewsets.ModelViewSet):
    serializer_class = ShortenedURLSerializer
    lookup_field = 'short_code'
    lookup_value_regex = '[A-Za-z0-9_-]+'
    filterset_class = ShortenedURLFilter
    search_fields = ['original_url', 'short_code', 'title']
    ordering_fields = ['created_at', 'clicks', 'expires_at']
    ordering = ['-created_at']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):  # schema generation has no user
            return ShortenedURL.objects.none()
        # Users only ever see their own links. Others get a 404, not a 403,
        # so the existence of someone else's link is not revealed.
        return ShortenedURL.objects.filter(user=self.request.user)

    def get_throttles(self):
        throttles = super().get_throttles()  # anon + user rates always apply
        if self.action == 'create':
            self.throttle_scope = 'shorten'  # ...and creating links has its own, stricter rate
            throttles.append(ScopedRateThrottle())
        return throttles

    @extend_schema(
        description=(
            'Create a short link. Send an `Idempotency-Key` header (8-128 characters, '
            'e.g. a UUID) to make retries safe: repeating the request with the same key '
            'returns the original response with `Idempotent-Replayed: true`.'
        ),
        parameters=[
            OpenApiParameter('Idempotency-Key', str, OpenApiParameter.HEADER, required=False),
        ],
    )
    @idempotent
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Same URL submitted again (without a custom code): return the existing link.
        if not data.get('custom_code'):
            existing = ShortenedURL.objects.filter(
                user=request.user,
                original_url=data['original_url'],
                is_active=True,
            ).first()
            if existing:
                return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)

        serializer.save(user=request.user)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @extend_schema(
        parameters=[OpenApiParameter('days', int, description='Period length, 1-365 (default 30)')],
        responses=URLStatsSerializer,
    )
    @action(detail=True, methods=['get'])
    def stats(self, request, short_code=None):
        url = self.get_object()
        try:
            days = int(request.query_params.get('days', 30))
        except ValueError:
            days = 30
        days = max(1, min(days, 365))
        return Response(build_stats(url, days))

    @extend_schema(responses=SummarySerializer)
    @action(detail=False, methods=['get'])
    def summary(self, request):
        links = self.get_queryset()
        data = links.aggregate(
            total_links=Count('id'),
            active_links=Count('id', filter=Q(is_active=True)),
            total_clicks=Coalesce(Sum('clicks'), 0),
        )
        week_ago = timezone.now() - timedelta(days=7)
        data['clicks_last_7_days'] = ClickEvent.objects.filter(
            url__user=request.user, clicked_at__gte=week_ago
        ).count()
        top = links.order_by('-clicks')[:5]
        data['top_links'] = ShortenedURLSerializer(
            top, many=True, context=self.get_serializer_context()
        ).data
        return Response(data)


class IgnoreClientContentNegotiation(BaseContentNegotiation):
    # Always use the first renderer, whatever the Accept header says.
    def select_parser(self, request, parsers):
        return parsers[0]

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


class QRCodeView(APIView):
    # Public on purpose: it only encodes a link that is already public,
    # and <img src=...> tags cannot send an Authorization header.
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'qr'
    content_negotiation_class = IgnoreClientContentNegotiation

    @extend_schema(responses={(200, 'image/png'): bytes})
    def get(self, request, short_code):
        url = get_object_or_404(ShortenedURL, short_code=short_code)
        try:
            box_size = int(request.query_params.get('size', 10))
        except ValueError:
            box_size = 10
        box_size = max(4, min(box_size, 30))
        png = make_qr_png(url.short_url, box_size=box_size)
        response = HttpResponse(png, content_type='image/png')
        response['Cache-Control'] = 'public, max-age=86400'
        return response

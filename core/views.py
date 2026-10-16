import logging

from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class PublicProbeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []  # monitoring must never be rate limited


STATUS_SCHEMA = inline_serializer('Status', {'status': serializers.CharField()})
READY_SCHEMA = inline_serializer(
    'Readiness',
    {
        'status': serializers.CharField(),
        'checks': serializers.DictField(child=serializers.CharField()),
    },
)


class HealthView(PublicProbeView):
    # Liveness: "the process is up". Touches nothing external.
    @extend_schema(responses=STATUS_SCHEMA)
    def get(self, request):
        return Response({'status': 'ok'})


class ReadinessView(PublicProbeView):
    # Readiness: "the process can do useful work". Checks the database and Redis.
    @extend_schema(responses={200: READY_SCHEMA, 503: READY_SCHEMA})
    def get(self, request):
        checks = {}
        try:
            connection.ensure_connection()
            checks['database'] = 'ok'
        except Exception:
            logger.exception('Readiness: database check failed')
            checks['database'] = 'error'
        try:
            cache.set('readiness-probe', '1', timeout=5)
            checks['cache'] = 'ok' if cache.get('readiness-probe') == '1' else 'error'
        except Exception:
            logger.exception('Readiness: cache check failed')
            checks['cache'] = 'error'
        healthy = all(value == 'ok' for value in checks.values())
        return Response(
            {'status': 'ok' if healthy else 'unavailable', 'checks': checks},
            status=200 if healthy else 503,
        )

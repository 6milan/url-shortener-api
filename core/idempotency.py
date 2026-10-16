import functools
import hashlib
import json
import re
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from .models import IdempotencyKey

HEADER = 'Idempotency-Key'
KEY_PATTERN = re.compile(r'^[A-Za-z0-9_.:-]{8,128}$')


def _fingerprint(request):
    # Same key + different request is a client bug; the fingerprint detects it.
    body = json.dumps(request.data, sort_keys=True, default=str, separators=(',', ':'))
    raw = f'{request.method}\n{request.path}\n{body}'
    return hashlib.sha256(raw.encode()).hexdigest()


def _claim(user, key, fingerprint):
    # Try to become the one request that owns this key. The unique constraint
    # makes this race-free: of two simultaneous requests, exactly one INSERT wins.
    try:
        with transaction.atomic():
            record = IdempotencyKey.objects.create(user=user, key=key, fingerprint=fingerprint)
        return record, True
    except IntegrityError:
        return IdempotencyKey.objects.get(user=user, key=key), False


def _take_over_if_stale(record, fingerprint):
    # A request that crashed leaves its key "in progress" forever. After the lock
    # timeout another attempt may take it over. The UPDATE ... WHERE is atomic,
    # so only one competing request can win the takeover.
    cutoff = timezone.now() - timedelta(seconds=settings.IDEMPOTENCY_LOCK_SECONDS)
    taken = IdempotencyKey.objects.filter(
        pk=record.pk, status_code__isnull=True, locked_at__lt=cutoff
    ).update(locked_at=timezone.now(), fingerprint=fingerprint)
    return taken == 1


def _replay(record):
    response = Response(record.response_body, status=record.status_code)
    response['Idempotent-Replayed'] = 'true'
    return response


def idempotent(view_method):
    # Decorator for a DRF view method (typically `create`). Clients opt in by
    # sending an `Idempotency-Key` header. Retrying with the same key never
    # repeats the work: the stored response is returned instead.
    @functools.wraps(view_method)
    def wrapper(self, request, *args, **kwargs):
        key = request.headers.get(HEADER)
        if not key or not request.user.is_authenticated:
            return view_method(self, request, *args, **kwargs)

        if not KEY_PATTERN.fullmatch(key):
            return Response(
                {'detail': f'{HEADER} must be 8-128 characters: letters, digits, _ . : -'},
                status=400,
            )

        fingerprint = _fingerprint(request)
        record, owner = _claim(request.user, key, fingerprint)

        if not owner:
            if record.fingerprint != fingerprint and record.status_code is not None:
                return Response(
                    {'detail': f'This {HEADER} was already used with a different request.'},
                    status=422,
                )
            if record.status_code is not None:
                return _replay(record)
            if not _take_over_if_stale(record, fingerprint):
                response = Response(
                    {'detail': 'A request with this key is still being processed.'}, status=409
                )
                response['Retry-After'] = '1'
                return response
            # We took over a stale lock: fall through and do the work.

        try:
            # The work and the saved response commit together, or not at all.
            with transaction.atomic():
                response = view_method(self, request, *args, **kwargs)
                if 200 <= response.status_code < 300:
                    IdempotencyKey.objects.filter(pk=record.pk).update(
                        status_code=response.status_code,
                        response_body=json.loads(JSONRenderer().render(response.data)),
                    )
                    return response
        except BaseException:
            IdempotencyKey.objects.filter(pk=record.pk, status_code__isnull=True).delete()
            raise

        # Non-2xx: remember nothing, so the client can fix the request and retry.
        IdempotencyKey.objects.filter(pk=record.pk, status_code__isnull=True).delete()
        return response

    return wrapper

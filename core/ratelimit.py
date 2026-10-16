import functools
import time

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

from .network import get_client_ip

PERIODS = {'second': 1, 'minute': 60, 'hour': 3600, 'day': 86400}


def parse_rate(rate):
    # '240/minute' -> (240, 60)
    count, _, period = rate.partition('/')
    return int(count), PERIODS[period.strip()]


def hit(identity, scope, limit, window):
    # Fixed-window counter in the cache. Returns (allowed, seconds_until_reset).
    # cache.add + cache.incr are atomic in Redis, so concurrent requests are
    # counted correctly even across many worker processes.
    now = int(time.time())
    bucket = now // window
    key = f'ratelimit:{scope}:{identity}:{bucket}'
    cache.add(key, 0, timeout=window)
    try:
        count = cache.incr(key)
    except ValueError:  # the key expired between add() and incr()
        cache.set(key, 1, timeout=window)
        count = 1
    if count is None:
        # The cache is unreachable (django-redis returns None when IGNORE_EXCEPTIONS
        # is on). Fail open: a Redis outage must not take the redirects down with it.
        return True, 0
    return count <= limit, window - (now % window)


def rate_limit(scope):
    # Decorator for plain Django views (DRF views use throttle classes instead).
    # Rates live in settings.RATE_LIMITS so they are configured in one place.
    def decorator(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            limit, window = parse_rate(settings.RATE_LIMITS[scope])
            allowed, retry_after = hit(get_client_ip(request) or 'unknown', scope, limit, window)
            if not allowed:
                response = JsonResponse(
                    {'detail': 'Too many requests. Please slow down.'}, status=429
                )
                response['Retry-After'] = str(retry_after)
                return response
            return view(request, *args, **kwargs)

        return wrapper

    return decorator

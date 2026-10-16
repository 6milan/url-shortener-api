from django.conf import settings
from django.core.cache import cache

from .models import ShortenedURL


def redirect_key(short_code):
    return f'redirect:{short_code}'


def get_redirect_target(short_code):
    # The redirect is the hottest path in the product, so we answer it from Redis
    # and only touch the database on a cache miss. Returns None for unknown codes.
    key = redirect_key(short_code)
    target = cache.get(key)
    if target is not None:
        return target

    row = (
        ShortenedURL.objects.filter(short_code=short_code)
        .values('id', 'original_url', 'is_active', 'expires_at')
        .first()
    )
    if row is None:
        return None  # unknown codes are not cached: attackers could fill the cache
    target = {
        'id': row['id'],
        'url': row['original_url'],
        'is_active': row['is_active'],
        'expires_at': row['expires_at'],
    }
    cache.set(key, target, timeout=settings.REDIRECT_CACHE_TTL)
    return target


def invalidate_redirect(short_code):
    cache.delete(redirect_key(short_code))

from urllib.parse import urlparse

from django.http import HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from core.network import get_client_ip
from core.ratelimit import rate_limit

from .cache import get_redirect_target
from .tasks import enqueue_click


@never_cache
@require_http_methods(['GET', 'HEAD'])
@rate_limit('redirect')
def redirect_view(request, short_code):
    target = get_redirect_target(short_code)  # Redis first, database on a miss
    if target is None:
        return JsonResponse({'detail': 'Short link not found.'}, status=404)
    if not target['is_active']:
        return JsonResponse({'detail': 'This link has been disabled.'}, status=410)
    expires_at = target['expires_at']
    if expires_at is not None and timezone.now() >= expires_at:
        return JsonResponse({'detail': 'This link has expired.'}, status=410)

    if request.method == 'GET':  # HEAD requests (health checks, link scanners) are not clicks
        enqueue_click(
            url_id=target['id'],
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:512],
            referrer=(urlparse(request.META.get('HTTP_REFERER', '')).hostname or '')[:255],
        )

    # 302 (temporary), not 301: browsers cache a 301 forever and would skip
    # our server on later visits, so those clicks would never be counted.
    return HttpResponseRedirect(target['url'])

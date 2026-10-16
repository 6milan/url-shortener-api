import ipaddress

from django.conf import settings


def get_client_ip(request):
    # X-Forwarded-For is a list: "client, proxy1, proxy2". Anyone can forge the
    # left-hand entries, so we only trust the entry added by OUR OWN outermost
    # proxy, counting from the right. This mirrors DRF's NUM_PROXIES logic.
    remote = request.META.get('REMOTE_ADDR')
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    num_proxies = settings.NUM_PROXIES
    if num_proxies and forwarded:
        addresses = [part.strip() for part in forwarded.split(',')]
        ip = addresses[-min(num_proxies, len(addresses))]
    else:
        ip = remote
    try:
        return str(ipaddress.ip_address(ip))
    except (ValueError, TypeError):
        return None

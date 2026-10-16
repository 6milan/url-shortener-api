import secrets
import string
from io import BytesIO

import qrcode
from django.conf import settings

from .models import ShortenedURL

ALPHABET = string.ascii_letters + string.digits  # 62 characters


def generate_short_code(length=None):
    # Return a random, unused short code. Uses secrets (not random) so codes are unpredictable.
    length = length or settings.SHORT_CODE_LENGTH
    for _ in range(10):
        code = ''.join(secrets.choice(ALPHABET) for _ in range(length))
        if code.lower() in settings.RESERVED_CODES:
            continue
        if not ShortenedURL.objects.filter(short_code=code).exists():
            return code
    # Extremely unlikely (many collisions in a row): make codes one character longer.
    return generate_short_code(length + 1)


def parse_user_agent(user_agent):
    # Tiny User-Agent classifier. Returns (device_type, browser).
    # In production you might use the `user-agents` package instead.
    ua = (user_agent or '').lower()
    if not ua:
        return 'unknown', ''

    bot_markers = ('bot', 'crawler', 'spider', 'slurp', 'curl', 'wget',
                   'python-requests', 'headless', 'preview')
    if any(marker in ua for marker in bot_markers):
        device = 'bot'
    elif 'ipad' in ua or 'tablet' in ua or ('android' in ua and 'mobile' not in ua):
        device = 'tablet'
    elif 'mobi' in ua or 'iphone' in ua or 'android' in ua:
        device = 'mobile'
    else:
        device = 'desktop'

    # Order matters: Edge and Opera also contain 'chrome', Chrome also contains 'safari'.
    if 'edg/' in ua or 'edge/' in ua:
        browser = 'Edge'
    elif 'opr/' in ua or 'opera' in ua:
        browser = 'Opera'
    elif 'firefox' in ua or 'fxios' in ua:
        browser = 'Firefox'
    elif 'chrome' in ua or 'crios' in ua:
        browser = 'Chrome'
    elif 'safari' in ua:
        browser = 'Safari'
    elif 'msie' in ua or 'trident' in ua:
        browser = 'Internet Explorer'
    else:
        browser = 'Other'
    return device, browser


def make_qr_png(data, box_size=10, border=4):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white')
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()

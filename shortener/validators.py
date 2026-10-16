import re
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError

CUSTOM_CODE_PATTERN = re.compile(r'^[A-Za-z0-9_-]{3,20}$')


def validate_custom_code(value):
    if not CUSTOM_CODE_PATTERN.fullmatch(value):
        raise ValidationError('Use 3-20 characters: letters, numbers, hyphen or underscore.')
    if value.lower() in settings.RESERVED_CODES:
        raise ValidationError('This code is reserved. Please choose another.')


def validate_destination_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https'):
        raise ValidationError('Only http and https URLs can be shortened.')

    host = (parsed.hostname or '').lower()
    if not host:
        raise ValidationError('The URL must contain a valid host name.')

    # Prevent redirect loops: never shorten our own short links.
    own_host = (urlparse(settings.SHORT_URL_BASE).hostname or '').lower()
    if host == own_host:
        raise ValidationError('You cannot shorten a link that points to this service.')

    for blocked in settings.BLOCKED_DOMAINS:
        if host == blocked or host.endswith('.' + blocked):
            raise ValidationError('This domain is not allowed.')

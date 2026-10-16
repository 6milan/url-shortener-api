import re
import secrets

from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


def unique_username(email):
    # Build a valid, unused username from the part of the email before the @.
    base = re.sub(r'[^A-Za-z0-9.@+_-]', '', email.split('@')[0])[:120] or 'user'
    candidate = base
    while User.objects.filter(username__iexact=candidate).exists():
        candidate = f'{base}{secrets.randbelow(100000)}'
    return candidate

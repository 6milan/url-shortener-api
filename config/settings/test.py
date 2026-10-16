"""Used automatically by `manage.py test`: fast, isolated, no Redis needed."""
from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = 'test-secret-key-' + 'x' * 48  # long enough to silence JWT warnings
ALLOWED_HOSTS = ['testserver', 'localhost']

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# Run Celery tasks immediately, in-process, and surface their exceptions.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']  # speed only
SHORT_URL_BASE = 'http://localhost:8000'
BLOCKED_DOMAINS = []
GOOGLE_CLIENT_ID = ''
LOGGING['root']['level'] = 'CRITICAL'  # noqa: F405
LOGGING['loggers']['django.request']['level'] = 'CRITICAL'  # noqa: F405

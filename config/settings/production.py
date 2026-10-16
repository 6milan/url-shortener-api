"""Production. Every required value comes from the environment; nothing is guessed."""
from decouple import Csv, config

from .base import *  # noqa: F403

DEBUG = False

# No defaults: the process refuses to start if these are missing.
SECRET_KEY = config('SECRET_KEY')
ALLOWED_HOSTS = config('ALLOWED_HOSTS', cast=Csv())
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', cast=Csv())
SHORT_URL_BASE = config('SHORT_URL_BASE')

if len(SECRET_KEY) < 50 or SECRET_KEY.startswith('insecure'):
    raise RuntimeError('SECRET_KEY must be a long random string in production.')

ENABLE_API_DOCS = config('ENABLE_API_DOCS', default=False, cast=bool)

# --------------------------------------------------------------- Static files
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')  # noqa: F405
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

# ------------------------------------------------------- HTTPS and cookies
# We assume a TLS-terminating proxy in front of Gunicorn that sets
# X-Forwarded-Proto. Make sure it overwrites that header from clients.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
SECURE_REDIRECT_EXEMPT = [r'^api/health/']  # load balancers probe over plain HTTP
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

# ---------------------------------------------------- Redis failure policy
# If Redis is unreachable, cache calls are skipped (and logged) instead of
# raising. Redirects keep working from the database; throttling "fails open".
CACHES['default']['OPTIONS']['IGNORE_EXCEPTIONS'] = True  # noqa: F405
DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS = True

# ------------------------------------------------------------------ Logging
LOGGING['handlers']['console']['formatter'] = 'json'  # noqa: F405

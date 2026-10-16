"""Settings shared by every environment. Environment modules import * from here."""
from datetime import timedelta
from pathlib import Path

import dj_database_url
from celery.schedules import crontab
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ------------------------------------------------------------------ Core
# Development has a throwaway default; production.py requires a real value.
SECRET_KEY = config('SECRET_KEY', default='insecure-development-key-do-not-use')
DEBUG = True
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    # Local apps
    'core',
    'accounts',
    'shortener',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # must be above CommonMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# --------------------------------------------------------------- Database
# One variable configures any database: sqlite:///db.sqlite3 or
# postgres://user:password@host:5432/dbname
DATABASES = {
    'default': dj_database_url.config(
        env='DATABASE_URL',
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}',
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# ------------------------------------------------------------------ Redis
# One Redis server, three logical databases: 0 = Celery broker, 1 = cache.
REDIS_URL = config('REDIS_URL', default='redis://localhost:6379')

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f'{REDIS_URL}/1',
        'KEY_PREFIX': 'urlshort',
        'TIMEOUT': 300,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'SOCKET_CONNECT_TIMEOUT': 2,
            'SOCKET_TIMEOUT': 2,
            'CONNECTION_POOL_KWARGS': {'max_connections': 50},
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ------------------------------------------------------------ Proxies / IPs
# How many reverse proxies (nginx, a cloud load balancer...) sit between the
# internet and Django. 0 means clients connect directly. DRF's throttles and
# our own get_client_ip() both use it to find the real client address.
NUM_PROXIES = config('NUM_PROXIES', default=0, cast=int)

# ------------------------------------------------------------------ DRF
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
    'DEFAULT_RENDERER_CLASSES': ('rest_framework.renderers.JSONRenderer',),
    'DEFAULT_PARSER_CLASSES': ('rest_framework.parsers.JSONParser',),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_PAGINATION_CLASS': 'shortener.pagination.StandardPagination',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '2000/hour',
        'auth': '10/minute',     # login, register, google, token refresh
        'shorten': '60/hour',    # creating links
        'qr': '300/hour',        # QR images (a dashboard may load many at once)
    },
    'NUM_PROXIES': NUM_PROXIES,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'URL Shortener API',
    'DESCRIPTION': 'A production-style URL shortener built with Django REST Framework.',
    'VERSION': '2.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}
ENABLE_API_DOCS = config('ENABLE_API_DOCS', default=True, cast=bool)

# ------------------------------------------------------------------ CORS
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000,http://127.0.0.1:3000',
    cast=Csv(),
)
# Let the browser read these response headers (CORS hides unlisted ones).
CORS_EXPOSE_HEADERS = ['Retry-After', 'Idempotent-Replayed']
CORS_ALLOW_HEADERS = [
    'accept', 'authorization', 'content-type', 'idempotency-key', 'origin',
    'x-requested-with',
]

# ---------------------------------------------------- Application settings
SHORT_URL_BASE = config('SHORT_URL_BASE', default='http://localhost:8000')
SHORT_CODE_LENGTH = 6

RESERVED_CODES = {
    'api', 'admin', 'static', 'media', 'docs', 'redoc', 'schema', 'auth',
    'login', 'logout', 'register', 'signup', 'dashboard', 'stats', 'qr',
    'urls', 'summary', 'health', 'ready', 'my-urls', 'settings', 'profile', 'about',
}
BLOCKED_DOMAINS = [d.lower() for d in config('BLOCKED_DOMAINS', default='', cast=Csv())]
GOOGLE_CLIENT_ID = config('GOOGLE_CLIENT_ID', default='')

# Rate limit for the public redirect endpoint, per client IP ("count/period").
RATE_LIMITS = {'redirect': config('REDIRECT_RATE_LIMIT', default='240/minute')}

# Redirect lookups are cached in Redis for this many seconds.
REDIRECT_CACHE_TTL = config('REDIRECT_CACHE_TTL', default=3600, cast=int)

# Idempotency keys are remembered for 24 hours; an unfinished request holds
# its key for at most 60 seconds before another attempt may take over.
IDEMPOTENCY_TTL_HOURS = 24
IDEMPOTENCY_LOCK_SECONDS = 60

# Privacy: IP addresses of click events are erased after this many days.
CLICK_IP_RETENTION_DAYS = config('CLICK_IP_RETENTION_DAYS', default=30, cast=int)

# ----------------------------------------------------------------- Celery
CELERY_BROKER_URL = f'{REDIS_URL}/0'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_IGNORE_RESULT = True          # we never read task results
CELERY_TASK_ACKS_LATE = True              # re-deliver if a worker dies mid-task
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_SOFT_TIME_LIMIT = 30
CELERY_TASK_TIME_LIMIT = 60
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'visibility_timeout': 3600,
    'socket_connect_timeout': 2,
}
# If Redis is down, fail fast when publishing so a click never blocks a redirect.
CELERY_TASK_PUBLISH_RETRY_POLICY = {'max_retries': 1, 'interval_start': 0, 'interval_step': 0.2}
CELERY_BEAT_SCHEDULE = {
    'purge-idempotency-keys': {
        'task': 'core.tasks.purge_idempotency_keys',
        'schedule': crontab(minute=15),
    },
    'anonymize-old-click-data': {
        'task': 'shortener.tasks.anonymize_old_clicks',
        'schedule': crontab(hour=3, minute=30),
    },
}

# Record clicks in a Celery worker (True) or inline in the request (False).
CLICK_RECORDING_ASYNC = config('CLICK_RECORDING_ASYNC', default=True, cast=bool)

# ---------------------------------------------------------------- Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'},
        'json': {'()': 'core.logging.JsonFormatter'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'root': {'handlers': ['console'], 'level': config('LOG_LEVEL', default='INFO')},
    'loggers': {
        'django.request': {'level': 'WARNING'},
    },
}

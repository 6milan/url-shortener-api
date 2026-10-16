import os

from celery import Celery

# Production is the safe default: forgetting to set the variable fails loudly
# (missing SECRET_KEY) instead of silently running with DEBUG on.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')

app = Celery('config')
# Every setting that starts with CELERY_ in Django settings configures Celery.
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

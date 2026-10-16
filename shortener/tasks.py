import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.conf import settings
from django.db import OperationalError, transaction
from django.db.models import F
from django.utils import timezone

from .models import ClickEvent, ShortenedURL
from .utils import parse_user_agent

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    ignore_result=True,
    autoretry_for=(OperationalError,),  # deadlocks, dropped connections...
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=5,
)
def record_click(self, url_id, clicked_at, ip_address, user_agent, referrer):
    # Arguments are plain JSON types because they travel through Redis.
    device_type, browser = parse_user_agent(user_agent)
    with transaction.atomic():
        # One atomic UPDATE ... SET clicks = clicks + 1: no lost updates.
        updated = ShortenedURL.objects.filter(pk=url_id).update(clicks=F('clicks') + 1)
        if not updated:
            return  # the link was deleted while the task waited in the queue
        ClickEvent.objects.create(
            url_id=url_id,
            clicked_at=datetime.fromisoformat(clicked_at),
            ip_address=ip_address,
            user_agent=user_agent,
            referrer=referrer,
            device_type=device_type,
            browser=browser,
        )


def enqueue_click(url_id, ip_address, user_agent, referrer):
    # Send the click to a worker. If the broker is down, record it inline so no
    # click is lost; one slow redirect is better than a missing statistic.
    payload = {
        'url_id': url_id,
        'clicked_at': timezone.now().isoformat(),
        'ip_address': ip_address,
        'user_agent': user_agent,
        'referrer': referrer,
    }
    if settings.CLICK_RECORDING_ASYNC:
        try:
            record_click.delay(**payload)
            return
        except Exception:
            logger.warning('Celery broker unavailable, recording click inline', exc_info=True)
    record_click.apply(kwargs=payload, throw=True)


@shared_task(ignore_result=True)
def anonymize_old_clicks():
    # GDPR-style retention: keep the statistics, erase the personal data.
    cutoff = timezone.now() - timedelta(days=settings.CLICK_IP_RETENTION_DAYS)
    return ClickEvent.objects.filter(clicked_at__lt=cutoff).exclude(
        ip_address=None, user_agent=''
    ).update(ip_address=None, user_agent='')

from django.conf import settings
from django.db import models
from django.utils import timezone


class ShortenedURL(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='shortened_urls',
    )
    original_url = models.URLField(max_length=2048)
    # unique=True already creates a database index, so db_index=True is redundant.
    short_code = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=200, blank=True)
    clicks = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', '-created_at'])]

    def __str__(self):
        return f'{self.short_code} -> {self.original_url}'

    @property
    def is_expired(self):
        return self.expires_at is not None and timezone.now() >= self.expires_at

    @property
    def short_url(self):
        base = settings.SHORT_URL_BASE.rstrip('/')
        return f'{base}/{self.short_code}'


class ClickEvent(models.Model):
    class DeviceType(models.TextChoices):
        DESKTOP = 'desktop', 'Desktop'
        MOBILE = 'mobile', 'Mobile'
        TABLET = 'tablet', 'Tablet'
        BOT = 'bot', 'Bot'
        UNKNOWN = 'unknown', 'Unknown'

    url = models.ForeignKey(
        ShortenedURL,
        on_delete=models.CASCADE,
        related_name='click_events',
    )
    # default= (not auto_now_add) so a Celery worker can record WHEN the click
    # happened, even if it processes the event a few seconds later.
    clicked_at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    referrer = models.CharField(max_length=255, blank=True)  # hostname only
    device_type = models.CharField(
        max_length=10,
        choices=DeviceType.choices,
        default=DeviceType.UNKNOWN,
    )
    browser = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ['-clicked_at']
        indexes = [
            models.Index(fields=['url', '-clicked_at']),
            models.Index(fields=['clicked_at']),  # retention jobs scan by age
        ]

    def __str__(self):
        return f'{self.url.short_code} @ {self.clicked_at:%Y-%m-%d %H:%M}'

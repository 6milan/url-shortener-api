from django.conf import settings
from django.db import models
from django.utils import timezone


class IdempotencyKey(models.Model):
    # One row per (user, Idempotency-Key header). While the request is running
    # status_code is NULL ("in progress"); when it succeeds we store the response
    # so that retries can be answered without doing the work again.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='idempotency_keys',
    )
    key = models.CharField(max_length=128)
    fingerprint = models.CharField(max_length=64)  # SHA-256 of method + path + body
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    locked_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'key'], name='unique_idempotency_key_per_user'),
        ]

    def __str__(self):
        return f'{self.user_id}:{self.key} ({self.status_code or "in progress"})'

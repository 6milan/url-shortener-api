from django.conf import settings
from django.db import models


class GoogleAccount(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='google_account',
    )
    sub = models.CharField(max_length=255, unique=True)  # Google's permanent user id
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user} <-> google:{self.sub}'

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import invalidate_redirect
from .models import ShortenedURL


@receiver(post_save, sender=ShortenedURL)
@receiver(post_delete, sender=ShortenedURL)
def drop_cached_redirect(sender, instance, **kwargs):
    # Whenever a link is edited or deleted, forget the cached copy so that a
    # disabled link stops redirecting immediately instead of after the TTL.
    invalidate_redirect(instance.short_code)

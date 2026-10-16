from django.contrib import admin

from .models import ClickEvent, ShortenedURL


@admin.register(ShortenedURL)
class ShortenedURLAdmin(admin.ModelAdmin):
    list_display = (
        'short_code', 'original_url', 'user', 'clicks', 'is_active', 'expires_at', 'created_at',
    )
    list_filter = ('is_active', 'created_at')
    search_fields = ('short_code', 'original_url', 'user__username')
    readonly_fields = ('clicks', 'created_at', 'updated_at')
    raw_id_fields = ('user',)


@admin.register(ClickEvent)
class ClickEventAdmin(admin.ModelAdmin):
    list_display = ('url', 'clicked_at', 'device_type', 'browser', 'referrer')
    list_filter = ('device_type', 'browser')
    date_hierarchy = 'clicked_at'
    raw_id_fields = ('url',)

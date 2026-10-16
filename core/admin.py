from django.contrib import admin

from .models import IdempotencyKey


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ('key', 'user', 'status_code', 'created_at')
    list_filter = ('status_code',)
    search_fields = ('key', 'user__username')
    raw_id_fields = ('user',)
    readonly_fields = ('fingerprint', 'response_body', 'locked_at', 'created_at')

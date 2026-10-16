from django.contrib import admin

from .models import GoogleAccount


@admin.register(GoogleAccount)
class GoogleAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'sub', 'created_at')
    search_fields = ('user__username', 'user__email', 'sub')
    raw_id_fields = ('user',)

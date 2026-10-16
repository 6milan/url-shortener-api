from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers

from .models import ClickEvent, ShortenedURL
from .utils import generate_short_code
from .validators import validate_custom_code as custom_code_validator
from .validators import validate_destination_url as destination_url_validator


class ShortenedURLSerializer(serializers.ModelSerializer):
    original_url = serializers.URLField(
        max_length=2048,
        validators=[destination_url_validator],
    )
    # Write-only: accepted when creating, never returned (the result is short_code).
    custom_code = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=20,
        validators=[custom_code_validator],
    )
    short_url = serializers.CharField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = ShortenedURL
        fields = [
            'id', 'original_url', 'short_code', 'short_url', 'custom_code',
            'title', 'clicks', 'is_active', 'is_expired', 'expires_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'short_code', 'clicks', 'created_at', 'updated_at']

    def validate_custom_code(self, value):
        if value and ShortenedURL.objects.filter(short_code=value).exists():
            raise serializers.ValidationError('This code is already taken.')
        return value

    def validate_expires_at(self, value):
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError('The expiry date must be in the future.')
        return value

    def validate(self, attrs):
        # A short code is part of a published link, so it can never change.
        if self.instance is not None and attrs.get('custom_code'):
            raise serializers.ValidationError(
                {'custom_code': 'The short code cannot be changed after creation.'}
            )
        return attrs

    def create(self, validated_data):
        # validated_data also contains `user`, passed by the view via serializer.save(user=...)
        custom_code = validated_data.pop('custom_code', '')

        if custom_code:
            try:
                with transaction.atomic():
                    return ShortenedURL.objects.create(short_code=custom_code, **validated_data)
            except IntegrityError:  # someone grabbed it a millisecond ago
                raise serializers.ValidationError({'custom_code': 'This code is already taken.'})

        # Random code. Two requests can generate the same code at the same moment;
        # the unique constraint catches that and we simply try again.
        for _ in range(5):
            try:
                with transaction.atomic():
                    return ShortenedURL.objects.create(
                        short_code=generate_short_code(), **validated_data
                    )
            except IntegrityError:
                continue
        raise serializers.ValidationError('Could not generate a unique code. Please try again.')


class ClickEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClickEvent
        fields = ['id', 'clicked_at', 'device_type', 'browser', 'referrer']


# ---- Plain serializers used to DOCUMENT response shapes in the OpenAPI schema ----

class DailyClicksSerializer(serializers.Serializer):
    date = serializers.DateField()
    clicks = serializers.IntegerField()


class BreakdownItemSerializer(serializers.Serializer):
    name = serializers.CharField()
    count = serializers.IntegerField()


class URLStatsSerializer(serializers.Serializer):
    short_code = serializers.CharField()
    short_url = serializers.CharField()
    original_url = serializers.URLField()
    created_at = serializers.DateTimeField()
    total_clicks = serializers.IntegerField()
    period_days = serializers.IntegerField()
    clicks_in_period = serializers.IntegerField()
    clicks_by_day = DailyClicksSerializer(many=True)
    devices = BreakdownItemSerializer(many=True)
    browsers = BreakdownItemSerializer(many=True)
    referrers = BreakdownItemSerializer(many=True)
    recent_clicks = ClickEventSerializer(many=True)


class SummarySerializer(serializers.Serializer):
    total_links = serializers.IntegerField()
    active_links = serializers.IntegerField()
    total_clicks = serializers.IntegerField()
    clicks_last_7_days = serializers.IntegerField()
    top_links = ShortenedURLSerializer(many=True)

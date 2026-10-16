from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from .serializers import ClickEventSerializer


def clicks_by_day(events, start, days):
    # One entry per day, including days with zero clicks, so charts have no gaps.
    rows = (
        events.annotate(day=TruncDate('clicked_at'))
        .values('day')
        .annotate(total=Count('id'))
        .order_by('day')
    )
    counts = {row['day']: row['total'] for row in rows}
    result = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        result.append({'date': day.isoformat(), 'clicks': counts.get(day, 0)})
    return result


def breakdown(events, field, limit=10, empty_label='Unknown'):
    rows = (
        events.order_by()  # drop the default ordering so GROUP BY stays on `field`
        .values(field)
        .annotate(total=Count('id'))
        .order_by('-total')[:limit]
    )
    return [{'name': row[field] or empty_label, 'count': row['total']} for row in rows]


def build_stats(url, days=30):
    start = timezone.localdate() - timedelta(days=days - 1)
    all_events = url.click_events.all()
    period = all_events.filter(clicked_at__date__gte=start)
    return {
        'short_code': url.short_code,
        'short_url': url.short_url,
        'original_url': url.original_url,
        'created_at': url.created_at,
        'total_clicks': url.clicks,
        'period_days': days,
        'clicks_in_period': period.count(),
        'clicks_by_day': clicks_by_day(period, start, days),
        'devices': breakdown(period, 'device_type'),
        'browsers': breakdown(period, 'browser'),
        'referrers': breakdown(period, 'referrer', empty_label='Direct'),
        'recent_clicks': ClickEventSerializer(all_events[:10], many=True).data,
    }

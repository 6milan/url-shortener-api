from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .cache import redirect_key
from .models import ClickEvent, ShortenedURL
from .tasks import anonymize_old_clicks, record_click
from .utils import generate_short_code, parse_user_agent

User = get_user_model()
PASSWORD = 'Str0ng-Pass-123!'

CHROME_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)
EDGE_UA = CHROME_UA + ' Edg/120.0.0.0'
IPHONE_UA = (
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
    '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
)
BOT_UA = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'


def make_url(user, code='abc123', url='https://example.com/page', **extra):
    return ShortenedURL.objects.create(user=user, short_code=code, original_url=url, **extra)


class ShortURLCrudTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user('alice', 'alice@example.com', PASSWORD)
        self.bob = User.objects.create_user('bob', 'bob@example.com', PASSWORD)
        self.client.force_authenticate(self.alice)
        self.list_url = reverse('shortener:url-list')

    def detail(self, code):
        return reverse('shortener:url-detail', kwargs={'short_code': code})

    def create(self, **data):
        return self.client.post(self.list_url, data, format='json')

    # ---- create -----------------------------------------------------------
    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_short_url(self):
        res = self.create(original_url='https://example.com/a/very/long/path')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        code = res.data['short_code']
        self.assertEqual(len(code), 6)
        self.assertEqual(res.data['short_url'], f'http://localhost:8000/{code}')
        self.assertEqual(res.data['clicks'], 0)
        self.assertNotIn('custom_code', res.data)
        self.assertEqual(ShortenedURL.objects.get(short_code=code).user, self.alice)

    def test_same_url_returns_the_existing_link(self):
        first = self.create(original_url='https://example.com/x')
        second = self.create(original_url='https://example.com/x')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data['short_code'], second.data['short_code'])
        self.assertEqual(ShortenedURL.objects.count(), 1)

    def test_custom_code(self):
        res = self.create(original_url='https://example.com', custom_code='my-link')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['short_code'], 'my-link')

    def test_custom_code_already_taken(self):
        make_url(self.bob, 'taken1')
        res = self.create(original_url='https://example.com', custom_code='taken1')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('custom_code', res.data)

    def test_custom_code_validation(self):
        for bad in ('admin', 'ready', 'ab', 'bad code!', 'x' * 21):
            res = self.create(original_url='https://example.com', custom_code=bad)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, bad)
            self.assertIn('custom_code', res.data)

    def test_only_http_and_https_are_allowed(self):
        for bad in ('ftp://example.com/file', 'javascript:alert(1)', 'not a url'):
            res = self.create(original_url=bad)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, bad)
            self.assertIn('original_url', res.data)

    def test_cannot_shorten_our_own_links(self):
        res = self.create(original_url='http://localhost:8000/abc123')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(BLOCKED_DOMAINS=['spam.com'])
    def test_blocked_domains(self):
        for url in ('https://spam.com/x', 'https://sub.spam.com/x'):
            res = self.create(original_url=url)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, url)

    def test_expiry_must_be_in_the_future(self):
        past = (timezone.now() - timedelta(days=1)).isoformat()
        res = self.create(original_url='https://example.com', expires_at=past)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        future = (timezone.now() + timedelta(days=1)).isoformat()
        res = self.create(original_url='https://example.com', expires_at=future)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertFalse(res.data['is_expired'])

    def test_creating_links_is_throttled(self):
        statuses = [
            self.create(original_url=f'https://example.com/{i}').status_code for i in range(61)
        ]
        self.assertEqual(statuses[:60], [201] * 60)
        self.assertEqual(statuses[60], status.HTTP_429_TOO_MANY_REQUESTS)

    # ---- read / update / delete --------------------------------------------
    def test_list_only_returns_my_links(self):
        make_url(self.alice, 'aaa111')
        make_url(self.bob, 'bbb222')
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['short_code'], 'aaa111')

    def test_other_users_links_are_hidden(self):
        make_url(self.bob, 'bbb222')
        self.assertEqual(self.client.get(self.detail('bbb222')).status_code, 404)
        patch_res = self.client.patch(self.detail('bbb222'), {'title': 'x'}, format='json')
        self.assertEqual(patch_res.status_code, 404)
        self.assertEqual(self.client.delete(self.detail('bbb222')).status_code, 404)
        self.assertTrue(ShortenedURL.objects.filter(short_code='bbb222').exists())

    def test_patch_link(self):
        link = make_url(self.alice)
        res = self.client.patch(
            self.detail('abc123'), {'is_active': False, 'title': 'Docs'}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        link.refresh_from_db()
        self.assertFalse(link.is_active)
        self.assertEqual(link.title, 'Docs')

    def test_short_code_cannot_be_changed(self):
        make_url(self.alice)
        res = self.client.patch(self.detail('abc123'), {'custom_code': 'newcode'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(ShortenedURL.objects.filter(short_code='abc123').exists())

    def test_delete_link(self):
        make_url(self.alice)
        res = self.client.delete(self.detail('abc123'))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ShortenedURL.objects.filter(short_code='abc123').exists())

    def test_search_and_filters(self):
        make_url(self.alice, 'py0001', 'https://python.org')
        make_url(self.alice, 'dj0001', 'https://djangoproject.com')
        make_url(
            self.alice, 'old001', 'https://old.example.com',
            expires_at=timezone.now() - timedelta(days=1),
        )

        res = self.client.get(self.list_url, {'search': 'django'})
        self.assertEqual(res.data['count'], 1)

        res = self.client.get(self.list_url, {'expired': 'true'})
        self.assertEqual([r['short_code'] for r in res.data['results']], ['old001'])

        res = self.client.get(self.list_url, {'expired': 'false'})
        self.assertEqual(res.data['count'], 2)

    def test_ordering_and_pagination(self):
        for index in range(12):
            make_url(self.alice, f'code{index:03d}', f'https://example.com/{index}', clicks=index)
        res = self.client.get(self.list_url, {'ordering': '-clicks', 'page_size': 5})
        self.assertEqual(res.data['count'], 12)
        self.assertEqual(len(res.data['results']), 5)
        self.assertEqual(res.data['results'][0]['clicks'], 11)
        self.assertIsNotNone(res.data['next'])


class RedirectTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user('alice', 'alice@example.com', PASSWORD)
        self.link = make_url(self.alice)

    def test_redirects_and_records_the_click(self):
        res = self.client.get(
            '/abc123/',
            HTTP_USER_AGENT=IPHONE_UA,
            HTTP_REFERER='https://twitter.com/some/post',
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res['Location'], 'https://example.com/page')
        self.link.refresh_from_db()
        self.assertEqual(self.link.clicks, 1)
        event = ClickEvent.objects.get()
        self.assertEqual(event.device_type, 'mobile')
        self.assertEqual(event.browser, 'Safari')
        self.assertEqual(event.referrer, 'twitter.com')
        self.assertEqual(event.ip_address, '127.0.0.1')

    def test_works_without_trailing_slash(self):
        self.assertEqual(self.client.get('/abc123').status_code, 302)

    def test_head_requests_are_not_counted(self):
        res = self.client.head('/abc123/')
        self.assertEqual(res.status_code, 302)
        self.link.refresh_from_db()
        self.assertEqual(self.link.clicks, 0)

    def test_unknown_code(self):
        res = self.client.get('/nope99/')
        self.assertEqual(res.status_code, 404)

    def test_expired_link_is_gone(self):
        ShortenedURL.objects.filter(pk=self.link.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        res = self.client.get('/abc123/')
        self.assertEqual(res.status_code, 410)
        self.assertEqual(ClickEvent.objects.count(), 0)

    def test_disabled_link_is_gone(self):
        ShortenedURL.objects.filter(pk=self.link.pk).update(is_active=False)
        self.assertEqual(self.client.get('/abc123/').status_code, 410)

    def test_link_that_expires_while_cached_stops_redirecting(self):
        self.link.expires_at = timezone.now() + timedelta(seconds=1)
        self.link.save()
        self.assertEqual(self.client.get('/abc123/').status_code, 302)  # now cached
        later = timezone.now() + timedelta(minutes=1)
        with patch('shortener.redirect.timezone.now', return_value=later):
            self.assertEqual(self.client.get('/abc123/').status_code, 410)


class RedirectCacheTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user('alice', 'alice@example.com', PASSWORD)
        self.link = make_url(self.alice)

    def test_first_redirect_fills_the_cache(self):
        self.assertIsNone(cache.get(redirect_key('abc123')))
        self.client.get('/abc123/')
        self.assertEqual(cache.get(redirect_key('abc123'))['url'], 'https://example.com/page')

    def test_unknown_codes_are_not_cached(self):
        self.client.get('/nope99/')
        self.assertIsNone(cache.get(redirect_key('nope99')))

    def test_disabling_a_link_takes_effect_immediately(self):
        self.client.get('/abc123/')  # warms the cache
        self.client.force_authenticate(self.alice)
        url = reverse('shortener:url-detail', kwargs={'short_code': 'abc123'})
        self.client.patch(url, {'is_active': False}, format='json')
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/abc123/').status_code, 410)

    def test_deleting_a_link_clears_the_cache(self):
        self.client.get('/abc123/')
        self.link.delete()
        self.assertEqual(self.client.get('/abc123/').status_code, 404)


class ClickRecordingTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user('alice', 'alice@example.com', PASSWORD)
        self.link = make_url(self.alice)

    def test_broker_outage_falls_back_to_inline_recording(self):
        with patch('shortener.tasks.record_click.delay', side_effect=ConnectionError('redis down')):
            res = self.client.get('/abc123/')
        self.assertEqual(res.status_code, 302)
        self.link.refresh_from_db()
        self.assertEqual(self.link.clicks, 1)
        self.assertEqual(ClickEvent.objects.count(), 1)

    @override_settings(CLICK_RECORDING_ASYNC=False)
    def test_inline_mode_never_touches_the_broker(self):
        with patch('shortener.tasks.record_click.delay') as delay:
            self.client.get('/abc123/')
        delay.assert_not_called()
        self.link.refresh_from_db()
        self.assertEqual(self.link.clicks, 1)

    def test_task_keeps_the_original_click_time(self):
        when = (timezone.now() - timedelta(minutes=5)).isoformat()
        record_click.apply(kwargs={
            'url_id': self.link.pk, 'clicked_at': when, 'ip_address': '1.2.3.4',
            'user_agent': CHROME_UA, 'referrer': '',
        })
        event = ClickEvent.objects.get()
        self.assertEqual(event.clicked_at.isoformat(), when)

    def test_task_ignores_a_deleted_link(self):
        record_click.apply(kwargs={
            'url_id': 999999, 'clicked_at': timezone.now().isoformat(), 'ip_address': None,
            'user_agent': '', 'referrer': '',
        })
        self.assertEqual(ClickEvent.objects.count(), 0)

    @override_settings(CLICK_IP_RETENTION_DAYS=30)
    def test_old_clicks_lose_their_personal_data(self):
        old = ClickEvent.objects.create(
            url=self.link, ip_address='1.2.3.4', user_agent=CHROME_UA,
            clicked_at=timezone.now() - timedelta(days=45),
        )
        fresh = ClickEvent.objects.create(url=self.link, ip_address='5.6.7.8', user_agent=CHROME_UA)
        anonymize_old_clicks.apply()
        old.refresh_from_db()
        fresh.refresh_from_db()
        self.assertIsNone(old.ip_address)
        self.assertEqual(old.user_agent, '')
        self.assertEqual(fresh.ip_address, '5.6.7.8')


class RedirectRateLimitTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user('alice', 'alice@example.com', PASSWORD)
        make_url(self.alice)

    @override_settings(RATE_LIMITS={'redirect': '3/minute'})
    def test_the_fourth_request_in_a_minute_is_refused(self):
        codes = [self.client.get('/abc123/').status_code for _ in range(3)]
        self.assertEqual(codes, [302, 302, 302])
        res = self.client.get('/abc123/')
        self.assertEqual(res.status_code, 429)
        self.assertTrue(1 <= int(res['Retry-After']) <= 60)
        self.assertEqual(ClickEvent.objects.count(), 3)  # refused requests are not clicks

    @override_settings(RATE_LIMITS={'redirect': '1/minute'})
    def test_each_client_ip_has_its_own_budget(self):
        self.assertEqual(self.client.get('/abc123/', REMOTE_ADDR='10.0.0.1').status_code, 302)
        self.assertEqual(self.client.get('/abc123/', REMOTE_ADDR='10.0.0.1').status_code, 429)
        self.assertEqual(self.client.get('/abc123/', REMOTE_ADDR='10.0.0.2').status_code, 302)

    @override_settings(RATE_LIMITS={'redirect': '1/minute'}, NUM_PROXIES=0)
    def test_forged_forwarded_headers_cannot_dodge_the_limit(self):
        first = self.client.get('/abc123/', HTTP_X_FORWARDED_FOR='9.9.9.1')
        second = self.client.get('/abc123/', HTTP_X_FORWARDED_FOR='9.9.9.2')
        self.assertEqual((first.status_code, second.status_code), (302, 429))

    @override_settings(RATE_LIMITS={'redirect': '1/minute'}, NUM_PROXIES=1)
    def test_behind_one_proxy_the_proxy_added_address_is_used(self):
        # "forged, real": the left entry is client-controlled, the right one is ours.
        a = self.client.get('/abc123/', HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.5')
        b = self.client.get('/abc123/', HTTP_X_FORWARDED_FOR='7.7.7.7, 203.0.113.5')
        c = self.client.get('/abc123/', HTTP_X_FORWARDED_FOR='7.7.7.7, 203.0.113.9')
        self.assertEqual((a.status_code, b.status_code, c.status_code), (302, 429, 302))


class StatsTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user('alice', 'alice@example.com', PASSWORD)
        self.bob = User.objects.create_user('bob', 'bob@example.com', PASSWORD)
        self.link = make_url(self.alice)
        self.client.get('/abc123/', HTTP_USER_AGENT=CHROME_UA)
        self.client.get(
            '/abc123/', HTTP_USER_AGENT=CHROME_UA, HTTP_REFERER='https://news.ycombinator.com/'
        )
        self.client.get('/abc123/', HTTP_USER_AGENT=IPHONE_UA)
        self.url = reverse('shortener:url-stats', kwargs={'short_code': 'abc123'})

    def test_stats_for_the_owner(self):
        self.client.force_authenticate(self.alice)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['total_clicks'], 3)
        self.assertEqual(res.data['clicks_in_period'], 3)
        self.assertEqual(len(res.data['clicks_by_day']), 30)
        self.assertEqual(res.data['clicks_by_day'][-1]['clicks'], 3)
        devices = {item['name']: item['count'] for item in res.data['devices']}
        self.assertEqual(devices, {'desktop': 2, 'mobile': 1})
        referrers = {item['name']: item['count'] for item in res.data['referrers']}
        self.assertEqual(referrers['news.ycombinator.com'], 1)
        self.assertEqual(referrers['Direct'], 2)
        self.assertEqual(len(res.data['recent_clicks']), 3)

    def test_days_parameter(self):
        self.client.force_authenticate(self.alice)
        res = self.client.get(self.url, {'days': 7})
        self.assertEqual(len(res.data['clicks_by_day']), 7)

    def test_stats_of_someone_elses_link_are_hidden(self):
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_stats_require_authentication(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)


class SummaryAndQRTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user('alice', 'alice@example.com', PASSWORD)
        self.bob = User.objects.create_user('bob', 'bob@example.com', PASSWORD)

    def test_summary(self):
        make_url(self.alice, 'top001', clicks=5)
        make_url(self.alice, 'low001', 'https://example.org', clicks=3)
        make_url(self.bob, 'bob001', 'https://example.net', clicks=100)
        self.client.force_authenticate(self.alice)
        res = self.client.get(reverse('shortener:url-summary'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['total_links'], 2)
        self.assertEqual(res.data['active_links'], 2)
        self.assertEqual(res.data['total_clicks'], 8)
        self.assertEqual(res.data['top_links'][0]['short_code'], 'top001')

    def test_summary_for_a_new_user_is_zero(self):
        self.client.force_authenticate(self.bob)
        res = self.client.get(reverse('shortener:url-summary'))
        self.assertEqual(res.data['total_clicks'], 0)
        self.assertEqual(res.data['top_links'], [])

    def test_qr_code_is_public_and_returns_a_png(self):
        make_url(self.alice)
        res = self.client.get(reverse('shortener:qr', kwargs={'short_code': 'abc123'}))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'image/png')
        self.assertEqual(res.content[1:4], b'PNG')

    def test_qr_code_for_unknown_code(self):
        res = self.client.get(reverse('shortener:qr', kwargs={'short_code': 'nope99'}))
        self.assertEqual(res.status_code, 404)


class UtilsTests(TestCase):
    def test_generated_code_shape(self):
        code = generate_short_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isalnum())

    def test_generated_codes_are_unique(self):
        codes = {generate_short_code() for _ in range(200)}
        self.assertEqual(len(codes), 200)

    def test_user_agent_parsing(self):
        self.assertEqual(parse_user_agent(CHROME_UA), ('desktop', 'Chrome'))
        self.assertEqual(parse_user_agent(EDGE_UA), ('desktop', 'Edge'))
        self.assertEqual(parse_user_agent(IPHONE_UA), ('mobile', 'Safari'))
        self.assertEqual(parse_user_agent(BOT_UA)[0], 'bot')
        self.assertEqual(parse_user_agent(''), ('unknown', ''))

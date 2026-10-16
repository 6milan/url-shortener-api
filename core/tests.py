from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from shortener.models import ShortenedURL

from .models import IdempotencyKey
from .network import get_client_ip
from .ratelimit import hit, parse_rate
from .tasks import purge_idempotency_keys

User = get_user_model()
PASSWORD = 'Str0ng-Pass-123!'
KEY = 'a1b2c3d4-0000-4000-8000-000000000001'


class IdempotencyTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user('alice', 'alice@example.com', PASSWORD)
        self.bob = User.objects.create_user('bob', 'bob@example.com', PASSWORD)
        self.client.force_authenticate(self.alice)
        self.url = reverse('shortener:url-list')

    def post(self, key=KEY, **data):
        data = data or {'original_url': 'https://example.com/pay'}
        extra = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
        return self.client.post(self.url, data, format='json', **extra)

    def test_retry_with_the_same_key_replays_the_first_response(self):
        first = self.post()
        retry = self.post()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 201)  # the original status, not 200
        self.assertEqual(retry.data, first.data)
        self.assertEqual(retry['Idempotent-Replayed'], 'true')
        self.assertNotIn('Idempotent-Replayed', first)
        self.assertEqual(ShortenedURL.objects.count(), 1)

    def test_different_keys_are_independent_requests(self):
        self.post(KEY, original_url='https://example.com/a')
        self.post('another-key-0001', original_url='https://example.com/b')
        self.assertEqual(ShortenedURL.objects.count(), 2)

    def test_the_same_key_with_a_different_body_is_rejected(self):
        self.post(original_url='https://example.com/one')
        res = self.post(original_url='https://example.com/two')
        self.assertEqual(res.status_code, 422)
        self.assertEqual(ShortenedURL.objects.count(), 1)

    def test_key_order_inside_the_body_does_not_matter(self):
        self.post(original_url='https://example.com/x', title='T')
        res = self.post(title='T', original_url='https://example.com/x')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res['Idempotent-Replayed'], 'true')

    def test_requests_without_a_key_behave_as_before(self):
        self.assertEqual(self.post(key=None).status_code, 201)
        self.assertEqual(IdempotencyKey.objects.count(), 0)

    def test_malformed_keys_are_rejected(self):
        for bad in ('short', 'has spaces in it', 'x' * 129):
            res = self.post(key=bad)
            self.assertEqual(res.status_code, 400, bad)
        self.assertEqual(ShortenedURL.objects.count(), 0)

    def test_a_failed_request_releases_the_key_so_it_can_be_retried(self):
        bad = self.post(original_url='not a url')
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(IdempotencyKey.objects.count(), 0)
        good = self.post(original_url='https://example.com/fixed')
        self.assertEqual(good.status_code, 201)

    def test_an_unexpected_error_releases_the_key_and_creates_nothing(self):
        with patch('shortener.serializers.generate_short_code', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.post()
        self.assertEqual(IdempotencyKey.objects.count(), 0)
        self.assertEqual(ShortenedURL.objects.count(), 0)
        self.assertEqual(self.post().status_code, 201)

    def test_keys_are_scoped_per_user(self):
        first = self.post()
        self.client.force_authenticate(self.bob)
        second = self.post()
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.data['short_code'], second.data['short_code'])
        self.assertEqual(ShortenedURL.objects.count(), 2)

    def test_a_request_that_is_still_running_gets_409(self):
        IdempotencyKey.objects.create(user=self.alice, key=KEY, fingerprint='whatever')
        res = self.post()
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res['Retry-After'], '1')
        self.assertEqual(ShortenedURL.objects.count(), 0)

    def test_a_crashed_request_can_be_taken_over_after_the_lock_timeout(self):
        stale = timezone.now() - timedelta(seconds=120)
        IdempotencyKey.objects.create(
            user=self.alice, key=KEY, fingerprint='whatever', locked_at=stale
        )
        res = self.post()
        self.assertEqual(res.status_code, 201)
        record = IdempotencyKey.objects.get(user=self.alice, key=KEY)
        self.assertEqual(record.status_code, 201)

    def test_the_stored_record_contains_the_response(self):
        res = self.post()
        record = IdempotencyKey.objects.get(user=self.alice, key=KEY)
        self.assertEqual(record.status_code, 201)
        self.assertEqual(record.response_body['short_code'], res.data['short_code'])

    def test_purge_task_removes_only_old_keys(self):
        old = IdempotencyKey.objects.create(user=self.alice, key='old-key-0001', fingerprint='x')
        yesterday = timezone.now() - timedelta(hours=25)
        IdempotencyKey.objects.filter(pk=old.pk).update(created_at=yesterday)
        IdempotencyKey.objects.create(user=self.alice, key='new-key-0001', fingerprint='x')
        self.assertEqual(purge_idempotency_keys.apply().get(), 1)
        remaining = list(IdempotencyKey.objects.values_list('key', flat=True))
        self.assertEqual(remaining, ['new-key-0001'])


class HealthTests(APITestCase):
    def test_liveness(self):
        res = self.client.get(reverse('core:health'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, {'status': 'ok'})

    def test_readiness_checks_database_and_cache(self):
        res = self.client.get(reverse('core:ready'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['checks'], {'database': 'ok', 'cache': 'ok'})

    def test_readiness_reports_a_cache_outage_with_503(self):
        with patch('core.views.cache.set', side_effect=ConnectionError('redis down')):
            res = self.client.get(reverse('core:ready'))
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.data['checks']['cache'], 'error')
        self.assertEqual(res.data['checks']['database'], 'ok')

    def test_probes_are_never_throttled(self):
        statuses = {self.client.get(reverse('core:health')).status_code for _ in range(120)}
        self.assertEqual(statuses, {200})


class RateLimitHelperTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_parse_rate(self):
        self.assertEqual(parse_rate('240/minute'), (240, 60))
        self.assertEqual(parse_rate('5/second'), (5, 1))
        self.assertEqual(parse_rate('100/hour'), (100, 3600))

    def test_counter_allows_up_to_the_limit_then_refuses(self):
        results = [hit('1.2.3.4', 'demo', 3, 60)[0] for _ in range(5)]
        self.assertEqual(results, [True, True, True, False, False])

    def test_it_fails_open_when_the_cache_is_unreachable(self):
        with patch('core.ratelimit.cache.incr', return_value=None):
            self.assertEqual(hit('1.2.3.4', 'demo', 1, 60), (True, 0))

    def test_scopes_and_identities_are_independent(self):
        for _ in range(3):
            hit('1.2.3.4', 'demo', 3, 60)
        self.assertTrue(hit('5.6.7.8', 'demo', 3, 60)[0])
        self.assertTrue(hit('1.2.3.4', 'other', 3, 60)[0])


class ClientIPTests(SimpleTestCase):
    factory = RequestFactory()

    def request(self, **meta):
        return self.factory.get('/', **meta)

    @override_settings(NUM_PROXIES=0)
    def test_direct_connection_ignores_forwarded_header(self):
        req = self.request(REMOTE_ADDR='10.0.0.9', HTTP_X_FORWARDED_FOR='1.1.1.1')
        self.assertEqual(get_client_ip(req), '10.0.0.9')

    @override_settings(NUM_PROXIES=2)
    def test_two_proxies_trust_the_second_entry_from_the_right(self):
        chain = '8.8.8.8, 203.0.113.7, 10.1.1.1'
        req = self.request(REMOTE_ADDR='10.0.0.9', HTTP_X_FORWARDED_FOR=chain)
        self.assertEqual(get_client_ip(req), '203.0.113.7')

    @override_settings(NUM_PROXIES=1)
    def test_garbage_is_not_returned_as_an_ip(self):
        req = self.request(REMOTE_ADDR='10.0.0.9', HTTP_X_FORWARDED_FOR='not-an-ip')
        self.assertIsNone(get_client_ip(req))

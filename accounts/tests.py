from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import GoogleAccount

User = get_user_model()
PASSWORD = 'Str0ng-Pass-123!'


class RegisterTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse('accounts:register')
        self.payload = {
            'username': 'alice',
            'email': 'alice@example.com',
            'password': PASSWORD,
            'password2': PASSWORD,
        }

    def test_register_returns_user_and_tokens(self):
        res = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', res.data)
        self.assertIn('refresh', res.data)
        self.assertEqual(res.data['user']['username'], 'alice')
        self.assertNotIn('password', res.data['user'])
        self.assertTrue(User.objects.get(username='alice').check_password(PASSWORD))

    def test_password_mismatch_is_rejected(self):
        self.payload['password2'] = 'something-else'
        res = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password2', res.data)

    def test_weak_password_is_rejected(self):
        self.payload.update(password='12345678', password2='12345678')
        res = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', res.data)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user('bob', 'ALICE@example.com', PASSWORD)
        res = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', res.data)

    def test_duplicate_username_is_rejected_case_insensitively(self):
        User.objects.create_user('Alice', 'other@example.com', PASSWORD)
        res = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('username', res.data)


class LoginTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('alice', 'alice@example.com', PASSWORD)
        self.url = reverse('accounts:login')

    def test_login_with_username(self):
        res = self.client.post(self.url, {'username': 'alice', 'password': PASSWORD}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('access', res.data)
        self.assertIn('refresh', res.data)
        self.assertEqual(res.data['user']['email'], 'alice@example.com')

    def test_login_with_email(self):
        res = self.client.post(
            self.url, {'username': 'ALICE@example.com', 'password': PASSWORD}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_wrong_password_is_unauthorized(self):
        res = self.client.post(self.url, {'username': 'alice', 'password': 'nope'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_is_throttled(self):
        for _ in range(10):
            self.client.post(self.url, {'username': 'alice', 'password': 'nope'}, format='json')
        res = self.client.post(self.url, {'username': 'alice', 'password': 'nope'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn('Retry-After', res)


class ProfileAndTokenTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('alice', 'alice@example.com', PASSWORD)
        res = self.client.post(
            reverse('accounts:login'), {'username': 'alice', 'password': PASSWORD}, format='json'
        )
        self.tokens = res.data

    def authenticate(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.tokens['access'])

    def test_me_requires_authentication(self):
        res = self.client.get(reverse('accounts:me'))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_current_user(self):
        self.authenticate()
        res = self.client.get(reverse('accounts:me'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['username'], 'alice')

    def test_update_profile_but_not_username(self):
        self.authenticate()
        res = self.client.patch(
            reverse('accounts:me'), {'first_name': 'Alice', 'username': 'hacker'}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Alice')
        self.assertEqual(self.user.username, 'alice')  # read-only field was ignored

    def test_change_password(self):
        self.authenticate()
        new_password = 'An0ther-Str0ng-Pass!'
        res = self.client.post(
            reverse('accounts:change_password'),
            {'old_password': PASSWORD, 'new_password': new_password},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))

    def test_change_password_with_wrong_old_password(self):
        self.authenticate()
        res = self.client.post(
            reverse('accounts:change_password'),
            {'old_password': 'wrong', 'new_password': 'An0ther-Str0ng-Pass!'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('old_password', res.data)

    def test_change_password_rejects_a_weak_new_password(self):
        self.authenticate()
        res = self.client.post(
            reverse('accounts:change_password'),
            {'old_password': PASSWORD, 'new_password': '12345678'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password', res.data)

    def test_refresh_rotates_the_refresh_token(self):
        res = self.client.post(
            reverse('accounts:token_refresh'), {'refresh': self.tokens['refresh']}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('access', res.data)
        self.assertNotEqual(res.data['refresh'], self.tokens['refresh'])

    def test_logout_blacklists_the_refresh_token(self):
        res = self.client.post(
            reverse('accounts:logout'), {'refresh': self.tokens['refresh']}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        res = self.client.post(
            reverse('accounts:token_refresh'), {'refresh': self.tokens['refresh']}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(GOOGLE_CLIENT_ID='test-client-id')
class GoogleLoginTests(APITestCase):
    PROFILE = {
        'sub': 'google-123',
        'email': 'newuser@example.com',
        'email_verified': True,
        'given_name': 'New',
        'family_name': 'User',
    }

    def setUp(self):
        cache.clear()
        self.url = reverse('accounts:google')

    @patch('accounts.views.google_id_token.verify_oauth2_token')
    def test_first_login_creates_user_and_second_login_reuses_it(self, verify):
        verify.return_value = self.PROFILE
        res = self.client.post(self.url, {'id_token': 'fake'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data['created'])
        self.assertIn('access', res.data)
        user = User.objects.get(email='newuser@example.com')
        self.assertFalse(user.has_usable_password())
        self.assertTrue(GoogleAccount.objects.filter(user=user, sub='google-123').exists())

        res = self.client.post(self.url, {'id_token': 'fake'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data['created'])
        self.assertEqual(User.objects.count(), 1)

    @patch('accounts.views.google_id_token.verify_oauth2_token')
    def test_existing_local_email_is_a_conflict(self, verify):
        verify.return_value = self.PROFILE
        User.objects.create_user('local', 'newuser@example.com', PASSWORD)
        res = self.client.post(self.url, {'id_token': 'fake'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)

    @patch('accounts.views.google_id_token.verify_oauth2_token')
    def test_invalid_token_is_rejected(self, verify):
        verify.side_effect = ValueError('bad token')
        res = self.client.post(self.url, {'id_token': 'fake'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('accounts.views.google_id_token.verify_oauth2_token')
    def test_unverified_email_is_rejected(self, verify):
        verify.return_value = {**self.PROFILE, 'email_verified': False}
        res = self.client.post(self.url, {'id_token': 'fake'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(GOOGLE_CLIENT_ID='')
    def test_not_configured(self):
        res = self.client.post(self.url, {'id_token': 'fake'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

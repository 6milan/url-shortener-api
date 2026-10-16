from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.utils import extend_schema
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import GoogleAccount
from .serializers import (
    ChangePasswordSerializer,
    GoogleLoginSerializer,
    LoginSerializer,
    LogoutSerializer,
    RegisterSerializer,
    UserSerializer,
    UserSessionSerializer,
)
from .utils import get_tokens_for_user, unique_username

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        payload = {'user': UserSerializer(user).data, **get_tokens_for_user(user)}
        return Response(payload, status=status.HTTP_201_CREATED)


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'


class LogoutView(APIView):
    # Open to anyone holding a refresh token: the access token may already
    # have expired when the user clicks 'Log out'.
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=LogoutSerializer, responses={204: None})
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data['refresh']).blacklist()
        except TokenError:
            return Response(
                {'detail': 'Invalid or expired token.'}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ChangePasswordSerializer, responses={200: None})
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save(update_fields=['password'])
        return Response({'detail': 'Password updated.'})


class GoogleLoginView(APIView):
    # The frontend obtains a Google ID token (a signed JWT) with Google Identity
    # Services and POSTs it here. We verify the signature, audience and expiry
    # with Google's public keys, then issue OUR OWN JWT tokens.
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    @extend_schema(
        request=GoogleLoginSerializer,
        responses={200: UserSessionSerializer, 201: UserSessionSerializer},
    )
    def post(self, request):
        if not settings.GOOGLE_CLIENT_ID:
            return Response(
                {'detail': 'Google login is not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = GoogleLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            info = google_id_token.verify_oauth2_token(
                serializer.validated_data['id_token'],
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
        except (ValueError, GoogleAuthError):
            return Response(
                {'detail': 'Invalid Google token.'}, status=status.HTTP_400_BAD_REQUEST
            )

        if not info.get('email_verified'):
            return Response(
                {'detail': 'Your Google email address is not verified.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = False
        account = GoogleAccount.objects.select_related('user').filter(sub=info['sub']).first()
        if account:
            user = account.user
        else:
            email = info['email'].lower()
            if User.objects.filter(email__iexact=email).exists():
                return Response(
                    {'detail': 'An account with this email already exists. '
                               'Please log in with your password.'},
                    status=status.HTTP_409_CONFLICT,
                )
            with transaction.atomic():
                user = User(
                    username=unique_username(email),
                    email=email,
                    first_name=info.get('given_name', '')[:150],
                    last_name=info.get('family_name', '')[:150],
                )
                user.set_unusable_password()  # Google users have no local password
                user.save()
                GoogleAccount.objects.create(user=user, sub=info['sub'])
            created = True

        if not user.is_active:
            return Response(
                {'detail': 'This account is disabled.'}, status=status.HTTP_403_FORBIDDEN
            )

        payload = {
            'user': UserSerializer(user).data,
            'created': created,
            **get_tokens_for_user(user),
        }
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(payload, status=code)

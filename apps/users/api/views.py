from __future__ import annotations

from django.conf import settings
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from ..models import User
from ..services import auth as auth_service
from ..services import mfa as mfa_service
from ..services import oauth as oauth_service
from ..services import password_reset as user_services
from ..services import webauthn_service
from ..services.audit import record_login_event
from ..services.mfa import InvalidCodeError, MFAAlreadyEnabledError, MFANotEnabledError
from ..services.oauth import OAuthError
from ..services.webauthn_service import WebAuthnError
from ..webauthn_models import WebAuthnCredential
from .serializers import (
    LoginSerializer,
    MFACodeSerializer,
    MFAVerifySerializer,
    OAuthCallbackSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RefreshTokenSerializer,
    RegisterSerializer,
    TOTPConfirmSerializer,
    UserSerializer,
    WebAuthnAuthOptionsSerializer,
    WebAuthnAuthVerifySerializer,
    WebAuthnCredentialSerializer,
    WebAuthnRegisterVerifySerializer,
)

# ============================================================ registration


class RegisterView(generics.CreateAPIView):
    """Public signup. Throttled aggressively (scope='auth') against enumeration/abuse."""

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


# ============================================================ password login + MFA


class LoginView(APIView):
    """Password login. If the account has confirmed MFA, this does NOT
    return usable tokens — it returns an `mfa_token` that must be exchanged
    at `/auth/mfa/verify/` for real tokens."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email, password = serializer.validated_data["email"], serializer.validated_data["password"]

        try:
            user = auth_service.authenticate_with_password(email=email, password=password, request=request)
        except auth_service.MFARequiredError as exc:
            record_login_event(
                request=request, email=email, method="password", success=True, reason="mfa_required"
            )
            return Response({"mfa_required": True, "mfa_token": exc.mfa_token, "methods": exc.methods})
        except auth_service.InvalidCredentialsError:
            record_login_event(
                request=request, email=email, method="password", success=False, reason="invalid_credentials"
            )
            return Response({"detail": "Invalid email or password."}, status=status.HTTP_401_UNAUTHORIZED)

        record_login_event(request=request, email=email, method="password", success=True, user=user)
        tokens = auth_service.issue_tokens(user=user, request=request)
        return Response({**tokens, "user": UserSerializer(user).data})


class MFAVerifyView(APIView):
    """Exchanges an `mfa_token` (from LoginView) + a TOTP/backup code for
    real tokens. Tightly throttled — this is the brute-force target for a
    6-digit code."""

    permission_classes = [AllowAny]
    throttle_scope = "mfa_verify"
    serializer_class = MFAVerifySerializer

    def post(self, request):
        serializer = MFAVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = auth_service.resolve_mfa_challenge(serializer.validated_data["mfa_token"])
        except auth_service.InvalidCredentialsError:
            return Response(
                {"detail": "Invalid or expired MFA challenge."}, status=status.HTTP_401_UNAUTHORIZED
            )

        method = mfa_service.verify_mfa_code(user=user, code=serializer.validated_data["code"])
        if method is None:
            record_login_event(
                request=request,
                email=user.email,
                method="mfa_totp",
                success=False,
                user=user,
                reason="invalid_code",
            )
            return Response({"detail": "Invalid verification code."}, status=status.HTTP_401_UNAUTHORIZED)

        record_login_event(request=request, email=user.email, method=method, success=True, user=user)
        tokens = auth_service.issue_tokens(user=user, request=request)
        return Response({**tokens, "user": UserSerializer(user).data})


class LogoutView(APIView):
    """Blacklists the refresh token so it can't be replayed after logout."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"
    serializer_class = RefreshTokenSerializer

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response({"detail": "refresh token is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid or already-blacklisted token."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self) -> User:
        return self.request.user


# ============================================================ MFA management (TOTP)


class TOTPEnrollView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "write"
    serializer_class = None  # request body is empty; response shape is bespoke

    def post(self, request):
        try:
            device = mfa_service.start_totp_enrollment(user=request.user)
        except MFAAlreadyEnabledError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            {
                "secret": device.get_secret(),
                "provisioning_uri": device.provisioning_uri(account_name=request.user.email),
            }
        )


class TOTPConfirmView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "mfa_verify"
    serializer_class = TOTPConfirmSerializer

    def post(self, request):
        serializer = TOTPConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            backup_codes = mfa_service.confirm_totp_enrollment(
                user=request.user, code=serializer.validated_data["code"]
            )
        except (MFANotEnabledError, InvalidCodeError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"backup_codes": backup_codes}, status=status.HTTP_201_CREATED)


class TOTPDisableView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "mfa_verify"
    serializer_class = MFACodeSerializer

    def post(self, request):
        serializer = MFACodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            mfa_service.disable_totp(user=request.user, code=serializer.validated_data["code"])
        except (MFANotEnabledError, InvalidCodeError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BackupCodesRegenerateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "mfa_verify"
    serializer_class = MFACodeSerializer

    def post(self, request):
        serializer = MFACodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            codes = mfa_service.regenerate_backup_codes(
                user=request.user, code=serializer.validated_data["code"]
            )
        except (MFANotEnabledError, InvalidCodeError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"backup_codes": codes})


# ============================================================ WebAuthn / passkeys


class WebAuthnRegisterOptionsView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "write"
    serializer_class = None  # request body is empty; response is a WebAuthn options object

    def post(self, request):
        return Response(webauthn_service.build_registration_options(request.user))


class WebAuthnRegisterVerifyView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "write"
    serializer_class = WebAuthnRegisterVerifySerializer

    def post(self, request):
        serializer = WebAuthnRegisterVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            credential = webauthn_service.verify_registration(
                user=request.user,
                credential=serializer.validated_data["credential"],
                device_name=serializer.validated_data["device_name"],
            )
        except WebAuthnError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(WebAuthnCredentialSerializer(credential).data, status=status.HTTP_201_CREATED)


class WebAuthnCredentialListView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "write"
    serializer_class = WebAuthnCredentialSerializer

    def get(self, request):
        creds = WebAuthnCredential.objects.filter(user=request.user).order_by("-created_at")
        return Response(WebAuthnCredentialSerializer(creds, many=True).data)


class WebAuthnCredentialDetailView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "write"
    serializer_class = WebAuthnCredentialSerializer

    def delete(self, request, credential_id):
        deleted, _ = WebAuthnCredential.objects.filter(id=credential_id, user=request.user).delete()
        if not deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WebAuthnAuthOptionsView(APIView):
    """Public: this is how passwordless login starts. `email` is optional —
    omitted, it's a usernameless/discoverable-credential ceremony."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"
    serializer_class = WebAuthnAuthOptionsSerializer

    def post(self, request):
        serializer = WebAuthnAuthOptionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        options, state = webauthn_service.build_authentication_options(serializer.validated_data.get("email"))
        return Response({**options, "state": state})


class WebAuthnAuthVerifyView(APIView):
    """Public: completes passwordless login. A verified passkey assertion
    (user-verification required) is treated as satisfying MFA on its own —
    it is itself possession + inherence/knowledge, phishing-resistant by
    construction — so this issues real tokens directly, no further MFA step."""

    permission_classes = [AllowAny]
    throttle_scope = "mfa_verify"
    serializer_class = WebAuthnAuthVerifySerializer

    def post(self, request):
        serializer = WebAuthnAuthVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = webauthn_service.verify_authentication(
                state_token=serializer.validated_data["state"],
                credential=serializer.validated_data["credential"],
            )
        except WebAuthnError as exc:
            record_login_event(request=request, email="", method="webauthn", success=False, reason=str(exc))
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        record_login_event(request=request, email=user.email, method="webauthn", success=True, user=user)
        tokens = auth_service.issue_tokens(user=user, request=request)
        return Response({**tokens, "user": UserSerializer(user).data})


# ============================================================ OAuth / social login


class OAuthAuthorizeView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"
    serializer_class = None  # GET with a path param; no request body

    def get(self, request, provider):
        try:
            url = oauth_service.build_authorization_url(provider)
        except OAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"authorization_url": url})


class OAuthCallbackView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"
    serializer_class = OAuthCallbackSerializer

    def post(self, request, provider):
        serializer = OAuthCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user, created = oauth_service.complete_oauth_login(**serializer.validated_data)
        except OAuthError as exc:
            record_login_event(
                request=request, email="", method=f"oauth:{provider}", success=False, reason=str(exc)
            )
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Defense in depth: OAuth login still respects an existing MFA enrollment.
        if mfa_service.user_has_mfa_enabled(user):
            record_login_event(
                request=request,
                email=user.email,
                method=f"oauth:{provider}",
                success=True,
                reason="mfa_required",
            )
            return Response(
                {
                    "mfa_required": True,
                    "mfa_token": auth_service.issue_mfa_challenge(user),
                    "methods": ["totp"],
                }
            )

        record_login_event(
            request=request, email=user.email, method=f"oauth:{provider}", success=True, user=user
        )
        tokens = auth_service.issue_tokens(user=user, request=request)
        return Response({**tokens, "user": UserSerializer(user).data, "created": created})


# ============================================================ password reset


class PasswordResetRequestView(APIView):
    """Public. Always returns 200 to avoid revealing whether an email exists.
    In DEBUG the response echoes the token so the flow is testable without an
    email backend; in production the token is delivered out of band."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"
    serializer_class = PasswordResetRequestSerializer

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_token = user_services.request_password_reset(email=serializer.validated_data["email"])
        body = {"detail": "If that email is registered, a reset link is on its way."}
        if settings.DEBUG and raw_token is not None:
            body["debug_token"] = raw_token  # dev convenience only; never in production
        return Response(body, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    """Public. Consumes a reset token and sets a new password."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"
    serializer_class = PasswordResetConfirmSerializer

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user_services.reset_password(
                raw_token=serializer.validated_data["token"],
                new_password=serializer.validated_data["new_password"],
            )
        except user_services.InvalidResetToken as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Your password has been reset. You can now sign in."})

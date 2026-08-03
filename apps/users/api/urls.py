from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    BackupCodesRegenerateView,
    LoginView,
    LogoutView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    MFAVerifyView,
    OAuthAuthorizeView,
    OAuthCallbackView,
    RegisterView,
    TOTPConfirmView,
    TOTPDisableView,
    TOTPEnrollView,
    WebAuthnAuthOptionsView,
    WebAuthnAuthVerifyView,
    WebAuthnCredentialDetailView,
    WebAuthnCredentialListView,
    WebAuthnRegisterOptionsView,
    WebAuthnRegisterVerifyView,
)

urlpatterns = [
    # core
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    # password reset
    path("password/reset/", PasswordResetRequestView.as_view(), name="password-reset"),
    path("password/reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    # MFA
    path("mfa/verify/", MFAVerifyView.as_view(), name="mfa-verify"),
    path("mfa/totp/enroll/", TOTPEnrollView.as_view(), name="mfa-totp-enroll"),
    path("mfa/totp/confirm/", TOTPConfirmView.as_view(), name="mfa-totp-confirm"),
    path("mfa/totp/disable/", TOTPDisableView.as_view(), name="mfa-totp-disable"),
    path(
        "mfa/backup-codes/regenerate/",
        BackupCodesRegenerateView.as_view(),
        name="mfa-backup-codes-regenerate",
    ),
    # WebAuthn / passkeys
    path(
        "webauthn/register/options/", WebAuthnRegisterOptionsView.as_view(), name="webauthn-register-options"
    ),
    path("webauthn/register/verify/", WebAuthnRegisterVerifyView.as_view(), name="webauthn-register-verify"),
    path("webauthn/credentials/", WebAuthnCredentialListView.as_view(), name="webauthn-credentials"),
    path(
        "webauthn/credentials/<uuid:credential_id>/",
        WebAuthnCredentialDetailView.as_view(),
        name="webauthn-credential-detail",
    ),
    path("webauthn/authenticate/options/", WebAuthnAuthOptionsView.as_view(), name="webauthn-auth-options"),
    path("webauthn/authenticate/verify/", WebAuthnAuthVerifyView.as_view(), name="webauthn-auth-verify"),
    # OAuth
    path("oauth/<str:provider>/authorize/", OAuthAuthorizeView.as_view(), name="oauth-authorize"),
    path("oauth/<str:provider>/callback/", OAuthCallbackView.as_view(), name="oauth-callback"),
]

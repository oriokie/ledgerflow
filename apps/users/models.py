"""Custom user model, set as AUTH_USER_MODEL from day one.

Retrofitting a custom user model after migrations exist against
django.contrib.auth.User is painful (FK rewrites across every app), so it is
established here before anything else. Email is the login identifier — this is
a consumer SaaS product, not an admin tool with usernames.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, UUIDModel, TimeStampedModel):
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True, default="")
    last_name = models.CharField(max_length=150, blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)  # email verification gate
    last_login_at = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # email + password only at createsuperuser time

    class Meta:
        indexes = [models.Index(fields=["is_active", "is_staff"])]

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.email


class UserProfile(UUIDModel, TimeStampedModel):
    """Per-user, cross-workspace preferences. Localization defaults resolve
    user profile -> tenant defaults -> system defaults.

    Lives in `users` (identity), not `tenancy` — it describes the person, not
    a workspace, and a user keeps exactly one profile across every tenant
    they belong to."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    locale = models.CharField(max_length=10, default="en-US")
    timezone = models.CharField(max_length=64, default="UTC")
    preferred_currency = models.CharField(max_length=3, default="USD")
    avatar_url = models.URLField(blank=True, default="")
    phone_number = models.CharField(max_length=32, blank=True, default="")
    phone_verified = models.BooleanField(default=False)
    last_active_tenant_id = models.UUIDField(null=True, blank=True)

    def __str__(self) -> str:
        return f"profile:{self.user_id}"


# Register concrete models defined in sibling modules so migrations see them.
from .mfa_models import MFABackupCode, TOTPDevice  # noqa: E402,F401
from .oauth_models import SocialAccount  # noqa: E402,F401
from .password_reset_models import PasswordResetToken  # noqa: E402,F401
from .security_events import LoginEvent  # noqa: E402,F401
from .webauthn_models import WebAuthnCredential  # noqa: E402,F401

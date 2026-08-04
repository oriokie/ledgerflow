from __future__ import annotations

from django.contrib.auth import password_validation
from rest_framework import serializers

from ..mfa_models import TOTPDevice
from ..models import User, UserProfile
from ..webauthn_models import WebAuthnCredential


class UserSerializer(serializers.ModelSerializer):
    mfa_enabled = serializers.SerializerMethodField()
    passkey_count = serializers.SerializerMethodField()
    is_platform_staff = serializers.SerializerMethodField()
    # Lives on UserProfile, surfaced here so the client reads its whole session
    # in the one /auth/me/ call it already makes rather than a second request
    # the shell would have to wait on before it could draw the sidebar.
    show_receipt_scanner = serializers.BooleanField(required=False)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "is_verified",
            "mfa_enabled",
            "passkey_count",
            "is_platform_staff",
            "show_receipt_scanner",
            "created_at",
        ]
        read_only_fields = ["id", "email", "is_verified", "created_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # The profile row is created on first write, so most accounts have
        # none — read through its absence to the field's default rather than
        # forcing a write on every read of /auth/me/.
        profile = getattr(instance, "profile", None)
        data["show_receipt_scanner"] = bool(profile.show_receipt_scanner) if profile else False
        return data

    def update(self, instance, validated_data):
        show_scanner = validated_data.pop("show_receipt_scanner", None)
        instance = super().update(instance, validated_data)
        if show_scanner is not None:
            profile, _ = UserProfile.objects.get_or_create(user=instance)
            if profile.show_receipt_scanner != show_scanner:
                profile.show_receipt_scanner = show_scanner
                profile.save(update_fields=["show_receipt_scanner", "updated_at"])
        return instance

    def get_mfa_enabled(self, obj) -> bool:
        return TOTPDevice.objects.filter(user=obj, confirmed_at__isnull=False).exists()

    def get_passkey_count(self, obj) -> int:
        return WebAuthnCredential.objects.filter(user=obj).count()

    def get_is_platform_staff(self, obj) -> bool:
        """Whether this account operates the platform rather than using it.

        Exposed on the ordinary user payload — not only the platform API —
        because the *customer* app needs it: an operator who lands on the
        customer shell should be sent to the console rather than shown a
        workspace picker they are not permitted to use. Returning a bare
        boolean leaks nothing about what they may do; capabilities stay behind
        the platform API.
        """
        from apps.platform_admin.separation import is_platform_staff

        return is_platform_staff(obj)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=12)

    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name"]

    def validate_password(self, value: str) -> str:
        password_validation.validate_password(value)
        return value

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def create(self, validated_data) -> User:
        return User.objects.create_user(**validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)


class RefreshTokenSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class MFAVerifySerializer(serializers.Serializer):
    mfa_token = serializers.CharField()
    code = serializers.CharField(max_length=32)


class MFACodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)


class TOTPConfirmSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=6, min_length=6)


class WebAuthnCredentialSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebAuthnCredential
        fields = ["id", "device_name", "transports", "backup_state", "created_at", "last_used_at"]


class WebAuthnRegisterVerifySerializer(serializers.Serializer):
    credential = serializers.JSONField()
    device_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class WebAuthnAuthOptionsSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)


class WebAuthnAuthVerifySerializer(serializers.Serializer):
    state = serializers.CharField()
    credential = serializers.JSONField()


class OAuthCallbackSerializer(serializers.Serializer):
    state = serializers.CharField()
    code = serializers.CharField()


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value: str) -> str:
        # Structural check only; full user-aware validation runs in the service
        # once the token resolves to a user.
        password_validation.validate_password(value)
        return value

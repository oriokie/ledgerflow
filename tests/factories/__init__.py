"""Factory Boy factories. One place to build valid test objects so tests read
as intent, not setup boilerplate."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.tenancy.models import Invitation, Membership, Role, Tenant, TenantType
from apps.users.mfa_models import MFABackupCode, TOTPDevice
from apps.users.models import User
from apps.users.oauth_models import SocialAccount
from apps.users.webauthn_models import WebAuthnCredential


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("email",)
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    is_active = True

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        self.set_password(extracted or "correct-horse-battery-staple")
        if create:
            self.save(update_fields=["password"])


class TenantFactory(DjangoModelFactory):
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Household {n}")
    type = TenantType.PERSONAL
    base_currency = "USD"
    #: Off by default here, unlike production, where it defaults to True.
    #:
    #: These fixtures build minimal ledgers: an account, a category, an expense,
    #: with no opening balance because the balance is almost never what is being
    #: tested. That is exactly the shape `block_overdrafts` refuses, so leaving
    #: it on would make roughly a hundred unrelated tests assert the overdraft
    #: guard instead of what they were written for — and every balance figure in
    #: them would have to be rewritten around a funding amount.
    #:
    #: The production default is covered directly instead, by the tests in
    #: `test_overdraft_policy.py`, which construct a workspace with the setting
    #: on and one with it off and check both.
    block_overdrafts = False


class MembershipFactory(DjangoModelFactory):
    class Meta:
        model = Membership

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)
    role = Role.OWNER


class InvitationFactory(DjangoModelFactory):
    class Meta:
        model = Invitation

    tenant = factory.SubFactory(TenantFactory)
    email = factory.Sequence(lambda n: f"invitee{n}@example.com")
    role = Role.MEMBER
    token_hash = factory.Sequence(lambda n: f"faketokenhash{n}")


class TOTPDeviceFactory(DjangoModelFactory):
    class Meta:
        model = TOTPDevice

    user = factory.SubFactory(UserFactory)

    @factory.post_generation
    def secret(self, create, extracted, **kwargs):
        self.set_secret(extracted or TOTPDevice.generate_secret())
        if create:
            self.save()


class MFABackupCodeFactory(DjangoModelFactory):
    class Meta:
        model = MFABackupCode

    user = factory.SubFactory(UserFactory)
    code_hash = factory.LazyFunction(lambda: MFABackupCode.hash_code("unused-code"))


class SocialAccountFactory(DjangoModelFactory):
    class Meta:
        model = SocialAccount

    user = factory.SubFactory(UserFactory)
    provider = "google"
    provider_user_id = factory.Sequence(lambda n: f"google-sub-{n}")
    email = factory.SelfAttribute("user.email")


class WebAuthnCredentialFactory(DjangoModelFactory):
    class Meta:
        model = WebAuthnCredential

    user = factory.SubFactory(UserFactory)
    credential_id = factory.Sequence(lambda n: f"fake-credential-id-{n}")
    public_key = "ZmFrZS1wdWJsaWMta2V5"  # base64("fake-public-key"), never verified in factory-built rows

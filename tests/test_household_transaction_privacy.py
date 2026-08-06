"""Transaction-level privacy.

The sibling of the account-level tests, one layer down. Account privacy decides
whether a partner sees an account; this decides how much of a line they see
inside an account they can already see.

Absence is asserted the same three ways account privacy is — from the listing,
from the redacted payload, and from the aggregate — because those are three
different ways the same leak surfaces.

One test here deliberately documents a **limitation** rather than a guarantee.
`test_hiding_a_line_does_not_hide_the_amount_from_arithmetic` asserts what the
product cannot do, so that nobody later reads the feature as stronger than it
is and builds a promise on top of it.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.finance import selectors as finance_selectors
from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from apps.household import transaction_privacy as privacy
from apps.household.models import (
    AccountSharing,
    SharingPolicy,
    TransactionPrivacy,
    TransactionVisibility,
)
from tests.factories import MembershipFactory, TenantFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _couple():
    tenant = TenantFactory()
    return tenant, MembershipFactory(tenant=tenant), MembershipFactory(tenant=tenant)


def _shared_account(owner=None):
    account = finance_services.create_financial_account(
        name="Joint current",
        account_type=AccountType.CHECKING,
        currency="KES",
        opening_balance_minor=500_000_00,
    )
    AccountSharing.objects.create(
        financial_account=account, owner=owner, policy=SharingPolicy.SHARED, is_joint=True
    )
    return account


def _spend(account, *, amount=2_400_00, memo="A gift"):
    from apps.finance.models import Category

    category = Category.objects.filter(name="Gifts", kind=CategoryKind.EXPENSE).first()
    if category is None:
        category = finance_services.create_category(name="Gifts", kind=CategoryKind.EXPENSE, currency="KES")
    return finance_services.record_expense(
        financial_account=account,
        category=category,
        amount_minor=amount,
        occurred_at=timezone.now(),
        memo=memo,
    )


class TestDefaults:
    def test_nothing_is_private_until_somebody_says_so(self):
        """Shipping this must be inert. No existing transaction has a privacy
        row, so nothing changes until a mark is made."""
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            txn = _spend(_shared_account())
        with tenant_scope(tenant.id, actor_id=brian.user_id):
            assert privacy.hidden_transaction_ids() == set()
            assert privacy.redaction_levels() == {}
            assert privacy.apply({"amount_minor": txn.amount_minor}, None)["amount_minor"]

    def test_a_workspace_of_one_hides_nothing_from_itself(self):
        tenant = TenantFactory()
        solo = MembershipFactory(tenant=tenant)
        with tenant_scope(tenant.id, actor_id=solo.user_id):
            txn = _spend(_shared_account())
            privacy.set_level(transaction=txn, level=TransactionVisibility.PRIVATE)
            assert privacy.hidden_transaction_ids() == set()


class TestLevels:
    def test_private_is_omitted_from_the_partner_s_listing(self):
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _shared_account(owner=amina)
            txn = _spend(account)
            privacy.set_level(transaction=txn, level=TransactionVisibility.PRIVATE)

        with tenant_scope(tenant.id, actor_id=brian.user_id):
            assert txn.id in privacy.hidden_transaction_ids()

    def test_category_only_shows_the_kind_and_hides_the_size(self):
        """The common case for a gift: "Gifts — private amount"."""
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            txn = _spend(_shared_account(owner=amina))
            privacy.set_level(transaction=txn, level=TransactionVisibility.CATEGORY_ONLY)

        with tenant_scope(tenant.id, actor_id=brian.user_id):
            out = privacy.apply(
                {"amount_minor": 2_400_00, "category_id": "c", "memo": "A gift"},
                privacy.redaction_levels()[txn.id],
            )
            assert out["amount_minor"] is None
            assert out["category_id"] == "c", "the category is the point of this level"
            assert out["redacted"] == "amount"

    def test_amount_only_shows_the_size_and_hides_the_kind(self):
        """The common case for a hobby somebody would rather not discuss but
        does not want to conceal the cost of."""
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            txn = _spend(_shared_account(owner=amina))
            privacy.set_level(transaction=txn, level=TransactionVisibility.AMOUNT_ONLY)

        with tenant_scope(tenant.id, actor_id=brian.user_id):
            out = privacy.apply(
                {"amount_minor": 2_400_00, "category_id": "c", "memo": "A gift", "payee_id": "p"},
                privacy.redaction_levels()[txn.id],
            )
            assert out["amount_minor"] == 2_400_00
            assert out["category_id"] is None
            assert out["memo"] is None
            assert out["payee_id"] is None

    def test_a_redaction_always_explains_itself(self):
        """A blank field that does not say why reads as missing data and
        invites the partner to ask what happened to it — the opposite of what a
        privacy control is for."""
        for level in (TransactionVisibility.CATEGORY_ONLY, TransactionVisibility.AMOUNT_ONLY):
            out = privacy.apply({"amount_minor": 1, "memo": "x"}, level)
            assert out["redaction_note"]

    def test_full_clears_an_existing_mark(self):
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            txn = _spend(_shared_account(owner=amina))
            privacy.set_level(transaction=txn, level=TransactionVisibility.PRIVATE)
            privacy.set_level(transaction=txn, level=TransactionVisibility.FULL)
            assert not TransactionPrivacy.objects.filter(transaction_id=txn.id).exists()


class TestOwnership:
    def test_your_own_privacy_never_hides_anything_from_you(self):
        """Otherwise marking a purchase private makes it vanish from your own
        ledger, which reads as data loss."""
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            txn = _spend(_shared_account(owner=amina))
            privacy.set_level(transaction=txn, level=TransactionVisibility.PRIVATE)
            assert txn.id not in privacy.hidden_transaction_ids()
            assert txn.id not in privacy.redaction_levels()

    def test_a_partner_cannot_lift_your_privacy(self):
        """A privacy setting the other party can remove is not a privacy
        setting. This is the one rule role seniority does not override."""
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            txn = _spend(_shared_account(owner=amina))
            privacy.set_level(transaction=txn, level=TransactionVisibility.PRIVATE)

        with (
            tenant_scope(tenant.id, actor_id=brian.user_id),
            pytest.raises(privacy.TransactionPrivacyError, match="Only the person"),
        ):
            privacy.set_level(transaction=txn, level=TransactionVisibility.FULL)

    def test_an_unknown_level_is_refused(self):
        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            txn = _spend(_shared_account(owner=amina))
            with pytest.raises(privacy.TransactionPrivacyError):
                privacy.set_level(transaction=txn, level="invisible")  # noqa: SIM117


class TestAggregates:
    def test_a_hidden_line_still_counts_in_the_balance(self):
        """A household's spending is its spending. A partner who cannot itemise
        a purchase must still see it in the totals, or the figures they *are*
        shown are wrong and they will act on them."""
        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _shared_account(owner=amina)
            before = finance_selectors.account_current_balance_minor(account)
            txn = _spend(account, amount=2_400_00)
            privacy.set_level(transaction=txn, level=TransactionVisibility.PRIVATE)

        with tenant_scope(tenant.id, actor_id=brian.user_id):
            after = finance_selectors.account_current_balance_minor(account)
            assert after == before - 2_400_00, "the ledger is unaffected by privacy"

    def test_restrict_transactions_removes_only_the_fully_private(self):
        tenant, amina, brian = _couple()
        from apps.finance.models import Transaction

        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _shared_account(owner=amina)
            hidden = _spend(account, memo="Hidden")
            partial = _spend(account, memo="Partial")
            _spend(account, memo="Open")
            privacy.set_level(transaction=hidden, level=TransactionVisibility.PRIVATE)
            privacy.set_level(transaction=partial, level=TransactionVisibility.CATEGORY_ONLY)

        with tenant_scope(tenant.id, actor_id=brian.user_id):
            visible = privacy.restrict_transactions(Transaction.objects.all())
            memos = {t.memo for t in visible}
            assert "Hidden" not in memos
            assert {"Partial", "Open"} <= memos


class TestKnownLimitation:
    def test_hiding_a_line_does_not_hide_the_amount_from_arithmetic(self):
        """**This documents what the product cannot do.**

        If the partner can see the account's balance, hiding a line does not
        hide its size — the balance moved and the visible lines do not account
        for the difference. PRIVATE reliably conceals *what* something was; it
        conceals *how much* only on an account whose balance the partner cannot
        see.

        Asserted rather than left implicit so that nobody later reads this
        feature as stronger than it is and builds a promise on top of it.
        """
        from apps.finance.models import Transaction

        tenant, amina, brian = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            account = _shared_account(owner=amina)
            opening = finance_selectors.account_current_balance_minor(account)
            secret = _spend(account, amount=2_400_00, memo="A gift")
            privacy.set_level(transaction=secret, level=TransactionVisibility.PRIVATE)

        with tenant_scope(tenant.id, actor_id=brian.user_id):
            balance = finance_selectors.account_current_balance_minor(account)
            visible = privacy.restrict_transactions(Transaction.objects.all())
            visible_total = sum(t.amount_minor for t in visible)

            derived = opening + visible_total - balance
            assert derived == 2_400_00, (
                "the hidden amount is derivable by subtraction — this is a real "
                "limitation of line-level privacy on a visible account, and the "
                "product must not claim otherwise"
            )


class TestIsolation:
    def test_privacy_marks_do_not_cross_households(self):
        first, amina, _ = _couple()
        second, other, _ = _couple()
        with tenant_scope(first.id, actor_id=amina.user_id):
            txn = _spend(_shared_account(owner=amina))
            privacy.set_level(transaction=txn, level=TransactionVisibility.PRIVATE)
        with tenant_scope(second.id, actor_id=other.user_id):
            assert privacy.hidden_transaction_ids() == set()


class TestAudit:
    def test_marking_something_private_is_recorded_without_its_details(self):
        """The event's existence is not the secret. Its specifics are exactly
        what was just protected."""
        from apps.household import audit

        tenant, amina, _ = _couple()
        with tenant_scope(tenant.id, actor_id=amina.user_id):
            txn = _spend(_shared_account(owner=amina), memo="A surprise gift")
            privacy.set_level(transaction=txn, level=TransactionVisibility.PRIVATE)
            events = [e for e in audit.timeline(subject_type="transaction")]
            assert events
            assert events[0].is_private
            assert "surprise" not in events[0].summary.lower()


class TestApi:
    def test_a_private_line_is_absent_from_the_partner_s_ledger(self, tenant_context):
        membership, client = tenant_context
        partner = MembershipFactory(tenant_id=membership.tenant_id)
        with tenant_scope(membership.tenant_id, actor_id=partner.user_id):
            account = _shared_account(owner=partner)
            secret = _spend(account, memo="A gift")
            _spend(account, memo="Groceries")
            privacy.set_level(transaction=secret, level=TransactionVisibility.PRIVATE)

        resp = client.get("/api/v1/finance/transactions/")
        assert resp.status_code == 200
        memos = {row["memo"] for row in resp.data["results"]}
        assert "A gift" not in memos
        assert "Groceries" in memos

    def test_a_partially_private_line_is_shown_blunted(self, tenant_context):
        membership, client = tenant_context
        partner = MembershipFactory(tenant_id=membership.tenant_id)
        with tenant_scope(membership.tenant_id, actor_id=partner.user_id):
            account = _shared_account(owner=partner)
            txn = _spend(account, amount=2_400_00, memo="A gift")
            privacy.set_level(transaction=txn, level=TransactionVisibility.CATEGORY_ONLY)

        resp = client.get("/api/v1/finance/transactions/")
        row = next(r for r in resp.data["results"] if r["id"] == txn.id)
        assert row["amount_minor"] is None
        assert row["redaction_note"]

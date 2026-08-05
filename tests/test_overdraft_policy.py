"""The overdraft guard, and the workspace setting that governs it.

These tests carry the weight for this feature. The shared `TenantFactory` turns
`block_overdrafts` off, because the rest of the suite builds minimal ledgers
where balances are incidental and would otherwise all be asserting this one
rule — so the production default is proven *here*, explicitly, by constructing
workspaces with the setting in each position.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.finance import services as fin
from apps.finance.models import AccountType, CategoryKind, TransactionSource
from apps.tenancy.models import Tenant
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db

WHEN = datetime(2026, 1, 15, 12, tzinfo=UTC)


def _workspace(*, block_overdrafts: bool):
    return MembershipFactory(tenant__block_overdrafts=block_overdrafts)


def _seed(*, opening=10_000, account_type=AccountType.CHECKING):
    account = fin.create_financial_account(
        name="Checking",
        account_type=account_type,
        currency="USD",
        opening_balance_minor=opening,
    )
    category = fin.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    return account, category


def test_a_new_workspace_blocks_overdrafts_without_being_asked():
    """The model default, which is what a real signup gets."""
    assert Tenant._meta.get_field("block_overdrafts").default is True


def test_a_manual_expense_past_the_balance_is_refused():
    membership = _workspace(block_overdrafts=True)
    with tenant_scope(membership.tenant_id):
        account, category = _seed(opening=10_000)
        with pytest.raises(fin.InsufficientFundsError) as caught:
            fin.record_expense(
                financial_account=account,
                category=category,
                amount_minor=25_000,
                occurred_at=WHEN,
            )
    assert caught.value.account_name == "Checking"
    assert caught.value.available_minor == 10_000
    assert caught.value.shortfall_minor == 15_000


def test_an_empty_account_is_policed_too():
    """The tightened rule.

    An earlier version exempted accounts at or below zero, reasoning that a
    zero balance might just mean no opening balance was ever recorded. That let
    the *first* overdraft through on exactly the accounts most likely to be
    mistracked. The escape hatch is the workspace setting, not a hole in the
    rule.
    """
    membership = _workspace(block_overdrafts=True)
    with tenant_scope(membership.tenant_id):
        account, category = _seed(opening=0)
        with pytest.raises(fin.InsufficientFundsError):
            fin.record_expense(
                financial_account=account, category=category, amount_minor=100, occurred_at=WHEN
            )


def test_an_already_negative_account_is_policed_too():
    membership = _workspace(block_overdrafts=True)
    with tenant_scope(membership.tenant_id):
        account, category = _seed(opening=0)
        # Put it underwater by a route the guard doesn't police.
        fin.record_expense(
            financial_account=account,
            category=category,
            amount_minor=5_000,
            occurred_at=WHEN,
            source=TransactionSource.IMPORTED,
        )
        with pytest.raises(fin.InsufficientFundsError):
            fin.record_expense(
                financial_account=account, category=category, amount_minor=100, occurred_at=WHEN
            )


def test_spending_down_to_exactly_zero_is_allowed():
    """It is the step *past* the limit that is refused, not reaching it."""
    membership = _workspace(block_overdrafts=True)
    with tenant_scope(membership.tenant_id):
        account, category = _seed(opening=10_000)
        txn = fin.record_expense(
            financial_account=account, category=category, amount_minor=10_000, occurred_at=WHEN
        )
    assert txn.amount_minor == -10_000


def test_turning_the_setting_off_lets_the_same_posting_through():
    """The whole point of the setting: the household decides for itself."""
    membership = _workspace(block_overdrafts=False)
    with tenant_scope(membership.tenant_id):
        account, category = _seed(opening=10_000)
        txn = fin.record_expense(
            financial_account=account, category=category, amount_minor=25_000, occurred_at=WHEN
        )
    assert txn.amount_minor == -25_000


def test_an_arranged_overdraft_is_a_real_ceiling():
    """`overdraft_limit_minor` is the finer instrument: "police me, but I have
    an agreed facility of X"."""
    membership = _workspace(block_overdrafts=True)
    with tenant_scope(membership.tenant_id):
        account, category = _seed(opening=10_000)
        account.overdraft_limit_minor = 20_000
        account.save(update_fields=["overdraft_limit_minor"])

        # 10,000 held + 20,000 arranged = 30,000 available.
        ok = fin.record_expense(
            financial_account=account, category=category, amount_minor=30_000, occurred_at=WHEN
        )
        assert ok.amount_minor == -30_000

        with pytest.raises(fin.InsufficientFundsError):
            fin.record_expense(
                financial_account=account, category=category, amount_minor=1, occurred_at=WHEN
            )


def test_a_credit_card_is_never_policed():
    """Carrying a balance is what a credit card is for."""
    membership = _workspace(block_overdrafts=True)
    with tenant_scope(membership.tenant_id):
        card, category = _seed(opening=0, account_type=AccountType.CREDIT_CARD)
        txn = fin.record_expense(
            financial_account=card, category=category, amount_minor=25_000, occurred_at=WHEN
        )
    assert txn.amount_minor == -25_000


@pytest.mark.parametrize(
    "source", [TransactionSource.IMPORTED, TransactionSource.RECURRING, TransactionSource.RULE]
)
def test_only_hand_typed_postings_are_policed(source):
    """An import, a sync or a standing order records what already happened. The
    money moved whether or not the ledger likes it, and refusing would leave the
    books disagreeing with the bank."""
    membership = _workspace(block_overdrafts=True)
    with tenant_scope(membership.tenant_id):
        account, category = _seed(opening=10_000)
        txn = fin.record_expense(
            financial_account=account,
            category=category,
            amount_minor=25_000,
            occurred_at=WHEN,
            source=source,
        )
    assert txn.amount_minor == -25_000


def test_a_transfer_out_is_policed_like_an_expense():
    membership = _workspace(block_overdrafts=True)
    with tenant_scope(membership.tenant_id):
        source_account, _ = _seed(opening=10_000)
        destination = fin.create_financial_account(
            name="Savings", account_type=AccountType.SAVINGS, currency="USD"
        )
        with pytest.raises(fin.InsufficientFundsError):
            fin.record_transfer(
                from_account=source_account,
                to_account=destination,
                amount_minor=25_000,
                occurred_at=WHEN,
            )


# ------------------------------------------------------------------ the setting
def test_an_owner_can_read_and_change_the_setting_over_http():
    membership = _workspace(block_overdrafts=True)
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)

    listed = client.get("/api/v1/tenancy/workspaces/")
    assert listed.status_code == 200
    assert listed.data[0]["tenant"]["block_overdrafts"] is True

    updated = client.patch(
        f"/api/v1/tenancy/workspaces/{membership.tenant_id}/",
        {"block_overdrafts": False},
        format="json",
    )
    assert updated.status_code == 200, updated.data
    assert updated.data["block_overdrafts"] is False

    membership.tenant.refresh_from_db()
    assert membership.tenant.block_overdrafts is False


def test_the_refusal_reaches_the_client_with_the_figures_behind_it():
    """"Insufficient funds" alone leaves the user to work out which account and
    by how much, so the 422 carries both."""
    membership = _workspace(block_overdrafts=True)
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)
    acct = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Checking",
            "account_type": "checking",
            "currency": "USD",
            "opening_balance_minor": 10_000,
        },
        format="json",
    ).data
    cat = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).data

    over = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 25_000,
            "occurred_at": "2026-01-15T12:00:00Z",
        },
        format="json",
    )
    assert over.status_code == 422, over.data
    assert over.data["code"] == "insufficient_funds"
    assert over.data["account_name"] == "Checking"
    assert over.data["available_minor"] == 10_000
    assert over.data["shortfall_minor"] == 15_000
    assert "Checking" in over.data["detail"]


def test_changing_the_setting_never_rewrites_what_was_already_posted():
    """Turning the guard on afterwards does not retroactively reject history."""
    membership = _workspace(block_overdrafts=False)
    with tenant_scope(membership.tenant_id):
        account, category = _seed(opening=10_000)
        fin.record_expense(
            financial_account=account, category=category, amount_minor=25_000, occurred_at=WHEN
        )

    membership.tenant.block_overdrafts = True
    membership.tenant.save(update_fields=["block_overdrafts"])

    with tenant_scope(membership.tenant_id):
        from apps.finance.models import Transaction

        assert Transaction.objects.filter(amount_minor=-25_000).exists()
        # …but the next one is refused.
        with pytest.raises(fin.InsufficientFundsError):
            fin.record_expense(
                financial_account=account, category=category, amount_minor=100, occurred_at=WHEN
            )

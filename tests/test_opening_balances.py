"""Opening balances, account lifecycle, and reporting inclusion.

The tests that matter most here are the ledger-integrity ones. An opening
balance is the first number a user enters and every balance, net-worth figure
and reconciliation downstream inherits it — so it has to be a real, balanced,
auditable journal entry, not a stored column.
"""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from apps.finance import selectors as finance_selectors
from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.ledger.models import AccountKind, Direction, JournalEntry, LedgerLine
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


# --------------------------------------------------------------- opening balances
def test_opening_balance_posts_a_real_balanced_journal_entry(tenant):
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Everyday Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=3_250_00,
        )

        entry = JournalEntry.objects.get(idempotency_key=f"opening:{account.id}")
        lines = list(LedgerLine.objects.filter(entry=entry))

        # Double-entry: two lines, equal and opposite.
        assert len(lines) == 2
        debits = sum(ln.amount_minor for ln in lines if ln.direction == Direction.DEBIT)
        credits = sum(ln.amount_minor for ln in lines if ln.direction == Direction.CREDIT)
        assert debits == credits == 3_250_00


def test_asset_opening_balance_debits_the_account_and_credits_equity(tenant):
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Savings", account_type=AccountType.SAVINGS, currency="USD", opening_balance_minor=10_000_00
        )
        entry = JournalEntry.objects.get(idempotency_key=f"opening:{account.id}")

        asset_line = LedgerLine.objects.get(entry=entry, account_id=account.ledger_account_id)
        equity_line = LedgerLine.objects.exclude(account_id=account.ledger_account_id).get(entry=entry)

        # You have it: the asset is debited, and it came from equity.
        assert asset_line.direction == Direction.DEBIT
        assert equity_line.direction == Direction.CREDIT
        assert equity_line.account.kind == AccountKind.EQUITY
        assert finance_selectors.account_current_balance_minor(account) == 10_000_00


def test_liability_opening_balance_credits_the_account_and_debits_equity(tenant):
    with tenant_scope(tenant):
        card = finance_services.create_financial_account(
            name="Travel Card",
            account_type=AccountType.CREDIT_CARD,
            currency="USD",
            opening_balance_minor=1_200_00,
        )
        entry = JournalEntry.objects.get(idempotency_key=f"opening:{card.id}")

        liability_line = LedgerLine.objects.get(entry=entry, account_id=card.ledger_account_id)
        equity_line = LedgerLine.objects.exclude(account_id=card.ledger_account_id).get(entry=entry)

        # You owe it: the liability is credited, balanced against equity.
        assert liability_line.direction == Direction.CREDIT
        assert equity_line.direction == Direction.DEBIT
        assert finance_selectors.account_current_balance_minor(card) == 1_200_00


def test_opening_balance_is_idempotent(tenant):
    """A retried request must never post the opening balance twice."""
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Cash", account_type=AccountType.CASH, currency="USD", opening_balance_minor=500_00
        )
        finance_services.set_opening_balance(financial_account=account, amount_minor=500_00)
        finance_services.set_opening_balance(financial_account=account, amount_minor=500_00)

        assert JournalEntry.objects.filter(idempotency_key=f"opening:{account.id}").count() == 1
        assert finance_selectors.account_current_balance_minor(account) == 500_00


def test_zero_opening_balance_posts_nothing(tenant):
    """An empty account is the normal case; it shouldn't litter the ledger."""
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="New Account", account_type=AccountType.CHECKING, currency="USD"
        )
        assert JournalEntry.objects.filter(idempotency_key=f"opening:{account.id}").count() == 0
        assert finance_selectors.account_current_balance_minor(account) == 0


def test_negative_opening_balance_is_rejected(tenant):
    """Direction comes from the account type, so a signed amount is ambiguous —
    and ambiguity here is how sign-flip bugs reach production."""
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        with pytest.raises(finance_services.FinanceError):
            finance_services.set_opening_balance(financial_account=account, amount_minor=-100_00)


def test_opening_equity_account_is_reused_per_currency(tenant):
    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="A", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=100_00
        )
        finance_services.create_financial_account(
            name="B", account_type=AccountType.SAVINGS, currency="USD", opening_balance_minor=200_00
        )
        finance_services.create_financial_account(
            name="C", account_type=AccountType.CHECKING, currency="EUR", opening_balance_minor=300_00
        )

        from apps.ledger.models import Account as LedgerAccount

        equity = LedgerAccount.objects.filter(kind=AccountKind.EQUITY)
        # One shared equity account per currency, not one per financial account.
        assert equity.filter(currency="USD").count() == 1
        assert equity.filter(currency="EUR").count() == 1
        assert all(a.is_system for a in equity)


def test_opening_balance_respects_a_backdated_date(tenant):
    with tenant_scope(tenant):
        when = timezone.now() - timezone.timedelta(days=90)
        account = finance_services.create_financial_account(
            name="Old Account",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_00,
            opening_balance_at=when,
        )
        entry = JournalEntry.objects.get(idempotency_key=f"opening:{account.id}")
        assert entry.occurred_at == when


# ------------------------------------------------------------------- net worth
def test_opening_balances_flow_into_net_worth(tenant):
    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=5_000_00
        )
        finance_services.create_financial_account(
            name="Card",
            account_type=AccountType.CREDIT_CARD,
            currency="USD",
            opening_balance_minor=1_500_00,
        )

        usd = next(n for n in finance_selectors.net_worth() if n.currency == "USD")
        assert usd.assets_minor == 5_000_00
        assert usd.liabilities_minor == 1_500_00
        # Equity is the counterparty to those assets, not a third bucket.
        assert usd.net_minor == 3_500_00


def test_excluded_accounts_are_left_out_of_net_worth_but_keep_their_ledger(tenant):
    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="Personal", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=2_000_00
        )
        business = finance_services.create_financial_account(
            name="Business",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=9_000_00,
            include_in_net_worth=False,
        )

        usd = next(n for n in finance_selectors.net_worth() if n.currency == "USD")
        assert usd.assets_minor == 2_000_00
        # Exclusion is a reporting choice — the money is still fully recorded.
        assert finance_selectors.account_current_balance_minor(business) == 9_000_00


def test_archived_accounts_leave_net_worth(tenant):
    with tenant_scope(tenant):
        keep = finance_services.create_financial_account(
            name="Keep", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=1_000_00
        )
        closed = finance_services.create_financial_account(
            name="Closed", account_type=AccountType.SAVINGS, currency="USD", opening_balance_minor=4_000_00
        )

        assert next(n for n in finance_selectors.net_worth() if n.currency == "USD").assets_minor == 5_000_00

        finance_services.archive_financial_account(financial_account=closed)

        usd = next(n for n in finance_selectors.net_worth() if n.currency == "USD")
        assert usd.assets_minor == 1_000_00
        assert finance_selectors.account_current_balance_minor(keep) == 1_000_00


# ------------------------------------------------------------------- lifecycle
def test_archiving_preserves_history_and_is_reversible(tenant):
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Old Card",
            account_type=AccountType.CREDIT_CARD,
            currency="USD",
            opening_balance_minor=300_00,
        )
        entries_before = JournalEntry.objects.count()

        finance_services.archive_financial_account(financial_account=account)
        account.refresh_from_db()
        assert account.is_archived is True
        assert account.is_active is False
        # Archiving is not deletion: nothing in the ledger moved.
        assert JournalEntry.objects.count() == entries_before
        assert finance_selectors.account_current_balance_minor(account) == 300_00

        finance_services.unarchive_financial_account(financial_account=account)
        account.refresh_from_db()
        assert account.is_archived is False
        assert account.is_active is True


def test_update_allows_presentation_but_never_currency_or_type(tenant):
    """Currency and type are baked into every posted ledger line; letting them
    change would silently invalidate history."""
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        finance_services.update_financial_account(
            financial_account=account,
            name="Everyday Checking",
            color="#5558d9",
            icon="landmark",
            notes="Joint account with Sam.",
            is_hidden=True,
            currency="EUR",
            account_type=AccountType.SAVINGS,
        )
        account.refresh_from_db()

        assert account.name == "Everyday Checking"
        assert account.color == "#5558d9"
        assert account.notes == "Joint account with Sam."
        assert account.is_hidden is True
        # Ignored, not applied.
        assert account.currency == "USD"
        assert account.account_type == AccountType.CHECKING


def test_hidden_accounts_still_count_toward_net_worth(tenant):
    """Hiding is a UI preference; excluding is arithmetic. They must not be
    conflated, or a user tidying their sidebar would silently change their
    reported net worth."""
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Tucked Away",
            account_type=AccountType.SAVINGS,
            currency="USD",
            opening_balance_minor=750_00,
        )
        finance_services.update_financial_account(financial_account=account, is_hidden=True)

        usd = next(n for n in finance_selectors.net_worth() if n.currency == "USD")
        assert usd.assets_minor == 750_00

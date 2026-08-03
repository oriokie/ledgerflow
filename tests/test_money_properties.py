"""Property-based tests for money arithmetic.

Every function here is already covered by example-based tests. That is the
point: examples prove a function works for the inputs someone thought of, and
money arithmetic fails on the inputs nobody thought of — the rounding boundary,
the discount that exceeds the subtotal, the credit that exactly covers the bill.

The A-1 accessibility finding earlier in this project makes the case. Contrast
was verified against two chosen colours and passed; computing it across the
whole palette showed income text at 2.86:1, roughly half the required ratio.
The example was not wrong, it was just not the failing one.

Each test below states an invariant that must hold for *any* input in range,
so a counterexample is found by search rather than by imagination. Hypothesis
shrinks failures to a minimal case and records them in `.hypothesis/` so a
regression re-runs the exact input that broke.

Bounds are deliberate, not decorative: `MINOR` caps at ~92 trillion minor units
because `amount_minor` is a `BigIntegerField`, and generating beyond the column
would test Postgres rather than the arithmetic.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from apps.billing import invoicing, promotions
from apps.billing.promotions_models import Coupon, CouponKind

pytestmark = pytest.mark.django_db

#: Money values within the column's range. Non-negative because every caller
#: takes a magnitude and a direction rather than a signed amount.
MINOR = st.integers(min_value=0, max_value=92_000_000_000_000)
#: Amounts a real invoice line might carry — keeps the arithmetic tests fast
#: while still crossing every rounding boundary that matters.
LINE = st.integers(min_value=1, max_value=10_000_000)
BPS = st.integers(min_value=0, max_value=10_000)

#: Database-backed property tests need a wider deadline than the default 200ms
#: and must not be flagged for reusing the function-scoped db fixture.
DB_SETTINGS = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ============================================================ invoice totals
@DB_SETTINGS
@given(subtotal=LINE, discount=MINOR, tax_bps=BPS)
def test_an_invoice_total_is_never_negative(subtotal, discount, tax_bps):
    """A discount larger than the bill must produce zero, never a debt owed to
    the customer via the invoice table."""
    invoice = invoicing.create_invoice(
        tenant_id=uuid.uuid4(),
        currency="USD",
        line_items=[invoicing.LineItemSpec(description="x", amount_minor=subtotal)],
        discount_minor=discount,
        tax_rate_bps=tax_bps,
    )
    assert invoice.total_minor >= 0
    assert invoice.discount_minor <= invoice.subtotal_minor


@DB_SETTINGS
@given(subtotal=LINE, discount=MINOR, tax_bps=BPS)
def test_invoice_arithmetic_is_internally_consistent(subtotal, discount, tax_bps):
    """The identity the whole document rests on:

        total = (subtotal − discount − credit) + tax

    Stated as a property because the ordering is the part that goes wrong —
    taxing before discounting overcharges, and no single example makes that
    visible across every rate.
    """
    invoice = invoicing.create_invoice(
        tenant_id=uuid.uuid4(),
        currency="USD",
        line_items=[invoicing.LineItemSpec(description="x", amount_minor=subtotal)],
        discount_minor=discount,
        tax_rate_bps=tax_bps,
    )
    taxable = invoice.subtotal_minor - invoice.discount_minor - invoice.credit_minor
    assert invoice.total_minor == taxable + invoice.tax_minor


@DB_SETTINGS
@given(subtotal=LINE, tax_bps=BPS)
def test_tax_never_exceeds_the_taxable_amount_at_or_below_100_percent(subtotal, tax_bps):
    invoice = invoicing.create_invoice(
        tenant_id=uuid.uuid4(),
        currency="USD",
        line_items=[invoicing.LineItemSpec(description="x", amount_minor=subtotal)],
        tax_rate_bps=tax_bps,
    )
    assert invoice.tax_minor <= invoice.subtotal_minor


@DB_SETTINGS
@given(lines=st.lists(LINE, min_size=1, max_size=8))
def test_the_subtotal_is_exactly_the_sum_of_its_lines(lines):
    """No rounding may creep in between the lines and the subtotal — a document
    whose parts do not add to its total is unusable to an accountant."""
    invoice = invoicing.create_invoice(
        tenant_id=uuid.uuid4(),
        currency="USD",
        line_items=[
            invoicing.LineItemSpec(description=f"line {i}", amount_minor=amount)
            for i, amount in enumerate(lines)
        ],
    )
    assert invoice.subtotal_minor == sum(lines)


# ================================================================== credits
@DB_SETTINGS
@given(credit=LINE, bill=LINE)
def test_credit_applied_never_exceeds_the_credit_available_or_the_bill(credit, bill):
    """The double-spend guard, stated as a property: whatever is consumed must
    be no more than existed and no more than was owed."""
    tenant = uuid.uuid4()
    invoicing.issue_credit(tenant_id=tenant, amount_minor=credit, currency="USD")
    invoice = invoicing.create_invoice(
        tenant_id=tenant,
        currency="USD",
        line_items=[invoicing.LineItemSpec(description="x", amount_minor=bill)],
    )
    assert invoice.credit_minor <= credit
    assert invoice.credit_minor <= bill


@DB_SETTINGS
@given(credit=LINE, bill=LINE)
def test_credit_is_conserved(credit, bill):
    """Spent plus remaining always equals issued. A credit balance that leaks
    is money quietly taken from a customer."""
    tenant = uuid.uuid4()
    invoicing.issue_credit(tenant_id=tenant, amount_minor=credit, currency="USD")
    invoice = invoicing.create_invoice(
        tenant_id=tenant,
        currency="USD",
        line_items=[invoicing.LineItemSpec(description="x", amount_minor=bill)],
    )
    remaining = invoicing.credit_balance(tenant_id=tenant, currency="USD")
    assert invoice.credit_minor + remaining == credit


@DB_SETTINGS
@given(credit=LINE, bill=LINE)
def test_voiding_an_invoice_restores_exactly_what_it_consumed(credit, bill):
    tenant = uuid.uuid4()
    invoicing.issue_credit(tenant_id=tenant, amount_minor=credit, currency="USD")
    invoice = invoicing.create_invoice(
        tenant_id=tenant,
        currency="USD",
        line_items=[invoicing.LineItemSpec(description="x", amount_minor=bill)],
    )
    invoicing.void_invoice(invoice=invoice, reason="property test")
    assert invoicing.credit_balance(tenant_id=tenant, currency="USD") == credit


# ================================================================== coupons
@given(amount=LINE, bps=BPS)
def test_a_percentage_discount_never_exceeds_the_amount(amount, bps):
    coupon = Coupon(code="P", name="P", kind=CouponKind.PERCENT, value=bps)
    discount = promotions.discount_for(coupon=coupon, amount_minor=amount)
    assert 0 <= discount <= amount


@given(amount=LINE, bps=st.integers(min_value=0, max_value=10_000))
def test_a_percentage_discount_is_monotonic_in_the_rate(amount, bps):
    """A larger percentage can never take less off. Sounds obvious; it is
    exactly the property a rounding change would break silently."""
    assume(bps < 10_000)
    smaller = promotions.discount_for(
        coupon=Coupon(code="A", name="A", kind=CouponKind.PERCENT, value=bps), amount_minor=amount
    )
    larger = promotions.discount_for(
        coupon=Coupon(code="B", name="B", kind=CouponKind.PERCENT, value=bps + 1),
        amount_minor=amount,
    )
    assert larger >= smaller


@given(amount=LINE, fixed=LINE)
def test_a_fixed_discount_is_capped_at_the_amount(amount, fixed):
    coupon = Coupon(code="F", name="F", kind=CouponKind.FIXED, value=fixed, currency="USD")
    discount = promotions.discount_for(coupon=coupon, amount_minor=amount, currency="USD")
    assert 0 <= discount <= amount


@given(amount=LINE)
def test_a_zero_rate_discount_takes_nothing(amount):
    coupon = Coupon(code="Z", name="Z", kind=CouponKind.PERCENT, value=0)
    assert promotions.discount_for(coupon=coupon, amount_minor=amount) == 0


@given(bps=BPS)
def test_no_discount_applies_to_a_zero_amount(bps):
    """Guards the free-plan path: a coupon on a £0 invoice must not produce a
    negative total or a credit out of nothing."""
    coupon = Coupon(code="P", name="P", kind=CouponKind.PERCENT, value=bps)
    assert promotions.discount_for(coupon=coupon, amount_minor=0) == 0


# ==================================================================== refunds
@DB_SETTINGS
@given(paid=LINE, first=LINE)
def test_refunds_can_never_exceed_the_payment(paid, first):
    """The over-refund guard as a property rather than the three examples that
    currently cover it."""
    from apps.billing import refunds
    from apps.billing.models import Payment, PaymentStatus

    payment = Payment.objects.create(
        tenant_id=uuid.uuid4(),
        amount_minor=paid,
        currency="USD",
        status=PaymentStatus.SUCCEEDED,
        provider="stripe",
        provider_ref=f"pi_{uuid.uuid4().hex[:12]}",
    )
    try:
        refunds.request_refund(payment=payment, amount_minor=first, reason="property test")
    except refunds.RefundError:
        # Refusing an over-refund is the correct outcome, not a failure.
        assume(first <= paid)
        raise

    assert refunds.refunded_minor(payment=payment) <= payment.amount_minor
    assert refunds.refundable_minor(payment=payment) == paid - first


# ======================================================== reconciliation
@DB_SETTINGS
@given(statement=st.integers(min_value=-10_000_000, max_value=10_000_000))
def test_the_reconciliation_difference_is_always_statement_minus_reconciled(statement):
    """The one number a reconciliation screen exists to produce."""
    from django.db import transaction as db_transaction

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant
    from apps.finance import reconciliation
    from apps.finance.models import FinancialAccount
    from tests.conftest import _bearer_client
    from tests.factories import MembershipFactory

    membership = MembershipFactory()
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)
    created = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Current", "account_type": "checking", "currency": "USD"},
        format="json",
    )
    assume(created.status_code in (200, 201))

    with db_transaction.atomic():
        bind_db_tenant(membership.tenant_id)
        with use_tenant(membership.tenant_id, actor_id=membership.user_id):
            account = FinancialAccount.objects.get(id=created.data["id"])
            summary = reconciliation.reconciliation_summary(
                account=account, statement_balance_minor=statement
            )

    assert summary.difference_minor == statement - summary.reconciled_minor
    assert summary.ledger_balance_minor == summary.reconciled_minor + summary.uncleared_minor

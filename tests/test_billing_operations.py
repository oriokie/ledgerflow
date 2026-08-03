"""Billing operations: invoicing, credits, refunds, coupons.

These cover the arithmetic and the state machines rather than the API surface —
the money rules are where a regression is expensive and silent.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing import invoicing, promotions, refunds
from apps.billing.invoicing_models import (
    Credit,
    CreditKind,
    Invoice,
    InvoiceStatus,
    RefundStatus,
)
from apps.billing.models import (
    BillingInterval,
    Payment,
    PaymentStatus,
    Plan,
    PlanTier,
)
from apps.billing.promotions_models import Coupon, CouponDuration, CouponKind
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _plan(**kwargs) -> Plan:
    defaults = dict(
        tier=PlanTier.PLUS,
        name="Plus",
        price_minor=1000,
        currency="USD",
        interval=BillingInterval.MONTHLY,
    )
    defaults.update(kwargs)
    return Plan.objects.create(**defaults)


def _line(amount=1000, description="Plus subscription"):
    return invoicing.LineItemSpec(description=description, amount_minor=amount)


def _payment(tenant_id, amount=1000, status=PaymentStatus.SUCCEEDED, provider="stripe"):
    return Payment.objects.create(
        tenant_id=tenant_id,
        amount_minor=amount,
        currency="USD",
        status=status,
        provider=provider,
        provider_ref=f"pi_{uuid.uuid4().hex[:12]}",
    )


# ------------------------------------------------------------------ numbering
def test_invoice_numbers_are_sequential_and_year_scoped():
    tenant = uuid.uuid4()
    first = invoicing.create_invoice(tenant_id=tenant, currency="USD", line_items=[_line()])
    second = invoicing.create_invoice(tenant_id=tenant, currency="USD", line_items=[_line()])

    year = timezone.now().year
    assert first.number == f"INV-{year}-000001"
    assert second.number == f"INV-{year}-000002"


def test_invoice_number_is_unique_across_tenants():
    a = invoicing.create_invoice(tenant_id=uuid.uuid4(), currency="USD", line_items=[_line()])
    b = invoicing.create_invoice(tenant_id=uuid.uuid4(), currency="USD", line_items=[_line()])
    assert a.number != b.number


# ------------------------------------------------------------------ arithmetic
def test_totals_apply_discount_then_credit_then_tax():
    """Order matters: taxing before discounting overcharges the customer."""
    tenant = uuid.uuid4()
    invoicing.issue_credit(tenant_id=tenant, amount_minor=200, currency="USD")

    invoice = invoicing.create_invoice(
        tenant_id=tenant,
        currency="USD",
        line_items=[_line(amount=1000)],
        discount_minor=100,
        tax_rate_bps=2000,  # 20%
        tax_label="VAT",
    )

    assert invoice.subtotal_minor == 1000
    assert invoice.discount_minor == 100
    assert invoice.credit_minor == 200
    # Tax is charged on 1000 - 100 - 200 = 700, so 140.
    assert invoice.tax_minor == 140
    assert invoice.total_minor == 840


def test_discount_cannot_exceed_the_subtotal():
    invoice = invoicing.create_invoice(
        tenant_id=uuid.uuid4(),
        currency="USD",
        line_items=[_line(amount=500)],
        discount_minor=900,
    )
    assert invoice.discount_minor == 500
    assert invoice.total_minor == 0


def test_invoice_requires_at_least_one_line():
    with pytest.raises(invoicing.InvoicingError):
        invoicing.create_invoice(tenant_id=uuid.uuid4(), currency="USD", line_items=[])


def test_invoice_cannot_be_due_before_it_is_issued():
    today = timezone.now().date()
    with pytest.raises(invoicing.InvoicingError):
        invoicing.create_invoice(
            tenant_id=uuid.uuid4(),
            currency="USD",
            line_items=[_line()],
            issue_date=today,
            due_date=today - timedelta(days=1),
        )


# --------------------------------------------------------------------- credits
def test_credit_is_consumed_oldest_first():
    """Oldest-first because credits expire; spending a lapsing one first is
    strictly better for the customer."""
    tenant = uuid.uuid4()
    old = invoicing.issue_credit(tenant_id=tenant, amount_minor=300, currency="USD")
    new = invoicing.issue_credit(tenant_id=tenant, amount_minor=300, currency="USD")

    invoicing.create_invoice(tenant_id=tenant, currency="USD", line_items=[_line(amount=400)])

    old.refresh_from_db()
    new.refresh_from_db()
    assert old.remaining_minor == 0
    assert new.remaining_minor == 200


def test_expired_credit_is_not_consumed():
    tenant = uuid.uuid4()
    invoicing.issue_credit(
        tenant_id=tenant,
        amount_minor=500,
        currency="USD",
        expires_at=timezone.now() - timedelta(days=1),
    )
    invoice = invoicing.create_invoice(
        tenant_id=tenant, currency="USD", line_items=[_line(amount=400)]
    )
    assert invoice.credit_minor == 0


def test_credit_in_another_currency_is_not_consumed():
    tenant = uuid.uuid4()
    invoicing.issue_credit(tenant_id=tenant, amount_minor=500, currency="KES")
    invoice = invoicing.create_invoice(
        tenant_id=tenant, currency="USD", line_items=[_line(amount=400)]
    )
    assert invoice.credit_minor == 0


def test_voiding_an_invoice_returns_the_credit_it_consumed():
    tenant = uuid.uuid4()
    credit = invoicing.issue_credit(tenant_id=tenant, amount_minor=500, currency="USD")
    invoice = invoicing.create_invoice(
        tenant_id=tenant, currency="USD", line_items=[_line(amount=400)]
    )
    credit.refresh_from_db()
    assert credit.remaining_minor == 100

    invoicing.void_invoice(invoice=invoice, reason="Billed in error")

    credit.refresh_from_db()
    invoice.refresh_from_db()
    assert credit.remaining_minor == 500
    assert invoice.status == InvoiceStatus.CANCELLED
    assert invoice.credit_minor == 0


def test_credit_balance_ignores_voided_and_spent_credit():
    tenant = uuid.uuid4()
    invoicing.issue_credit(tenant_id=tenant, amount_minor=100, currency="USD")
    voided = invoicing.issue_credit(tenant_id=tenant, amount_minor=900, currency="USD")
    invoicing.void_credit(credit=voided, reason="issued to the wrong account")

    assert invoicing.credit_balance(tenant_id=tenant, currency="USD") == 100


def test_voiding_a_credit_leaves_already_spent_amounts_alone():
    tenant = uuid.uuid4()
    credit = invoicing.issue_credit(tenant_id=tenant, amount_minor=500, currency="USD")
    invoice = invoicing.create_invoice(
        tenant_id=tenant, currency="USD", line_items=[_line(amount=200)]
    )
    invoicing.void_credit(credit=credit)

    invoice.refresh_from_db()
    # The 200 already applied to an issued invoice stays applied.
    assert invoice.credit_minor == 200


# ------------------------------------------------------------------- lifecycle
def test_only_a_draft_can_be_issued():
    invoice = invoicing.create_invoice(
        tenant_id=uuid.uuid4(), currency="USD", line_items=[_line()]
    )
    invoicing.issue_invoice(invoice=invoice)
    with pytest.raises(invoicing.InvoicingError):
        invoicing.issue_invoice(invoice=invoice)


def test_partial_payment_leaves_the_invoice_open():
    invoice = invoicing.create_invoice(
        tenant_id=uuid.uuid4(), currency="USD", line_items=[_line(amount=1000)]
    )
    invoicing.issue_invoice(invoice=invoice)
    invoicing.mark_paid(invoice=invoice, amount_minor=400)

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.PENDING
    assert invoice.amount_due_minor == 600


def test_payments_accumulate_to_settle_an_invoice():
    invoice = invoicing.create_invoice(
        tenant_id=uuid.uuid4(), currency="USD", line_items=[_line(amount=1000)]
    )
    invoicing.issue_invoice(invoice=invoice)
    invoicing.mark_paid(invoice=invoice, amount_minor=400)
    invoicing.mark_paid(invoice=invoice, amount_minor=600)

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.PAID
    assert invoice.paid_at is not None


def test_a_fully_credited_invoice_settles_itself():
    """Nothing to collect means it must not enter the dunning queue."""
    tenant = uuid.uuid4()
    invoicing.issue_credit(tenant_id=tenant, amount_minor=1000, currency="USD")
    invoice = invoicing.create_invoice(
        tenant_id=tenant,
        currency="USD",
        line_items=[_line(amount=1000)],
        status=InvoiceStatus.PENDING,
    )
    invoice.refresh_from_db()
    assert invoice.total_minor == 0
    assert invoice.status == InvoiceStatus.PAID


def test_a_paid_invoice_cannot_be_voided():
    invoice = invoicing.create_invoice(
        tenant_id=uuid.uuid4(), currency="USD", line_items=[_line()]
    )
    invoicing.issue_invoice(invoice=invoice)
    invoicing.mark_paid(invoice=invoice)
    with pytest.raises(invoicing.InvoicingError):
        invoicing.void_invoice(invoice=invoice)


def test_mark_overdue_moves_only_past_due_pending_invoices():
    tenant = uuid.uuid4()
    today = timezone.now().date()

    overdue = invoicing.create_invoice(
        tenant_id=tenant,
        currency="USD",
        line_items=[_line()],
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=16),
    )
    invoicing.issue_invoice(invoice=overdue)

    current = invoicing.create_invoice(tenant_id=tenant, currency="USD", line_items=[_line()])
    invoicing.issue_invoice(invoice=current)

    moved = invoicing.mark_overdue()

    overdue.refresh_from_db()
    current.refresh_from_db()
    assert moved == 1
    assert overdue.status == InvoiceStatus.OVERDUE
    assert current.status == InvoiceStatus.PENDING


def test_subscription_invoicing_is_idempotent_per_period():
    """Replaying a billing sweep must not bill the customer twice."""
    from apps.billing import services as billing

    tenant = uuid.uuid4()
    plan = _plan(price_minor=0)  # free plan activates without a provider
    sub = billing.subscribe(tenant_id=tenant, plan=plan)

    first = invoicing.invoice_for_subscription_period(subscription=sub)
    second = invoicing.invoice_for_subscription_period(subscription=sub)

    assert first.id == second.id
    assert Invoice.objects.filter(subscription=sub).count() == 1


def test_reconcile_rejects_a_currency_mismatch():
    tenant = uuid.uuid4()
    invoice = invoicing.create_invoice(
        tenant_id=tenant, currency="USD", line_items=[_line()]
    )
    invoicing.issue_invoice(invoice=invoice)
    payment = _payment(tenant)
    payment.currency = "KES"
    payment.save(update_fields=["currency"])

    with pytest.raises(invoicing.InvoicingError):
        invoicing.reconcile_payment(payment=payment, invoice=invoice)


# --------------------------------------------------------------------- refunds
def test_refund_requires_a_reason():
    tenant = uuid.uuid4()
    payment = _payment(tenant)
    with pytest.raises(refunds.RefundError):
        refunds.request_refund(payment=payment, reason="   ")


def test_only_a_succeeded_payment_can_be_refunded():
    tenant = uuid.uuid4()
    payment = _payment(tenant, status=PaymentStatus.FAILED)
    with pytest.raises(refunds.RefundError):
        refunds.request_refund(payment=payment, reason="Customer asked")


def test_refund_defaults_to_the_remaining_balance():
    tenant = uuid.uuid4()
    payment = _payment(tenant, amount=1000)
    requester, approver = UserFactory(), UserFactory()

    partial = refunds.request_refund(
        payment=payment, amount_minor=300, reason="Partial", requested_by=requester
    )
    refunds.approve_refund(refund=partial, approved_by=approver)

    rest = refunds.request_refund(payment=payment, reason="The rest", requested_by=requester)
    assert rest.amount_minor == 700


def test_refunds_cannot_exceed_the_payment():
    tenant = uuid.uuid4()
    payment = _payment(tenant, amount=1000)
    with pytest.raises(refunds.RefundError):
        refunds.request_refund(payment=payment, amount_minor=1500, reason="Too much")


def test_in_flight_refunds_count_against_the_refundable_balance():
    """Two agents each refunding 'the remaining half' must not pay out 150%."""
    tenant = uuid.uuid4()
    payment = _payment(tenant, amount=1000)

    refunds.request_refund(payment=payment, amount_minor=600, reason="First")
    # Still only REQUESTED — not yet approved, let alone settled.
    assert refunds.refundable_minor(payment=payment) == 400

    with pytest.raises(refunds.RefundError):
        refunds.request_refund(payment=payment, amount_minor=600, reason="Second")


def test_approval_by_the_requester_is_refused():
    """The RBAC split is meaningless if one person can satisfy it alone."""
    tenant = uuid.uuid4()
    payment = _payment(tenant)
    person = UserFactory()
    refund = refunds.request_refund(payment=payment, reason="Duplicate charge", requested_by=person)

    with pytest.raises(refunds.RefundError):
        refunds.approve_refund(refund=refund, approved_by=person)


def test_approved_refund_settles_and_marks_the_payment_refunded():
    tenant = uuid.uuid4()
    payment = _payment(tenant, amount=1000)
    refund = refunds.request_refund(
        payment=payment, reason="Service outage", requested_by=UserFactory()
    )
    refunds.approve_refund(refund=refund, approved_by=UserFactory())

    refund.refresh_from_db()
    payment.refresh_from_db()
    assert refund.status == RefundStatus.SUCCEEDED
    assert payment.status == PaymentStatus.REFUNDED


def test_partial_refund_leaves_the_payment_succeeded():
    tenant = uuid.uuid4()
    payment = _payment(tenant, amount=1000)
    refund = refunds.request_refund(
        payment=payment, amount_minor=250, reason="Goodwill", requested_by=UserFactory()
    )
    refunds.approve_refund(refund=refund, approved_by=UserFactory())

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCEEDED


def test_rejected_refund_frees_the_balance_again():
    tenant = uuid.uuid4()
    payment = _payment(tenant, amount=1000)
    refund = refunds.request_refund(payment=payment, amount_minor=1000, reason="Maybe")
    refunds.reject_refund(refund=refund, approved_by=UserFactory(), note="Out of policy")

    assert refunds.refundable_minor(payment=payment) == 1000


def test_mpesa_refund_stays_pending_until_the_provider_confirms():
    """Reporting success before Safaricom agrees would lie to the customer."""
    tenant = uuid.uuid4()
    payment = _payment(tenant, amount=1000, provider="mpesa")
    refund = refunds.request_refund(
        payment=payment, reason="Reversal", requested_by=UserFactory()
    )
    refunds.approve_refund(refund=refund, approved_by=UserFactory())

    refund.refresh_from_db()
    payment.refresh_from_db()
    assert refund.status == RefundStatus.PROCESSING
    assert payment.status == PaymentStatus.SUCCEEDED


def test_webhook_settles_a_processing_refund():
    tenant = uuid.uuid4()
    payment = _payment(tenant, amount=1000, provider="mpesa")
    refund = refunds.request_refund(payment=payment, reason="Reversal")
    refunds.approve_refund(refund=refund, approved_by=UserFactory())
    refund.refresh_from_db()

    refunds.settle_pending_refund(provider_ref=refund.provider_ref, succeeded=True)

    refund.refresh_from_db()
    payment.refresh_from_db()
    assert refund.status == RefundStatus.SUCCEEDED
    assert payment.status == PaymentStatus.REFUNDED


def test_unknown_refund_reference_is_ignored_not_raised():
    """Providers emit events for objects we didn't create."""
    assert refunds.settle_pending_refund(provider_ref="re_unknown", succeeded=True) is None


# --------------------------------------------------------------------- coupons
def _coupon(**kwargs) -> Coupon:
    defaults = dict(code="SAVE20", name="Spring 20%", kind=CouponKind.PERCENT, value=2000)
    defaults.update(kwargs)
    return Coupon.objects.create(**defaults)


def test_coupon_codes_are_normalised_to_uppercase():
    coupon = _coupon(code=" spring20 ")
    assert coupon.code == "SPRING20"
    assert promotions.find_coupon("Spring20") == coupon


def test_percentage_discount_is_computed_from_basis_points():
    assert promotions.discount_for(coupon=_coupon(value=2500), amount_minor=1000) == 250


def test_percentage_discount_never_exceeds_the_amount():
    assert promotions.discount_for(coupon=_coupon(value=20000), amount_minor=1000) == 1000


def test_fixed_discount_refuses_a_currency_mismatch():
    """An FX rate must not silently change a promised discount."""
    coupon = _coupon(code="TENOFF", kind=CouponKind.FIXED, value=1000, currency="USD")
    with pytest.raises(promotions.CouponError):
        promotions.discount_for(coupon=coupon, amount_minor=5000, currency="KES")


def test_non_monetary_coupons_discount_nothing():
    trial = _coupon(code="EXTRA14", kind=CouponKind.TRIAL_EXTENSION, value=14)
    assert promotions.discount_for(coupon=trial, amount_minor=1000) == 0
    assert promotions.bonus_days(coupon=trial) == 14


def test_expired_coupon_explains_itself():
    coupon = _coupon(expires_at=timezone.now() - timedelta(days=3))
    result = promotions.check_eligibility(coupon=coupon, tenant_id=uuid.uuid4())
    assert not result.ok
    assert "expired" in result.reason.lower()


def test_country_restriction_is_enforced():
    coupon = _coupon(allowed_countries=["KE", "UG"])
    assert not promotions.check_eligibility(
        coupon=coupon, tenant_id=uuid.uuid4(), country="US"
    ).ok
    assert promotions.check_eligibility(coupon=coupon, tenant_id=uuid.uuid4(), country="ke").ok


def test_plan_restriction_is_enforced():
    allowed, other = _plan(name="Plus"), _plan(tier=PlanTier.FAMILY, name="Family")
    coupon = _coupon()
    coupon.applies_to_plans.add(allowed)

    assert promotions.check_eligibility(coupon=coupon, tenant_id=uuid.uuid4(), plan=allowed).ok
    assert not promotions.check_eligibility(coupon=coupon, tenant_id=uuid.uuid4(), plan=other).ok


def test_per_tenant_limit_blocks_a_second_redemption():
    tenant = uuid.uuid4()
    coupon = _coupon()
    promotions.redeem(coupon=coupon, tenant_id=tenant, discount_minor=200, currency="USD")

    result = promotions.check_eligibility(coupon=coupon, tenant_id=tenant)
    assert not result.ok
    assert "already used" in result.reason.lower()


def test_global_redemption_limit_exhausts_a_coupon():
    coupon = _coupon(max_redemptions=1)
    promotions.redeem(coupon=coupon, tenant_id=uuid.uuid4(), discount_minor=200, currency="USD")

    coupon.refresh_from_db()
    assert coupon.is_exhausted
    with pytest.raises(promotions.CouponError):
        promotions.redeem(coupon=coupon, tenant_id=uuid.uuid4(), discount_minor=200, currency="USD")


def test_repeating_coupon_stays_active_for_its_duration():
    tenant = uuid.uuid4()
    coupon = _coupon(duration=CouponDuration.REPEATING, duration_in_months=3)
    redemption = promotions.redeem(
        coupon=coupon, tenant_id=tenant, discount_minor=200, currency="USD"
    )

    assert promotions.active_redemption(tenant_id=tenant) is not None
    promotions.consume_period(redemption=redemption)
    promotions.consume_period(redemption=redemption)
    assert promotions.active_redemption(tenant_id=tenant) is None


def test_once_coupon_does_not_discount_a_later_period():
    tenant = uuid.uuid4()
    coupon = _coupon(duration=CouponDuration.ONCE)
    promotions.redeem(coupon=coupon, tenant_id=tenant, discount_minor=200, currency="USD")
    assert promotions.active_redemption(tenant_id=tenant) is None


def test_forever_coupon_never_lapses():
    tenant = uuid.uuid4()
    coupon = _coupon(duration=CouponDuration.FOREVER)
    redemption = promotions.redeem(
        coupon=coupon, tenant_id=tenant, discount_minor=200, currency="USD"
    )
    for _ in range(5):
        promotions.consume_period(redemption=redemption)
    assert promotions.active_redemption(tenant_id=tenant) is not None


def test_credit_kind_is_recorded_for_reporting():
    credit = invoicing.issue_credit(
        tenant_id=uuid.uuid4(),
        amount_minor=500,
        currency="USD",
        kind=CreditKind.REFUND_OFFSET,
        reason="Outage compensation",
    )
    assert Credit.objects.get(pk=credit.pk).kind == CreditKind.REFUND_OFFSET

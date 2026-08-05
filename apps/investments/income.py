"""What an income-producing holding is expected to pay, and what it actually did.

The whole module turns on one distinction, and it is the same one the health
score and the income module draw: **what may be projected, and what may only be
reported after the fact.**

A bond's coupon is contractual — rate, face and dates are fixed at issue, so
the next payment can be stated before it happens. A money-market fund's yield is
reset continuously by its manager, and a SACCO's dividend is whatever the AGM
declares. For those two, last period's figure is a *measurement*, and quoting it
forward as though it were a schedule is exactly the error this file exists to
prevent.

So: `coupon_schedule` refuses to draw anything for a non-COUPON instrument, and
`realised_yield_bp` exists to answer the question those instruments *can*
answer — "what has this actually paid me?" — from real distributions only.

No Django here. Dates and money in, dates and money out, so the arithmetic can
be tested without a database and cannot quietly read a model it wasn't given.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

#: Payments per year, keyed by the same strings as `models.PaymentFrequency`.
#: Duplicated deliberately rather than imported: this module must stay free of
#: Django, and a test asserts the two agree so they cannot drift.
PAYMENTS_PER_YEAR: dict[str, int] = {
    "monthly": 12,
    "quarterly": 4,
    "semiannual": 2,
    "annual": 1,
}

_MONTHS_BETWEEN = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}

BASIS_POINTS = 10_000


@dataclass(frozen=True, slots=True)
class ScheduledPayment:
    """One expected payment. `is_final` marks the maturity date."""

    on_date: date
    #: Coupon interest due on this date.
    interest_minor: int
    #: Principal returned on this date — a scheduled partial redemption, or
    #: everything still outstanding if this is maturity.
    principal_minor: int
    #: Principal still outstanding *after* this payment.
    outstanding_minor: int
    is_final: bool

    @property
    def total_minor(self) -> int:
        return self.interest_minor + self.principal_minor


def coupon_schedule(
    *,
    face_value_minor: int,
    quantity: Decimal | int,
    coupon_rate_bp: int,
    payment_frequency: str,
    issued_on: date,
    matures_on: date,
    redemptions: list[tuple[date, int]] | None = None,
    from_date: date | None = None,
) -> list[ScheduledPayment]:
    """Every remaining payment on a fixed-coupon instrument.

    Interest is charged on the principal *still outstanding*, which is what
    makes a partial redemption matter: repay 20% in year three and every coupon
    after it is 20% smaller. Computing coupons off the original face — the
    obvious shortcut — overstates the income of any amortising bond for its
    entire remaining life.

    `redemptions` are `(date, portion_bp)` pairs against the **original**
    principal, matching how offer documents state them. Maturity is not among
    them: whatever is left on `matures_on` is returned then, so the two can
    never disagree about the final payment.

    Returns an empty list once the instrument has matured. Refusing to invent
    payments past maturity is the same refusal as refusing to project a
    variable rate.
    """
    if payment_frequency not in _MONTHS_BETWEEN:
        raise ValueError(f"Unknown payment frequency {payment_frequency!r}.")
    if matures_on < issued_on:
        raise ValueError("An instrument cannot mature before it was issued.")

    original = int(face_value_minor * Decimal(quantity))
    if original <= 0:
        return []

    from_date = from_date or issued_on
    step = _MONTHS_BETWEEN[payment_frequency]
    per_year = PAYMENTS_PER_YEAR[payment_frequency]

    # Redemptions, oldest first, so principal can be drawn down in order.
    pending = sorted(redemptions or [])

    payments: list[ScheduledPayment] = []
    outstanding = original
    cursor = issued_on + relativedelta(months=step)

    while cursor <= matures_on and outstanding > 0:
        # Any redemption falling in this period reduces the principal *before*
        # the coupon on the next one, not this one: the holder earned interest
        # on that money right up to the day it was repaid.
        interest = int(Decimal(outstanding) * Decimal(coupon_rate_bp) / BASIS_POINTS / per_year)

        principal = 0
        while pending and pending[0][0] <= cursor:
            _, portion_bp = pending.pop(0)
            principal += int(Decimal(original) * Decimal(portion_bp) / BASIS_POINTS)

        is_final = cursor >= matures_on or (cursor + relativedelta(months=step)) > matures_on
        if is_final:
            # Everything still owed comes back, whatever the schedule said.
            principal = outstanding

        principal = min(principal, outstanding)
        outstanding -= principal

        if cursor >= from_date:
            payments.append(
                ScheduledPayment(
                    on_date=cursor,
                    interest_minor=interest,
                    principal_minor=principal,
                    outstanding_minor=outstanding,
                    is_final=is_final,
                )
            )

        if is_final:
            break
        cursor += relativedelta(months=step)

    return payments


def realised_yield_bp(
    *,
    distributions: list[tuple[date, int]],
    average_balance_minor: int,
    over_days: int,
) -> int | None:
    """What a holding has *actually* paid, annualised, in basis points.

    The answer for everything that cannot be scheduled. A money-market fund and
    a SACCO share both have a real yield; it simply is not knowable in advance,
    so it is measured backwards from money that genuinely arrived.

    None — never zero — when there is nothing to measure from: no
    distributions, no balance to divide by, or a window too short to annualise
    without inventing precision. A zero would read as "this paid nothing",
    which is a finding; "not enough history" is not.
    """
    if not distributions or average_balance_minor <= 0:
        return None
    # Under a month, annualising multiplies noise by twelve or more.
    if over_days < 28:
        return None

    total = sum(amount for _, amount in distributions)
    if total <= 0:
        return None

    annualised = Decimal(total) * Decimal(365) / Decimal(over_days)
    return int(annualised / Decimal(average_balance_minor) * BASIS_POINTS)


def next_payment(payments: list[ScheduledPayment], *, on_or_after: date) -> ScheduledPayment | None:
    """The soonest scheduled payment at or after a date, or None."""
    return next((p for p in payments if p.on_date >= on_or_after), None)

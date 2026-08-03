"""Detection engine — pure functions over transaction data.

No ORM, for the same reasons as `debt/payoff.py`: the logic here decides what
the product tells people about their own money, so it must be directly testable
without fixtures, and identically reproducible.

Everything returns a **suggestion with a confidence and a reason**, never an
action. Automation in a financial product proposes; a person disposes. The one
exception the product allows is a metadata change (a category) above a high
confidence bar, and even then the decision is recorded so it can be undone and
learned from.

The keystone is `normalize_merchant`. Card descriptors are hostile — the same
coffee shop arrives as `SQ *COFFEE HOUSE 1234`, `SQ*COFFEE HOUSE`, and
`COFFEE HOUSE LONDON 4471`. Until those collapse to one merchant, every other
detector here is working with noise: recurring detection misses a subscription
that changed descriptor, duplicate detection over-fires, and category learning
never accumulates enough examples to be useful.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Merchant normalisation
# ---------------------------------------------------------------------------

#: Payment processors and aggregators that prefix the real merchant name. The
#: descriptor belongs to the processor; the merchant is what follows.
_PROCESSOR_PREFIXES = (
    "sq *", "sq*", "square *",
    "tst*", "tst *",
    "paypal *", "pp*", "paypal*",
    "sumup *", "sumup*",
    "izettle *",
    "stripe *",
    "shopify *",
    "amzn mktp", "amazon mktpl", "amzn digital",
    "wl *", "wl*",
    "zettle_*", "zettle *",
)

#: Noise that survives the prefix strip: trailing reference codes, store
#: numbers, terminal ids, dates baked into the descriptor.
_NOISE_PATTERNS = (
    # Reference codes: mixed letters and digits, with either two or more
    # digits or a digit somewhere after the first character. That drops
    # "8XY2Z" and "1A2B3C" while keeping real names like "7Eleven".
    re.compile(r"\b(?=[a-z0-9]*\d[a-z0-9]*\d)[a-z0-9]{4,}\b"),
    re.compile(r"\b[a-z]+\d[a-z0-9]*\b"),
    # Standalone digit runs — store or terminal numbers.
    re.compile(r"\b\d{3,}\b"),
    # Dates embedded in the descriptor.
    re.compile(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b"),
    # Card-present markers and similar trailing cruft.
    re.compile(r"\b(pos|ecom|contactless|chip|debit|credit|purchase|payment|card)\b"),
    # Trailing country/currency codes.
    re.compile(r"\b(gb|gbr|uk|us|usa|eu|eur|usd|gbp)\b\s*$"),
)

#: Kept because they carry meaning a user would recognise.
_KEEP_WORDS = {"co", "ltd", "inc", "the"}

#: Descriptors where stripping the prefix would leave something meaningless.
#: "AMZN Mktp US*1A2B3C" reduces to "US", which tells the user nothing — the
#: merchant they recognise is Amazon, so it is named directly.
_CANONICAL = {
    "amzn mktp": "Amazon",
    "amazon mktpl": "Amazon",
    "amzn digital": "Amazon",
    "amzn": "Amazon",
    "wl": "WorldPay",
}


def normalize_merchant(raw: str) -> str:
    """Collapse a card descriptor to a recognisable merchant name.

    Conservative by design: it strips known noise rather than guessing at
    structure. Over-normalising is worse than under-normalising here — merging
    two genuinely different merchants silently corrupts every figure derived
    from the merged pair, while leaving them separate merely misses a
    convenience.

    Returns the original (trimmed) string when normalisation would leave
    nothing, because an empty merchant name is worse than an ugly one.
    """
    if not raw:
        return ""

    text = raw.strip().lower()

    # A descriptor whose prefix *is* the merchant resolves directly, before any
    # stripping can reduce it to noise.
    for marker, canonical in sorted(_CANONICAL.items(), key=lambda kv: -len(kv[0])):
        if text.startswith(marker):
            return canonical

    # Strip processor prefixes, longest first so "amzn mktp" wins over "amzn".
    for prefix in sorted(_PROCESSOR_PREFIXES, key=len, reverse=True):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break

    text = re.sub(r"[*#]+", " ", text)
    for pattern in _NOISE_PATTERNS:
        text = pattern.sub(" ", text)

    text = re.sub(r"[^a-z0-9&' ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Drop trailing single characters left behind by stripping.
    words = [w for w in text.split() if len(w) > 1 or w in _KEEP_WORDS]
    cleaned = " ".join(words).strip()

    return cleaned.title() if cleaned else raw.strip()


def merchant_key(raw: str) -> str:
    """A stable grouping key for a merchant.

    Lowercased and space-free so trivial spacing differences group together,
    while remaining a pure function of the normalised name.
    """
    return re.sub(r"\s+", "", normalize_merchant(raw).lower())


# ---------------------------------------------------------------------------
# Shared shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Txn:
    """A transaction as the detectors see it.

    Signed `amount_minor`: negative is money out. The sign carries meaning for
    refund and transfer detection, so stripping it would lose the signal.
    """

    txn_id: str
    account_id: str
    occurred_on: date
    amount_minor: int
    merchant: str = ""
    category_id: str | None = None
    memo: str = ""

    @property
    def key(self) -> str:
        return merchant_key(self.merchant or self.memo)


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One proposal, with the evidence and reasoning behind it.

    `confidence` is 0–1 and is never rounded up for presentation. A suggestion
    the user cannot check is one they cannot trust, so `reason` is mandatory
    and states the actual observation rather than the rule name.
    """

    kind: str
    confidence: float
    reason: str
    txn_ids: tuple[str, ...]
    payload: dict = field(default_factory=dict)


class SuggestionKind:
    CATEGORY = "category"
    TRANSFER = "transfer"
    DUPLICATE = "duplicate"
    REFUND = "refund"
    RECURRING = "recurring"
    SPLIT = "split"
    INCOME = "income"


# ---------------------------------------------------------------------------
# Transfer detection
# ---------------------------------------------------------------------------

#: Two legs of one transfer rarely post the same day, but rarely more than a
#: few days apart either.
TRANSFER_WINDOW_DAYS = 4


def detect_transfers(txns: list[Txn]) -> list[Suggestion]:
    """Find pairs that are two legs of one movement between the user's accounts.

    A transfer is not income and not spending, and counting it as either
    inflates both sides of every cash-flow figure. That makes this the highest
    value detector in the module and also the one where a false positive costs
    most — so the criteria are strict: exact opposite amounts, different
    accounts, close dates.

    Amount equality is required rather than approximate. A near-match is far
    more likely to be two unrelated transactions than a transfer that lost
    money in flight, and pairing those would silently erase a real expense.
    """
    out: list[Suggestion] = []
    used: set[str] = set()

    outflows = sorted(
        (t for t in txns if t.amount_minor < 0), key=lambda t: (t.occurred_on, t.txn_id)
    )
    inflows = [t for t in txns if t.amount_minor > 0]

    for out_txn in outflows:
        if out_txn.txn_id in used:
            continue
        for in_txn in inflows:
            if in_txn.txn_id in used or in_txn.account_id == out_txn.account_id:
                continue
            if in_txn.amount_minor != -out_txn.amount_minor:
                continue
            gap = abs((in_txn.occurred_on - out_txn.occurred_on).days)
            if gap > TRANSFER_WINDOW_DAYS:
                continue

            # Same-day pairs are near-certain; the confidence tapers with the
            # gap because a week apart is more plausibly a coincidence.
            confidence = 0.95 if gap == 0 else max(0.7, 0.95 - gap * 0.06)
            out.append(
                Suggestion(
                    kind=SuggestionKind.TRANSFER,
                    confidence=round(confidence, 2),
                    reason=(
                        f"Equal and opposite amounts between two of your accounts"
                        + (" on the same day." if gap == 0 else f", {gap} day{'s' if gap > 1 else ''} apart.")
                    ),
                    txn_ids=(out_txn.txn_id, in_txn.txn_id),
                    payload={
                        "from_account_id": out_txn.account_id,
                        "to_account_id": in_txn.account_id,
                        "amount_minor": abs(out_txn.amount_minor),
                    },
                )
            )
            used.add(out_txn.txn_id)
            used.add(in_txn.txn_id)
            break
    return out


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

DUPLICATE_WINDOW_DAYS = 3


def detect_duplicates(txns: list[Txn]) -> list[Suggestion]:
    """Find transactions that may have been recorded twice.

    Deliberately reported as a *candidate*, never an assertion, and never
    auto-actioned. Two identical coffees on one day are entirely normal, and
    telling someone they were double-charged when they weren't costs more trust
    than the catch is worth.

    Same-day duplicates score higher than nearby ones, because a genuine
    double-post almost always lands together.
    """
    out: list[Suggestion] = []
    by_signature: dict[tuple, list[Txn]] = {}

    for txn in txns:
        if txn.amount_minor >= 0:
            continue  # a repeated credit is far more often legitimate
        by_signature.setdefault((txn.account_id, txn.amount_minor, txn.key), []).append(txn)

    for group in by_signature.values():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda t: (t.occurred_on, t.txn_id))
        for earlier, later in zip(group, group[1:]):
            gap = (later.occurred_on - earlier.occurred_on).days
            if gap > DUPLICATE_WINDOW_DAYS:
                continue
            confidence = 0.6 if gap == 0 else max(0.3, 0.6 - gap * 0.1)
            out.append(
                Suggestion(
                    kind=SuggestionKind.DUPLICATE,
                    confidence=round(confidence, 2),
                    reason=(
                        f"Same amount and merchant"
                        + (" on the same day." if gap == 0 else f", {gap} day{'s' if gap > 1 else ''} apart.")
                        + " Worth checking — repeats are often legitimate."
                    ),
                    txn_ids=(earlier.txn_id, later.txn_id),
                    payload={"amount_minor": abs(earlier.amount_minor), "gap_days": gap},
                )
            )
    return out


# ---------------------------------------------------------------------------
# Refund detection
# ---------------------------------------------------------------------------

REFUND_WINDOW_DAYS = 90


def detect_refunds(txns: list[Txn]) -> list[Suggestion]:
    """Match a credit against an earlier charge from the same merchant.

    Refunds matter because an unmatched credit reads as income, which inflates
    the savings rate and every figure derived from it. Linking the pair keeps
    both out of the income column where they belong.

    Requires the credit to come *after* the charge, which distinguishes a
    refund from a transfer or an unrelated payment.
    """
    out: list[Suggestion] = []
    charges = sorted(
        (t for t in txns if t.amount_minor < 0), key=lambda t: t.occurred_on, reverse=True
    )
    used: set[str] = set()

    for credit in sorted((t for t in txns if t.amount_minor > 0), key=lambda t: t.occurred_on):
        if not credit.key:
            continue
        for charge in charges:
            if charge.txn_id in used or charge.key != credit.key:
                continue
            if charge.occurred_on > credit.occurred_on:
                continue
            days = (credit.occurred_on - charge.occurred_on).days
            if days > REFUND_WINDOW_DAYS:
                continue

            exact = credit.amount_minor == -charge.amount_minor
            partial = credit.amount_minor < -charge.amount_minor
            if not (exact or partial):
                continue

            out.append(
                Suggestion(
                    kind=SuggestionKind.REFUND,
                    # A partial refund is plausible but weaker evidence than an
                    # exact reversal.
                    confidence=0.9 if exact else 0.65,
                    reason=(
                        f"Credit from {credit.merchant or 'the same merchant'} "
                        f"{days} day{'s' if days != 1 else ''} after a charge"
                        + (" for the same amount." if exact else " for part of the amount.")
                    ),
                    txn_ids=(charge.txn_id, credit.txn_id),
                    payload={
                        "charge_minor": abs(charge.amount_minor),
                        "refund_minor": credit.amount_minor,
                        "is_partial": partial,
                    },
                )
            )
            used.add(charge.txn_id)
            break
    return out


# ---------------------------------------------------------------------------
# Recurring detection
# ---------------------------------------------------------------------------

#: Cadences worth recognising, as (label, expected days, tolerance).
_CADENCES = (
    ("weekly", 7, 2),
    ("fortnightly", 14, 3),
    ("monthly", 30, 5),
    ("quarterly", 91, 10),
    ("yearly", 365, 20),
)

MIN_OCCURRENCES = 3


def detect_recurring(txns: list[Txn]) -> list[Suggestion]:
    """Find charges arriving on a regular cadence.

    Three occurrences is the minimum: two points define an interval but not a
    pattern, and calling a pair of coincidental charges a subscription would
    put a fictional commitment into the user's cash-flow projection.

    Amounts are allowed to drift slightly — subscriptions do change price — but
    the cadence must hold, because that is what distinguishes a subscription
    from a merchant someone simply visits often.
    """
    out: list[Suggestion] = []
    by_merchant: dict[str, list[Txn]] = {}
    for txn in txns:
        if txn.amount_minor < 0 and txn.key:
            by_merchant.setdefault(txn.key, []).append(txn)

    for key, group in by_merchant.items():
        if len(group) < MIN_OCCURRENCES:
            continue
        group = sorted(group, key=lambda t: t.occurred_on)
        gaps = [
            (later.occurred_on - earlier.occurred_on).days
            for earlier, later in zip(group, group[1:])
        ]
        if not gaps:
            continue
        average = sum(gaps) / len(gaps)

        for label, expected, tolerance in _CADENCES:
            if abs(average - expected) > tolerance:
                continue
            # Every gap must fit, not just the mean: alternating 1-day and
            # 59-day gaps average to monthly and are nothing of the sort.
            if any(abs(gap - expected) > tolerance * 1.5 for gap in gaps):
                continue

            amounts = [abs(t.amount_minor) for t in group]
            spread = (max(amounts) - min(amounts)) / max(amounts) if max(amounts) else 0
            confidence = 0.9 if spread < 0.02 else 0.75 if spread < 0.2 else 0.6

            out.append(
                Suggestion(
                    kind=SuggestionKind.RECURRING,
                    confidence=confidence,
                    reason=(
                        f"{len(group)} charges from {group[-1].merchant or 'this merchant'} "
                        f"about every {expected} days."
                        + ("" if spread < 0.02 else " The amount varies a little.")
                    ),
                    txn_ids=tuple(t.txn_id for t in group),
                    payload={
                        "merchant_key": key,
                        "cadence": label,
                        "average_gap_days": round(average, 1),
                        "typical_amount_minor": sorted(amounts)[len(amounts) // 2],
                        "occurrences": len(group),
                        # Enough to project the next occurrence. Without these
                        # an accepted detection could mark a merchant as
                        # recurring but never say *when* the next charge lands,
                        # which is the only part the forecast can use.
                        "last_seen": group[-1].occurred_on.isoformat(),
                        "expected_gap_days": expected,
                        "merchant": group[-1].merchant or "",
                    },
                )
            )
            break
    return out


# ---------------------------------------------------------------------------
# Income detection
# ---------------------------------------------------------------------------

INCOME_MIN_OCCURRENCES = 2


def detect_income(txns: list[Txn]) -> list[Suggestion]:
    """Identify regular credits that look like earnings.

    Distinguished from a refund by having no matching prior charge, and from a
    transfer by not having an opposite leg. This runs *after* those detectors
    for exactly that reason: what is left over is far more likely to be income.
    """
    matched = {tid for s in detect_transfers(txns) for tid in s.txn_ids}
    matched |= {tid for s in detect_refunds(txns) for tid in s.txn_ids}

    by_merchant: dict[str, list[Txn]] = {}
    for txn in txns:
        if txn.amount_minor > 0 and txn.txn_id not in matched and txn.key:
            by_merchant.setdefault(txn.key, []).append(txn)

    out: list[Suggestion] = []
    for key, group in by_merchant.items():
        if len(group) < INCOME_MIN_OCCURRENCES:
            continue
        group = sorted(group, key=lambda t: t.occurred_on)
        gaps = [
            (later.occurred_on - earlier.occurred_on).days
            for earlier, later in zip(group, group[1:])
        ]
        regular = bool(gaps) and all(20 <= gap <= 40 for gap in gaps)
        amounts = [t.amount_minor for t in group]
        steady = (max(amounts) - min(amounts)) / max(amounts) < 0.15 if max(amounts) else False

        confidence = 0.9 if regular and steady else 0.7 if regular else 0.5
        out.append(
            Suggestion(
                kind=SuggestionKind.INCOME,
                confidence=confidence,
                reason=(
                    f"{len(group)} credits from {group[-1].merchant or 'this source'}"
                    + (" arriving roughly monthly." if regular else ", with no matching charge or transfer.")
                ),
                txn_ids=tuple(t.txn_id for t in group),
                payload={
                    "merchant_key": key,
                    "typical_amount_minor": sorted(amounts)[len(amounts) // 2],
                    "is_regular": regular,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Split suggestions
# ---------------------------------------------------------------------------

#: Below this, splitting is more effort than the accuracy is worth.
SPLIT_MIN_AMOUNT_MINOR = 5_000


def suggest_splits(txn: Txn, history: list[Txn]) -> list[Suggestion]:
    """Suggest splitting a transaction across the categories a merchant usually
    attracts.

    Only fires where the same merchant has genuinely been categorised more than
    one way before — a supermarket that is sometimes groceries and sometimes
    household. Suggesting a split on a merchant with one consistent category
    would be noise dressed as insight.
    """
    if txn.amount_minor >= 0 or abs(txn.amount_minor) < SPLIT_MIN_AMOUNT_MINOR:
        return []

    counts: dict[str, int] = {}
    for past in history:
        if past.key == txn.key and past.category_id and past.txn_id != txn.txn_id:
            counts[past.category_id] = counts.get(past.category_id, 0) + 1

    if len(counts) < 2:
        return []

    total = sum(counts.values())
    if total < 4:
        # Too little history to claim a pattern rather than a coincidence.
        return []

    shares = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    return [
        Suggestion(
            kind=SuggestionKind.SPLIT,
            confidence=0.5,
            reason=(
                f"You've categorised {txn.merchant or 'this merchant'} {len(counts)} different "
                "ways before, so this may be worth splitting."
            ),
            txn_ids=(txn.txn_id,),
            payload={
                "parts": [
                    {
                        "category_id": category_id,
                        "share": round(count / total, 2),
                        "amount_minor": int(abs(txn.amount_minor) * count / total),
                    }
                    for category_id, count in shares
                ]
            },
        )
    ]


# ---------------------------------------------------------------------------
# Categorisation from learned history
# ---------------------------------------------------------------------------

#: Below this share of past decisions agreeing, a suggestion is a guess.
CATEGORY_MIN_SHARE = 0.6
CATEGORY_MIN_EXAMPLES = 2


def suggest_category(
    txn: Txn, *, merchant_stats: dict[str, dict[str, int]]
) -> Suggestion | None:
    """Suggest a category from what this user has chosen for this merchant.

    Learned from the user's own decisions rather than a shared model: two
    households categorise the same supermarket differently and both are right.
    A global model would be confidently wrong for one of them.

    Confidence is the observed agreement rate, capped below certainty — the
    user has changed their mind before and may again.
    """
    if txn.category_id or txn.amount_minor >= 0:
        return None

    stats = merchant_stats.get(txn.key)
    if not stats:
        return None

    total = sum(stats.values())
    if total < CATEGORY_MIN_EXAMPLES:
        return None

    category_id, count = max(stats.items(), key=lambda kv: kv[1])
    share = count / total
    if share < CATEGORY_MIN_SHARE:
        # Genuinely split history: a suggestion here would be a coin toss
        # presented as a recommendation.
        return None

    return Suggestion(
        kind=SuggestionKind.CATEGORY,
        confidence=round(min(0.95, share), 2),
        reason=(
            f"You've put {count} of the last {total} {txn.merchant or 'charges from here'} "
            "in this category."
        ),
        txn_ids=(txn.txn_id,),
        payload={"category_id": category_id, "examples": total, "agreement": round(share, 2)},
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

#: Order matters. Transfers and refunds claim their transactions first, so
#: income detection only considers what is genuinely left over.
def detect_all(
    txns: list[Txn], *, merchant_stats: dict[str, dict[str, int]] | None = None
) -> list[Suggestion]:
    """Run every detector and return suggestions, most confident first."""
    stats = merchant_stats or {}
    suggestions: list[Suggestion] = [
        *detect_transfers(txns),
        *detect_refunds(txns),
        *detect_duplicates(txns),
        *detect_recurring(txns),
        *detect_income(txns),
    ]
    for txn in txns:
        category = suggest_category(txn, merchant_stats=stats)
        if category:
            suggestions.append(category)
        suggestions.extend(suggest_splits(txn, txns))

    return sorted(suggestions, key=lambda s: -s.confidence)

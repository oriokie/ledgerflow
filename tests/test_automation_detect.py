"""Automation detection engine — pure, no database.

Merchant normalisation is tested hardest because everything else depends on it:
until descriptors collapse to one merchant, recurring detection misses
subscriptions, duplicate detection over-fires, and category learning never
accumulates enough examples to be useful.

The detectors are tested for their *refusals* as much as their findings. A
false transfer erases a real expense; a false duplicate accuses someone of
being double-charged when they weren't.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.intelligence import detect
from apps.intelligence.detect import SuggestionKind, Txn, merchant_key, normalize_merchant

START = date(2026, 1, 15)


def _txn(txn_id, amount, *, day=0, account="a1", merchant="", category=None):
    return Txn(
        txn_id=txn_id,
        account_id=account,
        occurred_on=START + timedelta(days=day),
        amount_minor=amount,
        merchant=merchant,
        category_id=category,
    )


def _kinds(suggestions):
    return {s.kind for s in suggestions}


# =============================================================================
# Merchant normalisation
# =============================================================================
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SQ *COFFEE HOUSE 1234", "Coffee House"),
        ("SQ*COFFEE HOUSE", "Coffee House"),
        ("TST* BURGER JOINT", "Burger Joint"),
        ("PAYPAL *STEAM GAMES", "Steam Games"),
        # Stripping the prefix would leave "US", which tells the user nothing.
        ("AMZN Mktp US*1A2B3C", "Amazon"),
        ("UBER   *TRIP 8XY2Z", "Uber Trip"),
        ("TESCO STORES 3456", "Tesco Stores"),
    ],
)
def test_processor_noise_is_stripped(raw, expected):
    assert normalize_merchant(raw) == expected


def test_the_same_merchant_collapses_to_one_key():
    """The keystone property. Without it every other detector works with noise."""
    variants = ["SQ *COFFEE HOUSE 1234", "SQ*COFFEE HOUSE", "COFFEE HOUSE 4471"]
    keys = {merchant_key(v) for v in variants}
    assert len(keys) == 1, f"variants did not collapse: {keys}"


def test_different_merchants_stay_separate():
    """Over-normalising is worse than under-normalising: merging two merchants
    silently corrupts every figure derived from the pair."""
    assert merchant_key("COFFEE HOUSE") != merchant_key("BURGER JOINT")
    assert merchant_key("TESCO EXPRESS") != merchant_key("TESCO METRO")


def test_dates_and_reference_codes_are_removed():
    assert "03" not in normalize_merchant("NETFLIX 03/14")
    assert normalize_merchant("SPOTIFY AB12CD34") == "Spotify"


def test_a_real_name_containing_a_digit_survives():
    """The reference-code rule must not eat merchants like 7Eleven."""
    assert normalize_merchant("7ELEVEN STORE 442") == "7Eleven Store"


def test_normalisation_never_returns_nothing():
    """An empty merchant name is worse than an ugly one."""
    assert normalize_merchant("12345") == "12345"
    assert normalize_merchant("*** ###") == "*** ###"
    assert normalize_merchant("") == ""


def test_normalisation_is_idempotent():
    once = normalize_merchant("SQ *COFFEE HOUSE 1234")
    assert normalize_merchant(once) == once


# =============================================================================
# Transfers
# =============================================================================
def test_an_equal_and_opposite_pair_across_accounts_is_a_transfer():
    txns = [
        _txn("out", -50_000, account="checking"),
        _txn("in", 50_000, account="savings"),
    ]
    [suggestion] = detect.detect_transfers(txns)
    assert suggestion.kind == SuggestionKind.TRANSFER
    assert suggestion.confidence >= 0.9
    assert set(suggestion.txn_ids) == {"out", "in"}


def test_confidence_tapers_as_the_legs_drift_apart():
    same_day = detect.detect_transfers([_txn("o", -50_000, account="a"), _txn("i", 50_000, account="b")])[0]
    days_apart = detect.detect_transfers(
        [_txn("o", -50_000, account="a"), _txn("i", 50_000, day=3, account="b")]
    )[0]
    assert same_day.confidence > days_apart.confidence


def test_a_near_match_is_not_a_transfer():
    """Far more likely two unrelated transactions than a transfer that lost
    money in flight — and pairing them would erase a real expense."""
    txns = [_txn("o", -50_000, account="a"), _txn("i", 49_900, account="b")]
    assert detect.detect_transfers(txns) == []


def test_two_legs_on_the_same_account_are_not_a_transfer():
    txns = [_txn("o", -50_000, account="a"), _txn("i", 50_000, account="a")]
    assert detect.detect_transfers(txns) == []


def test_legs_too_far_apart_are_not_paired():
    txns = [_txn("o", -50_000, account="a"), _txn("i", 50_000, day=20, account="b")]
    assert detect.detect_transfers(txns) == []


def test_a_transaction_is_only_paired_once():
    txns = [
        _txn("out", -50_000, account="a"),
        _txn("in1", 50_000, account="b"),
        _txn("in2", 50_000, account="c"),
    ]
    suggestions = detect.detect_transfers(txns)
    assert len(suggestions) == 1


# =============================================================================
# Duplicates
# =============================================================================
def test_identical_same_day_charges_are_flagged_as_candidates():
    txns = [
        _txn("a", -1_250, merchant="Corner Shop"),
        _txn("b", -1_250, merchant="Corner Shop"),
    ]
    [suggestion] = detect.detect_duplicates(txns)
    assert suggestion.kind == SuggestionKind.DUPLICATE
    # Deliberately not asserted as fact: two identical coffees are normal.
    assert suggestion.confidence < 0.7
    assert "often legitimate" in suggestion.reason


def test_repeated_credits_are_not_treated_as_duplicates():
    """A repeated credit is far more often legitimate than a double-post."""
    txns = [_txn("a", 1_250, merchant="Refund"), _txn("b", 1_250, merchant="Refund")]
    assert detect.detect_duplicates(txns) == []


def test_charges_on_different_accounts_are_not_duplicates():
    txns = [
        _txn("a", -1_250, account="one", merchant="Shop"),
        _txn("b", -1_250, account="two", merchant="Shop"),
    ]
    assert detect.detect_duplicates(txns) == []


def test_a_single_charge_is_never_a_duplicate():
    assert detect.detect_duplicates([_txn("a", -1_250, merchant="Shop")]) == []


def test_duplicate_confidence_falls_with_the_gap():
    same_day = detect.detect_duplicates(
        [_txn("a", -1_000, merchant="Shop"), _txn("b", -1_000, merchant="Shop")]
    )[0]
    apart = detect.detect_duplicates(
        [_txn("a", -1_000, merchant="Shop"), _txn("b", -1_000, day=3, merchant="Shop")]
    )[0]
    assert same_day.confidence > apart.confidence


# =============================================================================
# Refunds
# =============================================================================
def test_a_credit_matching_an_earlier_charge_is_a_refund():
    txns = [
        _txn("charge", -8_000, merchant="Big Store"),
        _txn("credit", 8_000, day=10, merchant="Big Store"),
    ]
    [suggestion] = detect.detect_refunds(txns)
    assert suggestion.kind == SuggestionKind.REFUND
    assert suggestion.confidence >= 0.85
    assert suggestion.payload["is_partial"] is False


def test_a_partial_refund_is_recognised_with_lower_confidence():
    txns = [
        _txn("charge", -8_000, merchant="Big Store"),
        _txn("credit", 3_000, day=5, merchant="Big Store"),
    ]
    [suggestion] = detect.detect_refunds(txns)
    assert suggestion.payload["is_partial"] is True
    assert suggestion.confidence < 0.9


def test_a_credit_before_the_charge_is_not_a_refund():
    """Ordering is what distinguishes a refund from an unrelated payment."""
    txns = [
        _txn("credit", 8_000, merchant="Big Store"),
        _txn("charge", -8_000, day=10, merchant="Big Store"),
    ]
    assert detect.detect_refunds(txns) == []


def test_a_credit_from_a_different_merchant_is_not_a_refund():
    txns = [
        _txn("charge", -8_000, merchant="Big Store"),
        _txn("credit", 8_000, day=5, merchant="Other Shop"),
    ]
    assert detect.detect_refunds(txns) == []


def test_a_credit_larger_than_the_charge_is_not_a_refund():
    txns = [
        _txn("charge", -8_000, merchant="Store"),
        _txn("credit", 20_000, day=5, merchant="Store"),
    ]
    assert detect.detect_refunds(txns) == []


# =============================================================================
# Recurring
# =============================================================================
def test_three_monthly_charges_are_recognised_as_recurring():
    txns = [
        _txn("a", -1_299, day=0, merchant="Streaming Co"),
        _txn("b", -1_299, day=30, merchant="Streaming Co"),
        _txn("c", -1_299, day=60, merchant="Streaming Co"),
    ]
    [suggestion] = detect.detect_recurring(txns)
    assert suggestion.payload["cadence"] == "monthly"
    assert suggestion.confidence >= 0.85


def test_two_charges_are_not_yet_a_pattern():
    """Two points define an interval but not a pattern — calling it a
    subscription would put a fictional commitment in the cash-flow projection."""
    txns = [
        _txn("a", -1_299, day=0, merchant="Streaming Co"),
        _txn("b", -1_299, day=30, merchant="Streaming Co"),
    ]
    assert detect.detect_recurring(txns) == []


def test_irregular_charges_are_not_recurring_even_if_the_mean_fits():
    """Alternating 1-day and 59-day gaps average to monthly and are nothing of
    the sort."""
    txns = [
        _txn("a", -1_000, day=0, merchant="Shop"),
        _txn("b", -1_000, day=1, merchant="Shop"),
        _txn("c", -1_000, day=60, merchant="Shop"),
    ]
    assert detect.detect_recurring(txns) == []


def test_a_drifting_price_still_counts_but_scores_lower():
    steady = detect.detect_recurring([_txn(f"s{i}", -1_000, day=i * 30, merchant="Sub") for i in range(3)])[0]
    drifting = detect.detect_recurring(
        [
            _txn("a", -1_000, day=0, merchant="Sub"),
            _txn("b", -1_200, day=30, merchant="Sub"),
            _txn("c", -1_400, day=60, merchant="Sub"),
        ]
    )[0]
    assert steady.confidence > drifting.confidence
    assert "varies" in drifting.reason


def test_weekly_and_yearly_cadences_are_recognised():
    weekly = detect.detect_recurring([_txn(f"w{i}", -500, day=i * 7, merchant="Weekly") for i in range(4)])
    yearly = detect.detect_recurring(
        [_txn(f"y{i}", -9_900, day=i * 365, merchant="Yearly") for i in range(3)]
    )
    assert weekly[0].payload["cadence"] == "weekly"
    assert yearly[0].payload["cadence"] == "yearly"


# =============================================================================
# Income
# =============================================================================
def test_regular_steady_credits_are_income():
    txns = [_txn(f"p{i}", 300_000, day=i * 30, merchant="Employer Ltd") for i in range(3)]
    [suggestion] = detect.detect_income(txns)
    assert suggestion.kind == SuggestionKind.INCOME
    assert suggestion.confidence >= 0.85
    assert suggestion.payload["is_regular"] is True


def test_a_refunded_credit_is_not_counted_as_income():
    """Refunds are claimed first, so what's left is far more likely earnings."""
    txns = [
        _txn("charge", -8_000, merchant="Store"),
        _txn("credit", 8_000, day=5, merchant="Store"),
        _txn("credit2", 8_000, day=40, merchant="Store"),
    ]
    income_ids = {tid for s in detect.detect_income(txns) for tid in s.txn_ids}
    assert "credit" not in income_ids


def test_a_transfer_leg_is_not_counted_as_income():
    txns = [
        _txn("out", -50_000, account="a", merchant="Savings"),
        _txn("in", 50_000, account="b", merchant="Savings"),
    ]
    assert detect.detect_income(txns) == []


def test_a_single_credit_is_not_yet_income():
    assert detect.detect_income([_txn("one", 300_000, merchant="Employer")]) == []


# =============================================================================
# Splits
# =============================================================================
def test_a_merchant_categorised_several_ways_suggests_a_split():
    history = [
        _txn("h1", -3_000, merchant="Supermarket", category="groceries"),
        _txn("h2", -3_000, merchant="Supermarket", category="groceries"),
        _txn("h3", -3_000, merchant="Supermarket", category="household"),
        _txn("h4", -3_000, merchant="Supermarket", category="household"),
    ]
    target = _txn("new", -12_000, merchant="Supermarket")
    [suggestion] = detect.suggest_splits(target, history)
    assert suggestion.kind == SuggestionKind.SPLIT
    assert len(suggestion.payload["parts"]) == 2


def test_a_consistently_categorised_merchant_suggests_no_split():
    """Noise dressed as insight."""
    history = [_txn(f"h{i}", -3_000, merchant="Supermarket", category="groceries") for i in range(5)]
    assert detect.suggest_splits(_txn("new", -12_000, merchant="Supermarket"), history) == []


def test_small_transactions_are_not_worth_splitting():
    history = [
        _txn("h1", -3_000, merchant="Shop", category="a"),
        _txn("h2", -3_000, merchant="Shop", category="a"),
        _txn("h3", -3_000, merchant="Shop", category="b"),
        _txn("h4", -3_000, merchant="Shop", category="b"),
    ]
    assert detect.suggest_splits(_txn("tiny", -500, merchant="Shop"), history) == []


def test_thin_history_does_not_support_a_split():
    history = [
        _txn("h1", -3_000, merchant="Shop", category="a"),
        _txn("h2", -3_000, merchant="Shop", category="b"),
    ]
    assert detect.suggest_splits(_txn("new", -12_000, merchant="Shop"), history) == []


# =============================================================================
# Category learning
# =============================================================================
def test_a_category_is_suggested_from_the_users_own_history():
    """Two households categorise the same supermarket differently and both are
    right — a shared model would be confidently wrong for one of them."""
    txn = _txn("new", -4_000, merchant="Corner Shop")
    stats = {merchant_key("Corner Shop"): {"groceries": 8, "household": 1}}
    suggestion = detect.suggest_category(txn, merchant_stats=stats)

    assert suggestion is not None
    assert suggestion.payload["category_id"] == "groceries"
    assert suggestion.confidence >= 0.85
    assert "8 of the last 9" in suggestion.reason


def test_genuinely_split_history_suggests_nothing():
    """A coin toss presented as a recommendation is worse than silence."""
    txn = _txn("new", -4_000, merchant="Shop")
    stats = {merchant_key("Shop"): {"a": 5, "b": 5}}
    assert detect.suggest_category(txn, merchant_stats=stats) is None


def test_thin_history_suggests_nothing():
    txn = _txn("new", -4_000, merchant="Shop")
    assert detect.suggest_category(txn, merchant_stats={merchant_key("Shop"): {"a": 1}}) is None


def test_an_already_categorised_transaction_is_left_alone():
    txn = _txn("new", -4_000, merchant="Shop", category="already")
    stats = {merchant_key("Shop"): {"groceries": 9}}
    assert detect.suggest_category(txn, merchant_stats=stats) is None


def test_confidence_never_reaches_certainty():
    """The user has changed their mind before and may again."""
    txn = _txn("new", -4_000, merchant="Shop")
    stats = {merchant_key("Shop"): {"groceries": 100}}
    suggestion = detect.suggest_category(txn, merchant_stats=stats)
    assert suggestion.confidence < 1.0


# =============================================================================
# Orchestration
# =============================================================================
def test_detect_all_returns_most_confident_first():
    txns = [
        _txn("out", -50_000, account="a", merchant="Savings"),
        _txn("in", 50_000, account="b", merchant="Savings"),
        _txn("d1", -1_250, merchant="Corner Shop"),
        _txn("d2", -1_250, merchant="Corner Shop"),
    ]
    suggestions = detect.detect_all(txns)
    confidences = [s.confidence for s in suggestions]
    assert confidences == sorted(confidences, reverse=True)
    assert SuggestionKind.TRANSFER in _kinds(suggestions)


def test_every_suggestion_carries_a_reason():
    """A suggestion the user cannot check is one they cannot trust."""
    txns = [
        _txn("out", -50_000, account="a", merchant="Savings"),
        _txn("in", 50_000, account="b", merchant="Savings"),
        *[_txn(f"s{i}", -1_299, day=i * 30, merchant="Streaming") for i in range(3)],
    ]
    for suggestion in detect.detect_all(txns):
        assert suggestion.reason.strip(), f"{suggestion.kind} has no reason"
        assert 0 < suggestion.confidence <= 1
        assert suggestion.txn_ids


def test_an_empty_ledger_produces_no_suggestions():
    assert detect.detect_all([]) == []

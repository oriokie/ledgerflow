"""Natural-language questions over the ledger.

The property that matters more than any parsing detail: **the model never
produces a figure.** It produces a filter, which is validated here and executed
by the ordinary selectors. A language model stating a number about somebody's
money would be indistinguishable from a right one when it was wrong.
"""

from __future__ import annotations

from datetime import date

from apps.intelligence.ask import ALLOWED_FIELDS, LedgerQuery, _coerce, parse_rules

TODAY = date(2026, 8, 3)


def test_a_period_becomes_a_date_range():
    q = parse_rules("how much did I spend last 30 days", today=TODAY)
    assert q.start == "2026-07-04"
    assert q.end == "2026-08-03"
    assert q.direction == "out"


def test_an_amount_phrase_becomes_a_bound():
    assert parse_rules("over 500", today=TODAY).min_amount_minor == 50_000
    assert parse_rules("under 20.50", today=TODAY).max_amount_minor == 2_050
    assert parse_rules("more than 1,200", today=TODAY).min_amount_minor == 120_000


def test_income_and_spending_are_directions_not_search_terms():
    assert parse_rules("income this year", today=TODAY).direction == "in"
    assert parse_rules("spending on coffee", today=TODAY).direction == "out"


def test_a_question_with_nothing_in_it_yields_nothing():
    """Better to fall through to plain search than to invent a filter."""
    assert parse_rules("", today=TODAY) is None
    assert parse_rules("   ", today=TODAY) is None


def test_the_query_only_ever_exposes_allowed_fields():
    """The allow-list is the security boundary, not the prompt: a prompt is a
    request, an allow-list is a guarantee."""
    q = LedgerQuery(start="2026-01-01", search="x", explanation="…", from_rules=False)
    assert set(q.as_params()) <= ALLOWED_FIELDS
    assert "explanation" not in q.as_params()
    assert "from_rules" not in q.as_params()


# ---------------------------------------------------------------------------
# Validating what a model returns
# ---------------------------------------------------------------------------
def test_a_hallucinated_category_is_dropped():
    """Filtering by a category the workspace does not have returns an empty
    list that looks exactly like an answer."""
    out = _coerce({"category": "Yacht maintenance"}, ["Groceries", "Rent"])
    assert "category" not in out
    assert _coerce({"category": "groceries"}, ["Groceries"])["category"] == "Groceries"


def test_unparseable_dates_are_dropped_not_guessed():
    assert _coerce({"start": "last March"}, []) == {}
    assert _coerce({"start": "2026-03-01"}, []) == {"start": "2026-03-01"}


def test_unknown_keys_never_survive():
    """A model returning `{"delete": true}` must be as inert as one returning
    nothing."""
    out = _coerce({"delete": True, "account_id": "abc", "sql": "DROP TABLE"}, [])
    assert out == {}


def test_amounts_must_be_non_negative_numbers():
    assert _coerce({"min_amount_minor": -5}, []) == {}
    assert _coerce({"min_amount_minor": "500"}, []) == {}
    assert _coerce({"min_amount_minor": True}, []) == {}
    assert _coerce({"min_amount_minor": 500}, []) == {"min_amount_minor": 500}


def test_direction_is_a_closed_set():
    assert _coerce({"direction": "sideways"}, []) == {}
    assert _coerce({"direction": "in"}, []) == {"direction": "in"}

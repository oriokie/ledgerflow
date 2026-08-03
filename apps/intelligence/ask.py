"""Natural-language questions over the ledger — as a *query*, never an answer.

The design decision that makes this shippable is refusing the obvious shape.
The obvious shape is: send the model some transactions, let it reply in prose.
That would mean a language model stating figures about somebody's money, where
a plausible wrong number is indistinguishable from a right one and there is
nothing for the user to check it against.

**So the model never produces a figure.** It produces a *filter* — dates, a
category, an amount range, a direction — which is then validated here and
executed by the same selectors, under the same tenant scoping and the same
permission checks, as if the user had built it in the UI. The arithmetic is the
product's. The model only ever decides what to look at.

That keeps every rule `llm.py` sets out:

* it cannot reach the database — it receives category *names* and nothing else;
* it cannot write — the output is a read filter, and unknown keys are dropped;
* its output is validated before use — anything that does not parse into a
  known field is discarded, and a failed parse falls back to plain search.

The honest limitation, stated plainly because the UI states it too: this
understands roughly the questions the filter bar can express. It is a faster way
to reach a view you could have built yourself, not a new capability.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from django.utils import timezone

from .llm import LLMError, complete_json, llm_available

#: Everything the model is permitted to influence. Anything else it returns is
#: dropped without comment — the allow-list is the security boundary, not the
#: prompt, because a prompt is a request and an allow-list is a guarantee.
ALLOWED_FIELDS = {
    "start",
    "end",
    "category",
    "search",
    "min_amount_minor",
    "max_amount_minor",
    "direction",
}

MAX_QUESTION_CHARS = 200


@dataclass(frozen=True, slots=True)
class LedgerQuery:
    """A validated, executable filter — the only thing this module returns."""

    start: str | None = None
    end: str | None = None
    category: str | None = None
    search: str | None = None
    min_amount_minor: int | None = None
    max_amount_minor: int | None = None
    #: "in" | "out" | None
    direction: str | None = None
    #: How this was derived, shown to the user. Never model-authored prose.
    explanation: str = ""
    #: True when the deterministic parser handled it and no model was called.
    from_rules: bool = True

    def as_params(self) -> dict:
        out = {k: v for k, v in asdict(self).items() if k in ALLOWED_FIELDS and v not in (None, "")}
        return out


# ---------------------------------------------------------------------------
# Deterministic first
# ---------------------------------------------------------------------------
_PERIODS: tuple[tuple[str, int], ...] = (
    ("last 7 days", 7),
    ("last week", 7),
    ("last 30 days", 30),
    ("last month", 30),
    ("last 90 days", 90),
    ("last 3 months", 90),
    ("last 6 months", 182),
    ("last year", 365),
    ("this year", 0),
)


def _period(text: str, today: date) -> tuple[str, str, str] | None:
    for phrase, days in _PERIODS:
        if phrase not in text:
            continue
        if phrase == "this year":
            return date(today.year, 1, 1).isoformat(), today.isoformat(), "this year"
        return (today - timedelta(days=days)).isoformat(), today.isoformat(), phrase
    return None


_AMOUNT = re.compile(r"(over|above|more than|under|below|less than)\s*([\d,]+(?:\.\d+)?)")


def parse_rules(question: str, *, today: date | None = None) -> LedgerQuery | None:
    """Handle the common questions without a model at all.

    Most of what people type is "groceries last month" or "over 500", and
    sending that to a hosted model would be slower, less reliable and less
    private than a regex. The model is for what is left over.
    """
    today = today or timezone.localdate()
    text = question.lower().strip()
    if not text:
        return None

    start = end = None
    period_label = ""
    period = _period(text, today)
    if period:
        start, end, period_label = period
        text = text.replace(period_label, " ")

    min_amount = max_amount = None
    match = _AMOUNT.search(text)
    if match:
        word, raw = match.group(1), match.group(2).replace(",", "")
        minor = int(round(float(raw) * 100))
        if word in ("over", "above", "more than"):
            min_amount = minor
        else:
            max_amount = minor
        text = text[: match.start()] + text[match.end() :]

    direction = None
    if "income" in text or "earned" in text or "paid me" in text:
        direction = "in"
        text = text.replace("income", " ").replace("earned", " ")
    # "spend" is a prefix of "spending", so it covers both; "spent" is the
    # irregular past tense and needs saying separately.
    elif "spend" in text or "spent" in text or "expenses" in text:
        direction = "out"
        for word in ("spending", "spend", "spent", "expenses"):
            text = text.replace(word, " ")

    for filler in ("how much did i", "how much", "show me", "find", "on", "in", "did i"):
        text = text.replace(filler, " ")
    search = " ".join(text.split()) or None

    if not any((start, min_amount, max_amount, direction, search)):
        return None

    bits = [b for b in (period_label, direction and f"money {direction}", search) if b]
    return LedgerQuery(
        start=start,
        end=end,
        search=search,
        min_amount_minor=min_amount,
        max_amount_minor=max_amount,
        direction=direction,
        explanation="Showing " + (", ".join(bits) if bits else "everything"),
        from_rules=True,
    )


# ---------------------------------------------------------------------------
# Model second
# ---------------------------------------------------------------------------
_SYSTEM = """You convert a question about personal finances into a JSON filter.

Reply with ONLY a JSON object. Allowed keys, all optional:
  start, end          ISO dates (YYYY-MM-DD)
  category            one of the category names given, copied exactly
  search              free text to match against payee or memo
  min_amount_minor    integer, minor units (cents)
  max_amount_minor    integer, minor units (cents)
  direction           "in" or "out"

Never invent totals, answers or commentary. You are choosing what to look at,
not saying what it adds up to. If the question cannot be expressed as a filter,
reply with {}."""


def _coerce(raw: dict, categories: list[str]) -> dict:
    """Keep only what is recognisable, and only in the right shape.

    A model that returns `{"start": "last March"}` or invents a category is
    normal, not exceptional — so anything that fails to coerce is dropped
    rather than trusted or raised on.
    """
    out: dict = {}
    for key in ("start", "end"):
        value = raw.get(key)
        if isinstance(value, str):
            try:
                out[key] = date.fromisoformat(value.strip()).isoformat()
            except ValueError:
                continue

    for key in ("min_amount_minor", "max_amount_minor"):
        value = raw.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            out[key] = int(value)

    direction = raw.get("direction")
    if direction in ("in", "out"):
        out["direction"] = direction

    search = raw.get("search")
    if isinstance(search, str) and search.strip():
        out["search"] = search.strip()[:80]

    # A category the workspace does not have is a hallucination, and silently
    # filtering by it would return an empty list that looks like an answer.
    category = raw.get("category")
    if isinstance(category, str):
        match = next((c for c in categories if c.lower() == category.strip().lower()), None)
        if match:
            out["category"] = match

    return out


def interpret(question: str, *, categories: list[str] | None = None) -> LedgerQuery | None:
    """Turn a question into a filter. `None` when nothing usable came of it.

    Rules first, model second, neither required. With no provider configured
    this degrades to the deterministic parser, and with that finding nothing the
    caller falls back to plain search — the feature never becomes the reason
    somebody cannot look something up.
    """
    question = (question or "").strip()[:MAX_QUESTION_CHARS]
    if not question:
        return None

    rules = parse_rules(question)
    if rules is not None:
        return rules

    available, _ = llm_available()
    if not available:
        return None

    categories = categories or []
    try:
        raw = complete_json(
            system=_SYSTEM,
            user=f"Categories: {', '.join(categories[:60])}\nQuestion: {question}",
        )
    except LLMError:
        return None

    if not isinstance(raw, dict):
        return None

    fields = _coerce(raw, categories)
    if not fields:
        return None

    return LedgerQuery(
        **fields,
        explanation="Interpreted from your question — check the filters below.",
        from_rules=False,
    )

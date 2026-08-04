"""Asking in words, answered by arithmetic.

"Can we afford a second home?" is a sentence. `decisions.can_i_afford_mortgage`
is a function with six keyword arguments. This module is the distance between
them, and it is built on the rule `ask.py` established and `advisor.py`
inherited:

    The model routes. The product computes.

A language model reads the question, picks which of the five evaluators answers
it, and pulls the numbers *the user typed in their own sentence* into that
evaluator's parameters. It does not compute anything, does not estimate a
missing figure, and never sees a balance. Every number in the answer comes from
`apps.projections.decisions`, and the narrative comes from `advisor.explain`,
which already refuses to repeat a figure the calculation did not produce.

**There is a deterministic router underneath, and it is not a fallback.** It
runs first, it handles the phrasings people actually use, and when no model is
configured — the default — it is the whole feature. A keyword router is a poor
substitute for language understanding and a perfectly good way to tell "can I
afford this house" from "when can I retire", which is all that is being asked
of it.

**What it refuses to do.** If the question does not resolve to an evaluator, it
says so and lists what it *can* answer. It does not guess at the closest match,
because being confidently answered with the wrong question is worse than being
told to rephrase — the user cannot tell from the output that the wrong thing
was computed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.intelligence.llm import LLMError, complete_json, llm_available

#: Evaluator slug -> the words that pick it out. Ordered by specificity: the
#: first pattern that matches wins, so "how much house" beats "afford".
ROUTES: list[tuple[str, list[str]]] = [
    (
        "how-much-house",
        [
            "how much house",
            "how much home",
            "how much can i borrow",
            "how much could i borrow",
            "what can i afford to buy",
            "how expensive a house",
        ],
    ),
    (
        "buy-or-rent",
        [
            "buy or rent",
            "rent or buy",
            "renting or buying",
            "better to rent",
            "better to buy",
            "should i rent",
        ],
    ),
    (
        "debt-or-invest",
        [
            "pay off debt or invest",
            "debt or invest",
            "invest or pay",
            "pay down debt or",
            "overpay or invest",
            "clear my debt or",
        ],
    ),
    (
        "retire",
        ["retire", "retirement", "stop working", "financial independence", "work optional"],
    ),
    (
        "afford-mortgage",
        [
            "afford this mortgage",
            "afford a mortgage",
            "afford this house",
            "afford this home",
            "afford a house",
            "afford a home",
            "second home",
            "can i afford",
            "can we afford",
        ],
    ),
]

#: What each evaluator needs before it can answer. Used to tell the user what
#: is missing rather than silently defaulting it — a mortgage answered with an
#: invented interest rate is worse than no answer.
REQUIRED: dict[str, list[str]] = {
    "afford-mortgage": ["property_price_minor", "annual_rate"],
    "how-much-house": ["annual_rate"],
    "debt-or-invest": ["monthly_amount_minor", "expected_return"],
    "retire": ["years_until", "monthly_income_needed_minor"],
    "buy-or-rent": ["property_price_minor", "annual_rate", "monthly_rent_minor"],
}

QUESTION_LABELS = {
    "afford-mortgage": "Can I afford this mortgage?",
    "how-much-house": "How much house can I comfortably afford?",
    "debt-or-invest": "Should I pay debt down or invest?",
    "retire": "Can I retire when I want to?",
    "buy-or-rent": "Should I buy or rent?",
}


@dataclass(frozen=True)
class Routing:
    """Where a question was sent, and what could be pulled out of it."""

    slug: str | None
    params: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    #: True when a model did the routing. Surfaced so the UI can say so.
    llm_used: bool = False
    #: Why nothing was matched, when nothing was.
    detail: str = ""

    @property
    def answerable(self) -> bool:
        return self.slug is not None and not self.missing


#: Numbers as people write them: "450k", "1.2m", "450,000", "9%".
_MAGNITUDES = {"k": 1_000, "m": 1_000_000, "bn": 1_000_000_000, "b": 1_000_000_000}
_AMOUNT = re.compile(r"(\d[\d,]*\.?\d*)\s*(k|m|bn|b)?\b", re.IGNORECASE)
_PERCENT = re.compile(r"(\d+\.?\d*)\s*%")
_YEARS = re.compile(r"(?:in|after|for)\s+(\d+)\s*year", re.IGNORECASE)


def _numbers_in(text: str) -> tuple[list[int], list[float], int | None]:
    """Amounts (in minor units), percentages (as fractions), and a year count.

    Percentages are stripped before amounts are read, or "9%" is also collected
    as the amount nine.
    """
    percents = [float(m.group(1)) / 100 for m in _PERCENT.finditer(text)]
    without_percents = _PERCENT.sub(" ", text)

    years_match = _YEARS.search(text)
    years = int(years_match.group(1)) if years_match else None
    without_years = _YEARS.sub(" ", without_percents) if years_match else without_percents

    amounts = []
    for match in _AMOUNT.finditer(without_years):
        raw = match.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:  # pragma: no cover - regex guarantees numeric
            continue
        suffix = (match.group(2) or "").lower()
        value *= _MAGNITUDES.get(suffix, 1)
        # Bare small integers are almost always counts ("2 years", "3 children"),
        # not money. Requiring a magnitude suffix or a thousands separator keeps
        # them out of the amount list.
        if value < 1000 and not suffix:
            continue
        amounts.append(round(value * 100))
    return amounts, percents, years


def route_deterministic(question: str) -> Routing:
    """Match on the phrasings people actually use.

    Runs first and, with no model configured, is the whole feature.
    """
    text = question.lower().strip()
    if not text:
        return Routing(slug=None, detail="Ask a question and this will try to answer it.")

    slug = next((s for s, phrases in ROUTES if any(p in text for p in phrases)), None)
    if slug is None:
        return Routing(
            slug=None,
            detail="That is not one of the questions this can compute an answer to.",
        )

    amounts, percents, years = _numbers_in(text)
    params: dict = {}
    if amounts:
        params[
            (
                "property_price_minor"
                if slug in ("afford-mortgage", "buy-or-rent")
                else (
                    "monthly_amount_minor"
                    if slug == "debt-or-invest"
                    else "monthly_income_needed_minor" if slug == "retire" else "deposit_minor"
                )
            )
        ] = amounts[0]
        if slug == "buy-or-rent" and len(amounts) > 1:
            params["monthly_rent_minor"] = amounts[1]
        elif slug == "afford-mortgage" and len(amounts) > 1:
            params["deposit_minor"] = amounts[1]
    if percents:
        params["annual_rate" if slug != "debt-or-invest" else "expected_return"] = percents[0]
    if years is not None and slug == "retire":
        params["years_until"] = years

    missing = [f for f in REQUIRED.get(slug, []) if f not in params]
    return Routing(slug=slug, params=params, missing=missing)


SYSTEM = """You route a personal-finance question to one of five calculators.

Reply with JSON only: {"slug": "...", "params": {...}}

Valid slugs: afford-mortgage, how-much-house, debt-or-invest, retire, buy-or-rent.
Use null for slug if the question is not one of these.

Rules:
- Only put a number in params if the user stated it. Never estimate, never
  infer, never fill in a typical value.
- Money goes in minor units (multiply by 100). Rates go as fractions (9% -> 0.09).
- Parameter names: property_price_minor, deposit_minor, annual_rate, years,
  monthly_rent_minor, monthly_amount_minor, expected_return, years_until,
  monthly_income_needed_minor.

You do not answer the question. You only decide which calculator answers it and
which numbers the user supplied."""


def route(question: str, *, use_llm: bool = True) -> Routing:
    """Route a question, with a model when one is configured.

    The model's answer is accepted only when it names a real slug and supplies
    parameters this module knows. Anything else falls back to the deterministic
    routing, which has already run — so an unavailable or confused model costs
    nothing but the round trip.
    """
    baseline = route_deterministic(question)
    if not use_llm:
        return baseline

    available, _why = llm_available()
    if not available:
        return baseline

    try:
        raw = complete_json(system=SYSTEM, user=question)
    except LLMError:
        return baseline

    if not isinstance(raw, dict):
        return baseline
    slug = raw.get("slug")
    if slug not in QUESTION_LABELS:
        # A model that cannot place the question does not get to overrule a
        # deterministic match that did.
        return baseline

    known = {
        "property_price_minor",
        "deposit_minor",
        "annual_rate",
        "years",
        "monthly_rent_minor",
        "monthly_amount_minor",
        "expected_return",
        "years_until",
        "monthly_income_needed_minor",
        "annual_tax_minor",
        "annual_insurance_minor",
        "monthly_pension_income_minor",
    }
    params = {}
    for key, value in (raw.get("params") or {}).items():
        if key not in known or not isinstance(value, (int, float)):
            continue  # unknown keys dropped, same as ask.py's allow-list
        params[key] = value

    missing = [f for f in REQUIRED.get(slug, []) if f not in params]
    return Routing(slug=slug, params=params, missing=missing, llm_used=True)


def describe_missing(routing: Routing) -> str:
    """What to tell someone whose question could not be answered as asked."""
    if routing.slug is None:
        return f"{routing.detail} It can answer: " + "; ".join(QUESTION_LABELS.values()) + "."
    pretty = ", ".join(m.replace("_minor", "").replace("_", " ") for m in routing.missing)
    return (
        f"That looks like “{QUESTION_LABELS[routing.slug]}”, but it needs "
        f"{pretty} before it can compute anything. Nothing is assumed here — a "
        "mortgage answered with an invented interest rate would look like an answer "
        "and would not be one."
    )

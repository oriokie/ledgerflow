"""Putting a decision into words — without letting a model near the numbers.

`apps.projections.decisions` computes a verdict and the figures behind it. This
module turns that into prose. The whole design question is how much of the
prose a language model is allowed to write, and the answer here is: the joins,
never the facts.

**The rule, inherited from `ask.py`.** That module refused the obvious shape —
send the model some transactions, let it reply in prose — because a plausible
wrong number is indistinguishable from a right one and there is nothing for the
user to check it against. It solved that by having the model emit a *filter*
and letting the product do the arithmetic. The same problem arrives here in a
harder form, because a decision genuinely does want narrative, so the guarantee
has to be enforced rather than designed around:

    every figure in the final text is one the decision engine computed.

`_check_figures` parses each number out of the model's reply and rejects the
whole response if any of them is not in the decision's allow-list. Not repairs
— rejects, and falls back to the deterministic rendering. A model that invents
"you'd save about 40,000" where the real figure is 4,000 has not made a typo,
it has made something up, and the rest of its paragraph is no longer worth
trusting either.

**The deterministic rendering is the product, not the fallback.** It runs
first, it is always complete, and it is what ships when no model is configured
— which is the default. The LLM tier only ever replaces the connective tissue.
Nothing here is required for the feature to work, which is the same standard
every other provider in this app is held to.

Nothing this module returns is advice. It explains a calculation and names what
it assumed; the wording throughout is chosen to keep that distinction visible,
because the product is decision support and a regulated activity is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.projections.decisions import Confidence, Decision, Verdict

from .llm import LLMError, complete, llm_available

#: How a verdict opens. Deliberately plain: an answer that hedges in its first
#: clause has not answered.
VERDICT_OPENER = {
    Verdict.YES: "Yes.",
    Verdict.YES_WITH_CARE: "Yes, with one thing to watch.",
    Verdict.TIGHT: "Only just.",
    Verdict.NO: "Not as it stands.",
    Verdict.UNKNOWN: "There isn't enough recorded to answer this yet.",
}

#: What each confidence level actually means, in words rather than a badge.
CONFIDENCE_SENTENCE = {
    Confidence.MEASURED: (
        "This rests almost entirely on what your ledger already records, so it is about "
        "as solid as an answer of this kind gets."
    ),
    Confidence.MIXED: (
        "Your position is measured; the years ahead are assumed. Treat the direction as "
        "reliable and the exact figures as a sketch."
    ),
    Confidence.ASSUMED: (
        "Most of this rests on assumptions about returns and inflation over a long "
        "period. It is a way to compare options, not a forecast."
    ),
}

#: Numbers that carry no information about someone's money and therefore do not
#: need to be in the allow-list: years, small counts, percentages already stated
#: in the findings. Kept tight on purpose — the looser this is, the weaker the
#: guarantee.
_SAFE_SMALL_NUMBER = 200

#: A bare number in this range, written without a thousands separator, is a
#: calendar year rather than an amount. The decisions layer genuinely produces
#: them ("around 2041"), so the check has to let them through.
_YEAR_FLOOR = 1900
_YEAR_CEILING = 2200


@dataclass(frozen=True)
class Explanation:
    """A decision in prose."""

    headline: str
    paragraphs: list[str] = field(default_factory=list)
    #: True when a model wrote the connective text. Surfaced so the UI can say
    #: so — a user is entitled to know which sentences a model touched.
    llm_used: bool = False
    #: Why the model's text was not used, when it wasn't. Empty when it was, or
    #: when none was configured.
    rejected_reason: str = ""


def _money(amount_minor: int, currency: str) -> str:
    """Whole units with thousands separators. Rendering happens here rather
    than in the client so the figure in the prose and the figure in the table
    are produced by the same code."""
    return f"{currency} {amount_minor / 100:,.2f}"


def render(decision: Decision, *, currency: str) -> Explanation:
    """The deterministic explanation. Always available, always complete."""
    paragraphs: list[str] = []

    opener = VERDICT_OPENER.get(decision.verdict, "")
    paragraphs.append(f"{opener} {decision.headline}".strip())

    if decision.because:
        reasons = "; ".join(_finding_sentence(f, currency) for f in decision.because)
        paragraphs.append(f"What it turns on: {reasons}.")

    if decision.costs:
        costs = "; ".join(_finding_sentence(f, currency) for f in decision.costs)
        paragraphs.append(f"What it costs: {costs}.")

    if decision.risks:
        risks = " ".join(f"{f.label}: {f.text}" for f in decision.risks)
        paragraphs.append(f"What could go wrong. {risks}")

    if decision.alternatives:
        alternatives = "; ".join(_finding_sentence(f, currency) for f in decision.alternatives)
        paragraphs.append(f"Worth considering instead: {alternatives}.")

    paragraphs.append(CONFIDENCE_SENTENCE.get(decision.confidence, ""))
    return Explanation(headline=decision.headline, paragraphs=[p for p in paragraphs if p])


def _finding_sentence(finding, currency: str) -> str:
    if finding.amount_minor is not None:
        return f"{finding.label.lower()} is {_money(finding.amount_minor, currency)}"
    return f"{finding.label.lower()} — {finding.text.rstrip('.')}"


# ---------------------------------------------------------------------------
# the optional model tier
# ---------------------------------------------------------------------------
SYSTEM = """You explain a financial calculation that has already been done.

Absolute rules:
- Never state a number that is not in the FIGURES list you are given. Not an
  approximation of one, not a rounding of one, not a new one you derived.
- Never give advice or tell the reader what to do. Explain what the
  calculation found and what it assumed.
- Do not add caveats about consulting a professional; the product handles that.
- Two short paragraphs, plain language, no headings, no bullet points, no
  markdown.

You are writing for someone who asked a question about their own money and got
an answer. Explain why the answer came out that way."""


def explain(decision: Decision, *, currency: str, use_llm: bool = True) -> Explanation:
    """Deterministic explanation, optionally rephrased by a configured model.

    The model's reply is accepted only if every figure in it appears in the
    decision's allow-list. Otherwise the deterministic text stands and the
    reason is recorded — visibly, because silently discarding a model's output
    would make an operator think the feature was working when it was not.
    """
    baseline = render(decision, currency=currency)
    if not use_llm:
        return baseline

    available, _why = llm_available()
    if not available:
        return baseline

    allowed = decision.figures()
    figures = ", ".join(_money(f, currency) for f in sorted(allowed)) or "none"
    user = "\n".join(
        [
            f"QUESTION: {decision.question}",
            f"ANSWER: {decision.verdict} — {decision.headline}",
            f"FIGURES you may use, and no others: {figures}",
            "",
            "FINDINGS:",
            *[f"- {f.label}: {f.text}" for f in decision.because],
            *[f"- cost — {f.label}: {f.text}" for f in decision.costs],
            *[f"- risk — {f.label}: {f.text}" for f in decision.risks],
            *[f"- alternative — {f.label}: {f.text}" for f in decision.alternatives],
            "",
            "ASSUMPTIONS: " + "; ".join(decision.assumptions),
        ]
    )

    try:
        text = complete(system=SYSTEM, user=user)
    except LLMError as exc:
        return Explanation(
            headline=baseline.headline,
            paragraphs=baseline.paragraphs,
            rejected_reason=f"the model could not be reached ({exc})",
        )

    problem = _check_figures(text, allowed)
    if problem:
        return Explanation(
            headline=baseline.headline,
            paragraphs=baseline.paragraphs,
            rejected_reason=problem,
        )

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return baseline
    return Explanation(
        headline=decision.headline,
        paragraphs=paragraphs + [CONFIDENCE_SENTENCE.get(decision.confidence, "")],
        llm_used=True,
    )


#: Numbers as they appear in prose: 1,234.56 / 1234 / 12.5
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _check_figures(text: str, allowed_minor: set[int]) -> str:
    """Reject the whole reply if it contains a figure we did not compute.

    Reject rather than repair. A model that writes "about 40,000" where the
    figure is 4,000 has not mistyped, it has invented — and the sentence around
    the invention is no longer worth keeping either.

    Three things pass without being allow-listed, each because it carries no
    claim about the size of someone's money:

    * small integers — counts, "3 months", "25 years";
    * percentages, which the findings already state and which cannot be
      mistaken for a balance;
    * bare four-digit years. The decisions layer says things like "around
      2041", and rejecting that would make the feature unusable. A *comma* is
      the discriminator: "2041" reads as a year and "2,041" reads as money, so
      only the unseparated form is exempt.
    """
    allowed_major = {round(a / 100, 2) for a in allowed_minor}
    # Also allow the whole-unit rounding a model will naturally reach for.
    allowed_major |= {float(round(a / 100)) for a in allowed_minor}

    for match in _NUMBER.finditer(text):
        raw = match.group(0)
        # A percentage is not a claim about a balance.
        after = text[match.end() : match.end() + 1]
        if after == "%":
            continue
        try:
            value = float(raw.replace(",", ""))
        except ValueError:  # pragma: no cover - regex guarantees parseability
            continue
        if value <= _SAFE_SMALL_NUMBER and value == int(value):
            continue
        if "," not in raw and value == int(value) and _YEAR_FLOOR <= value <= _YEAR_CEILING:
            continue
        if round(value, 2) in allowed_major or float(round(value)) in allowed_major:
            continue
        return f"the model stated a figure the calculation did not produce ({raw})"
    return ""

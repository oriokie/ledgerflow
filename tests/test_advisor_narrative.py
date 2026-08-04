"""The narrative layer, and the guarantee that holds it together.

One property matters more than the rest: **every figure in the final text is
one the decision engine computed.** Everything else here is presentation; that
one is the reason a verdict can be shown at all.

The tests exercise the check directly and through a stubbed model, including
the case that motivates it — a model that states a plausible, wrong number.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.intelligence import advisor
from apps.projections import decisions as dec
from apps.projections.engine import FinancialPosition

TODAY = date(2026, 1, 31)


def position(**kwargs) -> FinancialPosition:
    base = {
        "currency": "KES",
        "as_of": TODAY,
        "liquid_minor": 8_000_000,
        "monthly_net_income_minor": 600_000,
        "monthly_expenses_minor": 350_000,
    }
    base.update(kwargs)
    return FinancialPosition(**base)


def a_decision() -> dec.Decision:
    return dec.can_i_afford_mortgage(
        position=position(),
        property_price_minor=20_000_000,
        deposit_minor=5_000_000,
        annual_rate=0.09,
    )


# ---------------------------------------------------------------------------
# the deterministic rendering — the product, not the fallback
# ---------------------------------------------------------------------------


def test_the_deterministic_explanation_is_complete_without_any_model():
    explanation = advisor.explain(a_decision(), currency="KES", use_llm=False)
    assert explanation.paragraphs
    assert not explanation.llm_used
    assert explanation.headline


def test_it_opens_with_an_answer_rather_than_a_hedge():
    explanation = advisor.render(a_decision(), currency="KES")
    assert explanation.paragraphs[0].startswith(("Yes", "Only just", "Not as it stands", "There isn't"))


def test_every_section_of_a_decision_reaches_the_prose():
    decision = dec.can_i_afford_mortgage(
        position=position(monthly_net_income_minor=400_000),
        property_price_minor=40_000_000,
        deposit_minor=4_000_000,
        annual_rate=0.09,
    )
    text = " ".join(advisor.render(decision, currency="KES").paragraphs)
    assert "What it turns on" in text
    assert "What it costs" in text
    assert "What could go wrong" in text
    assert "Worth considering instead" in text


def test_confidence_is_explained_in_words_not_shown_as_a_badge():
    explanation = advisor.render(a_decision(), currency="KES")
    expected = advisor.CONFIDENCE_SENTENCE[a_decision().confidence]
    assert expected in explanation.paragraphs


def test_it_does_not_tell_the_reader_what_to_do():
    """The product is decision support. Explaining a calculation is not advice,
    and the wording has to keep that visible."""
    text = " ".join(advisor.render(a_decision(), currency="KES").paragraphs).lower()
    for imperative in ("you should", "we recommend", "you must", "i advise"):
        assert imperative not in text


# ---------------------------------------------------------------------------
# the figure allow-list
# ---------------------------------------------------------------------------


def test_a_figure_the_calculation_produced_is_allowed():
    allowed = {5_000_000}  # KES 50,000.00
    assert advisor._check_figures("The deposit is KES 50,000.00.", allowed) == ""


def test_a_rounded_version_of_a_real_figure_is_allowed():
    allowed = {5_000_000}
    assert advisor._check_figures("The deposit is about KES 50,000.", allowed) == ""


def test_an_invented_figure_is_rejected():
    """The case the whole module exists for: a plausible wrong number is
    indistinguishable from a right one to the person reading it."""
    allowed = {400_000}  # 4,000.00
    problem = advisor._check_figures("You would save about 40,000 over the term.", allowed)
    assert problem
    assert "40,000" in problem


def test_small_counts_and_years_pass_without_being_allow_listed():
    """Demanding these be listed would reject almost every well-formed
    sentence, and they carry no claim about the size of anyone's money."""
    assert advisor._check_figures("Over 25 years, across 3 months, by 2041.", set()) == ""


def test_percentages_pass_because_they_cannot_be_mistaken_for_a_balance():
    assert advisor._check_figures("That is 30% of your income.", set()) == ""


def test_a_large_number_with_no_backing_is_rejected_even_alone():
    assert advisor._check_figures("You will have 1,250,000 left.", set()) != ""


# ---------------------------------------------------------------------------
# the model tier
# ---------------------------------------------------------------------------


@pytest.fixture
def model(monkeypatch):
    """Stub the LLM so these tests never make a network call."""

    def install(reply: str | Exception):
        monkeypatch.setattr(advisor, "llm_available", lambda: (True, ""))

        def fake_complete(*, system: str, user: str, config=None):
            if isinstance(reply, Exception):
                raise reply
            return reply

        monkeypatch.setattr(advisor, "complete", fake_complete)

    return install


def test_a_clean_model_reply_is_used(model):
    decision = a_decision()
    deposit = next(f for f in decision.because if f.amount_minor)
    model(
        f"The payment fits comfortably inside your income.\n"
        f"The deposit of KES {deposit.amount_minor / 100:,.2f} is the part worth thinking about."
    )
    explanation = advisor.explain(decision, currency="KES")
    assert explanation.llm_used
    assert not explanation.rejected_reason


def test_a_model_that_invents_a_figure_is_rejected_wholesale(model):
    """Not repaired — rejected. The sentence around an invention is no longer
    worth keeping either."""
    model("You would be left with KES 999,999,999.00, which is plenty.")
    explanation = advisor.explain(a_decision(), currency="KES")
    assert not explanation.llm_used
    assert "did not produce" in explanation.rejected_reason
    # ...and the deterministic text still ships.
    assert explanation.paragraphs


def test_an_unreachable_model_falls_back_and_says_so(model):
    from apps.intelligence.llm import LLMError

    model(LLMError("timeout"))
    explanation = advisor.explain(a_decision(), currency="KES")
    assert not explanation.llm_used
    assert "could not be reached" in explanation.rejected_reason
    assert explanation.paragraphs


def test_no_configured_model_is_not_an_error(monkeypatch):
    """The product ships fully functional with LLM features off, which is the
    default and the standard every provider in this app is held to."""
    monkeypatch.setattr(advisor, "llm_available", lambda: (False, "LLM features are turned off."))
    explanation = advisor.explain(a_decision(), currency="KES")
    assert not explanation.llm_used
    assert not explanation.rejected_reason
    assert explanation.paragraphs


def test_the_model_is_told_which_figures_it_may_use(model, monkeypatch):
    captured = {}

    monkeypatch.setattr(advisor, "llm_available", lambda: (True, ""))

    def fake_complete(*, system: str, user: str, config=None):
        captured["system"] = system
        captured["user"] = user
        return "A short explanation with no figures at all."

    monkeypatch.setattr(advisor, "complete", fake_complete)

    advisor.explain(a_decision(), currency="KES")
    assert "FIGURES you may use, and no others" in captured["user"]
    assert "Never state a number that is not in the FIGURES list" in captured["system"]


def test_the_confidence_sentence_survives_the_model(model):
    model("A clean explanation.\nWith two paragraphs.")
    explanation = advisor.explain(a_decision(), currency="KES")
    assert explanation.llm_used
    expected = advisor.CONFIDENCE_SENTENCE[a_decision().confidence]
    assert expected in explanation.paragraphs

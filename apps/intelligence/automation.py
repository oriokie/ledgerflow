"""Rule-based automation engine.

Evaluates `AutomationRule`s against a transaction in priority order and applies
their actions. Two safety properties by construction:

* **Deterministic & pure evaluation.** Conditions are a small, closed
  expression language (`all`/`any` of field-op-value clauses). No code eval, no
  model calls — a rule does exactly the same thing every time, which is the
  whole reason users trust automation with their money.

* **Allow-listed actions.** An action can only be one of a fixed set that map
  to safe, reversible engine operations (set category, add tag, flag for
  review). A rule can never post, void, or move money — those stay behind
  explicit human/service calls. This is what lets us store rule bodies as
  flexible JSON without opening a hole.

LLM integration point: an assistant can *author* rules from natural language
("categorize anything from Whole Foods as groceries and tag it") by emitting
this same JSON, which is then shown to the user for confirmation before it's
saved. The LLM writes rules; it never executes them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---- condition language ----------------------------------------------------
_OPS = {
    "eq": lambda a, b: a == b,
    "contains": lambda a, b: b.lower() in str(a).lower(),
    "startswith": lambda a, b: str(a).lower().startswith(str(b).lower()),
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
    "abs_gte": lambda a, b: abs(a) >= b,
    "abs_lte": lambda a, b: abs(a) <= b,
    # Case-insensitive, unanchored — same "does this text contain a match"
    # semantics as `contains`, just with a pattern instead of a literal. A
    # statement memo like "Pay Bill Online to 4161505 - PARKNGO LIMITED Acc.
    # Garden- sp" matches field=memo, op=regex, value="PARKNGO" with no
    # anchoring needed.
    "regex": lambda a, b: re.search(b, str(a), re.IGNORECASE) is not None,
}

# fields a rule may read off a transaction feature dict
_ALLOWED_FIELDS = {
    "payee_normalized",
    "memo",
    "amount_minor",
    "currency",
    "account_type",
    "category_id",
}

# actions a rule may request -> validated & executed by the caller
ALLOWED_ACTION_TYPES = {"set_category", "add_tag", "flag_review"}


class AutomationError(Exception): ...


@dataclass(frozen=True, slots=True)
class RuleMatch:
    rule_id: str
    rule_name: str
    actions: tuple[dict, ...]
    stop_processing: bool


def _clause_matches(clause: dict, features: dict) -> bool:
    field = clause.get("field")
    op = clause.get("op")
    value = clause.get("value")
    if field not in _ALLOWED_FIELDS:
        raise AutomationError(f"Rule references unknown field {field!r}.")
    if op not in _OPS:
        raise AutomationError(f"Rule uses unknown operator {op!r}.")
    actual = features.get(field)
    if actual is None:
        return False
    try:
        return _OPS[op](actual, value)
    except (TypeError, re.error):
        return False


def conditions_match(conditions: dict, features: dict) -> bool:
    """Evaluate an all/any condition tree. Empty conditions never match (a rule
    must be explicit about what it targets — no accidental match-all)."""
    if not conditions:
        return False
    if "all" in conditions:
        clauses = conditions["all"]
        return bool(clauses) and all(_clause_matches(c, features) for c in clauses)
    if "any" in conditions:
        clauses = conditions["any"]
        return bool(clauses) and any(_clause_matches(c, features) for c in clauses)
    raise AutomationError("Conditions must have an 'all' or 'any' key.")


def validate_conditions(conditions: dict) -> None:
    """Walk the condition tree and compile every regex clause, so a bad
    pattern 422s at save time instead of failing silently (as a permanent
    non-match, via `_clause_matches`'s own `re.error` guard) inside the
    post_save signal on the next matching transaction.

    Deliberately shallow: the stored schema is one level of `all` *or* `any`,
    never nested (see `conditions_match`), so this validates exactly what the
    evaluator supports rather than inventing structure it doesn't use.
    """
    clauses = conditions.get("all") or conditions.get("any") or []
    for clause in clauses:
        if clause.get("op") == "regex":
            try:
                re.compile(str(clause.get("value", "")))
            except re.error as exc:
                raise AutomationError(f"Invalid regex {clause.get('value')!r}: {exc}") from exc


def validate_actions(actions: list[dict]) -> None:
    """Reject a rule whose actions aren't on the allow-list — called at save
    time so a bad rule never reaches execution."""
    for action in actions:
        if action.get("type") not in ALLOWED_ACTION_TYPES:
            raise AutomationError(
                f"Action type {action.get('type')!r} is not allowed. "
                f"Permitted: {sorted(ALLOWED_ACTION_TYPES)}."
            )


def evaluate_rules(rules: list, features: dict) -> list[RuleMatch]:
    """Run active rules (already ordered by priority) against one transaction's
    features. Returns the ordered matches; honors `stop_processing`."""
    matches: list[RuleMatch] = []
    for rule in rules:
        if not rule.is_active:
            continue
        if conditions_match(rule.conditions, features):
            validate_actions(rule.actions)
            matches.append(
                RuleMatch(
                    rule_id=str(rule.id),
                    rule_name=rule.name,
                    actions=tuple(rule.actions),
                    stop_processing=rule.stop_processing,
                )
            )
            if rule.stop_processing:
                break
    return matches

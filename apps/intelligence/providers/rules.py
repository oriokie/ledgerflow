"""Rule-based categorization — the shipping default.

Two tiers, cheapest first:

1. **Merchant memory** — if this payee has been categorized before, reuse the
   most recent choice with high confidence. This is where most real accuracy
   comes from and it needs no AI at all; it also improves automatically as the
   user categorizes, because it reads their own history.
2. **Keyword rules** — a config-driven map from keywords to category slugs,
   for first-time payees.

Returns a `CategorySuggestion` with calibrated confidence and full provenance.
An `LLMCategorizer` will later implement the identical `suggest_category`
method; the registry swaps them with no change to callers, and an ensemble can
take merchant-memory as a strong prior and ask the LLM only on low-confidence
first-time payees (the expensive case), keeping cost down.
"""

from __future__ import annotations

import hashlib

from ..protocols import (
    CategorizationProvider,
    CategorySuggestion,
    Provenance,
    ProviderKind,
    TransactionFeatures,
)

VERSION = "1.0.0"

# Keyword -> category slug. Config seed; a real deployment loads/extends this
# per tenant. Order matters only for readability — matching checks all.
DEFAULT_KEYWORD_RULES: dict[str, str] = {
    "coffee": "dining_out",
    "cafe": "dining_out",
    "restaurant": "dining_out",
    "grill": "dining_out",
    "market": "groceries",
    "grocery": "groceries",
    "foods": "groceries",
    "uber": "transport",
    "lyft": "transport",
    "transit": "transport",
    "fuel": "transport",
    "gas": "transport",
    "rent": "rent",
    "property": "rent",
    "electric": "utilities",
    "utility": "utilities",
    "internet": "utilities",
    "netflix": "subscriptions",
    "spotify": "subscriptions",
    "subscription": "subscriptions",
    "payroll": "salary",
    "salary": "salary",
}


def _digest(features: TransactionFeatures) -> str:
    raw = f"{features.payee_normalized}|{features.memo}|{features.amount_minor}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


class RuleBasedCategorizer(CategorizationProvider):
    def __init__(self, keyword_rules: dict[str, str] | None = None, slug_to_id: dict[str, str] | None = None):
        # slug_to_id lets the caller map rule slugs to this tenant's real
        # category ids; without it the provider returns slugs as ids (useful in
        # tests and as a stable contract).
        self._rules = keyword_rules or DEFAULT_KEYWORD_RULES
        self._slug_to_id = slug_to_id or {}

    def _resolve(self, slug: str) -> str:
        return self._slug_to_id.get(slug, slug)

    def suggest_category(self, features: TransactionFeatures) -> CategorySuggestion:
        digest = _digest(features)

        # Tier 1: merchant memory — reuse this payee's most recent category.
        if features.recent_category_ids_for_payee:
            most_recent = features.recent_category_ids_for_payee[0]
            return CategorySuggestion(
                category_id=most_recent,
                confidence=0.95,
                provenance=Provenance(
                    provider="RuleBasedCategorizer",
                    kind=ProviderKind.RULE,
                    version=VERSION,
                    rationale=f"Reused the category last used for '{features.payee_normalized}'.",
                    inputs_digest=digest,
                ),
                alternatives=tuple((cid, 0.6) for cid in features.recent_category_ids_for_payee[1:3]),
            )

        # Tier 2: keyword rules over payee + memo.
        haystack = f"{features.payee_normalized} {features.memo}".lower()
        matches = [(kw, slug) for kw, slug in self._rules.items() if kw in haystack]
        if matches:
            # longest keyword wins — more specific
            keyword, slug = max(matches, key=lambda m: len(m[0]))
            return CategorySuggestion(
                category_id=self._resolve(slug),
                confidence=0.75,
                provenance=Provenance(
                    provider="RuleBasedCategorizer",
                    kind=ProviderKind.RULE,
                    version=VERSION,
                    rationale=f"Matched keyword '{keyword}' in payee/memo.",
                    inputs_digest=digest,
                ),
                alternatives=tuple((self._resolve(s), 0.4) for _, s in matches if s != slug)[:3],
            )

        # No signal — abstain (None) rather than guess. An abstention is a
        # correct, honest answer that an LLM tier can then be asked to improve.
        return CategorySuggestion(
            category_id=None,
            confidence=0.0,
            provenance=Provenance(
                provider="RuleBasedCategorizer",
                kind=ProviderKind.RULE,
                version=VERSION,
                rationale="No merchant history or keyword match; abstained.",
                inputs_digest=digest,
            ),
        )

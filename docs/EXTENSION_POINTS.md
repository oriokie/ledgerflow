# Extension Points

Seams the codebase was deliberately designed to grow through, in rough order
of how often you'll use them.

## Adding an LLM provider

The single most-anticipated extension. Every AI capability is a `Protocol` in
`apps/intelligence/protocols.py` (`CategorizationProvider`, `ForecastProvider`,
`HealthScoreProvider`, `AnomalyProvider`, `RecommendationProvider`), and
concrete implementations are resolved by dotted path in `registry.py`.

To add an LLM categorizer:

1. Implement `apps/intelligence/providers/llm.py::LLMCategorizer` satisfying
   `CategorizationProvider`: a `suggest_category(self, features:
   TransactionFeatures) -> CategorySuggestion` method. Take the model-free
   `TransactionFeatures` DTO in, return a `CategorySuggestion` DTO out —
   never a Django model, never HTTP concerns.
2. Fill `Provenance` honestly (`provider="LLMCategorizer"`, `kind=ProviderKind.LLM`,
   a `version` you bump when the prompt/model changes, and `rationale` from
   the model's own explanation if available).
3. Point at it via settings, no code changes anywhere else:
   ```python
   INTELLIGENCE_PROVIDERS = {
       "categorization": "apps.intelligence.providers.llm.LLMCategorizer",
   }
   ```
4. Consider an **ensemble**: since `RuleBasedCategorizer`'s merchant-memory
   tier is already free and high-confidence, a natural design is "ask the LLM
   only when rules abstain" — wrap both providers in a new class satisfying
   the same protocol, call it from `INTELLIGENCE_PROVIDERS` like any other.

The same pattern applies to `ForecastProvider`, `HealthScoreProvider`,
`AnomalyProvider`, `RecommendationProvider` — one interface each, swap by
config. Whatever you build, remember: **AI output is always advisory.**
`intelligence.services` stores suggestions and applies them only through the
finance service layer after an explicit accept (human tap, or automatic if
confidence clears `INTELLIGENCE_AUTO_ACCEPT_CONFIDENCE`). Never have a new
provider write to the ledger directly.

## Adding an automation action

`apps/intelligence/automation.py::ALLOWED_ACTION_TYPES` is a closed allow-list
— a rule's `actions` JSON can only request one of these, validated at save
time (`validate_actions`) so a bad rule never reaches execution. Today:
`set_category`, `add_tag`, `flag_review`.

To add a new action (e.g. `set_wallet`):

1. Add the type string to `ALLOWED_ACTION_TYPES`.
2. Handle it in `apps/intelligence/services.py::_apply_action` — call the
   relevant **finance service function** (never a raw model write), return a
   human-readable effect string.
3. Add a test authoring a rule with the new action shape and asserting the
   effect, following the pattern in `tests/test_review_fixes.py::test_automation_flag_review_sets_real_state`.

Keep the "an action can only invoke a real, safe, already-existing engine
capability" invariant — this is what lets rule bodies be flexible JSON without
becoming an arbitrary-code-execution hole, and it's also what will let an LLM
someday *author* rules (natural language → this JSON) without ever being in
the execution path.

## Adding a new financial account type

`apps/finance/models.py::AccountType` is the enum; `apps/finance/services.py::_ASSET_TYPES`
/ `_LIABILITY_TYPES` decide which `ledger.AccountKind` backs it. To add e.g.
`AccountType.BROKERAGE`:

1. Add the choice to `AccountType`.
2. Add it to `_ASSET_TYPES` or `_LIABILITY_TYPES` in `services.py` — this is
   the only place that decides the ledger-kind mapping.
3. Migration: `makemigrations` (it's just a new `TextChoices` value, no schema
   change beyond the migration Django generates for the choices list).
4. No changes needed to `selectors.py` — `net_worth()`, `cash_flow()`, etc.
   already generalize over `AccountKind`, not the finer-grained `AccountType`.

## Adding an OAuth provider

`OAUTH_PROVIDERS` in `config/settings/base.py` is a plain dict — a new entry
(`authorize_url`, `token_url`, `userinfo_url`, `scope`, `client_id`/`client_secret`
from env) makes `/api/v1/auth/oauth/<provider>/authorize/` and
`.../callback/` work for it with zero code changes, as long as the provider
speaks standard OAuth2/OIDC. See `apps/users/services/oauth.py`.

## Adding an event consumer

Any code that needs to react to a domain event (a posted transaction, a new
member, an accepted invitation) should **not** hook into services directly —
subscribe to the outbox instead. Two ways:

- **In-process**: use Django's `post_save` signals the way
  `apps/finance/signals.py` does for cache invalidation — appropriate for
  fast, same-database reactions.
- **Out-of-process**: implement a new `EventPublisher`
  (`apps/common/publishing.py`) pointing at your message bus (SNS, Kafka,
  Pub/Sub — `RedisStreamPublisher` is the worked example) and set
  `EVENT_PUBLISHER` in settings. Your consumer then subscribes downstream of
  the broker, decoupled from the Django process entirely. Every event carries
  a stable `event_id` for idempotent consumption (at-least-once delivery).

## Adding a custom per-tenant role

Currently out of scope by design — `apps/tenancy/rbac.py`'s docstring
explains why: a fixed `VIEWER < MEMBER < ADMIN < OWNER` hierarchy covers real
personal-finance access patterns, and custom roles are a materially bigger
feature (role CRUD, migrating existing memberships when a role is edited or
deleted, UI for building permission sets). The seam is already there if you
need it: every caller asks `has_capability(membership, X)`, never `role >= Y`
directly (except where seniority itself is the rule, via `outranks()`). To
add custom roles, you'd extend `ROLE_CAPABILITIES` to be per-tenant-configurable
data instead of a fixed dict — callers wouldn't need to change.

## Adding a new tenant type

`apps/tenancy/models.py::TenantType` (`personal`/`household`/`organization`)
is a `TextChoices` distinguishing presentation/policy, not isolation — all
three share one `Tenant`/`Membership` schema. A new type is a new choice value
plus whatever policy differences you want to attach to it (e.g. a seat limit
check in `tenancy.services.add_member`); it does not require new tables or
new RLS policies.

## Cross-currency support (documented, not yet built)

`apps.fx.models.ExchangeRate` exists as reference data (timestamped,
attributed to a source) but nothing in `ledger` or `finance` consumes it yet
— every `post_journal_entry` call still requires all lines to share one
currency (`CurrencyMismatchError` otherwise). The intended seam: a future
`fx.services.convert()` producing a rate-attributed `Money`, and a
`record_transfer`-like service that posts a *three*-line entry (source
currency out, an FX clearing account, destination currency in) so the
audit trail shows the rate used at posting time. `net_worth()` and
`cash_flow()` already refuse to sum across currencies (returning a per-currency
list) specifically so this remains safe to add without a breaking change to
their contract.

## Adding a new module (bounded context)

Follow the shape every existing module uses: `models.py` (inherit
`TenantOwnedModel` for immutable financial data or `SoftDeletableModel` for
mutable domain data — see `apps/common/models.py`), `services.py` (the only
place state mutates, `@transaction.atomic`, emits `OutboxEvent`s for anything
worth telling other systems about), `selectors.py` (pure reads), `api/`
(serializers/views/urls), and register it in `LOCAL_APPS`
(`config/settings/base.py`) and `api_v1_patterns` (`config/urls.py`). If it
introduces new tenant-owned tables, add them to `RLS_TABLES` in
`apps/ledger/migrations/0002_financial_integrity.py`'s pattern — a new
context-specific migration doing the same `ENABLE`/`FORCE ROW LEVEL SECURITY`
+ policy DDL for its own tables (don't hand-edit the existing migration for a
new module; add a new one that follows the same shape).

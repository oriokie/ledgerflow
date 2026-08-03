# AI Financial Coach

The intelligence layer: it observes the user's finances, explains what it sees,
and ranks what matters. It is deliberately **not** an LLM feature — it is an
architecture into which an LLM can be dropped without a caller changing.

## The provider seam

The `intelligence` app already had a provider protocol layer before this work;
the coach extends it rather than replacing it.

```
InsightProvider    <- RuleBasedCoach     (today)
                   <- LLMCoach           (later, same interface)
NarrativeProvider  <- TemplateNarrator   (today)
                   <- LLMNarrator        (later, same interface)
```

Swapping either is a settings change:

```python
INTELLIGENCE_PROVIDERS = {
    "insight":   "myapp.providers.LLMCoach",
    "narrative": "myapp.providers.LLMNarrator",
}
```

Three properties make the seam real rather than aspirational:

**Providers never touch the ORM.** They receive a `CoachContext` — a frozen
dataclass of pre-computed figures — and return `InsightCandidate` objects.
Adding an LLM means writing a prompt over that dataclass; it does not mean
giving a model database access.

**Detection and narration are separate protocols.** Finding a condition and
describing it well are different problems with different failure modes. A
deterministic detector paired with an LLM narrator is a genuinely useful
configuration, and the split is what makes it expressible.

**The deterministic provider is real, not a placeholder.** The product works
with zero AI configuration, which also gives any future LLM provider a free
offline fallback.

## Configuring a model

Nothing here is required. `LLM_ENABLED` defaults to off and the product is
complete without it.

```bash
LLM_ENABLED=true
LLM_PROVIDER=groq          # or google, openrouter, together, mistral, ollama…
LLM_API_KEY=…              # not needed for local providers
LLM_SHARE_FINANCIAL_CONTEXT=true   # required for hosted providers
```

| Preset | Notes |
|---|---|
| `google`, `groq`, `openrouter`, `together`, `mistral` | Free tier available |
| `openai`, `anthropic`, `deepseek` | Paid |
| `ollama`, `lmstudio` | Local, no key, nothing leaves the machine |
| `custom` | Any OpenAI-compatible endpoint via `LLM_BASE_URL` |

Presets only supply defaults — `LLM_BASE_URL` and `LLM_MODEL` always win, so an
unlisted endpoint needs no code change.

### One adapter, not a dozen SDKs

Almost every popular and free-tier service now speaks the OpenAI
chat-completions wire format, so supporting Groq, OpenRouter, Together,
DeepSeek, Mistral, Ollama, LM Studio and vLLM is a base URL and a model name.
Anthropic and Google get small explicit adapters. That's three request shapes
covering roughly a dozen services, with **no vendor SDK dependency anywhere** —
`requests` was already in the tree.

### Two switches, not one

`LLM_ENABLED` turns the feature on. `LLM_SHARE_FINANCIAL_CONTEXT` permits
sending a household's spending summary to a third party. They're separate
because they're different decisions, and the second one is somebody's private
finances. Local providers are exempt: nothing leaves the machine, so there's
nothing to consent to.

### Enabling narration before detection

`LLMNarrator` rewords figures the engine already computed and validated.
`LLMCoach` decides what's worth saying. The first carries far less risk than the
second, and the split between the protocols exists so you can take one without
the other:

```python
INTELLIGENCE_PROVIDERS = {
    "narrative": "apps.intelligence.providers.llm_coach.LLMNarrator",
}
```

### What a model is not allowed to do

- **Replace the deterministic engine.** `LLMCoach` always runs `RuleBasedCoach`
  first and *adds* to its output. A predicted overdraft is never missed because
  a model was having an off day.
- **Break the product when it fails.** Timeouts, rate limits, outages and
  malformed JSON all fall back to rules. A misconfigured key means the full
  product, not an empty screen.
- **Supply its own figures.** Model-authored insights carry `evidence={}` — the
  model phrases numbers the engine produced. A number a model invented is a
  number nobody computed.
- **Invent an insight type or skip the explanation.** Candidates are validated
  against the taxonomy and must have a rationale. Anything malformed is dropped
  silently.
- **Flood the feed.** Capped at six candidates per run, and discounted in
  scoring against rule-based ones.

The settings panel at **Settings → AI & insights** reports what's configured and,
crucially, *why it isn't working* — "I turned it on and nothing happened" is the
most common and most silent failure mode here. The API key is never returned by
the API, only whether one is present.

## What the coach cannot do

Every `InsightCandidate` must carry a `rationale` and a `dedupe_key`. This is a
contract, not a convention, and it is the main safeguard against a future LLM:

- **`rationale`** — an insight a user can't check is one they can't trust. A
  model must state why, in terms of the figures it was given.
- **`evidence`** — the numbers behind the claim, so it's auditable rather than
  oracular.
- **Nothing writes to the ledger.** Insights are advisory. The immutable
  double-entry core is never at the mercy of a model.

A test asserts every candidate from the shipping provider has both fields.

## Scoring

A coach that surfaces twenty things surfaces nothing. `scoring.py` is a pure
function — no database, no provider — so it's directly testable and the feed is
stable between runs.

| Factor | Max points | Why weighted this way |
|---|---|---|
| Severity | 60 | A deadline outranks an idea, however large |
| Magnitude | 22 | How much is at stake, **relative to the user's own scale** |
| Urgency | 12 | How soon it matters |
| Confidence | 6 | Weighted lightly — see below |

**Magnitude is relative.** £200 means something different to someone spending
£800 a month than to someone spending £8,000. Absolute thresholds are how a
coach ends up shouting at wealthy users and whispering at everyone else.

**Confidence is weighted lightly on purpose.** Once an LLM is supplying that
number *about itself*, a provider that could rank itself first would eventually
rank itself first for everything. There's a test asserting confidence can never
outweigh even the lowest severity band.

`explain_score()` returns the breakdown, so ranking can be justified rather
than asserted.

## Severity discipline

`CRITICAL` requires a deadline. Today only cash-flow risk earns it, because a
projected overdraft has a date attached and an overspend doesn't. A test pins
this: a wildly-over budget line plus large debt plus zero savings produces
*nothing* critical.

A coach that shouts about everything gets muted.

## Idempotent generation

The coach runs on a schedule, so the same condition is detected every morning.
`dedupe_key` encodes the **condition**, not the run:

```
overspending:{category_id}:{period_end}
cashflow_risk:{first_negative_date}
```

Re-detection refreshes the evidence on the existing row. Without this, a user
would wake to a fresh copy of "you're over budget on groceries" every day, and
dismissing one would achieve nothing.

**A dismissal is never overridden.** Re-detection updates a dismissed insight's
figures but does not return it to the feed. Overriding a user's dismissal is
how a product teaches people to stop reading it.

Bookmarked insights *stay* in the feed — a bookmark means "keep this in front
of me", which is the opposite of a dismissal.

## Insight taxonomy

Thirteen kinds: spending anomaly, overspending, budget recommendation, savings
opportunity, duplicate transaction, large purchase, merchant change, salary
change, cash-flow risk, subscription review, goal recommendation, debt
recommendation, health improvement.

**Every kind is reachable**, and a test asserts it: a taxonomy value with a
model, an icon and a label but no detector behind it is a promise the product
never keeps. Merchant change, income change and health improvement were exactly
that until the context builder was extended to feed them.

Some detectors are deliberately restrained about firing:

* **Merchant change** requires at least two prior charges from that payee.
  Treating a first-ever purchase as a price rise is the false alarm that gets a
  coach muted.
* **Income change** needs a full prior month and a 15% move, because pay varies
  for benign reasons — overtime, a five-week month, a bonus — and a false
  "your income dropped" is genuinely alarming.
* **Price drops are reported too.** A coach that only ever delivers bad news is
  one people stop opening.

Wording rules that matter as much as detection:

- **Say the number.** "You've spent £412 of your £350 grocery budget" is
  checkable; "you're overspending" is an accusation.
- **Never assert what was only observed.** Two identical charges on one day are
  a *candidate* duplicate — the copy says "worth checking", because telling
  someone they were double-charged when they bought two coffees costs more
  trust than the catch was worth.

## Briefings

Daily, weekly and monthly narrative reviews. Unique per
`(tenant, period, period_start)`, so a re-run refreshes rather than duplicates.

The narrator leads with the most severe insight, and when there's nothing to
report it says so — "Nothing needs your attention today" is a real, useful
answer, and far better than inventing something.

`metrics` stores the figures the prose was written from, so the narrative can
always be checked against the numbers.

## Context building

`coach_context.py` is the only file in the coaching layer that touches the ORM,
and it composes **existing, already-tested selectors** — budget status, the
cash-flow statement, the cash-flow calendar, goal recommendations — rather than
recomputing anything.

Reimplementing "how much did they spend on groceries" inside the coach would
create a second source of truth that drifts from the one the dashboard shows,
and a coach that disagrees with the dashboard is worse than no coach.

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/intelligence/insights/` | Feed. `?status=bookmarked\|dismissed\|all` |
| `POST` | `/api/v1/intelligence/insights/generate/` | Re-run. Idempotent. |
| `POST` | `/api/v1/intelligence/insights/{id}/{decision}/` | `dismiss`, `bookmark`, `seen`, `acted` |
| `GET` | `/api/v1/intelligence/briefing/{period}/` | `daily`, `weekly`, `monthly` |

Reading and generating are separate verbs so opening the dashboard never blocks
on a full recompute.

## Scheduling

`intelligence.dispatch_coach_run` runs daily at 05:30 — after the nightly
recurring-transaction and bill jobs, so the coach reasons over today's posted
state rather than yesterday's. Same fan-out topology as the other sweeps: stream
active tenants, batch, one isolated per-tenant task under its own RLS binding.

Each run purges expired insights, regenerates the feed, and writes the daily
briefing. Weekly briefings are written on Mondays and monthly ones on the 1st,
rather than every day: rewriting "this month in review" each morning would mean
the user never sees a stable monthly summary.

The purge runs inside the same task rather than on its own schedule, so a
just-expired insight can't linger in the feed for up to a day.

## Multi-tenancy

`Insight` and `Briefing` are tenant-scoped with fail-closed RLS
(`0003_rls_coach_tables`). The M2M join table has no `tenant_id` of its own and
is protected by an EXISTS check against the parent briefing — without that, the
join table would be the one unguarded path to the data.

Insights describe a household's spending in plain language, so this is not
optional hardening.

## Frontend

| Surface | Where |
|---|---|
| Coach page | `/coach` — briefing over a ranked insight feed |
| Dashboard | Top three insights, linking through to the full feed |
| Nav | "Coach" under Intelligence |

**"Why am I seeing this?" is a first-class control, not a tooltip.** Every card
has a real, focusable disclosure that reveals the rationale, the figures the
claim was computed from, and which provider produced it. That last part matters
more once an LLM can author these.

**Severity is one accent edge, not a filled card.** The backend reserves
`critical` for conditions with a deadline; the UI has to honour that restraint
or the distinction stops meaning anything. Severity is also always stated as
text ("Needs attention"), never carried by colour alone.

**Evidence rendering is allow-listed.** Only keys with a known label are shown —
dumping an opaque dict at the user would defeat the point of evidence, which is
that it can be read. A test asserts every `_minor` key is formatted as money, so
a new one can't render as a raw integer like "35000".

**Unknown action verbs render no button.** `actionRoute()` returns null rather
than a link that goes nowhere, so a backend action the client doesn't recognise
degrades to a card with no CTA instead of a dead control.

Dismissal is optimistic — it's the most common action on the surface and
waiting on a round-trip makes the feed feel like a form. Rollback restores the
exact snapshot on failure, because a silently-failed dismissal would have the
card reappear later with no explanation.

## Testing

`tests/test_ai_coach.py` — 32 tests plus 1 conditional skip.

### A bug only an integration test could find

`list_transactions()` returns an **ordered** queryset, and Django folds
`ORDER BY` fields into `GROUP BY`. So `.values(...).annotate(...)` over it
produced one row per transaction instead of one per group — and the `n > 1`
filter that finds duplicates matched nothing, ever.

The duplicate and merchant-change detectors looked fully implemented, had unit
tests, and passed them all: the unit tests build a `CoachContext` by hand, so
they never exercised the query. Only an integration test that wrote real
transactions and read the context back could catch it.

Both aggregations now call `.order_by()` first. An audit of the other seven
`.values().annotate()` sites in `apps/` found no further exposure — they all
start from managers whose models have no `Meta.ordering`, so nothing leaks into
their `GROUP BY`. The risk is specific to querysets that already carry
ordering, whether from a selector or from `Meta.ordering`.

### Other bugs found during development

All of the same class — **claiming something we don't actually know**:

1. `savings_rate` defaulted to `0.0`, which is indistinguishable from a
   *measured* zero. An empty workspace was told "very little is being set
   aside" — a claim about figures that didn't exist. Now `float | None`.
2. Evidence dicts legitimately contain `date` objects that `JSONField` can't
   serialise, and the failure surfaced at save time rather than where the value
   was added. Now converted centrally.
3. The context builder assumed `Budget.period_start`/`period_end`; the model
   stores `starts_on` plus a period length. The end date is now derived.

A `StubCoach` test proves the registry seam: a custom provider is picked up by
a settings change alone, with the caller untouched.

Frontend — 29 tests across `InsightCard`, `BriefingCard`, `insightMeta` and
`useCoach`. Notable ones:

* the metadata test asserts an icon and label exist for **every** backend
  insight kind, so a kind added server-side can't render as a blank card;
* the optimistic-decision tests cover dismiss, bookmark, "acted", and rollback
  on failure;
* `actionRoute` is tested for unknown verbs returning null.

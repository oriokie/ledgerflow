# `analytics` — Reporting Platform

Fourteen dashboards, built as a **platform rather than fourteen reports**. That
decision shapes everything else: filtering, caching, export and rendering are
each written once, and adding report fifteen is one backend function with no
frontend change at all.

## One shape for every report

```python
@dataclass(frozen=True, slots=True)
class ReportResult:
    slug, title, currency, start, end
    totals: dict   # headline figures
    series: list   # anything plotted over time
    rows: list     # anything tabular
    meta: dict     # caveats, comparison windows, thresholds
```

A report fills whichever parts it needs. The client draws from what is present
plus a chart hint in the catalogue, so seven renderers cover all fourteen
dashboards.

| Group | Reports |
|---|---|
| Where you stand | Net worth, savings rate, financial health |
| Money in and out | Cash flow, income vs spending, income sources |
| Where it goes | Expense trends, categories, merchants, largest purchases, subscriptions |
| Compared | This month vs last, year over year, lifestyle inflation |

## Filters

One `ReportFilters` for all of them — the filters are the same because the
questions are the same shape: a window, optionally narrowed to some accounts or
categories.

Frozen and hashable, so it keys a cache entry directly.

**Named periods, not raw dates.** "This year" means something different
tomorrow, and a cached `2026-01-01 to 2026-12-31` would silently answer a
question nobody asked once the year turned.

**The comparison window matches the current one in length.** A 90-day view
compares against the preceding 90 days, not a fixed month. Comparing unequal
spans is the most common way a "vs last period" figure ends up meaningless.

Supplying explicit dates *is* the request for a custom window, so the API
promotes `period` to `custom` rather than honouring the named period and
quietly answering a different question. A half-specified range is a 400 rather
than a silent fallback.

## Caching

Version-stamped and tenant-scoped: every key embeds a per-tenant counter, and
invalidation is a single increment that orphans everything derived for that
tenant. O(1), no key enumeration, no stale key surviving because something
forgot to delete it.

**Two independent guards on cross-tenant leakage.** The tenant id is in the key
itself, not only in the version counter, so a coding error in the version logic
still cannot serve one workspace's figures to another. An unscoped read bypasses
the cache entirely rather than touching a shared key.

### The bug this work uncovered

`apps/common/cache.py` already implemented exactly this pattern and was already
used by the intelligence app. The analytics module had grown **a second version
counter**, which meant bumping one left the other serving stale figures.

Worse: `invalidate_tenant` was called by **nothing at all**. Every cached health
score, recommendation and forecast in the product was stale for the length of
its TTL after any posting.

Both fixed. `apps/analytics/cache.py` is now a thin adapter over the shared
counter, and `post_journal_entry` — the single choke point every financial write
passes through — schedules a bump.

The bump runs in `transaction.on_commit`, deliberately: a rolled-back posting
must not invalidate anything, and firing before the data is visible would let a
concurrent read repopulate the cache with pre-write figures. Failures are
swallowed and logged, because a cache backend being unreachable must never roll
back a journal entry.

## Honest emptiness

`is_empty` treats **all-zero totals as empty**. Every report populates the same
keys whether or not there is data behind them, so testing for a non-empty dict
would call `{"total_spend_minor": 0}` a finding — and the client would render
"you spent nothing", which is a claim rather than an absence. Empty reports
answer 204.

Reports flag their own limitations in `meta`: partial months, insufficient
history, a large uncategorised share. The renderer surfaces those **above the
chart**, because a half-finished month read as a collapse in spending is the
most common way any of this gets misread.

## Rendering

Seven chart types — area, line, bar, composed, donut, table, score — driven by
the catalogue. Field handling is derived from naming conventions the reports
already follow (`*_minor` is money, `label` is the display name, `*_id` is for
linking not reading), so a new report needs no mapping table.

Rows are clickable for drill-down only when a handler is wired, so nothing looks
interactive that isn't.

### A second bug this uncovered

`<Money neutral>` suppressed the minus sign as well as the colour coding. The
prop is documented as "suppress the in/out colour coding" — the sign
suppression was unintended scope creep in the implementation.

The consequence: any neutral total that could go negative rendered a −$450
deficit as a comfortable "$450". That affected report totals, net worth, the
debt summary and the portfolio.

Colour and sign are different channels. `neutral` now governs colour only.
Fixing it broke no existing test, which confirms nothing depended on the old
behaviour.

## API

| Method | Path |
|---|---|
| `GET` | `/api/v1/analytics/reports/` — catalogue with chart hints |
| `GET` | `/api/v1/analytics/reports/{slug}/` — 204 when empty |
| `GET` | `/api/v1/analytics/reports/{slug}/export/` — CSV |

Export writes **minor units**, unlike the debt schedule's major units. This is
machine-facing data headed for a pivot table, where rounding on the way out
would lose precision the caller may need; the debt schedule is read by people.
The header is the union of keys across all rows, so a report that omits a field
on some rows doesn't silently drop that column.

## UI

`/reports` — grouped tabs rather than fourteen charts on one screen, which is a
wall. Each report fetches independently, so one heavy query delays only its own
card. The period is chosen once and applies to all of them.

## Testing

`tests/test_analytics_platform.py` — 37 tests. The platform machinery is tested
once, then each report is checked for what it specifically claims.

The cache tests carry the most weight, including one asserting a posting
actually invalidates. That test needed `django_capture_on_commit_callbacks`:
pytest's surrounding transaction defers `on_commit` indefinitely, so without
executing the callbacks the test would pass against broken code — a false
negative on precisely the property that matters most.

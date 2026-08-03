# Mobile & PWA

LedgerFlow is a Progressive Web App, not a native app. Every capability below
is built on standard web platform APIs — WebAuthn, Web Push, Background Sync,
`getUserMedia` — rather than a native wrapper, which is a deliberate
trade-off: it means one codebase for every platform, but it also means being
honest about what a PWA genuinely can and cannot do. Where a capability has a
real ceiling (see **Home screen widgets** below), this document says so rather
than overclaiming.

## What's real vs. what a PWA can't do

**Home screen widgets** — there is no cross-platform web API for a live,
glanceable native widget. iOS has none at all for PWAs; Android's manifest
`shortcuts` (below) are the closest analogue, but they are long-press launch
shortcuts, not live-updating tiles. LedgerFlow ships shortcuts because they
are genuinely useful, not because they're the same thing.

Everything else — biometric login, push notifications, offline support,
camera capture, background sync — is implemented for real against the actual
browser APIs, not a fake it that requires an app store to work properly.

## Receipt scanning

`apps/receipts/` (backend) + `/receipts/scan` (frontend). See
[`docs/modules/automation.md`](./automation.md) for the sibling detection
engine and [receipts' own module doc](./receipts.md) if present, or the
service layer docstrings in `apps/receipts/services.py`.

**The governing rule, enforced at both layers:** OCR proposes, a person
disposes. `Receipt.parsed_fields` — what the OCR engine read — never reaches
the ledger directly. Only `confirmed_*` fields, which the user has actively
looked at and could have changed, ever become a transaction. The frontend
mirrors this: every OCR-guessed field renders as a live, editable `<input>`,
never as read-only text presented as fact.

- **Camera** (`components/receipts/ReceiptCamera.tsx`): `getUserMedia` is the
  primary path — it keeps someone inside the app with a receipt-shaped guide
  frame, rather than bouncing them to the OS camera app. It is not the only
  path: permission denial, no camera API, or an insecure context all fall back
  identically to a native `<input type="file" accept="image/*"
  capture="environment">`, which still opens the device camera on essentially
  every mobile browser with zero JavaScript camera API required. Camera
  scanning degrades to file picking; it never simply breaks.
- **OCR** (`apps/receipts/providers.py`): `TesseractOCRProvider` reads locally
  — no network call, no per-image cost, no receipt photo ever leaves the
  server for OCR. `NullOCRProvider` is the safe fallback when Tesseract isn't
  installed, or to force manual entry. A cloud vendor is a third
  implementation of the same protocol away, exactly like the coach's LLM
  provider seam.
- **Field extraction** is deliberately simple pattern matching over a model: a
  receipt's layout is semi-structured enough that "the total is next to a
  total-shaped word" gets most of the way there, and a wrong heuristic is
  easier for a person to spot and correct than a wrong black-box prediction.

## Quick Add

`apps/finance/quick_add.py` (backend) + `/quick-add` (frontend). Two required
fields — amount and who it was to — because that is the ceiling of what
someone will reliably enter in a queue, on a phone, without giving up.
Everything else is inferred and **shown back, never silently applied**:

- **Account** defaults to the one most recently transacted on — derived fresh
  from history every time rather than a stored preference that can drift out
  of sync with what's actually in someone's hand.
- **Category** is inferred from the exact same learned store
  (`apps.intelligence.automation_services.merchant_stats`) the automation
  review queue reads, so Quick Add and the automation engine can never
  disagree about what a merchant "usually is."

### Idempotent replay — the property offline support depends on

Every Quick Add submission — including ones that succeed immediately online —
carries a client-generated idempotency key from the start. There is no
separate "offline mode" code path in the posting logic, only a difference in
whether the request is attempted now or queued for later.

This is safe only because the server genuinely guarantees it: a replayed
`idempotency_key` reuses the *same* journal entry (`post_journal_entry`'s
existing behaviour) **and** the same domain `Transaction` row. The second half
of that guarantee did not exist until this work: `record_expense`,
`record_income`, and `record_transfer` each unconditionally created a new
`Transaction` on every call, and since `Transaction.journal_entry` is a plain
`ForeignKey` rather than `OneToOneField`, nothing stopped two `Transaction`
rows from pointing at one replayed journal entry — the ledger stayed balanced,
but the transaction list would have shown a queued entry twice. Fixed with a
shared `_existing_transactions_for(entry)` guard in `apps/finance/services.py`,
applied to all three posting functions and tested directly against each
before anything offline was allowed to depend on it.

## Offline support & background sync

`src/lib/offlineQueue.ts` + `src/sw.ts`. Deliberately narrow: this queues
**one** kind of write — Quick Add — not a generic "retry any request"
mechanism. A financial ledger is the wrong place for a general-purpose
offline-write system: arbitrary requests have arbitrary side effects, and
replaying one blindly could double-apply something never meant to be
idempotent. Quick Add is safe to queue specifically because of the
server-side replay guarantee above; that's a property of the backend, not an
assumption made only on the client.

- **IndexedDB**, not localStorage: entries need to survive a page reload and a
  service-worker restart, and IndexedDB — unlike localStorage — is available
  to the service worker itself, which is what actually drains the queue.
- **Two independent triggers**: the `online` browser event (works everywhere)
  and the Background Sync API (`sync` event, tag `quick-add-queue`) where the
  browser implements it. Safari has no Background Sync support at all as of
  this writing, which is exactly why the `online` listener isn't just a
  fallback for the rare case — it's load-bearing for an entire browser.
- **Network failures are queued; validation failures are not.** A `TypeError`
  from `fetch()` itself (genuine unreachability) is queued and retried. A
  `400`/`401` wrapped in `ApiError` (bad category, expired session) surfaces
  immediately — replaying it would just fail again identically, and silently
  swallowing it into "saved offline" would hide a real mistake from the person
  who made it.

## Service worker caching strategy

No build-time precache manifest (the kind `vite-plugin-pwa` generates) — Vite
content-hashes every build asset, so a hand-written service worker hardcoding
filenames would need regenerating on every deploy. Runtime caching sidesteps
this: the cache fills itself from whatever the browser actually requests, and
a new deploy naturally produces new hashed URLs that simply aren't cached yet.

| Request | Strategy | Why |
|---|---|---|
| Navigation (HTML) | Network-first, falls back to cached shell / `offline.html` | Try for the latest build; still open with no connection at all |
| Same-origin static (JS/CSS/images) | Stale-while-revalidate | Instant repeat loads, self-healing on redeploy via content hashing |
| `/api/*` | Network-only, always | Financial data must never be served stale from a cache |

The service worker builds to a **stable, unhashed `/sw.js`** via a second
Rollup entry in `vite.config.ts` (`build.rollupOptions.input`), not a plugin —
browsers re-fetch exactly that literal URL to check for updates, so it can
never carry a content hash the way the app's own JS/CSS does.

## Push notifications

`apps/notifications/push.py` (backend) + `src/lib/pushSubscription.ts`
(frontend). Standards-based Web Push via VAPID (`py_vapid` + `pywebpush`), no
vendor SDK — any browser implementing the Push API receives without a
proprietary client library.

- **Optional infrastructure**, exactly like the coach's LLM providers: the
  product works fully with no VAPID key configured.
  `push.vapid_configured()` is the single gate every send checks; the
  frontend's `PushToggle` renders nothing at all when unconfigured rather than
  offering a control that can never work.
- **Wired at the single producer choke point.** `raise_notification` in
  `apps/notifications/services.py` is the one place every notification in the
  product gets created; push dispatch hooks in there via `transaction.
  on_commit`, so every one of the five-odd producers (budget alerts, bill
  reminders, goal milestones…) gets push delivery automatically rather than
  each needing to remember to wire it in — the identical pattern to the
  ledger dispatching analytics-cache invalidation from `post_journal_entry`.
- **Refreshing a deduped notification does not re-dispatch push.** A budget
  alert nudging from 90% to 105% is the same underlying alert; re-buzzing a
  phone on every refresh would be closer to spam than a notification.
- **A permanently expired subscription (410/404 from the push service) stops
  being retried**, marked rather than deleted so "why did push stop working on
  my phone" has an answer. A transient failure (503) does not expire it —
  that would silence a working device over a passing wobble.
- **Permission is only ever requested from the explicit Settings toggle**,
  never on page load. Prompting on load is how people learn to reflexively
  deny every permission a site ever asks for again, which would poison every
  future prompt this product might need.

### A bug found building this

`PushSubscription`'s unique constraint on `endpoint` was not scoped to live
rows — the identical soft-delete/unique-constraint trap caught on
`DebtProfile`'s rate history earlier in this project. Unsubscribing then
resubscribing the same browser would have collided with a constraint enforced
against a row the alive-only manager could no longer see, turning "turn
notifications back on" into a 500. Fixed by scoping the constraint to
`deleted_at__isnull=True`; a regression test pins the resubscribe path
directly.

## PWA manifest & install

`public/manifest.webmanifest` — standalone display, theme colour matching the
brand token, four `shortcuts` (Quick Add, Scan Receipt, Review, Dashboard).
Real generated icons at 192/512/512-maskable/apple-touch, not placeholders.

`src/lib/pwa.ts` captures the browser's `beforeinstallprompt` event so the app
can offer installation from its own UI at a sensible moment, rather than
whatever timing the browser would otherwise choose.

## Biometric login

Already fully implemented prior to this work — `apps/users/webauthn_models.py`,
`services/webauthn_service.py`, and the frontend `PasskeyButton`/
`PasskeyManager` components. Audited during this work and left untouched
rather than duplicated.

## Accessibility

Audited with `axe-core` against every new surface (`src/pages/mobile.a11y.
test.tsx`), plus explicit checks for the things automated auditing
structurally cannot see. That distinction turned out to matter: **axe passed
all five structural audits while both behavioural checks failed**, which is a
fair summary of what automated a11y tooling is and isn't for.

### Touch targets

`--lf-touch-target: 44px` is the product's own stated minimum. One gap found:
`<Switch>`'s visible track is a deliberate compact 44×26px, but its *tappable*
region — the wrapping `<label>` — was only as tall as the track. Fixed with a
`.lf-switch-label` rule giving the label a 44px minimum height without
changing how the control looks, scoped narrowly rather than touching the
shared layout utilities it composes with.

Camera controls meet the same bar: 72px shutter (the primary action gets
more, not less), 44px close and provider-switch controls.

### Focus management — what axe cannot check

The camera is a full-screen overlay, which makes it a modal in every sense
that matters, and it originally had none of the behaviour a modal needs. Two
real bugs, both caught by explicit tests rather than the automated audit:

- **Focus never moved into the camera.** A keyboard or screen-reader user was
  left with focus on whatever button opened it — a control now buried behind
  a full-screen overlay they had no way of knowing they were inside.
- **Escape did nothing.** No keyboard route out at all.

Both fixed by applying the same pattern `AppShell` already uses for its nav
drawer: focus moved to the close control on open (the one action guaranteed
to exist in both the live-camera and file-fallback views), Escape to leave,
focus handed back on close, background scroll locked.

### A pre-existing violation found in the design system

Running the audit harness across the shared primitives surfaced a **serious**
WCAG violation that predates this work: `<Meter>` rendered
`role="progressbar"` with no accessible name, so a screen reader announced
"40%" with no indication of 40% *of what*. Ten call sites across budget
consumption, plan limits, and health scores were affected.

Fixed at the primitive — a string `label` now supplies the name automatically
(covering most call sites without changes), with an explicit `aria-label`
prop for the two sites whose label is a ReactNode or absent. A string
`caption` becomes `aria-valuetext`, so a savings-rate meter announces "72% of
income kept" rather than a bare number. `src/ui/Meter.test.tsx` pins it.

### Contrast — measured, not eyeballed

The camera hint text sits on a scrim over **live video**, so its worst case is
the brightest thing the camera might be pointed at — which for a receipt
scanner is a white page under good light, i.e. the common case rather than an
edge case. axe cannot evaluate this at all: jsdom has no paint engine, so
there are no pixels to sample.

Computed directly instead. The original 45% scrim with 85%-opacity white text
measured **2.88:1**, below the 4.5:1 AA floor for normal text. Now a 70% scrim
with fully opaque text, measuring **8.52:1** against pure-white video —
chosen for headroom rather than to sit on the boundary. The close control got
the same treatment for the same reason. WCAG contrast is definitionally a
computed ratio, so the arithmetic is the authoritative check here, not a
stand-in for a visual one.

### What remains unaudited

This pass covered the new mobile surfaces and the shared primitives they
compose from. A full WCAG audit of every existing page in the product has
**not** been done — the `findViolations` helper in `src/test/a11y.ts` is
deliberately generic so that work can proceed page by page without new
infrastructure.

## Testing

- `tests/test_receipt_ocr.py`, `tests/test_receipt_services.py` — 24 + 18
  backend tests, including a real Tesseract pass against a rendered image.
- `tests/test_quick_add.py` — 21 tests, including direct idempotent-replay
  coverage at both the service and API layers.
- `tests/test_push_notifications.py` — 25 tests, including the 410-expiry and
  soft-delete-constraint regression.
- `tests/test_finance_engine.py` (additions) — 4 tests pinning that
  `record_expense`/`record_income`/`record_transfer` never create a second
  `Transaction` on replay.
- Frontend: `offlineQueue.test.ts` (real IndexedDB via `fake-indexeddb`),
  `pwa.test.ts`, `pushSubscription.test.ts`, `ReceiptCamera.test.tsx`,
  `QuickAddPage.test.tsx`, `ReceiptScanPage.test.tsx`, `PushToggle.test.tsx`,
  `OfflineIndicator.test.tsx`, `mobile.a11y.test.tsx`, `ui/Meter.test.tsx` —
  77 tests across the new mobile surfaces.

Two testing lessons worth keeping: jsdom implements neither the Service
Worker nor Push API at all, so both need explicit stubs rather than being
assumed present; and `getByLabelText` in this test environment matches on raw
`textContent`, which includes `aria-hidden` children (the required-field
asterisk) — a label reading "To" is literally text `"To*"` to the query, which
is a testing-tool limitation, not an accessibility defect in the markup
itself.

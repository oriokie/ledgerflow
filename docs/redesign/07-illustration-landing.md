# Illustration system & landing page

An addition to the Meridian system, not a departure from it. Everything here is
built from the same tokens as the application — no new palette, no new type
scale, no asset pipeline.

---

## 1. Why SVG rather than rendered 3D

The brief asks for a *premium 3D clay* language. What ships is **clay-inspired
vector**: soft radial shading, chunky rounded forms, a single top-left light
source and a grounded contact shadow — every pixel an SVG built from design
tokens.

That is a real trade and worth stating plainly. Rendered images would give
photoreal texture. Token-driven SVG gives three things they cannot:

| | Rendered PNG | Token SVG |
|---|---|---|
| Dark mode | A second asset, kept in sync by hand | Recolours itself |
| Contrast | Unverifiable | Gated by `verify_palette.py` like everything else |
| Weight | A network request per illustration | None — inlined, scales to any size |

For a product whose landing page argues that it loads fast and tells the truth
about its own numbers, that trade goes one way.

## 1a. What makes it read as clay

Five properties, applied to every form by the shared paints in `ClayScene`
rather than by each drawing:

1. **A single light from the upper left**, so highlights and shadows agree
   across illustrations drawn months apart.
2. **A warm highlight and a cool core shadow.** This is the one that matters:
   a two-stop ramp reads as plastic, and it is the third stop — the surface
   colour lifting the top edge, the text colour deepening the lower right —
   that reads as modelled material.
3. **A rim light** along the shaded edge. Without it a soft form reads as an
   out-of-focus blob rather than a solid.
4. **Ambient occlusion** where forms overlap, offset down-right because the
   light is upper-left. The offset carries the direction; the blur only softens.
5. **Generous radii and no hairlines.** Clay has no edges.

The build order for every motif is the same — occlusion, mass, lit face,
recess, rim — and following it is what makes two illustrations added a year
apart look like the same substance.

The whole set renders together at `/_ui`, which is the only way to judge
whether a new motif actually matches the others' lighting and weight. Two were
rebuilt after seeing them side by side there: at the neutral tone every form
shares a hue, so `no-data` and `offline` had merged into grey masses. Both now
carry a real value difference — light sheets against a dark tray, a solid bar
against hollow wells — rather than relying on hue alone.

## 2. Consistency is structural, not editorial

`ClayScene.tsx` owns the backdrop wash, the light source, the ground shadow and
the palette. A motif in `scenes.tsx` supplies **shapes and nothing else**.

The brief asks that illustrations stay consistent in "style, lighting,
perspective, and colour palette". Those four things are not left to whoever
draws the next one — a new illustration cannot drift, because it never gets to
decide any of them.

Two details that are easy to get wrong:

- **Gradient ids are per-instance** (`useId`). Two illustrations sharing an id
  makes the second silently adopt the first one's fill — a bug that only
  appears on a page with both.
- **Decorative by default.** Every scene is `aria-hidden` unless given a
  `title`. An illustration that repeats the heading beside it is noise.

## 3. Where illustrations go — and where they do not

Addressed by meaning (`name="offline"`), never by drawing. A name survives the
motif being redrawn; a drawing does not, and invites a second offline
illustration the day it changes.

| Size | Max width | Used on |
|---|---|---|
| `hero` | 560px | The landing hero, once |
| `panel` | 300px | Pages that own their whole surface — auth, 404, 500, maintenance, offline |
| `spot` | 132px | Inside the application: feature cards, page-level empty states |

**The workspace rule.** Dashboards, tables, reports and every financial screen
stay data-focused. `EmptyState` takes an opt-in `illustration` prop rather than
using one by default: an empty state inside a data screen keeps the quiet icon
plate, because artwork there competes with the numbers. The illustration is for
states that own their surface.

## 4. The landing page

Built from the application's own components and tokens — it is the product
speaking, not a marketing site that links to one. If it needed a separate design
language to look good, the application's would not be good enough.

Three deliberate refusals:

**No figures anywhere.** The interface preview is a token-built abstraction, not
a screenshot. A screenshot goes stale on the next screen change, cannot follow
the visitor's colour scheme, and necessarily contains either somebody's real
data or invented data dressed as real. The preview shows the *shape* of the
interface and contains no numbers to make a claim with. A test asserts it.

**Pricing is fetched, not written.** The page reads the same public
`/billing/plans/` endpoint the billing screen uses. Hardcoded prices could
advertise something a visitor is not actually charged; these cannot drift.

**No invented testimonials.** The section is designed and renders the moment
real, attributable quotes are added to `marketingCopy.ts`. It is empty on
purpose, and shows a visible placeholder saying so. Fabricated endorsements on a
page whose entire argument is trustworthiness would undermine the only thing it
is selling. **This is the one section that needs real content before launch.**

Every claim the page makes lives in `marketingCopy.ts` rather than scattered
through JSX, so a claim that stops being true is likelier to be caught.

## 5. Full-page states

`404`, `500`, `maintenance` and `offline` share one component. Four separate
ones would drift, and the drift always goes the same way — the rarely-seen page
ends up the one that looks unfinished.

Each says three things in order: what happened, whether it is the user's fault,
and what to do next.

- A wrong URL used to `Navigate` silently to the overview, which tells someone
  their link was fine and they simply ended up somewhere else. It now 404s.
- `AppErrorBoundary` wraps everything, because `RouteErrorBoundary` sits
  *inside* the shell — a crash in the shell, the router or a provider still
  produced a blank tab, the one outcome with no way out of it.

## 6. What the new audit coverage found

The route audit had never visited a signed-out page. The landing page, the auth
screens and the error states — the first thing anyone sees and the pages nobody
looks at twice — were entirely unmeasured. A `PUBLIC_ROUTES` pass in its own
no-login browser context fixed that, and immediately found:

- **A real layout defect in the new FAQ.** Chromium hides a closed `<details>`'
  content with `content-visibility`, not `display: none`, so each answer's box
  survived at its intrinsic size — the text vanished but a 60px gap did not.
  Every collapsed row had a hole in it.
- **Six touch targets on the sign-in flow at phone width**, all pre-existing.
  The password reveal toggle was 40px on its narrow axis — a control reached
  one-handed while typing a password. Fixed, along with the standalone "Forgot
  password?" link.

Three inline links inside sentences ("Create an account", "Log in") were left
at their natural 28px. They clear the 24px WCAG AA floor, and forcing a 44px box
around three words mid-sentence would break the sentence — the same trade taken
on the platform console's exception panel.

**`/` is audited twice** — signed out it is the landing page, signed in it is
the dashboard — and the public pass labels its findings `(public)/…` so the two
cannot merge. Reported under one label, a regression on either would look like a
regression on both.

---

## 7. Platform console — rail and sign out

### The console had no way out of it

There was no sign-out anywhere in the admin shell. The only exit was "Back to
LedgerFlow", which is not a sign out — and for a platform account it is a dead
end, because the customer app has no workspace to send an operator to and
bounces them straight back to `/admin`.

So **an operator who can suspend somebody's account could not end their own
session.** On a shared or unattended machine that is the whole problem. It now
sits with the operator's own identity in the rail rather than in the topbar:
signing out is about *who you are*, and the topbar is about where you are.

Hard navigation rather than a router push, matching the customer app — it drops
every in-memory query cache along with the session, so nothing the next operator
sees was fetched under the previous one's credentials.

### The rail

Eleven flat entries became four groups — **Overview, Revenue, Operations,
Governance** — on the same principle the customer rail was rebuilt on in Phase
5: a flat list is read, a structure is scanned, and an operator arriving
mid-incident is scanning. A group whose items are all hidden by capability
renders nothing at all, since a heading with nothing under it tells an operator
only that there is something they cannot see.

The active marker is a signal-amber bar, so "where am I" is answered in the one
hue this product reserves for the control room. The rail carries a faint wash of
that accent — enough that it does not read as a flat black column, not enough to
compete with the exception panel, which is the only thing on the dashboard
allowed to shout.

**Two token bypasses removed.** `rgb(255 255 255 / 8%)` hardcoded white for the
hover and active states. The rail is dark — but via `--lf-bg-inverse`, which
*inverts with the theme*, so the literal was a latent bug waiting for a light
operator theme as well as a bypass of the token system. Both are now
`color-mix` on `--lf-text-inverse`. `literal-rgb` 28 → 26.


---

## 8. Three illustration sets, switchable from the console

### Why a second set rather than a variant of the first

The three sets make three different arguments, which is why all three are worth
keeping rather than being one set with filters over it:

| Set | Draws | Says |
|---|---|---|
| **Clay** | the thing — a vault, a shield | this is solid |
| **Doodle** | somebody doing something with it | this is human |
| **Motion** | money going somewhere | here is where it went |

A product can want to feel substantial, or human, or like it is tracking
something — and those are different weeks.

All three implement the same registry, and the type system enforces it:
`Record<IllustrationName, …>` means a name present in one set and missing from
the other will not compile. Without that, switching the style could blank a
surface — and it would be a surface nobody thought to check, because the
setting is platform-wide.

### What makes the doodle set read as hand-drawn

Four things, none of them a texture filter:

1. **Open strokes, not filled masses** — a consistent line weight with round
   caps, and fills that sit *behind* the line the way marker sits behind ink.
2. **The fill is offset from the line.** Colour that does not quite register
   with its outline is the single most legible signal of a human hand; perfect
   registration reads as vector art immediately.
3. **Nothing is quite straight or level** — every element carries a small
   rotation, and no two are the same.
4. **Visible construction marks** — a stray tick, motion lines, an underline.

**The figures are faceless on purpose.** Drawing a face means deciding whose
face, and on a product used across a hundred countries the honest answer is
that we do not know. Posture carries the meaning anyway: what someone is
*doing* is the subject.

A note on a fix that was tried and reverted: `vector-effect: non-scaling-stroke`
looks right for line art until you work out which direction it scales. It holds
the stroke at its authored width in *screen* pixels, so the 62px spot
illustration would have carried the heaviest line in the product. Line art
should scale its strokes with the drawing.

### The third set: motion

The clay set draws the thing. The doodle set draws somebody doing something.
The motion set draws **money going somewhere** — and that is the closest of the
three to what the product is actually about. A ledger is a record of movement,
and every screen here answers some version of "where did it go?".

Every motif carries a **trail**: a dashed path connecting where money was to
where it went, with a note or a coin travelling on it. The trail is the
subject; the person is the reason it matters. A motif with a trail and nothing
moving on it is a person looking at a shape, and the test suite fails on one.

### Motion, and the reduced-motion contract

This is the part that had to be got right rather than got working.

`base.css` neutralises motion globally by forcing `animation-duration` to
0.01ms and `animation-iteration-count` to 1 — which lands every animation on
its **end** state. A "money flies away" animation written as a one-way trip
would therefore leave a reduced-motion user with an empty frame: every note
parked at its off-screen destination, the illustration silently gutted for
exactly the people least able to tell us.

So every keyframe in the set is **cyclical, with 0% and 100% identical**. The
end state and the resting composition are the same drawing, and the
illustration is complete either way. Verified rather than asserted: with
reduced motion emulated, all fourteen motifs render the same 229 shapes and
every animated node reports `animation-name: none`.

The explicit `animation: none` block is still needed on top of that, because an
infinite loop with a near-zero duration finishes instantly and then keeps
scheduling work every frame forever.

**Inside the application the set does not animate at all.** Spot illustrations
sit next to numbers someone is reading, and peripheral movement beside a
balance is exactly what the brief rules out. The drawing keeps its trail; it
just holds still. The single exception is the console's own style picker, which
opts in through an explicit `animate` prop — an operator choosing an animated
set has to be able to see it move, or they are choosing blind.

### One SVG trap worth recording

A CSS `transform` from an animation **replaces** the `transform` presentation
attribute rather than composing with it. The first version of this set put both
on the same `<g>`, and every note in all fourteen motifs snapped to the SVG
origin — the money piled up invisibly in the top-left corner, which at a glance
looked exactly like an illustration that simply had no money in it.

The fix is to position on an outer group and animate an inner one. There is now
a test asserting that no element carrying a motion class also carries a
`transform` attribute; it was confirmed to fail when the bug is reintroduced.

### The setting

`appearance.illustration_style` in the platform console, under a new
**Appearance** group. Three things make it safe:

- **A closed set, enforced in two places.** `SettingSpec` gained a `choices`
  field; the store raises on a value outside it and the API turns that into a
  400. A closed-set setting stored with a bad value errors *nowhere* — the only
  symptom is artwork that quietly stops rendering.
- **A choice control, not a text box.** The console renders `choices` as a
  segmented control with **both sets previewed side by side**, because a visual
  setting whose effect you cannot see until you save it and go looking is one
  people change once and then leave alone.
- **A public read endpoint.** `/platform/appearance/` is unauthenticated and
  returns exactly one string, because the landing page and the login form need
  the style before anyone has signed in. Deliberately its own endpoint rather
  than an exemption on the console's settings API — that one reports which
  secrets are configured, and an allowlist of one is easier to keep safe than a
  filter over everything.

The provider sits outside the router and outside auth, and falls back to `clay`
while the request is in flight and if it fails outright. An unreachable settings
endpoint must degrade to *an* illustration set, never to blank surfaces — which
is also why the hook does not retry.

## 9. Testimonials

The section is populated, and **every quote in it is written copy, not a
customer endorsement.**

The mechanism is a `sample: true` flag on the data. While any quote carries it,
the page shows a notice saying so and tags each card `Example`. Replace the
quotes with attributable ones, drop the flag, and the notice disappears on its
own — it is tied to the data rather than written into the page, so it cannot be
left behind.

Attribution is a **role**, never a name: "Freelance designer, two currencies".
A fabricated full name is the part that turns sample copy into a fake
endorsement, and the type has no `name` field to put one in. A test asserts
that.

The copy deliberately echoes things the product actually does — the cash-flow
view admitting what it is not counting, the audit trail, the debt planner
showing its arithmetic — so it is a usable starting point rather than generic
praise. **It still needs replacing with real quotes before launch.**

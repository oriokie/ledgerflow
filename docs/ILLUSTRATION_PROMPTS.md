# Illustration prompts

Prompts for generating LedgerFlow's illustration set with ChatGPT (GPT-Image /
DALL·E). One per screen, plus a shared style block that has to be pasted at the
top of **every** request.

## How to use this

1. Paste **§1 House style** verbatim.
2. Paste **one** scene prompt from §3 beneath it.
3. Generate 4 variations, keep the one whose *silhouette* reads at 120px — these
   render as small as 96px in empty states, and a scene that only works large is
   the wrong scene.

**Two things to know before you start.**

The app's existing illustrations are hand-built **SVG components**
(`frontend/app/src/ui/illustration/`), addressed by meaning — `secure`,
`no-data`, `growth` — never by what they depict, so a redraw doesn't break any
caller. ChatGPT returns **raster PNGs**. Those are usable directly as assets,
but they will not inherit the theme the way the SVG set does: the current
illustrations recolour themselves from CSS tokens in light and dark mode, and a
PNG cannot. Either generate a light and a dark variant of each, or treat the
generated art as a reference for redrawing in SVG. §4 covers this.

Second: the product already has **three complete sets** — `clay` (the object
itself, dimensional), `doodle` (a person doing something, line art), and
`motion`. The platform picks one via `appearance.illustration_style`. If you are
adding a fourth, generate all fourteen names or the switch will land on a
missing scene. If you are replacing one, match its register.

---

## 1. House style — paste this first, every time

```
You are producing one illustration from a coherent set for a personal-finance
web app called LedgerFlow. The set must look like one hand made all of it.

STYLE
- Flat vector illustration. Clean confident line work, uniform stroke weight
  roughly 2.5px at a 200×170 canvas. No gradients on the linework, no drop
  shadows, no 3D, no glassmorphism, no photographic texture.
- One soft translucent colour wash sitting slightly offset behind the linework,
  like a printing misregistration. This is the only fill. Everything else is
  line.
- Generous negative space. The subject occupies the middle 70% of the frame.
- Rounded line caps and joins. Nothing sharp or technical.

PALETTE — use these exact values and nothing else
- Line and text:      #1a1917  (warm graphite, never pure black)
- Primary wash:       #ddf0e6  (pale jade)
- Accent, sparingly:  #0d7350  (jade — one element per scene at most)
- Secondary wash:     #fbefd6  (pale ochre) for warmth where a second is needed
- Background:         transparent

PEOPLE
- Where a person appears they are drawn simply: a circle head, a single-stroke
  body, gestural limbs. No facial features beyond, at most, a suggestion of
  closed eyes or a small smile. No hair detail, no clothing detail.
- Deliberately ambiguous in age, gender and ethnicity. This product is used
  across East Africa, Europe and North America and no illustration should read
  as being about one of them.

COMPOSITION
- Square-ish canvas, roughly 200×170 proportion, transparent background.
- A single light ground line under the subject where one is needed for balance.
- The silhouette must read at 120px. Test it small before you commit.

TONE — this is a finance product, and the rules below are not decorative
- Calm and matter-of-fact. Never celebratory, never anxious.
- No money symbols raining down, no piggy banks, no rocket ships, no
  briefcase-and-tie businessmen, no upward arrows implying guaranteed growth.
- No specific numbers, no currency symbols, no readable text of any kind. The
  app's own figures go beside the illustration; art that carries a number
  competes with them and is wrong the moment the number changes.
- Nothing that implies a promise about money. This product's whole discipline
  is not overstating what it knows.
```

---

## 2. What each scene has to survive

Every prompt below states its **job**, because the illustration is doing
different work in each place:

| Job | Where it appears | What it must not do |
|---|---|---|
| **Empty state** | Screen with no data yet | Read as an error, or as failure |
| **Guidance** | Beside instructions | Compete with the text |
| **Reassurance** | Auth, security | Look corporate or cold |
| **Absence** | Nothing due, nothing found | Look like something broke |
| **Error** | 404, offline, maintenance | Blame the user, or alarm |

---

## 3. Per-page prompts

### Login / Register / Reset password — `secure`

```
A person sitting cross-legged and relaxed, calm and unhurried, beside a large
simple shield shape with a soft check mark inside it. The shield is drawn in
line only, with the pale jade wash offset behind it. The person's posture is
settled — this is somebody who is not worried.

Job: the first screen anyone sees, and its entire task is to feel safe to type
a password into. Warmth, not security theatre. No padlocks, no vaults, no
fingerprints, no shields with spikes.
```

### Workspace picker — `welcome`

```
A person standing at a simple fork in a path, hand raised to shade their eyes,
looking toward two soft rounded shapes in the middle distance. Unhurried,
curious. The pale jade wash sits behind the shapes.

Job: choosing which workspace to enter, or creating a first one. It is a
beginning, not a decision under pressure. No signposts with text, no maps.
```

### Dashboard / Overview — `insight`

```
A person seated at a low table with a single large sheet of paper, one hand
resting on it, head slightly tilted in thought. Two or three simple bar shapes
on the sheet, drawn in line, with the jade wash behind one of them.

Job: the daily landing screen. The feeling is "here is your position, calmly
laid out" — reading, not reacting. The bars must be flat and unremarkable, never
climbing dramatically to the right.
```

### Transactions — `no-data`

```
An open, empty shallow tray or drawer, drawn in clean line, with a person
standing beside it holding a single sheet of paper about to file it. The tray is
plainly empty — not broken, not dusty.

Job: the ledger before anything has been recorded, and the state after a filter
matches nothing. It has to say "nothing here yet", never "something went wrong".
No cobwebs, no sad faces, no crumpled paper.
```

### Accounts — `vault`

```
A person standing beside a large simple rounded rectangle with a circular dial
on its face — a strongbox reduced to its essentials. One hand rests on it
casually, the posture proud rather than protective.

Job: the accounts a household holds. This is about *having built something*,
not about guarding it against threat. No chains, no locks with keyholes, no
bank columns.
```

### Income — `growth`

```
A person standing beside three simple vertical bars of increasing height,
gesturing toward them with an open hand, explaining rather than celebrating. The
bars are slightly irregular, hand-drawn, one carrying the jade wash.

Job: money coming in and how steady it is. Steady, not soaring — a good number
of this product's users have irregular income and a triumphant chart would read
as a rebuke.
```

### Budgets — `compass`

```
A person holding a large simple circular dial with a single needle, looking at
it thoughtfully. The circle is clean line work with the pale jade wash offset
behind it.

Job: setting limits and keeping to them. Orientation, not restriction. No
scales, no scissors cutting cards, no belt-tightening.
```

### Goals — `success`

```
A person reaching up to place a final small circular shape on top of a short
stack of them. The stack is modest — four or five — and the person is on the
ground, not climbing. Jade wash behind the topmost shape.

Job: saving toward something named. Nearly-there rather than triumphant. No
trophies, no summits, no finish lines, no confetti.
```

### Bills — `envelope`

```
A person holding a single open envelope with a simple sheet emerging from it,
reading it calmly. One further envelope rests on a surface beside them.

Job: what is due and when. Ordinary admin handled in good time. Never a pile of
unopened mail, never red stamps, never a hand over the face.
```

### Recurring / Subscriptions — `cycle`

```
A person standing beside a large open circular arrow — a loop drawn as one
continuous confident line — with two or three small evenly spaced marks around
its circumference. The jade wash sits behind the loop's lower arc.

Job: charges that repeat whether or not you think about them. Rhythm and
regularity, not a trap. No hamster wheels, no drains, no leaking taps.
```

### Debt — `path`

```
A person walking along a simple line that descends gently from left to right,
carrying a modest bundle. The line ends at a small flat platform. Steady pace,
upright posture.

Job: what is owed and the route out of it. A descending line here is *good* —
the balance falling. Dignity above all: no chains, no boulders, no drowning, no
weight crushing anyone. People in debt use this screen and it must not shame
them.
```

### Receivables / Owed to you — `waiting`

```
Two simple figures at a slight distance from each other, one holding out an
open hand, the other mid-step toward them holding a small rounded shape. The
gesture is friendly and unresolved — mid-exchange, not confrontation.

Job: money other people owe you, most of it lent to friends and family.
Absolutely not a debt collector: no pointing, no crossed arms, no ledgers being
brandished. The relationship survives the transaction.
```

### Assets — `holdings`

```
A person standing beside three simple objects of different sizes on a low
plinth — a house shape, a rounded vehicle shape, and a small block — all drawn
in flat line. One hand rests on the largest. Jade wash behind the house shape.

Job: the things a household owns but does not transact through. Ownership,
plainly stated. Not wealth display: no mansions, no sports cars, no gold bars,
no jewellery sparkles.
```

### Investments — `portfolio`

```
A person seated beside a simple circle divided into three or four unequal
segments, one segment lifted slightly away from the rest. They are looking at
it, considering. Jade wash behind the lifted segment.

Job: holdings and how they are spread. Composition, not performance. No candle
charts, no bulls, no bears, no tickers, no arrows.
```

### Cash flow / Projections — `horizon`

```
A person standing at the left of the frame looking toward a soft line that
travels to the right and then dissolves into a series of increasingly faint
dashes. The solid portion carries the jade wash; the dashed portion carries
none.

Job: what is known versus what is projected — the single most important idea in
this product. The illustration must make the fading legible: the further right,
the less certain. Never a confident straight line to a bright destination.
```

### Reports / Analytics — `search`

```
A person holding a simple round lens over a sheet marked with three or four
plain horizontal lines, leaning in slightly. The lens is a clean circle with a
short handle. Jade wash behind the sheet.

Job: looking closely at what already happened. Examination, not surveillance.
No magnifying glass over a dollar sign, no detective imagery.
```

### Coach / Insights — `conversation`

```
Two simple figures seated at a slight angle to each other, one gesturing gently
toward a small shared sheet between them. Equal height, equal posture — neither
is instructing the other.

Job: advice the product offers. Advisory, never authoritative. The equal posture
is the whole point: this product states what it found and does not tell people
what to do. No lecterns, no raised fingers, no robots.
```

### Household / Members — `together`

```
Three simple figures standing in a loose group, shoulders overlapping slightly,
one with an arm raised in a small wave. Different heights. A single ground line
beneath all three.

Job: shared workspaces — partners, families. Warm and informal. Not a corporate
org chart, not a family posed for a portrait, no hierarchy in the arrangement.
```

### Settings — `adjust`

```
A person reaching up to move a small marker along a simple horizontal track,
one of three parallel tracks stacked vertically. Unhurried, precise.

Job: preferences and workspace configuration. Small deliberate adjustments. No
gears, no cogs, no wrenches — mechanical metaphors make settings feel like
repair.
```

### Notifications — `signal`

```
A person looking up at a single small rounded shape floating just above and
ahead of them, with two short curved lines suggesting it has just arrived.
Calm attention, not alarm.

Job: things worth knowing about. Never a bell mid-ring, never an exclamation
mark, never red.
```

### Billing / Plan — `steps`

```
A person standing on the lower of two simple broad steps, looking up at the
higher one, one foot raised. The upper step carries the jade wash.

Job: the plan you are on and the one above it. An open door, not a locked gate.
No padlocks, no "premium" crowns, no velvet ropes, no price tags.
```

### 404 / Not found — `lost`

```
A person standing beside a simple signpost with two blank arms pointing in
different directions, one hand on their chin. Mildly puzzled, entirely
unbothered.

Job: a page that does not exist. Light and slightly wry — the tone of a small
shrug. Never distressed, never apologetic, never a broken robot.
```

### Offline — `offline`

```
A person seated calmly beside a simple rounded shape with a short gap broken
into one edge, a couple of small dots trailing away from the gap. Patient
posture, waiting rather than panicking.

Job: no connection. This app queues work offline and syncs later, so the
illustration should feel like a pause, not a failure. No lightning bolts, no
crossed-out symbols, no red.
```

### Maintenance — `maintenance`

```
A person seated on a low stool beside a simple rounded shape, tightening one
small detail on it with an unhurried gesture. A tidy workspace, nothing
scattered.

Job: planned downtime. Competent people doing expected work. Never smoke, never
sparks, never a hard hat with a caution stripe.
```

### Error / Something broke — `broken`

```
A simple rounded shape with one clean crack across it, and a person beside it
already reaching out to mend it — mid-repair, not mid-despair.

Job: an unexpected failure. The reaching hand is what stops this reading as
blame or hopelessness. No shattered glass, no error triangles, no red, no
figure with head in hands.
```

---

## 4. Getting the output into the app

**Naming.** Save each as its meaning, not its subject: `secure.png`, not
`shield-with-person.png`. The whole illustration system is addressed by meaning
so a redraw never breaks a caller, and file names that describe the drawing
undo that the first time somebody changes the drawing.

**Themes.** The SVG sets recolour from CSS tokens, so they follow light and dark
automatically. PNGs cannot. Generate each scene twice — once with `#1a1917`
linework for light mode, once with `#f2f1ed` linework for dark — and swap on
`prefers-color-scheme`. If that doubles the work past what it is worth, use the
generated art as a reference and redraw in SVG instead; the existing scenes in
`doodleScenes.tsx` show the shape that takes.

**Size.** Export at 3× the largest display size. `hero` renders around 320px on
the landing page, so 960px is the floor.

**The set has to match.** Generate all of them in one session with the same
style block. Coming back a week later produces a different hand, and the
mismatch is more visible than any individual scene's quality.

**Check the small size before accepting anything.** These render at 96–120px in
empty states. Most illustrations that look excellent at full size become an
unreadable smudge there, and that is the size most users actually see.

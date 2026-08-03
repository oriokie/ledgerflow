#!/usr/bin/env python3
"""Walk every route in a real browser and assert the things screenshots miss.

Why this exists
---------------
The UX audit that produced `docs/redesign/` found its most concrete defects by
measuring the DOM, not by looking: a 130px text overlap on Accounts, eleven
24px-wide nav links in the admin console, eleven distinct font sizes against a
seven-step scale. It also produced one *false* finding by trusting screenshots
from an instrumented browser — see `docs/redesign/01-audit.md` section 4. Both
outcomes point the same way: measure the DOM, in a real browser, repeatably.

Checks, per route per viewport:

* **overlap**       — two visible text nodes occupying the same pixels
* **tiny-text**     — visible text below 11px
* **target-aa**     — interactive target below 24px (WCAG 2.5.8, AA)
* **target-project**— interactive target below `--lf-touch-target` (44px), mobile
* **h-overflow**    — the page scrolls sideways
* **type-scale**    — more than 7 distinct computed font sizes (tokens.css
                      defines exactly 7)
* **heading-outline** — no `h1`, or a skipped level

Like `check_style_tokens.py` this is a **ratchet**: existing violations are the
ceiling, and CI fails when the count goes up. A wall would just get switched
off on day one.

    python scripts/audit_routes.py                 # check against baseline
    python scripts/audit_routes.py --list          # every violation, with detail
    python scripts/audit_routes.py --update        # re-baseline (deliberate)
    python scripts/audit_routes.py --routes /debt,/goals

Requires the dev server (`make run` + `npm --prefix frontend/app run dev`) and
a seeded workspace (`python manage.py seed_tenant_demo`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    print("playwright is not installed.  pip install playwright && playwright install chromium", file=sys.stderr)
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "route_audit_baseline.json"
BASE_URL = "http://localhost:5173"

TENANT_ROUTES = [
    "/", "/transactions", "/accounts", "/categories", "/budgets", "/goals",
    "/bills", "/recurring", "/income", "/investments", "/debt", "/coach", "/cashflow",
    "/analytics", "/reports", "/insights", "/automation", "/members",
    "/settings", "/billing", "/notifications",
    # Phase 5 IA. Only the hub *chrome* is new; the tab bodies are the same
    # components already audited at their legacy paths. Auditing
    # `/plan?tab=bills` as well as `/bills` counts one control twice, which
    # inflates the ratchet without describing a defect and would leave room for
    # a real regression to hide under the slack. `/activity` is omitted for the
    # same reason — it renders exactly what `/transactions` renders.
    "/plan",
]

#: Routes whose content the Phase 5 flag decides, audited in their own pass with
#: the flag seeded before the app boots. An IA behind a flag that nothing checks
#: is an IA nobody has checked.
FLAGGED_ROUTES = ["/insights"]

#: Routes a signed-out visitor sees. Audited in a context with no login at all,
#: which is the only way to reach them — `/` is the dashboard once you are in.
#:
#: None of these had ever been measured. The landing page and the auth screens
#: are the first thing anyone sees, and the error states are the ones nobody
#: looks at twice, which is exactly the combination that rots unwatched.
PUBLIC_ROUTES = [
    "/",
    "/login",
    "/register",
    "/forgot-password",
    "/maintenance",
    "/offline",
    "/this-route-does-not-exist",
]
NAV_V2_INIT = "localStorage.setItem('lf-flag-nav-v2','on')"
ADMIN_ROUTES = [
    "/admin", "/admin/tenants", "/admin/billing", "/admin/invoices",
    "/admin/dunning", "/admin/coupons", "/admin/plans", "/admin/analytics", "/admin/health",
    "/admin/audit", "/admin/staff", "/admin/settings",
]

VIEWPORTS = {"mobile": (375, 812), "desktop": (1280, 900)}

TENANT_USER = ("amina@example.test", "PlatformAdmin!2026")
ADMIN_USER = ("admin@ledgerflow.test", "PlatformAdmin!2026")

#: tokens.css defines eight steps. Anything beyond that is an ad-hoc px value
#: or a relative size that has landed between steps.
#:
#: Was seven. The scale gained `2xl` (2.0736rem) when the xl->2xl gap was
#: closed — it had been a 1.44 jump in an otherwise uniform 1.2 scale, and
#: three stylesheets had already worked around it by reaching for a
#: `--lf-text-3xl` that did not exist.
MAX_FONT_SIZES = 8
MIN_FONT_PX = 11.0
TARGET_AA = 24.0
TARGET_PROJECT = 44.0

PROBE = """
() => {
  /* An element scrolled out of a clipping ancestor still reports a
     `getBoundingClientRect()` at its laid-out position, not its painted one.
     Without this check, every row below the fold of a scrollable table
     "overlaps" whatever is drawn beneath the container — which reported five
     phantom collisions on the transactions ledger alone, and would have sent
     someone hunting a layout bug that does not exist. */
  /* `className` on an SVG element is an SVGAnimatedString, not a string, so
     `e.className || e.tagName` stringified to "[object SVGAnimatedString]" and
     every finding inside a chart was unidentifiable — which is exactly where
     overlaps happen, because chart libraries lay out their own ticks. */
  const label = (e) => {
    const cls = typeof e.className === "string" ? e.className : e.className?.baseVal;
    const text = (e.textContent || "").trim().slice(0, 18);
    if (cls) return cls;
    return text ? `${e.tagName}("${text}")` : e.tagName;
  };

  const clipped = (e) => {
    const r = e.getBoundingClientRect();
    for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (!/auto|scroll|hidden/.test(s.overflow + s.overflowX + s.overflowY)) continue;
      const c = p.getBoundingClientRect();
      if (r.bottom <= c.top + 1 || r.top >= c.bottom - 1) return true;
      if (r.right <= c.left + 1 || r.left >= c.right - 1) return true;
    }
    return false;
  };
  const vis = (e) => {
    const r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const s = getComputedStyle(e);
    if (s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) <= 0.01) return false;
    return !clipped(e);
  };
  const root = document.querySelector('main') || document.body;
  const leaves = [...root.querySelectorAll('*')]
    .filter((e) => e.childElementCount === 0 && e.textContent.trim() && vis(e));

  // --- overlap: two visible text nodes sharing pixels
  const overlaps = [];
  for (let i = 0; i < leaves.length; i++) {
    for (let j = i + 1; j < leaves.length; j++) {
      const a = leaves[i].getBoundingClientRect();
      const b = leaves[j].getBoundingClientRect();
      const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (ox > 2 && oy > 2) {
        overlaps.push(`${label(leaves[i])} | ${label(leaves[j])}`);
      }
    }
  }

  // --- tiny text
  const tiny = leaves
    .map((e) => ({ px: parseFloat(getComputedStyle(e).fontSize), cls: label(e),
                   text: e.textContent.trim().slice(0, 24) }))
    .filter((o) => o.px && o.px < MIN_FONT_PX_);

  // --- interactive targets
  const targets = [...root.querySelectorAll('a,button,input,select,textarea,[role=button],[role=tab],[role=link]')]
    .filter(vis)
    .map((e) => {
      const r = e.getBoundingClientRect();
      return { w: r.width, h: r.height, cls: label(e),
               text: (e.textContent || '').trim().slice(0, 24) };
    });

  // --- type scale
  //
  // Rounded to 0.1px before de-duplicating. The ledger-cents rule derives its
  // size from the parent (one exact step down), and floating point lands it a
  // couple of thousandths off the token it matches: 11.1062 against 11.104.
  // Counting those as two sizes is the check inventing a design inconsistency
  // that no eye can see and no change could fix.
  const sizes = [...new Set(leaves.map((e) => Math.round(parseFloat(getComputedStyle(e).fontSize) * 10) / 10))]
    .sort((a, b) => a - b)
    .map((n) => `${n}px`);

  // --- heading outline
  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]
    .filter(vis)
    .map((h) => ({ level: Number(h.tagName[1]), text: h.textContent.trim().slice(0, 30) }));
  const outline = [];
  if (headings.length === 0) outline.push('no headings');
  else if (headings[0].level !== 1) outline.push(`starts at h${headings[0].level}`);
  for (let i = 1; i < headings.length; i++) {
    if (headings[i].level - headings[i - 1].level > 1) {
      outline.push(`h${headings[i - 1].level} -> h${headings[i].level} (${headings[i].text})`);
    }
  }

  return {
    overlaps: [...new Set(overlaps)],
    tiny,
    targets,
    sizes,
    outline,
    hOverflow: document.documentElement.scrollWidth > window.innerWidth + 1
      ? document.documentElement.scrollWidth : 0,
    headingCount: headings.length,
  };
}
""".replace("MIN_FONT_PX_", str(MIN_FONT_PX))


#: The visual fingerprint of a route: every distinct rendered value, not every
#: pixel. See `snapshot()` for why this replaces screenshot diffing.
FINGERPRINT = """
() => {
  const vis = (e) => {
    const r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const s = getComputedStyle(e);
    return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.01;
  };
  const els = [...(document.querySelector('main') || document.body).querySelectorAll('*')].filter(vis);
  const bag = { color: new Set(), background: new Set(), border: new Set(),
                fontSize: new Set(), fontFamily: new Set(), fontWeight: new Set(),
                radius: new Set(), shadow: new Set() };
  const TRANSPARENT = 'rgba(0, 0, 0, 0)';
  for (const e of els) {
    const s = getComputedStyle(e);
    if (e.textContent.trim() && e.childElementCount === 0) {
      bag.color.add(s.color);
      bag.fontSize.add(s.fontSize);
      bag.fontFamily.add(s.fontFamily.split(',')[0].replace(/["']/g, ''));
      bag.fontWeight.add(s.fontWeight);
    }
    if (s.backgroundColor !== TRANSPARENT) bag.background.add(s.backgroundColor);
    if (s.borderTopWidth !== '0px' && s.borderTopColor !== TRANSPARENT) bag.border.add(s.borderTopColor);
    if (s.borderRadius !== '0px') bag.radius.add(s.borderRadius);
    if (s.boxShadow !== 'none') bag.shadow.add(s.boxShadow);
  }
  const out = {};
  for (const [k, v] of Object.entries(bag)) out[k] = [...v].sort();
  return out;
}
"""


class Finding:
    def __init__(self, route: str, viewport: str, kind: str, detail: str) -> None:
        self.route, self.viewport, self.kind, self.detail = route, viewport, kind, detail

    def __str__(self) -> str:
        return f"{self.route:<22}{self.viewport:<9}[{self.kind}]  {self.detail}"


def login(page, email: str, password: str) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
    page.fill("input[type=email]", email)
    page.fill("input[type=password]", password)
    page.click("button[type=submit]")
    page.wait_for_timeout(2500)


def settle(page, tries: int = 12, interval: int = 250) -> None:
    """Wait for the DOM to stop changing shape.

    A fixed sleep is not enough. Routes fetch, render skeletons, then swap in
    content, and sampling mid-swap counts a different number of interactive
    elements each run — which made an early version of this script report 181
    small targets on one pass and 197 on the next. A ratchet that moves on its
    own is noise, so the probe waits for two consecutive identical samples
    rather than for a guessed duration.
    """
    previous = None
    for _ in range(tries):
        sample = page.evaluate(
            """() => ({
                 controls: document.querySelectorAll('a,button,input,select,textarea,[role=button]').length,
                 skeletons: document.querySelectorAll('[class*=skeleton]').length,
                 chars: document.body.innerText.length,
               })"""
        )
        stable = sample == previous
        if stable and sample["skeletons"] == 0:
            return
        previous = sample
        page.wait_for_timeout(interval)


def audit_route(page, route: str, viewport: str) -> list[Finding]:
    page.goto(f"{BASE_URL}{route}", wait_until="networkidle")
    settle(page)
    r = page.evaluate(PROBE)
    found: list[Finding] = []

    for pair in r["overlaps"]:
        found.append(Finding(route, viewport, "overlap", pair))
    for t in r["tiny"]:
        found.append(Finding(route, viewport, "tiny-text", f'{t["px"]:.2f}px  "{t["text"]}"  .{t["cls"]}'))
    if r["hOverflow"]:
        found.append(Finding(route, viewport, "h-overflow", f'scrollWidth {r["hOverflow"]}'))
    if len(r["sizes"]) > MAX_FONT_SIZES:
        found.append(Finding(route, viewport, "type-scale", f'{len(r["sizes"])} sizes: {", ".join(r["sizes"])}'))
    for issue in r["outline"]:
        found.append(Finding(route, viewport, "heading-outline", issue))

    for t in r["targets"]:
        smallest = min(t["w"], t["h"])
        label = t["text"] or f'.{t["cls"]}'
        if smallest < TARGET_AA:
            found.append(Finding(route, viewport, "target-aa", f'{t["w"]:.0f}x{t["h"]:.0f}  {label}'))
        elif viewport == "mobile" and smallest < TARGET_PROJECT:
            found.append(Finding(route, viewport, "target-project", f'{t["w"]:.0f}x{t["h"]:.0f}  {label}'))
    return found


def run(routes_tenant: list[str], routes_admin: list[str], viewports: dict) -> list[Finding]:
    findings: list[Finding] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, (w, h) in viewports.items():
            for user, routes in ((TENANT_USER, routes_tenant), (ADMIN_USER, routes_admin)):
                if not routes:
                    continue
                context = browser.new_context(viewport={"width": w, "height": h})
                page = context.new_page()
                login(page, *user)
                for route in routes:
                    # One retry: a `networkidle` wait occasionally loses a race
                    # with a slow chunk, and a flaky probe that lands in the
                    # baseline is a hole the ratchet can never close.
                    for attempt in (1, 2):
                        try:
                            findings.extend(audit_route(page, route, name))
                            break
                        except Exception as exc:  # noqa: BLE001 — one bad route must not end the run
                            if attempt == 2:
                                findings.append(Finding(route, name, "probe-error", str(exc)[:90]))
                context.close()

            # Signed-out pass. No login, so it must come from its own context.
            if routes_tenant:
                context = browser.new_context(viewport={"width": w, "height": h})
                page = context.new_page()
                for route in PUBLIC_ROUTES:
                    for attempt in (1, 2):
                        try:
                            # `/` is two different pages depending on whether
                            # anyone is signed in — the landing page and the
                            # dashboard. Reported under one label their findings
                            # merge, and a regression on either looks like a
                            # regression on both.
                            found = audit_route(page, route, name)
                            findings.extend(
                                [
                                    Finding(f"(public){f.route}", f.viewport, f.kind, f.detail)
                                    for f in found
                                ]
                            )
                            break
                        except Exception as exc:  # noqa: BLE001
                            if attempt == 2:
                                findings.append(Finding(route, name, "probe-error", str(exc)[:90]))
                context.close()

            # Second tenant pass with the Phase 5 flag on, for the routes whose
            # content the flag decides.
            if routes_tenant:
                context = browser.new_context(viewport={"width": w, "height": h})
                context.add_init_script(NAV_V2_INIT)
                page = context.new_page()
                login(page, *TENANT_USER)
                for route in FLAGGED_ROUTES:
                    for attempt in (1, 2):
                        try:
                            findings.extend(audit_route(page, f"{route}", name))
                            break
                        except Exception as exc:  # noqa: BLE001
                            if attempt == 2:
                                findings.append(Finding(route, name, "probe-error", str(exc)[:90]))
                context.close()
        browser.close()
    return findings


def snapshot(routes_tenant: list[str], routes_admin: list[str], viewports: dict, out_path: Path) -> None:
    """Record each route's *visual fingerprint* — every distinct rendered
    colour, type size, family, weight, radius and shadow.

    This is deliberately not a screenshot diff. Pixel snapshots taken on macOS
    never match ones rendered on CI's Linux — different font rasterisation and
    subpixel antialiasing guarantee a diff on every run — so they would have to
    be generated inside a pinned container to mean anything, and even then a
    diff only tells you *that* a page changed.

    The fingerprint answers the question Phase 3 actually asks. After the token
    swap, every colour in every route's fingerprint should have moved; anything
    still sitting at its old value is one of the 53 literal colours the token
    layer does not reach. A JSON diff names it. A pixel diff cannot.
    """
    result: dict[str, dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, (w, h) in viewports.items():
            for user, routes in ((TENANT_USER, routes_tenant), (ADMIN_USER, routes_admin)):
                if not routes:
                    continue
                context = browser.new_context(viewport={"width": w, "height": h})
                page = context.new_page()
                login(page, *user)
                for route in routes:
                    page.goto(f"{BASE_URL}{route}", wait_until="networkidle")
                    settle(page)
                    result[f"{route} @{name}"] = page.evaluate(FINGERPRINT)
                context.close()
        browser.close()

    out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    values = sum(len(v) for route in result.values() for v in route.values())
    print(f"Fingerprinted {len(result)} route/viewport pairs ({values} distinct rendered values)")
    print(f"Written to {out_path.relative_to(ROOT) if out_path.is_relative_to(ROOT) else out_path}")


def counts(findings: list[Finding]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f.kind] = out.get(f.kind, 0) + 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print every finding")
    parser.add_argument("--update", action="store_true", help="write current counts as the new ceiling")
    parser.add_argument("--routes", default="", help="comma-separated subset, e.g. /debt,/goals")
    parser.add_argument("--viewport", default="", choices=["", *VIEWPORTS], help="restrict to one viewport")
    parser.add_argument(
        "--snapshot",
        metavar="PATH",
        help="write each route's visual fingerprint (colours, type, radii, shadows) as JSON "
        "instead of auditing — the reviewable before/after for a token change",
    )
    args = parser.parse_args()

    tenant, admin = TENANT_ROUTES, ADMIN_ROUTES
    if args.routes:
        wanted = {r.strip() for r in args.routes.split(",")}
        tenant = [r for r in TENANT_ROUTES if r in wanted]
        admin = [r for r in ADMIN_ROUTES if r in wanted]
    viewports = {args.viewport: VIEWPORTS[args.viewport]} if args.viewport else VIEWPORTS

    if args.snapshot:
        snapshot(tenant, admin, viewports, Path(args.snapshot))
        return 0

    findings = run(tenant, admin, viewports)
    current = counts(findings)

    if args.list:
        for f in sorted(findings, key=lambda f: (f.kind, f.route, f.viewport)):
            print(f)
        print()

    if args.update:
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print(f"Baseline written to {BASELINE.relative_to(ROOT)}:")
        for kind, n in sorted(current.items()):
            print(f"  {kind:<18}{n}")
        return 0

    if not BASELINE.exists():
        print("No baseline. Run with --update to create one.", file=sys.stderr)
        return 1
    baseline = json.loads(BASELINE.read_text())

    print(f"Route audit  ({len(tenant) + len(admin)} routes x {len(viewports)} viewports)")
    for kind in sorted(set(baseline) | set(current)):
        print(f"  {kind:<18}{current.get(kind, 0):>4}  (ceiling {baseline.get(kind, 0)})")

    regressions = [
        f"  {k:<18}{baseline.get(k, 0)} -> {current.get(k, 0)}"
        for k in sorted(set(baseline) | set(current))
        if current.get(k, 0) > baseline.get(k, 0)
    ]
    if regressions:
        print("\nRegressions:", file=sys.stderr)
        for line in regressions:
            print(line, file=sys.stderr)
        print("\nRun with --list for detail.", file=sys.stderr)
        return 1

    print("\nNo regressions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

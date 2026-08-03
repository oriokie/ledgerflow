#!/usr/bin/env python3
"""Guard the design tokens against drift, as a ratchet.

`tokens.css` is the single source of truth for colour, type and elevation. It
only stays that way if bypassing it is harder than using it. This finds the
three bypasses that actually happened in this codebase:

* **Literal colours in stylesheets** — a hex or rgb() outside `tokens.css`.
  53 of these had accumulated, which is how a theme swap ends up with the
  handful of elements that don't change.
* **`em`-relative font sizes** — these compound through nested components and
  are what put 9.44px text on live screens against a 7-step scale.
* **Colour and font-size in inline `style={{…}}`** — invisible to every CSS
  tool, so it is where drift hides.

Why a ratchet rather than a wall: there are existing violations, and failing
the build on all of them on day one means the check gets disabled within a
week. Instead the current counts are the ceiling. Add one and CI fails; remove
one and you are asked to lower the ceiling, so the numbers only ever go down.

    python scripts/check_style_tokens.py            # check against the baseline
    python scripts/check_style_tokens.py --list     # show every violation
    python scripts/check_style_tokens.py --update   # re-baseline (deliberate)

Deliberately stdlib-only and file-based, matching `check_design_system.py` —
the alternative was stylelint plus its dependency tree for three rules.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "app" / "src"
STYLES = SRC / "styles"
TOKENS = STYLES / "tokens.css"
BASELINE = Path(__file__).resolve().parent / "style_tokens_baseline.json"

#: Colour literals. `currentColor`, `transparent` and `inherit` are fine — they
#: defer to something else rather than hardcoding a value.
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RGB = re.compile(r"\brgba?\([^)]*\)")
EM_FONT = re.compile(r"font-size:\s*[0-9.]+em")
INLINE_STYLE = re.compile(r"style=\{\{[^}]*\}\}")
INLINE_PROP = re.compile(r"\b(color|background|backgroundColor|fontSize)\s*:")
MEDIA_PX = re.compile(r"@media[^{]*?(\d+)px")

#: The six canonical breakpoints, documented in tokens.css.
#:
#: They cannot be custom properties — `@media (min-width: var(--bp-md))` never
#: resolves — so this is where they are actually enforced. The stylesheets grew
#: 14 distinct values including four off-by-one pairs (639/640, 767/768,
#: 899/900, 1023/1024), each leaving a one-pixel band with no rule applying.
BREAKPOINTS = {480, 640, 768, 1024, 1280, 1600}

#: `sw.ts` and the PWA manifest legitimately carry literal colours: a theme
#: colour has to be a real value before any stylesheet has loaded.
EXEMPT_FILES = {"tokens.css"}
EXEMPT_TSX = {"sw.ts", "pwa.ts"}


class Violation:
    def __init__(self, path: Path, line: int, kind: str, text: str) -> None:
        self.path = path.relative_to(ROOT)
        self.line = line
        self.kind = kind
        self.text = text.strip()[:80]

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  [{self.kind}]  {self.text}"


def _scan_css() -> list[Violation]:
    out: list[Violation] = []
    for css in sorted(STYLES.glob("*.css")):
        is_tokens = css.name in EXEMPT_FILES
        for n, line in enumerate(css.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("/*") or stripped.startswith("*"):
                continue
            if EM_FONT.search(line):
                out.append(Violation(css, n, "em-font-size", line))
            for match in MEDIA_PX.finditer(line):
                width = int(match.group(1))
                if width not in BREAKPOINTS:
                    out.append(Violation(css, n, "off-scale-breakpoint", f"{width}px"))
            if is_tokens:
                continue
            for pattern, kind in ((HEX, "literal-hex"), (RGB, "literal-rgb")):
                for match in pattern.finditer(line):
                    out.append(Violation(css, n, kind, match.group(0)))
    return out


def _scan_tsx() -> list[Violation]:
    out: list[Violation] = []
    for tsx in sorted([*SRC.rglob("*.tsx"), *SRC.rglob("*.ts")]):
        if tsx.name in EXEMPT_TSX or tsx.name.endswith(".test.tsx") or tsx.name.endswith(".test.ts"):
            continue
        for n, line in enumerate(tsx.read_text().splitlines(), 1):
            for match in INLINE_STYLE.finditer(line):
                body = match.group(0)
                if INLINE_PROP.search(body) and "var(--lf-" not in body:
                    out.append(Violation(tsx, n, "inline-style-literal", body))
    return out


def collect() -> list[Violation]:
    return _scan_css() + _scan_tsx()


def counts(violations: list[Violation]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for v in violations:
        totals[v.kind] = totals.get(v.kind, 0) + 1
    return totals


def load_baseline() -> dict[str, int]:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print every violation")
    parser.add_argument("--update", action="store_true", help="write the current counts as the new ceiling")
    args = parser.parse_args()

    violations = collect()
    current = counts(violations)

    if args.list:
        for v in sorted(violations, key=lambda v: (str(v.path), v.line)):
            print(v)
        print()

    if args.update:
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print(f"Baseline written to {BASELINE.relative_to(ROOT)}:")
        for kind, n in sorted(current.items()):
            print(f"  {kind:<24}{n}")
        return 0

    baseline = load_baseline()
    if not baseline:
        print("No baseline. Run with --update to create one.", file=sys.stderr)
        return 1

    regressions, improvements = [], []
    for kind in sorted(set(baseline) | set(current)):
        was, now = baseline.get(kind, 0), current.get(kind, 0)
        if now > was:
            regressions.append(f"  {kind:<24}{was} -> {now}  (+{now - was})")
        elif now < was:
            improvements.append(f"  {kind:<24}{was} -> {now}  ({now - was})")

    print("Design-token drift")
    for kind in sorted(set(baseline) | set(current)):
        print(f"  {kind:<24}{current.get(kind, 0):>4}  (ceiling {baseline.get(kind, 0)})")

    if regressions:
        print("\nNew token bypasses — use a var(--lf-*) instead:", file=sys.stderr)
        for line in regressions:
            print(line, file=sys.stderr)
        print("\nRun with --list to see them.", file=sys.stderr)
        return 1

    if improvements:
        print("\nViolations removed — thank you. Lower the ceiling with --update:")
        for line in improvements:
            print(line)
        return 1

    print("\nNo drift.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

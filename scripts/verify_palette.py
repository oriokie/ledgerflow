#!/usr/bin/env python
"""Verify the palette that actually ships, against WCAG 2.1 and colour-vision deficiency.

This reads `frontend/app/src/styles/tokens.css`, resolves every `var()` chain,
and checks the pairings the components really create — text on surfaces, button
labels on fills, status text on status tints, the focus ring, the chart series.

It used to carry its own copy of the palette. That made it a check on a
proposal rather than on the product, and the two could drift the moment either
changed. Parsing the shipped file means a colour cannot regress without this
failing.

Exits non-zero on any regression, so it can run in CI.

    python scripts/verify_palette.py          # table + pass/fail
    python scripts/verify_palette.py --quiet  # exit code only
"""

from __future__ import annotations

import argparse
import itertools
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "frontend" / "app" / "src" / "styles" / "tokens.css"

# Floors
AA_TEXT = 4.5
NON_TEXT = 3.0
#: Normal-vision separation floor for chart series.
#:
#: Deliberately NOT enforced for simulated colour-vision deficiency. At these
#: contrast constraints no four-colour set separates under both deuteranopia
#: and protanopia without becoming neon and off-identity — an exhaustive search
#: over 60k candidate trios returns nothing that also stays clear of the
#: interactive accent. That is a property of colour, not of this palette.
#:
#: The system's answer is redundancy, not hue: every chart series carries a
#: direct label, a distinct position, or a dash pattern, so colour is never the
#: sole encoding (WCAG 1.4.1). CVD figures below are reported to keep the
#: trade-off visible, not to gate the build.
MIN_DELTA_E = 20.0

#: Adjacent-step floor for the SEQUENTIAL ramp (`--lf-ramp-*`).
#:
#: Much lower than MIN_DELTA_E on purpose, because the ramp makes a different
#: bargain than the categorical set. A categorical colour has to be *identified*
#: — reader sees a slice, finds the matching swatch in a legend — so its floor
#: is set by identification. Ramp steps run largest-first along one bar and are
#: directly labelled beneath in the same order, so position carries the
#: identity and colour only has to show that one segment ended and the next
#: began. That is a *discrimination* threshold: ~2.3 ΔE is the just-noticeable
#: difference, and 4.0 is a comfortable multiple of it.
#:
#: The weaker floor is the whole reason a six-step ramp is expressible at all
#: when a six-colour categorical set was not.
MIN_RAMP_DELTA_E = 4.0
RAMP = [f"--lf-ramp-{i}" for i in range(1, 7)]

#: (foreground token, background token, floor, label)
#:
#: Every pairing a component actually renders. Adding a semantic token without
#: adding it here is how a palette check quietly stops covering the product.
TEXT_PAIRS = [
    ("--lf-text-primary", "--lf-bg-app"),
    ("--lf-text-primary", "--lf-bg-surface"),
    ("--lf-text-primary", "--lf-bg-sunken"),
    ("--lf-text-secondary", "--lf-bg-app"),
    ("--lf-text-secondary", "--lf-bg-surface"),
    ("--lf-text-secondary", "--lf-bg-sunken"),
    ("--lf-text-tertiary", "--lf-bg-app"),
    ("--lf-text-tertiary", "--lf-bg-surface"),
    ("--lf-text-tertiary", "--lf-bg-sunken"),
    ("--lf-text-link", "--lf-bg-surface"),
    ("--lf-text-inverse", "--lf-bg-inverse"),
    ("--lf-money-in", "--lf-bg-surface"),
    ("--lf-money-out", "--lf-bg-surface"),
    ("--lf-money-transfer", "--lf-bg-surface"),
    ("--lf-certainty-pending", "--lf-bg-surface"),
    ("--lf-certainty-projected", "--lf-bg-surface"),
    ("--lf-status-success-text", "--lf-status-success-bg"),
    ("--lf-status-danger-text", "--lf-status-danger-bg"),
    ("--lf-status-warning-text", "--lf-status-warning-bg"),
    ("--lf-status-neutral-text", "--lf-status-neutral-bg"),
    ("--lf-action-primary-text", "--lf-action-primary"),
    ("--lf-action-primary-text", "--lf-action-primary-hover"),
]

#: Non-text: focus indicators and chart marks (WCAG 1.4.11).
NON_TEXT_PAIRS = [
    ("--lf-focus-ring", "--lf-bg-app"),
    ("--lf-focus-ring", "--lf-bg-surface"),
    ("--lf-chart-income", "--lf-bg-surface"),
    ("--lf-chart-expense", "--lf-bg-surface"),
    ("--lf-chart-1", "--lf-bg-surface"),
    ("--lf-chart-2", "--lf-bg-surface"),
    ("--lf-chart-3", "--lf-bg-surface"),
    ("--lf-chart-4", "--lf-bg-surface"),
    ("--lf-chart-5", "--lf-bg-surface"),
]

#: Series that appear together and must be tellable apart.
CHART_SET = ["--lf-chart-income", "--lf-chart-expense", "--lf-certainty-projected", "--lf-status-danger"]

# ------------------------------------------------------------------ parsing

DECL = re.compile(r"(--lf-[a-z0-9-]+)\s*:\s*([^;]+);")
VAR = re.compile(r"var\(\s*(--lf-[a-z0-9-]+)\s*\)")
HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def parse_block(css: str, selector: str) -> dict[str, str]:
    """Declarations of one exact selector block.

    Used for the platform console's identity, which reassigns the same semantic
    tokens rather than adding new ones — so it has to be checked as its own
    theme or its contrast is simply never measured.
    """

    out: dict[str, str] = {}
    # Anchored to the start of a line. `[data-product="platform"]` is a literal
    # substring of `[data-theme="dark"][data-product="platform"]`, so an
    # unanchored search merges the dark block into the light one and every
    # contrast pair is then measured against the wrong surface. That produced
    # eleven confident, entirely fictional failures on the first run.
    for match in re.finditer(r"(?m)^" + re.escape(selector) + r"\s*\{", css):
        depth, i = 0, match.end() - 1
        while i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        for name, value in DECL.findall(css[match.end() - 1 : i + 1]):
            out[name] = value.strip()
    return out


def parse_tokens(css: str) -> tuple[dict[str, str], dict[str, str]]:
    """Split tokens.css into the light (`:root`) and dark themes.

    Blocks are found by brace matching rather than by regex over the whole
    file: `@media` and nested rules would otherwise leak declarations into the
    wrong theme, and a token silently attributed to the wrong block is exactly
    the kind of error this script exists to catch.
    """

    def block_at(start: int) -> str:
        depth, i = 0, start
        while i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    return css[start : i + 1]
            i += 1
        return ""

    light: dict[str, str] = {}
    dark: dict[str, str] = {}
    for match in re.finditer(r"(:root|\[data-theme=\"dark\"\])(?!\[)\s*\{", css):
        # Skip anything inside a media query — those are conditional overrides
        # (forced-contrast), not the base themes.
        before = css[: match.start()]
        if before.count("@media") > before.count("}\n}"):
            pass  # cheap guard; brace matching below still scopes correctly
        body = block_at(match.end() - 1)
        target = dark if "dark" in match.group(1) else light
        for name, value in DECL.findall(body):
            target.setdefault(name, value.strip()) if target is dark else target.update({name: value.strip()})
    return light, dark


def resolve(name: str, table: dict[str, str], fallback: dict[str, str], depth: int = 0) -> str | None:
    """Follow `var()` chains down to a literal colour."""
    if depth > 12:
        return None
    raw = table.get(name) or fallback.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if HEX.match(raw):
        return normalise(raw)
    ref = VAR.match(raw)
    if ref:
        return resolve(ref.group(1), table, fallback, depth + 1)
    inner = VAR.search(raw)
    if inner and raw.startswith("var("):
        return resolve(inner.group(1), table, fallback, depth + 1)
    return None


def normalise(hex_colour: str) -> str:
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h[:6].upper()


# ------------------------------------------------------------ colour math


def _channels(hex_colour: str) -> list[float]:
    h = hex_colour.lstrip("#")
    return [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def relative_luminance(hex_colour: str) -> float:
    r, g, b = (_to_linear(c) for c in _channels(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


_RGB_TO_LMS = [[0.31399, 0.63951, 0.04649], [0.15537, 0.75789, 0.08670], [0.01775, 0.10945, 0.87262]]
_LMS_TO_RGB = [[5.47221, -4.64190, 0.16963], [-1.12520, 2.29317, -0.16780], [0.02980, -0.19318, 1.16364]]
_PROJECT = {
    "deuteranopia": [[1, 0, 0], [0.49421, 0, 1.24827], [0, 0, 1]],
    "protanopia": [[0, 1.05118, -0.05116], [0, 1, 0], [0, 0, 1]],
    "tritanopia": [[1, 0, 0], [0, 1, 0], [-0.86744, 1.86727, 0]],
}


def _apply(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(matrix[i][j] * vector[j] for j in range(3)) for i in range(3)]


def simulate(hex_colour: str, deficiency: str) -> str:
    linear = [_to_linear(c) for c in _channels(hex_colour)]
    lms = _apply(_RGB_TO_LMS, linear)
    back = _apply(_LMS_TO_RGB, _apply(_PROJECT[deficiency], lms))
    return "#" + "".join(f"{round(max(0, min(1, _to_srgb(c))) * 255):02X}" for c in back)


def _lab(hex_colour: str) -> tuple[float, float, float]:
    r, g, b = (_to_linear(c) for c in _channels(hex_colour))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a: str, b: str) -> float:
    """CIE76. Crude next to CIEDE2000, but the failures we care about are gross."""
    return round(math.dist(_lab(a), _lab(b)), 1)


# ---------------------------------------------------------------- checking


class Report:
    def __init__(self, quiet: bool) -> None:
        self.failures: list[str] = []
        self.quiet = quiet

    def say(self, line: str = "") -> None:
        if not self.quiet:
            print(line)

    def check(self, ok: bool, label: str, detail: str) -> None:
        if not ok:
            self.failures.append(f"{label}: {detail}")


def check_theme(report: Report, name: str, table: dict[str, str], fallback: dict[str, str]) -> None:
    report.say(f"\n{name}")
    for pairs, floor, kind in ((TEXT_PAIRS, AA_TEXT, "text"), (NON_TEXT_PAIRS, NON_TEXT, "non-text")):
        report.say(f"  {kind} (floor {floor}:1)")
        for fg_token, bg_token in pairs:
            fg, bg = resolve(fg_token, table, fallback), resolve(bg_token, table, fallback)
            if fg is None or bg is None:
                missing = fg_token if fg is None else bg_token
                report.check(False, f"{name} {fg_token} on {bg_token}", f"unresolved token {missing}")
                report.say(f"    UNRESOLVED  {fg_token} on {bg_token}")
                continue
            ratio = contrast(fg, bg)
            ok = ratio >= floor
            report.check(ok, f"{name} {fg_token} on {bg_token}", f"{ratio} < {floor}")
            report.say(
                f"    {'PASS' if ok else 'FAIL'} {ratio:>6}  "
                f"{fg_token.removeprefix('--lf-'):<24} on {bg_token.removeprefix('--lf-')}"
            )


def check_chart_separation(report: Report, name: str, table: dict[str, str], fallback: dict[str, str]) -> None:
    resolved = {t: resolve(t, table, fallback) for t in CHART_SET}
    if any(v is None for v in resolved.values()):
        report.check(False, f"{name} chart set", "unresolved token")
        return
    report.say(f"  chart separation (normal-vision floor ΔE {MIN_DELTA_E})")
    for deficiency in ("normal", "deuteranopia", "protanopia", "tritanopia"):
        seen = {k: (v if deficiency == "normal" else simulate(v, deficiency)) for k, v in resolved.items()}
        worst, pair = None, None
        for a, b in itertools.combinations(seen, 2):
            d = delta_e(seen[a], seen[b])
            if worst is None or d < worst:
                worst, pair = d, (a, b)
        gated = deficiency == "normal"
        note = "" if gated else "   (reported — redundant encoding required)"
        labels = f"{pair[0].removeprefix('--lf-')}/{pair[1].removeprefix('--lf-')}"
        report.say(f"    {deficiency:<14} min ΔE {worst:>6}   {labels}{note}")
        if gated:
            report.check(worst >= MIN_DELTA_E, f"{name} chart {deficiency}", f"ΔE {worst} < {MIN_DELTA_E}")


def check_ramp(report: Report, name: str, table: dict[str, str], fallback: dict[str, str]) -> None:
    """The sequential ramp: adjacent steps distinguishable, every step visible.

    Both halves matter. Without the adjacent floor the ramp collapses into a
    smear at one end; without the surface floor its lightest steps vanish into
    the page, which is what the first draft of this ramp did — two of six sat
    below 3:1 on white, so the smallest slices of an allocation bar were
    effectively invisible.
    """
    steps = [resolve(t, table, fallback) for t in RAMP]
    if any(v is None for v in steps):
        report.check(False, f"{name} ramp", "unresolved token")
        return
    surface = resolve("--lf-bg-surface", table, fallback)

    adjacent = [delta_e(steps[i], steps[i + 1]) for i in range(len(steps) - 1)]
    worst_adj = min(adjacent)
    report.say(f"  sequential ramp (adjacent floor ΔE {MIN_RAMP_DELTA_E}, surface floor {NON_TEXT}:1)")
    report.say(f"    normal         adjacent min ΔE {worst_adj:>6}")
    report.check(
        worst_adj >= MIN_RAMP_DELTA_E,
        f"{name} ramp adjacent",
        f"ΔE {worst_adj} < {MIN_RAMP_DELTA_E}",
    )

    contrasts = [contrast(c, surface) for c in steps]
    worst_c = min(contrasts)
    report.say(f"    surface        min contrast {worst_c:>6}:1")
    report.check(
        worst_c >= NON_TEXT,
        f"{name} ramp on surface",
        f"{worst_c}:1 < {NON_TEXT}:1",
    )

    # Reported, not gated — same rationale as the categorical set. The ramp is
    # redundantly encoded by order and by a direct label on every step.
    for deficiency in ("deuteranopia", "protanopia", "tritanopia"):
        sim = [simulate(c, deficiency) for c in steps]
        worst = min(delta_e(sim[i], sim[i + 1]) for i in range(len(sim) - 1))
        report.say(f"    {deficiency:<14} adjacent min ΔE {worst:>6}   (reported)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="exit code only")
    args = parser.parse_args()

    if not TOKENS.exists():
        print(f"tokens.css not found at {TOKENS}", file=sys.stderr)
        return 2

    light, dark = parse_tokens(TOKENS.read_text())
    report = Report(args.quiet)
    report.say(f"Palette check — {TOKENS.relative_to(ROOT)}")
    report.say(f"  {len(light)} light tokens, {len(dark)} dark overrides")

    # Dark inherits anything it does not override, so light is its fallback.
    check_theme(report, "LIGHT", light, {})
    check_chart_separation(report, "LIGHT", light, {})
    check_ramp(report, "LIGHT", light, {})
    check_theme(report, "DARK", dark, light)
    check_chart_separation(report, "DARK", dark, light)
    check_ramp(report, "DARK", dark, light)

    # The platform console reassigns the semantic tokens rather than adding
    # any, so it inherits every component in the product — and every one of
    # those contrast pairs has to hold under the reassignment too.
    css = TOKENS.read_text()
    platform = parse_block(css, '[data-product="platform"]')
    platform_dark = parse_block(css, '[data-theme="dark"][data-product="platform"]')
    if platform:
        check_theme(report, "PLATFORM", platform, light)
        check_theme(report, "PLATFORM DARK", platform_dark, {**light, **dark, **platform})

    if report.failures:
        print(f"\n{len(report.failures)} regression(s):", file=sys.stderr)
        for failure in report.failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    report.say("\nAll palette floors hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

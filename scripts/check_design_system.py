#!/usr/bin/env python3
"""Design-system verification for LedgerFlow (stdlib only).

Checks, in order:
1. WCAG 2.1 contrast for every semantic foreground/background pair actually
   used by the components, in BOTH themes. Text pairs must meet >= 4.5:1
   (AA, normal text — we hold even small meta text to this); non-text
   indicators (focus ring) must meet >= 3:1 (AA, 1.4.11).
2. Token integrity: every var(--lf-*) referenced anywhere resolves to a
   definition in tokens.css.
3. HTML well-formedness of the three demo pages (tag balance).
4. The transactions demo's running-balance column is real arithmetic:
   balance[i+1] == balance[i] - amount[i] (rows are newest-first).

Exit code 0 = all green. Anything else prints the failures.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

DS = Path(__file__).resolve().parent.parent / "frontend" / "design-system"

VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


# --------------------------------------------------------------------- color math
def _channel(value: int) -> float:
    srgb = value / 255
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg: str, bg: str) -> float:
    lighter, darker = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# --------------------------------------------------------------------- token parsing
def parse_tokens(css: str) -> tuple[dict[str, str], dict[str, str]]:
    """Returns (light, dark) maps of --token -> raw value, with var()
    references resolved to hex where possible."""
    blocks = {"light": "", "dark": ""}
    root = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    dark = re.search(r'\[data-theme="dark"\]\s*\{(.*?)\n\}', css, re.S)
    blocks["light"] = root.group(1) if root else ""
    blocks["dark"] = dark.group(1) if dark else ""

    def parse_block(text: str) -> dict[str, str]:
        return dict(re.findall(r"(--lf-[\w-]+)\s*:\s*([^;]+);", text))

    light = parse_block(blocks["light"])
    dark_overrides = parse_block(blocks["dark"])
    dark_full = {**light, **dark_overrides}

    def resolve(token: str, table: dict[str, str], depth: int = 0) -> str:
        if depth > 10:
            return ""
        value = table.get(token, "").strip()
        match = re.fullmatch(r"var\((--lf-[\w-]+)\)", value)
        if match:
            return resolve(match.group(1), table, depth + 1)
        return value

    return (
        {token: resolve(token, light) for token in light},
        {token: resolve(token, dark_full) for token in dark_full},
    )


# --------------------------------------------------------------------- checks
def check_contrast(light: dict[str, str], dark: dict[str, str]) -> list[str]:
    # (foreground token, background token, minimum ratio, where it's used)
    TEXT = 4.5
    NON_TEXT = 3.0
    pairs = [
        ("--lf-text-primary", "--lf-bg-app", TEXT, "body text on app background"),
        ("--lf-text-primary", "--lf-bg-surface", TEXT, "body text on cards"),
        ("--lf-text-primary", "--lf-bg-sunken", TEXT, "body text on sunken/hover"),
        ("--lf-text-secondary", "--lf-bg-app", TEXT, "secondary text on app bg"),
        ("--lf-text-secondary", "--lf-bg-surface", TEXT, "secondary text on cards"),
        ("--lf-text-secondary", "--lf-bg-sunken", TEXT, "secondary text on hover rows"),
        ("--lf-text-tertiary", "--lf-bg-surface", TEXT, "meta text/placeholders on cards"),
        ("--lf-text-tertiary", "--lf-bg-sunken", TEXT, "meta text on hover rows"),
        ("--lf-text-tertiary", "--lf-bg-app", TEXT, "tab bar labels on app bg"),
        ("--lf-text-link", "--lf-bg-surface", TEXT, "links on cards"),
        ("--lf-text-link", "--lf-bg-app", TEXT, "links on app bg"),
        ("--lf-text-inverse", "--lf-bg-inverse", TEXT, "toast text"),
        ("--lf-action-primary-text", "--lf-action-primary", TEXT, "primary button label"),
        ("--lf-action-primary-text", "--lf-action-primary-hover", TEXT, "primary button label (hover state)"),
        ("--lf-money-in", "--lf-bg-surface", TEXT, "money-in amounts"),
        ("--lf-money-in", "--lf-bg-app", TEXT, "money-in on app bg"),
        ("--lf-money-out", "--lf-bg-surface", TEXT, "money-out amounts"),
        ("--lf-money-transfer", "--lf-bg-surface", TEXT, "transfer amounts"),
        ("--lf-money-transfer", "--lf-bg-sunken", TEXT, "transfer amounts on hover"),
        ("--lf-status-success-text", "--lf-status-success-bg", TEXT, "success badge"),
        ("--lf-status-danger-text", "--lf-status-danger-bg", TEXT, "danger badge"),
        ("--lf-status-warning-text", "--lf-status-warning-bg", TEXT, "warning badge"),
        ("--lf-status-neutral-text", "--lf-status-neutral-bg", TEXT, "neutral badge"),
        ("--lf-status-danger-text", "--lf-bg-surface", TEXT, "error text under fields"),
        ("--lf-status-danger", "--lf-bg-surface", TEXT, "over-budget amounts"),
        ("--lf-focus-ring", "--lf-bg-app", NON_TEXT, "focus ring vs app bg"),
        ("--lf-focus-ring", "--lf-bg-surface", NON_TEXT, "focus ring vs cards"),
        ("--lf-chart-1", "--lf-bg-surface", NON_TEXT, "chart ramp 1 on cards"),
        ("--lf-chart-2", "--lf-bg-surface", NON_TEXT, "chart ramp 2 on cards"),
        ("--lf-chart-3", "--lf-bg-surface", NON_TEXT, "chart ramp 3 on cards"),
        ("--lf-chart-4", "--lf-bg-surface", NON_TEXT, "chart ramp 4 on cards"),
        ("--lf-chart-5", "--lf-bg-surface", NON_TEXT, "chart ramp 5 on cards"),
    ]

    failures = []
    for theme_name, table in (("light", light), ("dark", dark)):
        for fg, bg, minimum, usage in pairs:
            fg_hex, bg_hex = table.get(fg, ""), table.get(bg, "")
            if not (fg_hex.startswith("#") and bg_hex.startswith("#")):
                failures.append(f"[{theme_name}] cannot resolve {fg} or {bg} to hex")
                continue
            ratio = contrast(fg_hex, bg_hex)
            status = "OK " if ratio >= minimum else "FAIL"
            print(f"  [{theme_name:5}] {status} {ratio:5.2f}:1 (min {minimum}) {fg} on {bg} — {usage}")
            if ratio < minimum:
                failures.append(
                    f"[{theme_name}] {fg} ({fg_hex}) on {bg} ({bg_hex}) = {ratio:.2f}:1 < {minimum} ({usage})"
                )
    return failures


def check_token_references(light: dict[str, str]) -> list[str]:
    defined = set(light.keys())
    failures = []
    for css_file in ("base.css", "components.css", "tokens.css"):
        text = (DS / css_file).read_text()
        for ref in set(re.findall(r"var\((--lf-[\w-]+)\)", text)):
            if ref not in defined:
                failures.append(f"{css_file}: var({ref}) has no definition in tokens.css")
    for html_file in DS.glob("*.html"):
        for ref in set(re.findall(r"var\((--lf-[\w-]+)\)", html_file.read_text())):
            if ref not in defined:
                failures.append(f"{html_file.name}: var({ref}) has no definition in tokens.css")
    return failures


class TagBalanceChecker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append(f"closing </{tag}> with empty stack")
        elif self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(f"expected </{self.stack[-1]}>, got </{tag}>")


def check_html() -> list[str]:
    failures = []
    for page in ("index.html", "dashboard.html", "transactions.html"):
        checker = TagBalanceChecker()
        checker.feed((DS / page).read_text())
        for error in checker.errors:
            failures.append(f"{page}: {error}")
        if checker.stack:
            failures.append(f"{page}: unclosed tags at EOF: {checker.stack}")
        if not checker.errors and not checker.stack:
            print(f"  OK   {page}: tags balanced")
    return failures


def check_ledger_arithmetic() -> list[str]:
    """In transactions.html, rows are newest-first; each row carries
    data value attributes for amount and running balance. The invariant:
    balance[i+1] == balance[i] - amount[i]."""
    text = (DS / "transactions.html").read_text()
    tbody = re.search(r"<tbody>(.*?)</tbody>", text, re.S)
    rows = re.findall(r"<tr>(.*?)</tr>", tbody.group(1), re.S)
    parsed = []
    for row in rows:
        values = re.findall(r'<data class="lf-amount[^"]*" value="(-?[\d.]+)"', row)
        if len(values) >= 2:  # amount + balance columns
            parsed.append((float(values[0]), float(values[1])))
    failures = []
    for i in range(len(parsed) - 1):
        amount, balance = parsed[i]
        _, prev_balance = parsed[i + 1]
        expected = round(balance - amount, 2)
        if abs(prev_balance - expected) > 0.001:
            failures.append(
                f"transactions.html row {i + 1}: balance {balance} - amount {amount} "
                f"should give previous balance {expected}, table shows {prev_balance}"
            )
    if not failures:
        print(f"  OK   transactions.html: running balance verified across {len(parsed)} rows")
    return failures


def check_bar_proportions() -> list[str]:
    """Bar-chart fill widths must be proportional to their data values:
    width_i == value_i / max(values) * 100 (±0.25pp for 1dp rounding)."""
    failures = []
    for page in ("dashboard.html", "index.html"):
        text = (DS / page).read_text()
        for chart_index, chart in enumerate(re.findall(r'<ul class="lf-bars">(.*?)</ul>', text, re.S)):
            rows = re.findall(r'<li data-value="([\d.]+)">.*?style="width:\s*([\d.]+)%;"', chart, re.S)
            if not rows:
                failures.append(f"{page} chart {chart_index}: no parsable bars")
                continue
            values = [float(value) for value, _ in rows]
            maximum = max(values)
            for value, width in rows:
                expected = float(value) / maximum * 100
                if abs(float(width) - expected) > 0.25:
                    failures.append(
                        f"{page} chart {chart_index}: value {value} should be "
                        f"{expected:.1f}% wide, markup says {width}%"
                    )
            if not any(f.startswith(f"{page} chart {chart_index}") for f in failures):
                print(f"  OK   {page} chart {chart_index}: {len(rows)} bar widths proportional to values")
    return failures


def check_page_wiring() -> list[str]:
    """Every page must carry the no-flash theme snippet in <head>, include
    app.js, and contain the command-palette dialog it wires up."""
    failures = []
    for page in ("index.html", "dashboard.html", "transactions.html"):
        text = (DS / page).read_text()
        head = text.split("</head>")[0]
        if 'localStorage.getItem("lf-theme")' not in head:
            failures.append(f"{page}: no-flash theme snippet missing from <head>")
        if '<script src="app.js">' not in text:
            failures.append(f"{page}: app.js not included")
        if 'id="cmdk"' not in text:
            failures.append(f"{page}: command-palette dialog missing")
        if f"{page}:" not in " ".join(failures):
            print(f"  OK   {page}: theme snippet, app.js, palette present")
    return failures


def check_safe_to_spend() -> list[str]:
    """The dashboard's hero is a DERIVED number; its disclosure shows the
    inputs. Invariant: start − Σ(minus) == result, to the cent."""
    text = (DS / "dashboard.html").read_text()
    entries = re.findall(r'data-sts="(\w+)" value="([\d.]+)"', text)
    start = sum(float(v) for k, v in entries if k == "start")
    minus = sum(float(v) for k, v in entries if k == "minus")
    results = [float(v) for k, v in entries if k == "result"]
    failures = []
    if not results or start == 0:
        return ["dashboard.html: safe-to-spend data-sts markers missing"]
    expected = round(start - minus, 2)
    if abs(results[0] - expected) > 0.001:
        failures.append(
            f"dashboard.html: safe-to-spend shows {results[0]}, but " f"{start} − {minus} = {expected}"
        )
    else:
        print(
            f"  OK   dashboard.html: safe to spend {results[0]} == "
            f"{start} − {minus} (derived number is honest)"
        )
    return failures


def check_insight_rules() -> list[str]:
    """Design rules for insight cards, enforced mechanically:
    - attention/soon insights: exactly ONE action button
    - good insights: ZERO actions (good news doesn't nag)
    - every insight: at least one disclosure (the 'show the math' grounding)
    """
    failures = []
    for page in ("dashboard.html",):
        text = (DS / page).read_text()
        cards = re.findall(
            r'<article class="lf-card lf-insight lf-insight--(\w+)">(.*?)</article>', text, re.S
        )
        if not cards:
            failures.append(f"{page}: no insight cards found")
        for index, (severity, body) in enumerate(cards):
            actions = body.count("data-insight-action")
            disclosures = body.count('class="lf-disclosure"')
            if severity in ("attention", "soon") and actions != 1:
                failures.append(f"{page} insight {index} ({severity}): needs exactly 1 action, has {actions}")
            if severity == "good" and actions != 0:
                failures.append(
                    f"{page} insight {index} (good): positive insights must not carry actions, has {actions}"
                )
            if disclosures < 1:
                failures.append(
                    f"{page} insight {index} ({severity}): missing its 'show the math' disclosure"
                )
        if not any(f.startswith(page) for f in failures):
            print(f"  OK   {page}: {len(cards)} insight cards follow the action/disclosure rules")
    return failures


def main() -> int:
    tokens_css = (DS / "tokens.css").read_text()
    light, dark = parse_tokens(tokens_css)
    print(f"Parsed {len(light)} light tokens, {len(dark)} dark tokens\n")

    print("== WCAG contrast ==")
    failures = check_contrast(light, dark)
    print("\n== Token reference integrity ==")
    ref_failures = check_token_references(light)
    for failure in ref_failures:
        print(f"  FAIL {failure}")
    if not ref_failures:
        print("  OK   every var(--lf-*) reference resolves")
    failures += ref_failures
    print("\n== HTML well-formedness ==")
    failures += check_html()
    print("\n== Demo ledger arithmetic ==")
    failures += check_ledger_arithmetic()
    print("\n== Chart bar proportionality ==")
    failures += check_bar_proportions()
    print("\n== Page wiring (theme + palette) ==")
    failures += check_page_wiring()
    print("\n== Safe-to-spend derivation ==")
    failures += check_safe_to_spend()
    print("\n== Insight card rules ==")
    failures += check_insight_rules()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

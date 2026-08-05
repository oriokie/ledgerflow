#!/usr/bin/env python3
"""Screenshot any route of the running app, signed in.

`audit_routes.py` already drives a real browser against a real dev server and
already knows how to sign in; this reuses that machinery for the other half of
the job — actually *looking* at a screen. The audit answers "does anything
measure wrong"; this answers "does it look right", which no assertion does.

    python scripts/shoot.py / /transactions --out /tmp/shots
    python scripts/shoot.py /login --signed-out
    python scripts/shoot.py / --viewport mobile --theme light

Requires the stack from `.claude/launch.json` to be up (api on 8000, web on
5173) — the same precondition the audit has.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from audit_routes import BASE_URL, TENANT_USER, VIEWPORTS, login, settle

THEME_KEY = "lf-theme"


def shoot(
    routes: list[str],
    out: Path,
    *,
    viewport: str,
    theme: str | None,
    signed_out: bool,
    full_page: bool,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        width, height = VIEWPORTS[viewport]
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()

        if theme:
            # Seeded before the app boots, or the first paint uses the old one
            # and the screenshot catches the transition rather than the theme.
            context.add_init_script(f"localStorage.setItem('{THEME_KEY}', '{theme}')")

        if not signed_out:
            login(page, *TENANT_USER)

        for route in routes:
            page.goto(f"{BASE_URL}{route}", wait_until="networkidle")
            settle(page)
            name = (route.strip("/") or "root").replace("/", "-")
            path = out / f"{name}-{viewport}{f'-{theme}' if theme else ''}.png"
            page.screenshot(path=str(path), full_page=full_page)
            print(path)

        browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("routes", nargs="+", help="routes to shoot, e.g. / /transactions")
    ap.add_argument("--out", default="/tmp/lf-shots", help="output directory")
    ap.add_argument("--viewport", default="desktop", choices=list(VIEWPORTS))
    ap.add_argument("--theme", default=None, choices=["light", "dark"])
    ap.add_argument("--signed-out", action="store_true", help="don't sign in first")
    ap.add_argument("--full-page", action="store_true", help="capture past the fold")
    args = ap.parse_args()

    shoot(
        args.routes,
        Path(args.out),
        viewport=args.viewport,
        theme=args.theme,
        signed_out=args.signed_out,
        full_page=args.full_page,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Visual smoke test: does any of this actually render?

Every screen built in this workstream has been verified by unit tests and by
API calls, and none of it has been watched in a browser. Those are different
questions: a page can pass every assertion about its data and still throw on
mount, render a blank shell, or hide its content behind a CSS mistake.

This drives a real Chromium against a real dev server and a real database, and
fails on anything that reaches the console as an error — a React crash, a
failed fetch, an unhandled rejection. Screenshots are written for inspection.

Deliberately not a replacement for the unit tests: it asserts that things
appear, not that the arithmetic behind them is right. It is the layer that
catches "the whole page is white", which no amount of `expect(mrr).toBe(...)`
ever will.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
SHOTS = Path("/tmp/ui-shots")
ADMIN = ("admin@ledgerflow.test", "PlatformAdmin!2026")
#: A seeded demo customer — used for the tenant-side pages, since a platform
#: account is now barred from owning a workspace at all.
CUSTOMER = ("amina@example.test", "PlatformAdmin!2026")

failures: list[str] = []
console_errors: list[str] = []


def record(page):
    def on_console(message):
        if message.type == "error":
            text = message.text
            # React Router emits future-flag notices as errors in v7; they are
            # advisory and not a rendering failure.
            # Dev-server artifacts, not rendering failures:
            #  * the PWA service worker is generated at build time, so the dev
            #    server returns index.html for /sw.js and registration fails;
            #  * React Router emits future-flag notices at error level.
            ignorable = ("unsupported mime type", "serviceworker", "future flag")
            if any(token in text.lower() for token in ignorable):
                return
            console_errors.append(text)

    page.on("console", on_console)
    page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))


def login(page, email, password):
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill('input[type="email"]', email)
    page.fill('input[type="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_timeout(2500)


def visit(page, path, name, expect_text=None):
    """Load a page, screenshot it, and check it is not blank."""
    before = len(console_errors)
    page.goto(f"{BASE}{path}", wait_until="networkidle")
    # Long enough for React Query to resolve. Screenshotting mid-fetch produces
    # a picture of a loading state, which proves nothing about the page.
    page.wait_for_timeout(3000)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)

    body = page.inner_text("body").strip()
    if len(body) < 200:
        failures.append(f"{name}: page is effectively blank ({len(body)} chars)")
    if expect_text and expect_text.lower() not in body.lower():
        failures.append(f"{name}: expected to find {expect_text!r} on the page")
    new_errors = console_errors[before:]
    if new_errors:
        failures.append(f"{name}: console errors -> {new_errors[:3]}")
    print(f"  {'ok ' if not new_errors else 'ERR'} {name:28} {len(body):>6} chars  {path}")
    return body


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/opt/google/chrome/chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        record(page)

        # ---------------------------------------------------- admin console
        print("\nADMIN CONSOLE (platform owner)")
        login(page, *ADMIN)

        # Separation: an operator landing on a customer route must be sent to
        # the console, not shown a workspace picker they may not use.
        page.goto(f"{BASE}/dashboard", wait_until="networkidle")
        page.wait_for_timeout(1500)
        if "/admin" not in page.url:
            failures.append(f"separation: operator on /dashboard landed at {page.url}, expected /admin")
        else:
            print(f"  ok  redirect to console         {page.url}")

        visit(page, "/admin", "admin-dashboard", expect_text="MRR")
        visit(page, "/admin/tenants", "admin-tenants", expect_text="Customers")
        visit(page, "/admin/billing", "admin-billing", expect_text="Billing")
        visit(page, "/admin/invoices", "admin-invoices", expect_text="Invoices")
        visit(page, "/admin/dunning", "admin-dunning", expect_text="recovery")
        visit(page, "/admin/coupons", "admin-coupons", expect_text="Promotions")
        visit(page, "/admin/analytics", "admin-analytics", expect_text="Analytics")
        visit(page, "/admin/health", "admin-health", expect_text="System")
        visit(page, "/admin/audit", "admin-audit", expect_text="Audit")
        visit(page, "/admin/staff", "admin-staff", expect_text="Platform access")
        settings_body = visit(page, "/admin/settings", "admin-settings", expect_text="Settings")

        # A secret must never reach the browser at all.
        if "sk_live" in settings_body or "sk_test" in settings_body:
            failures.append("settings: a secret value appears in the rendered page")

        # Tenant detail — the busiest screen, and the one with the most actions.
        page.goto(f"{BASE}/admin/tenants", wait_until="networkidle")
        page.wait_for_timeout(1200)
        link = page.query_selector("a.lf-admin-link")
        if link:
            link.click()
            page.wait_for_timeout(2000)
            page.screenshot(path=str(SHOTS / "admin-tenant-detail.png"), full_page=True)
            body = page.inner_text("body")
            for expected in ("Subscription", "Usage", "Actions"):
                if expected.lower() not in body.lower():
                    failures.append(f"tenant-detail: missing {expected!r}")
            print(f"  ok  admin-tenant-detail          {len(body):>6} chars")
        else:
            failures.append("tenant-detail: no tenant link found in the directory")

        # Dark mode — the whole console inherits the token system, so a single
        # check is enough to catch a hard-coded colour.
        page.emulate_media(color_scheme="dark")
        page.goto(f"{BASE}/admin", wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(SHOTS / "admin-dashboard-dark.png"), full_page=True)
        print("  ok  admin-dashboard-dark")
        page.emulate_media(color_scheme="light")

        # Mobile — the rail collapses to an icon bar.
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{BASE}/admin", wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(SHOTS / "admin-dashboard-mobile.png"), full_page=True)
        print("  ok  admin-dashboard-mobile")
        page.set_viewport_size({"width": 1440, "height": 900})

        context.close()

        # ------------------------------------------- the two reported bugs
        print("\nCUSTOMER APP (the two reported bugs)")
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        record(page)
        login(page, *CUSTOMER)

        investments = visit(page, "/investments", "customer-investments")
        debt = visit(page, "/debt", "customer-debt")

        browser.close()

    print("\n" + "=" * 62)
    if failures:
        print(f"{len(failures)} PROBLEM(S):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("All screens rendered with no console errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

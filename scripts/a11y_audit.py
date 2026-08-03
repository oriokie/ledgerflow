"""Accessibility audit using axe-core against the running app.

Automated checks catch roughly a third of WCAG issues — they find contrast,
labels, roles and landmarks reliably, and cannot judge whether a heading
structure makes sense or whether an interaction is operable by keyboard. So a
clean run here is a floor, not a certificate.
"""
from __future__ import annotations
import json, os, sys, urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
AXE = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"

# `/dashboard` was in this list and is not a route — the dashboard is the index
# route at `/`. Every run since therefore audited the 404 page and reported it
# clean, which is worse than not auditing it: it produced a green tick for a
# screen nobody had checked. `assert_rendered` below is the guard against the
# same thing happening the next time a route moves.
PAGES_CUSTOMER = ["/", "/activity", "/accounts", "/plan", "/income", "/investments",
                  "/debt", "/goals", "/insights", "/reports", "/settings"]
PAGES_ADMIN = ["/admin", "/admin/tenants", "/admin/billing", "/admin/invoices",
               "/admin/dunning", "/admin/coupons", "/admin/plans", "/admin/analytics",
               "/admin/settings", "/admin/health", "/admin/audit", "/admin/staff"]

def login(page, email, pw):
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill('input[type="email"]', email); page.fill('input[type="password"]', pw)
    page.click('button[type="submit"]'); page.wait_for_timeout(3000)

def assert_rendered(page, path):
    """Fail loudly if the route did not render the screen it names.

    A clean axe run on a 404 or a login redirect looks identical to a clean run
    on the real page. This is the difference between the two.
    """
    state = page.evaluate("""() => ({
        status: !!document.querySelector('.lf-status-body, .lf-status-page'),
        path: location.pathname,
    })""")
    if state["status"]:
        raise RuntimeError(f"{path} rendered the status/404 page — route does not exist")
    # Signed-out is a *route*, not a password field. Keying off `input[type=password]`
    # failed /admin/settings, which legitimately contains credential inputs.
    if state["path"].rstrip("/") in ("/login", "/register"):
        raise RuntimeError(f"{path} bounced to sign-in — session was not established")
    # A section index redirecting to its own default child (/settings ->
    # /settings/profile) is the route working, not a failure. Landing somewhere
    # outside the requested subtree still is.
    landed, asked = state["path"].rstrip("/"), path.rstrip("/")
    if landed != asked and not landed.startswith(f"{asked}/"):
        raise RuntimeError(f"{path} redirected to {state['path']}")


def audit(page, path, axe_src):
    page.goto(f"{BASE}{path}", wait_until="networkidle")
    page.wait_for_timeout(2500)
    assert_rendered(page, path)
    page.add_script_tag(content=axe_src)
    res = page.evaluate("""async () => {
        const r = await axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}});
        return r.violations.map(v => ({id:v.id, impact:v.impact, help:v.help, n:v.nodes.length,
                                       sample:(v.nodes[0]&&v.nodes[0].html||'').slice(0,120)}));
    }""")
    return res

def main():
    axe_src = urllib.request.urlopen(AXE, timeout=30).read().decode()
    findings = {}
    with sync_playwright() as p:
        # The hardcoded /opt/google/chrome path only exists on Linux CI, so this
        # script could not run on a developer machine at all — which is how it
        # drifted out of the verification loop. Fall back to the chromium
        # Playwright installs itself, the same build audit_routes.py uses.
        chrome = "/opt/google/chrome/chrome"
        b = p.chromium.launch(
            executable_path=chrome if os.path.exists(chrome) else None,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        for label, pages, creds in (
            ("customer", PAGES_CUSTOMER, ("amina@example.test","PlatformAdmin!2026")),
            ("admin", PAGES_ADMIN, ("admin@ledgerflow.test","PlatformAdmin!2026")),
        ):
            ctx = b.new_context(viewport={"width":1440,"height":900})
            page = ctx.new_page()
            login(page, *creds)
            for path in pages:
                try:
                    v = audit(page, path, axe_src)
                except Exception as exc:
                    v = [{"id":"AUDIT_ERROR","impact":"serious","help":str(exc)[:80],"n":0,"sample":""}]
                findings[path] = v
                total = sum(x["n"] for x in v)
                print(f"  {'OK ' if not v else 'HIT'} {path:24} {len(v)} rule(s), {total} node(s)")
            ctx.close()
        b.close()

    print("\n" + "="*66)
    agg = {}
    for path, vs in findings.items():
        for v in vs:
            k = (v["id"], v["impact"], v["help"])
            agg.setdefault(k, {"nodes":0,"pages":[]})
            agg[k]["nodes"] += v["n"]; agg[k]["pages"].append(path)
    if not agg:
        print("No WCAG 2.1 A/AA violations detected by axe-core.")
        return 0
    order = {"critical":0,"serious":1,"moderate":2,"minor":3}
    for (rid, impact, help_), d in sorted(agg.items(), key=lambda kv: order.get(kv[0][1],9)):
        print(f"\n[{impact}] {rid} — {help_}")
        print(f"   {d['nodes']} node(s) across {len(d['pages'])} page(s): {', '.join(d['pages'][:5])}")
    json.dump(findings, open("/tmp/a11y.json","w"), indent=1)
    return 0

if __name__ == "__main__":
    sys.exit(main())

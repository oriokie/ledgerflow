/* UI inspection: drives the real app (Django API + built frontend) with the
 * system Chromium, walks the core journeys, asserts key UI contracts, and
 * captures screenshots for visual review. Run: node ui-check.mjs */

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = "http://localhost:4173";
const SHOTS = "/tmp/ui-shots";
mkdirSync(SHOTS, { recursive: true });

const email = `ui.check+${Date.now()}@example.com`;
const password = "PlaywrightPass12!";
const results = [];
const ok = (name, cond, extra = "") => {
  results.push(`${cond ? "PASS" : "FAIL"}  ${name}${extra ? ` — ${extra}` : ""}`);
  if (!cond) process.exitCode = 1;
};

const browser = await chromium.launch({
  executablePath: "/opt/google/chrome/chrome",
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

try {
  // ---------- Desktop: login page with quote panel ----------
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(`${BASE}/login`);
  await page.waitForSelector(".lf-quote-text");
  ok("login: quote panel renders a quote", !!(await page.textContent(".lf-quote-text")));
  ok("login: quote author attributed", (await page.textContent(".lf-quote-author"))?.includes("—"));
  ok("login: split panel visible", await page.isVisible(".lf-auth-panel"));
  ok("login: form heading", await page.isVisible("h1:has-text('Log in')"));
  ok("login: forgot-password link", await page.isVisible("a[href='/forgot-password']"));
  await page.screenshot({ path: `${SHOTS}/01-login-desktop.png` });

  // ---------- Register → workspace → dashboard onboarding ----------
  await page.goto(`${BASE}/register`);
  await page.fill("input[autocomplete='given-name']", "Ada");
  await page.fill("input[autocomplete='family-name']", "Lovelace");
  await page.fill("input[type='email']", email);
  await page.fill("input[autocomplete='new-password']", password);
  await page.screenshot({ path: `${SHOTS}/02-register.png` });
  await page.click("button[type='submit']");
  await page.waitForURL("**/workspaces", { timeout: 15000 });
  ok("register: lands on workspace picker", page.url().includes("/workspaces"));

  await page.fill("input[placeholder*='Personal']", "Playwright Home");
  await page.screenshot({ path: `${SHOTS}/03-workspace-create.png` });
  await page.click("button[type='submit']");
  await page.waitForSelector(".lf-onboard", { timeout: 20000 });
  ok("dashboard: Getting Started checklist for a fresh workspace", await page.isVisible(".lf-onboard"));
  ok("dashboard: step CTA points at accounts", await page.isVisible(".lf-onboard a[href='/accounts']"));
  await page.screenshot({ path: `${SHOTS}/04-dashboard-onboarding.png`, fullPage: true });

  // ---------- Add an account, then a transaction (seeded categories) ----------
  await page.click(".lf-onboard a[href='/accounts']");
  await page.waitForURL("**/accounts");
  await page.click("button:has-text('New account')");
  await page.waitForSelector("dialog[open]");
  await page.fill("dialog[open] input[name='name']", "Checking");
  await page.screenshot({ path: `${SHOTS}/05-accounts-create.png` });
  await page.click("dialog[open] button:has-text('Create account')");
  await page.waitForSelector(".lf-modal[open]", { state: "detached", timeout: 15000 }).catch(() => {});
  await page.waitForSelector("text=Checking", { timeout: 15000 });
  ok("accounts: created and listed", await page.isVisible("text=Checking"));

  await page.goto(`${BASE}/transactions?add=1`);
  await page.waitForSelector("form select");
  const categoryOptions = await page.$$eval("form select:nth-of-type(1) option", (o) => o.length);
  ok("transactions: add form opens via ?add=1 with seeded data", categoryOptions > 0);
  await page.screenshot({ path: `${SHOTS}/06-add-transaction.png` });

  // ---------- Insights (unmetered → AI on) ----------
  await page.goto(`${BASE}/insights`);
  await page.waitForSelector(".lf-insights-greeting-title", { timeout: 15000 });
  ok("insights: conversational check-in", await page.isVisible("text=Your money check-in"));
  await page.screenshot({ path: `${SHOTS}/07-insights.png`, fullPage: true });

  // ---------- Billing ----------
  await page.goto(`${BASE}/billing`);
  await page.waitForSelector("text=Billing & plans");
  await page.screenshot({ path: `${SHOTS}/08-billing.png`, fullPage: true });

  // ---------- Settings (grouped nav) ----------
  await page.goto(`${BASE}/settings/workspace`);
  await page.waitForSelector(".lf-settings-nav");
  ok("settings: grouped nav + data & privacy", await page.isVisible("text=Data & privacy"));
  await page.screenshot({ path: `${SHOTS}/09-settings-workspace.png`, fullPage: true });

  // ---------- Appearance customization ----------
  await page.goto(`${BASE}/settings/preferences`);
  await page.waitForSelector(".lf-accent-swatches");
  await page.click("[role='radio'][aria-label='Verdant']");
  ok("appearance: accent applies instantly",
    (await page.getAttribute("html", "data-accent")) === "verdant");
  await page.click("label:has-text('Compact')");
  ok("appearance: compact density applies",
    (await page.getAttribute("html", "data-density")) === "compact");
  await page.screenshot({ path: `${SHOTS}/13-preferences-appearance.png` });
  await page.reload();
  await page.waitForSelector(".lf-accent-swatches");
  ok("appearance: accent + density persist across reload",
    (await page.getAttribute("html", "data-accent")) === "verdant" &&
    (await page.getAttribute("html", "data-density")) === "compact");
  await page.goto(`${BASE}/`);
  await page.waitForSelector(".lf-dash-greeting");
  await page.screenshot({ path: `${SHOTS}/14-dashboard-verdant-compact.png`, fullPage: true });
  // reset for the remaining steps
  await page.goto(`${BASE}/settings/preferences`);
  await page.click("[role='radio'][aria-label='Iris']");
  await page.click("label:has-text('Comfortable')");

  // ---------- Logout journey ----------
  await page.click(".lf-topbar button[aria-haspopup='menu'], .lf-topbar [aria-label*='profile' i], .lf-topbar [aria-label*='account' i]").catch(() => {});
  // Fallback: find the profile menu trigger generically
  if (!(await page.isVisible("[role='menuitem']:has-text('Log out')"))) {
    const triggers = await page.$$(".lf-topbar button");
    for (const t of triggers.reverse()) {
      await t.click().catch(() => {});
      if (await page.isVisible("[role='menuitem']:has-text('Log out')")) break;
    }
  }
  await page.click("[role='menuitem']:has-text('Log out')");
  await page.waitForURL("**/logged-out", { timeout: 15000 });
  await page.waitForSelector(".lf-quote-text");
  ok("logout: lands on farewell page with quote panel", await page.isVisible("h1:has-text(\"You're signed out\")"));
  await page.screenshot({ path: `${SHOTS}/10-logged-out.png` });

  // ---------- Mobile: login + tab bar ----------
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(`${BASE}/login`);
  await mobile.waitForSelector(".lf-auth-mobile-brand");
  ok("mobile login: panel hidden, brand shown", !(await mobile.isVisible(".lf-auth-panel")));
  await mobile.screenshot({ path: `${SHOTS}/11-login-mobile.png` });

  await mobile.fill("input[type='email']", email);
  await mobile.fill("input[autocomplete='current-password']", password);
  await mobile.click("button[type='submit']");
  await mobile.waitForSelector(".lf-tabbar", { timeout: 20000 });
  ok("mobile app: bottom tab bar present", await mobile.isVisible(".lf-tabbar"));
  await mobile.screenshot({ path: `${SHOTS}/12-dashboard-mobile.png`, fullPage: true });
  // ---------- Dark mode ----------
  const dark = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: "dark" });
  await dark.goto(`${BASE}/login`);
  await dark.waitForSelector(".lf-quote-text");
  ok("dark: system preference resolves to dark theme",
    (await dark.getAttribute("html", "data-theme")) === "dark");
  await dark.screenshot({ path: `${SHOTS}/15-login-dark.png` });
  await dark.fill("input[type='email']", email);
  await dark.fill("input[autocomplete='current-password']", password);
  await dark.click("button[type='submit']");
  await dark.waitForSelector(".lf-dash-greeting", { timeout: 20000 });
  await dark.screenshot({ path: `${SHOTS}/16-dashboard-dark.png`, fullPage: true });
  ok("dark: dashboard renders under dark theme", (await dark.getAttribute("html", "data-theme")) === "dark");

  // ---------- Tablet ----------
  const tablet = await browser.newPage({ viewport: { width: 820, height: 1180 } });
  await tablet.goto(`${BASE}/login`);
  await tablet.fill("input[type='email']", email);
  await tablet.fill("input[autocomplete='current-password']", password);
  await tablet.click("button[type='submit']");
  await tablet.waitForSelector(".lf-dash-greeting", { timeout: 20000 });
  await tablet.screenshot({ path: `${SHOTS}/17-dashboard-tablet.png`, fullPage: true });
  ok("tablet: dashboard renders at 820px", true);

  // ---------- Quote rotation (live timing) ----------
  const rot = await browser.newPage({ viewport: { width: 1200, height: 800 } });
  await rot.goto(`${BASE}/login`);
  await rot.waitForSelector(".lf-quote-text");
  const firstQuote = await rot.textContent(".lf-quote-text");
  await rot.waitForTimeout(8700); // one rotation interval + fade
  const secondQuote = await rot.textContent(".lf-quote-text");
  ok("quotes: rotate on the login panel over time", firstQuote !== secondQuote,
    "changed after ~8.7s");
} finally {
  await browser.close();
}

console.log("\n===== UI CHECK RESULTS =====");
for (const r of results) console.log(r);
console.log(`Screenshots in ${SHOTS}`);

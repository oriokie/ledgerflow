import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
const BASE = "http://localhost:4173";
const SHOTS = "/tmp/ui-shots"; mkdirSync(SHOTS, { recursive: true });
const email = `fix.check+${Date.now()}@example.com`, password = "PlaywrightPass12!";
const out = []; const ok = (n, c, x = "") => { out.push(`${c ? "PASS" : "FAIL"}  ${n}${x ? ` — ${x}` : ""}`); if (!c) process.exitCode = 1; };
const browser = await chromium.launch({ executablePath: "/opt/google/chrome/chrome", args: ["--no-sandbox", "--disable-dev-shm-usage"] });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(`${BASE}/register`);
  await page.fill("input[autocomplete='given-name']", "Fix");
  await page.fill("input[autocomplete='family-name']", "Check");
  await page.fill("input[type='email']", email);
  await page.fill("input[autocomplete='new-password']", password);
  await page.click("button[type='submit']");
  await page.waitForURL("**/workspaces", { timeout: 20000 });
  await page.fill("input[placeholder*='Personal']", "FX Home");
  await page.click("button[type='submit']");
  await page.waitForSelector(".lf-onboard", { timeout: 20000 });

  // #2 + #5: modal centering & currency dropdown
  await page.goto(`${BASE}/accounts`);
  await page.click("button:has-text('New account')");
  await page.waitForSelector("dialog[open]");
  const box = await page.locator("dialog[open]").boundingBox();
  const vw = 1440, vh = 900;
  const dxCenter = Math.abs((box.x + box.width / 2) - vw / 2);
  const dyCenter = Math.abs((box.y + box.height / 2) - vh / 2);
  ok("modal horizontally centered", dxCenter < 12, `off by ${Math.round(dxCenter)}px`);
  ok("modal vertically centered", dyCenter < 24, `off by ${Math.round(dyCenter)}px`);
  const isSelect = await page.locator("dialog[open] select").count();
  ok("currency is a lookup (select), not free text", isSelect >= 2);
  const opts = await page.locator("dialog[open] select").last().locator("option").count();
  ok("currency catalog populated", opts > 20, `${opts} options`);
  await page.screenshot({ path: `${SHOTS}/18-modal-centered-currency.png` });

  // #1: create EUR account then post a transaction against a base-currency category
  await page.locator("dialog[open] input[name='name']").fill("EU Checking");
  await page.locator("dialog[open] select").last().selectOption("EUR");
  await page.click("dialog[open] button:has-text('Create account')");
  await page.waitForSelector("text=EU Checking", { timeout: 20000 });
  ok("#3 account creation succeeds (no 500)", await page.isVisible("text=EU Checking"));

  await page.goto(`${BASE}/transactions?add=1`);
  await page.waitForSelector("form select");
  await page.fill("form input[name='amount']", "42.50").catch(() => {});
  const amt = await page.locator("form input[type='text'], form input[inputmode='decimal'], form input[type='number']").first();
  await amt.fill("42.50");
  await page.locator("form select").first().selectOption({ index: 1 }).catch(() => {});
  await page.click("form button[type='submit']");
  await page.waitForTimeout(2500);
  const err = await page.locator("text=cross-currency").count();
  ok("#1 no cross-currency error posting to EUR account", err === 0);
  await page.screenshot({ path: `${SHOTS}/19-eur-transaction.png`, fullPage: true });

  // #4: base currency editable
  await page.goto(`${BASE}/settings/workspace`);
  await page.waitForSelector("select[aria-label='Base currency']");
  await page.selectOption("select[aria-label='Base currency']", "EUR");
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/settings/workspace`);
  await page.waitForSelector("select[aria-label='Base currency']");
  const val = await page.inputValue("select[aria-label='Base currency']");
  ok("#4 base currency is editable and persists", val === "EUR", `now ${val}`);
  await page.screenshot({ path: `${SHOTS}/20-base-currency.png` });
} finally { await browser.close(); }
console.log("\n===== FIX CHECK =====");
for (const r of out) console.log(r);

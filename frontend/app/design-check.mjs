/* Visual review of the design system. Renders design-check.html — which loads
 * the real stylesheets in the real import order — across themes and viewports
 * and writes screenshots for review. No API or auth required, so a CSS change
 * can be eyeballed in seconds.
 *
 * Run: node design-check.mjs   (shots land in /tmp/lf-design-shots)
 */

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGE = `file://${resolve(HERE, "design-check.html")}`;
const SHOTS = "/tmp/lf-design-shots";
mkdirSync(SHOTS, { recursive: true });

/** name, data-theme, width, height */
const MATRIX = [
  ["light-desktop", null, 1440, 900],
  ["dark-desktop", "dark", 1440, 900],
  ["light-ultrawide", null, 1920, 1080],
  ["light-tablet", null, 834, 1112],
  ["light-mobile", null, 390, 844],
  ["dark-mobile", "dark", 390, 844],
];

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH ?? "/opt/google/chrome/chrome",
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

try {
  for (const [name, theme, width, height] of MATRIX) {
    const page = await browser.newPage({ viewport: { width, height } });
    await page.goto(PAGE);
    if (theme) {
      await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
    }
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });

    // The dialog is rendered inline and opened here so the modal — including
    // its pinned footer and mobile bottom-sheet behavior — is captured too.
    await page.evaluate(() => document.getElementById("demo-modal")?.showModal());
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${SHOTS}/${name}-modal.png` });
    await page.close();
    console.log(`captured ${name}`);
  }
  console.log(`\nScreenshots written to ${SHOTS}`);
} finally {
  await browser.close();
}

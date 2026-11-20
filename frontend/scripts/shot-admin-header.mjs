// Captures the signed-in control-room header at desktop and mobile widths.
// Usage: node scripts/shot-admin-header.mjs  (WEB_URL, EMAIL, PASSWORD, SHOTS_DIR, CHROMIUM_PATH optional)
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const WEB = process.env.WEB_URL ?? "http://localhost:3000";
const EMAIL = process.env.EMAIL ?? "chairman@sjcjos-alumni.org";
const PASSWORD = process.env.PASSWORD ?? "ChangeMe!2026";
const OUT = process.env.SHOTS_DIR ?? "../screenshots/admin-header";
const CHROME =
  process.env.CHROMIUM_PATH ??
  path.join(
    os.homedir(),
    "AppData",
    "Local",
    "ms-playwright",
    "chromium-1255",
    "chrome-win64",
    "chrome.exe"
  );

await fs.mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ executablePath: CHROME });

for (const [width, height, tag] of [
  [1440, 900, "1440"],
  [390, 844, "390"],
]) {
  const context = await browser.newContext({ viewport: { width, height } });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(String(error)));

  await page.goto(`${WEB}/admin/login`, { waitUntil: "networkidle" });
  await page.fill("#email", EMAIL);
  await page.fill("#password", PASSWORD);
  await page.click("button[type=submit], button.btn-primary");
  await page.waitForURL("**/admin", { timeout: 20000 });
  await page.waitForSelector("header nav", { timeout: 20000 });
  await page.waitForTimeout(800);

  await page.locator("header").screenshot({ path: `${OUT}/header-${tag}.png` });
  await page.screenshot({ path: `${OUT}/page-${tag}.png` });

  const metrics = await page.evaluate(() => {
    const header = document.querySelector("header");
    const nav = header?.querySelector("nav");
    const rect = (el) => (el ? el.getBoundingClientRect() : null);
    const h = rect(header);
    const n = rect(nav);
    const tabs = [...(nav?.querySelectorAll("a") ?? [])].map((a) => ({
      label: a.textContent?.trim(),
      height: Math.round(a.getBoundingClientRect().height),
      width: Math.round(a.getBoundingClientRect().width),
      current: a.getAttribute("aria-current"),
    }));
    return {
      headerHeight: h && Math.round(h.height),
      navHeight: n && Math.round(n.height),
      scrollWidth: nav?.scrollWidth,
      clientWidth: nav?.clientWidth,
      tabs,
    };
  });

  console.log(tag, JSON.stringify(metrics));
  console.log(tag, "console errors:", errors.length ? errors : "none");
  await context.close();
}

await browser.close();

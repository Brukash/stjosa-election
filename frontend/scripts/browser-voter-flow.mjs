#!/usr/bin/env node
/**
 * Voter-flow browser test: accredit a Voter ID, mark and submit a ballot, open
 * the receipt.
 *
 * It drives the real pages against a throwaway API and frontend, so a break in
 * the client-side credential blinding, the ballot state machine or a receipt
 * route fails here instead of after the election opens.
 *
 * Run it through backend/scripts/browser_e2e.sh, which boots the throwaway
 * stack and points this script at it. Environment:
 *   FRONTEND_URL   default http://localhost:3010
 *   VOTER_ID       default SJC/AL/2004/001 (a seeded, unvoted voter)
 *   SHOTS_DIR      default ../screenshots/browser-e2e
 *   CHROMIUM_PATH  optional explicit browser binary
 */
import { chromium } from "playwright-core";
import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = (process.env.FRONTEND_URL ?? "http://localhost:3010").replace(/\/$/, "");
const VOTER_ID = process.env.VOTER_ID ?? "SJC/AL/2004/001";
const SHOTS = resolve(process.env.SHOTS_DIR ?? join(HERE, "..", "..", "screenshots", "browser-e2e"));
const BROWSER_CACHE =
  process.env.PLAYWRIGHT_BROWSERS_PATH ??
  join(process.env.LOCALAPPDATA ?? process.env.HOME ?? "", "ms-playwright");

const results = [];
const browserErrors = [];
const failedRequests = [];

function check(label, passed, detail = "") {
  results.push({ label, passed, detail });
  console.log(`  ${passed ? "PASS" : "FAIL"}  ${label}${detail && !passed ? ` — ${detail}` : ""}`);
  return passed;
}

/** Find an already-installed Chromium: playwright-core ships no browser. */
function findChromium() {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH;
  const layouts = [
    ["chrome-win64", "chrome.exe"],
    ["chrome-win", "chrome.exe"],
    ["chrome-linux", "chrome"],
    ["chrome-mac", "Chromium.app/Contents/MacOS/Chromium"],
  ];
  const found = [];
  try {
    for (const entry of readdirSync(BROWSER_CACHE)) {
      if (!entry.startsWith("chromium-")) continue;
      for (const [folder, binary] of layouts) {
        const candidate = join(BROWSER_CACHE, entry, folder, binary);
        if (existsSync(candidate)) found.push(candidate);
      }
    }
  } catch {
    return null;
  }
  return found.sort().pop() ?? null;
}

function overflow(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    return root.scrollWidth - root.clientWidth;
  });
}

const READ_ONLY = process.env.READ_ONLY === "1";

const PUBLIC_PAGES = [
  { path: "/", name: "home" },
  { path: "/accredit", name: "accredit" },
  { path: "/vote", name: "vote" },
  { path: "/results", name: "results" },
  { path: "/verify", name: "verify" },
  { path: "/commitments", name: "commitments" },
];

/**
 * Read-only pass over the public pages: useful against a live site, where a
 * test must never cast a real ballot. It checks that each page responds, has a
 * heading, shows no error message, does not scroll sideways at 390px, and
 * produces no console errors or failed requests.
 */
async function readOnlyPass(page, shot) {
  console.log(`Read-only page check on ${FRONTEND}`);
  for (const entry of PUBLIC_PAGES) {
    browserErrors.length = 0;
    failedRequests.length = 0;
    const response = await page.goto(`${FRONTEND}${entry.path}`, {
      waitUntil: "domcontentloaded",
      timeout: 60000,
    });
    check(
      `${entry.name}: page responds`,
      Boolean(response && response.status() < 400),
      `HTTP ${response?.status()}`
    );
    try {
      await page.waitForLoadState("networkidle", { timeout: 15000 });
    } catch {
      // a page that keeps a request open is not a failure by itself
    }
    await page.waitForTimeout(800);
    const heading = (await page
      .locator("h1")
      .first()
      .innerText()
      .catch(() => ""))?.trim();
    check(`${entry.name}: renders a heading`, Boolean(heading), `got "${heading}"`);
    const errorBoxes = await page.locator('[class*="border-clay"]').allInnerTexts();
    check(
      `${entry.name}: no error message`,
      errorBoxes.length === 0,
      errorBoxes.join(" | ").slice(0, 160)
    );
    await shot(`public-${entry.name}`);

    await page.setViewportSize({ width: 390, height: 844 });
    const narrow = await overflow(page);
    check(`${entry.name}: fits 390px without sideways scroll`, narrow <= 0, `${narrow}px`);
    await page.setViewportSize({ width: 1440, height: 900 });

    check(
      `${entry.name}: no console errors`,
      browserErrors.length === 0,
      browserErrors.slice(0, 2).join(" | ")
    );
    check(
      `${entry.name}: no failed requests`,
      failedRequests.length === 0,
      failedRequests.slice(0, 2).join(" | ")
    );
  }
}

async function main() {
  const executablePath = findChromium();
  if (!executablePath) {
    console.error(`No installed Chromium found under ${BROWSER_CACHE}.`);
    process.exit(2);
  }
  mkdirSync(SHOTS, { recursive: true });

  const browser = await chromium.launch({ executablePath, headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);

  page.on("pageerror", (error) => browserErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(`console: ${message.text()}`);
  });
  page.on("requestfailed", (request) => {
    const reason = request.failure()?.errorText ?? "failed";
    if (reason.includes("ERR_ABORTED")) return; // navigation cancels in-flight fetches
    failedRequests.push(`${request.method()} ${request.url()} — ${reason}`);
  });

  const shot = async (name) => page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: false });

  if (READ_ONLY) {
    await readOnlyPass(page, shot);
    await browser.close();
    return;
  }

  // ── 1. accreditation ───────────────────────────────────────────────────────
  await page.goto(`${FRONTEND}/accredit`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.getByLabel("Voter ID").waitFor({ state: "visible" });
  check("accreditation page loads with a Voter ID field", true);

  await page.getByLabel("Voter ID").fill(VOTER_ID);
  await shot("01-accredit");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByText(/^Welcome, /).waitFor({ state: "visible" });
  check("Voter ID is accepted and names the voter", true);

  await page.getByRole("button", { name: "Get my ballot" }).click();
  await page.getByText("Your ballot is unlocked in this browser.").waitFor({ state: "visible" });
  check("browser creates and stores the voting credential", true);
  await shot("02-credential");

  // ── 2. ballot ──────────────────────────────────────────────────────────────
  await page.getByRole("link", { name: "Open my ballot" }).click();
  await page.waitForURL(/\/vote/, { timeout: 60000 });
  const sections = page.locator("section[aria-labelledby^='pos-']");
  await sections.first().waitFor({ state: "visible" });
  const positionCount = await sections.count();
  check("ballot renders every position", positionCount > 0, `found ${positionCount}`);

  const chosenNames = [];
  for (let index = 0; index < positionCount; index += 1) {
    const section = sections.nth(index);
    const firstOption = section.locator("label.option-row").first();
    const name =
      (await firstOption.locator("span.block").first().textContent())?.trim() ?? `option ${index + 1}`;
    chosenNames.push(name);
    await firstOption.click();
  }
  const progress = page.getByText(`${positionCount} of ${positionCount} chosen`);
  await progress.waitFor({ state: "visible" });
  check("every position can be marked", true);
  await shot("03-ballot-marked");

  // ── 3. review and submit ───────────────────────────────────────────────────
  await page.getByRole("button", { name: "Review" }).click();
  await page.getByText("This is your ballot").waitFor({ state: "visible" });
  const reviewText = await page.locator("dl").first().innerText();
  const reviewMatches = chosenNames.every((name) => reviewText.includes(name));
  check("review shows exactly the marked choices", reviewMatches, reviewText.slice(0, 160));
  await shot("04-review");

  await page.getByRole("button", { name: "Submit my ballot" }).click();
  await page.getByText("Your ballot is sealed").waitFor({ state: "visible" });
  check("ballot is sealed before casting", true);

  await page.getByRole("button", { name: "Cast my ballot" }).click();
  await page.getByText("Your vote is in.").waitFor({ state: "visible" });
  check("ballot is accepted", true);

  const reference = (await page.locator("dd.tabular").nth(1).innerText()).trim();
  const receiptNumber = (await page.locator("dd.tabular").first().innerText()).trim();
  check(
    "receipt reference is issued",
    /^SJCJ[-0-9A-Z]+$/.test(reference),
    `reference "${reference}"`
  );
  await shot("05-accepted");

  // ── 4. receipt, through the links the voter is actually given ──────────────
  await page.getByRole("link", { name: "Check my ballot now" }).click();
  await page.waitForURL(/\/verify\?ref=/, { timeout: 60000 });
  await page.getByText("Ballot accepted and on record").waitFor({ state: "visible" });
  check("verification page confirms the ballot is on record", true);
  await shot("06-verify");

  await page.getByRole("link", { name: "Open receipt" }).click();
  await page.waitForURL(/\/receipt\?ref=/, { timeout: 60000 });
  await page.getByText("Your ballot receipt").waitFor({ state: "visible" });
  const receiptHeading = (await page.locator("p.font-display").first().innerText()).trim();
  check("receipt page opens the issued receipt", receiptHeading === receiptNumber, receiptHeading);
  check(
    "receipt shows the ballot fingerprint",
    (await page.getByText("Ballot fingerprint").count()) === 1
  );
  const errorBoxes = await page.locator('[class*="border-clay"]').allInnerTexts();
  check(
    "receipt page has no error message",
    errorBoxes.length === 0,
    errorBoxes.join(" | ").slice(0, 200)
  );
  await shot("07-receipt");

  // ── 5. narrow screen ───────────────────────────────────────────────────────
  await page.setViewportSize({ width: 390, height: 844 });
  const receiptOverflow = await overflow(page);
  check("receipt fits 390px without sideways scroll", receiptOverflow <= 0, `${receiptOverflow}px`);
  await shot("08-receipt-390");

  await page.goto(`${FRONTEND}/vote`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  const voteOverflow = await overflow(page);
  check("ballot page fits 390px without sideways scroll", voteOverflow <= 0, `${voteOverflow}px`);

  check("no browser console errors", browserErrors.length === 0, browserErrors.slice(0, 3).join(" | "));
  check("no failed network requests", failedRequests.length === 0, failedRequests.slice(0, 3).join(" | "));

  await browser.close();
}

main()
  .then(() => {
    const failed = results.filter((result) => !result.passed);
    console.log("\n==================================================");
    if (failed.length === 0) {
      console.log(`VOTER FLOW PASSED: ${results.length} checks`);
      console.log(`screenshots: ${SHOTS}`);
      console.log("==================================================");
      process.exit(0);
    }
    console.log(`VOTER FLOW FAILED: ${failed.length} of ${results.length} checks`);
    for (const failure of failed) console.log(`  - ${failure.label} ${failure.detail}`);
    if (browserErrors.length) console.log(`  console: ${browserErrors.slice(0, 5).join(" | ")}`);
    console.log(`screenshots: ${SHOTS}`);
    console.log("==================================================");
    process.exit(1);
  })
  .catch((error) => {
    console.error("\nVOTER FLOW CRASHED:", error?.message ?? error);
    if (browserErrors.length) console.error("console:", browserErrors.slice(0, 5).join(" | "));
    process.exit(1);
  });

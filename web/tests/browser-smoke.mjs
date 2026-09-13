import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.SMOKE_BASE_URL || "http://localhost:3100";
const artifacts = path.resolve(process.env.SMOKE_ARTIFACT_DIR || ".browser-results");
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.SMOKE_CHANNEL ? { channel: process.env.SMOKE_CHANNEL } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, acceptDownloads: true });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const passed = [];
async function check(name, action) {
  await action();
  passed.push(name);
  console.log("PASS " + name);
}
async function visit(route) {
  const response = await page.goto(base + route);
  await page.locator("main h1").first().waitFor();
  return response;
}
const scaleControl = () => page.locator(".toolbar .prefctl").filter({ hasText: "Show in" }).locator("select").first();
try {
  await check("Homepage source preview and exact ticker search", async () => {
    await visit("/");
    await page.getByRole("button", { name: /Net income.*FY 2023/i }).click();
    assert.match(await page.locator(".preview-evidence").innerText(), /Net income.*FY 2023/s);
    await page.screenshot({ path: path.join(artifacts, "home-desktop.png"), fullPage: true });
    await page.getByRole("combobox").fill("AAPL");
    await page.getByRole("combobox").press("Enter");
    await page.waitForURL("**/companies/320193");
    await page.getByRole("heading", { name: /^Apple Inc\./ }).waitFor();
  });
  await check("Statement evidence and Excel download", async () => {
    await visit("/companies/320193/statements");
    await page.getByRole("button", { name: /Total net sales.*FY2024.*Inspect evidence/i }).click();
    await page.locator("#statement-evidence").waitFor();
    assert.match(await page.locator("#statement-evidence").innerText(), /391,035,000,000/);
    assert.match(await page.locator("#statement-evidence").innerText(), /2024-11-01/);
    await page.screenshot({ path: path.join(artifacts, "statements-desktop.png"), fullPage: true });
    await page.getByRole("button", { name: /Export/i }).first().click();
    const dialog = page.getByRole("dialog", { name: "Export to Excel" });
    await dialog.waitFor();
    const downloadPromise = page.waitForEvent("download");
    await dialog.getByRole("button", { name: "Download Excel", exact: true }).click();
    const download = await downloadPromise;
    const workbook = path.join(artifacts, "AAPL-fixture-statements.xlsx");
    await download.saveAs(workbook);
    assert.equal((await readFile(workbook)).subarray(0, 2).toString(), "PK");
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
  });
  await check("Filing reader and text search", async () => {
    await page.locator("#statement-evidence").getByRole("link", { name: /Read filing/ }).first().click();
    await page.locator("iframe").waitFor();
    assert.ok((await page.frameLocator("iframe").locator("body").innerText()).length > 100);
    await visit("/companies/320193/search?q=repurchase");
    await page.locator(".research-results .result-snippet").first().waitFor();
    assert.match(await page.locator(".research-results .result-snippet").first().innerText(), /repurchase/i);
  });
  await check("Public coverage and anonymous administrator denial", async () => {
    await visit("/coverage");
    await page.getByRole("heading", { name: "Financial statements by fiscal year" }).waitFor();
    assert.ok(await page.locator("tbody tr").count() > 0);
    await page.goto(base + "/metrics");
    await page.getByText("Page not found", { exact: true }).waitFor();
    assert.equal(await page.getByRole("heading", { name: "How Disclosure is doing" }).count(), 0);
    assert.equal((await context.request.get(base + "/api/subscribe")).status(), 401);
  });
  await check("Magic link sign-in and persistent preferences", async () => {
    await visit("/signin");
    await page.locator("input[type=email]").fill("browser-" + Date.now() + "@example.com");
    await page.getByRole("button", { name: "Email me a link" }).click();
    await page.getByRole("link", { name: "open the link" }).click();
    await page.waitForURL(base + "/");
    await visit("/companies/320193/statements");
    await scaleControl().selectOption("thousands");
    await page.waitForFunction(() => document.querySelector(".toolbar .prefctl select")?.value === "thousands");
    await page.reload();
    await page.getByRole("tab", { name: /^Income statement$/i }).waitFor();
    assert.equal(await scaleControl().inputValue(), "thousands");
    await page.route("**/api/prefs", route => route.request().method() === "PUT" ? route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"Simulated save failure"}' }) : route.continue());
    await scaleControl().selectOption("billions");
    await page.getByRole("alert").filter({ hasText: /save/i }).first().waitFor();
    assert.equal(await scaleControl().inputValue(), "thousands");
    await page.unroute("**/api/prefs");
    await page.goto(base + "/metrics");
    await page.getByText("Page not found", { exact: true }).waitFor();
  });
  await check("Account watchlist and verified-email alert controls", async () => {
    await visit("/companies/320193");
    await page.getByRole("button", { name: "Follow company", exact: true }).click();
    await page.getByRole("button", { name: "Following", exact: true }).waitFor();
    await visit("/watchlist");
    await page.getByRole("button", { name: "Enable email alerts", exact: true }).click();
    await page.getByRole("button", { name: "Pause alerts", exact: true }).waitFor();
    assert.equal((await (await context.request.get(base + "/api/subscribe")).json()).subscribed, true);
    await page.getByRole("button", { name: "Pause alerts", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "Email alerts are paused." }).waitFor();
    assert.equal((await (await context.request.get(base + "/api/subscribe")).json()).subscribed, false);
    await page.screenshot({ path: path.join(artifacts, "watchlist-desktop.png"), fullPage: true });
  });
  await check("Mobile search and bounded page width", async () => {
    await page.setViewportSize({ width: 320, height: 844 });
    await visit("/");
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Homepage fits a 320px phone");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(artifacts, "home-mobile.png"), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.getByRole("combobox").fill("JPM");
    await page.getByRole("combobox").press("Enter");
    await page.waitForURL("**/companies/19617");
    await page.getByRole("heading", { name: /JPMorgan/ }).waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  });
  await check("Reduced motion and readable content without JavaScript", async () => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await visit("/");
    await page.locator(".research-section").scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.getAnimations().every(animation => animation.playState !== "running"));
    assert.equal(await page.locator(".research-section").evaluate(element => getComputedStyle(element).opacity), "1");
    await page.getByRole("button", { name: /Net income.*FY 2023/i }).click();
    assert.match(await page.locator(".preview-evidence").innerText(), /Net income.*FY 2023/s);
    const staticContext = await browser.newContext({ javaScriptEnabled: false });
    try {
      const staticPage = await staticContext.newPage();
      await staticPage.goto(base);
      for (const selector of [".landing-copy", ".feature-triptych", ".research-section", ".coverage-callout"]) {
        assert.ok(await staticPage.locator(selector).isVisible(), `${selector} requires no JavaScript to read`);
        assert.equal(await staticPage.locator(selector).evaluate(element => getComputedStyle(element).opacity), "1");
      }
      assert.ok(await staticPage.getByRole("link", { name: "Explore an example" }).isVisible());
    } finally {
      await staticContext.close();
    }
  });
  assert.deepEqual(errors, [], "Browser runtime exceptions");
  console.log(JSON.stringify({ passed: passed.length, scenarios: passed, runtimeErrors: errors }, null, 2));
} catch (error) {
  await page.screenshot({ path: path.join(artifacts, "failure.png"), fullPage: true }).catch(() => {});
  console.error("FAILED AT", page.url());
  throw error;
} finally {
  await browser.close();
}

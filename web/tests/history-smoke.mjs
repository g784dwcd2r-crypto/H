import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.SMOKE_BASE_URL || "http://localhost:3100";
const artifacts = path.resolve(".browser-results/history");
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.SMOKE_CHANNEL ? { channel: process.env.SMOKE_CHANNEL } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const errors = [];
page.on("pageerror", error => errors.push(error.message));
try {
  await page.goto(`${base}/research?q=repurchase&cik=320193`);
  await page.locator(".research-results li").first().waitFor();
  await page.getByRole("link", { name: "Read indexed text" }).first().click();
  await page.getByRole("region", { name: "Extracted filing text" }).waitFor();
  const currentPath = new URL(page.url()).pathname;
  const choice = page.locator("#before-version option:not([disabled])").first();
  const earlierVersion = await choice.getAttribute("value");
  assert.ok(earlierVersion?.startsWith("sha256:"));
  await page.getByLabel("Compare this version with").selectOption(earlierVersion);
  await page.getByRole("button", { name: "Compare captured text" }).click();
  const diff = page.getByLabel("Captured text comparison");
  await diff.waitFor();
  assert.match(await diff.innerText(), /Revenue was unchanged year over year/);
  assert.match(await diff.innerText(), /Revenue grew year over year/);
  assert.equal(new URL(page.url()).searchParams.get("before"), earlierVersion);
  await page.reload();
  await diff.waitFor();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(artifacts, "document-comparison.png"), fullPage: true });
  console.log("PASS Immutable document versions, exact text changes and reload persistence");

  await page.goto(`${base}${currentPath}?before=${encodeURIComponent("sha256:" + "0".repeat(64))}`);
  await page.getByRole("alert").filter({ hasText: "unavailable" }).waitFor();
  assert.equal(await page.getByLabel("Captured text comparison").count(), 0);
  await page.goto(`${base}${currentPath}?before=${encodeURIComponent(earlierVersion)}`);
  await page.setViewportSize({ width: 390, height: 844 });
  await diff.waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.getByRole("link", { name: "Clear comparison" }).click();
  await page.waitForURL(url => !url.searchParams.has("before"));
  assert.equal(new URL(page.url()).searchParams.has("before"), false);
  await page.getByRole("region", { name: "Extracted filing text" }).waitFor();
  assert.deepEqual(errors, []);
  console.log("PASS Missing-version state, mobile comparison and clear-view behavior");
} catch (error) {
  await page.screenshot({ path: path.join(artifacts, "failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally {
  await browser.close();
}

import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.ADMIN_SMOKE_BASE_URL || "http://localhost:3201";
const artifacts = path.resolve(process.env.ADMIN_SMOKE_ARTIFACT_DIR || ".browser-results/admin");
const mutationReason = `Synthetic browser suspension verification ${Date.now()}`;
const replacement = process.env.ADMIN_SMOKE_PASSWORD || "Synthetic operator phrase! 9876";
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.SMOKE_CHANNEL ? { channel: process.env.SMOKE_CHANNEL } : {}) });
const operator = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const ordinary = await browser.newContext();
const page = await operator.newPage();
const analyst = await ordinary.newPage();
page.setDefaultTimeout(20000);
const errors = [];
page.on("pageerror", error => errors.push(error.message));
async function check(name, fn) { await fn(); console.log("PASS " + name); }
async function navigate(name) { await page.getByRole("navigation", { name: "Administration sections" }).getByRole("button", { name, exact: true }).click(); await page.getByRole("heading", { name, exact: true, level: 1 }).waitFor(); }
async function review(reason) {
  const modal = page.getByRole("dialog");
  await modal.getByLabel("Operational reason").fill(reason);
  await modal.getByLabel("Re-enter administrator password").fill(replacement);
  await modal.getByRole("checkbox").check();
  await modal.getByRole("button", { name: "Confirm reviewed change" }).click();
}
try {
  await check("Ordinary account and forged headers cannot access control plane", async () => {
    await analyst.goto(base + "/signin");
    await analyst.locator("input[type=email]").fill("analyst-admin-smoke@example.test");
    await analyst.getByRole("button", { name: "Email me a link" }).click();
    await analyst.getByRole("link", { name: "open the link" }).click();
    await analyst.waitForURL(base + "/");
    assert.equal((await ordinary.request.get(base + "/api/platform-admin/users", { headers: { "X-Admin-Session": "disclosure.forged", "X-Role": "superadmin" } })).status(), 401);
    assert.equal((await ordinary.request.post(base + "/api/platform-admin/login", { headers: { Origin: "https://attacker.example" }, data: { username: "disclosure", password: "1234" } })).status(), 403);
    assert.equal((await ordinary.request.get(base + "/api/sessions")).status(), 200);
  });
  await check("Explicit local bootstrap forces a strong change and keeps tokens HttpOnly", async () => {
    await page.goto(base + "/admin");
    await page.getByLabel("Administrator password", { exact: true }).fill("1234");
    const loginResponse = page.waitForResponse(response => response.url().endsWith("/api/platform-admin/login"));
    await page.getByRole("button", { name: "Sign in to administration" }).click();
    assert.equal((await (await loginResponse).json()).token, undefined);
    await page.getByRole("heading", { name: "Choose your own password." }).waitFor();
    assert.equal((await operator.request.get(base + "/api/platform-admin/users")).status(), 403);
    await page.getByLabel("Initial or current password").fill("1234");
    await page.getByLabel("New password", { exact: true }).fill(replacement);
    await page.getByLabel("Repeat new password").fill(replacement);
    await page.getByRole("button", { name: "Change password and continue" }).click();
    await page.getByRole("heading", { name: "Overview", exact: true, level: 1 }).waitFor();
    await page.getByText("Synthetic", { exact: true }).count();
    const cookie = (await operator.cookies()).find(row => row.name === "disclosure_admin_dev");
    assert.ok(cookie?.httpOnly && cookie.sameSite === "Strict");
    assert.ok(!(await page.evaluate(() => document.cookie)).includes("disclosure_admin_dev"));
    await page.getByRole("heading", { name: "Recent ingestion runs" }).waitFor();
    await page.screenshot({ path: path.join(artifacts, "admin-overview.png"), fullPage: true });
  });
  let uid;
  await check("Reviewed suspension handles failure and then revokes real user access", async () => {
    await navigate("Accounts");
    await page.getByLabel("Search Accounts").fill("analyst-admin-smoke");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await page.getByRole("button", { name: "analyst-admin-smoke@example.test", exact: true }).click();
    const account = page.getByRole("article", { name: "Account details" });
    await account.getByRole("button", { name: "Review suspension" }).click();
    const statusRoute = /\/api\/platform-admin\/users\/[a-z0-9]+\/status$/;
    await page.route(statusRoute, route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "Simulated storage failure; no status change." }) }));
    await review(mutationReason);
    await page.getByRole("dialog").getByRole("alert").filter({ hasText: "Simulated storage failure" }).waitFor();
    assert.equal((await ordinary.request.get(base + "/api/sessions")).status(), 200);
    await page.unroute(statusRoute);
    await review(mutationReason);
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    await page.getByRole("status").filter({ hasText: "Suspend account completed" }).waitFor();
    const response = await operator.request.get(base + "/api/platform-admin/users?q=analyst-admin-smoke");
    const user = (await response.json()).items[0];
    uid = user.id;
    assert.equal(user.status, "suspended");
    assert.equal((await ordinary.request.get(base + "/api/sessions")).status(), 401);
    await account.getByRole("button", { name: "Review account restoration" }).waitFor();
    await page.screenshot({ path: path.join(artifacts, "admin-account-suspended.png"), fullPage: true });
  });
  await check("Backend audit records the actual reviewed mutation", async () => {
    await navigate("Audit history");
    await page.getByLabel("Search Audit history").fill(uid);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    const auditRow = page.getByRole("row").filter({ hasText: mutationReason });
    await auditRow.getByText("account.status", { exact: true }).waitFor();
    await auditRow.getByText(mutationReason, { exact: true }).click();
    assert.match(await auditRow.locator("pre").innerText(), /"status": "suspended"/);
    assert.ok(!(await page.locator("body").innerText()).includes(replacement));
    await page.screenshot({ path: path.join(artifacts, "admin-audit.png"), fullPage: true });
  });
  await check("Source and incomplete coverage states remain honest; mobile stays usable", async () => {
    await navigate("Source readiness");
    await page.getByRole("heading", { name: "Broker and independent research", exact: true }).waitFor();
    assert.ok((await page.getByText("provider required", { exact: true }).count()) > 0);
    await navigate("Research index");
    await page.getByRole("heading", { name: "Incomplete filing inventories", exact: true }).waitFor();
    await navigate("Research jobs");
    await page.getByRole("heading", { name: "Job controls unavailable" }).waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await navigate("Accounts");
    await page.getByLabel("Search Accounts").waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.screenshot({ path: path.join(artifacts, "admin-mobile.png"), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check("Failed logout preserves session; successful logout revokes it server-side", async () => {
    await page.route("**/api/platform-admin/logout", route => route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"Simulated logout failure"}' }));
    await page.getByRole("button", { name: "Sign out operator" }).click();
    await page.getByRole("alert").filter({ hasText: "Simulated logout failure" }).waitFor();
    assert.equal((await operator.request.get(base + "/api/platform-admin/session")).status(), 200);
    await page.unroute("**/api/platform-admin/logout");
    await page.getByRole("button", { name: "Sign out operator" }).click();
    await page.getByRole("heading", { name: "Manage the platform." }).waitFor();
    assert.equal((await operator.request.get(base + "/api/platform-admin/session")).status(), 401);
    await page.getByLabel("Administrator password", { exact: true }).fill(replacement);
    await page.getByRole("button", { name: "Sign in to administration" }).click();
    await page.getByRole("heading", { name: "Overview", exact: true, level: 1 }).waitFor();
  });
  assert.deepEqual(errors, []);
} finally { await browser.close(); }

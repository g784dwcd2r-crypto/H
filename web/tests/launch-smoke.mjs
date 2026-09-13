import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const base = process.env.SMOKE_BASE_URL || 'http://localhost:3100';
const artifacts = path.resolve(process.env.SMOKE_ARTIFACT_DIR || '.browser-results', 'launch');
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.SMOKE_CHANNEL ? { channel: process.env.SMOKE_CHANNEL } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
const page = await context.newPage();
page.setDefaultTimeout(20000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const check = async (name, fn) => { await fn(); console.log('PASS ' + name); };
const campaign = async () => (await (await context.request.get(base + '/api/launch/campaign')).json()).campaign;
try {
  await check('Public writes reject cross-origin callers and arbitrary launch paths', async () => {
    assert.equal((await context.request.post(base + '/api/demo-requests', { headers: { Origin: 'https://other.example' }, data: {} })).status(), 403);
    assert.equal((await context.request.post(base + '/api/launch/membership', { headers: { Origin: 'https://other.example' }, data: {} })).status(), 403);
    assert.equal((await context.request.get(base + '/api/launch/platform-admin')).status(), 404);
    assert.equal((await context.request.get(base + '/api/launch/membership')).status(), 401);
  });
  await check('An uncertain demo submission retries the saved request without duplication or allocation', async () => {
    const before = await campaign();
    await page.goto(base + '/demo');
    const form = page.getByRole('form', { name: 'Request a demo' });
    const email = `launch-demo-${Date.now()}@example.com`;
    await form.getByLabel('Full name').fill('Ada Analyst');
    await form.getByLabel('Email address').fill(email);
    await form.getByLabel('Organisation').fill('Synthetic Research');
    await form.getByRole('combobox', { name: 'Region', exact: true }).selectOption('UK');
    await form.getByLabel('What would you like to explore?').fill('Compare annual statements and examine source evidence with our research team.');
    let persisted;
    const submitted = [];
    await page.route('**/api/demo-requests', async route => {
      submitted.push(route.request().postDataJSON());
      const saved = await route.fetch();
      assert.equal(saved.status(), 201);
      persisted = await saved.json();
      await route.fulfill({ status: 503, json: { error: 'Synthetic response delivery failed. Retry your request.' } });
    }, { times: 1 });
    await form.getByRole('button', { name: 'Request a demo', exact: true }).click();
    await form.getByRole('alert').filter({ hasText: 'Synthetic response delivery failed' }).waitFor();
    assert.equal(await form.getByLabel('Email address').inputValue(), email);
    assert.equal(await page.getByText('Request received', { exact: true }).count(), 0);
    const retry = page.waitForRequest(request => request.url().endsWith('/api/demo-requests'));
    await form.getByRole('button', { name: 'Request a demo', exact: true }).click();
    submitted.push((await retry).postDataJSON());
    await page.getByText('Request received', { exact: true }).waitFor();
    await page.getByText(`Reference: ${persisted.reference}`, { exact: true }).waitFor();
    assert.equal(submitted[0].request_id, submitted[1].request_id);
    assert.equal((await campaign()).allocated, before.allocated, 'A demo enquiry must not consume a founding place');
    await page.screenshot({ path: path.join(artifacts, 'demo-confirmed.png'), fullPage: true });
  });
  await check('Email verification returns to early access; only explicit opt-in reserves one place', async () => {
    const before = await campaign();
    await page.goto(base + '/early-access');
    await page.getByLabel('Your region').selectOption('AU');
    await page.getByRole('link', { name: 'Verify email and continue' }).click();
    await page.getByRole('textbox', { name: 'Email address', exact: true }).fill(`launch-founder-${Date.now()}@example.com`);
    await page.getByRole('button', { name: 'Email me a link' }).click();
    await page.getByRole('link', { name: 'open the link' }).click();
    await page.waitForURL(base + '/early-access');
    const reserve = page.getByRole('button', { name: 'Reserve my founding place', exact: true });
    await reserve.waitFor();
    assert.equal(await reserve.isDisabled(), true);
    assert.equal(await page.getByLabel('Your region').inputValue(), 'AU');
    assert.equal((await campaign()).allocated, before.allocated, 'Verification alone must not allocate');
    assert.equal((await (await context.request.get(base + '/api/launch/membership')).json()).membership, null);
    await page.getByRole('checkbox', { name: /I have read/ }).check();
    await reserve.click();
    await page.getByRole('heading', { name: 'Your place is reserved.' }).waitFor();
    const membership = (await (await context.request.get(base + '/api/launch/membership')).json()).membership;
    assert.equal(membership.status, 'reserved'); assert.equal(membership.region, 'AU');
    assert.equal((await campaign()).allocated, before.allocated + 1);
    await page.reload();
    await page.getByRole('heading', { name: 'Your place is reserved.' }).waitFor();
    const repeat = await context.request.post(base + '/api/launch/membership', { headers: { Origin: base }, data: { region: 'US', accept_terms: true } });
    assert.equal(repeat.status(), 200);
    assert.deepEqual((await repeat.json()).membership, membership);
    assert.equal((await campaign()).allocated, before.allocated + 1);
    await page.screenshot({ path: path.join(artifacts, 'founding-membership.png'), fullPage: true });
  });
  await check('Public forms and content remain readable at phone widths with reduced motion', async () => {
    for (const width of [320, 390]) {
      await page.setViewportSize({ width, height: 844 });
      for (const route of ['/demo', '/company/contact', '/early-access', '/platform', '/privacy']) {
        await page.goto(base + route);
        await page.locator('main h1').first().waitFor();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${route} at ${width}px must fit`);
      }
      await page.goto(base + '/demo');
      await page.getByLabel('Full name').fill('Mobile Analyst');
      await page.screenshot({ path: path.join(artifacts, `demo-${width}px.png`), fullPage: true });
    }
  });
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: path.join(artifacts, 'failure.png'), fullPage: true });
  console.error(error); console.error('Browser errors:', errors); process.exitCode = 1;
} finally { await browser.close(); }

import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const base = process.env.SMOKE_BASE_URL || 'http://localhost:3100';
const artifacts = path.resolve(process.env.SMOKE_ARTIFACT_DIR || '.browser-results', 'public-header');
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.SMOKE_CHANNEL ? { channel: process.env.SMOKE_CHANNEL } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const passed = [];
const header = () => page.locator('[data-public-header]');
const navigation = () => header().getByRole('navigation', { name: 'Main navigation' });
const openMenu = name => navigation().getByRole('button', { name, exact: true }).click();
const check = async (name, fn) => { await fn(); passed.push(name); console.log('PASS ' + name); };

try {
  await check('Campaign announcements reflect capacity and remember dismissal', async () => {
    let state = 'open';
    await page.route('**/api/launch/campaign', route => route.fulfill({ json: { campaign: { id: 'founding-members-2026', state } } }));
    await page.goto(base + '/');
    const announcement = page.getByRole('complementary', { name: 'Disclosure launch announcement' });
    await announcement.getByText(/Six months free for our first 20/).waitFor();
    state = 'full'; await page.reload();
    await announcement.getByText(/Our 20 founding places are filled/).waitFor();
    assert.equal((await announcement.getByRole('link').innerText()).replace(/\s+/g, ' '), 'Join the waitlist →');
    await announcement.getByRole('button', { name: 'Dismiss launch announcement' }).click();
    await page.reload();
    await page.waitForFunction(() => !document.querySelector('[aria-label="Disclosure launch announcement"]'));
    await page.evaluate(() => localStorage.removeItem('disclosure-announcement-dismissed'));
    await page.unroute('**/api/launch/campaign');
  });

  await check('Desktop menus are exclusive, dismissible and restore keyboard focus', async () => {
    await page.goto(base + '/');
    await openMenu('Platform');
    await header().getByRole('link', { name: /^Filings & search/ }).waitFor();
    await page.screenshot({ path: path.join(artifacts, 'platform-menu-desktop.png'), fullPage: false, animations: 'disabled' });
    await openMenu('Solutions');
    assert.equal(await header().getByRole('link', { name: /^Filings & search/ }).count(), 0);
    await header().getByRole('link', { name: /^Earnings preparation/ }).focus();
    await page.keyboard.press('Escape');
    assert.equal(await navigation().getByRole('button', { name: 'Solutions', exact: true }).getAttribute('aria-expanded'), 'false');
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'nav-solutions');
    await openMenu('Resources');
    await header().getByRole('button', { name: 'Log in', exact: true }).click();
    assert.equal(await navigation().getByRole('button', { name: 'Resources', exact: true }).getAttribute('aria-expanded'), 'false');
    await header().getByText('All regions currently use Disclosure Global.', { exact: true }).waitFor();
    await page.keyboard.press('Escape');
    await openMenu('Company');
    await page.locator('main').click({ position: { x: 8, y: 650 } });
    assert.equal(await navigation().getByRole('button', { name: 'Company', exact: true }).getAttribute('aria-expanded'), 'false');
  });

  await check('Public menu destinations and section anchors resolve to real content', async () => {
    await page.goto(base + '/');
    const targets = new Set(['/coverage', '/security', '/demo', '/early-access', '/privacy']);
    for (const menu of ['Platform', 'Solutions', 'Resources', 'Company']) {
      await openMenu(menu);
      for (const href of await header().locator('[id^="panel-"] a').evaluateAll(links => links.map(link => link.getAttribute('href')))) targets.add(href);
    }
    for (const target of targets) {
      const response = await page.goto(base + target);
      if (response) assert.equal(response.status(), 200, target);
      else assert.equal(new URL(page.url()).pathname, new URL(base + target).pathname, target);
      await page.locator('main h1').first().waitFor();
      const hash = new URL(base + target).hash;
      if (hash) assert.equal(await page.locator(hash).count(), 1, target + ' anchor');
    }
  });

  await check('Every login region reaches global sign-in and preserves the research destination', async () => {
    for (const [label, code] of [['United States', 'US'], ['United Kingdom', 'UK'], ['Europe', 'EU'], ['Australia', 'AU'], ['Rest of the world', 'ROW']]) {
      await page.goto(base + '/');
      await header().getByRole('button', { name: 'Log in', exact: true }).click();
      await header().getByRole('link', { name: new RegExp(label) }).click();
      await page.waitForURL('**/signin?**');
      const url = new URL(page.url());
      assert.equal(url.searchParams.get('region'), code); assert.equal(url.searchParams.get('next'), '/research');
      await page.getByText(/All regions currently use Disclosure Global/).waitFor();
      assert.equal((await context.cookies()).find(cookie => cookie.name === 'fh_region')?.value, code);
      const signup = new URL(await page.getByRole('link', { name: 'Get started for free', exact: true }).getAttribute('href'), base);
      assert.equal(signup.searchParams.get('region'), code); assert.equal(signup.searchParams.get('next'), '/research');
    }
  });

  await check('Mobile and tablet menus fit, expand by touch and close with Escape', async () => {
    for (const width of [320, 390, 768, 1119]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(base + '/');
      const toggle = header().getByRole('button', { name: 'Menu', exact: true });
      await toggle.click();
      await openMenu('Platform');
      await header().getByRole('link', { name: /^Ownership/ }).waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, width + 'px must not overflow');
      await page.waitForFunction(() => document.querySelector('#public-navigation').getBoundingClientRect().bottom <= innerHeight + 1);
      await page.keyboard.press('Escape');
      assert.equal(await page.evaluate(() => document.activeElement?.id), 'nav-platform');
      if (width === 390) await page.screenshot({ path: path.join(artifacts, 'navigation-mobile.png'), fullPage: false, animations: 'disabled' });
      await page.keyboard.press('Escape');
      assert.equal(await header().getByRole('button', { name: 'Menu', exact: true }).getAttribute('aria-expanded'), 'false');
    }
    await page.setViewportSize({ width: 1440, height: 960 });
  });

  await check('Email sign-in retains its input after a network failure and resumes early access', async () => {
    await page.goto(base + '/signin?next=/early-access&region=ROW');
    const email = 'public-header-' + Date.now() + '@example.com';
    await page.getByRole('textbox', { name: 'Email address', exact: true }).fill(email);
    await page.route('**/api/auth/magic-link', route => route.abort('failed'), { times: 1 });
    await page.getByRole('button', { name: 'Email me a link' }).click();
    await page.getByRole('alert').filter({ hasText: 'That did not go through' }).waitFor();
    assert.equal(await page.getByRole('textbox', { name: 'Email address', exact: true }).inputValue(), email);
    await page.getByRole('button', { name: 'Email me a link' }).click();
    const devLink = page.getByRole('link', { name: 'open the link' });
    await devLink.waitFor();
    const destination = new URL(await devLink.getAttribute('href'), base);
    assert.equal(destination.searchParams.get('next'), '/early-access'); assert.equal(destination.searchParams.get('region'), 'ROW');
    await devLink.click();
    await page.waitForURL(base + '/early-access');
    await header().getByRole('link', { name: /Open workspace/ }).waitFor();
    await page.goto(base + '/signin?next=/research&region=ROW');
    await page.waitForURL(base + '/research');
    await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Research', exact: true }).waitFor();
    assert.equal(await header().count(), 0, 'Daily workspace keeps its own navigation');
  });
  await check('Public and account pages serve readable content without JavaScript', async () => {
    const staticContext = await browser.newContext({ javaScriptEnabled: false, reducedMotion: 'reduce' });
    try {
      const staticPage = await staticContext.newPage();
      for (const route of ['/', '/platform', '/solutions', '/resources', '/company/about', '/coverage', '/security', '/demo', '/early-access', '/signin', '/signup']) {
        const response = await staticPage.goto(base + route);
        assert.equal(response.status(), 200, route);
        assert.equal(await staticPage.locator('main h1').first().isVisible(), true, route + ' must not stay in a hidden streamed boundary');
        assert.equal(await staticPage.getByText('Opening your workspace…', { exact: true }).count(), 0, route);
      }
    } finally { await staticContext.close(); }
  });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ passed, screenshots: artifacts }, null, 2));
} catch (error) {
  await page.screenshot({ path: path.join(artifacts, 'failure.png'), fullPage: true });
  console.error(error); console.error('Browser errors:', errors); process.exitCode = 1;
} finally { await browser.close(); }

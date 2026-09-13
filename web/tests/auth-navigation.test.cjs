const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { webcrypto } = require('node:crypto');
const { NextRequest } = require('next/server');

function runtime(api = {}) {
  const modules = new Map();
  function load(file) {
    if (modules.has(file)) return modules.get(file).exports;
    const module = { exports: {} }; modules.set(file, module);
    const source = fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    vm.runInNewContext(code, { module, exports: module.exports, URL, URLSearchParams, Response, crypto: webcrypto,
      require(name) {
        if (name === '@/lib/server-api') return { api };
        if (name === '@/lib/session') return { SESSION_COOKIE: 'fh_session', SESSION_DAYS: 30 };
        if (name.startsWith('@/')) return load(name.slice(2) + '.ts');
        if (name.startsWith('./')) return load(path.join(path.dirname(file), name) + '.ts');
        return require(name);
      },
    });
    return module.exports;
  }
  return load;
}

test('auth resumes known local product pages with their query and anchor intact', () => {
  const { safeAuthNext } = runtime()('lib/auth-navigation.ts');
  for (const next of ['/', '/early-access', '/research?q=AAPL', '/companies/320193/statements?period_mode=annual#statement-evidence', '/settings/security']) assert.equal(safeAuthNext(next), next);
});

test('auth return paths reject external, auth, API and ambiguously encoded destinations', () => {
  const { safeAuthNext } = runtime()('lib/auth-navigation.ts');
  for (const next of ['https://evil.example', '//evil.example', '/\\evil.example', '/%5cevil.example', '/%2f%2fevil.example', '/research/../../signin', '/auth/google', '/api/auth/signout', '/signin', '/signup', '/unknown', '/research/%2e%2e/auth/google', '/research/%252e%252e/auth/google', '/research\n', '/research%0d', 'javascript:alert(1)', null]) assert.equal(safeAuthNext(next), '/', String(next));
});

test('valid explicit regions override remembered regions; unknown values never become preferences', () => {
  const { authRegion, authHref } = runtime()('lib/auth-navigation.ts');
  assert.equal(authRegion('ROW', 'UK'), 'ROW');
  assert.equal(authRegion('invented', 'UK'), 'UK');
  assert.equal(authRegion('invented', 'invented'), null);
  const url = new URL(authHref('/signin', '/early-access', 'EU', 'link'), 'https://disclosure.example');
  assert.equal(url.searchParams.get('next'), '/early-access');
  assert.equal(url.searchParams.get('region'), 'EU');
  assert.equal(url.searchParams.get('error'), 'link');
});

test('email callback resumes its verified-account destination and remembers the cross-device region', async () => {
  const load = runtime({ post: async () => ({ ok: true, data: { session: 'verified-session' } }) });
  const response = await load('app/auth/callback/route.ts').GET(new NextRequest('https://disclosure.example/auth/callback?token=one-time&next=%2Fearly-access&region=ROW'));
  assert.equal(response.headers.get('location'), 'https://disclosure.example/early-access');
  assert.equal(response.cookies.get('fh_session').value, 'verified-session');
  assert.equal(response.cookies.get('fh_session').httpOnly, true);
  assert.equal(response.cookies.get('fh_region').value, 'ROW');
  assert.equal(response.cookies.get('fh_region').secure, true);
});

test('expired email links preserve a safe destination and region for retry without a session', async () => {
  const load = runtime({ post: async () => ({ ok: false, data: {} }) });
  const response = await load('app/auth/callback/route.ts').GET(new NextRequest('https://disclosure.example/auth/callback?token=expired&next=%2Fearly-access&region=EU'));
  const url = new URL(response.headers.get('location'));
  assert.equal(url.pathname, '/signin'); assert.equal(url.searchParams.get('next'), '/early-access'); assert.equal(url.searchParams.get('region'), 'EU');
  assert.equal(response.cookies.get('fh_session'), undefined);
});

test('Google initiation binds continuation to its state in a secure httpOnly callback-only cookie', async () => {
  const load = runtime({ authConfig: async () => ({ google_client_id: 'configured-client' }) });
  const response = await load('app/auth/google/route.ts').GET(new NextRequest('https://disclosure.example/auth/google?next=%2Fearly-access&region=AU'));
  const google = new URL(response.headers.get('location'));
  assert.equal(google.origin, 'https://accounts.google.com');
  const cookie = response.cookies.get('fh_oauth_state');
  const context = JSON.parse(cookie.value);
  assert.equal(context.state, google.searchParams.get('state'));
  assert.equal(context.next, '/early-access'); assert.equal(context.region, 'AU');
  assert.equal(cookie.httpOnly, true); assert.equal(cookie.secure, true); assert.equal(cookie.sameSite, 'lax');
  assert.equal(cookie.path, '/auth/google/callback'); assert.equal(cookie.maxAge, 600);
});

test('Google rejects missing or mismatched state before contacting the provider API', async () => {
  let calls = 0;
  const load = runtime({ post: async () => { calls++; return { ok: true, data: { session: 'bad' } }; } });
  const callback = load('app/auth/google/callback/route.ts').GET;
  for (const state of ['', 'wrong-state']) {
    const request = new NextRequest('https://disclosure.example/auth/google/callback?code=code&state=' + state);
    request.cookies.set('fh_oauth_state', JSON.stringify({ state: 'expected-long-random-state', next: '/early-access', region: 'US' }));
    const response = await callback(request);
    assert.equal(new URL(response.headers.get('location')).pathname, '/signin');
    assert.equal(response.cookies.get('fh_session'), undefined);
  }
  assert.equal(calls, 0);
});

test('Google resumes only cookie-bound context and clears it after a successful callback', async () => {
  const load = runtime({ post: async () => ({ ok: true, data: { session: 'verified-session' } }) });
  const request = new NextRequest('https://disclosure.example/auth/google/callback?code=code&state=expected-long-random-state&next=https://evil.example&region=US');
  request.cookies.set('fh_oauth_state', JSON.stringify({ state: 'expected-long-random-state', next: '/early-access', region: 'ROW' }));
  const response = await load('app/auth/google/callback/route.ts').GET(request);
  assert.equal(response.headers.get('location'), 'https://disclosure.example/early-access');
  assert.equal(response.cookies.get('fh_region').value, 'ROW');
  assert.equal(response.cookies.get('fh_oauth_state').maxAge, 0);
  assert.equal(response.cookies.get('fh_oauth_state').path, '/auth/google/callback');
});

test('Google provider failure preserves a safe retry destination and removes stale state', async () => {
  const load = runtime({ post: async () => { throw new Error('provider unavailable'); } });
  const request = new NextRequest('https://disclosure.example/auth/google/callback?code=code&state=expected-long-random-state');
  request.cookies.set('fh_oauth_state', JSON.stringify({ state: 'expected-long-random-state', next: '/research', region: 'UK' }));
  const response = await load('app/auth/google/callback/route.ts').GET(request);
  const url = new URL(response.headers.get('location'));
  assert.equal(url.pathname, '/signin'); assert.equal(url.searchParams.get('next'), '/research'); assert.equal(url.searchParams.get('region'), 'UK');
  assert.equal(response.cookies.get('fh_oauth_state').maxAge, 0);
});

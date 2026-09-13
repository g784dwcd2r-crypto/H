const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const ts = require('typescript');
const { NextRequest } = require('next/server');

function runtime(extra = {}) {
  const modules = new Map();
  function load(relative) {
    const filename = path.join(__dirname, '..', relative);
    if (modules.has(filename)) return modules.get(filename).exports;
    const module = { exports: {} }; modules.set(filename, module);
    const source = fs.readFileSync(filename, 'utf8');
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
    vm.runInNewContext(code, {
      module, exports: module.exports, crypto: webcrypto, TextEncoder, Uint8Array, Headers, URLSearchParams,
      process: {env:{FILINGS_API_KEY:'gateway-secret', NODE_ENV:'test'}},
      require(name) { if (name === 'server-only') return {}; if (name === 'next/headers') return { cookies: async () => ({get:() => undefined}) }; if (name.startsWith('@/')) return load(name.slice(2)+'.ts'); return require(name); },
      ...extra,
    });
    return module.exports;
  }
  return load;
}

test('anonymous visitor cookies are signed, expiring and different for different browsers', async () => {
  const load = runtime(); const {issueVisitor,verifyVisitor,VISITOR_MAX_AGE} = load('lib/gateway-identity.ts');
  const now = 1789300000; const first = await issueVisitor('gateway-secret',now); const second = await issueVisitor('gateway-secret',now);
  assert.notEqual(first.id,second.id);
  assert.equal(await verifyVisitor(first.token,'gateway-secret',now),first.id);
  assert.equal(await verifyVisitor(first.token,'wrong-secret',now),null);
  assert.equal(await verifyVisitor(first.token.replace(first.id,second.id),'gateway-secret',now),null);
  assert.equal(await verifyVisitor(first.token,'gateway-secret',now+VISITOR_MAX_AGE),null);
  assert.equal(await verifyVisitor('arbitrary-client-id','gateway-secret',now),null);
});

test('middleware replaces forged identity and makes first-request cookie available downstream', async () => {
  const load = runtime(); const {middleware} = load('middleware.ts'); const helper = load('lib/gateway-identity.ts');
  const req = new NextRequest('https://disclosure.example/api/search?q=AAPL',{headers:{'X-Disclosure-Visitor':'attacker-chosen','Cookie':'fh_visitor=forged'}});
  const response = await middleware(req);
  const cookie = response.cookies.get(helper.VISITOR_COOKIE).value;
  const id = await helper.verifyVisitor(cookie,'gateway-secret');
  assert.ok(id);
  assert.equal(response.headers.get('x-middleware-request-x-disclosure-visitor'),id);
  assert.match(response.headers.get('x-middleware-request-cookie'),new RegExp(cookie.replaceAll('.','\\.')));
  assert.match(response.headers.get('set-cookie'),/HttpOnly/i);
  assert.match(response.headers.get('set-cookie'),/Secure/i);
  assert.match(response.headers.get('set-cookie'),/SameSite=lax/i);
  assert.equal(response.headers.get('x-disclosure-visitor'),null);
});

test('valid visitor cookie wins over incoming identity headers and stays stable', async () => {
  const load = runtime(); const helper = load('lib/gateway-identity.ts'); const issued = await helper.issueVisitor('gateway-secret'); const {middleware} = load('middleware.ts');
  const response = await middleware(new NextRequest('https://disclosure.example/',{headers:{Cookie:`fh_visitor=${issued.token}`,'X-Disclosure-Visitor':'forged'}}));
  assert.equal(response.headers.get('x-middleware-request-x-disclosure-visitor'),issued.id);
  assert.equal(response.headers.get('set-cookie'),null);
});

test('transport includes verified browser identity, session and service key for normal calls and exports', async () => {
  const helper = runtime()('lib/gateway-identity.ts'); const issued = await helper.issueVisitor('gateway-secret');
  const calls = []; let transportLoad;
  transportLoad = runtime({
    require(name) { if(name === 'server-only') return {}; if(name === 'next/headers') return {cookies:async()=>({get:(key)=>({value:key==='fh_visitor'?issued.token:key==='fh_session'?'session-cookie':undefined})})}; if(name.startsWith('@/'))return transportLoad(name.slice(2)+'.ts'); return require(name); },
    fetch:async(url,options)=>{ calls.push({url,options}); return {ok:true,status:200,json:async()=>({results:[]})}; },
  });
  const {api} = transportLoad('lib/server-api.ts');
  await api.search('AAPL'); await api.exportResponse('320193',new URLSearchParams({limit:'2'}));
  assert.equal(calls.length,2);
  for(const {options} of calls) {
    assert.equal(options.headers['X-API-Key'],'gateway-secret');
    assert.equal(options.headers['X-Disclosure-Visitor'],issued.id);
    assert.equal(options.headers['X-Session'],'session-cookie');
  }
});

test('shared browser types do not import server transport or contain service credentials', () => {
  const source = fs.readFileSync(path.join(__dirname,'../lib/api.ts'),'utf8');
  assert.doesNotMatch(source,/process\.env|server-api|next\/headers|const KEY|export const api/);
  const transport = fs.readFileSync(path.join(__dirname,'../lib/server-api.ts'),'utf8');
  assert.match(transport,/import "server-only"/);
});

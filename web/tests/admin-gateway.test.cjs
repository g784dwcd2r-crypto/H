const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function route({ token = 'opaque-admin-token', status = 200, data = {}, origin = 'https://admin.example.test' } = {}) {
  const source = fs.readFileSync(path.join(__dirname,'../app/api/platform-admin/[[...segments]]/route.ts'),'utf8');
  const code = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const module = { exports: {} }, calls = [];
  const json = (data, options) => { const value = {data,status:options.status,headers:options.headers,cookieWrites:[]}; value.cookies = {set(...args){value.cookieWrites.push(args);}}; return value; };
  vm.runInNewContext(code,{module,exports:module.exports,URLSearchParams,AbortSignal,Date,JSON,
    process:{env:{FILINGS_API_URL:'http://private-api:8000',FILINGS_API_KEY:'private-service-key',PLATFORM_ADMIN_ORIGIN:origin}},
    fetch:async(url,options)=>{calls.push({url,options});return {ok:status>=200&&status<300,status,json:async()=>({...data})};},
    require(name){if(name==='next/server')return {NextResponse:{json}};if(name==='next/headers')return {cookies:async()=>({get:()=>token?{value:token}:undefined})};throw new Error(name);}});
  async function request(path, method='GET', headers={}) {
    return module.exports[method]({method,headers:new Headers({Origin:origin,'X-Admin-CSRF':'csrf',...headers}),nextUrl:new URL('https://admin.example.test/api/platform-admin/'+path),text:async()=>'{}'}, {params:Promise.resolve({segments:path.split('?')[0].split('/')})});
  }
  return {request,calls};
}
test('admin gateway strips bearer tokens and sets a strict secure HttpOnly cookie', async()=>{
  const gateway=route({data:{token:'new-private-token',csrf:'csrf-value',expires_at:'2030-01-01T00:00:00Z'}});
  const result=await gateway.request('login','POST');
  assert.equal(result.data.token,undefined);assert.equal(result.data.csrf,'csrf-value');
  assert.equal(result.cookieWrites[0][0],'__Host-disclosure_admin');
  assert.equal(result.cookieWrites[0][2].secure,true);assert.equal(result.cookieWrites[0][2].httpOnly,true);
  assert.equal(result.cookieWrites[0][2].sameSite,'strict');
});
test('admin gateway never forwards caller chosen service, operator or tenant identity',async()=>{
  const gateway=route();
  await gateway.request('users','GET',{'X-API-Key':'forged','X-Admin-Session':'forged','X-Session':'ordinary','X-Role':'owner'});
  const sent=gateway.calls[0].options.headers;
  assert.equal(sent['X-API-Key'],'private-service-key');assert.equal(sent['X-Admin-Session'],'opaque-admin-token');
  assert.equal(sent['X-Session'],undefined);assert.equal(sent['X-Role'],undefined);
  const absent=route({token:null});assert.equal((await absent.request('users','GET',{'X-Admin-Session':'forged'})).status,401);assert.equal(absent.calls.length,0);
});
test('cross-origin mutations and paths outside the management allowlist never reach API',async()=>{
  const gateway=route();
  assert.equal((await gateway.request('logout','POST',{Origin:'https://attacker.example'})).status,403);
  assert.equal((await gateway.request('users/../../projects')).status,404);
  assert.equal(gateway.calls.length,0);
});
test('logout failures keep the cookie; verified invalid sessions finish logout',async()=>{
  const failed=await route({status:503,data:{detail:'Unavailable'}}).request('logout','POST');
  assert.equal(failed.status,503);assert.equal(failed.cookieWrites.length,0);
  const invalid=await route({status:401,data:{detail:'Revoked'}}).request('logout','POST');
  assert.equal(invalid.status,200);assert.equal(invalid.data.already_invalid,true);assert.equal(invalid.cookieWrites[0][2].maxAge,0);
});

test('launch admin routes preserve bounded filters and reject roster writes',async()=>{
  const gateway=route();
  await gateway.request('launch-memberships?q=founder&status=reserved&limit=25&offset=25&role=owner');
  const url=new URL(gateway.calls[0].url);
  assert.equal(url.pathname,'/platform-admin/launch-memberships');
  assert.equal(url.searchParams.get('status'),'reserved'); assert.equal(url.searchParams.get('offset'),'25');
  assert.equal(url.searchParams.has('role'),false);
  assert.equal((await gateway.request('launch-memberships','POST')).status,404);
  const absent=route({token:null});
  assert.equal((await absent.request('demo-requests')).status,401);
  assert.equal((await absent.request('launch-memberships')).status,401);
});
test('demo status updates accept real UUIDs and use reviewed operator credentials',async()=>{
  const gateway=route();
  const id='b1bc808e-90e4-4c0e-9975-5b1f030df621';
  await gateway.request('demo-requests/'+id+'/status','POST',{'X-Admin-Session':'forged','X-Admin-CSRF':'review-csrf'});
  assert.equal(gateway.calls[0].options.headers['X-Admin-Session'],'opaque-admin-token');
  assert.equal(gateway.calls[0].options.headers['X-Admin-CSRF'],'review-csrf');
  assert.equal((await gateway.request('demo-requests/not-an-id/status','POST')).status,404);
  assert.equal(gateway.calls.length,1);
});

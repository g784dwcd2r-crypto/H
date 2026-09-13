const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function loadRoute(result, allowed = true) {
  const source = fs.readFileSync(path.join(__dirname,'../app/api/auth/signout/route.ts'),'utf8');
  const code = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
  const module = {exports:{}};
  const response = (data,options) => ({data,status:options?.status ?? 200,cleared:[],cookies:{set(...args){this.owner.cleared.push(args);}}});
  const create = (data,options) => { const r=response(data,options);r.cookies.owner=r;return r; };
  vm.runInNewContext(code,{module,exports:module.exports,URL,require(name){
    if(name==='next/server')return {NextResponse:{redirect:create,json:create}};
    if(name==='@/lib/session')return {SESSION_COOKIE:'fh_session'};
    if(name==='@/lib/workspace-api')return {sameOriginMutation:()=>allowed,workspaceRequest:async()=>result};
    throw new Error(name);
  }});
  return module.exports.POST;
}
test('logout retains the browser session when server-side revocation fails',async()=>{
  const post=loadRoute({ok:false,status:502,data:null});
  const response=await post({nextUrl:new URL('https://disclosure.example/api/auth/signout')});
  assert.equal(response.status,303);
  assert.equal(response.data.pathname,'/settings/security');
  assert.equal(response.data.searchParams.get('error'),'signout');
  assert.equal(response.cleared.length,0);
});
test('logout clears its cookie after successful revocation or an already invalid session',async()=>{
  for(const result of [{ok:true,status:200,data:{revoked:true}},{ok:false,status:401,data:null}]){
    const response=await loadRoute(result)({nextUrl:new URL('https://disclosure.example/api/auth/signout')});
    assert.equal(response.status,303);assert.equal(response.data.pathname,'/');
    assert.equal(response.cleared.length,1);assert.equal(response.cleared[0][0],'fh_session');
    assert.equal(response.cleared[0][2].maxAge,0);
  }
});
test('cross-origin logout does not clear the cookie',async()=>{
  const response=await loadRoute({ok:true,status:200},false)({nextUrl:new URL('https://disclosure.example/api/auth/signout')});
  assert.equal(response.status,403);assert.equal(response.cleared.length,0);
});

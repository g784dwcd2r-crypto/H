const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { NextRequest } = require('next/server');
function runtime({ status=201, data={received:true,reference:'saved-reference'}, retryAfter=null }={}) {
  const calls=[], modules=new Map();
  function load(file) {
    if(modules.has(file))return modules.get(file).exports;
    const module={exports:{}};modules.set(file,module);
    const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'..',file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
    vm.runInNewContext(code,{module,exports:module.exports,URL,AbortSignal,
      process:{env:{FILINGS_API_URL:'http://private-api:8000'}},
      fetch:async(url,options)=>{calls.push({url,options});return new Response(JSON.stringify(data),{status,headers:retryAfter?{'Retry-After':retryAfter}:{}});},
      require(name){
        if(name==='server-only')return {};
        if(name==='@/lib/server-api')return {requestHeaders:async()=>({'X-API-Key':'private-service','X-Session':'server-cookie-session'})};
        if(name.startsWith('@/'))return load(name.slice(2)+'.ts');
        return require(name);
      }});
    return module.exports;
  }
  return {calls,send:async(value,origin='https://disclosure.example')=>load('app/api/demo-requests/route.ts').POST(new NextRequest('https://disclosure.example/api/demo-requests',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json','X-Session':'forged'},body:JSON.stringify(value)}))};
}
test('demo transport keeps retry reference and forwards only form fields with server credentials',async()=>{
  const gateway=runtime();
  const response=await gateway.send({request_id:'original-reference',name:'Ada',email:'ada@example.test',region:'UK',workflow:'Source research',role:'superadmin',user_id:'another-user'});
  assert.equal(response.status,201);
  const body=JSON.parse(gateway.calls[0].options.body);
  assert.equal(body.request_id,'original-reference');assert.equal(body.role,undefined);assert.equal(body.user_id,undefined);
  assert.equal(gateway.calls[0].options.headers['X-Session'],'server-cookie-session');
  assert.equal(response.headers.get('cache-control'),'private, no-store');
});
test('durable demo throttle preserves Retry-After without reporting success',async()=>{
  const gateway=runtime({status:429,data:{detail:'Please wait before sending another demo request.'},retryAfter:'3600'});
  const response=await gateway.send({});
  assert.equal(response.status,429);assert.equal(response.headers.get('retry-after'),'3600');
  const body=await response.json();assert.equal(body.received,undefined);assert.match(body.error,/Please wait/);
});
test('cross-origin demo requests never reach the private API',async()=>{
  const gateway=runtime();assert.equal((await gateway.send({},'https://attacker.example')).status,403);assert.equal(gateway.calls.length,0);
});

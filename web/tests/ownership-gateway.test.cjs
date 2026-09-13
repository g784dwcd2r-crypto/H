const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
function gateway({status=200,data={flow:'insiders',items:[]},csv='name,shares\nSynthetic person,100\n'}={}){
 const module={exports:{}},calls=[];
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../app/api/ownership/[[...segments]]/route.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module,exports:module.exports,URLSearchParams,Response,AbortSignal,
  process:{env:{FILINGS_API_URL:'http://private-api:8000'}},
  fetch:async(url,options)=>{calls.push({url,options});return new Response(status===200?csv:JSON.stringify({detail:'Narrow this export to at most 10,000 rows.'}),{status});},
  require(name){if(name==='@/lib/server-api')return{requestHeaders:async()=>({'X-API-Key':'gateway-only','X-Session':'current-account'})};if(name==='@/lib/workspace-api')return{workspaceRequest:async url=>{calls.push({url});return{status,data:status===200?data:null,error:null};}};throw Error(name);}});
 return{calls,request:(route,query='')=>module.exports.GET({nextUrl:new URL('https://app.test/api/ownership/'+route+'?'+query),headers:new Headers({'X-API-Key':'forged','X-Session':'forged'})},{params:Promise.resolve({segments:route.split('/')})})};
}
test('ownership export is flow-scoped, uses trusted identity and excludes pagination/identity query fields',async()=>{
 const g=gateway(),response=await g.request('320193/insiders/export','direction=sales&from=2026-01-01&offset=20&limit=1&api_key=forged');
 assert.equal(response.status,200);assert.equal(g.calls[0].url,'http://private-api:8000/companies/320193/ownership/insiders/export.csv?from=2026-01-01&direction=sales');assert.equal(g.calls[0].options.headers['X-API-Key'],'gateway-only');assert.equal(g.calls[0].options.headers['X-Session'],'current-account');assert.match(response.headers.get('content-disposition'),/320193-insiders\.csv/);assert.equal(response.headers.get('cache-control'),'private, no-store');
});
test('oversized exports return actionable failure rather than a successful partial download',async()=>{
 const response=await gateway({status:422}).request('320193/events/export');assert.equal(response.status,422);assert.match((await response.json()).error,/10,000/);assert.equal(response.headers.has('content-disposition'),false);
});
test('ownership gateway rejects unintended routes and preserves each recent-flow query',async()=>{
 const g=gateway();assert.equal((await g.request('320193/../../projects')).status,404);assert.equal((await g.request('320193/all/export')).status,404);assert.equal(g.calls.length,0);
 await g.request('recent','ciks=320193,19617&flow=events&since=2026-01-01&user_id=forged');assert.equal(g.calls[0].url,'/ownership/recent?ciks=320193%2C19617&flow=events&since=2026-01-01');
});

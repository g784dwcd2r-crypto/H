const test=require('node:test'); const assert=require('node:assert/strict');
const fs=require('node:fs'); const path=require('node:path'); const vm=require('node:vm'); const ts=require('typescript');
function load(file,globals={}){const module={exports:{}};const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'..',file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;vm.runInNewContext(code,{module,exports:module.exports,URL,URLSearchParams,Response,...globals});return module.exports;}
test('exact evidence matches Unicode code-point offsets and refuses changed or partial text',()=>{
  const {exactEvidenceSpan}=load('lib/evidence-span.ts'); const text='A😀 revenue 1,200. End';
  assert.equal(exactEvidenceSpan(text,3,10,'revenue').quote,'revenue');
  assert.equal(exactEvidenceSpan(text,4,11,'revenue'),null);
  assert.equal(exactEvidenceSpan(text,3,10,'Revenue'),null);
  for(const [a,b] of [[-1,3],[1,1],[1,100],[NaN,3],[1.5,3]])assert.equal(exactEvidenceSpan(text,a,b,'x'),null);
});
test('number suggestions preserve supplementary Unicode offsets and complete signed decimal literals',()=>{
  const {evidenceNumbers}=load('lib/evidence-span.ts'); const text='😀 Revenue 1,200. Cost (350.25), change -1.5 and version abc123.';
  const values=evidenceNumbers(text,50);
  assert.deepEqual(Array.from(values,v=>v.text),['1,200','(350.25)','-1.5']);
  for(const value of values)assert.equal(Array.from(text).slice(value.start-50,value.end-50).join(''),value.text);
});
test('reordered explicit scope shares the request fingerprint while question or cutoff changes do not',()=>{
  const {runRequestKey}=load('lib/cited-research.ts');
  const request={question:'Revenue?',ciks:[2,1],version_ids:['b','a'],as_of:'2026-01-01'};
  assert.equal(runRequestKey(request),runRequestKey({...request,ciks:[1,2],version_ids:['a','b']}));
  assert.notEqual(runRequestKey(request),runRequestKey({...request,as_of:'2026-01-02'}));
});
function route({signedIn=true,origin=true}={}){
  const calls=[];
  const api=load('app/api/research-assistant/[[...segments]]/route.ts',{require(name){
    if(name==='next/server')return {};
    if(name==='@/lib/session')return {sessionToken:async()=>signedIn?'signed-session':null};
    if(name==='@/lib/workspace-api')return {sameOriginMutation:()=>origin,workspaceRequest:async(...args)=>{calls.push(args);return {status:200,data:{ok:true}};}};
    throw Error(name);
  }});
  return {api,calls};
}
test('research gateway denies cross-origin mutations and anonymous private runs before forwarding',async()=>{
  for(const options of [{origin:false},{signedIn:false}]){
    const {api,calls}=route(options);const result=await api.POST({method:'POST',json:async()=>({question:'test'})},{params:Promise.resolve({segments:['runs']})});
    assert.equal(result.status,options.origin===false?403:401);assert.equal(calls.length,0);
  }
});
test('research gateway allowlists paths, removes identity query fields and disables caching',async()=>{
  const {api,calls}=route();
  const result=await api.GET({method:'GET',nextUrl:new URL('https://example.test/api/research-assistant/search?q=risk&owner_id=other&limit=20')},{params:Promise.resolve({segments:['search']})});
  assert.equal(calls[0][0],'/research/search?q=risk&limit=20'); assert.match(result.headers.get('cache-control'),/no-store/);
  for(const segments of [['runs','x','delete'],['..','users'],['documents','x','extra']]){
    const denied=await api.GET({method:'GET'},{params:Promise.resolve({segments})}); assert.ok([400,404].includes(denied.status));
  }
  assert.equal(calls.length,1);
  await api.GET({method:'GET'},{params:Promise.resolve({segments:['projections','projection:'+'a'.repeat(64)]})});
  assert.match(calls[1][0],/^\/research\/projections\/projection%3A/);
});
test('Unicode minus remains signed and unsupported dash/parenthesis prefixes never yield positive suffixes',()=>{
  const {evidenceNumbers}=load('lib/evidence-span.ts');
  assert.deepEqual(Array.from(evidenceNumbers('Cash −1,200; change −15.5.',0),v=>v.text),['−1,200','−15.5']);
  for(const text of ['Cash –1,200','Cash − 1,200','Cash ( 1,200 )','Cash —1,200'])assert.equal(evidenceNumbers(text,0).length,0,text);
});
test('research recovery is account and context scoped and retains a pending request key',()=>{
  const {readResearchDraft,writeResearchDraft,clearResearchDraft}=load('lib/research-drafts.ts');const values=new Map();const storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  const draft={question:'Follow up?',companies:[{cik:1,name:'Issuer'}],documents:[],cutoff:'2026-01-01',parent:'a'.repeat(32),request:{fingerprint:'question+scope',key:'request-123'}};
  assert.equal(writeResearchDraft(storage,'owner','run1',draft),true);
  assert.equal(readResearchDraft(storage,'owner','run1').request.key,'request-123');
  assert.equal(readResearchDraft(storage,'other','run1'),null);assert.equal(readResearchDraft(storage,'owner','run2'),null);
  clearResearchDraft(storage,'owner','run1');assert.equal(readResearchDraft(storage,'owner','run1'),null);
  assert.equal(writeResearchDraft(null,'owner','run1',draft),false);assert.equal(readResearchDraft(null,'owner','run1').parent,draft.parent);
});

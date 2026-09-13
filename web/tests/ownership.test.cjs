const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');const ts=require('typescript');
const moduleObject={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../lib/ownership.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,{module:moduleObject,exports:moduleObject.exports,URL,URLSearchParams});
const {ownershipFilters,ownershipQuery,ownershipPagePath,ownershipReturnPath,ownershipSourceHref,ownershipValue,compatibleHistory}=moduleObject.exports;
test('ownership flow filters and pagination preserve the other flows and clear only the chosen flow',()=>{
 const values={insiders_direction:'buys',insiders_from:'2025-01-01',insiders_offset:'20',institutions_to:'2026-01-01',institutions_offset:'40',events_from:'2024-01-01'};
 const next=new URL(ownershipPagePath(320193,values,{flow:'insiders',offset:40}),'https://test.invalid');
 assert.equal(next.searchParams.get('insiders_offset'),'40');assert.equal(next.searchParams.get('institutions_offset'),'40');assert.equal(next.searchParams.get('events_from'),'2024-01-01');assert.equal(next.hash,'#insiders');
 const cleared=new URL(ownershipPagePath(320193,values,{flow:'insiders',clear:true}),'https://test.invalid');assert.equal(cleared.searchParams.has('insiders_direction'),false);assert.equal(cleared.searchParams.get('institutions_to'),'2026-01-01');
 const exportQuery=new URLSearchParams(ownershipQuery(ownershipFilters(values,'insiders'),false));assert.equal(exportQuery.get('direction'),'buys');assert.equal(exportQuery.get('from'),'2025-01-01');assert.equal(exportQuery.has('limit'),false);assert.equal(exportQuery.has('offset'),false);
});
test('malformed dates remain explicit API validation errors rather than silently widening scope',()=>{
 assert.equal(ownershipFilters({insiders_from:'not-a-date'},'insiders').from,'not-a-date');assert.match(ownershipQuery(ownershipFilters({insiders_from:'not-a-date'},'insiders')),/from=not-a-date/);
 assert.equal(ownershipFilters({institutions_direction:'buys'},'institutions').direction,'all');
});
test('source return links are local, issuer-scoped and preserve only known ownership filters',()=>{
 const returnTo='/companies/320193/ownership?insiders_direction=sales&events_offset=20#events';const href=ownershipSourceHref(320193,{document_id:'a'.repeat(64)},returnTo);assert.equal(new URL(href,'https://test.invalid').searchParams.get('return_to'),returnTo);
 for(const unsafe of ['//evil.test/companies/320193/ownership','https://evil.test/companies/320193/ownership','/companies/1/ownership','/companies/320193/ownership/../../signin','javascript:alert(1)'])assert.equal(ownershipReturnPath(320193,unsafe),'/companies/320193/ownership');
 assert.equal(ownershipReturnPath(320193,'/companies/320193/ownership?return_to=https://evil.test&events_offset=20'),'/companies/320193/ownership?events_offset=20');
});
test('reported zero stays distinct from missing and large exact quantities never use floating point formatting',()=>{
 assert.equal(ownershipValue('0'),'0');assert.equal(ownershipValue(null),'Not reported');assert.equal(ownershipValue('9007199254740993.125'),'9,007,199,254,740,993.125');assert.equal(ownershipValue('-1200.00'),'-1,200.00');
});
test('holding charts refuse mismatched direct/indirect or security series and sort compatible observations',()=>{
 const observation=(date,value,series_key='common:direct')=>({date,value,series_key,label:'Common shares · direct'});
 assert.equal(compatibleHistory([observation('2026-01-01','0')]),null);
 assert.equal(compatibleHistory([observation('2026-01-01','100'),observation('2026-02-01','120','common:indirect')]),null);
 assert.equal(compatibleHistory([observation('2026-01-01','100'),observation('2026-02-01','unknown')]),null);
 assert.equal(compatibleHistory([observation('2026-02-01','120'),observation('2026-01-01','0')])[0].value,'0');
});

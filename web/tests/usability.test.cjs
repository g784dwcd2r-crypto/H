const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
function load(file) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname,'..',file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
  const module={exports:{}};
  vm.runInNewContext(code,{module,exports:module.exports,URL,URLSearchParams});
  return module.exports;
}
function storage() {const values=new Map();return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};}
const draft = () => ({version:1,accountId:'account-a',projectId:'project-a',noteId:'note-a',baseRevision:2,draft:{title:'Thesis',body:'Unsaved evidence',kind:'thesis',citations:[]}});
test('tab draft recovery isolates accounts and projects and clears saved drafts',()=>{
  const {writeProjectDraft,readProjectDraft,clearProjectDraft}=load('lib/project-drafts.ts');const cache=storage();
  assert.equal(writeProjectDraft(cache,draft()),true);
  assert.equal(readProjectDraft(cache,'account-a','project-a').draft.body,'Unsaved evidence');
  assert.equal(readProjectDraft(cache,'account-b','project-a'),null);assert.equal(readProjectDraft(cache,'account-a','project-b'),null);
  clearProjectDraft(cache,'account-a','project-a');assert.equal(readProjectDraft(cache,'account-a','project-a'),null);
});
test('recovered source pointers cannot claim old access or verification metadata',()=>{
  const {writeProjectDraft,readProjectDraft}=load('lib/project-drafts.ts');const cache=storage();const value=draft();
  value.draft.citations=[{kind:'document',document_id:'doc',version_id:'sha256:a',status:'available',title:'Previously private document',explanation:'Old permission'}];
  writeProjectDraft(cache,value);const refs=readProjectDraft(cache,'account-a','project-a').draft.citations;
  assert.deepEqual(JSON.parse(JSON.stringify(refs)),[{kind:'document',document_id:'doc',version_id:'sha256:a'}]);
});
test('blocked browser storage retains in-page recovery without claiming durable persistence',()=>{
  const {writeProjectDraft,readProjectDraft,clearProjectDraft}=load('lib/project-drafts.ts');const cache={getItem(){throw Error('blocked')},setItem(){throw Error('blocked')},removeItem(){throw Error('blocked')}};
  assert.equal(writeProjectDraft(cache,draft()),false);assert.equal(readProjectDraft(cache,'account-a','project-a').baseRevision,2);
  clearProjectDraft(cache,'account-a','project-a');assert.equal(readProjectDraft(cache,'account-a','project-a'),null);
});
test('malformed or cross-account draft records are not restored',()=>{
  const {projectDraftKey,readProjectDraft}=load('lib/project-drafts.ts');const cache=storage();const key=projectDraftKey('account-a','project-a');
  cache.setItem(key,'{broken');assert.equal(readProjectDraft(cache,'account-a','project-a'),null);
  cache.setItem(key,JSON.stringify({...draft(),accountId:'account-b'}));assert.equal(readProjectDraft(cache,'account-a','project-a'),null);
  cache.setItem(key,JSON.stringify({...draft(),draft:{...draft().draft,body:{unsafe:true}}}));assert.equal(readProjectDraft(cache,'account-a','project-a'),null);
});
test('source-reader return context preserves search filters while refusing external destinations',()=>{
  const {researchReturnPath,indexedDocumentHref}=load('lib/research.ts');
  const original='/research?q=%22supply+chain%22&cik=320193&form=8-K&from=2024-01-01&to=2025-01-01&offset=40';
  const href=indexedDocumentHref('sha256:abc',original);const returned=new URL(href,'https://disclosure.invalid').searchParams.get('return_to');
  assert.equal(returned,original);
  for(const unsafe of ['https://attacker.example/research','//attacker.example/research','/research/../../signin','javascript:alert(1)','/projects'])assert.equal(researchReturnPath(unsafe),null);
  assert.equal(researchReturnPath('/research?q=safe&return_to=https://attacker.example'),'/research?q=safe');
});

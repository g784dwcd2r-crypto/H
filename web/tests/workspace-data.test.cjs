const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
function load(file, globals = {}) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports, URL, URLSearchParams, ...globals });
  return module.exports;
}
test('research pagination preserves the exact query and every filter without empty date parameters', () => {
  const { researchQuery } = load('lib/research.ts');
  const params = new URLSearchParams(researchQuery({ q:'"A & B" AND NOT risk',cik:'320193',form:'10-K/A',from:'2024-01-01',to:'',offset:0 },40));
  assert.equal(params.get('q'),'"A & B" AND NOT risk');
  assert.equal(params.get('cik'),'320193'); assert.equal(params.get('form'),'10-K/A');
  assert.equal(params.get('from'),'2024-01-01'); assert.equal(params.has('to'),false);
  assert.equal(params.get('offset'),'40'); assert.equal(params.get('limit'),'20');
});
test('source links reject script and data URLs', () => {
  const { safeSourceUrl } = load('lib/research.ts');
  assert.equal(safeSourceUrl('javascript:alert(1)'),null);
  assert.equal(safeSourceUrl('data:text/html,test'),null);
  assert.equal(safeSourceUrl('https://www.sec.gov/Archives/test.htm'),'https://www.sec.gov/Archives/test.htm');
});
test('PDF page offsets preserve supplementary Unicode without moving text across pages', () => {
  const { indexedPageTexts } = load('lib/research.ts');
  const pages = indexedPageTexts('A😀\n\n𠮷B', [{page:1,start:0,end:2},{page:2,start:4,end:6}]);
  assert.deepEqual(JSON.parse(JSON.stringify(pages)), [{page:1,text:'A😀'},{page:2,text:'𠮷B'}]);
});
test('document route parameters normalize one reserved-character encoding and reject malformed paths', () => {
  const { documentVersionParam } = load('lib/research.ts');
  const version = 'sha256:' + 'a'.repeat(64);
  assert.equal(documentVersionParam(version),version);
  assert.equal(documentVersionParam(encodeURIComponent(version)),version);
  assert.equal(documentVersionParam(encodeURIComponent(encodeURIComponent(version))),null);
  assert.equal(documentVersionParam('sha256%3A../../secret'),null);
  assert.equal(documentVersionParam('sha256%ZZ'),null);
});
test('edited source references cannot submit cached verification metadata as trusted evidence', () => {
  const { referencePointer } = load('lib/project-client.ts');
  const ref = referencePointer({ kind:'document',document_id:'doc',version_id:'sha256:version',status:'available',explanation:'Old status',source_url:'https://example.com',title:'Source' });
  assert.deepEqual(JSON.parse(JSON.stringify(ref)),{kind:'document',document_id:'doc',version_id:'sha256:version'});
  const financial = referencePointer({kind:'financial_snapshot',snapshot_id:'snap',issuer_id:'issuer',status:'available'});
  assert.deepEqual(JSON.parse(JSON.stringify(financial)),{kind:'financial_snapshot',snapshot_id:'snap',issuer_id:'issuer'});
});
test('a revision conflict is distinguishable from successful project persistence', async () => {
  const { projectRequest } = load('lib/project-client.ts',{ fetch:async () => ({ ok:false,status:409,json:async () => ({error:'conflict'}) }) });
  await assert.rejects(projectRequest('/a/notes/b','PATCH',{expected_revision:1}), error => error.status === 409 && /draft is still here/.test(error.message));
});
test('device labels are bounded browser hints without reflecting arbitrary user-agent text', () => {
  const { deviceLabel } = load('lib/device-label.ts');
  assert.equal(deviceLabel('Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/145.0 Safari/537.36'),'Chrome on macOS');
  assert.equal(deviceLabel('Mozilla/5.0 (Windows NT 10.0) Chrome/145.0 Edg/145.0'),'Edge on Windows');
  assert.equal(deviceLabel('<script>' + 'private'.repeat(1000)),'Browser');
});
test('filing cutoff validates calendar dates and stays outside saved export configuration', () => {
  const { validFilingDate } = load('lib/filing-cutoff.ts');
  assert.equal(validFilingDate('2024-02-29'),true);
  assert.equal(validFilingDate('2025-02-29'),false);
  assert.equal(validFilingDate('2025-13-01'),false);
  const { exportQuery, EXPORT_DEFAULTS } = load('lib/api.ts');
  const profile = {...EXPORT_DEFAULTS,as_of:'2020-01-01'};
  assert.equal(new URLSearchParams(exportQuery('320193',profile)).has('as_of'),false);
  assert.equal(new URLSearchParams(exportQuery('320193',profile,undefined,'2024-12-31')).get('as_of'),'2024-12-31');
  assert.equal(Object.hasOwn(EXPORT_DEFAULTS,'as_of'),false);
});

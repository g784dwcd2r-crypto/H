const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function load(relativePath, globals = {}) {
  const source = fs.readFileSync(path.join(__dirname, '..', relativePath), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports, ...globals });
  return module.exports;
}
function storage() {
  const map = new Map();
  return { get length() { return map.size; }, key(index) { return [...map.keys()][index]; }, getItem(key) { return map.get(key) ?? null; }, setItem(key,value) { map.set(key,value); }, removeItem(key) { map.delete(key); } };
}

test('SEC per-share facts keep their magnitude even when legacy unit is USD', () => {
  const { formatFinancialValue: fmt } = load('lib/number-format.ts');
  assert.equal(fmt(6.11, 'USD', 'millions', 'parentheses', 'EarningsPerShareBasic'), '6.11');
  assert.equal(fmt(6.08, 'USD/shares', 'billions', 'parentheses'), '6.08');
  assert.equal(fmt(-1.25, 'USD', 'thousands', 'parentheses', 'EarningsPerShareDiluted'), '(1.25)');
  assert.equal(fmt(391035000000, 'USD', 'millions', 'parentheses', 'Revenue'), '391,035');
  assert.equal(fmt(100000000, 'shares', 'millions', 'parentheses', 'WeightedAverageNumberOfDilutedSharesOutstanding'), '100,000,000');
});
test('missing, zero and negative values remain distinct', () => {
  const { formatFinancialValue: fmt } = load('lib/number-format.ts');
  assert.equal(fmt(null, 'USD', 'millions', 'parentheses'), '');
  assert.equal(fmt(0, 'USD', 'millions', 'parentheses'), '0');
  assert.equal(fmt(-1500000, 'USD', 'millions', 'minus'), '-1.5');
});
test('local statement and export scopes survive reload without losing colon-separated identities', async () => {
  const localStorage = storage();
  const client = load('lib/prefs-client.ts', { window: { localStorage } });
  assert.equal(await client.savePref({ scope:'statement', scope_key:'320193:IS', key:'scale', value:'billions' }, false), true);
  assert.equal(await client.savePref({ scope:'export', scope_key:'Model: annual', key:'profile', value:{ scale:'millions' } }, false), true);
  localStorage.setItem('fh:pref:company:123:broken', '{');
  assert.equal(await client.savePref({ scope:'global', scope_key:'', key:'period_mode', value:'annual' }, false), true);
  const prefs = JSON.parse(JSON.stringify(client.listLocalPrefs()));
  assert.deepEqual(prefs, [{scope:'statement', scope_key:'320193:IS', key:'scale', value:'billions'}, {scope:'export', scope_key:'Model: annual', key:'profile', value:{scale:'millions'}}, {scope:'global',scope_key:'',key:'period_mode',value:'annual'}]);
  assert.equal(client.readLocalPref('scale', {cik:320193,statement:'IS'}).value, 'billions');
});
test('failed browser persistence returns failure instead of a saved confirmation', async () => {
  const client = load('lib/prefs-client.ts', { window: { localStorage: { setItem() { throw new Error('Quota'); }, removeItem() { throw new Error('Blocked'); } } } });
  const pref = { scope:'global', scope_key:'', key:'scale', value:'millions' };
  assert.equal(await client.savePref(pref, false), false);
  assert.equal(await client.resetPref(pref, false), false);
});
test('rejected account writes remain unsuccessful', async () => {
  const client = load('lib/prefs-client.ts', { fetch: async () => ({ok:false}), URLSearchParams });
  const pref = { scope:'global', scope_key:'', key:'scale', value:'millions' };
  assert.equal(await client.savePref(pref, true), false);
  assert.equal(await client.resetPref(pref, true), false);
});

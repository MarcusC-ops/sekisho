import test from 'node:test';
import assert from 'node:assert/strict';
import { scenarios, scenarioFor, safeRunnerURL, confirmedTransaction, resetResult } from './state.mjs';
test('missing evidence and review pause, prohibited payment refuses', () => { assert.equal(scenarios.unavailable.verdict,'HOLD'); assert.equal(scenarios.review.verdict,'HOLD'); assert.equal(scenarios.refused.verdict,'BLOCK'); assert.match(scenarios.review.settlement,/No escrow deposit/); });
test('illustrations never provide invented transactions or source responses', () => { for (const s of Object.values(scenarios)) { assert.match(s.evidence,/Illustrative/); assert.equal(s.tx_hash,undefined); } assert.equal(scenarioFor('unknown'),scenarios.clear); });
test('runner configuration rejects unsafe transport and embedded credentials', () => { for (const value of ['javascript:alert(1)','http://example.com','https://key@example.com','https://example.com?token=secret','http://localhost:8000','https://localhost']) assert.equal(safeRunnerURL(value,'public.example'),null,value); assert.equal(safeRunnerURL('https://runner.example/','public.example'),'https://runner.example'); assert.equal(safeRunnerURL('http://127.0.0.1:8000/','localhost'),'http://127.0.0.1:8000'); });

test('transaction links require paid receipt state, not ALLOW or a transaction hash', () => { const tx_hash = '0x'+'a'.repeat(64); assert.equal(confirmedTransaction({verdict:'ALLOW',tx_hash}),null); assert.equal(confirmedTransaction({status:'unconfirmed',tx_hash}),null); assert.equal(confirmedTransaction({status:'paid',tx_hash:'javascript:alert(1)'}),null); assert.equal(confirmedTransaction({status:'paid',tx_hash}),`https://sepolia.basescan.org/tx/${tx_hash}`); });

test('new attempts remove previous report, payment links and successful result', () => {
  const elements = new Map();
  const doc = {getElementById(id) { if (!elements.has(id)) elements.set(id, {textContent:'previous paid result',hidden:false,href:'https://old-result.example',children:['previous confirmation'],removeAttribute(name) { delete this[name]; },replaceChildren() {this.children=[];}}); return elements.get(id); }};
  resetResult(doc);
  for (const id of ['result-summary','reason','raw-evidence','case-record','hash-status','canonical-report','purchased-data']) assert.equal(doc.getElementById(id).textContent,'',id);
  for (const id of ['sample-report','live-purchase','live-record','tx-link','case-link']) assert.equal(doc.getElementById(id).hidden,true,id);
  assert.equal(doc.getElementById('tx-link').href,undefined);
  assert.equal(doc.getElementById('case-link').href,undefined);
  assert.deepEqual(doc.getElementById('timeline').children,[]);
});

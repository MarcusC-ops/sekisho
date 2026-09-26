import { scenarioFor, safeRunnerURL, confirmedTransaction, resetResult } from './state.mjs';
import { publicRunnerURL } from './config.mjs';
const $ = id => document.getElementById(id);
let selected = 'clear', ready = false, busy = false, generation = 0;
const base = safeRunnerURL(publicRunnerURL, location.hostname);
const liveScenario = () => selected === 'clear' ? 'clean' : selected === 'unavailable' ? null : 'flagged';
const text = (id, value) => { $(id).textContent = value; };
function controls() { $('start').disabled = busy; $('start-live').disabled = busy || !ready || !liveScenario(); document.querySelectorAll('[data-scenario]').forEach(b => b.disabled = busy); }
function timeline(items) { $('timeline').replaceChildren(...items.map(([title, description]) => { const li = document.createElement('li'), heading = document.createElement('strong'), p = document.createElement('p'); heading.textContent = title; p.textContent = description; li.append(heading, p); return li; })); }
function reveal(title) { resetResult(document); $('results').hidden = false; text('result-title', title); $('result-title').focus(); }
function simulate() {
  const s = scenarioFor(selected); generation++;
  text('mode-label', 'Simulation · No money moves'); text('mode-description', 'Illustrative evidence and outcomes. No API calls, signatures or transactions.'); text('evidence-network', 'Illustrative only');
  reveal(s.result); text('result-summary', 'This entire result is an illustration, not a live test.'); text('verdict', `${s.verdict} · simulated`); text('reason', s.why); text('next', s.next);
  timeline([['Payment requested', 'An assistant requests the ETH/JPY market report for 0.05 test USDC.'], ['Risk evidence', s.evidence], ['Policy decision', `${s.verdict}: ${s.why}`], ['Payment signing', s.verdict === 'ALLOW' ? 'Illustration: the payment tool permits signing the matching request.' : 'Illustration: no payment signature is produced.'], ['Settlement', s.settlement], ['Case record', 'Illustrative result only. No recorded onchain hash or live case exists.']]);
  text('raw-evidence', JSON.stringify({mode:'simulation', scenario:selected, provider_response:'Illustrative only — no provider was contacted', verdict:s.verdict, reason:s.why, payment:{amount_usdc:'0.05',chain_id:84532,signature_created:false,transaction_sent:false,escrow_deposited:false}}, null, 2)); $('sample-report').hidden = s.verdict !== 'ALLOW';
}
async function request(path, options = {}) { const response = await fetch(`${base}${path}`, { ...options, credentials:'omit', signal:AbortSignal.timeout(15000) }); if (!response.ok) { const error = new Error(response.status === 429 ? 'Trial capacity reached. Please retry later.' : response.status === 503 ? 'The live runner is not ready. No simulation has been substituted.' : 'The runner could not complete this request.'); throw error; } return response.json(); }
async function checkReadiness() {
  ready = false; controls();
  if (!base) { text('live-status', 'Not connected yet. Simulation is available now; live testing needs a configured HTTPS public runner and verified credentials, contracts and funding.'); return; }
  $('live-check').disabled = true; text('live-status', 'Checking the live testnet runner…');
  try { const data = await request('/public/readiness'); ready = data.ready === true && data.mode === 'live' && data.network === 'Base Sepolia'; text('live-status', ready ? 'Testnet runner ready. Live calls use current risk evidence and a server-funded, limited Base Sepolia purchase. No wallet connection needed.' : `Live testing unavailable. ${(Array.isArray(data.blockers) ? data.blockers.map(b => b.message).filter(v => typeof v === 'string') : []).join(' ') || 'Required setup checks have not passed.'}`); }
  catch (error) { text('live-status', `${error.message} Simulation remains separately available.`); }
  finally { $('live-check').disabled = false; controls(); }
}
function renderLive(record) {
  resetResult(document);
  const r = record.result || {}; const verdict = ['ALLOW','BLOCK','HOLD'].includes(r.verdict) ? r.verdict : 'PENDING';
  text('verdict', `${verdict} · live`); text('reason', typeof r.reason === 'string' ? r.reason : 'Waiting for the runner’s recorded policy result.');
  text('result-summary', `Runner state: ${record.status}. A policy verdict and settlement are separate states.`);
  text('next', record.status === 'failed' || record.status === 'interrupted' ? 'The run did not finish normally. Do not infer payment success. Inspect the recorded state before starting another purchase.' : verdict === 'ALLOW' ? 'Inspect settlement evidence below. ALLOW alone does not prove that the seller was paid or delivered the report.' : verdict === 'BLOCK' ? 'The payment tool refuses this purchase. Try a different provider.' : verdict === 'HOLD' ? 'Signing is paused. A privileged operator must investigate; this public page cannot release funds.' : 'Waiting for evidence and policy evaluation.');
  timeline([['Payment requested', 'Preset 0.05 test USDC purchase on Base Sepolia.'],['Risk evidence', Array.isArray(r.checks) && r.checks.length ? 'Provider check results received. Inspect the recorded fields below.' : 'Waiting for required risk evidence.'],['Policy decision', verdict],['Payment state', typeof r.status === 'string' ? `${r.status}${r.settlement_reason ? ': ' + r.settlement_reason : ''}` : 'No completed payment state reported.'],['Case record', r.case_id ? `Recorded case: ${r.case_id}` : 'No case identifier reported yet.']]);
  // Do not display the private run capability in copyable evidence.
  const { run_id: _runCapability, ...publicRecord } = record;
  text('raw-evidence', JSON.stringify(publicRecord, null, 2));
  const txURL = confirmedTransaction(r);
  $('tx-link').hidden = !txURL; if (txURL) $('tx-link').href = txURL;
  if (r.case && typeof r.case === 'object') { $('live-record').hidden = false; text('case-record', JSON.stringify(r.case, null, 2)); $('case-link').href = '#live-record'; $('case-link').hidden = false; }
  text('hash-status', r.report_hash_verified === true ? 'Runner verified: the canonical report matches its recorded hash. This is a server-side consistency check, not an independent browser check or validation of risk-data truth.' : r.report_hash_verified === false ? 'Report consistency check failed. Do not rely on this report as matching the recorded fingerprint.' : 'No completed report consistency check supplied.');
  text('canonical-report', typeof r.canonical_report === 'string' ? r.canonical_report : 'No canonical report supplied.');
  if (txURL && r.purchased_data != null) { $('live-purchase').hidden = false; text('purchased-data', typeof r.purchased_data === 'string' ? r.purchased_data : JSON.stringify(r.purchased_data, null, 2)); text('result-summary', 'Testnet payment independently confirmed by the runner. The seller’s returned report is shown below.'); }
}
async function runLive() {
  if (!ready || busy || !liveScenario() || !base) return;
  busy = true; controls(); const current = ++generation;
  text('mode-label', 'Live · Base Sepolia testnet'); text('mode-description', 'Current provider evidence and a limited testnet run. No hidden simulation fallback.'); text('evidence-network', 'Mainnet risk data; testnet payment');
  reveal('Following the live purchase'); text('result-summary','Starting the preset purchase…'); text('verdict','PENDING'); text('reason','Waiting for the runner.'); text('next','Keep this page open while the test runs.'); timeline([['Requesting a run','No result has been received yet.']]); text('raw-evidence','No result received yet.');
  try {
    const random = () => [...crypto.getRandomValues(new Uint8Array(24))].map(b => b.toString(16).padStart(2,'0')).join('');
    let session = sessionStorage.getItem('sekisho-public-session'); if (!session) { session = random(); sessionStorage.setItem('sekisho-public-session', session); }
    // Keep a pending request key across network ambiguity: retrying must not create a second spend.
    const pendingKey = `sekisho-pending-${liveScenario()}`;
    let idempotency = sessionStorage.getItem(pendingKey); if (!idempotency) { idempotency = random(); sessionStorage.setItem(pendingKey,idempotency); }
    let record = await request('/public/runs', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario:liveScenario(),session_id:session,idempotency_key:idempotency})});
    if (!/^[a-zA-Z0-9_-]{16,128}$/.test(record.run_id || '')) throw new Error('Runner returned an invalid run identifier.');
    sessionStorage.setItem('sekisho-public-run',record.run_id); renderLive(record);
    for (let i=0; record.status === 'running' && i<80 && current === generation; i++) { await new Promise(resolve => setTimeout(resolve,1500)); record = await request(`/public/runs/${encodeURIComponent(record.run_id)}`); renderLive(record); }
    if (record.status === 'running') text('result-summary','The runner is still working. Retry uses the same pending request to avoid a duplicate purchase.');
    else if (record.status === 'completed') sessionStorage.removeItem(pendingKey);
  } catch (error) { text('result-summary',`${error.message} No live success is being claimed. Retry keeps the same request identifier.`); }
  finally { busy = false; controls(); }
}
document.querySelectorAll('[data-scenario]').forEach(button => button.addEventListener('click', () => { selected = button.dataset.scenario; document.querySelectorAll('[data-scenario]').forEach(b => b.setAttribute('aria-pressed',String(b === button))); $('results').hidden = true; controls(); }));
$('start').addEventListener('click',simulate); $('live-check').addEventListener('click',checkReadiness); $('start-live').addEventListener('click',runLive); checkReadiness();

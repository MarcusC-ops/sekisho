// Illustrative UI data only. This module never screens, signs, or moves funds.
export const scenarios = {
  clear: { label: 'Meets the policy', verdict: 'ALLOW', evidence: 'Illustrative required checks returned usable evidence, with no trigger in this demo policy.', why: 'The example recipient and payment meet the configured rules.', next: 'A real payment tool may now sign this exact payment. Only a confirmed receipt proves settlement.', result: 'Sample market report unlocked', settlement: 'Illustrative payment confirmation; no transaction was sent.' },
  refused: { label: 'Payment refused', verdict: 'BLOCK', evidence: 'Illustrative screening identifies a recipient prohibited by the demo policy.', why: 'The recipient triggers a blocking rule.', next: 'Choose another provider. No payment signature is produced for this request.', result: 'Purchase stopped before signing', settlement: 'Not attempted. No funds moved.' },
  review: { label: 'Human review needed', verdict: 'HOLD', evidence: 'Illustrative wallet history includes a mixer-related risk signal. This is not itself a sanctions designation.', why: 'The demo policy requires a person to review this signal.', next: 'An authorized operator reviews the case. This pause does not deposit funds into escrow or authorize a release.', result: 'Purchase paused for review', settlement: 'Not attempted. No escrow deposit exists.' },
  unavailable: { label: 'Evidence unavailable', verdict: 'HOLD', evidence: 'Illustrative provider timeout: required wallet-risk evidence is unavailable.', why: 'Missing evidence cannot become an automatic pass.', next: 'Retry screening after the provider recovers. The payment stays unsigned in the meantime.', result: 'Purchase paused: screening incomplete', settlement: 'Not attempted. No funds moved.' },
};
export function scenarioFor(id) { return scenarios[id] || scenarios.clear; }
export function safeRunnerURL(value, pageHostname = '') {
  if (!value) return null;
  try { const url = new URL(value); if (url.username || url.password || url.search || url.hash) return null;
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost','127.0.0.1'].includes(url.hostname) && ['localhost','127.0.0.1'].includes(pageHostname))) return null;
    if (['localhost','127.0.0.1','[::1]'].includes(url.hostname) && !['localhost','127.0.0.1'].includes(pageHostname)) return null;
    return url.href.replace(/\/$/, '');
  } catch { return null; }
}
// A verdict or a hash alone is never settlement proof.
export function confirmedTransaction(result = {}) {
  return result.status === 'paid' && /^0x[0-9a-fA-F]{64}$/.test(result.tx_hash || '') ? `https://sepolia.basescan.org/tx/${result.tx_hash}` : null;
}
// Clear every prior evidence/result field before another run or simulation.
export function resetResult(document) {
  for (const id of ['result-summary','verdict','reason','next','raw-evidence','case-record','hash-status','canonical-report','purchased-data']) document.getElementById(id).textContent = '';
  document.getElementById('timeline').replaceChildren();
  for (const id of ['sample-report','tx-link','case-link','live-record','live-purchase']) document.getElementById(id).hidden = true;
  for (const id of ['tx-link','case-link']) document.getElementById(id).removeAttribute('href');
}

import { scenarios } from './demo-data.mjs';
import { initialState, transition } from './demo-state.mjs';

const byId = id => document.getElementById(id);
let state = initialState();
const steps = ['Request', 'Evidence', 'Decision', 'Outcome'];
const labels = { 'intercepta.quick_scan': 'Wallet scan', 'sanctions.oracle': 'Sanctions oracle', 'trace.source_of_funds': 'Source of funds', 'intercepta.impersonation': 'Impersonation check', 'intercepta.token': 'Token check', 'intercepta.deep_scan': 'Deep scan' };
function paragraph(text, className) {
  const p = document.createElement('p');
  p.textContent = text;
  if (className) p.className = className;
  return p;
}
function render() {
  const scenario = scenarios.find(s => s.id === state.scenario);
  document.querySelectorAll('[data-scenario]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.scenario === state.scenario)));
  document.querySelectorAll('[data-step]').forEach(item => {
    if (Number(item.dataset.step) === state.step) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  });
  byId('demo-progress').textContent = `Simulation · Step ${state.step + 1} of 4 · ${scenario.label}`;
  byId('demo-title').textContent = ['An agent wants to pay.', 'What the screening found.', scenario.headline, 'What happens to the payment?'][state.step];
  const body = byId('demo-body');
  body.replaceChildren();
  byId('demo-verdict').hidden = state.step < 2;
  byId('demo-verdict').textContent = scenario.verdict;
  byId('demo-verdict').className = `verdict ${scenario.verdict.toLowerCase()}`;
  if (state.step === 0) {
    body.append(paragraph('A treasury agent requests market data. The vendor asks for 0.05 USDC through x402. Before creating a payment signature, the agent sends the counterparty to Sekisho.'));
    body.append(paragraph('Example payment · 0.05 USDC · Base Sepolia', 'demo-payment'));
    body.append(paragraph('Choose a wallet scenario above, then follow the evidence. All cases here are synthetic.'));
  } else if (state.step === 1) {
    const list = document.createElement('dl');
    list.className = 'demo-evidence';
    scenario.checks.forEach(check => {
      const row = document.createElement('div');
      const title = document.createElement('dt');
      title.textContent = labels[check.name] || check.name;
      const detail = document.createElement('dd');
      detail.textContent = `${check.status === 'error' ? 'Unavailable: ' : ''}${check.summary}`;
      row.append(title, detail); list.append(row);
    });
    body.append(list);
  } else if (state.step === 2) {
    body.append(paragraph('The deterministic policy produces this example verdict. An AI explanation cannot change it.'));
    const reasons = scenario.reasons;
    if (!reasons.length) body.append(paragraph('No policy rule triggered in this fixture. The verdict applies only to this request and the evidence available at screening.'));
    else {
      const list = document.createElement('ul'); list.className = 'demo-reasons';
      reasons.forEach(reason => {
        const item = document.createElement('li');
        const title = document.createElement('strong'); title.textContent = reason.label;
        item.append(title, paragraph(reason.detail)); list.append(item);
      });
      const first = list.firstElementChild;
      const primary = document.createElement('ul'); primary.className = 'demo-reasons';
      primary.append(first); body.append(primary);
      if (list.children.length) {
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = `View ${list.children.length} other triggered rules`;
        details.append(summary, list); body.append(details);
      }
    }
  } else {
    body.append(paragraph(scenario.outcome));
    if (state.resolution) body.append(paragraph(state.resolution === 'release' ? 'Simulated release: the officer authorizes payment to the vendor. A real release would require a successful testnet transaction and a recorded override.' : 'Simulated refund: the officer returns the held amount to the buyer. A real refund would require a successful testnet transaction and a recorded override.', 'demo-resolution'));
    body.append(paragraph('This walkthrough creates no transaction, attestation, or report hash. Live end-to-end proof is still pending.', 'demo-footnote'));
  }
  byId('demo-officer').hidden = !(state.scenario === 'mixer' && state.step === 3);
  document.querySelectorAll('[data-resolution]').forEach(button => button.disabled = Boolean(state.resolution));
  byId('demo-back').disabled = state.step === 0;
  byId('demo-next').textContent = state.step === 3 ? 'Restart example ↺' : `Next: ${steps[state.step + 1]} →`;
  byId('demo-announcement').textContent = `${scenario.label}. Step ${state.step + 1} of 4: ${steps[state.step]}.${state.step >= 2 ? ` ${scenario.verdict}.` : ''}${state.resolution ? ` Simulated ${state.resolution} complete.` : ''}`;
}
document.querySelectorAll('[data-scenario]').forEach(button => button.addEventListener('click', () => {
  state = transition(state, { type: 'select', id: button.dataset.scenario }); render();
}));
byId('demo-next').addEventListener('click', () => {
  state = transition(state, { type: state.step === 3 ? 'restart' : 'next' }); render();
  byId('demo-title').focus();
});
byId('demo-back').addEventListener('click', () => {
  state = transition(state, { type: 'back' }); render(); byId('demo-title').focus();
});
document.querySelectorAll('[data-resolution]').forEach(button => button.addEventListener('click', () => {
  state = transition(state, { type: 'resolve', value: button.dataset.resolution }); render();
  byId('demo-title').focus();
}));
byId('copy-sdk').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(byId('sdk-code').textContent);
    byId('copy-status').textContent = 'Copied Python example.';
  } catch {
    byId('copy-status').textContent = 'Clipboard unavailable. Select the code or download the example below.';
  }
});
render();
byId('demo-fallback').hidden = true;
byId('demo-interactive').hidden = false;
byId('copy-sdk').hidden = false;

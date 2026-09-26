import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, transition } from '../website/demo-state.mjs';
import { scenarios } from '../website/demo-data.mjs';

test('all four paths stay bounded and restart without previous officer action', () => {
  for (const scenario of scenarios) {
    let state = transition(initialState(), {type:'select', id:scenario.id});
    assert.equal(transition(state, {type:'back'}).step, 0);
    for (let i = 0; i < 5; i++) state = transition(state, {type:'next'});
    assert.equal(state.step, 3);
    const reset = transition({...state, resolution:'release'}, {type:'restart'});
    assert.deepEqual(reset, {scenario:scenario.id, step:0, resolution:null});
  }
});
test('release and refund exist only at the mixer outcome; cannot resolve twice', () => {
  for (const scenario of scenarios) for (let step = 0; step < 4; step++) {
    const state = {scenario:scenario.id, step, resolution:null};
    const next = transition(state, {type:'resolve', value:'release'});
    assert.equal(next.resolution, scenario.id === 'mixer' && step === 3 ? 'release' : null);
  }
  const held = {scenario:'mixer', step:3, resolution:null};
  const refunded = transition(held, {type:'resolve', value:'refund'});
  assert.equal(refunded.resolution, 'refund');
  assert.deepEqual(transition(refunded, {type:'resolve', value:'release'}), refunded);
  assert.equal(transition(refunded, {type:'back'}).resolution, null);
  assert.deepEqual(transition(refunded, {type:'select', id:'clean'}), initialState());
});
test('fixture excerpts retain fail-closed outcome and verbatim trait, omit live claims', () => {
  assert.deepEqual(scenarios.map(s => s.verdict), ['ALLOW','HOLD','BLOCK','HOLD']);
  assert.equal(scenarios[3].checks[0].status, 'error');
  assert.equal(scenarios[1].reasons[0].detail, 'The address has sent or received funds through a mixer service.');
  assert.ok(scenarios.every(s => s.checks.every(c => !('live' in c) && !('latency_ms' in c))));
});

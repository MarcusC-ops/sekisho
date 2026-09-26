// Presentation only. Never evaluates policy, screens a wallet, or signs a payment.
import { scenarios } from './demo-data.mjs';
export const initialState = () => ({ scenario: 'clean', step: 0, resolution: null });
export function transition(state, action) {
  if (action.type === 'select' && scenarios.some(s => s.id === action.id)) {
    return { scenario: action.id, step: 0, resolution: null };
  }
  if (action.type === 'restart') return { ...state, step: 0, resolution: null };
  if (action.type === 'next') return { ...state, step: Math.min(3, state.step + 1) };
  if (action.type === 'back') return { ...state, step: Math.max(0, state.step - 1), resolution: null };
  if (action.type === 'resolve' && state.scenario === 'mixer' && state.step === 3 && !state.resolution && ['release', 'refund'].includes(action.value)) {
    return { ...state, resolution: action.value };
  }
  return state;
}

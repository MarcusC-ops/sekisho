# Readiness and remaining work

Status as of 26 September 2026. Sekisho is a working testnet hackathon MVP, not a
production compliance service. Transaction links and dated observations are in
[LIVE-EVIDENCE.md](LIVE-EVIDENCE.md).

## Verified demonstration

| Capability | Evidence |
|---|---|
| Hosted browser purchase | A 0.05 test-USDC purchase settled on Base Sepolia and returned the seller's sample report. |
| Hosted refusal | A flagged purchase was refused before a payment signature was created. |
| Decision attestations | Both hosted decisions have confirmed registry attestations and indexed MultiBaas events. |
| Webhook delivery | Genuine MultiBaas deliveries reached the hosted gate. |
| Persistent trial limits | Completed runs and 100,000 atomic units of reservations survived redeployment. |
| Escrow contracts | A separate operator rehearsal verified deposit, premature-release rejection, clearance/release and refund. |

Try the [public application](https://sekisho-phi.vercel.app/try/). Its live actions
use a server-funded testnet wallet; visitors need no wallet or API key. Four separate
illustrative scenarios are explicitly labelled simulations. The operator console
and privileged gate endpoints remain private.

A HOLD verdict alone does **not** mean funds entered escrow. The full journey from a
live provider-triggered HOLD through the gate and escrow remains unverified. The
separate contract rehearsal must not be presented as proof of that journey.

## Recorded verification

The latest integrated backend verification recorded 485 passing Python tests.
Five trial-state tests passed after the public backend URL was configured. The
Render Docker build and hosted Chrome paid/refused flows succeeded. Earlier
contract verification passed 18 tests, including two 256-run fuzz checks; the console
production build, lint and 45 report-hash checks also passed. These are dated results,
not a claim that tests have been rerun after every documentation edit.

For a fresh checkout, use the commands in the [main README](../README.md),
[console README](../dashboard/README.md), and [public deployment guide](PUBLIC-TRIAL.md).
Unit tests mock upstream providers and do not replace live integration evidence.

## Before presenting or submitting

- Check the hosted readiness response, remaining trial allowance, provider quota and
  testnet balances. A configured service can still lose provider availability.
- Keep the paid/refused evidence available if live trial capacity is exhausted; do
  not reset the persistent database to evade budget limits.
- Review the public repository and its history for secrets before changing visibility.
- Complete truthful team, human-contribution and AI-assistance disclosures, sponsor
  feedback and submission fields. See [AI usage](ai-usage.md).
- Rehearse the final deck and record a human-narrated product demonstration.

## Remaining engineering scope

- Verify a genuine provider-triggered HOLD end to end.
- Measure performance over repeated live runs; individual observed timings do not
  establish p50/p95 targets.
- Production deployment requires a separate review of authentication, tenant
  isolation, signer custody, policy ownership, monitoring and operational recovery.
  The current public runner is a bounded, single-instance testnet demonstration.

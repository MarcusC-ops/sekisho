# Hackathon minimum viable submission

Target: Intercepta Safe Agent-to-Agent Payments and Curvegrid Best AI Agent Project.
The smallest convincing demo is S1 (live screening permits a settled payment) and
S3 (live screening blocks signing), with visible evidence and a MultiBaas attestation.
S2 escrow review is the next priority. Do not expand RWA or multi-chain scope.

## Acceptance checklist, in execution order

| Task | Done when | Current state |
|---|---|---|
| Payment boundary | Exact payee, amount, token, chain and direction bound before signing; shared spending caps | Implemented; regression tests |
| Provider failures | Empty/404/204 and unavailable Quick Scan cannot create a clean decision | Implemented; regression tests |
| Operator access | Review, reset and scenario launch reject missing/wrong credentials | Implemented; regression tests |
| Testnet restriction | Agent payments and backend contract writes reject non-Base-Sepolia chains | Implemented; regression tests |
| Provider setup | Intercepta live key and Base Sepolia MultiBaas deployment/API key work | MultiBaas authenticated on chain 84532; Intercepta pending |
| Wallet funding | Four distinct role wallets have Base Sepolia ETH; buyer has test USDC | Pending funding |
| Contract setup | Registry and escrow deployed/linked, roles correct, webhook indexed | Pending live setup |
| Counterparty selection | Actual Quick Scan responses for clean buyer/vendor and blocked vendor | Pending Intercepta key |
| S1 | Live outbound and inbound screening, one confirmed USDC payment, visible receipt | Pending live rehearsal |
| S3 | Live Intercepta evidence, BLOCK before signature, visible reason | Pending live rehearsal |
| Curvegrid proof | Actual registry transaction and indexed Screened event; report verifies | Pending live rehearsal |
| S2 enhancement | Actual deposit, officer release/refund, matching events | After S1/S3 |
| Submission | Public repo, team/socials, sponsor feedback, narrated video | Human inputs/publishing pending |

## Configuration

Use Base Sepolia, chain **84532**, `X402_NETWORK=eip155:84532`, canonical test USDC
`0x036CbD53842c5426634e7929541eC2318f3dCF7e`. Ethereum/Base mainnet endpoints are
read-only sources of risk information. No mainnet transaction is permitted.

1. Copy `.env.example` to `.env` only if `.env` does not already exist.
2. Save the MultiBaas deployment URL in `MB_URL` (without `/api/v0`). Create a backend
   **Administrators** API key and put it in `MB_ADMIN_API_KEY`.
3. Put the live Intercepta sandbox key in `INTERCEPTA_API_KEY`.
4. Set a separate random `SEKISHO_OPERATOR_TOKEN` and `MB_WEBHOOK_SECRET`. Never put
   provider credentials in `NEXT_PUBLIC_*`, source code, screenshots, or chat.
5. Run `make wallets` once; preserve those keys. Fund all four addresses with Base
   Sepolia ETH and the buyer with test USDC. Keep `.env` private and backed up locally.
6. For the initial deterministic payment rehearsal, use `LLM_PROVIDER=none`. To prove
   the actual AI-agent flow for Curvegrid, configure an existing supported model key
   and run the treasury agent after the payment paths are stable.

`python scripts/check_setup.py --minimum` checks the S1/S3 configuration without
requiring the optional Blockscout key or S2/S5 counterparty addresses. It remains an
offline check, not evidence that credentials work. The full `make check-setup` is for
the complete showcase. Keyless Blockscout tracing is available with reduced reliability.

## Live rehearsal

Use the commands in [SETUP.md](SETUP.md) to deploy/link contracts, start the gate,
register the webhook and Event Queries, start vendors and the console. Keep the gate
and control services on loopback. A public tunnel is for the webhook; for an internet
demo, restrict public ingress to `/webhooks/multibaas` rather than exposing the whole
operator/API surface. Operator authentication does not provide API quotas or tenancy.

```bash
.venv/bin/python scripts/check_setup.py --minimum
.venv/bin/python scripts/scan_candidates.py <real-mainnet-candidates> --max-calls 20
.venv/bin/python scripts/demo.py setup
.venv/bin/python scripts/demo.py S1
.venv/bin/python scripts/demo.py S3
.venv/bin/python scripts/smoke.py
```

The buyer must also receive an explicit successful clean scan for two-sided S1.
Do not fabricate clean results for a new wallet: a 404 is now unavailable evidence.
Ask Intercepta for supported clean/known-risk addresses if necessary. Do not disable
a warning-producing check just to obtain a green demo.

In the console, open **Operator access**, paste the local `SEKISHO_OPERATOR_TOKEN`,
and select **Use token**. It stays in this tab's memory and clears on reload. The
token is validated by the server when an action is submitted. No token is needed to
view the local console. Fixture mode remains synthetic and never qualifies as a live run.

For S2, select a real HOLD vendor, deposit, inspect the case, then release/refund with
an officer note. Verify the Screened report hash and escrow event links. Run S6 separately
with `FAULT_INJECT=intercepta_timeout`, then restore the normal setting.

## Evidence to save

- S1: case ID, complete live Intercepta response, report hash, USDC settlement tx,
  registry tx, indexed event, and successful report verification.
- S3: case ID, live Intercepta traits/reasons, verdict and agent log showing refusal
  before signing. Absence of a transaction hash alone does not prove no signature.
- S2 if included: deposit/release or refund hashes, hold ID, officer note, final state.
- Real model run: the task, tool calls, payment outcome, and the distinction between
  model advice and deterministic enforcement.
- A human-narrated recording of those real outcomes; keep the fixture preview labelled.

Rehearse the minimum flow twice. Record actual latency, not unit-test timings, as provider
performance. Keep raw provider descriptions unchanged. Never claim ALLOW guarantees safety.

## Submission packaging

Before submission, make the repository public after reviewing it for secrets. Add team
names/socials and 3–5 lines of genuine Intercepta feedback (time to first call, confusing
parts, missing features). Link directly to
`gate/sekisho_gate/screening/intercepta.py`, `sdk/sekisho/x402_hooks.py`,
`gate/sekisho_gate/chain/multibaas.py`, and the live contract/explorer records.
Add actual MultiBaas usage/feedback and complete the human review in `docs/ai-usage.md`.

Prize criteria: [Intercepta](https://ethglobal.com/events/tokyo2026/prizes/intercepta)
and [Curvegrid](https://ethglobal.com/events/tokyo2026/prizes/curvegrid).

## Deliberate limits

The demo accepts only canonical Base Sepolia USDC. The treasury reserves at most
**$1 per payment and $5 per TreasuryTools run**, including escrow deposits. Reservations
are retained on uncertain failures because a signature may settle later. Restarting
the process resets this budget; it is not a persistent organization-wide ledger.
Wallet risk and spending caps do not establish that an invoice is authorized.
The gate is a single-operator demo, not a production custodial service.


## Current local wallet funding

These fresh role wallets were generated for this checkout. Their private keys stay in
`.env`; preserve that file. All four need Base Sepolia ETH, and the buyer also needs
Base Sepolia test USDC. Latest checked balances were zero.

| Role | Public address |
|---|---|
| Deployer | `0x942F259eE6B8C307dd4d2c72A19dcCeab28fDfd7` |
| Screener | `0xbCebc3C468E054D3Aeb4bb6a40dDD7f76A11073D` |
| Officer | `0x65b31ea2568e6fF146f9274A457944e1d527A6AC` |
| Buyer | `0x575853600574495A0a9588536e155DddD809bD43` |

Use the [ETHGlobal Base Sepolia faucet](https://ethglobal.com/faucet/base-sepolia-84532)
and [Circle test USDC faucet](https://faucet.circle.com/), choosing Base Sepolia.

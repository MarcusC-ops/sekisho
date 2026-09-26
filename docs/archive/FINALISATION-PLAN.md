# Sekisho finalisation execution plan

26 September 2026. Owner: Codex for implementation/testing; team for credentials,
provider-account access, commercial facts and final submission.

## Definition of done

A new visitor understands the task, runs an isolated preset purchase in the browser,
sees live risk evidence before signing, and can distinguish a confirmed test-USDC
payment from a refusal or pause. The deck tells the same story. Automated tests alone
do not satisfy the live requirement.

| Order | Action | Acceptance evidence | Dependency |
|---|---|---|---|
| 1 | Reconcile local payment and authorization fixes with upstream | Combined regression suite, reviewed diff and narrow commits | None |
| 2 | Add `/try/` with four labelled simulation paths | Desktop/mobile/keyboard run, paid/refused/paused explanations, no fabricated explorer links | None |
| 3 | Add isolated public run API | Preset destinations, exact 0.05 USDC, one signature/run, no operator routes, session isolation | None |
| 4 | Persist public limits and idempotency | Repeated/concurrent requests and restart tests; hard global run/spend caps | None |
| 5 | Correct console claims | ALLOW shown as permission; HOLD distinct from confirmed escrow; no “losses prevented” counter | None |
| 6 | Prepare persistent backend container | Config validation, no credentials in image, private gate/vendors, durable `/data` | Host account for deployment |
| 7 | Rework 10-slide deck and narration | Problem/customer, stakes, honest market model, full journey diagram, real integration snippet and explicit proof status | None for draft; live results for final proof slide |
| 8 | Authenticate providers and select counterparties | Live Quick Scan bodies with timestamps, genuine reasons, usable clean buyer/vendor | Intercepta and MultiBaas keys |
| 9 | Verify funds/contracts/events | Base Sepolia balances, role checks, deployment receipts, indexed event and report hash | Testnet ETH/USDC and keys |
| 10 | Rehearse locally, then through hosted `/try/` | One confirmed ALLOW purchase and one live BLOCK/HOLD; failure-path tests; latency/call counts | 8–9 and host |
| 11 | Publish submission evidence | Public repo after secret/history review, team/socials, real sponsor feedback, demo video | Verified results and team inputs |

## Work boundaries

- Keep the existing engine, deterministic policy and vibrant identity.
- Mainnet endpoints supply read-only screening data. Payments remain Base Sepolia only.
- Unknown/missing provider evidence never becomes a clean result.
- Public HOLD pauses; the separate operator demonstration may deposit to escrow.
- Do not expose the privileged controller or the whole gate as the public trial API.
- Do not reset quota storage to recover a failed run: reconcile possible settlement first.
- Do not invent market size, clients, savings, provider performance or completed transactions.

## Pitch acceptance

Opening: an agent buying a five-cent report still needs its owner's recipient policy.
Primary buyer: teams building spending agents and x402 services. Institutions supply
risk and recordkeeping context, not an unsupported initial bank-sales claim.

The example follows a request through recipient screening, policy, signature and
settlement, with separate refusal and review branches. Integration shows the actual
payer hook and server-side requirements. Market sizing separates risk activity from
software revenue; any pricing/customer-count scenario is an explicit hypothesis.

## Items requiring team input

- Provider credentials stored privately, not pasted into chat or committed.
- Hosting login/billing if no connected persistent hosting account exists.
- Additional team names/socials and review attribution.
- Prospect conversations and pricing validation after the hackathon.

The authoritative live evidence log is [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md).
Deployment instructions are [PUBLIC-TRIAL.md](PUBLIC-TRIAL.md).

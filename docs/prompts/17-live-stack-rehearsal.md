# Live stack and rehearsal

User request to Claude Code (26 September 2026), verbatim:

> Repo: <local-repository> (Sekisho, GitHub <original-repository>, currently private). ETHGlobal Tokyo 2026 submission is due Sun 27 Sep 2026 09:00 JST (internal target 07:00). Read AGENTS.md first and follow its rules (fail closed, no mock mode in the running gate, testnet only, never a mainnet transaction, keys only in the git-ignored .env, never print or commit secrets, small commits).
>
> Situation: nothing has run live yet. There is no .env and `make check-setup` passes 6 of 20 checks (docs/readiness.md). Intercepta's prize ("Safe Agent-to-Agent Payments with x402") requires at least one LIVE keyed Intercepta call before a payment is signed or accepted whose result decides what happens next (mocked or hard-coded responses don't qualify), screening real mainnet addresses, and a demo showing one payment that goes through and one blocked or held with the reason visible. Curvegrid's judges expect real MultiBaas use (deploy/link, writes, webhooks, Event Queries).
>
> Goal: get the live stack working, rehearsed and documented with verified facts.
>
> 1. Ask the user for: the Intercepta sandbox key (intercepta.io/ethglobal), a MultiBaas deployment URL and admin API key (Curvegrid), a public webhook URL (tunnel) and secret. Run `make wallets` for fresh testnet role keys; the user funds them with Base Sepolia gas and Circle faucet USDC.
> 2. Get `make check-setup` to 20/20. Deploy and link the contracts (`make deploy`, forge-multibaas). Read docs/research/services.md items 7, 8 and 12 first: signedTx 0x prefix, forge-multibaas FFI linking during simulation (export MULTIBAAS_ALLOW_UPDATE_CONTRACT=true and MULTIBAAS_ALLOW_UPDATE_ADDRESS=true for re-runs), free-plan event indexing limits. Then `python scripts/setup_multibaas.py` for USDC, the webhook and saved Event Queries.
> 3. Use `scripts/scan_candidates.py` to pick the clean and mixer-exposed vendors from real Intercepta profiles, starting from the test addresses Intercepta pinned in its ETHGlobal Discord channel (ask the user for them). Capture real Intercepta response bodies to replace the synthetic profile fixtures, keeping provenance, capture time, HTTP status and verbatim trait descriptions.
> 4. Rehearse `make demo S=S1`, then S3, then S2 with an officer release in the console, then S4 and S5, and S6 separately under FAULT_INJECT=intercepta_timeout. Run `make smoke`. Measure the real latencies (PITCH_PLAN.md quotes 300 ms and about 2 s, which were never measured).
> 5. Replace the TODO comments in README.md (status line → Base Sepolia contract addresses and one ALLOW, one HOLD, one BLOCK case; Intercepta keyed time to first call; MultiBaas live-deployment notes) and the [TODO] markers in docs/SUBMISSION.md, using only verified facts. Update docs/readiness.md.
>
> Optional if time remains: add Intercepta Scan Message (https://docs.web3antivirus.io/reference/scan-message; append .md for markdown) on the EIP-3009 authorization before the payer signs, since Intercepta's brief asks for the payment authorization itself to be screened. gate/policy/policy.yaml is hashed byte for byte into policy_id: ask the user before changing it.
>
> Record this work's prompt in docs/prompts/ and docs/ai-usage.md (ETHGlobal AI rule). Commit small and often; the user has approved pushing small milestone commits to main for this repo.

## Plan

1. Install the toolchain in the worktree, generate the four role wallets (`make wallets`,
   addresses only), and ask the user for the service keys, the tunnel choice and the
   Intercepta test addresses. Secrets go straight into the git-ignored `.env`; nothing
   prints them.
2. Once the wallets are funded: deploy and link the contracts through forge-multibaas,
   then run `scripts/setup_multibaas.py` (USDC alias with sync off, webhook, Event
   Queries) and read the live plan limits.
3. Scan the candidate addresses with live Intercepta calls, choose the clean and
   mixer-exposed vendors, and replace the synthetic Intercepta fixtures with captured
   bodies (provenance, capture time, HTTP status, verbatim trait text).
4. Rehearse S1, S3, S2 (officer release in the console), S4, S5, then S6 under fault
   injection; run `make smoke`; record the measured latencies from the case timelines.
5. Fill the README and SUBMISSION TODOs and the readiness page from what actually ran.

Scope: live configuration, deployment, rehearsal and documentation. No change to
`gate/policy/policy.yaml` without the user's approval. Testnet only; screening reads
mainnet data but never sends a mainnet transaction.


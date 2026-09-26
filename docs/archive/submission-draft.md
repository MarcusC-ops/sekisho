# ETHGlobal Tokyo 2026 submission copy

Text for the ETHGlobal submission form, ready to paste. The [README](../README.md) is the
source of truth for claims; if one changes, update both. Items marked **[TODO]** need the
live testnet run or the team's own answers.

Form limits: the short description is capped at 100 characters. Showcase pages display the
description and "How it's made" in full; these drafts are about 1,200 and 1,900 characters.

## Project name

Sekisho

## Short description (91 characters)

> Screen the wallet before your AI agent pays: allow, hold in escrow, or block x402 payments.

Alternative (64 characters, from PRD 13.2): *The compliance checkpoint every AI agent payment passes through.*

## Description

AI agents are starting to pay each other in USDC over x402, often before anyone has looked
at the wallet on the other side. No bank or business can let an agent pay a counterparty its
compliance team would refuse.

Sekisho (関所, the Edo-era road checkpoint) sits in that payment path. Before the buyer agent
signs, and before the seller accepts, it screens the other wallet with Intercepta's live risk
scan, the Chainalysis sanctions oracle and a short source-of-funds trace. A deterministic,
versioned policy then decides. ALLOW: the agent signs. HOLD: the USDC waits in an onchain
escrow until a human compliance officer releases or refunds it. BLOCK: no signature is ever
produced. If the Intercepta scan or the gate fails, the payment is held, never allowed.

Every verdict and override is attested onchain through Curvegrid MultiBaas with a hash of the
exact evidence report, which the compliance console re-hashes in the browser. The AI writes
the case note; the policy decides, so a prompt-injected agent still cannot move money.

Sekisho ships as a Python SDK with x402 payer and payee hooks, an MCP server for any agent,
and a compliance console. It runs a testnet demo policy, not a certified AML programme or
legal advice.

## How it's made

The gate is Python 3.11 with FastAPI, Pydantic, SQLite and server-sent events. Each screen
calls Intercepta Quick Scan (always live for the direct counterparty), Scan Token and an
address-poisoning check; makes a keyless `eth_call` to the Chainalysis sanctions oracle on
Ethereum and Base; and traces one to two hops of inbound funds through Blockscout, including
internal transactions, which is how mixer withdrawals arrive. The policy is a YAML file whose
keccak hash is the `policy_id`. The strongest rule wins, and a failed Quick Scan fails closed
to HOLD.

The x402 v2 Python SDK's lifecycle hooks do the enforcing: `on_before_payment_creation` on
the buyer and `on_before_verify` on the seller call the gate, so screening lives in tool code,
not in a prompt. A per-payment spend cap in the x402 client is a second, independent guard.
One hack worth noting: x402's httpx client wraps the abort error, so the SDK walks `__cause__`
to recover the verdict and case ID for the agent.

The contracts are Solidity (Foundry, OpenZeppelin). `ComplianceRegistry` records verdicts and
report hashes; `ComplianceEscrow` holds USDC and refuses to release it to a payee without a
fresh ALLOW. There are 18 contract tests, including 2 fuzz tests. MultiBaas is our path
onchain: `forge-multibaas` links the contracts at deploy, every write is composed through its
REST API and signed locally, HMAC-verified webhooks drive case state, and Event Queries feed
the treasury view.

The console is Next.js 16, React 19 and viem. Its audit page re-hashes the served report
bytes and compares them with the hash recorded onchain; 45 parity checks keep Python and
browser hashing byte-identical. The AI analyst (Claude Haiku or GPT behind a provider switch)
writes an advisory note only after the verdict and hash exist. An MCP server exposes screening
to any agent. The team wrote the PRD; Claude Code and Codex built from it, and every prompt is
committed.

## Links

- Repository: <original-repository> **[TODO: make public before submitting]**
- Website and guided walkthrough: https://getsekisho.vercel.app
- Demo video: **[TODO]**

## Partner prizes

Select **Intercepta** and **Curvegrid**. One Curvegrid selection covers all three of its tracks;
lead with Best AI Agent Project, then Best Digital Asset Dashboard. Leave the third slot empty
unless a real integration lands (see [the third slot](#the-third-slot)).

### Intercepta: Safe Agent-to-Agent Payments with x402

**How we use it**

Sekisho puts Intercepta inside the x402 payment flow on both sides. Before our treasury agent
signs, the x402 payer hook (`sdk/sekisho/x402_hooks.py`) sends the vendor's `payTo` to the gate,
which calls Quick Scan Address (always live), Scan Token on the asset's mainnet equivalent and
an address-poisoning check (`gate/sekisho_gate/screening/intercepta.py`, `pipeline.py`). Before
a vendor accepts, it screens the payer the same way (`agents/vendors/app.py`, `on_before_verify`).
Intercepta's traits and toxic score feed a deterministic policy (`gate/policy/policy.yaml`):
hard-block traits mean BLOCK and no signature; hold traits such as mixer exposure mean HOLD, with
the USDC in an onchain escrow for a human officer; a failed scan means HOLD. Direct funders found
by the source-of-funds trace get a cached Quick Scan, and Deep Scan enriches held cases. The
console shows Intercepta's trait descriptions word for word. In the demo, a clean vendor is paid,
a sanctioned address is blocked before signing, and a mixer-exposed vendor is held until an
officer releases the funds.

**Feedback**

- Time to first call: quick. `/llms.txt` and the Markdown version of each docs page let our
  coding agents read the reference directly, and the auth error is clear.
  **[TODO: time from receiving the key to the first keyed response]**
- Confusing: one product with three names (intercepta.io, docs.web3antivirus.io,
  api.web3antivirus.io); docs.intercepta.io does not resolve.
- Missing: example response bodies for the address endpoints, and documented responses for a
  never-seen wallet and an exhausted quota. A fail-closed gate has to tell clean from unknown
  from out of quota.
- Would help most: a chain parameter on address scans, and one call that screens a whole x402
  payment (`payTo`, asset, amount and the EIP-3009 authorization).
- Ease of use rating: **[TODO: team's score]**

### Curvegrid: Best AI Agent Project (and Best Digital Asset Dashboard)

**How we use it**

MultiBaas is Sekisho's path onchain. `forge-multibaas` links `ComplianceRegistry` and
`ComplianceEscrow` at deploy (`contracts/script/Deploy.s.sol`). Every write (screening
attestations, officer overrides, the escrow deposit, release and refund) is composed through
the MultiBaas REST API, signed locally by the role's key, and submitted through MultiBaas
(`gate/sekisho_gate/chain/multibaas.py`, `attest.py`). HMAC-verified webhooks drive case state
(`gate/sekisho_gate/webhooks.py`), and saved Event Queries (`exposure_by_payee`,
`released_by_payee`) power the console's Treasury page.

AI Agent track: the treasury agent is a policy-aware transaction agent. It reads chain activity
through the source-of-funds trace and acts onchain under a policy with spending limits
(a per-payment cap, and a hold on a first large payment to a new counterparty), refused
counterparties and required human approval for held funds. Dashboard track: the console turns
each decision into an operational action (release or refund) with the evidence, treasury
exposure and an onchain audit trail in view.

**Feedback**

- Wins: every contract call is a REST call, so the Python gate needed no web3 stack for writes.
  Indexed events and webhooks replaced an indexer we would otherwise have written. The OpenAPI
  spec let us check request shapes before we had a deployment.
- Challenges: the docs' webhook sample and the spec disagree on the alias field (`addressLabel`
  or `addressAlias`); `GET /events` has no sort order and returns 10 rows by default, so we poll
  by transaction hash; Event Query `eventName` formats differ across official samples and result
  keys come back lowercased; `forge-multibaas` links aliases during simulation, so a failed
  broadcast leaves aliases pointing at nothing and re-runs return 409 without both allow-update
  flags.
- **[TODO: notes from the live deployment, plus the ease of use rating]**

### The third slot

Leave it empty: we only select partners whose tools Sekisho actually uses. If time allows after
the live run, add Intercepta Scan Message on the EIP-3009 authorization before signing, since
Intercepta's brief asks for the payment authorization itself to be screened.

## Demo video and live pitch

Use [PITCH_PLAN.md](../PITCH_PLAN.md): section 3 for the 4-minute live demo and section 4 for
the video. Correct these claims before recording:

| In the plan | Say instead |
|---|---|
| "Intercepta live scan, 300 milliseconds"; "about two seconds" | The latencies measured in the live run, as shown on screen |
| "That reason is Intercepta's own words" (S3) | Keep it only for live data: fixture traits are placeholder text |
| S4: "Suppose the model falls for it" | Keep "suppose": the demo forces the bad tool call unless a live LLM is used |
| "It matches the chain" | "It matches the hash recorded onchain" (the gate relays the MultiBaas event) |
| "What if Intercepta or the gate is down? It fails closed" | True for Intercepta and the gate; an oracle or trace failure alone doesn't hold the payment |

If asked who can release escrowed funds: only the officer role's key can sign a release onchain,
and the escrow refuses payees without a fresh ALLOW. The demo gate's decision endpoint has no
login; a deployment would put it behind the bank's single sign-on.

## Before submitting

1. Get the Intercepta key (intercepta.io/ethglobal; keys can take hours) and a MultiBaas
   deployment; `make check-setup` should pass 20 of 20.
2. Fund fresh Base Sepolia wallets (gas and Circle faucet USDC), then deploy and link the contracts.
3. Pick the clean and mixer-exposed vendors from real Intercepta profiles (`scripts/scan_candidates.py`),
   starting from the test addresses Intercepta pinned in its ETHGlobal Discord channel.
4. Rehearse S1 to S5, and S6 separately. Capture one raw Intercepta response with its latency.
5. Record the video: human voice, 2 to 4 minutes, at least 720p, no speed-up.
6. Fill the README TODOs (video link, contract addresses, one case per verdict, team handles,
   keyed time to first call), "Team review" in [ai-usage.md](ai-usage.md), and the PRD
   provenance note.
7. Make the repository public. Every GitHub link on the website returns 404 until then.
8. Submit with Intercepta and Curvegrid selected, pasting the answers above.


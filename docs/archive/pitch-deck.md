# Wallet Audit Trail
## Pitch deck for ETHGlobal Tokyo 2026

**Target tracks**
- Intercepta — Safe Agent-to-Agent Payments with x402
- Curvegrid — Best Digital Asset Dashboard

**Core message:** Before money moves, Wallet Audit Trail turns wallet risk into an explainable, time-bound, auditable decision.

---

## Slide 1 — The payment problem
### Sending crypto is easy. Knowing whether to send it is not.

- A user or agent receives a payment request.
- The recipient address may be unfamiliar, exposed to suspicious activity, or incorrectly flagged.
- Existing checks are fragmented, opaque, and difficult to reconstruct later.
- A blocked payment without an explanation is frustrating; an approved payment without evidence is risky.

**Speaker note:** We are not trying to label wallet owners or declare guilt. We are solving the decision moment immediately before payment.

---

## Slide 2 — Our solution
### Wallet Audit Trail: evidence before payment

A screening and audit layer for crypto payments that:

1. Checks the recipient wallet and payment intent.
2. Combines live risk signals with bounded on-chain transaction evidence.
3. Explains the reasons behind `ALLOW`, `HOLD`, or `DENY`.
4. Preserves the assessment, evidence, policy version, and decision history.

**One-line pitch:** Give every crypto payment a reasoned, reproducible pre-flight check.

---

## Slide 3 — Who needs it?
### One infrastructure layer, three users

| User | Need | Product outcome |
|---|---|---|
| Individual sender | “Can I trust this recipient enough to pay?” | Understandable wallet result |
| Business or AML reviewer | “Why was this payment held?” | Evidence-linked case and export |
| Agent or payment platform | “Should my signer accept this request?” | Machine-readable policy decision |

**Initial buyer hypothesis:** crypto-payment providers, agent-payment facilitators, wallets, and businesses operating stablecoin payouts.

---

## Slide 4 — Product flow
### From payment request to accountable decision

1. Receive the exact payment intent: chain, token, amount, payee, nonce, expiry, and resource.
2. Validate the address and supported network.
3. Run a live risk-provider check.
4. Retrieve bounded transaction evidence and reviewed findings.
5. Apply deterministic rules and coverage checks.
6. Return `ALLOW`, `HOLD`, or `DENY` with reasons.
7. Sign only when the intent is unchanged and the policy permits it.
8. Save the decision and later settlement evidence.

**Visual suggestion:** `Request → Screen → Explain → Policy → Sign / Hold / Refuse → Audit`.

---

## Slide 5 — What makes the result trustworthy?
### We separate risk, coverage, and policy

- `LISTED`: exact match in a current, approved source.
- `SUSPICIOUS`: supported rule or reviewed evidence indicates elevated risk.
- `NO_DETECTED_RISK`: required MVP checks completed without a trigger.
- `UNKNOWN`: required data is missing, stale, unsupported, or contradictory.

Payment actions are separate:

- `ALLOW`: checks complete, no detected trigger, limits satisfied.
- `HOLD`: suspicious signal, stale evidence, incomplete checks, or unresolved conflict.
- `DENY`: current actionable exact match or reviewed malicious finding.

**Important:** “No detected risk” is not “safe.” The UI shows scope, freshness, and limitations.

---

## Slide 6 — Evidence, not an opaque score
### Every reason points to inspectable data

For the demo, the engine checks:

- Current source matches with source, category, and freshness.
- Direct outbound exposure to a reviewed or sourced high-risk address.
- A bounded rapid-forwarding pattern using supported USDC activity.
- Analyst-reviewed findings and their correction history.

Each finding includes:

- Transaction hash and event index.
- Direction, token, amount, block/time, and finality.
- Rule version and evidence references.
- Coverage boundaries, including truncation and unchecked counterparties.

**Speaker note:** These are provisional deterministic heuristics, not an AML conviction or an accuracy claim.

---

## Slide 7 — Intercepta track
### Safe agent-to-agent payments with x402

**The trust moment:** an agent is about to pay an unknown service or recipient.

Our integration:

- Screens the actual `payTo` address before signing.
- Checks the token and payment authorization against the intended payment.
- Enforces amount, chain, token, expiry, and recipient policy.
- Allows one payment to proceed.
- Holds or refuses a risky payment before the signer is called.
- Displays the reason and records the decision.

**What judges should see:**

1. A valid request → live check → `ALLOW` → signed testnet payment → resource delivered.
2. A risky request → live check → `HOLD` or `DENY` → zero signing attempts.

**Partner proof:** live Intercepta API call, visible verdict, blocked/held path, public implementation file, and integration feedback.

---

## Slide 8 — Curvegrid track
### A digital-asset dashboard that leads to action

Most dashboards show balances. Wallet Audit Trail shows operational decisions.

Dashboard views:

- Wallet and payment-intent overview.
- Risk verdict, severity, freshness, and coverage.
- Transaction evidence and one-hop counterparties.
- Review queue for pending, disputed, stale, and corrected findings.
- Audit export with rule, source, evidence, policy, and timestamps.
- Optional watchlist and reassessment status.

**Why this is useful:** a payment operator can move from “something looks wrong” to “here is the evidence, here is the policy action, and here is the record we can hand to a reviewer.”

---

## Slide 9 — Demo script
### Four minutes, one clear story

**0:00–0:20 — Problem**
- “Agents can pay automatically, but they cannot automatically understand who they are paying.”

**0:20–1:05 — Live screening**
- Enter an Ethereum address.
- Show progress, live provider result, coverage, and verdict.

**1:05–1:55 — Evidence**
- Open the flagged transfer.
- Show the direction, amount, counterparty, rule, source, and explorer link.

**1:55–2:40 — Correction and audit**
- Open the clearly labelled synthetic review case.
- Correct a false-positive finding.
- Show that the current result changes while the previous decision remains in history.

**2:40–3:30 — Intercepta payment gate**
- Show allowed payment and then held/refused payment.
- Prove the risky path never calls the signer.

**3:30–4:00 — Close**
- Show dashboard/export.
- State what is implemented and what is deliberately out of scope.

---

## Slide 10 — Technical architecture
### Modular enough for a weekend; structured enough to adopt

```text
Dashboard / Agent
       |
Screening & Payment API
       |
Assessment jobs + policy engine
   /          |             \
Risk adapter  History/RPC     Registry + audit DB
       |
   Intercepta
       |
 Guarded signer / x402 flow
```

**Implementation principles:**

- Backend owns provider keys, policy decisions, and signer controls.
- Adapters normalize upstream responses; unknown fields do not become “safe.”
- Evidence is stored with source and retrieval timestamps.
- Payment approval is bound to a hash of the full intent.
- Results are asynchronous and preserve retries without duplicating evidence.
- Synthetic fixtures are separate from live findings.

---

## Slide 11 — Why this can be adopted
### Start as a decision API, not a replacement for a payment system

A company can integrate one endpoint before its existing signer or payment facilitator:

```text
POST /v1/payment-decisions

Input:
chain_id, payTo, token, amount, nonce, expiry, resource

Output:
ALLOW | HOLD | DENY
reasons, evidence_ids, coverage, expiry, policy_version
```

Adoption path:

1. Dashboard for analysts and operators.
2. API for pre-payment screening.
3. Guarded signer or x402 middleware.
4. Watchlists, scheduled rescans, and review workflows.
5. Production-specific retention, access control, and regulatory processes.

**Commercial value:** reduce avoidable payment risk while making decisions explainable to operators and customers.

---

## Slide 12 — What is novel?
### Not another blacklist. Not another wallet dashboard.

- **Decision-bound:** evaluates the exact payment, not just an address in isolation.
- **Explainable:** every action resolves to evidence, rule, or policy.
- **Time-bound:** stale or changed evidence cannot silently authorize payment.
- **Correctable:** reviewers can clear an error without erasing history.
- **Honest about uncertainty:** incomplete data produces `UNKNOWN` or `HOLD`, not a fabricated confidence score.
- **Composable:** dashboard, API, and agent gate use the same assessment record.

---

## Slide 13 — Limitations and responsible scope
### Trust comes from saying what we do not know

- Ethereum-first MVP; not full-chain or cross-chain tracing.
- Last 30 days and bounded event/counterparty coverage.
- Heuristics are demo rules, not validated AML thresholds.
- Public transaction proximity does not prove ownership or criminal conduct.
- `NO_DETECTED_RISK` is not a safety guarantee.
- No custody, automatic regulatory filing, or mainnet payment execution in the MVP.
- Statistical confidence remains unavailable until independently labelled data and validation exist.

**Speaker note:** This is a feature for judges: we can explain the system’s boundaries instead of hiding them behind a score.

---

## Slide 14 — How we measure success
### A good decision is traceable, not merely fast

Hackathon acceptance targets:

- A live bounded assessment completes in the deployed demo environment.
- Every displayed reason maps to evidence and a rule/source.
- A correction updates current results while retaining history.
- A risky payment produces zero signer calls.
- A saved assessment can be reproduced from normalized evidence and its ruleset.
- API and export expose coverage, freshness, expiry, and policy version.

Post-hackathon metrics:

- Unknown/partial assessment rate.
- Provider failure and latency.
- Review backlog and correction time.
- Reviewer reversal rate.
- Independently adjudicated precision, recall, abstention, and false-positive rate.

---

## Slide 15 — The ask / closing
### Let every payment carry its own evidence

Wallet Audit Trail helps people and agents answer one question before money moves:

> **“What do we know about this payment, why do we know it, and what should happen next?”**

We are submitting to:

- **Intercepta:** because the product makes screening part of the payment decision before signing.
- **Curvegrid:** because the product turns wallet data into an operational, reviewable digital-asset dashboard.

**Final line:** Safer onchain payments do not require pretending that uncertainty disappears. They require making uncertainty visible before the transaction is signed.

---

# Appendix A — Judge Q&A

## Why not just use a blacklist?

A blacklist does not explain coverage, freshness, evidence, correction history, or what to do when the address is unknown. We preserve source attribution and distinguish exact listings from heuristic indicators.

## Does a suspicious flag prove wrongdoing?

No. It is a screening signal requiring context and review. We explicitly avoid identity claims, conviction language, and unjustified probability scores.

## What happens when the risk provider is unavailable?

The assessment becomes partial or unknown. In the payment flow, a missing required check produces `HOLD`; it never silently becomes `ALLOW`.

## How do you stop a changed payment from reusing approval?

The approval is bound to the exact chain, recipient, token, amount, authorization payload, nonce, expiry, and payment-intent hash. Any change or expiry requires a fresh check.

## Why should an agent need this?

An agent can execute instructions quickly but may not understand counterparty risk. The gate lets the owner define what the agent may pay, which checks are required, and when a human must intervene.

## Are you claiming regulatory compliance?

No. This is a screening and decision-support layer. A production deployment would need jurisdiction-specific legal, compliance, privacy, retention, and source-licensing review.

## What is genuinely live in the demo?

State this precisely during judging: live provider call, actual normalized history response, deployed rules, saved audit record, and—if claiming the Intercepta prize—live pre-sign screening with one allowed and one held/refused payment. Do not present mocked provider responses as live integration.

## Why does the Curvegrid dashboard matter?

It is not only a portfolio display. It connects holdings and transfers to an actionable operational decision, evidence, review state, and reproducible export. A company can use it to investigate and then integrate the same decision through the API.

## Why not include AI?

The safety-critical verdict is deterministic and evidence-linked. AI may help summarize structured evidence later, but it should not invent reasons, set risk status, approve payments, or execute instructions from untrusted reports.

---

# Appendix B — Submission checklist

- [ ] Public repository with incremental commit history.
- [ ] README with setup, test, architecture, supported coverage, limitations, and exact integration files.
- [ ] PRD, prompts, specifications, and planning artifacts included where required.
- [ ] AI assistance attributed by file or asset; team contributions described.
- [ ] Live provider/API call demonstrated where the selected prize requires it.
- [ ] Synthetic fixtures visibly labelled and separated from live findings.
- [ ] Intercepta: one allowed and one held/refused payment; risky path calls signer zero times.
- [ ] Curvegrid: useful dashboard, export, setup/testing instructions, and any required integration feedback.
- [ ] Four-minute presentation rehearsed; optional video is 2–4 minutes, at least 720p, and human-narrated.
- [ ] Submission buffer before Sunday, 27 September 2026, 09:00 JST / 08:00 Singapore time, subject to dashboard confirmation.

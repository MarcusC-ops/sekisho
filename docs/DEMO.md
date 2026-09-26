# Demonstration guide

Use [the public trial](https://sekisho-phi.vercel.app/try/), supported by
[recorded transaction evidence](LIVE-EVIDENCE.md). The complete video should fit
within four minutes and use the presenter's own voice.

## Suggested 3:30 sequence

| Time | Show | Say |
|---|---|---|
| 0:00–0:25 | Project / payment diagram | An agent can buy data automatically, but its owner needs control over whom it pays. Sekisho checks before signing. |
| 0:25–0:55 | Evidence → policy → payment diagram | Intercepta supplies risk evidence; deterministic rules decide; MultiBaas records decisions and delivers events. |
| 0:55–1:45 | Standard-vendor trial | Run the real testnet purchase. Show ALLOW, PAID, the exact receipt and the returned sample report. ALLOW alone is not settlement. |
| 1:45–2:30 | Flagged-recipient trial | Show live risk reasons, BLOCK and REFUSED. No payment signature is created. The audit attestation is separate from a payment transaction. |
| 2:30–3:00 | Evidence links / SDK example | Both parties can screen at the payment boundary. Report hashes preserve byte consistency; transaction receipts establish settlement. |
| 3:00–3:30 | Scope and next step | Hosted payment/refusal is verified. Escrow release/refund passed separately; full provider-triggered HOLD remains unverified. Seek design partners running paid agent services. |

## Before recording

Check readiness, provider quota and testnet funds. The public runner uses persistent
limits: do not exhaust them through repeated practice. Use clearly labelled recorded
proof for rehearsal, and preserve sufficient capacity for judges. Do not delete the
trial database to evade those limits.

Record the application at 720p or above with a human narrator. Cut waiting rather than
speeding up footage. If showing recorded results, call them recorded results. Never
label simulations as live provider/payment evidence.

## Useful answers

**Why more than an API wrapper?** The provider supplies signals; Sekisho applies policy,
binds the decision to the payment terms, enforces it at signing/acceptance, and connects
it to settlement and an audit record.

**Does the hash prove a wallet is safe?** No. It proves consistency of report bytes.
Provider evidence, policy judgment and successful payment settlement are separate facts.

**Is this bank-ready?** No. This is a bounded testnet prototype. Production custody,
tenancy, policy ownership, operations and compliance validation are separate work.

**What is unfinished?** Full live provider-triggered HOLD through escrow, broader
performance measurement and production operational readiness.

Market/customer/pricing examples are hypotheses. Do not call illustrative revenue
arithmetic a measured addressable market or existing traction.

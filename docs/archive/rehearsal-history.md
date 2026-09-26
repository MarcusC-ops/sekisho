# Live evidence record

**Current status: hosted browser payment and refusal verified, with confirmed registry attestations and genuine MultiBaas webhook delivery. Operator escrow release/refund is verified; a provider-triggered full-gate HOLD remains pending.**
The dated sections below preserve earlier failures and limitations; they are historical,
not the current deployment status.
Do not replace pending items with unit-test results or simulation screenshots.

## Hosted Chrome acceptance — 26 September 2026, 12:28 UTC

Public page: https://sekisho-phi.vercel.app/try/ . Restricted backend:
https://sekisho-trial.onrender.com . Website commit `cfb4b272e9edbabe8f1956d0e52dd8b0a0c08210`.
The operator approved server-side credentials and testnet signing; visitors need no wallet or API key.

| Evidence | Clean preset | Flagged preset |
|---|---|---|
| Decision UTC | 12:28:16 | 12:28:55 |
| Case | `cs_01M3EV007YAR0QBM9XM8T86055` | `cs_01M3EV1301FFKZZ9STRDVYKGXA` |
| Live Quick Scan | score 0, no traits | score 100; known_scammer, sanction_address, blacklist |
| Sanctions oracle | negative on Ethereum and Base | positive on Ethereum and Base |
| Result | ALLOW → PAID; exact 0.05 test USDC, seller sample report delivered | BLOCK → REFUSED; no payment signature or payment transaction |
| Canonical report hash | `0x89b5a42ed9d226dc3f4088dd11bb1c7353f281a874585c8f9a2be1f11800563a` | `0x878ecb256dc5dba0127a0e2ea7a795bd50ec6e0ab952d1c02447c5c28f3440aa` |
| Hash check | runner verified exact canonical bytes | runner verified exact canonical bytes |
| Registry event | confirmed Screened matches case/report | confirmed Screened matches case/report |
| Actual webhook delivered UTC | 12:28:18.325095 | 12:28:58.352609 |

- [Hosted payment receipt](https://sepolia.basescan.org/tx/0xc8f523ae7b729e0f34f9d3bd433a9508a209eb11fa328d8c77424ec021e8d4f7).
- [Clean attestation](https://sepolia.basescan.org/tx/0x57b2cc0aa1f961a4b3fb724719b83b7791b4d05034e8642f1aa1a3b5e9643a3c).
- [Refused-decision attestation](https://sepolia.basescan.org/tx/0x7a50948b410acd04deb57d7035097ccda99251f854e892069043fb5863e7dc23).

The first browser request encountered a deployment interruption. Retrying reused the
same idempotency key; the recorded clean run completed once. A startup oracle timeout
was preserved in logs; the next startup self-test and both actual trial oracle checks passed.
The returned market report is labelled sample data, not a live market quote.
The clean source trace had no priced inbound history; this is not proof of wallet safety.
The flagged trace reported 4.59% taint of approximately $754.6m sampled inbound value,
3 of 5 top senders flagged and hop 2 on 2 paths, subject to the report's sampling/pricing limits.
Both public reports preserve provider evidence; no simulation fallback was used.
Delivery evidence comes from MultiBaas webhook history (`deliveredAt`) for the exact
successful attestation transactions, not a fabricated webhook POST.
Operator routes remain private; unsigned webhook requests return 401.
After the proof-panel redeployment, a read-only Render shell query confirmed exactly
two completed stored trials, with the same clean/refused case IDs and 100,000 atomic
test-USDC reserved against the global allowance. The initial request retry did not
create a third run. No private run capability, session ID, IP or credential was printed.

## Earlier local rehearsal evidence (before contracts and hosting)

| Evidence | Allowed purchase | Refusal or pause |
|---|---|---|
| UTC decision and source commit | 2026-09-26 11:38:23 UTC; 0f2ae6c | 2026-09-26 11:38:52 UTC; 0f2ae6c |
| Public run/case identifiers (redact bearer run capability from shared logs) | Pending | Pending |
| Actual recipient and screening network | Pending | Pending |
| Quick Scan HTTP status, timestamp, verbatim traits | Pending | Pending |
| Policy version/hash and decision reason | Pending | Pending |
| Signing result (permitted / no signature) | EIP-3009 authorization created | BLOCK; no signature produced |
| Base Sepolia receipt and matching USDC Transfer | Confirmed, 50,000 atomic USDC | No transaction |
| Purchased report delivered | ETH/JPY vendor JSON returned | Not expected |
| Canonical report hash consistency | Match | Match |
| MultiBaas attestation receipt + indexed Screened event | Pending | Pending |
| Elapsed time and provider calls consumed | Pending | Pending |

A transaction hash alone is not settlement evidence. Match a successful receipt to
the configured buyer, exact preset recipient, canonical test USDC and 50,000 atomic
units. A hash match proves consistency of the served report, not truth of the provider.

## Rehearsal checklist

1. Run `.venv/bin/python scripts/check_setup.py --minimum` (offline config only).
2. Validate credentials and supported real mainnet profiles; do not synthesize clean
   data for an unknown buyer. Set vendor recipients only from reviewed profiles.
3. Confirm Base Sepolia chain 84532, role-wallet balances and contract addresses.
4. Deploy/link contracts, register the webhook and saved MultiBaas queries, and run
   `.venv/bin/python scripts/smoke.py`. Keep all privileged endpoints private.
5. Run S1 and S3 locally; collect actual results. If evidence produces HOLD instead
   of the expected verdict, investigate it; do not edit policy merely for a green demo.
6. Only after this evidence is reviewed, enable the public runner and repeat the
   allowed/refused path through the browser, within its fixed testnet limits.
7. Verify provider 401/429/timeout/malformed data fails closed with controlled tests.
   Do not deliberately exhaust the real sponsor quota.
8. For the separate escrow showcase, prove deposit, officer authorization, fresh
   clearance and release/refund receipts. Public HOLD by itself is not an escrow demo.
9. Replace the pitch proof slide with measured results and record new narration.

## Sponsor feedback (write after live use)

Intercepta feedback from the 26 September preflight:
- Live Quick Scan returned HTTP 200 with score/traits for the configured flagged example and explicit zero-score responses for buyer and fresh merchant.
- Verbatim trait descriptions make the refusal explainable without a generated risk interpretation.
- One subsequent direct scan exceeded the application’s 3-second budget; a traced funder returned HTTP 404. The application preserves unavailable evidence rather than fabricating a clean profile.
- Actual payment hooks subsequently ran for two clean purchases and one refusal, as recorded below. Hosted browser execution remains pending.
Curvegrid: pending actual API/event-query/webhook feedback.
Team review and names/socials: pending confirmation.

## Provider preflight — 26 September 2026, about 11:35 UTC

- Intercepta: live HTTP 200 flagged scan, score 100, traits known_scammer,
  sanction_address and blacklist. Buyer and fresh merchant each returned explicit
  score 0 with no traits. A later flagged direct request timed out; the sanctions
  oracle still flagged that candidate. These are separate observations.
- Blockscout: authenticated Ethereum address-transactions HTTP 200, valid items list.
- MultiBaas: currentuser HTTP 200; linked address inventory empty.
- Payment RPC: chain 84532. Buyer balance 20 test USDC. All four role wallets had
  zero ETH; deployment and registry/escrow writes remain blocked on funding.
- Fresh merchant: 0xAb861a9FD96Db82A58D67fD75D14A210Eb439Bc1; its key remains
  only in ignored .env. No mainnet transactions are authorized.
- Bounded candidate scan used 8 Intercepta requests including traced funders.
  Merchant and buyer preliminary policy prediction ALLOW; flagged candidate BLOCK.
  This scan excludes impersonation/token checks and does not sign or settle.
- Base-mainnet oracle request encountered HTTP 429 for the buyer. Preserve this
  limitation; do not report every supporting check as successful.

Raw local scan_results.json is gitignored. Public evidence above omits credentials.

Additional read-only preflight: merchant impersonation scan HTTP 200, no poisoning
lookalike; mainnet-equivalent USDC token scan HTTP 200, neutral/info, riskScore 0.
The configured x402 facilitator's `/supported` returned HTTP 200 and lists v2 exact
payments on eip155:84532. These checks establish supported interfaces, not settlement.

## Actual local payment and refusal — 26 September 2026

**Paid case:** `cs_01M3ER4NQ8A4X3H58QP4SYRAJX`, ALLOW then PAID.
The buyer signed one EIP-3009 authorization; the vendor screened the buyer ALLOW
and delivered its market-report JSON. Exact 0.05 test USDC moved to the configured
merchant on Base Sepolia.

[Payment receipt](https://sepolia.basescan.org/tx/0x5b1ddf417e0ea9f77fff1e3e4ae8bbb913fed94d3a8184f84be412ffee7dc42a).
Initial case reporting returned 502 because the RPC exposed the receipt before its
block timestamp. Retrying the **same existing transaction report**, without another
signature or payment, returned 200 and PAID after independent receipt verification.
The first scripted S1 attempt therefore failed its PAID-state assertion; the payment
was subsequently reconciled. This failure must remain in the rehearsal record.

**Refused case:** `cs_01M3ER5EBB3D3343AAV623XVD6`, BLOCK then REFUSED.
Live Intercepta Quick Scan returned score 100 with known_scammer, sanction_address
and blacklist; both sanctions-oracle checks were positive. Treasury produced no
payment signature or transaction. Scripted S3 passed all 3 assertions.

Observed decision times were 1462 ms (paid case) and 5190 ms (refused case); live direct
scan times 1406 ms and 1104 ms respectively. These are two observations, not p50/p95 or
a performance guarantee. Supporting token/impersonation results may be cached and
are labelled in the recorded checks. Both canonical reports match their served hash.

Both registry attestations failed because no contract is linked/deployed in MultiBaas.
Do not present report consistency as successful onchain attestation. These are local
service runs, not yet proof of the hosted browser path or escrow review/release.

### Second paid rehearsal and remaining receipt issue

Case `cs_01M3ERA0JJHTT79GB5GQ7PAJDH` also settled 0.05 test USDC and delivered
the vendor report. [Second receipt](https://sepolia.basescan.org/tx/0x4f55cab63e2534f7a79ba4abd9c378aa5b4a3db0cbd8a23bcd99d9f693fdb13b).
The first bounded block lookup retry did not resolve the initial HTTP 502; scripted S1
again failed its PAID assertion. Re-reporting this existing transaction later returned
200 and PAID, without signing or paying again. Buyer balance after the two purchases
is 19.90 test USDC; all four role wallets still have zero ETH. No new purchases should
be used to diagnose this issue. Automated first-attempt receipt confirmation remains
unverified until a revised reconciliation path is exercised.

The revised verifier refreshes the same transaction receipt when its provisional
block hash is unavailable, instead of polling only the original hash. It rejects
placeholder hashes, stale transactions and mismatched transfers. This follows the
[Flashblocks JSON-RPC behavior](https://github.com/flashbots/rollup-boost/blob/main/specs/flashblocks.md#ethereum-json-rpc-modifications).
Both already-settled receipts pass the revised real-RPC verifier. A fresh payment
immediately after settlement has not been rerun with this revision; no third payment
was sent. Regression tests model provisional-to-canonical receipt changes.

## Funded deployment and automatic rehearsal — 26 September, 12:00–12:06 UTC

Base Sepolia registry `0x8a15c703B4A5Dc972BDBf48d3fAC73B5DCdEa572` (block47327855)
and escrow `0xf81852231BD2C57d0Dd7543162B7fe02ebC81CbE` (block47327856) are deployed
and linked to MultiBaas. Screener/officer roles and token/registry wiring verified.

- New clean case `cs_01M3ESEP86NDM0XQH3BN11WWCE`, decided12:01:20UTC: liveALLOW,
  automaticPAID, seller report delivered, all3 S1 assertionspassed.
  [Payment](https://sepolia.basescan.org/tx/0x7c5058cec305d01d104a75864f15a5c1f949525f4c3f6d6c8ec2fb35c7e07f20),
  [registry attestation](https://sepolia.basescan.org/tx/0x209080a68581703b5df98103e71b0431d815838d2f23ffb199216e4199e1d89b).
- New refused case `cs_01M3ESF7MBQPHNM6V782975PMS`, decided12:01:41UTC: score100,
  BLOCK, no payment signature/transaction, all3 S3 assertionspassed.
  [Registry attestation](https://sepolia.basescan.org/tx/0xef10ebc5e52f5692f15886e5b687f6cb4eec6341c65880e93199a93ce8984a40).
- Both attestation receipts confirmed and exact corresponding `Screened` events
  retrieved from MultiBaas. Refusal still creates an audit transaction.
- Separate **operator-driven escrow rehearsal**, not provider-generated HOLD: two
  0.05testUSDC deposits to own deployer payee; premature release rejectedNotCleared;
  one [release after officer clearance](https://sepolia.basescan.org/tx/0x5f434f2177dfbe6fdba401101708071afeaa27d367e1843de4c5b913bc2cb4e8),
  one [refund](https://sepolia.basescan.org/tx/0x15e342f5c18a3cb3982f626dec54f8e492682aa8a89b77fffe631104428e15f7).
  Indexed Held/Released/Refunded events observed, final statusesRELEASED/REFUNDED,
  totalHeld0 and remaining temporary allowance0. Full gate S2 remains unverified.

Live integration findings: ABI-only MultiBaas uploads require `bin: "0x"`; fixed and
linked USDC. This deployment's tx_hash event filter returned empty for indexed events;
a bounded block/transaction-index fallback with exact local hash matching recovered
them. Approval became visible in the receipt RPC before MultiBaas could estimate a
deposit; the existing approval was allowed to propagate, not sent again.

Earlier failed rehearsals above are historical and retained for transparency. They
do not supersede this new successful automatic S1 run. Webhook delivery and hosted
browser evidence still require the deployed service and credential configuration.

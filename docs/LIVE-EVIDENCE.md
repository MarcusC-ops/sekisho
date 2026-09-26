# Verified live evidence

Current measured results for the hosted trial and the separate escrow rehearsal.
Historical attempts are archived rather than mixed with current readiness.

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

## Deployed contracts and escrow rehearsal

All contract writes and payments below used **Base Sepolia (84532)**.

| Contract | Address | Deployment block |
|---|---|---|
| ComplianceRegistry | `0x8a15c703B4A5Dc972BDBf48d3fAC73B5DCdEa572` | 47327855 |
| ComplianceEscrow | `0xf81852231BD2C57d0Dd7543162B7fe02ebC81CbE` | 47327856 |
| Canonical test USDC | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` | — |

Both application contracts are linked in MultiBaas. Screener/officer roles and registry/token wiring were checked.

The separate **operator-driven escrow rehearsal** used two 0.05 test-USDC deposits.
Attempts to release before clearance failed with `NotCleared`. One hold was cleared
and released; the other was refunded. This does not demonstrate provider-triggered HOLD.

- [First deposit](https://sepolia.basescan.org/tx/0xe4e8cbf6ae18214242c11ad2974b83cd2124c81a95774fac4f5c25727306fed8)
- [Release after clearance](https://sepolia.basescan.org/tx/0x5f434f2177dfbe6fdba401101708071afeaa27d367e1843de4c5b913bc2cb4e8)
- [Second deposit](https://sepolia.basescan.org/tx/0x324fbc36b37584ed243da24ee9b826f17c85b822506382c5d37edab7db584efe)
- [Refund](https://sepolia.basescan.org/tx/0x15e342f5c18a3cb3982f626dec54f8e492682aa8a89b77fffe631104428e15f7)

Indexed Held/Released/Refunded events matched the transactions. Final `totalHeld`,
escrow token balance and remaining temporary buyer allowance were zero.
Saved queries returned cumulative deposits of 100,000 atomic USDC and releases of
50,000; cumulative deposits are not outstanding escrow.

## Limits and history

- Full provider-triggered HOLD through the gate remains unverified.
- Public trials pause on HOLD and never expose officer release/refund controls.
- Market data is a sample payload; risk checks and testnet settlement are real.
- Trace history is bounded and uses approximate valuation. An ALLOW is not proof of safety.
- Earlier receipt-indexing failures, reconciliation and failed attestations before deployment
  remain in the [chronological rehearsal record](archive/rehearsal-history.md).
- Actual provider errors and integration feedback are summarized in the [README](../README.md#sponsor-integrations).
- Tests and browser checks have a separate [verification scope](readiness.md).

# Local setup and testnet rehearsal

[Back to Sekisho](../README.md). These steps configure the implementation; live readiness
is tracked separately in [readiness.md](readiness.md).

## Local installation

Prerequisites: Python 3.11, Node.js 22 with npm, Foundry, Git, and (for live webhook
rehearsals) an HTTPS webhook-only ingress. Run commands from the repository root.

```bash
make install
test -f .env || cp .env.example .env
make wallets
```

Do not overwrite an existing `.env`. `make wallets` creates one when absent, fills
only empty role keys, and prints addresses only. Fund all four fresh role wallets
with testnet gas and the treasury buyer with test USDC. Keep local keys in ignored `.env`; hosted credentials belong in private environment variables.

Fill the service configuration in `.env`:

| Configuration | Purpose |
|---|---|
| `INTERCEPTA_API_KEY` | Live wallet scans |
| `BLOCKSCOUT_API_KEY` | Source-of-funds history |
| `MB_URL`, `MB_ADMIN_API_KEY` | MultiBaas on the configured testnet |
| `PUBLIC_GATE_URL`, `MB_WEBHOOK_SECRET` | Public webhook delivery and verification |
| `VENDOR_CLEAN_PAYTO`, `VENDOR_SANCTIONED_PAYTO`, optional `VENDOR_MIXER_PAYTO` | Counterparties selected from real scans |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | Optional LLM provider; set `LLM_PROVIDER=none` for template notes and deterministic scenarios |

Run `make check-setup` for an offline, secret-safe checklist. A green result checks
configuration only; it does not validate credentials, balances, or deployment.

## Live testnet setup

Default value-transfer and contract chain: Base Sepolia (84532). Ethereum and Base
mainnet RPCs are used **read-only** for screening. Never send mainnet transactions.

1. Configure and fund the wallets, then run `make deploy`. Save the printed registry
   and escrow addresses in `.env`. The script deploys and links through forge-multibaas;
   see [contract deployment details](../contracts/README.md).
2. Start `make gate`. For external webhooks, use the restricted ingress described in
   [PUBLIC-TRIAL.md](PUBLIC-TRIAL.md), or an equivalent webhook-only reverse proxy.
   Set its HTTPS URL as `PUBLIC_GATE_URL`; do not expose the full local gate.
3. Run `make setup-multibaas` to link USDC, register the webhook and create the
   `exposure_by_payee` and `released_by_payee` Event Queries. Restart the gate after
   changing its environment, including the webhook secret.
4. Run `.venv/bin/python scripts/scan_candidates.py <candidate-addresses-or-file>`.
   Select actual ALLOW and mixer-exposed HOLD candidates from `scan_results.json`;
   the buyer wallet must also screen ALLOW. Set the vendor addresses in `.env` and
   restart processes that loaded the old settings. Scans consume Intercepta quota.
5. Run `make vendors`, `make control`, and `make dashboard` in separate terminals.
   Optional: `make mcp` starts streamable HTTP at `http://127.0.0.1:9000/mcp`.
6. Run `make demo-setup` to check balances and approve test USDC to escrow, then
   `make demo S=S1` to produce an attestation/webhook. Run `make smoke` before rehearsal.

| Service | Local address |
|---|---|
| Console | http://localhost:3000 |
| Gate / OpenAPI | http://localhost:8000/docs |
| Vendors | http://localhost:4021–4024 |
| Scenario control | http://localhost:8100 |
| MCP HTTP | http://localhost:9000/mcp |

The console defaults to live gate data. Optional `dashboard/.env.local` values are
shown at the end of `.env.example`. `NEXT_PUBLIC_*` values are compiled at build time;
rebuild when changing them. Never put service keys in browser environment variables.
Set `SEKISHO_OPERATOR_TOKEN` for privileged actions and enter it in the console.
Do not put it in `NEXT_PUBLIC_*` values. Keep the gate and console on a private network.

## Demo and verification

```bash
make demo-reset
make demo S=S1       # clean: ALLOW → PAID, buyer screened by seller too
make demo S=S3       # sanctioned: BLOCK before signing
make demo S=S2       # HOLD → escrow; release from the case's officer panel
make demo S=S4       # simulated compromised model attempts injected payment; gate blocks
make demo S=S5       # spoofed tainted payer refused before facilitator verification
```

`make demo S=all` runs S1, S3, S2, S4, S5. It waits for officer release during S2.
For an unattended **testnet rehearsal**, use
`.venv/bin/python scripts/demo.py all --auto-release`.
Run `make demo-reset` between rehearsals so prior clearances do not alter S2.
S4 defaults to a deterministic compromised-agent path; `--llm` exercises the real model.

S6 is separate: restart the gate with `FAULT_INJECT=intercepta_timeout make gate`,
then run `make demo S=S6`. Restart normally afterward. S6 is not silently included
in `all`, because normal and fault-injected cases require different gate settings.

On `/audit`, open a confirmed case and click **Verify report**. The browser hashes the
exact report text and compares it with the indexed onchain `Screened.reportHash`.
On `/treasury`, chain-read balances and Event Query totals are separate from
case-store totals. Exposure means cumulative Held events; it is not net outstanding
escrow. Missing reads display as unavailable, never zero.

## Tests and UI-only development

```bash
make test
npm --prefix dashboard run lint
npm --prefix dashboard run build
```

If Foundry crashes in macOS proxy discovery, run the isolated contract suite offline:
`cd contracts && forge test --offline`. No network is needed after dependencies and
compiler artifacts have been installed.

For UI development without credentials:

```bash
cd dashboard
npm run dev:fixtures
```

This enables the conspicuous **FIXTURE DATA** banner and browser-only simulated
scenarios, officer decisions, and events. The running gate has no mock mode. Stop
that dev process before starting the normal console. Submitted builds must leave
`NEXT_PUBLIC_USE_FIXTURES` unset or `false`.

## Integration details and limits

**Intercepta:** direct Quick Scan runs before payer signing and payee acceptance.
Supporting cached checks are labelled. Trait descriptions remain verbatim; missing
required evidence produces at least HOLD. Synthetic test fixtures belong in unit tests,
not the live provider path. Current measured results are in [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md).
Historical interface research is in [archive/research/services.md](archive/research/services.md).

**MultiBaas:** registry/escrow contracts are deployed and linked on Base Sepolia.
Contract calls, indexed attestations, genuine webhooks and the operator escrow rehearsal
are verified. See the [deployment addresses and receipts](LIVE-EVIDENCE.md).

**Scope:** S1/S3 are verified hosted flows. S2 is an available rehearsal script, not a
claim that the full provider-triggered HOLD journey passed. Do not fabricate a provider
verdict or alter policy simply to demonstrate an expected branch. Fault injection and
reset require explicit local demo configuration and must not be enabled in the public stack.

This is a demo policy, not legal advice or a certified AML programme. Tracing is
bounded to one/two hops with limited history and a configured ETH/USD approximation.
An ALLOW is a point-in-time policy decision, not a safety guarantee. Only testnet value moves.

For presentation, use the [current demo sequence](DEMO.md). For remaining team and
publication tasks, use the [submission checklist](SUBMISSION.md).

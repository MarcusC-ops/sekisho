# Gate API contract

The private gate runs FastAPI on port 8000. The console, SDK, agents and MCP server
use this API. The public trial exposes a separate restricted interface described in
[PUBLIC-TRIAL.md](PUBLIC-TRIAL.md); it does not proxy `/v1/*`.

Schema sources:

- [gate models](../gate/sekisho_gate/models.py): runtime validation and serialization
- [SDK models](../sdk/sekisho/models.py): standalone client models
- [console types](../dashboard/lib/types.ts): TypeScript representation

Keep corresponding fields synchronized when changing the API. JSON examples below
illustrate shapes; they are not live evidence or performance measurements.

## Access boundary

Keep the full gate private. Officer decisions, demo reset and treasury `POST /run`
require `Authorization: Bearer <SEKISHO_OPERATOR_TOKEN>`. Missing server configuration
returns 503; missing or invalid credentials return 401. The console holds this
separate token in tab memory only. Other gate routes are not a tenant-authenticated
public API. Webhooks authenticate using the MultiBaas HMAC signature, independently
of the operator token.

## Conventions

- JSON everywhere. Times are ISO 8601 UTC with a `Z` suffix (`2026-09-26T10:21:33Z`).
- Amounts are atomic-unit strings (USDC has 6 decimals, so `"50000"` is 0.05 USDC), plus
  a derived `*_usd` number.
- Addresses are EIP-55 checksummed. Tx hashes and `bytes32` values are `0x` + lowercase hex.
- Errors: `{"error": "<Code>", "message": "<human text>"}` with a 4xx or 5xx status.
  Validation errors are 422 with `error: "invalid_request"`.
- CORS allows `CONSOLE_ORIGIN`.

## Enums

| Name | Values |
|---|---|
| Verdict | `ALLOW`, `HOLD`, `BLOCK` |
| Direction | `outbound` (we pay them), `inbound` (they pay us) |
| Source | `x402`, `mcp`, `direct` |
| CaseStatus | `DECIDED`, `PAID`, `HELD_ESCROWED`, `RELEASED`, `REFUNDED`, `CLEARED`, `REJECTED`, `REFUSED` |
| CheckStatus | `ok`, `error`, `skipped` |
| AttestationStatus | `queued`, `submitted`, `confirmed`, `failed` |
| HoldStatus | `HELD`, `RELEASED`, `REFUNDED` |
| OfficerAction | `release`, `refund`, `release_unchecked` (DEMO_MODE only) |

Status lifecycle: ALLOW `DECIDED → PAID`; outbound HOLD
`DECIDED → HELD_ESCROWED → RELEASED | REFUNDED`; inbound HOLD `DECIDED → CLEARED | REJECTED`;
BLOCK is set to `REFUSED` at decision time.

## Objects

### Check
One entry per check that ran. The names are `intercepta.quick_scan`, `sanctions.oracle`,
`trace.source_of_funds`, `intercepta.impersonation`, `intercepta.token` and
`intercepta.deep_scan`.

```json
{"name": "intercepta.quick_scan", "status": "ok", "live": true, "latency_ms": 312,
 "summary": "toxicScore 100, 3 traits", "evidence_id": "E1", "error": null}
```
`live` is `true` for a fresh call, `false` for a cache hit, and `null` for checks that
don't call Intercepta. `error` holds a short message when `status` is `error`.

### Reason
One entry per triggered policy rule.

```json
{"rule": "hard_block_trait:sanction_address", "severity": "block", "source": "intercepta",
 "label": "sanction_address", "detail": "<Intercepta description, verbatim>",
 "evidence_id": "E1", "risk": 100, "txs_count": 0}
```
- `severity` is `block` or `hold`.
- `source` is `chainalysis`, `intercepta`, `trace`, `policy` or `officer`.
- `risk` and `txs_count` appear only on Intercepta trait reasons.

### TraceResult
Contains `chains: int[]`, `inbound_usd_traced: number`, `hop1: TraceHop1[]`,
`hop2: TraceHop2[]`, `taint_pct: number`, `paths: string[]`, `truncated: boolean` and
`notes: string[]`. Hop records include addresses, chain IDs, amounts and flags;
see the runtime models for complete optional fields. `trace` is `null` if its check
failed.

### AnalystNote
An explanatory note and the metadata identifying how it was produced:

```json
{"headline": "…", "summary": "…", "key_findings": [{"text": "…", "evidence": ["E1"]}],
 "owner_message": "…", "officer_recommendation": "release", "recommendation_rationale": "…",
 "agrees_with_policy": true, "provider": "anthropic", "model": "claude-haiku-4-5",
 "fallback": false, "generated_at": "2026-09-26T10:21:36Z"}
```
- `officer_recommendation` is `release`, `refund` or `n/a`.
- `provider` is `anthropic`, `openai` or `template`.
- A template note has `provider: "template"`, `model: null` and `fallback: true`.

### Attestation
```json
{"status": "confirmed", "tx_hash": "0x…", "explorer_url": "https://sepolia.basescan.org/tx/0x…", "error": null}
```

### Hold
```json
{"hold_id": 3, "status": "HELD", "deposit_tx": "0x…", "override_tx": null, "action_tx": null, "officer_note": null}
```
`hold` is `null` until the agent reports the escrow deposit, or the `Held` webhook links
it. It stays `null` for inbound HOLD cases, which have no escrow.

### ChainEvent
One decoded contract event, from MultiBaas webhooks or the fallback poller.

```json
{"event_uid": "0xabc…:3", "name": "Screened", "contract_alias": "compliance_registry",
 "tx_hash": "0x…", "block_number": 123, "log_index": 3,
 "inputs": {"subject": "0x…", "verdict": 3, "riskScore": 100, "reportHash": "0x…",
            "policyId": "0x…", "expiresAt": 1790000000, "screener": "0x…", "caseId": "0x…"},
 "case_id": "cs_01J8Z6Q4M0T3R9", "explorer_url": "https://sepolia.basescan.org/tx/0x…",
 "received_at": "2026-09-26T10:21:40Z"}
```
- `name` is `Screened`, `VerdictOverridden`, `Held`, `Released` or `Refunded`.
- `inputs` uses the Solidity parameter names. Integers are JSON numbers when they fit in
  2^53, otherwise decimal strings.
- `case_id` is resolved from the `caseId` bytes32 when it matches a known case.

### ScreeningDecision
The frontend contract, returned by `POST /v1/screen` and used in lists and SSE.

| Field | Type |
|---|---|
| `case_id` | `"cs_"` + 26-char ULID |
| `case_id_b32` | `keccak(text=case_id)`, 0x + 64 hex |
| `verdict` | Verdict |
| `risk_score` | int 0 to 100 |
| `headline` | string (from the policy's top reason, not the LLM) |
| `direction` | Direction |
| `counterparty` | address |
| `amount`, `amount_usd` | atomic string, number |
| `asset` | canonical Base Sepolia USDC token address |
| `payment_chain_id` | int; 84532 for payable decisions (legacy missing values become 0 and cannot be signed) |
| `reasons` | Reason[] (only triggered rules) |
| `checks` | Check[] |
| `trace` | TraceResult or null |
| `policy` | `{"id": "0x…", "version": "1.0.0", "triggered_rules": ["…"]}` |
| `report_hash` | 0x + 64 hex |
| `attestation` | Attestation |
| `analyst` | AnalystNote or null (filled later over SSE) |
| `hold` | Hold or null |
| `status` | CaseStatus |
| `decided_at` | time |
| `latency_ms` | int |

### CaseDetail
Every ScreeningDecision field, plus:

| Field | Type |
|---|---|
| `source`, `agent_id`, `purpose`, `resource` | strings (`purpose` and `resource` may be `""`) |
| `untrusted_context` | string or null, verbatim counterparty text |
| `payment_tx` | tx hash or null (the x402 settlement or direct transfer) |
| `evidence` | `{"quick_scan": {...} or null, "oracle": {"1": true, "8453": false} or null, "impersonation": {...} or null, "token_scan": {...} or null, "deep_scan": {...} or null}` |
| `chain_events` | ChainEvent[] for this case, oldest first |

`evidence.quick_scan.traits[]` lists **every** trait, including info ones, each with a
`class` of `hard_block`, `hold`, `info` or `other`. The raw Intercepta response fields stay
alongside.

## Endpoints

| Method and path | Request | Response |
|---|---|---|
| `POST /v1/screen` | ScreenRequest (below) | ScreeningDecision |
| `GET /v1/cases` | query `verdict`, `status`, `direction`, `limit` (default 50, max 100), `cursor` | `{"items": ScreeningDecision[], "next_cursor": string or null}`, newest first, archived cases excluded |
| `GET /v1/cases/{case_id}` | | CaseDetail, or 404 `not_found` |
| `POST /v1/cases/{case_id}/payment` | `{"tx_hash", "network"}` | `{"case_id", "status": "PAID"}` |
| `POST /v1/cases/{case_id}/hold` | `{"hold_id", "deposit_tx"}` | `{"case_id", "status": "HELD_ESCROWED"}` |
| `POST /v1/cases/{case_id}/decision` | `{"action": OfficerAction, "note": string}` | `{"override_tx", "action_tx", "status"}` (see below) |
| `GET /v1/reports/{report_hash}` | | exact canonical bytes, `Content-Type: application/json` |
| `GET /v1/metrics` | | Metrics (below) |
| `GET /v1/audit` | query `limit` (default 100), `case_id` | `{"items": ChainEvent[]}`, newest first |
| `GET /v1/treasury` | | Treasury (below) |
| `GET /v1/policy` | | `{"id", "version", "name", "yaml", "parsed": {...}}` |
| `GET /v1/quota` | | `{"used", "quota", "remaining", "warn_at", "reserve_from"}` |
| `GET /v1/stream` | | Server-Sent Events (below) |
| `POST /v1/demo/reset` | | `{"archived": n, "overrides_cleared": n}`, DEMO_MODE only, else 403 `demo_mode_only` |
| `POST /webhooks/multibaas` | MultiBaas delivery (HMAC verified) | `{"ok": true}`, or 401 |
| `GET /healthz` | | Health (below) |

### ScreenRequest

Required fields are `counterparty`, `direction`, `amount` and `asset`.
`payment_chain_id` defaults to `84532`; `source` defaults to `direct`.
`agent_id`, `purpose` and `resource` default to empty strings, and
`untrusted_context` defaults to null. Address, amount and enum validation uses the
runtime models. The gate additionally rejects non-positive amounts, unsupported
networks and noncanonical payment assets before provider calls.

**Officer decision errors:**
- 409 `invalid_state`: the case isn't in a decidable state.
- 409 `<RevertName>` (e.g. `NotCleared`): the contract refused. `message` says which call.
- 403 `demo_mode_only`: `release_unchecked` outside DEMO_MODE.
- 502 `chain_error`: MultiBaas or RPC failure.

### Metrics
```json
{"window": "since_reset", "screened": 14, "allow": 8, "hold": 3, "block": 3,
 "value_screened_usd": 3.4, "value_held_usd": 0.5, "value_blocked_usd": 25.05,
 "latency_ms_p50": 1840, "latency_ms_p95": 4100,
 "intercepta_calls_used": 212, "intercepta_quota": 1000, "attestations_confirmed": 13}
```

### Treasury
```json
{"buyer_address": "0x…", "buyer_usdc": "4950000", "buyer_usdc_usd": 4.95,
 "escrow_address": "0x…", "escrow_total_held": "500000", "escrow_total_held_usd": 0.5,
 "paid_via_x402_usd": 0.15, "value_blocked_usd": 25.05,
 "exposure_by_payee": [{"payee": "0x…", "total": "500000", "total_usd": 0.5}],
 "released_by_payee": [{"payee": "0x…", "total": "500000", "total_usd": 0.5}],
 "counterparty_book": [{"counterparty": "0x…", "latest_verdict": "HOLD", "last_screened_at": "…",
                        "total_paid_usd": 0.0, "total_held_usd": 0.5, "cases": 2}],
 "source": "multibaas", "cached_at": "2026-09-26T10:21:40Z", "errors": []}
```
`exposure_by_payee` is cumulative deposited value from indexed events, not current
outstanding escrow. Use `escrow_total_held` for outstanding funds. MultiBaas reads and
Event Queries are cached for 60 s. A failed read leaves its field
`null` and adds a message to `errors` instead of failing the whole response.

### SSE (`GET /v1/stream`)
Standard `text/event-stream`. Each message has an `id` (increasing integer), an `event`
and a JSON `data` payload. The gate sends a keep-alive comment every 15 s.

| event | data |
|---|---|
| `case.created` | ScreeningDecision |
| `case.updated` | ScreeningDecision (latest state: analyst note, attestation, hold, status) |
| `chain.event` | ChainEvent |
| `metrics.updated` | Metrics |

### Health (`GET /healthz`)
```json
{"status": "ok", "demo_mode": true, "policy": {"id": "0x…", "version": "1.0.0"},
 "checks": {"intercepta": {"ok": true, "detail": "key valid, 212/1000 used"},
            "oracle_self_test": {"ok": true, "detail": "0x098B…2F96 sanctioned on 1"},
            "multibaas": {"ok": true, "detail": "reachable"},
            "contracts_rpc": {"ok": true, "detail": "chain 84532, block 123"},
            "llm": {"ok": true, "detail": "anthropic claude-haiku-4-5"}}}
```
`status` is `ok` when every check passes and `degraded` otherwise. The endpoint always
returns 200.

## Treasury control API (`agents/treasury/control.py`, `:8100`)

The console's demo bar drives scenarios through this API. CORS allows `CONSOLE_ORIGIN`.

| Method and path | Request | Response |
|---|---|---|
| `POST /run` | `{"scenario": "S1".."S6" or "all"}` | `{"run_id"}`, or 409 if a run is in progress |
| `GET /runs/{run_id}` | | `{"run_id", "scenario", "status": "running" or "succeeded" or "failed", "lines": [string], "started_at", "finished_at"}` |

## Payment and screening enforcement

Screening accepts only canonical Base Sepolia USDC and a positive amount. Unsupported
payment assets/networks return 422 before provider calls. Decision deduplication binds
the complete screening request, policy, current override and relevant check settings.
The SDK binds payee, amount, asset, chain and direction before any signing or escrow.
An empty, 204 or generic 404 Quick Scan response is unavailable evidence, never clean.

Payment reports are accepted only for outbound ALLOW cases after Base Sepolia RPC
confirms a successful receipt and the exact USDC Transfer from the configured buyer
to the case counterparty for its amount. The receipt block must not predate the case.
Transaction reuse across different cases, including archived cases, is rejected.
Hold reports similarly verify the configured escrow's Held event, hold/case identifiers,
buyer, payee and amount. Later indexed release/refund states are preserved.
Receipt mismatches return 409 `receipt_mismatch`; unavailable RPC evidence returns
502 `receipt_unavailable`. Reporting a transaction hash alone does not change the case.

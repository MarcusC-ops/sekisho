# Build gate core (policy, API, SSE)

Subagent prompt written by the lead agent (Claude Code, Claude Opus 5.5) on 2026-09-25 13:18 UTC.
Local paths are shortened to `<repo>` and `<scratchpad>`; the text is otherwise verbatim.

---

You are the **gate core** builder for Sekisho, a hackathon project (ETHGlobal Tokyo 2026, due Sun 27 Sep 09:00 JST: be efficient, P0 first). The gate (C1, Python 3.11 + FastAPI) is the product: before an AI agent pays or accepts USDC over x402, it screens the counterparty wallet, applies a deterministic policy (ALLOW, HOLD or BLOCK), stores a hashed evidence report, attests the verdict onchain through Curvegrid MultiBaas, and serves the compliance console.

Repo: `<repo>`. Read first:
- `AGENTS.md`, the project rules. Rules 1 to 9 are non-negotiable: fail closed, no mock mode, policy bytes hashed, verbatim Intercepta text, the AI never decides.
- `docs/api.md`, the exact API contract. Implement it exactly.
- `PRD.md` Section 9 (lines ~389-788) in full, plus Section 5 (demo scenarios) and Appendices D, E.1, E.2 and F.

Already in the repo:
- `gate/sekisho_gate/config.py` with `get_settings()`, covering every env var (SecretStr for keys; `policy_path` and `db_path` are resolved against the repo root).
- `gate/sekisho_gate/screening/types.py` with `CheckOutcome`, the shared result type of every check. Read its docstring for the `data` shapes.
- `gate/policy/policy.yaml`, which hashes to `0xd55f2a7678cc2571a18073afd351f2fc13ffe4aa9c570632b94a8190f9c14719`. Never modify it.
- `pytest.ini` (asyncio_mode auto, importlib mode).
- The venv at `.venv` with everything installed: fastapi 0.141, pydantic 2.13, sse-starlette 3.4, web3 8.0, eth-account 0.14, eth-utils, httpx 0.28, anthropic 1.8, openai 3.19, pytest, pytest-asyncio 1.4, respx. Run things with `.venv/bin/python`. Don't install new packages; if you truly need one, say so in your report.

**Another agent (gate integrations) is building these at the same time, and you must not write them:** `screening/intercepta.py`, `screening/cache.py`, `screening/sanctions.py`, `screening/tracer.py`, `chain/__init__.py`, `chain/multibaas.py`, `scripts/setup_multibaas.py`, and their tests. Code against these interfaces. Until their files appear, use your own fakes in tests. When they exist, run against them; if an interface differs, adapt your side and note it in your report.

```python
# screening/intercepta.py
class InterceptaClient:
    def __init__(self, settings, http: httpx.AsyncClient | None = None): ...
    async def quick_scan(self, address: str, *, live: bool = True) -> CheckOutcome      # "intercepta.quick_scan"; live=True skips the cache read, still writes it
    async def quick_scan_cached(self, address: str) -> CheckOutcome                     # cache-first, "skipped" once quota >= INTERCEPTA_RESERVE_FROM (tracer funders)
    async def deep_scan(self, address: str) -> CheckOutcome                             # "intercepta.deep_scan"
    async def impersonation(self, address: str) -> CheckOutcome                         # "intercepta.impersonation"
    async def token_scan(self, token_address: str, chain_id: int = 8453) -> CheckOutcome # "intercepta.token"
    def quota_status(self) -> dict        # {"used", "quota", "remaining", "warn_at", "reserve_from"}
    def key_status(self) -> tuple[bool, str]  # from config and the last HTTP status seen (403 = bad key); makes no API call
    async def aclose(self) -> None
# screening/sanctions.py
class SanctionsOracle:
    def __init__(self, settings, http=None): ...
    async def check(self, address: str) -> CheckOutcome      # "sanctions.oracle", data {"1": bool|None, "8453": bool|None}
    async def self_test(self) -> tuple[bool, str]            # isSanctioned(0x098B…2F96) on Ethereum must be true
    async def aclose(self) -> None
# screening/tracer.py
class Tracer:
    def __init__(self, settings, oracle: SanctionsOracle, intercepta: InterceptaClient, policy_cfg: dict, http=None): ...
    async def trace(self, address: str) -> CheckOutcome      # "trace.source_of_funds", data = TraceResult dict (PRD 9.5)
    async def aclose(self) -> None
# chain/multibaas.py
class MultiBaasError(Exception):  # attrs: status: int | None, body: str, revert: str | None (e.g. "NotCleared"), selector: str | None
class MultiBaasClient:
    def __init__(self, settings, http=None): ...
    configured: bool                                                              # property: MB_URL and MB_ADMIN_API_KEY set
    async def call_write(self, alias, label, method, args: list, signer) -> str  # compose via MultiBaas, sign locally, submit; returns the tx hash; raises MultiBaasError (revert decoded)
    async def call_read(self, alias, label, method, args: list): ...             # returns the output
    async def wait_for_receipt(self, tx_hash: str, timeout_s: float = 30.0) -> dict  # polls CONTRACTS_RPC_URL; {"status": 1 or 0, "blockNumber": int, ...}
    async def list_events(self, *, contract_alias: str | None = None, limit: int = 20) -> list[dict]  # parse_event()-normalised
    async def query_results(self, name: str) -> list[dict]                       # saved Event Query results
    async def address_of(self, alias: str) -> str
    async def health(self) -> tuple[bool, str]
    async def aclose(self) -> None
def parse_event(raw: dict) -> dict  # webhook `data` or /events item -> {"name", "contract_alias", "contract_address", "tx_hash", "block_number", "log_index", "inputs": {name: value}}
def verify_webhook_signature(body: bytes, timestamp: str, signature: str, secret: str) -> bool
def encode_args(...)  # arg-encoding helper (uint -> decimal string, etc.)
```

**You own and build** (under `gate/sekisho_gate/` unless noted):
1. `models.py`: pydantic models mirroring `docs/api.md` (ScreenRequest, Check, Reason, TraceResult, AnalystNote, Attestation, Hold, ChainEvent, ScreeningDecision, CaseDetail, Metrics, the list responses and so on). Validate and EIP-55-checksum addresses with `eth_utils`, and give invalid input a 422 in the documented error shape.
2. `store/db.py` (+ `store/__init__.py`): stdlib sqlite3, WAL, one connection guarded by a lock. Tables per PRD 9.14, **except** `intercepta_cache` and `quota`, which the integrations agent owns in `screening/cache.py` (same DB file). Include case history (prior ALLOW/PAID cases for rule 12), officer overrides with expiry, the idempotency lookup (same counterparty, direction, amount and resource within 10 s returns the same case), archiving for demo reset, and the chain_events upsert (idempotent on `txHash + indexInLog`).
3. `policy/engine.py` (+ `policy/__init__.py`):
   - Load the YAML; `policy_id = "0x" + keccak(file bytes)`.
   - `evaluate()` implements rules 0 to 13 exactly as in the PRD 9.6 table, including rule 0's override semantics: rules 1, 2 and 7 always apply, and a BLOCK override is BLOCK. Collect every triggered rule; the strongest outcome wins; compute `risk_score` per the formula.
   - `info_traits` never change the verdict.
   - Build reasons with the Intercepta `description` verbatim, and a policy-derived `headline` (e.g. "Counterparty is on a sanctions list").
   - Classify every trait as hard_block, hold, info or other for `evidence.quick_scan.traits[].class`.
4. `report.py`: build the report with only the deterministic parts (PRD 9.7; schema `sekisho.report.v1`, including every check's raw response). The canonical bytes are `json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`, and `report_hash = "0x" + keccak(bytes).hex()`. Store the exact bytes. Test it against the Appendix F vector.
5. `screening/pipeline.py`:
   - Run the checks in parallel with per-check timeouts (quick scan 3 s, oracle 2 s, trace 6 s, impersonation 3 s, token 3 s) inside an overall 8 s budget.
   - The token scan targets the mainnet equivalent of the payment asset: Base Sepolia USDC maps to Base USDC `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`, chainId 8453.
   - `FAULT_INJECT=intercepta_timeout` makes the quick scan fail as a timeout (scenario S6).
   - A failed check is recorded with `status: "error"`, never dropped.
   - Assign evidence ids consistently: E1 quick scan, E2 oracle, E3 trace, E4 impersonation, E5 token, E6 deep scan.
   - P1: after a HOLD, run a background Deep Scan and add it to `evidence.deep_scan` (not to the hashed report).
6. `analyst/llm.py` and `analyst/prompts.py`:
   - Prompts are verbatim from Appendix E.1 and E.2.
   - Provider switch `LLM_PROVIDER=anthropic|openai|none` wrapping both SDKs behind `async def complete_json(system, user) -> dict`. Default models when `LLM_MODEL` is empty: Anthropic `claude-haiku-4-5`, OpenAI a current small model. Keep the model id in one constant.
   - 8 s timeout. Validate with pydantic. On timeout, invalid JSON, a missing key or `none`, produce a **template note** from the triggered rules with `provider: "template"` and `fallback: true`.
   - Counterparty text goes inside `<untrusted_context>`. Runs in the background after the verdict; the note never touches the verdict or the hash.
   - If a `claude-api` skill is available to you, consult it for current Anthropic SDK usage.
7. `chain/attest.py`:
   - One `asyncio.Queue` and one worker per signer key (screener, officer). Never send two txs from the same key concurrently.
   - `recordScreening(subject, verdict, riskScore, ttlSeconds, reportHash, policyId, caseId)` goes to alias/label `compliance_registry`, signed by `GATE_SCREENER_PK`, with the TTL from the policy's `verdict_ttl_seconds`. The Verdict enum is 1 ALLOW, 2 HOLD, 3 BLOCK.
   - Track attestation status queued → submitted → confirmed or failed; update the store and publish SSE `case.updated`.
   - Officer decisions per PRD 9.11 `POST /v1/cases/{id}/decision`, steps 1 to 7: overrideVerdict, then wait, then release or refund; override only for inbound; `release_unchecked` only in DEMO_MODE; reverts become 409 `{error: "<RevertName>"}`. Note hashes are `keccak(text=note)`.
   - If MultiBaas isn't configured, the attestation becomes `failed` with a clear error and nothing crashes.
8. `webhooks.py`: `POST /webhooks/multibaas` with HMAC verification via `verify_webhook_signature`, idempotent upserts, and the case updates per PRD 9.13 (Screened confirms the attestation; Held links the hold and sets HELD_ESCROWED; Released/Refunded set the status; VerdictOverridden is logged). Publish SSE `chain.event` and `case.updated`. P1: the fallback poller from PRD 9.13 using `list_events`.
9. `sse.py`: an in-process pub/sub fanning out to `/v1/stream` subscribers, with incrementing ids and a 15 s keep-alive.
10. `main.py`:
    - The FastAPI app with a lifespan that creates the clients, starts the attestation workers and runs the oracle self-test.
    - Every route in `docs/api.md`, and CORS for `CONSOLE_ORIGIN`.
    - `/v1/metrics` since the last reset, and `/v1/audit`.
    - `/v1/treasury` via MultiBaas reads and the Event Queries `exposure_by_payee` / `released_by_payee`, cached for 60 s, and tolerant of errors per the contract.
    - `/v1/policy`, `/v1/quota`, and `/healthz` (always 200).
    - `/v1/demo/reset` (DEMO_MODE only): archive the cases and delete the officer overrides and the idempotency cache; never touch the chain or the Intercepta cache.
    - Structured JSON logs with `case_id` on every line.
    - Latency targets: p50 < 2.5 s, fail closed to HOLD at the 8 s budget.
    - The verdict returns immediately; the attestation and the analyst run in the background.
11. Tests in `gate/tests/` (you own `conftest.py`). The integrations agent writes `test_intercepta.py`, `test_sanctions.py`, `test_tracer.py` and `test_multibaas.py`; don't use those names. Required (P0):
    - A pytest table with one case per policy rule 0 to 12, including the override semantics.
    - The three profiles: clean ALLOW, mixer HOLD, sanctioned BLOCK. Real captured Intercepta responses don't exist yet (the key hasn't arrived), so build them from the documented schema, label them clearly as synthetic, and make them easy to swap for real captures.
    - Hashing against Appendix F, and the policy_id.
    - Fail closed: a quick-scan error or timeout gives at least HOLD, and never ALLOW.
    - Idempotency.
    - Webhook HMAC accept/reject and idempotent replay.
    - The attestation worker, with a fake MultiBaas (nonce lane, status transitions, revert → 409).
    - API tests through `httpx.ASGITransport` with fake clients: `POST /v1/screen` returns the contract shape; cases list and detail; `reports/{hash}` returns the exact bytes; the decision flow.
    - Use respx or fakes only in tests. The running service has no mock mode.

**Live smoke check when done** (public, read-only calls only): start the gate with `.venv/bin/python -m uvicorn sekisho_gate.main:app --port 8000` and no `.env` (no Intercepta key, no MultiBaas), then `POST /v1/screen` for the sanctioned address `0x098B716B8Aaf21512996dC57EB0615e2383E2f96` (outbound, amount "50000", asset the Base Sepolia USDC).
- If the integrations agent's clients exist by then, expect BLOCK via the Chainalysis oracle, the quick scan as an error ("key not set"), a failed attestation with a clear error, and a template analyst note.
- Also screen a random fresh address (expect HOLD from fail-closed, since there is no Intercepta key), and exercise `/healthz`, `/v1/cases`, `/v1/cases/{id}`, `/v1/reports/{hash}` (re-hash the returned bytes and compare) and the `/v1/stream` output.
- Stop the server afterwards, and delete any `gate/sekisho.db` you created.

Rules: only touch the files listed as yours. No git commands that write; the lead commits. Never send transactions, and never use real keys (none exist yet).

Final report (concise):
- the module list and what each does
- the test count and results (verbatim pytest summary)
- the live smoke-check output (the verdict JSON, trimmed)
- deviations from the PRD or `docs/api.md` and why
- every interface mismatch with the integrations agent's code
- the env vars you read
- open issues or TODOs, especially anything that needs the Intercepta key or MultiBaas to verify

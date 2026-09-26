# Build gate integration clients

Subagent prompt written by the lead agent (Claude Code, Claude Opus 5.5) on 2026-09-25 13:20 UTC.
Local paths are shortened to `<repo>` and `<scratchpad>`; the text is otherwise verbatim.

---

You are the **gate integrations** builder for Sekisho, a hackathon project (ETHGlobal Tokyo 2026, due Sun 27 Sep 09:00 JST: be efficient, P0 first). Sekisho's gate (Python 3.11, FastAPI) screens a counterparty wallet before an AI agent pays or accepts USDC over x402, then applies a deterministic ALLOW/HOLD/BLOCK policy and attests onchain through Curvegrid MultiBaas. You build the gate's **external-service clients**. Another agent (gate core) is building the pipeline, policy, store, API and attestation worker against the interfaces below, at the same time.

Repo: `<repo>`. Read first:
- `AGENTS.md` (rules: fail closed, no mock mode, raw responses kept verbatim, Intercepta descriptions verbatim)
- `PRD.md` Sections 7.3, 9.2 to 9.5, 9.8, 9.9, 9.13 and 9.15, plus Appendix D (the policy's trace parameters and trait lists)
- `gate/sekisho_gate/config.py` (`get_settings()`, every env var) and `gate/sekisho_gate/screening/types.py` (`CheckOutcome` and its per-check `data` shapes; return exactly these)

The venv at `.venv` has httpx, pydantic, web3 8, eth-account, eth-utils, pytest, pytest-asyncio and respx. Use `.venv/bin/python` and don't install packages.

**Verified API facts:** a research agent is writing `<scratchpad>/research/services.md`. It may still be in progress: check it now and again before you finalise. Its raw material is already in that `research/` folder: `intercepta-docs/`, `multibaas-docs/`, `blockscout-samples/` (real keyless responses for the sanctioned address), `blockscout-docs/`, `chainalysis/`, `forge-multibaas/` and `raw/`. Where the PRD and the real docs or samples disagree, follow the real API and list every difference in your report.

**You own** (create exactly these; touch nothing else):
- `gate/sekisho_gate/screening/intercepta.py` and `gate/sekisho_gate/screening/cache.py` (the `intercepta_cache` and `quota` tables, in the same SQLite file at `settings.db_path`, created if missing; stdlib sqlite3, WAL)
- `gate/sekisho_gate/screening/sanctions.py`
- `gate/sekisho_gate/screening/tracer.py`
- `gate/sekisho_gate/chain/__init__.py` (empty) and `gate/sekisho_gate/chain/multibaas.py`
- `scripts/setup_multibaas.py`
- tests: `gate/tests/test_intercepta.py`, `test_sanctions.py`, `test_tracer.py`, `test_multibaas.py`, `test_setup_multibaas.py`, and fixtures under `gate/tests/fixtures/`. The core agent owns `gate/tests/conftest.py`, so don't create it; put helpers in your own test files.

**Interfaces (implement exactly; the core agent codes against them):**
```python
# screening/intercepta.py
class InterceptaClient:
    def __init__(self, settings, http: httpx.AsyncClient | None = None): ...
    async def quick_scan(self, address: str, *, live: bool = True) -> CheckOutcome      # "intercepta.quick_scan"; live=True skips the cache read, still writes it
    async def quick_scan_cached(self, address: str) -> CheckOutcome                     # cache-first; status "skipped" once quota used >= INTERCEPTA_RESERVE_FROM (tracer funders)
    async def deep_scan(self, address: str) -> CheckOutcome                             # "intercepta.deep_scan"
    async def impersonation(self, address: str) -> CheckOutcome                         # "intercepta.impersonation"
    async def token_scan(self, token_address: str, chain_id: int = 8453) -> CheckOutcome # "intercepta.token", cached 24 h
    def quota_status(self) -> dict        # {"used", "quota", "remaining", "warn_at", "reserve_from"}
    def key_status(self) -> tuple[bool, str]  # from config and the last HTTP status seen (403 = bad key); makes no API call
    async def aclose(self) -> None
# screening/sanctions.py
class SanctionsOracle:
    def __init__(self, settings, http=None): ...
    async def check(self, address: str) -> CheckOutcome      # "sanctions.oracle", data {"1": bool|None, "8453": bool|None}; status "ok" only if both chains answered
    async def self_test(self) -> tuple[bool, str]            # isSanctioned(0x098B716B8Aaf21512996dC57EB0615e2383E2f96) on Ethereum must be true
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
    async def call_write(self, alias, label, method, args: list, signer) -> str  # compose via MultiBaas, sign locally (eth-account LocalAccount), submit; returns the tx hash; raises MultiBaasError with the revert decoded
    async def call_read(self, alias, label, method, args: list): ...             # returns the output
    async def wait_for_receipt(self, tx_hash: str, timeout_s: float = 30.0) -> dict  # polls CONTRACTS_RPC_URL eth_getTransactionReceipt every 1 s; {"status": 1 or 0, "blockNumber": int, ...}
    async def list_events(self, *, contract_alias: str | None = None, limit: int = 20) -> list[dict]  # parse_event()-normalised
    async def query_results(self, name: str) -> list[dict]                       # saved Event Query results
    async def address_of(self, alias: str) -> str
    async def health(self) -> tuple[bool, str]
    async def aclose(self) -> None
def parse_event(raw: dict) -> dict  # webhook `data` object or /events item -> {"name", "contract_alias", "contract_address", "tx_hash", "block_number", "log_index", "inputs": {name: value}}
def verify_webhook_signature(body: bytes, timestamp: str, signature: str, secret: str) -> bool
def encode_args(...)  # your helper: uint -> decimal string, bytes32 -> 0x+64 hex, enum -> number, address -> checksummed
def decode_revert(text: str) -> tuple[str, str] | None   # find a known 4-byte selector in an error body -> (name, selector)
```
Every public client method returns a `CheckOutcome` and never raises for upstream failures. The exception is `MultiBaasClient`, which raises `MultiBaasError`. Record `latency_ms`, a human `summary` (e.g. "toxicScore 100, 3 traits" or "sanctioned on 1") and `raw` exactly as received. `data` follows the shapes in `types.py`.

**Behaviour required by the PRD:**
- **Intercepta (9.3):**
  - Header `X-API-KEY`.
  - A 404 or empty body for an address with no history means `status: "ok"`, `toxicScore: 0`, `traits: []`, not an error (otherwise every fresh wallet is refused).
  - A 403 is an error ("invalid Intercepta API key"), with no retry.
  - An empty key is an immediate error with no HTTP call.
  - The cache TTL is 24 h.
  - Count every HTTP call in the quota table, and log a warning at `INTERCEPTA_WARN_AT`.
  - The direct live scan always runs; only funder scans are skipped above the reserve.
  - Set a sane httpx timeout per call (quick 3 s, deep 5 s).
  - **Never make a real Intercepta call:** there is no key yet. Tests use respx.
- **Sanctions (9.4):**
  - JSON-RPC `eth_call` over httpx to `ETH_MAINNET_RPC_URL` and `BASE_MAINNET_RPC_URL`, with the oracle addresses from the PRD and both chains in parallel.
  - Decode the bool. A failed chain gives `None` for that chain and a check status of "error"; the policy still BLOCKs if any chain says true.
  - Include a public helper for the tracer to check many addresses.
- **Tracer (9.5):** implement the algorithm exactly: hop 1 is P0; hop 2 is P1, gated by `TRACE_ENABLE_HOP2` and the policy's trace section.
  - Use the Blockscout PRO API with `BLOCKSCOUT_API_KEY`. When the key is empty, fall back to the keyless hosts `eth.blockscout.com` / `base.blockscout.com` (dev only).
  - Include internal transactions: that is how mixer withdrawals arrive.
  - Use the field names from the real samples, not guesses.
  - Wrap calls in `Semaphore(4)`, with max 2 retries and backoff on 429/5xx.
  - Normalisation rules: stablecoins at face value; ETH and WETH × `ETH_USD_PRICE`; everything else is 0 (counted but not weighted). Drop zero-value transfers and `is_scam` tokens.
  - Group by sender and take the top-k. Flag each top sender from: the oracle; `quick_scan_cached` hard-block or hold traits, or `toxicScore >= hold_score`; the Blockscout `is_scam` flag; and the label keywords from the policy.
  - Compute the taint maths as specified, readable `paths` strings (like the PRD example), `truncated`, and `notes`. The whole trace must fit in about 5.5 s; if hop 2 runs out of time, return the hop-1 result with a note.
  - Set `raw` to the normalised transfer list plus the source URLs (full Blockscout pages are too big to hash into every report), and say so in the notes.
- **MultiBaas (9.8):**
  - Compose, sign locally and submit, with `chainId = settings.chain_id`, EIP-1559 fields from the composed tx, and the tx hash taken from the response or falling back to keccak of the raw tx.
  - Arg encoding per 9.8. The contracts agent is verifying the ABI types and error selectors from the compiled contracts; use the PRD's selector list for now.
  - Revert decoding from compose-error bodies.
  - Retries (max 2) with backoff on 429/5xx.
  - Confirm the exact response shapes, the webhook payload and the HMAC construction from `multibaas-docs/`.
- **`scripts/setup_multibaas.py` (9.9, steps 4 to 6):**
  - Upload the minimal ERC-20 ABI as label `erc20` and link USDC at alias `usdc` with event sync off.
  - Create or update the webhook `sekisho-gate` pointing at `${PUBLIC_GATE_URL}/webhooks/multibaas` for `event.emitted`. Write its secret into `.env`'s `MB_WEBHOOK_SECRET` line and never print it.
  - Save the Event Queries `exposure_by_payee` and `released_by_payee`.
  - Set the CORS origin `CONSOLE_ORIGIN` if the API allows it.
  - Make it idempotent and safe to re-run, with `--update-webhook` (for when the tunnel URL changes) and `--dry-run` (print what would be sent, with secrets redacted).
  - Test it with respx. It never runs against a real deployment here.

**Tests (respx; the running code has no mock mode):**
- Intercepta: ok, 404 treated as clean, 403 with no retry, empty key, cache hit and miss, live=True writing the cache, quota counting and the reserve skip.
- Oracle: true and false decoding, one chain failing.
- Tracer taint maths: hop 1 only, hop 1 + hop 2, zero inbound. Also normalisation, `is_scam` drops, label flags and internal-tx inclusion. Build fixtures from the real samples, trimmed, in `gate/tests/fixtures/`.
- MultiBaas: arg encoding on a composed-but-not-submitted call; the compose → sign → submit flow; revert mapping; the tx-hash fallback; `parse_event` on a docs sample payload; HMAC accept and reject.
- setup_multibaas: the right requests are sent.

**Live checks** (public and read-only only; no keys, no transactions):
1. The oracle self-test against the real public RPCs (expect true).
2. The tracer, hop 1 and hop 2, against keyless Blockscout for `0x098B716B8Aaf21512996dC57EB0615e2383E2f96`, plus one other address you expect to show mixer exposure, if you can find one quickly from the Blockscout labels. With no Intercepta key, the funder scans come back error or skipped, and the flags come from the oracle and labels.

Report the timings and the resulting TraceResult (trimmed).

Rules: no git commands that write (the lead commits). Delete any `gate/sekisho.db` you create.

Final report (concise):
- files and a one-line purpose for each
- the pytest summary (verbatim)
- the live-check results with timings
- the full list of PRD-vs-reality differences you found and how you handled each (Intercepta fields and 404 behaviour, Blockscout field names, MultiBaas response, webhook and HMAC shapes, Event Query syntax, CORS API)
- anything that still needs the real keys to confirm

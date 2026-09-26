# Build SDK, x402 hooks and vendors

Subagent prompt written by the lead agent (Claude Code, Claude Opus 5.5) on 2026-09-25 13:21 UTC.
Local paths are shortened to `<repo>` and `<scratchpad>`; the text is otherwise verbatim.

---

You are the **SDK + x402** builder for Sekisho, a hackathon project (ETHGlobal Tokyo 2026, due Sun 27 Sep 09:00 JST: be efficient, P0 first). Sekisho is a compliance checkpoint for AI agent payments. Before an agent signs an x402 payment (payer side), or before a paid agent verifies one (payee side), a hook asks the Sekisho gate to screen the counterparty. On ALLOW the payment proceeds; on HOLD or BLOCK it aborts **before any signature exists**.

Repo: `<repo>`. Read first:
- `AGENTS.md` (rules; especially fail closed: an unreachable gate counts as HOLD)
- `docs/api.md` (the gate API contract your client and models must mirror)
- `PRD.md` Sections 5 (scenarios), 10.1 (SDK and hooks), 10.2 (vendor agents) and 10.4 (the S5 spoofed payer), plus 3.1 (what the Intercepta judges look for)

**Ground truth for x402:** `x402==2.24.0` is installed at `.venv/lib/python3.11/site-packages/x402/`. Read its source; the PRD says "confirm on day one" for several names. A research agent is writing verified findings to `<scratchpad>/research/x402-mcp.md` (it may still be in progress; its raw notes are in the same `research/` folder: `x402-src/`, `introspect_x402.py`, `offline_behaviour_x402.py`). Trust the installed source over the PRD and the memo, and list every PRD correction in your report.

Pin down specifically:
- the hook context field names
- `AbortResult`
- which exception `x402HttpxClient` raises on abort, and whether it's wrapped
- `set_spend_controls`
- `get_payment_settle_response`
- `decode_payment_signature_header`
- the middleware's behaviour on abort
- the v2 payload structure

**You own** (touch nothing else; other agents are building the gate, the treasury agent and the console in parallel):
- `sdk/sekisho/`: `__init__.py` (already there with a docstring; extend it), `client.py`, `models.py`, `errors.py`, `x402_hooks.py`
- `sdk/README.md` (install with `pip install -e sdk[x402]`, one-screen usage for both hooks and the MCP config pointer)
- `sdk/tests/`
- `agents/vendors/app.py`, `agents/vendors/run_all.py`
- `agents/rogue/spoofed_payer.py`
- `agents/tests/test_vendors.py` and `agents/tests/test_rogue.py`. Another agent writes other files in `agents/tests/`, so use only these names plus your own fixture files prefixed `vendors_`.

**SDK interface.** The treasury agent, demo runner and MCP server are being written against this now, so implement it exactly:
```python
# sdk/sekisho/__init__.py exports:
#   SekishoClient, SekishoUnavailable, Decision, payer_hook, payee_hook, CURRENT, parse_abort_reason, unwrap_payment_aborted
class SekishoClient:
    def __init__(self, base_url: str, timeout_s: float = 10.0): ...
    async def screen(self, *, counterparty: str, direction: str, amount: str, asset: str, payment_chain_id: int,
                     source: str, agent_id: str, purpose: str = "", resource: str = "",
                     untrusted_context: str | None = None) -> Decision        # raises SekishoUnavailable on connect errors, timeouts, 5xx
    async def report_payment(self, case_id: str, tx_hash: str, network: str) -> None
    async def report_hold(self, case_id: str, hold_id: int, deposit_tx: str) -> None
    async def get_case(self, case_id: str) -> dict
    async def list_cases(self, limit: int = 10, **filters) -> list[Decision]
    async def policy(self) -> dict
    async def aclose(self) -> None      # also usable as `async with SekishoClient(...)`
CURRENT: contextvars.ContextVar   # per PRD 10.1: the agent sets a fresh dict; the payer hook writes "decision" into it
def payer_hook(sk: SekishoClient, agent_id: str): ...   # for client.on_before_payment_creation
def payee_hook(sk: SekishoClient, agent_id: str): ...   # for server.on_before_verify
def parse_abort_reason(reason: str) -> tuple[str, str | None, str]  # "BLOCK|cs_…|headline" -> ("BLOCK", "cs_…", "headline"); "HOLD|unavailable|…" -> ("HOLD", None, …)
def unwrap_payment_aborted(exc: BaseException): ...     # returns the x402 abort exception if exc is one or wraps one (walk __cause__/__context__), else None
```
`Decision` is a pydantic model mirroring ScreeningDecision in `docs/api.md`. Use `extra="allow"` so gate additions don't break old SDKs. The SDK depends only on httpx and pydantic; x402 is an optional extra. Import x402 lazily inside `x402_hooks.py`, so `import sekisho` works without it.

**Vendors (PRD 10.2):** one FastAPI app configured by env (`VENDOR_ID`, `VENDOR_NAME`, `PAY_TO`, `MODE` = normal or injection, `PORT`, `PRICE` default `$0.05`, plus `SEKISHO_URL`, `FACILITATOR_URL` and `X402_NETWORK` from `sekisho_gate.config.get_settings()`, which you may import).
- It runs `x402ResourceServer` + `HTTPFacilitatorClient` + `ExactEvmServerScheme` on `eip155:84532`, with `server.on_before_verify(payee_hook(...))` and `PaymentMiddlewareASGI`.
- `GET /v1/market-data?pair=ETH-JPY` returns `{pair, bid, ask, ts, source: "sample data"}`. `MODE=injection` adds `notes` with the exact attack text from PRD 10.2.
- `GET /healthz` returns the vendor id, payTo and mode.
- The P1 `payer_gate` middleware returns a clear 403 JSON (`{"error": "payer_refused", "verdict", "case_id", "reasons"}`) for payers who aren't ALLOWed, running before the x402 middleware.
- `run_all.py` starts the four instances from the PRD 10.2 table (kabuto 4021 → VENDOR_CLEAN_PAYTO; nightowl 4022 → VENDOR_MIXER_PAYTO; ronin-signals 4023 → VENDOR_SANCTIONED_PAYTO; oracle-feeds 4024 → VENDOR_CLEAN_PAYTO in injection mode). It uses prefixed log lines, refuses to start a vendor whose PAY_TO is empty (with a clear message), and shuts all children down on Ctrl-C.
- Vendor names are fictional and must stay clearly fictional.
- Vendors need no keys: the facilitator settles.

**Rogue payer (PRD 10.4):** `spoofed_payer.py` gets the 402 requirements from vendor-clean, builds an x402 v2 payment with `authorization.from = ROGUE_PAYER_ADDR` and a random signature (we hold no key for that address), sends it in the right header, and prints the refusal. Label all output "Simulated spoofed payer". Exit code 0 if the vendor refused, 1 if it accepted.

**Tests (P0, PRD 12):**
1. **The payer hook aborts before signing on BLOCK.** Use the real x402 client with an EVM signer, a respx-mocked vendor that returns a proper v2 402, and a respx-mocked gate that returns BLOCK. Assert that no request carrying the payment-signature header is ever sent, and that the signer's sign method was never called (wrap or spy it). Do the same for HOLD, and for the gate being unreachable (fail closed).
2. On ALLOW the flow proceeds to signing. It's fine if settlement is mocked.
3. **The payee hook refuses a flagged payer.** Drive the vendors app through `httpx.ASGITransport` with a crafted payment for a flagged payer, the gate mocked to BLOCK, and the facilitator mocked (including anything the middleware calls at startup, such as `/supported`). Assert a refusal (403 via payer_gate, or 402 with the reason) and that the facilitator's verify and settle were never called.
4. Unit tests for `parse_abort_reason`, `unwrap_payment_aborted` and the client's `SekishoUnavailable` mapping.

Mock HTTP with respx in tests only. The running code has no mock mode.

**Live checks:** you may `GET https://x402.org/facilitator/supported` (public, read-only) to confirm the network, scheme and version. Don't attempt payments: no funded keys exist yet. You may start one vendor locally (`PAY_TO` = any checksummed address, gate not running) and curl `/v1/market-data` without payment to confirm it returns a proper v2 402. Paste the decoded PAYMENT-REQUIRED header in your report.

Rules: no git commands that write (the lead commits). Don't install packages; if one is missing, report it.

Final report (concise):
- files
- the pytest summary (verbatim)
- the confirmed x402 API table, with the PRD corrections
- the decoded 402 sample
- how to run the vendors and the rogue payer
- anything the treasury-agent builder must know (e.g. the exact exception raised on abort, and how to read the settlement tx hash)

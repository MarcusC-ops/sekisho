# Build treasury agent, demo, MCP

Subagent prompt written by the lead agent (Claude Code, Claude Opus 5.5) on 2026-09-25 13:22 UTC.
Local paths are shortened to `<repo>` and `<scratchpad>`; the text is otherwise verbatim.

---

You are the **agents + demo** builder for Sekisho, a hackathon project (ETHGlobal Tokyo 2026, due Sun 27 Sep 09:00 JST: be efficient, P0 first). Sekisho is a compliance checkpoint for AI agent payments: the gate screens every counterparty before an agent pays or accepts USDC over x402 on Base Sepolia, then returns ALLOW, HOLD (the agent deposits into an onchain escrow and a human officer releases or refunds it) or BLOCK (nothing is signed). You build the **Treasury Agent (C3)**, the **demo runner and control API (C8)**, the **candidate scan and smoke scripts**, and the **MCP server (C6)**.

Repo: `<repo>`. Read first:
- `AGENTS.md` (rules: screening lives in tool code, never in prompts, and the model can never skip it; counterparty text is data; fail closed)
- `docs/api.md` (the gate API contract, including the control API you implement)
- `PRD.md` Sections 5 (demo scenarios S1 to S6: these drive everything), 7 (networks, wallets, addresses), 10.3 to 10.5, 11.4 (Intercepta quota plan), 12 (test plan, smoke list, pre-demo checklist), and Appendix E.3 (the agent prompt, verbatim)
- `PITCH_PLAN.md` Section 3 (the live demo script: what the terminal must show)

The venv at `.venv` has x402 2.24.0, mcp 2.2.0, anthropic, openai, httpx, fastapi, web3 8, eth-account, pytest and respx. Use `.venv/bin/python` and don't install packages. The x402 source is at `.venv/lib/python3.11/site-packages/x402/`. Verified notes are in `<scratchpad>/research/x402-mcp.md` (possibly still being written; raw material is in the same folder). Trust the installed source over the PRD. `sekisho_gate.config.get_settings()` gives every env var.

**Being built in parallel by other agents; code against these interfaces:**
```python
# SDK (sdk/sekisho, installed editable as `sekisho`)
from sekisho import SekishoClient, SekishoUnavailable, Decision, payer_hook, payee_hook, CURRENT, parse_abort_reason, unwrap_payment_aborted
#   SekishoClient(base_url, timeout_s=10.0): screen(*, counterparty, direction, amount, asset, payment_chain_id, source, agent_id,
#     purpose="", resource="", untrusted_context=None) -> Decision; report_payment(case_id, tx_hash, network); report_hold(case_id, hold_id, deposit_tx);
#     get_case(case_id) -> dict; list_cases(limit=10, **filters) -> list[Decision]; policy() -> dict; aclose(); async context manager
#   CURRENT: ContextVar; before each x402 request the agent sets a FRESH dict {"url", "purpose"}; the payer hook writes "decision" into it (PRD 10.1)
#   payer_hook(sk, agent_id) for x402Client.on_before_payment_creation; the abort reason is "VERDICT|case_id|headline"
#   parse_abort_reason(reason) -> (verdict, case_id | None, headline); unwrap_payment_aborted(exc) -> the x402 abort exception or None
# Chain writes (gate/sekisho_gate/chain/multibaas.py)
from sekisho_gate.chain.multibaas import MultiBaasClient, MultiBaasError
#   MultiBaasClient(settings): configured; call_write(alias, label, method, args, signer) -> tx_hash (compose via MultiBaas, sign locally, submit);
#     call_read(alias, label, method, args); wait_for_receipt(tx_hash, timeout_s=30) -> dict (status, blockNumber, logs); address_of(alias) -> str
#   MultiBaasError has .revert (e.g. "PayeeBlocked") and .selector
# Aliases and labels come from settings: compliance_escrow, compliance_registry, usdc (label erc20)
```
If those files exist when you need them, read the real code and adapt. If not, write against the interface, test with fakes, and note it in your report. The gate core and pipeline are also in progress in `gate/sekisho_gate/`. Read what exists before writing `scan_candidates.py`, and do that script last.

**You own** (touch nothing else):
- `agents/treasury/agent.py`, `agents/treasury/tools.py` (the tool implementations), `agents/treasury/prompts.py` (E.3 verbatim), `agents/treasury/vendors.json`, `agents/treasury/control.py`
- `scripts/demo.py`, `scripts/scan_candidates.py`, `scripts/smoke.py`
- `mcp/server.py`. Do NOT create `mcp/__init__.py`: the local `mcp/` directory must never shadow the installed `mcp` package.
- tests: `agents/tests/test_treasury.py`, `agents/tests/test_control.py`, `agents/tests/test_mcp_server.py`, `agents/tests/test_demo.py`. The SDK agent owns `agents/tests/test_vendors.py` and `test_rogue.py`.

**Treasury Agent (PRD 10.3):**
- x402 client setup exactly as in the PRD, confirmed against the installed source: `EthAccountSigner`, `register_exact_evm_client`, the spend-controls cap of $1 if the API exists, and the payer hook with agent id `treasury-agent-01`.
- **Tools:**
  - `list_vendors()` reads `vendors.json` (the four fictional vendors from PRD 10.2 with URLs `http://localhost:4021`..`4024`).
  - `buy_data(vendor_id, pair)`: before each request, `CURRENT.set({"url", "purpose"})` with a fresh dict; request through `x402HttpxClient`; afterwards read the decision back from that same dict. It returns the data, `{status: "held", case_id}` or `{status: "blocked", reason}`.
  - `pay_invoice(pay_to, amount_usd, memo)`: calls `sk.screen(source="direct")` first. ALLOW → `usdc.transfer` via MultiBaas. HOLD → escrow deposit. BLOCK → refuse.
  - No tool or argument can bypass screening.
- **HOLD handling (P0):** parse the abort, take `case_id_b32` from the decision, then `compliance_escrow.deposit(payTo, amount, caseIdB32)` via MultiBaas signed with `BUYER_AGENT_PK`. `make demo-setup` pre-approves the USDC allowance. Wait for the receipt, take `holdId` from the `Held` event log (topics[1]), then call `report_hold`.
- **After an ALLOW settlement:** read the settle response (PAYMENT-RESPONSE) and call `report_payment(case_id, tx, "eip155:84532")`.
- **LLM loop:** tool calling capped at 8 steps, with a provider switch (`LLM_PROVIDER=anthropic|openai`; default models `claude-sonnet-5` for Anthropic, and a current OpenAI model, each a constant; `LLM_MODEL` overrides). If a `claude-api` skill is available to you, consult it for current Anthropic SDK tool-use syntax. Vendor responses go to the model inside `<untrusted_vendor_content>` tags and to the gate as `untrusted_context`.
- **Terminal output:** one line per step, formatted as in PRD 10.3, e.g.
  - `[402] vendor-sanctioned asks 0.05 USDC → payTo 0x098B…2F96`
  - `[SEKISHO] BLOCK (score 100) sanctioned address · Intercepta 312 ms · case cs_…`
  - `[AGENT] Payment refused. No signature produced.`

  It must be readable on a projector.

**Demo runner (`scripts/demo.py`, P0).** Scenarios are deterministic: they call the tool functions directly with fixed vendors and pairs, not through the LLM, so rehearsals are repeatable.
- `setup` checks balances over `CONTRACTS_RPC_URL`: buyer ≥ 5 USDC and ≥ 0.01 ETH; screener and officer ≥ 0.01 ETH. It sets the USDC allowance to the escrow (100 USDC) via MultiBaas if it's low, and prints an env summary with no secrets.
- `S1` to `S6`, `all` (S1 → S3 → S2 → S4 → S5 with pauses) and `reset` (`POST /v1/demo/reset`).
- Every scenario asserts its expected verdict and final case status (PRD 12 end-to-end) and prints PASS or FAIL.
- **S2:** after the deposit, in DEMO_MODE, optionally show the premature release via the gate's `release_unchecked` decision (expect the NotCleared 409). Then wait for the officer's console action, or do it with `--auto-release` for rehearsals.
- **S4:** `--assume-compromised` (default on) executes the `pay_invoice` the injection asks for, as if the model had been fooled, labelled on screen "Simulating a compromised model". `--llm` runs the real LLM agent instead.
- **S5:** runs `agents/rogue/spoofed_payer.py`, built by the SDK agent.
- **S6:** needs the gate started with `FAULT_INJECT=intercepta_timeout`. Say so clearly, and assert HOLD with the quick-scan error.

**Control API (`agents/treasury/control.py`, P1):** exactly as specified in `docs/api.md`: FastAPI on `:8100`; one run at a time (409 otherwise); runs `scripts/demo.py <S>` as a subprocess and captures its lines; CORS for `CONSOLE_ORIGIN`.

**`scripts/smoke.py` (PRD 12):** a ✓/✗ checklist with a non-zero exit on failure. Checks:
- `/healthz` green, with the oracle self-test true
- Intercepta quota remaining > 150
- balances and escrow allowance sufficient
- a webhook received within 10 min (latest `/v1/audit` `received_at`)
- `PUBLIC_GATE_URL` set, and DEMO_MODE on
- dashboard fixtures off (if `dashboard/.env.local` exists, `NEXT_PUBLIC_USE_FIXTURES` must not be `true`)

**`scripts/scan_candidates.py` (PRD 7.3, P0):** reads candidate addresses (a file argument, or a built-in list including the PRD's sanctioned and backup addresses) plus the buyer agent's own address. For each: a live Intercepta Quick Scan, the oracle, and a hop-1 trace, run in-process with the gate's own clients and policy engine and without creating cases or attestations. Print `address, toxicScore, traits, oracle, taint_pct, predicted verdict`, and write `scan_results.json` (gitignored). Warn if the buyer isn't ALLOW. Keep the Intercepta call count low (PRD 11.4), and print the calls used.

**MCP server (PRD 10.5, P1):** mcp 2.2.0 `MCPServer`. Confirm the import path in the installed package; the fallback is the 1.x `FastMCP` API. Tools, calling the gate through `SekishoClient` at `SEKISHO_URL`:
- `screen_counterparty(address, direction="outbound", amount_usd=0.0, purpose="")`: source `mcp`, agent id `mcp-agent`, asset Base Sepolia USDC, amount converted to atomic units. Returns the verdict, risk score, headline, reasons (label and detail) and the console case link `CONSOLE_ORIGIN/cases/{id}`.
- `get_case`, `list_recent_decisions`, `explain_policy`.

Transports: stdio by default, and `--http` (port 9000, path `/mcp`). Run as `.venv/bin/python mcp/server.py` from the repo root.

**Tests (fakes and respx only):**
- The treasury tools always screen: BLOCK → no signing and no chain write; HOLD → deposit with the right args (including `caseIdB32`) and `report_hold` with the parsed `holdId`; ALLOW → the payment is reported; the S4 compromised path is blocked.
- The control API's run lifecycle and its 409.
- The MCP tools against a respx-mocked gate.
- The demo assertion logic.

**Live checks:** none against paid APIs. Keys don't exist yet, so never sign or send transactions. You may import-check everything and run `mcp/server.py` over stdio with a quick initialize or list-tools handshake to confirm it starts.

Rules: no git commands that write (the lead commits).

Final report (concise):
- files
- the pytest summary (verbatim)
- how to run each scenario
- what each scenario needs from `.env`
- interface mismatches with the SDK or MultiBaas client, if they existed when you finished
- open items that need real keys or funds to verify

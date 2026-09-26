# Verify x402 and MCP SDK APIs

Subagent prompt written by the lead agent (Claude Code, Claude Opus 5.5) on 2026-09-25 13:00 UTC.
Local paths are shortened to `<repo>` and `<scratchpad>`; the text is otherwise verbatim.

---

You are verifying third-party Python SDK APIs for a hackathon build called Sekisho (an AML/compliance checkpoint that screens counterparties before AI agents pay each other over x402). The PRD is at `<downloads>/PRD (2).md (now committed as PRD.md)`. Read Sections 10.1 to 10.5 (roughly lines 791-995) to see exactly what the team plans to use. Several items there say "confirm on day one". Your job is to confirm or correct each one against the real source code, so builders can write working code directly from your memo.

Rules:
- Do NOT install anything into the user's environment and do not execute any third-party package code.
- Prefer reading the source on GitHub via `gh api` (the user is authenticated) or WebFetch. The x402 Python SDK lives in the `x402-foundation/x402` repo (check `coinbase/x402` if it moved or redirects) under `python/`, with examples under `examples/python/`. PyPI JSON: https://pypi.org/pypi/x402/json and https://pypi.org/pypi/mcp/json.
- If reading via GitHub is impractical, you may run `pip download <pkg>==<ver> --no-deps -d <dir>` into `<scratchpad>/research/pkgs/` and unzip the wheel to read the source. Never import or run it.

Confirm for `x402==2.24.0` (does the version exist? What is the latest?):
1. Every import listed in PRD 10.1: is each module path correct? If not, give the right one.
2. Client side: `x402Client`, `register_exact_evm_client(client, signer)`, `EthAccountSigner(Account)`, and `client.set_spend_controls(...)` (does it exist, and what argument format?). For `client.on_before_payment_creation(hook)`: the hook signature (sync or async), the context type name, and the exact attribute names for pay_to, amount (attribute or method?), asset and network (e.g. `ctx.selected_requirements.pay_to`). What the hook returns to abort (`AbortResult(reason=...)`?) and to continue (None?). Which exception the client raises on abort (`PaymentAbortedError`? which module?). Does `x402HttpxClient` wrap it, e.g. in an httpx exception? Trace the code path.
3. `x402HttpxClient` usage: constructor args, and is it an `httpx.AsyncClient` subclass? How to read the settlement response: confirm `x402HTTPClient(client).get_payment_settle_response(lambda n: r.headers.get(n))` and which field holds the tx hash (`.transaction`?).
4. Server side: `x402ResourceServer(HTTPFacilitatorClient(FacilitatorConfig(url=...)))` and `server.register(network, ExactEvmServerScheme())`. For `server.on_before_verify(hook)`: the hook signature, context type (`VerifyContext`?) and attribute names (`ctx.payment_payload.payload["authorization"]["from"]`, `ctx.requirements.amount/.asset/.network`), the abort return type, and what the HTTP middleware returns to the client on abort (402 with the reason where?). Also the fields of `RouteConfig(accepts=[PaymentOption(scheme, pay_to, price, network)], mime_type, description)`; how `PaymentMiddlewareASGI(..., routes=..., server=...)` is used in FastAPI (via `app.add_middleware`?); and whether the server needs an explicit initialize or startup call (e.g. fetching facilitator /supported). The v2 header names (`PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, `PAYMENT-RESPONSE`). The helper that decodes the PAYMENT-SIGNATURE header (`decode_payment_signature_header` in `x402.http.utils`?). The exact v2 payment payload JSON structure, needed to craft a spoofed payload as in PRD 10.4: `{"x402Version": 2, "accepted": ..., "payload": {"signature", "authorization": {...}}}`. Is the header value plain base64 of the JSON?
5. Any async vs sync gotchas, and anything else a builder would trip on (e.g. the network string format "eip155:84532", the price format "$0.05").
Summarise the canonical example files (e.g. examples/python/clients/httpx/main.py, servers/fastapi, servers/advanced/hooks.py or wherever they now live) with their key code lines.

Confirm for `mcp==2.2.0` (does it exist?): `from mcp.server.mcpserver import MCPServer` (or the correct path), the `@mcp.tool()` decorator, and how to run stdio vs streamable HTTP with host, port and path (e.g. `mcp.run(transport="streamable-http", ...)` or via settings). If 2.x doesn't exist or differs, give the working 1.x equivalent (`from mcp.server.fastmcp import FastMCP`) with its run options.

Output: write the findings to `<scratchpad>/research/x402-mcp.md`. Mark each item CONFIRMED, CORRECTED (with the correct code) or UNKNOWN, citing the source file path and line (GitHub URL). Include short verbatim snippets of the key signatures and class definitions. Keep it concise but precise. Your final message: a summary of at most 15 lines listing the corrections to the PRD.

# sekisho: Python SDK

Screen the other wallet before an AI agent pays or accepts an x402 payment. On ALLOW the
payment goes ahead. On HOLD or BLOCK it stops before any signature exists. If the gate
can't be reached, that counts as HOLD (fail closed).

```bash
pip install -e "sdk[x402]"      # run from the repo root; without [x402] you get only the client (httpx + pydantic)
```

## Payer side: the buying agent

```python
from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client
from sekisho import CURRENT, SekishoClient, parse_abort_reason, payer_hook, unwrap_payment_aborted

sk = SekishoClient("http://localhost:8000")
client = x402Client()
register_exact_evm_client(client, EthAccountSigner(account))
client.on_before_payment_creation(payer_hook(sk, "treasury-agent-01"))

CURRENT.set({"url": url, "purpose": "Buy ETH/JPY market data"})   # a fresh dict for every request
try:
    async with x402HttpxClient(client) as http:
        r = await http.get(url)          # ALLOW: signed, paid; check r.status_code == 200
except Exception as exc:
    aborted = unwrap_payment_aborted(exc)    # x402HttpxClient wraps the abort in its own PaymentError
    if aborted is None:
        raise                                # not Sekisho (e.g. x402's own $1 spend cap)
    verdict, case_id, headline = parse_abort_reason(aborted.reason)   # HOLD with case_id None: gate unreachable
decision = CURRENT.get().get("decision")     # the Decision the hook wrote (ALLOW included)
```

## Payee side: the paid agent

```python
from sekisho import SekishoClient, payee_hook

server.on_before_verify(payee_hook(SekishoClient(SEKISHO_URL), "vendor-clean"))  # x402ResourceServer
```

When the payer isn't ALLOWed, the middleware answers 402, and the PAYMENT-REQUIRED header's
`error` is `VERDICT|case_id|headline`. This happens before verify, the handler or settle.
[`agents/vendors/app.py`](../agents/vendors/app.py) also puts a 403 `payer_refused` middleware
in front.

## Direct calls and errors

The x402 snippets above assume an initialized signer account, resource URL and
resource server. Use only fresh Base Sepolia testnet accounts. They are integration
fragments; see [the treasury tools](../agents/treasury/tools.py) for payment terms,
budget controls, settlement reporting and the complete execution path.

A complete screening-only example is in [examples/screen_before_signing.py](examples/screen_before_signing.py).
Run `python sdk/examples/screen_before_signing.py 0xCOUNTERPARTY` from the repository root
with the SDK installed and a gate on localhost:8000. It never signs or sends funds;
HTTP errors and incomplete decisions return HOLD. Exit code 0 means ALLOW, 1 means
HOLD or BLOCK. The public website distributes this same tested file.


`await sk.screen(counterparty=…, direction=…, amount=…, asset=…, payment_chain_id=…, source=…, agent_id=…)`
returns a `Decision`, which mirrors ScreeningDecision in [docs/api.md](../docs/api.md). The client
also has `report_payment`, `report_hold`, `get_case`, `list_cases`, `policy` and `aclose`
(or use `async with`).

It raises two errors:
- `SekishoUnavailable`: a connection error, timeout, 5xx or unusable response body. Treat it as HOLD.
- `SekishoRequestError`: a 4xx.

## MCP

An agent without x402 hooks can call the gate through the [MCP server](../mcp/server.py). `make mcp` starts streamable HTTP on port 9000;
the configuration below starts stdio instead.
In a Claude Desktop or Cursor config, use absolute paths:

```json
{"mcpServers": {"sekisho": {"command": "/abs/path/.venv/bin/python", "args": ["/abs/path/mcp/server.py"],
  "env": {"SEKISHO_URL": "http://localhost:8000"}}}}
```

## Verification and deployment boundary

```bash
.venv/bin/python -m pytest sdk/tests -q
```

The SDK talks to the full private gate. The hosted public runner intentionally does
not expose `/v1/screen` or the rest of this API; use a gate you operate. HOLD pauses
signing and does not itself deposit funds. The hosted paid/refused flow is verified;
the full provider-triggered HOLD journey remains pending. See
[readiness](../docs/readiness.md) for the distinction.

# x402 2.24.0 and mcp 2.2.0: API check for Sekisho PRD 10.1 to 10.5

**Verdict.** Every x402 import and class in the PRD exists as written. The corrections are about behaviour:

- The buyer-side abort reaches the caller wrapped in another exception.
- Hooks must catch every exception.
- The S5 `accepted` block must be copied verbatim from the 402.
- In mcp 2.x, host, port and path go in `run()`.

**Method.**
- **Source.** I read tag `pypi-x402@v2.24.0` (commit `71eb9a5`) and mcp tag `v2.2.0` (commit `9972c21`).
- **Installed copy.** The venv copies (`<repo>/.venv/lib/python3.11/site-packages/{x402,mcp}`) are byte-identical to those tags. I diffed them; only unshipped test files differ. So the GitHub line links below match the installed code.
- **Behaviour.** I checked behaviour with an offline run. The buyer used an httpx `MockTransport`. The seller used an in-process fake facilitator with Starlette `TestClient`. No network calls were made. Scripts: `scratchpad/research/offline_behaviour_x402.py` and `introspect_x402.py`.

**Status:** CONFIRMED, CORRECTED or UNKNOWN. Nothing below is UNKNOWN.

**Link bases:**
- x402 source: `https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/`
- x402 examples: `.../71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/examples/python/`
- mcp: `https://github.com/modelcontextprotocol/python-sdk/blob/9972c21aa42054fb1450c5fc614761ed11847ec6/src/mcp/`

---

## 0. Versions: CONFIRMED

- **x402 2.24.0** exists and is the latest on PyPI (uploaded 2026-09-22, Python >= 3.10). `x402[httpx,fastapi,evm]` are all valid extras.
- **mcp 2.2.0** exists and is the latest (2026-09-07). The `cli` extra exists. The latest 1.x release is 1.30.0.

## 1. PRD 10.1 imports: all CONFIRMED

Every line imports cleanly in the venv.

| PRD import | Status and location |
|---|---|
| `from x402.schemas import AbortResult, PaymentCreationContext` | CONFIRMED. [schemas/hooks.py L23-33](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/schemas/hooks.py#L23-L33), [L378-388](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/schemas/hooks.py#L378-L388) |
| `VerifyContext` ("same module, confirm") | CONFIRMED: `from x402.schemas import VerifyContext`. [schemas/hooks.py L233-249](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/schemas/hooks.py#L233-L249) |
| `from x402 import x402Client` | CONFIRMED. [client.py L72](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/client.py#L72) |
| `PaymentAbortedError` ("confirm module") | CONFIRMED: `from x402.schemas import PaymentAbortedError`; `from x402 import PaymentAbortedError` also works. [schemas/errors.py L72-81](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/schemas/errors.py#L72-L81) |
| `from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption, x402HTTPClient` | CONFIRMED. [http/\_\_init\_\_.py L17-57](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/__init__.py#L17-L57) |
| `from x402.http.types import RouteConfig` | CONFIRMED (also exported from `x402.http`). [http/types.py L203-227](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/types.py#L203-L227) |
| `from x402.http.clients import x402HttpxClient` | CONFIRMED (lazy re-export). [http/clients/httpx.py L344](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/clients/httpx.py#L344-L376) |
| `from x402.http.middleware.fastapi import PaymentMiddlewareASGI` | CONFIRMED. [http/middleware/fastapi.py L535-569](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/middleware/fastapi.py#L535-L569) |
| `from x402.server import x402ResourceServer` | CONFIRMED. [server.py L66](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/server.py#L66) |
| `from x402.mechanisms.evm import EthAccountSigner` | CONFIRMED. [mechanisms/evm/signers.py L68-95](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/mechanisms/evm/signers.py#L68-L95) |
| `from x402.mechanisms.evm.exact import ExactEvmServerScheme` | CONFIRMED (alias of `exact/server.py:ExactEvmScheme`). [exact/\_\_init\_\_.py L11](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/mechanisms/evm/exact/__init__.py#L11) |
| `from x402.mechanisms.evm.exact.register import register_exact_evm_client` | CONFIRMED. [exact/register.py L25-70](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/mechanisms/evm/exact/register.py#L25-L70) |

The fixes in sections 2 and 4 need these extra imports:

```python
from x402.http.clients.httpx import PaymentError as X402TransportError   # the wrapper the buyer actually receives
from x402.schemas import NoMatchingRequirementsError
from x402.http.utils import decode_payment_signature_header, decode_payment_required_header
```

Two name traps:

- **`FacilitatorConfig`.** `from x402 import FacilitatorConfig` gives a TypedDict ([schemas/config.py L28](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/schemas/config.py#L28-L37)), not the `x402.http` dataclass. The client accepts both, but a dict config ignores `timeout`. Keep importing it from `x402.http`.
- **`PaymentError`.** `x402.PaymentError` (the base class of `PaymentAbortedError`) and `x402.http.clients.httpx.PaymentError` (the transport wrapper) share a name but are unrelated classes.

## 2. Client (buyer) side

### 2.1 Setup: CONFIRMED

```python
signer = EthAccountSigner(Account.from_key(BUYER_AGENT_PK))   # signers.py L95: __init__(self, account: LocalAccount)
client = x402Client()                                          # client.py L92: __init__(payment_requirements_selector=None)
register_exact_evm_client(client, signer)                      # register.py L25: (client, signer, networks=None, policies=None) -> client
client.set_spend_controls({"max_amount_per_payment": "$1"})   # client_base.py L462: (controls: SpendControls | Literal[False]) -> Self
client.on_before_payment_creation(payer_hook(sk, "treasury-agent-01"))  # client.py L128 -> Self
```

- **Registration.** `register_exact_evm_client` registers the V2 scheme on `eip155:*` and every V1 network. You can also pass a bare `LocalAccount`; it is wrapped automatically ([exact/client.py L27-38](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/mechanisms/evm/exact/client.py#L27-L38)).
- **Spend-control format.** `SpendControls` is a TypedDict ([client_base.py L204-213](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/client_base.py#L204-L213)):
  `{"max_amount_per_payment": "$1" | 1.0 | False, "allowed_assets": True | [{"network", "asset", "max_amount_per_payment": "<atomic int str>"}]}`.
- **The PRD call is redundant.** `"$1"` is already the default (`DEFAULT_MAX_AMOUNT_PER_PAYMENT`, [L184](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/client_base.py#L184)). Base Sepolia USDC is a default asset, so it is allowed.
- **GOTCHA: the spend cap runs before the Sekisho hook.** Spend controls are applied during requirement selection ([client_base.py L773](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/client_base.py#L773)).
  - An over-cap price never reaches Sekisho, so no case is created.
  - The buyer receives `X402TransportError` with `__cause__` set to `NoMatchingRequirementsError`.
  - Verified offline: the hook was not called.

### 2.2 `on_before_payment_creation` hook: CONFIRMED

- **Type** ([client_base.py L290-292](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/client_base.py#L290-L292)):
  `Callable[[PaymentCreationContext], Awaitable[AbortResult | None] | AbortResult | None]`
  - Sync and async hooks both work; the client auto-detects which ([client.py L250-255](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/client.py#L250-L255)).
  - The hook is awaited inline, in the caller's asyncio task (verified: same task id).
- **Context.** `ctx` is `PaymentCreationContext(payment_required, selected_requirements)`.
- **Fields on `ctx.selected_requirements`** (a pydantic `PaymentRequirements`, [schemas/payments.py L33-60](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/schemas/payments.py#L33-L60)). Values below are from the offline run:
  - `.pay_to`
  - `.amount` is an **attribute**: an atomic `str`, e.g. `"50000"` for $0.05. `.get_amount()` returns the same value.
  - `.asset`, e.g. `"0x036CbD53842c5426634e7929541eC2318f3dCF7e"`
  - `.network`, e.g. `"eip155:84532"`
  - `.scheme`, `.max_timeout_seconds`, `.extra`
- **The PRD's day-one `print(vars(ctx))` check is no longer needed.**
- **Abort and continue.** Return `AbortResult(reason="...")` to abort. `message` is optional and unused on this path. Return `None` to continue.
  - **Only an `AbortResult` instance aborts**, because the code does an `isinstance` check ([client_base.py L791](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/client_base.py#L783-L794)).
  - Returning `False` or a string still signs.
- **What happens on abort.** The client raises `PaymentAbortedError(result.reason)` at L794. That is before the scheme signs (signing is at [L818-827](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/client_base.py#L818-L827)).
  - Nothing is signed. Verified: no `PAYMENT-SIGNATURE` request was sent.
- **ContextVar.** Because the hook runs in the caller's task, `CURRENT.get()` works. The PRD's mutate-the-dict pattern is correct (verified).

### 2.3 The abort through `x402HttpxClient`: CORRECTED (it is wrapped)

Code path:

1. `x402HttpxClient.__init__` installs `x402AsyncTransport` ([httpx.py L363-376](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/clients/httpx.py#L363-L376)).
2. `handle_async_request` receives the 402 and calls `await self._client.create_payment_payload(payment_required)` ([L161](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/clients/httpx.py#L161)).
3. Inside it, `_create_payment_payload_v2_core` raises `PaymentAbortedError`.
4. The exception reaches this handler ([httpx.py L192-195](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/clients/httpx.py#L192-L195)):

```python
        except PaymentError:      # the LOCAL class defined at httpx.py L25, NOT x402.schemas.PaymentError
            raise
        except Exception as e:
            raise PaymentError(f"Failed to handle payment: {e}") from e
```

httpx does not wrap transport exceptions, so `await http.get(...)` raises:

- `x402.http.clients.httpx.PaymentError('Failed to handle payment: Payment aborted: BLOCK|cs_…|headline')`
- `__cause__` is `PaymentAbortedError`, and `__cause__.reason` is your string.
- It is **not** an `httpx.HTTPError`.

The repo's own test asserts this wrapping ([tests/unit/http/clients/test_httpx.py L845-864](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/tests/unit/http/clients/test_httpx.py#L845-L864)), and the offline run confirmed it.

The same wrapper also carries `NoMatchingRequirementsError` (spend cap) and any exception your hook raises. Catch it like this:

```python
try:
    r = await http.get(url, params={"pair": pair})
except X402TransportError as e:
    cause = e.__cause__
    if isinstance(cause, PaymentAbortedError):
        verdict, case_id, headline = cause.reason.split("|", 2)   # maxsplit: the headline may contain "|"
        ...                                                         # HOLD -> escrow flow; BLOCK -> refuse
    elif isinstance(cause, NoMatchingRequirementsError):
        ...                                                         # spend cap or unsupported network; Sekisho never ran
    else:
        raise
```

- **CORRECTED: `payer_hook` must catch every exception**, not only `SekishoUnavailable`, and return `AbortResult("HOLD|unavailable|…")`. An uncaught exception still fails closed (nothing is signed), but it comes out as a wrapped error instead of your verdict string.
- **Guard the chain-id parse.** `int(req.network.split(":")[1])` raises on V1 names such as `"base-sepolia"`, so keep it inside the `try`.

## 3. `x402HttpxClient` and the settlement response

- **Class: CONFIRMED.** `class x402HttpxClient(httpx.AsyncClient)` with `__init__(self, x402_client: x402Client | x402HTTPClient, **kwargs)`.
  - Extra kwargs go straight to `httpx.AsyncClient` (`timeout=`, `base_url=`, `headers=`).
  - Do not pass `transport=`; it raises TypeError as a duplicate kwarg.
  - Use it as `async with x402HttpxClient(client) as http:`.
- **Flow.** Plain request → 402 → hooks → sign → exactly one retry carrying `PAYMENT-SIGNATURE`. If the paid retry also gets a 402, it comes back as a normal response, not an exception ([L167-190](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/clients/httpx.py#L167-L190)).
- **Settlement read: CONFIRMED.** `x402HTTPClient(client).get_payment_settle_response(lambda n: r.headers.get(n))` ([x402_http_client_base.py L154-177](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/x402_http_client_base.py#L154-L177)).
  - It is **sync**.
  - It returns a `SettleResponse` ([schemas/responses.py L62-88](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/schemas/responses.py#L62-L88)).
  - The tx hash is in **`.transaction`** (a str).
  - Other fields: `.success`, `.network`, `.payer`, `.amount`, `.error_reason`, `.error_message`.
  - It raises `ValueError` when there is no `PAYMENT-RESPONSE` or `X-PAYMENT-RESPONSE` header.
  - Verified offline.
- **Before calling `report_payment`, check `r.status_code == 200 and s.success`.**
  - If the vendor's inbound screening refuses the buyer, the buyer gets a plain `402` response. Read the reason with `decode_payment_required_header(r.headers["PAYMENT-REQUIRED"]).error`. Verified offline (`offline_refused_buyer.py`): one signed retry, then a 402 response with no exception.
  - A failed settlement is also a 402, with `PAYMENT-RESPONSE` set to `success=false`.

## 4. Server (seller) side

### 4.1 Construction and initialize: CONFIRMED

```python
server = x402ResourceServer(HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL, timeout=10.0)))
server.register(NET, ExactEvmServerScheme())        # server_base.py L493: register(network, server) -> Self
server.on_before_verify(payee_hook(sk, VENDOR_ID))  # server.py L121 -> Self
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
```

**`FacilitatorConfig`** is a dataclass ([facilitator_client_base.py L136-144](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/facilitator_client_base.py#L136-L144)) with these fields:
- `url` (default `https://x402.org/facilitator`)
- `timeout` (default `90.0`)
- `http_client`, `auth_provider`, `identifier`

**No explicit initialize call is needed.** The chain is:

1. `PaymentMiddlewareASGI.__init__` calls `payment_middleware(..., sync_facilitator_on_start=True)`.
2. That calls `http_server.initialize()`, which calls `server.initialize()`.
3. That makes a **sync, blocking** `GET {url}/supported` ([facilitator_client.py L203-226](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/facilitator_client.py#L203-L226)).
4. Starlette builds the middleware stack on the first ASGI event, which is lifespan startup under uvicorn.

What can go wrong at startup:

- **Transient failure.** It prints `Warning: failed to initialize x402 server: …` and retries on the first paid request ([fastapi.py L252-257, L284-292](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/middleware/fastapi.py#L249-L292)).
- **Route or capability mismatch** (for example, the network is missing from `/supported`). The process calls `os._exit(1)` ([background_init.py L28-41](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/background_init.py#L28-L41)).
- **Slow facilitator.** Set `timeout=10.0`; the default of 90 s blocks startup.

Call `server.initialize()` yourself only if you use `verify_payment` or `build_payment_requirements` directly. Without it they raise `RuntimeError: Server not initialized`.

### 4.2 `on_before_verify` hook: CONFIRMED

- **Type** ([server_base.py L393-396](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/server_base.py#L393-L396)):
  `Callable[[VerifyContext], Awaitable[AbortResult | SkipVerifyResult | None] | AbortResult | SkipVerifyResult | None]`
  - Sync or async; auto-detected ([server.py L374-379](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/server.py#L374-L379)).
- **Context.** `ctx` is `VerifyContext(payment_payload, requirements, payload_bytes, requirements_bytes, declared_extensions, transport_context)`.
- **Field access** (verified offline):
  - `ctx.payment_payload` is a pydantic `PaymentPayload`, and its `.payload` is a plain dict. So `ctx.payment_payload.payload["authorization"]["from"]` works for EIP-3009 payloads.
  - `ctx.requirements.amount`, `.asset`, `.network` and `.pay_to` are all attributes.
- **More robust payer extraction:**
  `p = ctx.payment_payload.payload; payer = (p.get("authorization") or p.get("permit2Authorization") or {}).get("from")`
  - Permit2 payloads use the `permit2Authorization` key ([evm/types.py L110-134](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/mechanisms/evm/types.py#L110-L134)).
  - Base Sepolia USDC defaults to EIP-3009.
- **Abort.** Return `AbortResult(reason=…)`. The server then raises `PaymentAbortedError(result.reason)` ([server_base.py L1392-1396](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/server_base.py#L1386-L1396)).
- **The PRD's "screen in `on_before_verify`, not `on_before_settle`" is CONFIRMED.** The `authorization` flow runs verify, then the route handler, then settle ([payment_flow.py L21-26](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/payment_flow.py#L21-L26); [fastapi.py L331-437](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/middleware/fastapi.py#L331-L437)).

### 4.3 What the client receives when the seller aborts: CONFIRMED

`_process_request_core` catches the exception, sets `error_msg = e.reason`, and rebuilds the 402 ([x402_http_server_base.py L640-663](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/x402_http_server_base.py#L640-L663)). The client gets:

- **HTTP 402** with a JSON body of `{}`.
- A `PAYMENT-REQUIRED` header: base64 of the `PaymentRequired` JSON.
  - Its **`"error"` field is your reason, verbatim**, e.g. `"BLOCK|cs_ROGUE|Simulated spoofed payer"`.
  - It also carries `accepts` and `resource`.
- Neither the facilitator's `verify` nor the route handler is called.

Verified offline.

The hook only runs after the payload decodes and matches:

- **Undecodable header.** Treated as unpaid ([L904-917](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/x402_http_server_base.py#L904-L917)). The client gets 402 `"Payment required"` and the hook never runs.
- **Non-matching `accepted`.** The client gets 402 `"No matching payment requirements"` ([L500-525](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/x402_http_server_base.py#L500-L525)) and the hook never runs.
- **The hook raises.** The client gets a 402 with `error = str(exception)`. That fails closed but leaks the message, so catch everything and return an `AbortResult`.

### 4.4 P1 403 middleware (PRD 10.1): ordering CONFIRMED, snippet needs hardening

- **Ordering.** "Added after the x402 middleware, so it runs first" is correct.
  - Starlette `add_middleware` inserts at index 0 (installed `starlette/applications.py` L104-107, Starlette 1.7.0).
  - `@app.middleware("http")` is simply `add_middleware(BaseHTTPMiddleware, dispatch=func)`.
  - Verified: the request got a 403 and x402 never ran.
- **Fix: wrap the decode.** A garbage header currently causes a 500.

  ```python
  try:
      p = decode_payment_signature_header(h).payload
      payer = (p.get("authorization") or p.get("permit2Authorization") or {}).get("from")
  except Exception:
      payer = None          # fall through; x402 answers 402
  ```
- **Double screening.** With both this middleware and `on_before_verify`, an ALLOW payer is screened twice. Either pass identical `(counterparty, direction, amount, resource)` values so the gate's 10 s idempotency dedups, or drop the hook.
- **The native alternative doesn't fit.** `x402HTTPResourceServer.on_protected_request` returning `AbortProtectedRequestResult(reason)` gives a 403 `{"error": reason}` ([L412-424](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/x402_http_server_base.py#L412-L424)). But it is **not reachable** through `PaymentMiddlewareASGI`, which builds its own `x402HTTPResourceServer` internally ([fastapi.py L240](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/middleware/fastapi.py#L240)). Keep the PRD approach.

### 4.5 `RouteConfig`, `PaymentOption` and the middleware: CONFIRMED

- **`PaymentOption`** is a dataclass ([http/types.py L191-200](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/types.py#L191-L200)): `PaymentOption(scheme, pay_to, price, network, max_timeout_seconds=None, extra=None)`. `pay_to` and `price` may also be callables.
- **`RouteConfig`** is a dataclass with these fields:
  - `accepts`: a `PaymentOption` or a list of them
  - `resource`, `description`, `mime_type`
  - `service_name`, `tags`, `icon_url`
  - `custom_paywall_html`, `unpaid_response_body`, `settlement_failed_response_body`
  - `extensions`, `hook_timeout_seconds`
- **Route key.** `"GET /v1/market-data"` is correct; the query string is ignored when matching.
- **Middleware.** `PaymentMiddlewareASGI(app, routes, server, paywall_config=None, paywall_provider=None)`, registered with `app.add_middleware(...)`.
- **Price conversion.** `price="$0.05"` on `eip155:84532` produced this `accepts[0]` (verified):
  `{"scheme":"exact","network":"eip155:84532","asset":"0x036CbD53842c5426634e7929541eC2318f3dCF7e","amount":"50000","payTo":…,"maxTimeoutSeconds":300,"extra":{"name":"USDC","version":"2"}}`
  - Accepted price forms: `"$0.05"`, `"0.05"`, `0.05`, `"0.05 USDC"`, or `AssetAmount(amount, asset, extra)` ([schemas/helpers.py L325-351](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/schemas/helpers.py#L325-L351)).
  - `maxTimeoutSeconds` defaults to 300 ([server_base.py L715](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/server_base.py#L715)).

### 4.6 Headers, encoding and the decode helper: CONFIRMED

- **Header names** ([http/constants.py L4-6](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/constants.py#L4-L9)):
  - `PAYMENT-SIGNATURE` on the request
  - `PAYMENT-REQUIRED` on the 402 response
  - `PAYMENT-RESPONSE` on the settled response
  - V1 legacy names: `X-PAYMENT` and `X-PAYMENT-RESPONSE`
  - Lookups are case-insensitive.
- **Encoding.** Each value is **plain standard base64** of UTF-8 camelCase JSON: `base64.b64encode`, not urlsafe ([http/utils.py L18-25](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/utils.py#L18-L25)).
- **Decode helpers.** `decode_payment_signature_header(h) -> PaymentPayload` lives in `x402.http.utils` ([L33-44](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/http/utils.py#L33-L44)) and is re-exported from `x402.http`. `decode_payment_required_header` and `decode_payment_response_header` sit next to it.

### 4.7 The v2 payload and the S5 spoof (PRD 10.4): CONFIRMED, with 2 conditions

This is the wire shape, identical to what the SDK builds ([client_base.py L840-846](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/client_base.py#L840-L846); [evm/types.py L26-44](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/mechanisms/evm/types.py#L26-L44)):

```json
{"x402Version": 2,
 "accepted": {"scheme":"exact","network":"eip155:84532","asset":"0x036C…CF7e","amount":"50000",
              "payTo":"0x…","maxTimeoutSeconds":300,"extra":{"name":"USDC","version":"2"}},
 "payload": {"authorization": {"from":"0x…","to":"0x…","value":"50000","validAfter":"0",
                               "validBefore":"<unix ts>","nonce":"0x<32 bytes hex>"},
             "signature":"0x<65 bytes hex>"},
 "resource": {"url":"…","description":"…","mimeType":"…"}}
```

`resource` and `extensions` are optional.

The PRD's S5 code works unchanged. Verified: the vendor hook saw the rogue `from` and returned a 402 before verification. It depends on two conditions:

1. **Copy `accepts[0]` verbatim:**
   `requirements_from_402 = json.loads(base64.b64decode(r402.headers["PAYMENT-REQUIRED"]))["accepts"][0]`
   - The server requires an exact match on scheme, network, amount, asset, payTo and maxTimeoutSeconds.
   - `extra` must be a superset of the server's `extra` ([server_base.py L245-273](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/server_base.py#L245-L273)).
   - Otherwise the client gets 402 "No matching payment requirements", and **screening never runs**.
2. **Use the atomic amount:** `amount = requirements_from_402["amount"]` (an atomic string).

## 5. Other gotchas

- **Use the async classes** (`x402Client`, `x402ResourceServer`, `HTTPFacilitatorClient`) with httpx and FastAPI, not the `*Sync` variants. Hooks may be `def` or `async def`.
- **Network strings are CAIP-2 everywhere:** `"eip155:84532"` in `server.register`, `PaymentOption.network` and the hook fields. `x402.schemas.Network` is just an alias for `str`.
- **No event-loop patching.** `nest-asyncio` is a declared dependency but is never imported by the code.
- **When the buyer is charged.** Settlement only happens after the handler returns a status below 400. A handler that returns 400 or higher means no settle, so the buyer is not charged.
- **Don't use `x402.mcp.create_payment_wrapper` with mcp 2.x.** It imports `mcp.server.fastmcp` ([x402 mcp/server.py L95](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/python/x402/mcp/server.py#L95)), which no longer exists in 2.x. The PRD does not use it.

## 6. Canonical examples

All paths are under `examples/python/` at commit 71eb9a5.

**[clients/httpx/main.py](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/examples/python/clients/httpx/main.py#L58-L94)**
- L58: `client = x402Client().set_spend_controls({"max_amount_per_payment": "$1"})`
- L62-63: `account = Account.from_key(pk); register_exact_evm_client(client, EthAccountSigner(account))`
- L73: `http_client = x402HTTPClient(client)`
- L80-91:
  ```python
  async with x402HttpxClient(client) as http:
      response = await http.get(url); await response.aread()
      settle = http_client.get_payment_settle_response(lambda name: response.headers.get(name))
  ```
  `except ValueError` handles the missing-header case.

**[clients/advanced/hooks.py](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/examples/python/clients/advanced/hooks.py#L38-L111)**
- L38-57: `async def before_payment_creation_hook(context: PaymentCreationContext) -> AbortResult | None`, reading `context.selected_requirements.network`, `.scheme` and `.get_amount()`
- L109: `client.on_before_payment_creation(...)`

**[clients/advanced/spend_controls.py](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/examples/python/clients/advanced/spend_controls.py#L32-L58)**
- L32-58: `x402Client.from_config(x402ClientConfig(schemes=[SchemeRegistration(network="eip155:*", client=ExactEvmScheme(signer))], spend_controls={..., "allowed_assets": [...]}))`

**[servers/fastapi/main.py](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/examples/python/servers/fastapi/main.py#L47-L97)**
- L47-50: `facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL)); server = x402ResourceServer(facilitator); server.register("eip155:84532", ExactEvmServerScheme())`
- L52-71: `routes = {"GET /weather": RouteConfig(accepts=[PaymentOption(scheme="exact", pay_to=EVM_ADDRESS, price="$0.01", network=EVM_NETWORK)], mime_type="application/json", description="Weather report")}`
- L96: `app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)`
- L97 shows the function form as an alternative: `app.middleware("http")(payment_middleware(routes=routes, server=server))`

**[servers/advanced/hooks.py](https://github.com/x402-foundation/x402/blob/71eb9a55e081e7b81ba3046d0bd17c3eb9c7bf81/examples/python/servers/advanced/hooks.py#L39-L94)**
- L45-47: `async def before_verify(ctx): pprint(vars(ctx))`
- L75-80: `server.on_before_verify(...)`, plus `on_after_verify`, `on_verify_failure`, `on_before_settle`, `on_after_settle` and `on_settle_failure`
- L94: `add_middleware`

None of the examples calls `initialize()` explicitly.

## 7. MCP (PRD 10.5) on mcp 2.2.0

**Import and constructor: CONFIRMED.**
- `from mcp.server.mcpserver import MCPServer` ([server/mcpserver/\_\_init\_\_.py L28](https://github.com/modelcontextprotocol/python-sdk/blob/9972c21aa42054fb1450c5fc614761ed11847ec6/src/mcp/server/mcpserver/__init__.py#L28)). The README's `from mcp.server import MCPServer` works too.
- `mcp = MCPServer("sekisho")`: `name` is the first positional argument ([server.py L157-186](https://github.com/modelcontextprotocol/python-sdk/blob/9972c21aa42054fb1450c5fc614761ed11847ec6/src/mcp/server/mcpserver/server.py#L157-L186)).

**`@mcp.tool()`: CONFIRMED** ([L660-728](https://github.com/modelcontextprotocol/python-sdk/blob/9972c21aa42054fb1450c5fc614761ed11847ec6/src/mcp/server/mcpserver/server.py#L660-L728)).
- The parentheses are required; a bare `@mcp.tool` raises TypeError.
- `async def` tools are fine, and the docstring becomes the tool description.
- Return types ([func_metadata.py L480-553](https://github.com/modelcontextprotocol/python-sdk/blob/9972c21aa42054fb1450c5fc614761ed11847ec6/src/mcp/server/mcpserver/utilities/func_metadata.py#L480-L553)):
  - `-> dict` (bare) gives unstructured text output.
  - `-> dict[str, Any]` gives `structuredContent`.
  - `-> list[dict]` is wrapped as `{"result": [...]}`.

**Run options: CORRECTED.** In 2.x, host, port and path are **`run()` kwargs**. The constructor rejects them; `MCPServer("x", port=9000)` raises TypeError (verified).

```python
if "--http" in sys.argv:
    mcp.run(transport="streamable-http", host="127.0.0.1", port=9000, streamable_http_path="/mcp")  # -> http://127.0.0.1:9000/mcp
else:
    mcp.run()                                   # stdio (default)
```

- The `run` overloads are at [L366-421](https://github.com/modelcontextprotocol/python-sdk/blob/9972c21aa42054fb1450c5fc614761ed11847ec6/src/mcp/server/mcpserver/server.py#L366-L421).
- Streamable-HTTP defaults are host `127.0.0.1`, port 8000 and path `/mcp` ([L1104-1142](https://github.com/modelcontextprotocol/python-sdk/blob/9972c21aa42054fb1450c5fc614761ed11847ec6/src/mcp/server/mcpserver/server.py#L1104-L1142)).
- **DNS-rebinding protection.** With host `127.0.0.1` or `localhost`, it switches on automatically and only localhost `Host` headers are accepted ([lowlevel/server.py L741-747](https://github.com/modelcontextprotocol/python-sdk/blob/9972c21aa42054fb1450c5fc614761ed11847ec6/src/mcp/server/lowlevel/server.py#L741-L747)). For a tunnel or a remote client, use `host="0.0.0.0"` or pass `transport_security=`.

**Operational gotchas:**
- **stdio.** Never `print()` to stdout; it corrupts the JSON-RPC stream. The SDK itself logs to stderr.
- **Claude Desktop config.** Use absolute paths for both the Python interpreter and the script, because Desktop does not start in the repo:
  `{"command": "/abs/path/.venv/bin/python", "args": ["/abs/path/sekisho/mcp/server.py"], "env": {...}}`
- **Folder name risk.** `python mcp/server.py` works. But `python -m mcp.server` or `uvicorn mcp.server:…` resolves to the **SDK**, which has its own `mcp/server/__main__.py`. And adding `mcp/__init__.py` would shadow the SDK whenever the repo root is on `sys.path`. Rename the folder to `mcp_server/`.

**1.x fallback** (only needed if 2.x is abandoned):
- Pin `mcp>=1.28,<2` (the latest 1.x is 1.30.0).
- In 2.x, importing `mcp.server.fastmcp` raises `ModuleNotFoundError` with a migration hint ([server/fastmcp.py L1-16](https://github.com/modelcontextprotocol/python-sdk/blob/9972c21aa42054fb1450c5fc614761ed11847ec6/src/mcp/server/fastmcp.py#L1-L16)). So the fallback is a **pin**, not a try/except on the same install.
- In 1.x, host, port and path go in the **constructor**, and `run()` only takes `transport` and `mount_path` ([v1.30.0 fastmcp/server.py L156-189, L295-316](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/fastmcp/server.py#L156-L189)):

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("sekisho", host="127.0.0.1", port=9000, streamable_http_path="/mcp")
mcp.run(transport="streamable-http")          # or mcp.run() for stdio
```

## 8. Corrections to the PRD

1. **10.1 note, 10.3 HOLD step 1.** `x402HttpxClient` **wraps** the abort. Catch `x402.http.clients.httpx.PaymentError` and read `e.__cause__`, which is the `PaymentAbortedError` (use `.reason`). It is neither an httpx error nor `x402.PaymentError`.
2. **10.1 hooks.** Catch every exception in `payer_hook` and `payee_hook`, not only `SekishoUnavailable`, and return `AbortResult("HOLD|…")`. Only an `AbortResult` instance aborts. Parse the reason with `.split("|", 2)`.
3. **10.3 spend cap.** The cap runs **before** the Sekisho hook. An over-cap payment raises the wrapper with a `NoMatchingRequirementsError` cause, and no case is created.
4. **10.3 after settlement.** Check `r.status_code == 200 and s.success`. A vendor refusal arrives as a 402 response, not an exception.
5. **10.1 P1 403 middleware.** Wrap the decode in try/except; a bad header currently gives a 500. Watch for double screening.
6. **10.2 vendors.** Use `FacilitatorConfig(url=..., timeout=10.0)`. `/supported` is fetched synchronously at startup, and a config mismatch calls `os._exit(1)`. No manual `initialize()` is needed.
7. **10.4 S5.** Set `accepted` to `accepts[0]` from the 402, verbatim, and `value` to `accepts[0]["amount"]`. Otherwise the vendor answers "No matching payment requirements" and screening never runs.
8. **10.5 MCP.** Call `mcp.run(transport="streamable-http", host=..., port=9000, streamable_http_path="/mcp")`; host and port belong in `run()`, not the constructor. Use absolute paths in the Desktop config, and consider renaming `mcp/` to `mcp_server/`.
9. **10.1 day-one check.** `print(vars(ctx))` is no longer needed: the field names are confirmed, and `.amount` is an attribute.

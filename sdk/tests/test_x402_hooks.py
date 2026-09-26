"""x402 hooks (PRD 12): the payer hook aborts BEFORE signing on HOLD, BLOCK and gate failure.

The buyer side is the real x402 2.24.0 client: x402Client + register_exact_evm_client with an
EthAccountSigner whose sign method is spied, driven through x402HttpxClient. respx mocks the
vendor (a proper v2 402) and the gate.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
import respx

pytest.importorskip("x402")

from eth_account import Account  # noqa: E402
from x402 import x402Client  # noqa: E402
from x402.http import x402HTTPClient  # noqa: E402
from x402.http.clients import x402HttpxClient  # noqa: E402
from x402.http.clients.httpx import PaymentError as X402TransportError  # noqa: E402
from x402.http.utils import (  # noqa: E402
    decode_payment_signature_header,
    encode_payment_required_header,
    encode_payment_response_header,
)
from x402.mechanisms.evm import EthAccountSigner  # noqa: E402
from x402.mechanisms.evm.exact.register import register_exact_evm_client  # noqa: E402
from x402.schemas import (  # noqa: E402
    NoMatchingRequirementsError,
    PaymentAbortedError,
    PaymentRequired,
    PaymentRequirements,
    ResourceInfo,
    SettleResponse,
)

from sekisho import (  # noqa: E402
    CURRENT,
    SekishoClient,
    parse_abort_reason,
    payer_hook,
    unwrap_payment_aborted,
)
from sekisho.x402_hooks import chain_id_from_network, payer_address  # noqa: E402

GATE = "http://gate.test"
VENDOR_URL = "http://vendor.test/v1/market-data"
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
PAY_TO = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"
CASE = "cs_01J8Z6Q4M0T3R9ABCDEFGHJKMN"
SETTLE_TX = "0x" + "ab" * 32
UNAVAILABLE = ("HOLD", None, "Screening unavailable, failing closed")


# ---------------------------------------------------------------------------- parse_abort_reason


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (f"BLOCK|{CASE}|Counterparty is on a sanctions list", ("BLOCK", CASE, "Counterparty is on a sanctions list")),
        (f"HOLD|{CASE}|Counterparty has mixer exposure", ("HOLD", CASE, "Counterparty has mixer exposure")),
        ("HOLD|unavailable|Screening unavailable, failing closed", UNAVAILABLE),
        (f"BLOCK|{CASE}|Headline | with a pipe", ("BLOCK", CASE, "Headline | with a pipe")),
        (f"Payment aborted: BLOCK|{CASE}|h", ("BLOCK", CASE, "h")),  # str(PaymentAbortedError)
        (f"Failed to handle payment: Payment aborted: HOLD|{CASE}|h", ("HOLD", CASE, "h")),  # httpx wrapper
        (f" block|{CASE}|h ", ("BLOCK", CASE, "h")),
        ("BLOCK", ("BLOCK", None, "")),
        ("spend cap exceeded", ("HOLD", None, "spend cap exceeded")),  # not ours: fail closed
        ("", ("HOLD", None, "")),
    ],
)
def test_parse_abort_reason(reason, expected):
    assert parse_abort_reason(reason) == expected


# ---------------------------------------------------------------------------- unwrap_payment_aborted


def _raise_wrapped(inner: BaseException, *, explicit: bool = True) -> BaseException:
    try:
        try:
            raise inner
        except BaseException as e:
            if explicit:
                raise X402TransportError(f"Failed to handle payment: {e}") from e
            raise X402TransportError("Failed to handle payment")  # implicit __context__ only
    except X402TransportError as outer:
        return outer


def test_unwrap_returns_the_abort_itself():
    abort = PaymentAbortedError(f"BLOCK|{CASE}|h")
    assert unwrap_payment_aborted(abort) is abort


def test_unwrap_walks_cause_as_raised_by_x402httpxclient():
    abort = PaymentAbortedError(f"BLOCK|{CASE}|h")
    wrapped = _raise_wrapped(abort)
    assert type(wrapped) is X402TransportError and wrapped.__cause__ is abort
    assert unwrap_payment_aborted(wrapped) is abort


def test_unwrap_walks_context_and_nested_wrappers():
    abort = PaymentAbortedError("HOLD|unavailable|x")
    implicit = _raise_wrapped(abort, explicit=False)
    assert implicit.__cause__ is None and unwrap_payment_aborted(implicit) is abort
    try:
        raise RuntimeError("tool failed") from _raise_wrapped(abort)
    except RuntimeError as outer:
        assert unwrap_payment_aborted(outer) is abort
    group = ExceptionGroup("task group", [ValueError("other"), _raise_wrapped(abort)])
    assert unwrap_payment_aborted(group) is abort


def test_unwrap_returns_none_for_other_errors_and_survives_cycles():
    assert unwrap_payment_aborted(None) is None
    assert unwrap_payment_aborted(ValueError("x")) is None
    assert unwrap_payment_aborted(_raise_wrapped(NoMatchingRequirementsError("spend cap"))) is None
    a, b = ValueError("a"), ValueError("b")
    a.__context__, b.__context__ = b, a
    assert unwrap_payment_aborted(a) is None


def test_helpers():
    assert chain_id_from_network("eip155:84532") == 84532
    assert chain_id_from_network("base-sepolia") == 84532
    with pytest.raises(ValueError):
        chain_id_from_network("solana:mainnet")
    inner = {"authorization": {"from": PAY_TO}, "signature": "0x"}
    assert payer_address(inner) == PAY_TO
    assert payer_address({"x402Version": 2, "payload": inner}) == PAY_TO
    assert payer_address(SimpleNamespace(payload={"permit2Authorization": {"from": PAY_TO}})) == PAY_TO
    assert payer_address({"signature": "0x"}) is None


# ---------------------------------------------------------------------------- payer hook, end to end


def payment_required(amount: str = "50000") -> PaymentRequired:
    return PaymentRequired(
        x402_version=2,
        error="Payment required",
        resource=ResourceInfo(url=VENDOR_URL, description="Ronin Signals market data",
                              mime_type="application/json"),
        accepts=[PaymentRequirements(
            scheme="exact", network="eip155:84532", asset=USDC, amount=amount, pay_to=PAY_TO,
            max_timeout_seconds=300, extra={"name": "USDC", "version": "2"})],
    )


def mock_vendor(router: respx.MockRouter, required: PaymentRequired) -> list[httpx.Request]:
    """A vendor that answers 402 without payment and 200 + PAYMENT-RESPONSE with one."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        header = request.headers.get("payment-signature")
        if not header:
            return httpx.Response(402, json={},
                                  headers={"PAYMENT-REQUIRED": encode_payment_required_header(required)})
        payload = decode_payment_signature_header(header)
        settled = SettleResponse(success=True, transaction=SETTLE_TX, network="eip155:84532",
                                 payer=payload.payload["authorization"]["from"],
                                 amount=required.accepts[0].amount)
        return httpx.Response(200, json={"pair": "ETH-JPY", "source": "sample data"},
                              headers={"PAYMENT-RESPONSE": encode_payment_response_header(settled)})

    router.route(method="GET", host="vendor.test", path="/v1/market-data").mock(side_effect=handler)
    return seen


@pytest.fixture
async def buyer():
    account = Account.create()
    signer = EthAccountSigner(account)
    signer.sign_typed_data = MagicMock(wraps=signer.sign_typed_data)  # the spy: every EVM signature goes here
    client = x402Client()
    register_exact_evm_client(client, signer)
    sk = SekishoClient(GATE, timeout_s=1.0)
    client.on_before_payment_creation(payer_hook(sk, "treasury-agent-01"))
    yield SimpleNamespace(account=account, sign=signer.sign_typed_data, client=client)
    await sk.aclose()


def signed(seen: list[httpx.Request]) -> list[httpx.Request]:
    return [r for r in seen if "payment-signature" in r.headers]


async def _buy(client: x402Client) -> httpx.Response:
    async with x402HttpxClient(client) as http:
        return await http.get(VENDOR_URL, params={"pair": "ETH-JPY"})


@pytest.mark.parametrize("verdict", ["BLOCK", "HOLD"])
async def test_payer_hook_aborts_before_signing(buyer, make_decision, verdict):
    with respx.mock(assert_all_mocked=True) as router:
        seen = mock_vendor(router, payment_required())
        gate = router.post(f"{GATE}/v1/screen").mock(
            return_value=httpx.Response(200, json=make_decision(verdict, case_id=CASE, counterparty=PAY_TO)))
        cur = {"url": VENDOR_URL, "purpose": "Buy ETH/JPY market data"}
        CURRENT.set(cur)
        with pytest.raises(X402TransportError) as info:  # wrapped by x402HttpxClient, not bare
            await _buy(buyer.client)

    aborted = unwrap_payment_aborted(info.value)
    assert isinstance(aborted, PaymentAbortedError)
    headline = make_decision(verdict)["headline"]
    assert aborted.reason == f"{verdict}|{CASE}|{headline}"
    assert parse_abort_reason(aborted.reason) == (verdict, CASE, headline)
    # Nothing was signed: one unpaid request, no PAYMENT-SIGNATURE ever sent, signer untouched.
    assert len(seen) == 1 and signed(seen) == []
    buyer.sign.assert_not_called()
    # The hook screened the payee with the 402's terms and the agent's context.
    assert json.loads(gate.calls.last.request.content) == {
        "counterparty": PAY_TO, "direction": "outbound", "amount": "50000", "asset": USDC,
        "payment_chain_id": 84532, "source": "x402", "agent_id": "treasury-agent-01",
        "purpose": "Buy ETH/JPY market data", "resource": VENDOR_URL, "untrusted_context": None,
    }
    assert cur["decision"].verdict == verdict and cur["decision"].case_id == CASE
    assert cur["abort_reason"] == aborted.reason


@pytest.mark.parametrize(
    ("mock", "headline"),
    [
        ({"side_effect": httpx.ConnectError("connection refused")}, UNAVAILABLE[2]),
        ({"side_effect": httpx.ReadTimeout("timed out")}, UNAVAILABLE[2]),
        ({"return_value": httpx.Response(503)}, UNAVAILABLE[2]),
        ({"return_value": httpx.Response(200, text="not json")}, UNAVAILABLE[2]),
        ({"return_value": httpx.Response(422, json={"error": "invalid_request", "message": "x"})},
         "Screening failed (SekishoRequestError), failing closed"),
    ],
    ids=["unreachable", "timeout", "503", "garbage", "422"],
)
async def test_payer_hook_fails_closed_when_the_gate_fails(buyer, mock, headline):
    with respx.mock(assert_all_mocked=True) as router:
        seen = mock_vendor(router, payment_required())
        router.post(f"{GATE}/v1/screen").mock(**mock)
        cur: dict = {"url": VENDOR_URL, "purpose": "p"}
        CURRENT.set(cur)
        with pytest.raises(X402TransportError) as info:
            await _buy(buyer.client)

    aborted = unwrap_payment_aborted(info.value)
    assert aborted is not None
    assert parse_abort_reason(aborted.reason) == ("HOLD", None, headline)
    assert signed(seen) == []
    buyer.sign.assert_not_called()
    assert "decision" not in cur and cur["error"]


async def test_payer_hook_allow_signs_once_and_settles(buyer, make_decision):
    with respx.mock(assert_all_mocked=True) as router:
        seen = mock_vendor(router, payment_required())
        router.post(f"{GATE}/v1/screen").mock(
            return_value=httpx.Response(200, json=make_decision("ALLOW", case_id=CASE, counterparty=PAY_TO)))
        cur = {"url": VENDOR_URL, "purpose": "Buy ETH/JPY market data"}
        CURRENT.set(cur)
        response = await _buy(buyer.client)

    assert response.status_code == 200
    buyer.sign.assert_called_once()
    paid = signed(seen)
    assert len(seen) == 2 and len(paid) == 1
    payload = decode_payment_signature_header(paid[0].headers["payment-signature"])
    auth = payload.payload["authorization"]
    assert (auth["from"], auth["to"], auth["value"]) == (buyer.account.address, PAY_TO, "50000")
    assert payload.payload["signature"].startswith("0x")
    # How the treasury agent reads the settlement (PRD 10.3): sync, tx hash in .transaction.
    settle = x402HTTPClient(buyer.client).get_payment_settle_response(lambda n: response.headers.get(n))
    assert settle.success and settle.transaction == SETTLE_TX and settle.network == "eip155:84532"
    assert cur["decision"].verdict == "ALLOW" and "abort_reason" not in cur


async def test_payer_hook_screens_even_without_current(buyer, make_decision):
    with respx.mock(assert_all_mocked=True) as router:
        seen = mock_vendor(router, payment_required())
        gate = router.post(f"{GATE}/v1/screen").mock(
            return_value=httpx.Response(200, json=make_decision("BLOCK", case_id=CASE)))
        task = asyncio.create_task(_buy(buyer.client), context=contextvars.Context())  # CURRENT unset
        with pytest.raises(X402TransportError):
            await task
    body = json.loads(gate.calls.last.request.content)
    assert (body["purpose"], body["resource"]) == ("", "")
    assert signed(seen) == []
    buyer.sign.assert_not_called()


async def test_spend_cap_runs_before_the_hook(buyer):
    """x402's own cap ($1 default) rejects first: no screen, no case, and no PaymentAbortedError."""
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        seen = mock_vendor(router, payment_required(amount="2000000"))  # $2
        gate = router.post(f"{GATE}/v1/screen")
        with pytest.raises(X402TransportError) as info:
            await _buy(buyer.client)
    assert isinstance(info.value.__cause__, NoMatchingRequirementsError)
    assert unwrap_payment_aborted(info.value) is None
    assert not gate.called and signed(seen) == []
    buyer.sign.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"counterparty": "0x" + "11" * 20},
    {"amount": "50001"},
    {"asset": "0x" + "22" * 20},
    {"payment_chain_id": 8453},
    {"payment_chain_id": None},
    {"direction": "inbound"},
])
async def test_mismatched_allow_never_signs(buyer, make_decision, changes):
    with respx.mock(assert_all_mocked=True) as router:
        seen = mock_vendor(router, payment_required())
        decision = make_decision("ALLOW", counterparty=PAY_TO)
        decision.update(changes)
        router.post(f"{GATE}/v1/screen").respond(200, json=decision)
        CURRENT.set({})
        with pytest.raises(X402TransportError):
            await _buy(buyer.client)
    buyer.sign.assert_not_called()
    assert not signed(seen)


@pytest.mark.parametrize(("asset", "chain"), [
    (USDC, 8453), ("0x" + "11" * 20, 84532),
])
async def test_unsupported_payment_never_reaches_screening(asset, chain):
    sk = SimpleNamespace(screen=MagicMock())
    ctx = SimpleNamespace(selected_requirements=SimpleNamespace(
        asset=asset, network=f"eip155:{chain}", amount="50000", pay_to=PAY_TO))
    result = await payer_hook(sk, "agent")(ctx)
    assert result.reason.startswith("HOLD|")
    sk.screen.assert_not_called()

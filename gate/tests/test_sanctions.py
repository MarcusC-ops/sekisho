"""Chainalysis oracle over JSON-RPC: bool decoding, one chain failing, batches (respx)."""

import json

import httpx
import pytest

from sekisho_gate.config import Settings
from sekisho_gate.screening.sanctions import ORACLES, SELECTOR, SanctionsOracle, calldata, decode_bool

pytestmark = pytest.mark.respx(assert_all_called=False)

ETH_RPC = "https://eth-rpc.test"
BASE_RPC = "https://base-rpc.test"
RONIN = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"
CLEAN = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
TRUE = "0x" + "0" * 63 + "1"
FALSE = "0x" + "0" * 64


def make_settings(**overrides) -> Settings:
    values = dict(_env_file=None, eth_mainnet_rpc_url=ETH_RPC, base_mainnet_rpc_url=BASE_RPC)
    values.update(overrides)
    return Settings(**values)


def rpc_result(result, req_id=1):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": req_id, "result": result})


@pytest.fixture
async def oracle():
    o = SanctionsOracle(make_settings(), http=httpx.AsyncClient())
    yield o
    await o._http.aclose()


def test_calldata_and_decoding():
    assert SELECTOR == "0xdf592f7d"
    assert calldata(RONIN) == "0xdf592f7d000000000000000000000000098b716b8aaf21512996dc57eb0615e2383e2f96"
    assert decode_bool(TRUE) is True
    assert decode_bool(FALSE) is False
    assert decode_bool("0x") is None  # no contract at the address
    assert decode_bool(None) is None
    assert decode_bool("0x" + "0" * 63 + "2") is None


async def test_true_and_false_on_two_chains(oracle, respx_mock):
    eth = respx_mock.post(ETH_RPC).mock(return_value=rpc_result(TRUE))
    respx_mock.post(BASE_RPC).mock(return_value=rpc_result(FALSE))
    out = await oracle.check(RONIN)
    assert out.name == "sanctions.oracle" and out.live is None
    assert out.status == "ok"
    assert out.data == {"1": True, "8453": False}
    assert out.summary == "sanctioned on 1"
    assert out.raw["1"] == {"jsonrpc": "2.0", "id": 1, "result": TRUE}
    sent = json.loads(eth.calls.last.request.content)
    assert sent["method"] == "eth_call"
    assert sent["params"] == [{"to": ORACLES[1], "data": calldata(RONIN)}, "latest"]


async def test_clean_address(oracle, respx_mock):
    respx_mock.post(ETH_RPC).mock(return_value=rpc_result(FALSE))
    respx_mock.post(BASE_RPC).mock(return_value=rpc_result(FALSE))
    out = await oracle.check(CLEAN)
    assert out.status == "ok" and out.data == {"1": False, "8453": False}
    assert out.summary == "not sanctioned (1, 8453)"


async def test_one_chain_failing_gives_none_and_error(oracle, respx_mock):
    respx_mock.post(ETH_RPC).mock(return_value=rpc_result(TRUE))
    base = respx_mock.post(BASE_RPC).mock(return_value=httpx.Response(503, text="busy"))
    out = await oracle.check(RONIN)
    assert out.status == "error"
    assert out.data == {"1": True, "8453": None}  # the policy still BLOCKs on the true chain
    assert "Base (8453): HTTP 503" in out.error
    assert base.call_count == 2  # one retry within the budget
    assert out.summary.startswith("sanctioned on 1")


async def test_rpc_error_object_is_a_failure(oracle, respx_mock):
    respx_mock.post(ETH_RPC).mock(
        return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "execution reverted"}})
    )
    respx_mock.post(BASE_RPC).mock(side_effect=httpx.ConnectError("down"))
    out = await oracle.check(RONIN)
    assert out.status == "error" and out.data == {"1": None, "8453": None}
    assert "RPC error: execution reverted" in out.error and "ConnectError" in out.error


async def test_check_many_uses_one_batch_per_chain(oracle, respx_mock):
    sanctioned = {RONIN.lower()}

    def answer(request):
        batch = json.loads(request.content)
        assert isinstance(batch, list)
        out = []
        for item in batch:
            addr = "0x" + item["params"][0]["data"][-40:]
            out.append({"jsonrpc": "2.0", "id": item["id"], "result": TRUE if addr in sanctioned else FALSE})
        return httpx.Response(200, json=list(reversed(out)))  # order must not matter

    eth = respx_mock.post(ETH_RPC).mock(side_effect=answer)
    base = respx_mock.post(BASE_RPC).mock(side_effect=answer)
    res = await oracle.check_many([RONIN, CLEAN.lower(), CLEAN, "not-an-address"])
    assert res == {RONIN: {"1": True, "8453": True}, CLEAN: {"1": False, "8453": False}}
    assert eth.call_count == 1 and base.call_count == 1


async def test_check_many_falls_back_to_single_calls(oracle, respx_mock):
    def answer(request):
        body = json.loads(request.content)
        if isinstance(body, list):  # this provider refuses batches
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": None, "error": {"message": "batch not supported"}})
        return rpc_result(TRUE if RONIN.lower()[2:] in body["params"][0]["data"] else FALSE, body["id"])

    respx_mock.post(ETH_RPC).mock(side_effect=answer)
    respx_mock.post(BASE_RPC).mock(return_value=httpx.Response(500))
    res = await oracle.check_many([RONIN, CLEAN], budget_s=1.0)
    assert res[RONIN]["1"] is True and res[CLEAN]["1"] is False
    assert res[RONIN]["8453"] is None


async def test_self_test(oracle, respx_mock):
    respx_mock.post(ETH_RPC).mock(return_value=rpc_result(TRUE))
    respx_mock.post(BASE_RPC).mock(return_value=rpc_result(TRUE))
    assert await oracle.self_test() == (True, "0x098B…2f96 sanctioned on 1 and 8453")


async def test_self_test_fails_when_oracle_says_false(oracle, respx_mock):
    respx_mock.post(ETH_RPC).mock(return_value=rpc_result(FALSE))
    respx_mock.post(BASE_RPC).mock(return_value=rpc_result(FALSE))
    ok, detail = await oracle.self_test()
    assert ok is False and "may have changed" in detail


async def test_invalid_address(oracle):
    out = await oracle.check("0x123")
    assert out.status == "error" and out.data == {"1": None, "8453": None}

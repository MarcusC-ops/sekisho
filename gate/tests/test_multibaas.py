"""MultiBaas client: arg encoding, compose -> sign -> submit, reverts, hash fallback,
events, webhook HMAC, receipts (respx only; no deployment is contacted)."""

import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from eth_account import Account
from eth_utils import keccak
from pydantic import SecretStr

from sekisho_gate.chain import multibaas as mbmod
from sekisho_gate.chain.multibaas import (
    KNOWN_ERRORS,
    MultiBaasClient,
    MultiBaasError,
    ReceiptTimeout,
    build_unsigned_tx,
    decode_revert,
    encode_args,
    parse_event,
    revert_reason,
    verify_webhook_signature,
)
from sekisho_gate.config import Settings

pytestmark = pytest.mark.respx(assert_all_called=False)

FIX = Path(__file__).parent / "fixtures" / "multibaas"
MB = "https://sekisho.multibaas.test"
API = MB + "/api/v0"
RPC = "https://sepolia-rpc.test"
SIGNER = Account.from_key("0x" + "11" * 32)  # throwaway test key
REGISTRY = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
SUBJECT = "0x098b716b8aaf21512996dc57eb0615e2383e2f96"
REPORT_HASH = "0x" + "ab" * 32
POLICY_ID = "0xd55f2a7678cc2571a18073afd351f2fc13ffe4aa9c570632b94a8190f9c14719"
CASE_ID = bytes.fromhex("cd" * 32)
COMPOSE_PATH = f"/chains/ethereum/addresses/compliance_registry/contracts/compliance_registry/methods/recordScreening"


def make_settings(**overrides) -> Settings:
    values = dict(_env_file=None, mb_url=MB, mb_admin_api_key=SecretStr("mb-admin-key"), chain_id=84532,
                  contracts_rpc_url=RPC)
    values.update(overrides)
    return Settings(**values)


def composed(**tx_overrides):
    tx = {"from": SIGNER.address, "to": REGISTRY, "nonce": 7, "gas": 120000, "gasFeeCap": "1500000000",
          "gasTipCap": "1000000", "value": "0", "data": "0xabcdef01", "type": 2}
    tx.update(tx_overrides)
    return {"status": 200, "message": "success",
            "result": {"kind": "TransactionToSignResponse", "submitted": False, "tx": tx}}


def expected_raw(**tx_overrides) -> bytes:
    tx = composed(**tx_overrides)["result"]["tx"]
    signed = SIGNER.sign_transaction({
        "to": REGISTRY, "nonce": tx["nonce"], "gas": tx["gas"], "maxFeePerGas": int(tx["gasFeeCap"]),
        "maxPriorityFeePerGas": int(tx["gasTipCap"]), "data": tx["data"], "value": 0, "chainId": 84532, "type": 2,
    })  # deterministic (RFC 6979) signature, so the bytes must match exactly
    return bytes(signed.raw_transaction)


def args():
    return [SUBJECT, "BLOCK", 100, 31536000, REPORT_HASH.upper().replace("0X", "0x"), POLICY_ID, CASE_ID]


def mock_nonce(respx_mock, nonce=7):
    return respx_mock.post(RPC).mock(return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(nonce)}))


@pytest.fixture
async def client(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(mbmod.asyncio, "sleep", no_sleep)  # skip retry backoff in tests
    c = MultiBaasClient(make_settings(), http=httpx.AsyncClient())
    yield c
    await c._http.aclose()


# ---------- encoding ----------


def test_encode_args_per_prd():
    enc = encode_args(mbmod.METHOD_TYPES["recordScreening"], args())
    assert enc == [
        "0x098B716B8Aaf21512996dC57EB0615e2383E2f96",  # checksummed
        3,  # enum Verdict as a number (BLOCK)
        "100",  # uint as a decimal string
        "31536000",
        "0x" + "ab" * 32,  # bytes32: 0x + 64 lowercase hex
        POLICY_ID,
        "0x" + "cd" * 32,
    ]
    assert encode_args(mbmod.METHOD_TYPES["recordScreening"], enc) == enc  # idempotent
    assert encode_args(["uint256"], ["0x10"]) == ["16"]
    with pytest.raises(ValueError):
        encode_args(["uint8"], [256])
    with pytest.raises(ValueError):
        encode_args(["bytes32"], ["0x1234"])
    with pytest.raises(ValueError):
        encode_args(["address"], ["0xnope"])
    with pytest.raises(ValueError):
        encode_args(["uint64"], [True])


async def test_compose_encodes_args_and_does_not_submit(client, respx_mock):
    compose = respx_mock.post(API + COMPOSE_PATH).mock(return_value=httpx.Response(200, json=composed()))
    submit = respx_mock.post(API + "/chains/ethereum/transactions/submit")
    tx = await client.compose("compliance_registry", "compliance_registry", "recordScreening", args(),
                              SIGNER.address, nonce=7)
    assert tx["nonce"] == 7 and tx["gasFeeCap"] == "1500000000"
    body = json.loads(compose.calls.last.request.content)
    assert body == {
        "args": ["0x098B716B8Aaf21512996dC57EB0615e2383E2f96", 3, "100", "31536000", "0x" + "ab" * 32,
                 POLICY_ID, "0x" + "cd" * 32],
        "from": SIGNER.address,
        "nonce": 7,
    }
    assert compose.calls.last.request.headers["Authorization"] == "Bearer mb-admin-key"
    assert submit.call_count == 0


# ---------- compose -> sign -> submit ----------


async def test_call_write_composes_signs_locally_and_submits(client, respx_mock):
    nonce = mock_nonce(respx_mock)
    compose = respx_mock.post(API + COMPOSE_PATH).mock(return_value=httpx.Response(200, json=composed()))
    raw = expected_raw()
    tx_hash = "0x" + keccak(raw).hex()
    submit = respx_mock.post(API + "/chains/ethereum/transactions/submit").mock(
        return_value=httpx.Response(200, json={"status": 200, "message": "success", "result": {"tx": {"hash": tx_hash}}})
    )
    out = await client.call_write("compliance_registry", "compliance_registry", "recordScreening", args(), SIGNER)
    assert out == tx_hash
    rpc_body = json.loads(nonce.calls.last.request.content)
    assert rpc_body["method"] == "eth_getTransactionCount" and rpc_body["params"] == [SIGNER.address, "pending"]
    assert json.loads(compose.calls.last.request.content)["nonce"] == 7
    signed_tx = json.loads(submit.calls.last.request.content)["signedTx"]
    assert not signed_tx.startswith("0x")  # the docs' form
    assert bytes.fromhex(signed_tx) == raw  # chainId 84532, EIP-1559 fees from the composed tx
    assert Account.recover_transaction(raw) == SIGNER.address


def test_build_unsigned_tx_uses_chain_id_and_1559_fields():
    tx = build_unsigned_tx(composed()["result"]["tx"], 84532)
    assert tx == {"nonce": 7, "gas": 120000, "data": "0xabcdef01", "value": 0, "chainId": 84532,
                  "to": REGISTRY, "maxFeePerGas": 1500000000, "maxPriorityFeePerGas": 1000000, "type": 2}
    legacy = build_unsigned_tx({"nonce": "0x2", "gas": 21000, "gasPrice": "5", "value": None,
                                "data": "0x", "to": REGISTRY, "type": 0}, 1)
    assert legacy["gasPrice"] == 5 and "maxFeePerGas" not in legacy and legacy["nonce"] == 2


async def test_tx_hash_falls_back_to_keccak_of_raw_tx(client, respx_mock):
    mock_nonce(respx_mock)
    respx_mock.post(API + COMPOSE_PATH).mock(return_value=httpx.Response(200, json=composed()))
    respx_mock.post(API + "/chains/ethereum/transactions/submit").mock(
        return_value=httpx.Response(200, json={"status": 200, "message": "success", "result": {"tx": {}}})
    )
    out = await client.call_write("compliance_registry", "compliance_registry", "recordScreening", args(), SIGNER)
    assert out == "0x" + keccak(expected_raw()).hex()


async def test_submit_retries_once_with_the_other_prefix(client, respx_mock):
    mock_nonce(respx_mock)
    respx_mock.post(API + COMPOSE_PATH).mock(return_value=httpx.Response(200, json=composed()))
    tx_hash = "0x" + keccak(expected_raw()).hex()
    submit = respx_mock.post(API + "/chains/ethereum/transactions/submit").mock(side_effect=[
        httpx.Response(400, json={"status": 400, "message": "invalid signed transaction: missing 0x prefix"}),
        httpx.Response(200, json={"status": 200, "message": "success", "result": {"tx": {"hash": tx_hash}}}),
    ])
    out = await client.call_write("compliance_registry", "compliance_registry", "recordScreening", args(), SIGNER)
    assert out == tx_hash
    forms = [json.loads(c.request.content)["signedTx"][:2] for c in submit.calls]
    assert forms[0] != "0x" and forms[1] == "0x"
    assert client.submit_with_0x is True  # remembered for the next submit


async def test_already_known_counts_as_submitted(client, respx_mock):
    mock_nonce(respx_mock)
    respx_mock.post(API + COMPOSE_PATH).mock(return_value=httpx.Response(200, json=composed()))
    respx_mock.post(API + "/chains/ethereum/transactions/submit").mock(
        return_value=httpx.Response(400, json={"status": 400, "message": "already known"})
    )
    out = await client.call_write("compliance_registry", "compliance_registry", "recordScreening", args(), SIGNER)
    assert out == "0x" + keccak(expected_raw()).hex()


# ---------- reverts and retries ----------


def test_known_selectors_match_the_prd():
    prd = {"0x92a032ca": "NotCleared", "0x845eadf1": "NotHeld", "0xecbe11eb": "PayeeBlocked",
           "0x1f2a2005": "ZeroAmount", "0x1435e357": "NotPayer", "0x085de625": "TooEarly",
           "0xe2517d3f": "AccessControlUnauthorizedAccount", "0xfbcebe72": "InvalidVerdict",
           "0x15561365": "InvalidScore", "0x3dc68a66": "InvalidTtl", "0x3ee5aeb5": "ReentrancyGuardReentrantCall",
           "0x5274afe7": "SafeERC20FailedOperation", "0xfb8f41b2": "ERC20InsufficientAllowance"}
    for sel, name in prd.items():
        assert KNOWN_ERRORS[sel] == name


def test_decode_revert_and_reason():
    assert decode_revert('{"status":400,"message":"execution reverted: 0x92a032ca"}') == ("NotCleared", "0x92a032ca")
    data = "0xe2517d3f" + "00" * 12 + "11" * 20 + "ab" * 32  # custom error with arguments
    assert decode_revert(f'{{"message": "reverted", "data": "{data}"}}') == ("AccessControlUnauthorizedAccount", "0xe2517d3f")
    assert decode_revert("execution reverted: custom error NotHeld()") == ("NotHeld", "0x845eadf1")
    assert decode_revert('{"message":"insufficient funds for gas"}') is None
    assert decode_revert("tx data 0xa0712d68000000") is None  # a function selector, not an error
    reason = "ERC20: transfer amount exceeds balance".encode()
    encoded = ("08c379a0" + (32).to_bytes(32, "big").hex() + len(reason).to_bytes(32, "big").hex()
               + reason.ljust(64, b"\0").hex())
    assert revert_reason(f'{{"message": "execution reverted", "data": "0x{encoded}"}}') == reason.decode()
    assert revert_reason('{"message":"execution reverted: ERC20: transfer amount exceeds allowance"}') == \
        "ERC20: transfer amount exceeds allowance"
    assert revert_reason('{"message":"execution reverted: NotCleared()"}') is None


async def test_compose_revert_is_decoded_and_not_retried(client, respx_mock):
    route = respx_mock.post(API + "/chains/ethereum/addresses/compliance_escrow/contracts/compliance_escrow/methods/release").mock(
        return_value=httpx.Response(500, json={"status": 500, "message": "execution reverted: 0x92a032ca"})
    )
    with pytest.raises(MultiBaasError) as info:
        await client.call_write("compliance_escrow", "compliance_escrow", "release", [3], SIGNER, nonce=1)
    err = info.value
    assert (err.revert, err.selector, err.status) == ("NotCleared", "0x92a032ca", 500)
    assert "0x92a032ca" in err.body and "reverted with NotCleared" in str(err)
    assert route.call_count == 1  # a revert is never retried, even on 5xx
    assert json.loads(route.calls.last.request.content)["args"] == ["3"]


async def test_error_string_revert_surfaces_the_message(client, respx_mock):
    respx_mock.post(API + "/chains/ethereum/addresses/usdc/contracts/erc20/methods/transfer").mock(
        return_value=httpx.Response(400, json={"status": 400, "message": "execution reverted: ERC20: transfer amount exceeds balance"})
    )
    with pytest.raises(MultiBaasError) as info:
        await client.call_write("usdc", "erc20", "transfer", [SUBJECT, 10**6], SIGNER, nonce=0)
    assert info.value.revert is None and info.value.reason == "ERC20: transfer amount exceeds balance"
    assert "transfer amount exceeds balance" in str(info.value)


async def test_5xx_and_429_are_retried_then_succeed(client, respx_mock):
    route = respx_mock.post(API + COMPOSE_PATH).mock(side_effect=[
        httpx.Response(503, json={"status": 503, "message": "unavailable"}),
        httpx.Response(429, json={"status": 429, "message": "slow down"}),
        httpx.Response(200, json=composed()),
    ])
    await client.compose("compliance_registry", "compliance_registry", "recordScreening", args(), SIGNER.address)
    assert route.call_count == 3


async def test_retries_stop_after_two(client, respx_mock):
    route = respx_mock.post(API + COMPOSE_PATH).mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(MultiBaasError) as info:
        await client.compose("compliance_registry", "compliance_registry", "recordScreening", args(), SIGNER.address)
    assert info.value.status == 502 and route.call_count == 3


async def test_4xx_is_not_retried(client, respx_mock):
    route = respx_mock.post(API + COMPOSE_PATH).mock(
        return_value=httpx.Response(404, json={"status": 404, "message": "Address Not Found"})
    )
    with pytest.raises(MultiBaasError) as info:
        await client.compose("compliance_registry", "compliance_registry", "recordScreening", args(), SIGNER.address)
    assert info.value.status == 404 and "Address Not Found" in str(info.value) and route.call_count == 1


async def test_not_configured_raises(monkeypatch):
    c = MultiBaasClient(make_settings(mb_url="https://<deployment-id>.multibaas.com"), http=httpx.AsyncClient())
    try:
        assert c.configured is False
        with pytest.raises(MultiBaasError):
            await c.call_read("compliance_registry", "compliance_registry", "isCleared", [SUBJECT])
        assert await c.health() == (False, "MB_URL or MB_ADMIN_API_KEY not set")
    finally:
        await c._http.aclose()


# ---------- reads, receipts, events, queries, health ----------


async def test_call_read_returns_output(client, respx_mock):
    route = respx_mock.post(API + "/chains/ethereum/addresses/compliance_registry/contracts/compliance_registry/methods/isCleared").mock(
        return_value=httpx.Response(200, json={"status": 200, "message": "success",
                                                "result": {"kind": "MethodCallResponse", "output": True}})
    )
    assert await client.call_read("compliance_registry", "compliance_registry", "isCleared", [SUBJECT]) is True
    assert json.loads(route.calls.last.request.content) == {
        "args": ["0x098B716B8Aaf21512996dC57EB0615e2383E2f96"], "formatInts": "auto"}


async def test_wait_for_receipt_polls_until_mined(client, respx_mock):
    route = respx_mock.post(RPC).mock(side_effect=[
        httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None}),
        httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
            "status": "0x1", "blockNumber": "0x1b4", "gasUsed": "0x5208", "transactionHash": "0xabc", "logs": []}}),
    ])
    receipt = await client.wait_for_receipt("0xabc", timeout_s=5, poll_s=0.01)
    assert receipt["status"] == 1 and receipt["blockNumber"] == 436 and receipt["gasUsed"] == 21000
    assert route.call_count == 2
    assert json.loads(route.calls.last.request.content)["method"] == "eth_getTransactionReceipt"


async def test_wait_for_receipt_times_out(client, respx_mock):
    respx_mock.post(RPC).mock(return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None}))
    with pytest.raises(ReceiptTimeout):
        await client.wait_for_receipt("0xabc", timeout_s=0.05, poll_s=0.01)


async def test_list_events_by_tx_hash_and_alias(client, respx_mock):
    sample = json.loads((FIX / "webhook_event_emitted.json").read_text())
    events = respx_mock.get(API + "/events").mock(
        return_value=httpx.Response(200, json={"status": 200, "message": "success", "result": [sample[0]["data"]]})
    )
    respx_mock.get(API + "/chains/ethereum/addresses/compliance_escrow").mock(
        return_value=httpx.Response(200, json={"status": 200, "message": "success",
                                                "result": {"alias": "compliance_escrow", "address": REGISTRY.lower(), "chain": "84532", "contracts": []}})
    )
    out = await client.list_events(tx_hash="0xe613")
    assert out[0]["name"] == "Mint"
    assert dict(events.calls.last.request.url.params) == {"limit": "20", "tx_hash": "0xe613"}
    await client.list_events(contract_alias="compliance_escrow", limit=5)
    assert dict(events.calls.last.request.url.params) == {"limit": "5", "contract_address": REGISTRY}


async def test_query_results_rows(client, respx_mock):
    rows = [{"payee": "0x1111111111111111111111111111111111111111", "total": "5000000"}]
    route = respx_mock.get(API + "/queries/exposure_by_payee/results").mock(
        return_value=httpx.Response(200, json={"status": 200, "message": "success", "result": {"rows": rows}})
    )
    assert await client.query_results("exposure_by_payee") == rows
    assert dict(route.calls.last.request.url.params) == {"limit": "50", "offset": "0"}


async def test_health(client, respx_mock):
    route = respx_mock.get(API + "/chains/ethereum/status").mock(
        return_value=httpx.Response(200, json={"status": 200, "message": "success",
                                                "result": {"chainID": 84532, "blockNumber": 123, "networkID": 84532, "version": "x"}})
    )
    assert await client.health() == (True, "reachable, chain 84532, block 123")
    route.mock(return_value=httpx.Response(200, json={"status": 200, "message": "success",
                                                      "result": {"chainID": 11155111, "blockNumber": 1}}))
    ok, detail = await client.health()
    assert ok is False and "11155111" in detail
    route.mock(return_value=httpx.Response(401, json={"status": 401, "message": "Unauthorized"}))
    ok, detail = await client.health()
    assert ok is False and "401" in detail


# ---------- webhooks ----------


def test_parse_event_on_docs_webhook_sample():
    sample = json.loads((FIX / "webhook_event_emitted.json").read_text())
    mint = parse_event(sample[0]["data"])
    assert mint == {
        "name": "Mint",
        "contract_alias": "autotoken",  # addressLabel in the docs sample
        "contract_address": "0x9deE62D32898B37F2BDf7e7cB1FA16a45D31D67a",
        "tx_hash": "0xe6136095471608942dda7f20b81b8a92c3bbb733ff4e6cb2960e6b457e1e14b2",
        "block_number": 10,
        "log_index": 0,
        "inputs": {"minter": "0xF9450D254A66ab06b30Cfa9c6e7AE1B7598c7172",
                   "receiver": "0xF9450D254A66ab06b30Cfa9c6e7AE1B7598c7172", "value": "123.456"},
    }
    transfer = parse_event(sample[1])  # a whole webhook item is unwrapped
    assert transfer["name"] == "Transfer" and transfer["log_index"] == 1
    # The OpenAPI spec names the alias field addressAlias; rawFields fill the gaps.
    spec_item = json.loads(json.dumps(sample[0]["data"]))
    spec_item["event"]["contract"] = {"address": REGISTRY, "addressAlias": "compliance_registry",
                                      "name": "ComplianceRegistry", "label": "compliance_registry"}
    spec_item["event"].pop("indexInLog")
    spec_item["transaction"].pop("blockNumber")
    parsed = parse_event(spec_item)
    assert parsed["contract_alias"] == "compliance_registry"
    assert parsed["log_index"] == 0 and parsed["block_number"] == 10  # from rawFields (hex)


def test_webhook_hmac_accept_and_reject():
    body = (FIX / "webhook_event_emitted.json").read_bytes()
    secret, ts = "whsec_test", "1699582290"
    sig = hmac.new(secret.encode(), body + ts.encode(), hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, ts, sig, secret) is True
    assert verify_webhook_signature(body, ts, sig.upper(), secret) is True
    assert verify_webhook_signature(body + b" ", ts, sig, secret) is False  # body changed
    assert verify_webhook_signature(body, "1699582291", sig, secret) is False  # timestamp changed
    assert verify_webhook_signature(body, ts, sig, "other") is False
    assert verify_webhook_signature(body, ts, sig, "") is False  # no secret: never verifies
    assert verify_webhook_signature(body, ts, "", secret) is False
    assert verify_webhook_signature(body, ts, sig, secret, max_age_s=300, now=1699582290 + 10) is True
    assert verify_webhook_signature(body, ts, sig, secret, max_age_s=300, now=1699582290 + 301) is False


@pytest.mark.parametrize("chain_id", [1, 8453, 11155111])
async def test_call_write_refuses_other_chains_before_signing_or_http(chain_id, respx_mock):
    from unittest.mock import MagicMock
    signer = MagicMock(wraps=SIGNER, address=SIGNER.address)
    async with httpx.AsyncClient() as http:
        client = MultiBaasClient(make_settings(chain_id=chain_id), http=http)
        with pytest.raises(MultiBaasError, match="Base Sepolia"):
            await client.call_write("usdc", "erc20", "transfer", [SUBJECT, "50000"], signer)
    signer.sign_transaction.assert_not_called()
    assert not respx_mock.calls


async def test_empty_tx_filter_uses_bounded_numeric_lookup_and_exact_hash(client, respx_mock):
    from copy import deepcopy
    sample = json.loads((FIX / "webhook_event_emitted.json").read_text())[0]["data"]
    tx = sample["transaction"]["txHash"]
    unrelated = deepcopy(sample)
    unrelated["transaction"]["txHash"] = "0x" + "ff" * 32
    events = respx_mock.get(API + "/events").mock(side_effect=[
        httpx.Response(200, json={"status": 200, "result": []}),
        httpx.Response(200, json={"status": 200, "result": [sample, unrelated]})])
    rpc = respx_mock.post(RPC).mock(return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
        "result": {"transactionHash": tx, "blockNumber": "0x2d22a99", "transactionIndex": "0xe"}}))
    out = await client.list_events(tx_hash=tx, limit=3)
    assert len(out) == 1 and out[0]["tx_hash"] == tx.lower()
    assert dict(events.calls[1].request.url.params) == {"limit": "3", "block_number": "47327897", "tx_index_in_block": "14"}
    assert json.loads(rpc.calls[0].request.content)["method"] == "eth_getTransactionReceipt"


@pytest.mark.parametrize("receipt", [None, {}, {"transactionHash": "wrong"}])
async def test_empty_tx_filter_never_broadens_without_matching_receipt(receipt, client, respx_mock):
    events = respx_mock.get(API + "/events").mock(return_value=httpx.Response(200, json={"status": 200, "result": []}))
    respx_mock.post(RPC).mock(return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": receipt}))
    assert await client.list_events(tx_hash="0x" + "12" * 32) == []
    assert events.call_count == 1


async def test_query_results_pages_without_losing_rows(client, respx_mock):
    rows = [{"payee": f"payee-{i}", "total": str(i)} for i in range(73)]
    def answer(request):
        start, count = int(request.url.params["offset"]), int(request.url.params["limit"])
        assert count <= 50
        return httpx.Response(200, json={"status": 200, "result": {"rows": rows[start:start + count]}})
    route = respx_mock.get(API + "/queries/exposure_by_payee/results").mock(side_effect=answer)
    assert await client.query_results("exposure_by_payee") == rows
    assert [dict(c.request.url.params) for c in route.calls] == [
        {"limit": "50", "offset": "0"}, {"limit": "50", "offset": "50"}]


@pytest.mark.parametrize("available", [100, 101])
async def test_query_results_ceiling_requires_overflow_probe(available, client, respx_mock):
    rows = [{"payee": str(i), "total": "1"} for i in range(available)]
    def answer(request):
        start, count = int(request.url.params["offset"]), int(request.url.params["limit"])
        return httpx.Response(200, json={"status": 200, "result": {"rows": rows[start:start + count]}})
    route = respx_mock.get(API + "/queries/exposure_by_payee/results").mock(side_effect=answer)
    if available == 100:
        assert await client.query_results("exposure_by_payee") == rows
    else:
        with pytest.raises(MultiBaasError, match="refusing truncated totals"):
            await client.query_results("exposure_by_payee")
    assert dict(route.calls.last.request.url.params) == {"limit": "1", "offset": "100"}


async def test_query_results_rejects_malformed_rows(client, respx_mock):
    respx_mock.get(API + "/queries/exposure_by_payee/results").mock(
        return_value=httpx.Response(200, json={"status": 200, "result": {"rows": [{"total": "1"}, None]}}))
    with pytest.raises(MultiBaasError, match="invalid rows"):
        await client.query_results("exposure_by_payee")

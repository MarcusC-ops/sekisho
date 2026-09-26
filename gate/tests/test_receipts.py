"""Only real matching successful logs can acknowledge agent payments and holds."""
import httpx
import pytest

from sekisho_gate.receipts import (
    CANONICAL_USDC, HELD_TOPIC, TRANSFER_TOPIC, ReceiptValidationError,
    verify_hold_receipt, verify_payment_receipt,
)

RPC = "https://rpc.example"
TX = "0x" + "12" * 32
BLOCK = "0x" + "34" * 32
CASE = "0x" + "56" * 32
PAYER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
ESCROW = "0x" + "33" * 20


def word(value):
    return "0x" + (value[2:].rjust(64, "0") if isinstance(value, str) else f"{value:064x}")


def receipt(hold=False):
    log = {
        "address": ESCROW if hold else CANONICAL_USDC,
        "topics": [HELD_TOPIC, word(7), CASE, word(PAYER)] if hold else [TRANSFER_TOPIC, word(PAYER), word(PAYEE)],
        "data": word(PAYEE) + word(50000)[2:] if hold else word(50000),
    }
    return {"status": "0x1", "transactionHash": TX, "blockHash": BLOCK, "logs": [log]}


def mock_rpc(respx_mock, result, *, chain="0x14a34", timestamp=100):
    def answer(request):
        import json
        method = json.loads(request.content)["method"]
        value = {"eth_chainId": chain, "eth_getTransactionReceipt": result,
                 "eth_getBlockByHash": {"timestamp": hex(timestamp)}}[method]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": value})
    return respx_mock.post(RPC).mock(side_effect=answer)


async def payment(**kw):
    args = dict(chain_id=84532, token=CANONICAL_USDC, payer=PAYER, payee=PAYEE, amount="50000", min_timestamp=100)
    args.update(kw)
    return await verify_payment_receipt(RPC, TX, **args)


async def hold(**kw):
    args = dict(chain_id=84532, escrow=ESCROW, payer=PAYER, payee=PAYEE, amount="50000",
                case_id_b32=CASE, hold_id=7, min_timestamp=100)
    args.update(kw)
    return await verify_hold_receipt(RPC, TX, **args)


@pytest.mark.parametrize("held", [False, True])
async def test_exact_successful_receipt(held, respx_mock):
    expected = receipt(held)
    mock_rpc(respx_mock, expected)
    assert await (hold() if held else payment()) == expected


@pytest.mark.parametrize("mutation", ["pending", "reverted", "wrong_tx", "wrong_chain", "old", "empty", "removed"])
async def test_unproven_transaction_is_rejected(mutation, respx_mock):
    result = receipt()
    chain, timestamp = "0x14a34", 100
    if mutation == "pending": result = None
    if mutation == "reverted": result["status"] = "0x0"
    if mutation == "wrong_tx": result["transactionHash"] = BLOCK
    if mutation == "wrong_chain": chain = "0x1"
    if mutation == "old": timestamp = 99
    if mutation == "empty": result["logs"] = []
    if mutation == "removed": result["logs"][0]["removed"] = True
    mock_rpc(respx_mock, result, chain=chain, timestamp=timestamp)
    with pytest.raises(ReceiptValidationError) as caught:
        await payment()
    assert caught.value.status == 409


@pytest.mark.parametrize("field,value", [("token", ESCROW), ("payer", ESCROW), ("payee", ESCROW), ("amount", "50001")])
async def test_wrong_payment_binding(field, value, respx_mock):
    mock_rpc(respx_mock, receipt())
    with pytest.raises(ReceiptValidationError):
        await payment(**{field: value})


@pytest.mark.parametrize("field,value", [("escrow", PAYEE), ("payer", ESCROW), ("payee", ESCROW),
                                         ("amount", "50001"), ("hold_id", 8), ("case_id_b32", BLOCK)])
async def test_wrong_hold_binding(field, value, respx_mock):
    mock_rpc(respx_mock, receipt(True))
    with pytest.raises(ReceiptValidationError):
        await hold(**{field: value})


async def test_forged_token_emitter_is_rejected(respx_mock):
    result = receipt()
    result["logs"][0]["address"] = ESCROW
    mock_rpc(respx_mock, result)
    with pytest.raises(ReceiptValidationError):
        await payment()


async def test_rpc_failure_is_502(respx_mock):
    respx_mock.post(RPC).mock(return_value=httpx.Response(503))
    with pytest.raises(ReceiptValidationError) as caught:
        await payment()
    assert caught.value.status == 502


async def test_same_second_payment_is_accepted(respx_mock):
    mock_rpc(respx_mock, receipt(), timestamp=100)
    await payment(min_timestamp=100.9)


@pytest.mark.parametrize("held", [False, True])
async def test_missing_block_is_retried_without_repeating_transaction(held, respx_mock, monkeypatch):
    import json
    calls, sleeps = [], []
    blocks = iter([None, None, {"timestamp": "0x64"}])
    async def sleep(delay):
        sleeps.append(delay)
    monkeypatch.setattr("sekisho_gate.receipts.asyncio.sleep", sleep)
    def answer(request):
        body = json.loads(request.content)
        calls.append((body["method"], body["params"]))
        value = next(blocks) if body["method"] == "eth_getBlockByHash" else {
            "eth_chainId": "0x14a34", "eth_getTransactionReceipt": receipt(held)}[body["method"]]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": value})
    respx_mock.post(RPC).mock(side_effect=answer)
    assert await (hold() if held else payment()) == receipt(held)
    assert sleeps == [0.5, 1.0]
    assert calls == [("eth_chainId", [])] + [("eth_getTransactionReceipt", [TX]),
        ("eth_getBlockByHash", [BLOCK, False])] * 3


async def test_missing_block_retries_exhaust_to_502(respx_mock, monkeypatch):
    import json
    sleeps, methods = [], []
    async def sleep(delay):
        sleeps.append(delay)
    monkeypatch.setattr("sekisho_gate.receipts.asyncio.sleep", sleep)
    def answer(request):
        method = json.loads(request.content)["method"]
        methods.append(method)
        value = {"eth_chainId": "0x14a34", "eth_getTransactionReceipt": receipt(), "eth_getBlockByHash": None}[method]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": value})
    respx_mock.post(RPC).mock(side_effect=answer)
    with pytest.raises(ReceiptValidationError) as caught:
        await payment()
    assert caught.value.status == 502
    assert sleeps == [0.5, 1.0, 2.0, 4.0]
    assert methods.count("eth_getBlockByHash") == 5
    assert methods.count("eth_getTransactionReceipt") == 5


@pytest.mark.parametrize("block,status", [({}, 502), ({"timestamp": "not-hex"}, 502), ({"timestamp": "0x63"}, 409)])
async def test_non_null_bad_block_is_never_retried(block, status, respx_mock, monkeypatch):
    import json
    async def no_sleep(delay):
        raise AssertionError("Only a null block may be retried")
    monkeypatch.setattr("sekisho_gate.receipts.asyncio.sleep", no_sleep)
    calls = []
    def answer(request):
        method = json.loads(request.content)["method"]
        calls.append(method)
        value = {"eth_chainId": "0x14a34", "eth_getTransactionReceipt": receipt(), "eth_getBlockByHash": block}[method]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": value})
    respx_mock.post(RPC).mock(side_effect=answer)
    with pytest.raises(ReceiptValidationError) as caught:
        await payment()
    assert caught.value.status == status
    assert calls.count("eth_getBlockByHash") == 1


@pytest.mark.parametrize("first_hash", [BLOCK, "0x0", "0x" + "0" * 64])
async def test_provisional_receipt_refreshes_to_new_block_hash(first_hash, respx_mock, monkeypatch):
    import json
    canonical_hash = "0x" + "ab" * 32
    early, final = receipt(), receipt()
    early["blockHash"], final["blockHash"] = first_hash, canonical_hash
    receipts = iter([early, final])
    calls = []
    async def sleep(delay):
        assert delay == 0.5
    monkeypatch.setattr("sekisho_gate.receipts.asyncio.sleep", sleep)
    def answer(request):
        body = json.loads(request.content)
        calls.append((body["method"], body["params"]))
        if body["method"] == "eth_chainId": value = "0x14a34"
        elif body["method"] == "eth_getTransactionReceipt": value = next(receipts)
        else: value = {"timestamp": "0x64"} if body["params"][0] == canonical_hash else None
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": value})
    respx_mock.post(RPC).mock(side_effect=answer)
    assert await payment() == final
    assert [params for method, params in calls if method == "eth_getTransactionReceipt"] == [[TX], [TX]]
    assert calls[-1] == ("eth_getBlockByHash", [canonical_hash, False])


@pytest.mark.parametrize("mutation", ["wrong_tx", "reverted", "empty_logs", "stale"])
async def test_refreshed_receipt_is_fully_revalidated(mutation, respx_mock, monkeypatch):
    import json
    early, final = receipt(), receipt()
    early["blockHash"] = "0x0"
    if mutation == "wrong_tx": final["transactionHash"] = BLOCK
    if mutation == "reverted": final["status"] = "0x0"
    if mutation == "empty_logs": final["logs"] = []
    receipts = iter([early, final])
    async def sleep(delay): pass
    monkeypatch.setattr("sekisho_gate.receipts.asyncio.sleep", sleep)
    def answer(request):
        method = json.loads(request.content)["method"]
        if method == "eth_chainId": value = "0x14a34"
        elif method == "eth_getTransactionReceipt": value = next(receipts)
        else: value = {"timestamp": "0x63" if mutation == "stale" else "0x64"}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": value})
    respx_mock.post(RPC).mock(side_effect=answer)
    with pytest.raises(ReceiptValidationError) as caught:
        await payment()
    assert caught.value.status == 409


async def test_placeholder_receipt_never_counts_as_final_even_without_timestamp(respx_mock, monkeypatch):
    import json
    early = receipt()
    early["blockHash"] = "0x0"
    sleeps = []
    async def sleep(delay): sleeps.append(delay)
    monkeypatch.setattr("sekisho_gate.receipts.asyncio.sleep", sleep)
    def answer(request):
        method = json.loads(request.content)["method"]
        assert method in ("eth_chainId", "eth_getTransactionReceipt")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                       "result": "0x14a34" if method == "eth_chainId" else early})
    respx_mock.post(RPC).mock(side_effect=answer)
    with pytest.raises(ReceiptValidationError) as caught:
        await payment(min_timestamp=None)
    assert caught.value.status == 502
    assert sleeps == [0.5, 1.0, 2.0, 4.0]

"""Read-only proof checks before accepting agent-reported payment/escrow state.

The caller supplies trusted expected parties from its case and configured agent.
Transaction uniqueness across cases is the caller's responsibility: ERC20 Transfer
has no case identifier. These checks never send a transaction.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
from eth_utils import keccak

from .errors import GateError
from .util import checksum_or_none, norm_hex32, validate_payment_asset

TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
HELD_TOPIC = "0x" + keccak(text="Held(uint256,bytes32,address,address,uint256)").hex()
CANONICAL_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


class ReceiptValidationError(GateError):
    """No matching successful onchain event could be established."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(status, "receipt_unavailable" if status == 502 else "receipt_mismatch", message)


def _address(value: Any) -> str:
    result = checksum_or_none(value)
    if result is None:
        raise ReceiptValidationError("Expected a valid configured EVM address")
    return result.lower()


def _word(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise ReceiptValidationError("Malformed event word")
    try:
        if len(bytes.fromhex(value[2:])) != 32:
            raise ValueError("not a 32-byte word")
    except ValueError as exc:
        raise ReceiptValidationError("Malformed event word") from exc
    return value.lower()


def _address_word(value: Any) -> str:
    return "0x" + "0" * 24 + _address(value)[2:]


async def _rpc(http: httpx.AsyncClient, url: str, method: str, params: list) -> Any:
    try:
        response = await http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=5.0)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ReceiptValidationError("Receipt RPC is unavailable", 502) from exc
    if not isinstance(body, dict) or body.get("error") or "result" not in body:
        raise ReceiptValidationError("Receipt RPC returned an invalid response", 502)
    return body["result"]


async def _receipt(
    http: httpx.AsyncClient, rpc_url: str, tx_hash: str, chain_id: int,
    min_timestamp: int | None,
) -> dict:
    if chain_id != 84532:
        raise ReceiptValidationError("Receipt verification supports Base Sepolia only")
    normalized = norm_hex32(tx_hash)
    if normalized is None:
        raise ReceiptValidationError("Invalid transaction hash")
    if await _rpc(http, rpc_url, "eth_chainId", []) != hex(chain_id):
        raise ReceiptValidationError("Receipt RPC is connected to the wrong chain")
    # Flashblock receipts can carry a placeholder or provisional block hash.
    # Refresh the SAME transaction's receipt on each retry, validating every new
    # response, so we do not poll an obsolete block hash forever. No writes occur.
    for attempt, delay in enumerate((0.0, 0.5, 1.0, 2.0, 4.0)):
        if delay:
            await asyncio.sleep(delay)
        receipt = await _rpc(http, rpc_url, "eth_getTransactionReceipt", [normalized])
        if receipt is None and attempt:
            continue  # transient disappearance while the preconfirmation seals
        if not isinstance(receipt, dict):
            raise ReceiptValidationError("Transaction receipt is pending or missing")
        block_hash = receipt.get("blockHash")
        placeholder = block_hash in ("0x0", "0x" + "0" * 64)
        if (receipt.get("status") != "0x1" or norm_hex32(receipt.get("transactionHash")) != normalized
                or (not placeholder and not norm_hex32(block_hash)) or not isinstance(receipt.get("logs"), list)):
            raise ReceiptValidationError("Transaction receipt is unsuccessful or malformed")
        if placeholder:
            continue
        if min_timestamp is None:
            return receipt
        block = await _rpc(http, rpc_url, "eth_getBlockByHash", [block_hash, False])
        if block is None:
            continue
        try:
            timestamp = int(block["timestamp"], 16)
        except (TypeError, KeyError, ValueError) as exc:
            raise ReceiptValidationError("Receipt block timestamp is unavailable", 502) from exc
        if timestamp < int(min_timestamp):
            raise ReceiptValidationError("Transaction predates this case")
        return receipt
    raise ReceiptValidationError("Receipt block timestamp is unavailable", 502)


def _matching_logs(receipt: dict, emitter: str, topic: str, topic_count: int):
    for entry in receipt["logs"]:
        if not isinstance(entry, dict) or entry.get("removed"):
            continue
        try:
            topics = entry.get("topics")
            if (_address(entry.get("address")) == emitter and isinstance(topics, list)
                    and len(topics) == topic_count and _word(topics[0]) == topic):
                yield entry, [_word(t) for t in topics]
        except ReceiptValidationError:
            continue


async def verify_payment_receipt(
    rpc_url: str, tx_hash: str, *, chain_id: int, token: str,
    payer: str, payee: str, amount: str | int, min_timestamp: int | None = None,
    http: httpx.AsyncClient | None = None,
) -> dict:
    """Require an exact canonical USDC Transfer from payer to payee on Base Sepolia."""
    try:
        validate_payment_asset(chain_id, token, CANONICAL_USDC)
        amount_int = int(amount)
        if amount_int <= 0:
            raise ValueError("nonpositive amount")
    except (ValueError, TypeError) as exc:
        raise ReceiptValidationError("Unsupported payment asset or amount") from exc
    sender, recipient, emitter = _address_word(payer), _address_word(payee), _address(token)
    if http is None:
        async with httpx.AsyncClient() as client:
            return await verify_payment_receipt(
                rpc_url, tx_hash, chain_id=chain_id, token=token, payer=payer, payee=payee,
                amount=amount, min_timestamp=min_timestamp, http=client,
            )
    receipt = await _receipt(http, rpc_url, tx_hash, chain_id, min_timestamp)
    for entry, topics in _matching_logs(receipt, emitter, TRANSFER_TOPIC, 3):
        try:
            if topics[1:] == [sender, recipient] and int(_word(entry.get("data")), 16) == amount_int:
                return receipt
        except ReceiptValidationError:
            continue
    raise ReceiptValidationError("No matching USDC Transfer in the successful receipt")


async def verify_hold_receipt(
    rpc_url: str, tx_hash: str, *, chain_id: int, escrow: str,
    case_id_b32: str, hold_id: int, payer: str, payee: str, amount: str | int,
    min_timestamp: int | None = None, http: httpx.AsyncClient | None = None,
) -> dict:
    """Require the configured escrow's Held event bound to this exact case and hold."""
    emitter, sender, recipient = _address(escrow), _address_word(payer), _address_word(payee)
    case_word = _word(case_id_b32)
    try:
        amount_int = int(amount)
        if amount_int <= 0 or hold_id <= 0:
            raise ValueError("nonpositive amount or hold id")
    except (TypeError, ValueError) as exc:
        raise ReceiptValidationError("Invalid hold amount or id") from exc
    if http is None:
        async with httpx.AsyncClient() as client:
            return await verify_hold_receipt(
                rpc_url, tx_hash, chain_id=chain_id, escrow=escrow, case_id_b32=case_id_b32,
                hold_id=hold_id, payer=payer, payee=payee, amount=amount,
                min_timestamp=min_timestamp, http=client,
            )
    receipt = await _receipt(http, rpc_url, tx_hash, chain_id, min_timestamp)
    for entry, topics in _matching_logs(receipt, emitter, HELD_TOPIC, 4):
        data = entry.get("data")
        if not isinstance(data, str) or len(data) != 130 or not data.startswith("0x"):
            continue
        try:
            if (int(topics[1], 16) == hold_id and topics[2:] == [case_word, sender]
                    and _word(data[:66]) == recipient
                    and int(_word("0x" + data[66:]), 16) == amount_int):
                return receipt
        except ReceiptValidationError:
            continue
    raise ReceiptValidationError("No matching Held event in the successful receipt")

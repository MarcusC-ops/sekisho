"""Curvegrid MultiBaas client (PRD 9.8, 9.13).

Every contract write is composed by MultiBaas, signed locally with an eth-account
LocalAccount and submitted back through MultiBaas. Reads go through MultiBaas too.
Receipts are polled on CONTRACTS_RPC_URL. Unlike the screening clients, this client
raises `MultiBaasError` on failure, with any contract revert decoded from the
compose-time error body (MultiBaas estimates gas when composing, so reverts surface
there).

Also here: `parse_event` (webhook `data` or `/events` item -> flat dict),
`verify_webhook_signature` (HMAC-SHA256 over body + timestamp), `encode_args` and
`decode_revert`.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from collections.abc import Sequence
from typing import Any

import httpx
from eth_utils import is_address, keccak, to_checksum_address

log = logging.getLogger(__name__)

VERDICT_CODES = {"NONE": 0, "ALLOW": 1, "HOLD": 2, "BLOCK": 3}  # ComplianceRegistry.Verdict

# Custom errors of ComplianceRegistry, ComplianceEscrow and their OpenZeppelin bases,
# plus the Solidity builtins. Selectors are computed, so they cannot drift from the
# signatures (they match PRD 9.11 step 6 and `forge inspect`).
ERROR_SIGNATURES = [
    "NotCleared()",
    "NotHeld()",
    "PayeeBlocked()",
    "ZeroAmount()",
    "NotPayer()",
    "TooEarly()",
    "InvalidVerdict()",
    "InvalidScore()",
    "InvalidTtl()",
    "AccessControlUnauthorizedAccount(address,bytes32)",
    "AccessControlBadConfirmation()",
    "ReentrancyGuardReentrantCall()",
    "SafeERC20FailedOperation(address)",
    "ERC20InsufficientAllowance(address,uint256,uint256)",
    "ERC20InsufficientBalance(address,uint256,uint256)",
    "Panic(uint256)",
]
KNOWN_ERRORS = {"0x" + keccak(text=sig)[:4].hex(): sig.split("(")[0] for sig in ERROR_SIGNATURES}
ERROR_SELECTORS = {name: sel for sel, name in KNOWN_ERRORS.items()}
ERROR_STRING_SELECTOR = "0x08c379a0"  # Error(string): plain require/revert messages

# ABI input types per method, used to encode args (PRD 9.8). "enum" = uint8 enum,
# sent as a JSON number; uints go as decimal strings; bytes32 as 0x + 64 hex.
METHOD_TYPES: dict[str, list[str]] = {
    # ComplianceRegistry
    "recordScreening": ["address", "enum", "uint8", "uint64", "bytes32", "bytes32", "bytes32"],
    "overrideVerdict": ["address", "enum", "uint64", "bytes32", "bytes32"],
    "latest": ["address"],
    "isCleared": ["address"],
    "isBlocked": ["address"],
    "hasRole": ["bytes32", "address"],
    "grantRole": ["bytes32", "address"],
    # ComplianceEscrow
    "deposit": ["address", "uint256", "bytes32"],
    "release": ["uint256"],
    "refund": ["uint256"],
    "holds": ["uint256"],
    # ERC-20 (USDC)
    "approve": ["address", "uint256"],
    "allowance": ["address", "address"],
    "balanceOf": ["address"],
    "transfer": ["address", "uint256"],
}

_RETRYABLE = {429, 500, 502, 503, 504}
_HEX_RUN = re.compile(r"0x([0-9a-fA-F]{8,})")
# Errors the chain raises regardless of how the signed tx is spelled.
_CHAIN_REJECTIONS = (
    "nonce", "insufficient funds", "underpriced", "fee cap", "intrinsic gas",
    "gas limit", "already known", "known transaction", "revert",
)


class MultiBaasError(Exception):
    """A failed MultiBaas (or contract-chain RPC) call.

    status: HTTP status, or None for transport errors and timeouts.
    body: the response body text (MultiBaas errors are {"status", "message"}).
    revert / selector: the decoded custom error, e.g. "NotCleared" / "0x92a032ca".
    reason: an Error(string) revert message, if any (e.g. from real USDC).
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: str = "",
        revert: str | None = None,
        selector: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.revert = revert
        self.selector = selector
        self.reason = reason

    @classmethod
    def from_http(cls, what: str, status: int, body: str) -> MultiBaasError:
        decoded = decode_revert(body)
        reason = revert_reason(body)
        message = _body_message(body)
        text = f"{what}: HTTP {status}"
        if decoded:
            text += f": reverted with {decoded[0]}"
        elif reason:
            text += f": reverted: {reason}"
        elif message:
            text += f": {message}"
        return cls(
            text, status=status, body=body[:4000], revert=decoded[0] if decoded else None,
            selector=decoded[1] if decoded else None, reason=reason,
        )


class ReceiptTimeout(MultiBaasError):
    """No receipt within the timeout."""


def _body_message(body: str) -> str:
    try:
        parsed = json.loads(body)
    except ValueError:
        return body.strip()[:300]
    if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
        return parsed["message"][:300]
    return body.strip()[:300]


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"not an integer: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lower().startswith("0x"):
            return int(text, 16)
        if re.fullmatch(r"-?\d+", text):
            return int(text)
    raise ValueError(f"not an integer: {value!r}")


def _int_or_zero(value: Any) -> int:
    return 0 if value is None or value == "" else _to_int(value)


# ---------- argument encoding ----------


def encode_arg(abi_type: str, value: Any) -> Any:
    """One argument in the form MultiBaas expects (PRD 9.8): address -> checksummed
    0x string, uintN/intN -> decimal string, enum -> JSON number (verdict names are
    accepted), bytes32 -> 0x + 64 lowercase hex. Raises ValueError on bad input."""
    t = abi_type.strip()
    if t == "address":
        if isinstance(value, (bytes, bytearray)) and len(value) == 20:
            value = "0x" + bytes(value).hex()
        if not isinstance(value, str) or not is_address(value):
            raise ValueError(f"not an address: {value!r}")
        return to_checksum_address(value)
    if t.startswith("enum"):
        if isinstance(value, str) and value.strip().upper() in VERDICT_CODES:
            return VERDICT_CODES[value.strip().upper()]
        n = _to_int(value)
        if not 0 <= n <= 255:
            raise ValueError(f"enum out of range: {value!r}")
        return n
    if t.startswith("uint"):
        n = _to_int(value)
        bits = int(t[4:] or 256)
        if not 0 <= n < 2**bits:
            raise ValueError(f"{t} out of range: {value!r}")
        return str(n)
    if t.startswith("int"):
        n = _to_int(value)
        bits = int(t[3:] or 256)
        if not -(2 ** (bits - 1)) <= n < 2 ** (bits - 1):
            raise ValueError(f"{t} out of range: {value!r}")
        return str(n)
    if t == "bytes32":
        if isinstance(value, (bytes, bytearray)):
            h = bytes(value).hex()
        elif isinstance(value, str):
            h = value.strip().lower().removeprefix("0x")
        else:
            raise ValueError(f"not bytes32: {value!r}")
        if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
            raise ValueError(f"not bytes32 (need 0x + 64 hex): {value!r}")
        return "0x" + h
    if t == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise ValueError(f"not a bool: {value!r}")
    if t == "bytes":
        if isinstance(value, (bytes, bytearray)):
            return "0x" + bytes(value).hex()
        return value
    if t == "string":
        return str(value)
    return value


def encode_args(types: Sequence[str], args: Sequence[Any]) -> list:
    """Encode a whole argument list. Idempotent: encoding encoded args changes nothing."""
    if len(types) != len(args):
        raise ValueError(f"expected {len(types)} args ({', '.join(types)}), got {len(args)}")
    return [encode_arg(t, v) for t, v in zip(types, args)]


def _encode_for(method: str, args: Sequence[Any], types: Sequence[str] | None) -> list:
    if types is None:
        types = METHOD_TYPES.get(method)
    if types is not None:
        return encode_args(types, args)
    return ["0x" + bytes(a).hex() if isinstance(a, (bytes, bytearray)) else a for a in args]


# ---------- revert decoding ----------


def decode_revert(text: str) -> tuple[str, str] | None:
    """Find a known custom-error selector (or name) in an error body.
    Returns (name, selector), e.g. ("NotCleared", "0x92a032ca"), or None."""
    if not text:
        return None
    text = text if isinstance(text, str) else str(text)
    for m in _HEX_RUN.finditer(text):
        sel = "0x" + m.group(1)[:8].lower()
        if sel in KNOWN_ERRORS:
            return KNOWN_ERRORS[sel], sel
    for sel, name in KNOWN_ERRORS.items():
        if name != "Panic" and re.search(rf"\b{name}\b", text):
            return name, sel
    return None


def revert_reason(text: str) -> str | None:
    """The message of an Error(string) revert: ABI-decoded from hex data, or the text
    after "execution reverted:". None if there is none (or it is a custom error)."""
    if not text:
        return None
    for m in _HEX_RUN.finditer(text):
        h = m.group(1)
        if h[:8].lower() != ERROR_STRING_SELECTOR[2:] or len(h) < 8 + 128:
            continue
        try:
            data = bytes.fromhex(h[8 : 8 + (len(h) - 8) // 2 * 2])
            offset = int.from_bytes(data[0:32], "big")
            length = int.from_bytes(data[offset : offset + 32], "big")
            reason = data[offset + 32 : offset + 32 + length].decode("utf-8", "replace")
        except (ValueError, IndexError):
            continue
        if reason:
            return reason
    m = re.search(r"execution reverted:\s*([^\"\n\\]+)", text)
    if m:
        reason = m.group(1).strip().rstrip("}").strip()
        if reason and not reason.lower().startswith("0x") and not re.fullmatch(r"\w+\(.*\)", reason):
            return reason
    return None


def _is_chain_rejection(body: str) -> bool:
    low = (body or "").lower()
    return any(k in low for k in _CHAIN_REJECTIONS)


# ---------- events and webhooks ----------


def _hex_or_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return _to_int(value)
    except ValueError:
        return None


def parse_event(raw: dict) -> dict:
    """A webhook `data` object, a whole webhook item, or a `/events` item ->
    {"name", "contract_alias", "contract_address", "tx_hash", "block_number",
    "log_index", "inputs": {name: value}}. Input values are kept as MultiBaas sent
    them (strings for uints). The alias is `addressAlias` in the OpenAPI spec but
    `addressLabel` in the docs' webhook sample, so both are read."""
    if isinstance(raw.get("data"), dict) and "event" in raw["data"]:
        raw = raw["data"]
    ev = raw.get("event") or {}
    tx = raw.get("transaction") or {}
    contract = ev.get("contract") or {}  # the emitter; transaction.contract is the called contract
    raw_fields: dict = {}
    if isinstance(ev.get("rawFields"), str):
        try:
            parsed = json.loads(ev["rawFields"])
            raw_fields = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            raw_fields = {}
    address = contract.get("address") or raw_fields.get("address")
    alias = contract.get("addressAlias") or contract.get("addressLabel") or None
    called = tx.get("contract") or {}
    if alias is None and address and str(called.get("address", "")).lower() == str(address).lower():
        alias = called.get("addressAlias") or called.get("addressLabel") or None
    tx_hash = tx.get("txHash") or raw_fields.get("transactionHash")
    block = tx.get("blockNumber")
    block = _hex_or_int(block) if block is not None else _hex_or_int(raw_fields.get("blockNumber"))
    log_index = ev.get("indexInLog")
    log_index = _hex_or_int(log_index) if log_index is not None else _hex_or_int(raw_fields.get("logIndex"))
    inputs = {}
    for i, item in enumerate(ev.get("inputs") or []):
        if isinstance(item, dict):
            inputs[item.get("name") or f"arg{i}"] = item.get("value")
    return {
        "name": ev.get("name"),
        "contract_alias": alias,
        "contract_address": to_checksum_address(address) if isinstance(address, str) and is_address(address) else None,
        "tx_hash": tx_hash.lower() if isinstance(tx_hash, str) else None,
        "block_number": block,
        "log_index": log_index,
        "inputs": inputs,
    }


def verify_webhook_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    secret: str,
    *,
    max_age_s: float | None = None,
    now: float | None = None,
) -> bool:
    """X-MultiBaas-Signature = hex(HMAC-SHA256(secret, body + timestamp)), timestamp in
    Unix seconds as sent in X-MultiBaas-Timestamp. An empty secret never verifies.
    `max_age_s` (optional) also rejects stale timestamps."""
    if not secret or not timestamp or not signature:
        return False
    if isinstance(body, str):
        body = body.encode("utf-8")
    ts = str(timestamp).strip()
    if max_age_s is not None:
        try:
            age = abs((time.time() if now is None else now) - int(ts))
        except ValueError:
            return False
        if age > max_age_s:
            return False
    expected = hmac.new(secret.encode("utf-8"), bytes(body) + ts.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature).strip().lower())


# ---------- transactions ----------


def build_unsigned_tx(tx: dict, chain_id: int) -> dict:
    """A MultiBaas composed tx (`result.tx`) -> an eth-account transaction dict. The
    composed tx has no chain id, so CHAIN_ID is used. Fees and value are decimal
    strings, nonce and gas are ints; hex is tolerated."""
    out: dict[str, Any] = {
        "nonce": _to_int(tx["nonce"]),
        "gas": _to_int(tx["gas"]),
        "data": tx.get("data") or "0x",
        "value": _int_or_zero(tx.get("value")),
        "chainId": int(chain_id),
    }
    if tx.get("to"):
        out["to"] = to_checksum_address(tx["to"])
    tx_type = _hex_or_int(tx.get("type"))
    if tx.get("gasFeeCap") is not None or tx_type == 2:
        out["maxFeePerGas"] = _int_or_zero(tx.get("gasFeeCap"))
        out["maxPriorityFeePerGas"] = _int_or_zero(tx.get("gasTipCap"))
        out["type"] = 2
    else:
        out["gasPrice"] = _int_or_zero(tx.get("gasPrice"))
    return out


def normalise_receipt(receipt: dict) -> dict:
    out = dict(receipt)
    for key in ("status", "blockNumber", "gasUsed", "cumulativeGasUsed", "effectiveGasPrice", "transactionIndex", "type"):
        if key in out and out[key] is not None:
            value = _hex_or_int(out[key])
            if value is not None:
                out[key] = value
    return out


class MultiBaasClient:
    def __init__(self, settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._url = settings.mb_url.strip().rstrip("/")
        self._key = settings.mb_admin_api_key.get_secret_value().strip()
        self._api = f"{self._url}/api/v0"
        self._chain_id = int(settings.chain_id)
        self._rpc_url = settings.contracts_rpc_url
        self._own_http = http is None
        self._http = http or httpx.AsyncClient()
        self._aliases: dict[str, str] = {}
        # The docs' submit example sends the raw tx without 0x; flipped (and logged) if
        # MultiBaas rejects that form and accepts the other.
        self.submit_with_0x = False

    @property
    def configured(self) -> bool:
        return bool(self._url and self._key) and "<" not in self._url

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()

    # ---------- HTTP ----------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        what: str,
        json_body: Any = None,
        params: dict | None = None,
        retries: int = 2,
        timeout: float = 15.0,
    ) -> Any:
        """One MultiBaas API call; returns the envelope's `result`. Retries (max 2,
        backoff) on 429/5xx and transport errors, never on a decoded revert."""
        if not self.configured:
            raise MultiBaasError("MultiBaas is not configured (MB_URL / MB_ADMIN_API_KEY)")
        url = self._api + path
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        last: MultiBaasError | None = None
        for attempt in range(retries + 1):
            try:
                resp = await self._http.request(
                    method, url, json=json_body, params=params, headers=headers, timeout=timeout
                )
            except httpx.TimeoutException:
                last = MultiBaasError(f"{what}: timed out after {timeout:g} s")
            except httpx.HTTPError as exc:
                last = MultiBaasError(f"{what}: request failed ({type(exc).__name__})")
            else:
                text = resp.text
                if resp.status_code < 400:
                    try:
                        body = resp.json()
                    except ValueError:
                        raise MultiBaasError(
                            f"{what}: non-JSON response", status=resp.status_code, body=text[:4000]
                        ) from None
                    if isinstance(body, dict):
                        if "result" in body:
                            return body["result"]
                        if body.get("message") not in (None, "success"):
                            raise MultiBaasError(
                                f"{what}: {body.get('message')}", status=resp.status_code, body=text[:4000]
                            )
                    return body
                err = MultiBaasError.from_http(what, resp.status_code, text)
                if resp.status_code not in _RETRYABLE or err.revert or err.reason:
                    raise err
                last = err
            if attempt < retries:
                await asyncio.sleep(0.5 * 2**attempt)
        assert last is not None
        raise last

    async def _rpc(self, method: str, params: list, *, timeout: float = 5.0) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            resp = await self._http.post(self._rpc_url, json=payload, timeout=timeout)
        except httpx.HTTPError as exc:
            raise MultiBaasError(f"RPC {method}: request failed ({type(exc).__name__})") from None
        if resp.status_code != 200:
            raise MultiBaasError(f"RPC {method}: HTTP {resp.status_code}", status=resp.status_code, body=resp.text[:2000])
        try:
            body = resp.json()
        except ValueError:
            raise MultiBaasError(f"RPC {method}: non-JSON response", body=resp.text[:2000]) from None
        if isinstance(body, dict) and body.get("error"):
            raise MultiBaasError(f"RPC {method}: {body['error']}", body=json.dumps(body)[:2000])
        return body.get("result") if isinstance(body, dict) else None

    # ---------- contract calls ----------

    def _method_path(self, alias: str, label: str, method: str) -> str:
        return f"/chains/ethereum/addresses/{alias}/contracts/{label}/methods/{method}"

    async def pending_nonce(self, address: str) -> int | None:
        """eth_getTransactionCount(address, "pending") on CONTRACTS_RPC_URL, or None."""
        try:
            return _to_int(await self._rpc("eth_getTransactionCount", [address, "pending"]))
        except (MultiBaasError, ValueError) as exc:
            log.warning("pending nonce lookup failed; letting MultiBaas choose: %s", exc)
            return None

    async def compose(
        self, alias: str, label: str, method: str, args: list, sender: str, *,
        nonce: int | None = None, types: Sequence[str] | None = None,
    ) -> dict:
        """Ask MultiBaas to build (not sign) a transaction; returns `result.tx`."""
        body: dict[str, Any] = {"args": _encode_for(method, args, types), "from": to_checksum_address(sender)}
        if nonce is not None:
            body["nonce"] = int(nonce)
        result = await self._request(
            "POST", self._method_path(alias, label, method), json_body=body, what=f"compose {method}"
        )
        tx = result.get("tx") if isinstance(result, dict) else None
        if not isinstance(tx, dict):
            raise MultiBaasError(
                f"compose {method}: no transaction in the response (is it a read method?)",
                body=json.dumps(result, default=str)[:4000],
            )
        if tx.get("from") and str(tx["from"]).lower() != sender.lower():
            raise MultiBaasError(f"compose {method}: MultiBaas built the tx for {tx['from']}, not {sender}")
        return tx

    async def call_write(
        self, alias: str, label: str, method: str, args: list, signer, *,
        nonce: int | None = None, types: Sequence[str] | None = None,
    ) -> str:
        """Compose via MultiBaas, sign locally, submit. Returns the tx hash.
        The nonce defaults to the signer's pending nonce on CONTRACTS_RPC_URL (one
        queue per signer key upstream means no two writes race)."""
        if self._chain_id != 84532:
            raise MultiBaasError("Contract writes are restricted to Base Sepolia (chain 84532)")
        if nonce is None:
            nonce = await self.pending_nonce(signer.address)
        tx = await self.compose(alias, label, method, args, signer.address, nonce=nonce, types=types)
        signed = signer.sign_transaction(build_unsigned_tx(tx, self._chain_id))
        raw = bytes(signed.raw_transaction)
        return await self._submit(raw, "0x" + keccak(raw).hex(), method)

    async def _submit(self, raw: bytes, local_hash: str, method: str) -> str:
        forms = [self.submit_with_0x, not self.submit_with_0x]
        for i, with_0x in enumerate(forms):
            signed_tx = ("0x" if with_0x else "") + raw.hex()
            try:
                result = await self._request(
                    "POST", "/chains/ethereum/transactions/submit",
                    json_body={"signedTx": signed_tx}, what=f"submit {method}",
                )
            except MultiBaasError as err:
                low = (err.body or "").lower()
                if "already known" in low or "known transaction" in low:
                    log.info("submit %s: transaction already known, using the local hash", method)
                    return local_hash
                retry_other_form = (
                    i == 0 and err.status is not None and 400 <= err.status < 500
                    and not err.revert and not err.reason and not _is_chain_rejection(err.body)
                )
                if retry_other_form:
                    log.warning(
                        "submit %s: MultiBaas rejected signedTx %s the 0x prefix (HTTP %s); retrying %s it",
                        method, "with" if with_0x else "without", err.status, "without" if with_0x else "with",
                    )
                    continue
                raise
            if i == 1:
                self.submit_with_0x = with_0x
                log.info("submit %s: MultiBaas accepted signedTx %s the 0x prefix", method, "with" if with_0x else "without")
            tx_hash = ((result or {}).get("tx") or {}).get("hash") if isinstance(result, dict) else None
            if isinstance(tx_hash, str) and tx_hash:
                if tx_hash.lower() != local_hash.lower():
                    log.warning("submit %s: MultiBaas hash %s differs from local %s", method, tx_hash, local_hash)
                return tx_hash
            return local_hash
        raise MultiBaasError(f"submit {method}: rejected in both signedTx forms")  # unreachable

    async def call_read(
        self, alias: str, label: str, method: str, args: list, *,
        types: Sequence[str] | None = None, format_ints: str = "auto",
    ) -> Any:
        """A view call through MultiBaas; returns `result.output`."""
        body = {"args": _encode_for(method, args, types), "formatInts": format_ints}
        result = await self._request(
            "POST", self._method_path(alias, label, method), json_body=body, what=f"read {method}"
        )
        if not isinstance(result, dict) or "output" not in result:
            raise MultiBaasError(
                f"read {method}: no output in the response", body=json.dumps(result, default=str)[:4000]
            )
        return result["output"]

    async def wait_for_receipt(self, tx_hash: str, timeout_s: float = 30.0, *, poll_s: float = 1.0) -> dict:
        """Poll eth_getTransactionReceipt on CONTRACTS_RPC_URL every `poll_s` seconds.
        Returns the receipt with status/blockNumber/gas fields as ints; raises
        ReceiptTimeout if none arrives within `timeout_s`."""
        deadline = time.monotonic() + timeout_s
        last_error: Exception | None = None
        while True:
            try:
                receipt = await self._rpc("eth_getTransactionReceipt", [tx_hash])
            except MultiBaasError as exc:
                last_error = exc
            else:
                if isinstance(receipt, dict):
                    return normalise_receipt(receipt)
            if time.monotonic() + poll_s > deadline:
                detail = f" (last RPC error: {last_error})" if last_error else ""
                raise ReceiptTimeout(f"no receipt for {tx_hash} after {timeout_s:g} s{detail}")
            await asyncio.sleep(poll_s)

    # ---------- events, queries, addresses ----------

    async def list_events(
        self, *, tx_hash: str | None = None, contract_alias: str | None = None, limit: int = 20
    ) -> list[dict]:
        """`GET /events`, parse_event()-normalised. /events has no sort and defaults to
        10 items, so poll by `tx_hash` for a pending transaction."""
        params: dict[str, Any] = {"limit": int(limit)}
        if tx_hash:
            params["tx_hash"] = tx_hash
        if contract_alias:
            params["contract_address"] = await self.address_of(contract_alias)
        result = await self._request("GET", "/events", params=params, what="list events")
        if tx_hash and not result:
            # Some deployments return an empty tx_hash-filtered list despite
            # indexing the event. The official parameter is still tx_hash; use
            # a bounded numeric lookup, then enforce the exact hash locally.
            try:
                receipt = await self._rpc("eth_getTransactionReceipt", [tx_hash])
            except MultiBaasError:
                return []
            if not isinstance(receipt, dict) or str(receipt.get("transactionHash", "")).lower() != tx_hash.lower():
                return []
            block = _hex_or_int(receipt.get("blockNumber"))
            index = _hex_or_int(receipt.get("transactionIndex"))
            if block is None or index is None:
                return []
            fallback = {k: v for k, v in params.items() if k != "tx_hash"}
            fallback.update(block_number=block, tx_index_in_block=index)
            result = await self._request("GET", "/events", params=fallback, what="list events by transaction position")
            return [parsed for e in (result or []) if isinstance(e, dict)
                    if (parsed := parse_event(e))["tx_hash"] == tx_hash.lower()]
        return [parse_event(e) for e in (result or []) if isinstance(e, dict)]

    async def query_results(self, name: str, *, limit: int = 100) -> list[dict]:
        """Complete saved-query rows, paged within MultiBaas's 50-row API ceiling.

        `limit` is the caller's safety ceiling. If more rows exist, raise rather
        than present a truncated financial aggregate as a complete result.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("query limit must be a positive integer")
        collected: list[dict] = []
        while True:
            remaining = limit - len(collected)
            page_size = min(50, remaining) if remaining else 1
            result = await self._request(
                "GET", f"/queries/{name}/results",
                params={"limit": page_size, "offset": len(collected)}, what=f"query {name}"
            )
            rows = result.get("rows") if isinstance(result, dict) else None
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or len(rows) > page_size:
                raise MultiBaasError(f"query {name}: invalid rows response")
            if not remaining:
                if rows:
                    raise MultiBaasError(f"query {name}: more than {limit} rows; refusing truncated totals")
                return collected
            collected.extend(rows)
            if len(rows) < page_size:
                return collected

    async def address_of(self, alias: str) -> str:
        if alias in self._aliases:
            return self._aliases[alias]
        result = await self._request("GET", f"/chains/ethereum/addresses/{alias}", what=f"address {alias}")
        address = result.get("address") if isinstance(result, dict) else None
        if not isinstance(address, str) or not is_address(address):
            raise MultiBaasError(f"address {alias}: no address in the response", body=json.dumps(result, default=str)[:2000])
        self._aliases[alias] = to_checksum_address(address)
        return self._aliases[alias]

    async def health(self) -> tuple[bool, str]:
        if not self.configured:
            return False, "MB_URL or MB_ADMIN_API_KEY not set"
        try:
            status = await self._request("GET", "/chains/ethereum/status", what="chain status", retries=0, timeout=5.0)
        except MultiBaasError as exc:
            return False, str(exc)
        chain = status.get("chainID") if isinstance(status, dict) else None
        block = status.get("blockNumber") if isinstance(status, dict) else None
        if chain is not None and _hex_or_int(chain) != self._chain_id:
            return False, f"deployment is on chain {chain}, but CHAIN_ID is {self._chain_id}"
        return True, f"reachable, chain {chain}, block {block}"

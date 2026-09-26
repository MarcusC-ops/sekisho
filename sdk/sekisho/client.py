"""Async client for the Sekisho gate API (docs/api.md).

Error mapping, the same for every method:
- connect errors, timeouts, 5xx, and 2xx bodies that aren't a valid answer: SekishoUnavailable
- 4xx (e.g. 422 invalid_request, 404 not_found): SekishoRequestError

The x402 hooks treat any failure as HOLD (fail closed). Direct callers must do the same:
never ALLOW on a failed screen.
"""

from __future__ import annotations

from typing import Any, get_args

import httpx
from pydantic import ValidationError

from .errors import SekishoRequestError, SekishoUnavailable
from .models import Decision, Direction, Source

__all__ = ["SekishoClient"]

_USER_AGENT = "sekisho-sdk/0.1.0"


class SekishoClient:
    """One client per process is enough; it keeps a pooled httpx.AsyncClient.

    Usable as `async with SekishoClient(url) as sk: ...`, or call `aclose()` when done.
    """

    def __init__(self, base_url: str, timeout_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_s,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )

    # ------------------------------------------------------------------ screening

    async def screen(
        self,
        *,
        counterparty: str,
        direction: str,
        amount: str,
        asset: str,
        payment_chain_id: int,
        source: str,
        agent_id: str,
        purpose: str = "",
        resource: str = "",
        untrusted_context: str | None = None,
    ) -> Decision:
        """POST /v1/screen. Raises SekishoUnavailable on connect errors, timeouts and 5xx."""
        if direction not in get_args(Direction):
            raise ValueError(f"direction must be one of {get_args(Direction)}, got {direction!r}")
        if source not in get_args(Source):
            raise ValueError(f"source must be one of {get_args(Source)}, got {source!r}")
        body = {
            "counterparty": counterparty,
            "direction": direction,
            "amount": str(amount),
            "asset": asset,
            "payment_chain_id": int(payment_chain_id),
            "source": source,
            "agent_id": agent_id,
            "purpose": purpose,
            "resource": resource,
            "untrusted_context": untrusted_context,
        }
        data = await self._json("POST", "/v1/screen", json=body)
        return _decision(data)

    # ------------------------------------------------------------------ case updates

    async def report_payment(self, case_id: str, tx_hash: str, network: str) -> None:
        """POST /v1/cases/{id}/payment: the x402 settlement tx for an ALLOW case (status PAID)."""
        await self._request(
            "POST", f"/v1/cases/{case_id}/payment", json={"tx_hash": tx_hash, "network": network}
        )

    async def report_hold(self, case_id: str, hold_id: int, deposit_tx: str) -> None:
        """POST /v1/cases/{id}/hold: the escrow deposit for a HOLD case (status HELD_ESCROWED)."""
        await self._request(
            "POST",
            f"/v1/cases/{case_id}/hold",
            json={"hold_id": int(hold_id), "deposit_tx": deposit_tx},
        )

    # ------------------------------------------------------------------ reads

    async def get_case(self, case_id: str) -> dict[str, Any]:
        """GET /v1/cases/{id}: the full CaseDetail as a dict (404 raises SekishoRequestError)."""
        data = await self._json("GET", f"/v1/cases/{case_id}")
        if not isinstance(data, dict):
            raise SekishoUnavailable("gate returned a case that is not a JSON object")
        return data

    async def list_cases(self, limit: int = 10, **filters: Any) -> list[Decision]:
        """GET /v1/cases, newest first. Filters: verdict, status, direction, cursor."""
        params: dict[str, Any] = {"limit": limit}
        params.update({k: v for k, v in filters.items() if v is not None})
        data = await self._json("GET", "/v1/cases", params=params)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SekishoUnavailable("gate returned a case list without `items`")
        return [_decision(item) for item in items]

    async def policy(self) -> dict[str, Any]:
        """GET /v1/policy: `{"id", "version", "name", "yaml", "parsed"}`."""
        data = await self._json("GET", "/v1/policy")
        if not isinstance(data, dict):
            raise SekishoUnavailable("gate returned a policy that is not a JSON object")
        return data

    # ------------------------------------------------------------------ lifecycle

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> SekishoClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ internals

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.request(method, path, json=json, params=params)
        except httpx.TimeoutException as exc:
            raise SekishoUnavailable(
                f"gate at {self.base_url} timed out after {self.timeout_s:g}s ({type(exc).__name__})"
            ) from exc
        except httpx.HTTPError as exc:
            raise SekishoUnavailable(
                f"gate at {self.base_url} is unreachable ({type(exc).__name__}: {exc})"
            ) from exc

        status = response.status_code
        if status >= 500:
            code, message = _error_fields(response)
            raise SekishoUnavailable(
                f"gate error {status} {code}: {message}".rstrip(": "), status_code=status
            )
        if status >= 400:
            code, message = _error_fields(response)
            raise SekishoRequestError(status, code, message)
        if not 200 <= status < 300:
            raise SekishoUnavailable(f"gate answered with unexpected status {status}", status_code=status)
        return response

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._request(method, path, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SekishoUnavailable(f"gate returned a non-JSON body for {method} {path}") from exc


def _decision(data: Any) -> Decision:
    try:
        return Decision.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()[:5]
        )
        raise SekishoUnavailable(f"gate returned an invalid decision ({problems})") from exc


def _error_fields(response: httpx.Response) -> tuple[str, str]:
    """The gate's `{"error", "message"}` body, or the status text if the body is something else."""
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        code = str(data.get("error") or response.reason_phrase or "error")
        message = data.get("message")
        if message is None and "detail" in data:  # a FastAPI default error body
            message = data["detail"]
        return code, str(message if message is not None else "")
    return response.reason_phrase or "error", response.text[:200]

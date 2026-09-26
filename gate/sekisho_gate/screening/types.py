"""The result type every screening check returns, shared by the checks and the pipeline."""

from typing import Any, Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "error", "skipped"]


class CheckOutcome(BaseModel):
    """One check's result. `raw` goes into the hashed report verbatim (PRD 9.3), so it
    must be exactly what the upstream API returned; `data` is the parsed view the
    policy reads. Shapes of `data` by check name:

    - intercepta.quick_scan / intercepta.deep_scan:
        {"toxicScore": int, "traits": [{"name", "risk", "txsCount", "description"}]}
    - sanctions.oracle: {"1": bool | None, "8453": bool | None}  (None = that chain failed)
    - trace.source_of_funds: a TraceResult dict (PRD 9.5)
    - intercepta.impersonation: {"isAddressPoisoned": bool, "originalAddress": str | None}
    - intercepta.token: {"riskScore", "riskLevel", "trust", "action", "detectors"}
    """

    name: str
    status: CheckStatus
    live: bool | None = None  # True = fresh call, False = cache hit, None = not Intercepta
    latency_ms: int | None = None
    summary: str = ""
    error: str | None = None
    data: dict[str, Any] | None = None
    raw: Any = None

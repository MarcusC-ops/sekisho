"""Sekisho SDK: screen the counterparty before an AI agent pays or accepts an x402 payment.

    from sekisho import SekishoClient, payer_hook, payee_hook, CURRENT

Depends only on httpx and pydantic. The x402 hooks need the `x402` extra
(`pip install -e 'sdk[x402]'`), which is imported lazily, so this package imports without it.
"""

from .client import SekishoClient
from .errors import SekishoError, SekishoRequestError, SekishoUnavailable
from .models import (
    AnalystNote,
    Attestation,
    Check,
    Decision,
    Direction,
    Hold,
    PolicyRef,
    Reason,
    Source,
    Verdict,
)
from .x402_hooks import (
    CURRENT,
    abort_reason,
    parse_abort_reason,
    payee_hook,
    payer_hook,
    screen_payer,
    unwrap_payment_aborted,
)

__version__ = "0.1.0"

__all__ = [
    "SekishoClient",
    "SekishoUnavailable",
    "SekishoRequestError",
    "SekishoError",
    "Decision",
    "Reason",
    "Check",
    "Attestation",
    "AnalystNote",
    "Hold",
    "PolicyRef",
    "Verdict",
    "Direction",
    "Source",
    "payer_hook",
    "payee_hook",
    "screen_payer",
    "CURRENT",
    "parse_abort_reason",
    "abort_reason",
    "unwrap_payment_aborted",
]

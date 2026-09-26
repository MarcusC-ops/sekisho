"""Errors raised by the Sekisho SDK."""

from __future__ import annotations


class SekishoError(Exception):
    """Base class for every Sekisho SDK error."""


class SekishoUnavailable(SekishoError):
    """The gate gave no usable answer: connect error, timeout, 5xx, or a body the SDK can't read.

    Callers must fail closed. The x402 hooks turn this into HOLD, never ALLOW (AGENTS.md rule 3).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class SekishoRequestError(SekishoError):
    """The gate refused the request with a 4xx, e.g. 422 `invalid_request` or 404 `not_found`."""

    def __init__(self, status_code: int, error: str, message: str) -> None:
        super().__init__(f"{status_code} {error}: {message}")
        self.status_code = status_code
        self.error = error
        self.message = message

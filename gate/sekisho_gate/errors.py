"""API errors in the documented shape: {"error": "<Code>", "message": "<human text>"}."""

from __future__ import annotations


class GateError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def body(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}


def not_found(what: str) -> GateError:
    return GateError(404, "not_found", f"{what} not found")


def invalid_state(message: str) -> GateError:
    return GateError(409, "invalid_state", message)

"""Small, fail-closed authentication boundary for privileged operator actions."""

from secrets import compare_digest

from pydantic import SecretStr

from .errors import GateError


def require_operator(authorization: str | None, configured: SecretStr) -> None:
    expected = configured.get_secret_value()
    if not expected:
        raise GateError(503, "operator_unconfigured", "Operator actions are disabled until SEKISHO_OPERATOR_TOKEN is configured.")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not compare_digest(supplied.encode(), expected.encode()):
        raise GateError(401, "unauthorized", "A valid operator token is required.")

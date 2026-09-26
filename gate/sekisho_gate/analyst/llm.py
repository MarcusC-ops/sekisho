"""AI analyst (PRD 9.10): writes the case note. It never decides.

The note runs in the background after the verdict is returned and never touches the
verdict or the report hash. Provider switch: LLM_PROVIDER=anthropic|openai|none, both
SDKs behind `complete_json(system, user) -> dict`. On a timeout (8 s), invalid JSON, a
missing field, a missing key or LLM_PROVIDER=none, the gate writes a template note built
from the triggered rules (`provider: "template"`, `fallback: true`).

Counterparty-supplied text only ever appears inside <untrusted_context> tags.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from pydantic import ValidationError

from ..checks import IMPERSONATION, ORACLE, QUICK_SCAN, TOKEN, TRACE
from ..logs import get_logger
from ..models import AnalystNote, AnalystOutput
from ..util import iso
from .prompts import SYSTEM_PROMPT, USER_TEMPLATE

log = get_logger("sekisho.analyst")

# The one place model ids live: the default when LLM_MODEL is empty.
DEFAULT_MODELS = {"anthropic": "claude-haiku-4-5", "openai": "gpt-5-mini"}
LLM_TIMEOUT_S = 8.0
MAX_OUTPUT_TOKENS = 2000
ANTHROPIC_API_URL = "https://api.anthropic.com"
OPENAI_API_URL = "https://api.openai.com/v1"

_UNTRUSTED_TAG = re.compile(r"<\s*(/?)\s*untrusted_context\s*>", re.IGNORECASE)


class LLMError(Exception):
    """Any reason the LLM could not produce a usable note."""


class LLMClient:
    """Thin async wrapper over the Anthropic and OpenAI SDKs."""

    def __init__(self, settings: Any):
        self.provider: str = settings.llm_provider
        self.model: str | None = (settings.llm_model or DEFAULT_MODELS.get(self.provider)) or None
        if self.provider == "anthropic":
            self._key = settings.anthropic_api_key.get_secret_value()
        elif self.provider == "openai":
            self._key = settings.openai_api_key.get_secret_value()
        else:
            self._key = ""
        self._client: Any = None

    @property
    def configured(self) -> bool:
        return self.provider in ("anthropic", "openai") and bool(self._key) and bool(self.model)

    def status(self) -> tuple[bool, str]:
        if self.provider == "none":
            return True, "LLM_PROVIDER=none: template notes"
        if not self._key:
            env = "ANTHROPIC_API_KEY" if self.provider == "anthropic" else "OPENAI_API_KEY"
            return False, f"{env} not set: template notes only"
        return True, f"{self.provider} {self.model}"

    def _get_client(self) -> Any:
        if self._client is None:
            # Only the gate's own settings are used: its configured key and the public API
            # endpoints (no ambient ANTHROPIC_BASE_URL / OPENAI_BASE_URL or profile lookup).
            if self.provider == "anthropic":
                import anthropic

                self._client = anthropic.AsyncAnthropic(
                    api_key=self._key, base_url=ANTHROPIC_API_URL, timeout=LLM_TIMEOUT_S, max_retries=0
                )
            else:
                import openai

                self._client = openai.AsyncOpenAI(
                    api_key=self._key, base_url=OPENAI_API_URL, timeout=LLM_TIMEOUT_S, max_retries=0
                )
        return self._client

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        if not self.configured:
            raise LLMError(self.status()[1])
        client = self._get_client()
        if self.provider == "anthropic":
            resp = await client.messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            if resp.stop_reason == "refusal":
                raise LLMError("model refused")
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        else:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
                "max_completion_tokens": MAX_OUTPUT_TOKENS * 2,
            }
            if str(self.model).startswith(("gpt-5", "o1", "o3", "o4")):
                kwargs["reasoning_effort"] = "low"
            resp = await client.chat.completions.create(**kwargs)
            text = (resp.choices[0].message.content or "") if resp.choices else ""
        return extract_json(text)

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # pragma: no cover - best effort
                pass


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text (tolerates code fences and stray prose)."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        value = json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start < 0 or end <= start:
            raise LLMError("no JSON object in the model output") from None
        try:
            value = json.loads(s[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"invalid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise LLMError("model output is not a JSON object")
    return value


def neutralise_untrusted(text: str) -> str:
    """Stop counterparty text from closing or re-opening the <untrusted_context> block."""
    return _UNTRUSTED_TAG.sub(lambda m: f"[{m.group(1)}untrusted_context]", text)


# ---------- the analyst ----------


def _check(case: dict[str, Any], name: str) -> dict[str, Any] | None:
    for c in case.get("checks") or []:
        if c.get("name") == name:
            return c
    return None


def _fmt_bool(value: Any) -> str:
    return "true" if value is True else "false" if value is False else "unavailable"


def _fmt_usd(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "unavailable"


def _outcome_text(check: dict[str, Any] | None, ok_text: str) -> str:
    if check is None:
        return "not run"
    if check.get("status") == "ok":
        return ok_text
    detail = check.get("error") or check.get("summary") or ""
    return f"{check.get('status')}" + (f" ({detail})" if detail else "")


def build_user_message(case: dict[str, Any], policy: Any) -> str:
    """Fill the Appendix E.2 template from a CaseDetail dict."""
    evidence = case.get("evidence") or {}
    qs_check = _check(case, QUICK_SCAN)
    qs = evidence.get("quick_scan") or {}
    if qs_check and qs_check.get("status") == "ok":
        live_or_cached = "live" if qs_check.get("live") else "cached"
    else:
        live_or_cached = qs_check.get("status", "not run") if qs_check else "not run"
    traits = [
        {k: t.get(k) for k in ("name", "risk", "txsCount", "description", "class")}
        for t in qs.get("traits") or []
        if isinstance(t, dict)
    ]
    oracle = evidence.get("oracle") or {}
    trace = case.get("trace") or {}
    trace_check = _check(case, TRACE)
    imp = evidence.get("impersonation") or {}
    tok = evidence.get("token_scan") or {}
    failed = [
        f"{c['name']} ({c.get('error') or c.get('summary') or c['status']})"
        for c in case.get("checks") or []
        if c.get("status") == "error"
    ]
    untrusted = case.get("untrusted_context")
    chain_names = {1: "Ethereum", 8453: "Base"}
    fields = {
        "verdict": case["verdict"],
        "risk_score": case["risk_score"],
        "policy_name": policy.name,
        "policy_version": policy.version,
        "policy_id": policy.id,
        "triggered_rules": ", ".join(case["policy"]["triggered_rules"]) or "none",
        "direction": case["direction"],
        "direction_help": "we pay them" if case["direction"] == "outbound" else "they pay us",
        "amount_usd": f"{float(case.get('amount_usd') or 0):g}",
        "purpose": case.get("purpose") or "not given",
        "live_or_cached": live_or_cached,
        "ms": qs_check.get("latency_ms") if qs_check and qs_check.get("latency_ms") is not None else "n/a",
        "toxic_score": qs.get("toxicScore", "unavailable") if qs else "unavailable",
        "traits_json": json.dumps(traits, ensure_ascii=False),
        "eth_result": _fmt_bool(oracle.get("1")),
        "base_result": _fmt_bool(oracle.get("8453")),
        "inbound_usd": _fmt_usd(trace.get("inbound_usd_traced")) if trace else "unavailable",
        "chains": ", ".join(chain_names.get(c, str(c)) for c in trace.get("chains") or []) or "none",
        "taint_pct": trace.get("taint_pct", "unavailable") if trace else "unavailable",
        "paths": "; ".join(trace.get("paths") or []) or ("none" if trace else _outcome_text(trace_check, "none")),
        "impersonation": _outcome_text(
            _check(case, IMPERSONATION),
            f"isAddressPoisoned={_fmt_bool(imp.get('isAddressPoisoned'))}"
            + (f", originalAddress={imp.get('originalAddress')}" if imp.get("originalAddress") else ""),
        ),
        "token_scan": _outcome_text(
            _check(case, TOKEN),
            ", ".join(f"{k}={tok.get(k)}" for k in ("action", "riskLevel", "riskScore", "trust") if k in tok)
            or "no data",
        ),
        "failed_checks_or_none": "; ".join(failed) or "none",
        "untrusted_context_or_none": neutralise_untrusted(untrusted) if untrusted else "none",
    }
    # The oracle has its own failure line when it errored entirely.
    oracle_check = _check(case, ORACLE)
    if oracle_check and oracle_check.get("status") != "ok" and not oracle:
        fields["eth_result"] = fields["base_result"] = "unavailable"
    return USER_TEMPLATE.format(**fields)


def template_note(case: dict[str, Any], why: str | None = None) -> dict[str, Any]:
    """Deterministic note from the triggered rules (no LLM)."""
    verdict = case["verdict"]
    direction = case["direction"]
    rules = case["policy"]["triggered_rules"]
    findings = []
    for r in case.get("reasons") or []:
        if len(findings) >= 5:
            break
        if r.get("source") == "intercepta" and str(r.get("rule", "")).startswith(("hard_block_trait:", "hold_trait:")):
            text = f'Intercepta trait {r["label"]}: "{r["detail"]}"'
        else:
            text = f"{r['label']}: {r['detail']}"
        findings.append({"text": text, "evidence": [r["evidence_id"]] if r.get("evidence_id") else []})
    for c in case.get("checks") or []:
        if len(findings) >= 5:
            break
        if c.get("status") == "error":
            findings.append(
                {"text": f"Check {c['name']} failed: {c.get('error') or 'no detail'}.",
                 "evidence": [c["evidence_id"]] if c.get("evidence_id") else []}
            )
    failed = [c["name"] for c in case.get("checks") or [] if c.get("status") == "error"]
    summary = (
        f"Policy returned {verdict} with risk score {case['risk_score']}. "
        f"Rules triggered: {', '.join(rules) if rules else 'none'}."
    )
    if failed:
        summary += f" Failed checks: {', '.join(failed)}."
    if verdict == "ALLOW":
        owner = "Payment allowed: no blocking or holding rule triggered."
    elif verdict == "HOLD":
        owner = (
            "Payment held for compliance review; a compliance officer will release or refund it."
            if direction == "outbound"
            else "Incoming payment refused for now and held for compliance review."
        )
    else:
        owner = (
            "Payment blocked: no signature was produced."
            if direction == "outbound"
            else "Incoming payment refused: the payer did not pass screening."
        )
    return {
        "headline": case["headline"],
        "summary": summary,
        "key_findings": findings,
        "owner_message": owner,
        "officer_recommendation": "n/a",
        "recommendation_rationale": "Template note (no model review"
        + (f": {why}" if why else "")
        + "). The officer decides from the evidence.",
        "agrees_with_policy": True,
        "provider": "template",
        "model": None,
        "fallback": True,
        "generated_at": iso(),
    }


class Analyst:
    def __init__(self, llm: LLMClient | None, policy: Any, timeout_s: float = LLM_TIMEOUT_S):
        self.llm = llm
        self.policy = policy
        self.timeout_s = timeout_s

    async def note(self, case: dict[str, Any]) -> dict[str, Any]:
        """An AnalystNote dict for a CaseDetail dict. Never raises."""
        if self.llm is None or not self.llm.configured:
            why = self.llm.status()[1] if self.llm is not None else "no LLM configured"
            return template_note(case, why)
        try:
            user = build_user_message(case, self.policy)
            raw = await asyncio.wait_for(self.llm.complete_json(SYSTEM_PROMPT, user), self.timeout_s)
            if isinstance(raw.get("officer_recommendation"), str):
                raw["officer_recommendation"] = raw["officer_recommendation"].strip().lower()
            out = AnalystOutput.model_validate(raw)
        except asyncio.TimeoutError:
            log.warning("analyst timed out", extra={"timeout_s": self.timeout_s})
            return template_note(case, f"LLM timed out after {self.timeout_s:g} s")
        except ValidationError as exc:
            log.warning("analyst output failed validation", extra={"errors": exc.error_count()})
            return template_note(case, "LLM output did not match the schema")
        except LLMError as exc:
            log.warning("analyst unusable output", extra={"error": str(exc)})
            return template_note(case, str(exc))
        except Exception as exc:  # SDK/network errors
            log.warning("analyst call failed", extra={"error": f"{type(exc).__name__}: {exc}"})
            return template_note(case, f"LLM call failed ({type(exc).__name__})")
        note = AnalystNote(
            **out.model_dump(),
            provider=self.llm.provider,
            model=self.llm.model,
            fallback=False,
            generated_at=iso(),
        )
        return note.model_dump(mode="json")

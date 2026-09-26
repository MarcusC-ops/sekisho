"""C3 Treasury Agent (PRD 10.3): an LLM tool-calling loop over the three treasury tools.

Run: make agent   (.venv/bin/python agents/treasury/agent.py [--provider anthropic|openai]
                   [--model MODEL] [--task TEXT])

The model picks vendors and writes the FX note. It decides nothing about compliance: every
payment is screened inside the tool code (tools.py), so this loop holds no screening logic
and has no way to skip it. Vendor responses reach the model inside
<untrusted_vendor_content> tags, and the loop stops after MAX_STEPS model calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.treasury.prompts import SYSTEM_PROMPT, TASK_PROMPT, TOOL_DESCRIPTIONS  # noqa: E402
from agents.treasury.tools import Style, TreasuryTools, build_treasury_tools, short_addr  # noqa: E402

MAX_STEPS = 8
MAX_TOKENS = 16000
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5", "openai": "gpt-5.5"}  # LLM_MODEL overrides

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_vendors": {"type": "object", "properties": {}, "additionalProperties": False},
    "buy_data": {
        "type": "object",
        "properties": {
            "vendor_id": {"type": "string", "description": "Vendor id from list_vendors"},
            "pair": {"type": "string", "description": "Currency pair, e.g. ETH-JPY"},
        },
        "required": ["vendor_id", "pair"],
        "additionalProperties": False,
    },
    "pay_invoice": {
        "type": "object",
        "properties": {
            "pay_to": {"type": "string", "description": "Payee wallet address (0x…)"},
            "amount_usd": {"type": "number", "description": "Amount in USD, paid in USDC"},
            "memo": {"type": "string", "description": "Invoice reference"},
        },
        "required": ["pay_to", "amount_usd", "memo"],
        "additionalProperties": False,
    },
}

_TAG = re.compile(r"<\s*/?\s*untrusted_vendor_content[^>]*>", re.IGNORECASE)
# Stops where the turn's tool calls may be truncated or withheld: never execute them.
HALT_STOPS = {"max_tokens", "refusal", "length", "content_filter"}


def render_for_model(result: Any) -> str:
    """Tool result as text for the model. Vendor text goes inside <untrusted_vendor_content>
    tags, with any tag of that name in the vendor text removed so it can't close the block."""
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, default=str)
    content = result.get("vendor_content")
    public = {k: v for k, v in result.items() if k not in ("vendor_content", "data")}
    text = json.dumps(public, ensure_ascii=False, default=str)
    if content:
        vendor = re.sub(r"[^a-z0-9-]", "", str(result.get("vendor_id") or "vendor").lower()) or "vendor"
        safe = _TAG.sub("[tag removed]", str(content))
        text += f'\n<untrusted_vendor_content vendor="{vendor}">\n{safe}\n</untrusted_vendor_content>'
    return text


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any] | None  # None: the model sent arguments that aren't valid JSON


@dataclass
class Turn:
    text: str
    calls: list[ToolCall]
    stop: str | None = None


@dataclass
class AgentRun:
    final_text: str
    steps: int
    finished: bool
    tool_calls: list[str] = field(default_factory=list)


class AnthropicChat:
    """Messages API with client tools, manual loop (anthropic 1.x)."""

    name = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, client: Any = None):
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=api_key or None)
        self.client, self.model = client, model
        self.tools = [{"name": n, "description": TOOL_DESCRIPTIONS[n], "input_schema": s}
                      for n, s in TOOL_SCHEMAS.items()]
        self.messages: list[dict[str, Any]] = []

    def start(self, task: str) -> None:
        self.messages = [{"role": "user", "content": task}]

    async def step(self) -> Turn:
        resp = await self.client.messages.create(
            model=self.model, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
            tools=self.tools, messages=self.messages,
        )
        # Keep the full content (thinking and tool_use blocks) for the next turn.
        self.messages.append({"role": "assistant", "content": resp.content})
        text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input) if isinstance(b.input, dict) else None)
                 for b in resp.content if getattr(b, "type", None) == "tool_use"]
        return Turn(text=text, calls=calls, stop=resp.stop_reason)

    def add_results(self, results: list[tuple[ToolCall, str, bool]]) -> None:
        # Every tool_result goes back in one user message.
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call.id, "content": text, "is_error": is_error}
            for call, text, is_error in results
        ]})


class OpenAIChat:
    """Chat Completions with function tools."""

    name = "openai"

    def __init__(self, model: str, api_key: str | None = None, client: Any = None):
        if client is None:
            import openai

            client = openai.AsyncOpenAI(api_key=api_key or None)
        self.client, self.model = client, model
        self.tools = [{"type": "function", "function": {"name": n, "description": TOOL_DESCRIPTIONS[n],
                                                        "parameters": s}}
                      for n, s in TOOL_SCHEMAS.items()]
        self.messages: list[dict[str, Any]] = []

    def start(self, task: str) -> None:
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": task}]

    async def step(self) -> Turn:
        resp = await self.client.chat.completions.create(
            model=self.model, messages=self.messages, tools=self.tools, max_completion_tokens=MAX_TOKENS,
        )
        choice = resp.choices[0]
        msg = choice.message
        entry: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        calls: list[ToolCall] = []
        tool_calls = [tc for tc in (msg.tool_calls or []) if getattr(tc, "function", None) is not None]
        if tool_calls:
            entry["tool_calls"] = [{"id": tc.id, "type": "function",
                                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                   for tc in tool_calls]
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except ValueError:
                    args = None
                calls.append(ToolCall(tc.id, tc.function.name, args if isinstance(args, dict) else None))
        self.messages.append(entry)
        return Turn(text=msg.content or "", calls=calls, stop=choice.finish_reason)

    def add_results(self, results: list[tuple[ToolCall, str, bool]]) -> None:
        for call, text, _ in results:
            self.messages.append({"role": "tool", "tool_call_id": call.id, "content": text})


def make_chat(provider: str, model: str | None, settings: Any) -> AnthropicChat | OpenAIChat:
    if provider not in DEFAULT_MODELS:
        raise SystemExit(f"LLM_PROVIDER={provider!r}: the Treasury Agent needs anthropic or openai "
                         "(scripted scenarios run without an LLM: make demo S=S1)")
    model = model or DEFAULT_MODELS[provider]
    if provider == "anthropic":
        return AnthropicChat(model, settings.anthropic_api_key.get_secret_value())
    return OpenAIChat(model, settings.openai_api_key.get_secret_value())


def _fmt_args(args: dict[str, Any] | None) -> str:
    if args is None:
        return "<invalid JSON>"
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())


async def run_agent(task: str, *, tools: TreasuryTools, chat: Any, emit: Callable[[str], None],
                    max_steps: int = MAX_STEPS) -> AgentRun:
    """One agent run: at most `max_steps` model calls, tools run in order as the model asks."""
    chat.start(task)
    called: list[str] = []
    for step in range(1, max_steps + 1):
        emit(f"[LLM] step {step}/{max_steps} · {chat.name} {chat.model}")
        turn = await chat.step()
        if turn.stop in HALT_STOPS:
            emit(f"[LLM] The model stopped ({turn.stop}); its tool calls, if any, are not run.")
            return AgentRun(final_text=turn.text.strip(), steps=step, finished=False, tool_calls=called)
        if not turn.calls:
            return AgentRun(final_text=turn.text.strip(), steps=step, finished=True, tool_calls=called)
        if turn.text.strip():
            emit(f"[LLM] {turn.text.strip().splitlines()[0][:160]}")
        results: list[tuple[ToolCall, str, bool]] = []
        for call in turn.calls:
            emit(f"[LLM] → {call.name}({_fmt_args(call.args)})")
            called.append(call.name)
            if call.args is None:
                results.append((call, json.dumps({"status": "error", "reason": "arguments were not valid JSON"}), True))
                continue
            try:
                result = await tools.call(call.name, call.args)
            except Exception as exc:  # noqa: BLE001 - report to the model, keep the loop alive
                results.append((call, json.dumps({"status": "error", "reason": f"{type(exc).__name__}: {exc}"}), True))
                continue
            is_error = isinstance(result, dict) and result.get("status") == "error"
            results.append((call, render_for_model(result), is_error))
        chat.add_results(results)
    emit(f"[AGENT] Stopped after {max_steps} model calls (step cap).")
    return AgentRun(final_text="", steps=max_steps, finished=False, tool_calls=called)


def attempt_lines(tools: TreasuryTools, style: Style) -> list[str]:
    """One line per payment attempt: verdict, counterparty, amount, outcome, case id."""
    lines = []
    for a in tools.attempts:
        verdict = str(a.get("verdict") or "-")
        who = a.get("vendor_id") or short_addr(a.get("pay_to"))
        amount = f"{a['amount_usd']:.2f} USDC" if isinstance(a.get("amount_usd"), float) else "?"
        colour = Style.VERDICT.get(verdict, "0")
        lines.append(f"  {style.paint(verdict.ljust(5), colour)}  {a['tool']:<11} {who:<18} {amount:>10}  "
                     f"{a.get('status', '?'):<17} case {a.get('case_id') or '-'}")
    return lines


async def _main(args: argparse.Namespace) -> int:
    from sekisho_gate.config import get_settings

    settings = get_settings()
    provider = args.provider or settings.llm_provider
    chat = make_chat(provider, args.model or settings.llm_model or None, settings)
    style = Style()
    tools = build_treasury_tools(settings, style=style)
    emit = tools.emit
    emit(f"[AGENT] Treasury Desk Agent · wallet {short_addr(tools.buyer.address)} · gate {settings.sekisho_url}")
    try:
        run = await run_agent(args.task, tools=tools, chat=chat, emit=emit, max_steps=args.max_steps)
    finally:
        await tools.aclose()
    if run.final_text:
        emit("[AGENT] Final answer:")
        for line in run.final_text.splitlines():
            emit(f"  {line}")
    emit("[AGENT] Payment attempts (from the tool log, not the model):")
    for line in attempt_lines(tools, style) or ["  none"]:
        emit(line)
    return 0 if run.finished else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Treasury Desk Agent once (LLM + x402).")
    parser.add_argument("--provider", choices=sorted(DEFAULT_MODELS), help="default: LLM_PROVIDER")
    parser.add_argument("--model", help=f"default: LLM_MODEL, else {DEFAULT_MODELS}")
    parser.add_argument("--task", default=TASK_PROMPT, help="the treasury team's request")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS)
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())

"""Pre-demo smoke test (PRD 12, PITCH_PLAN 7): a ✓/✗ checklist, non-zero exit on any ✗.

    make smoke     (.venv/bin/python scripts/smoke.py)

Checks: gate /healthz green with the oracle self-test true; Intercepta quota remaining
> 150; wallet balances and the escrow allowance; a MultiBaas webhook received in the last
10 minutes; PUBLIC_GATE_URL set and DEMO_MODE on; dashboard fixtures off; vendors up.
Read-only: it never signs or sends anything (make demo-setup tops up the allowance).
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from agents.treasury.tools import Style, load_vendors  # noqa: E402
from scripts.demo import Check, Demo, Result, Rpc, allowance_check, balance_checks, parse_time  # noqa: E402

MIN_QUOTA_REMAINING = 150
WEBHOOK_MAX_AGE_S = 600
DASHBOARD = ROOT / "dashboard"


async def health_checks(gate: httpx.AsyncClient) -> tuple[list[Check], dict[str, Any] | None]:
    try:
        health = (await gate.get("/healthz", timeout=10.0)).json()
    except Exception as exc:  # noqa: BLE001
        return [Check("gate /healthz reachable", False, f"{type(exc).__name__}: {exc} (make gate)")], None
    checks = [Check(f"gate /healthz status {health.get('status')}", health.get("status") == "ok",
                    "every health check must pass")]
    for name, item in (health.get("checks") or {}).items():
        if isinstance(item, dict):
            checks.append(Check(f"  {name}: {item.get('detail')}", bool(item.get("ok"))))
    oracle = (health.get("checks") or {}).get("oracle_self_test") or {}
    checks.append(Check("oracle self-test true", oracle.get("ok") is True, str(oracle.get("detail"))))
    return checks, health


async def quota_check(gate: httpx.AsyncClient) -> Check:
    try:
        quota = (await gate.get("/v1/quota", timeout=10.0)).json()
        remaining = int(quota["remaining"])
    except Exception as exc:  # noqa: BLE001
        return Check("Intercepta quota readable", False, f"{type(exc).__name__}: {exc}")
    return Check(f"Intercepta quota remaining {remaining} (need > {MIN_QUOTA_REMAINING})",
                 remaining > MIN_QUOTA_REMAINING, f"{quota.get('used')}/{quota.get('quota')} used")


async def webhook_check(gate: httpx.AsyncClient, now: datetime | None = None) -> Check:
    try:
        items = (await gate.get("/v1/audit", params={"limit": 1}, timeout=10.0)).json().get("items") or []
    except Exception as exc:  # noqa: BLE001
        return Check("chain events readable (/v1/audit)", False, f"{type(exc).__name__}: {exc}")
    if not items:
        return Check("MultiBaas webhook received in the last 10 min", False,
                     "no chain events yet: check the tunnel and make setup-multibaas")
    received = parse_time(items[0].get("received_at"))
    if received is None:
        return Check("MultiBaas webhook received in the last 10 min", False, "latest event has no received_at")
    age = ((now or datetime.now(UTC)) - received).total_seconds()
    return Check(f"MultiBaas webhook received {int(age // 60)} min ago ({items[0].get('name')})",
                 age <= WEBHOOK_MAX_AGE_S, "older than 10 min: run any scenario, then check the tunnel URL")


def config_checks(settings: Any, health: dict[str, Any] | None) -> list[Check]:
    url = settings.public_gate_url.strip()
    checks = [Check(f"PUBLIC_GATE_URL set ({url or 'empty'})", bool(url) and "<" not in url,
                    "cloudflared tunnel URL, registered in the MultiBaas webhook")]
    gate_demo = None if health is None else health.get("demo_mode")
    checks.append(Check("DEMO_MODE on", settings.demo_mode is True and gate_demo is not False,
                        f".env {settings.demo_mode}, gate {gate_demo}"))
    return checks


def fixtures_check(dashboard: Path = DASHBOARD) -> Check:
    """Fixtures are on only when NEXT_PUBLIC_USE_FIXTURES is exactly "true" (dashboard/lib/config.ts)."""
    offenders = []
    if os.environ.get("NEXT_PUBLIC_USE_FIXTURES", "").strip() == "true":
        offenders.append("environment")
    for path in sorted(dashboard.glob(".env*")):
        if path.name.endswith(".example") or not path.is_file():
            continue
        for line in path.read_text(errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip().removeprefix("export ").strip() == "NEXT_PUBLIC_USE_FIXTURES" and \
                    value.split("#")[0].strip().strip("\"'") == "true":
                offenders.append(path.name)
    return Check("dashboard fixtures off", not offenders, "NEXT_PUBLIC_USE_FIXTURES=true in " + ", ".join(offenders))


async def vendor_checks(http: httpx.AsyncClient) -> list[Check]:
    checks = []
    for vendor in load_vendors():
        base = vendor["url"].split("/v1/")[0]
        try:
            ok = (await http.get(f"{base}/healthz", timeout=5.0)).status_code == 200
            detail = ""
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__} (make vendors)"
        checks.append(Check(f"vendor {vendor['id']} up at {base}", ok, detail))
    return checks


async def run_smoke(demo: Demo, http: httpx.AsyncClient) -> Result:
    s = demo.settings
    checks, health = await health_checks(demo.gate)
    checks.append(await quota_check(demo.gate))
    rpc = Rpc(s.contracts_rpc_url, http)
    checks += await balance_checks(s, rpc)
    checks.append(await allowance_check(demo, rpc, approve=False))
    checks.append(await webhook_check(demo.gate))
    checks += config_checks(s, health)
    checks.append(fixtures_check())
    checks += await vendor_checks(http)
    return Result("smoke", "Pre-demo smoke test", checks)


async def amain() -> int:
    from sekisho_gate.config import get_settings

    settings = get_settings()
    style = Style()
    demo = Demo(settings, None, style=style)  # type: ignore[arg-type]
    demo.emit(style.bold(f"━━ Sekisho smoke test · gate {settings.sekisho_url} ━━"))
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            result = await run_smoke(demo, http)
    finally:
        await demo.aclose()
    for check in result.checks:
        mark = style.paint("✓", "32") if check.ok else style.paint("✗", "31")
        tail = f"  ({check.detail})" if check.detail and not check.ok else ""
        demo.emit(f"{mark} {check.name}{tail}")
    failed = sum(not c.ok for c in result.checks)
    word = style.paint("SMOKE PASS", "1;32") if not failed else style.paint(f"SMOKE FAIL ({failed} failed)", "1;31")
    demo.emit(f"{word} · {len(result.checks) - failed}/{len(result.checks)} checks")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))

"""Start the four vendor agents from PRD 10.2 (`make vendors`) with prefixed log lines.

    vendor-clean       Kabuto Market Data  :4021  VENDOR_CLEAN_PAYTO       normal     S1, S5
    vendor-mixer       Nightowl Analytics  :4022  VENDOR_MIXER_PAYTO       normal     S2
    vendor-sanctioned  Ronin Signals       :4023  VENDOR_SANCTIONED_PAYTO  normal     S3
    vendor-injection   Oracle Feeds Pro    :4024  VENDOR_CLEAN_PAYTO       injection  S4

All four vendors are fictional. A vendor whose payTo is empty in .env is not started, and
the others still are. Ctrl-C (or SIGTERM) stops every child.

    .venv/bin/python agents/vendors/run_all.py [--only vendor-clean kabuto ...]
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
APP = HERE / "app.py"
REPO_ROOT = HERE.parents[1]
SHUTDOWN_GRACE_S = 5.0


@dataclass(frozen=True)
class VendorSpec:
    vendor_id: str
    alias: str
    name: str
    port: int
    payto_setting: str  # the Settings attribute (and .env name, upper-cased)
    mode: str
    scenarios: str


VENDORS: tuple[VendorSpec, ...] = (
    VendorSpec("vendor-clean", "kabuto", "Kabuto Market Data", 4021, "vendor_clean_payto", "normal", "S1, S5"),
    VendorSpec("vendor-mixer", "nightowl", "Nightowl Analytics", 4022, "vendor_mixer_payto", "normal", "S2"),
    VendorSpec("vendor-sanctioned", "ronin-signals", "Ronin Signals", 4023, "vendor_sanctioned_payto",
               "normal", "S3"),
    VendorSpec("vendor-injection", "oracle-feeds", "Oracle Feeds Pro", 4024, "vendor_clean_payto",
               "injection", "S4"),
)


Planned = list[tuple[VendorSpec, str]]


def plan(settings: Any, only: list[str] | None = None) -> tuple[Planned, Planned]:
    """Split VENDORS into [(spec, pay_to)] to start and [(spec, why)] skipped."""
    to_start: Planned = []
    skipped: Planned = []
    wanted = {name.lower() for name in only or []}
    for spec in VENDORS:
        if wanted and spec.vendor_id not in wanted and spec.alias not in wanted:
            continue
        pay_to = str(getattr(settings, spec.payto_setting, "") or "").strip()
        if pay_to:
            to_start.append((spec, pay_to))
        else:
            skipped.append((spec, f"{spec.payto_setting.upper()} is empty in .env"))
    return to_start, skipped


def child_env(spec: VendorSpec, pay_to: str, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update(
        VENDOR_ID=spec.vendor_id,
        VENDOR_NAME=spec.name,
        PAY_TO=pay_to,
        MODE=spec.mode,
        PORT=str(spec.port),
        PYTHONUNBUFFERED="1",
    )
    env.setdefault("PRICE", "$0.05")
    return env


def _pump(proc: subprocess.Popen[str], prefix: str) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"{prefix}{line.rstrip()}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the fictional vendor agents (PRD 10.2)")
    parser.add_argument("--only", nargs="+", metavar="VENDOR", help="vendor ids or aliases to start")
    args = parser.parse_args(argv)

    from sekisho_gate.config import get_settings

    to_start, skipped = plan(get_settings(), args.only)
    for spec, why in skipped:
        print(f"[run_all] NOT starting {spec.vendor_id} ({spec.name}, :{spec.port}, {spec.scenarios}): "
              f"{why}. Set it and restart; scripts/scan_candidates.py picks the S2 address.",
              file=sys.stderr, flush=True)
    if not to_start:
        print("[run_all] no vendor to start", file=sys.stderr)
        return 1

    width = max(len(spec.vendor_id) for spec, _ in to_start)
    children: list[tuple[VendorSpec, subprocess.Popen[str], threading.Thread]] = []
    for spec, pay_to in to_start:
        proc = subprocess.Popen(
            [sys.executable, str(APP)],
            cwd=REPO_ROOT,
            env=child_env(spec, pay_to),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,  # Ctrl-C reaches only us; we stop the children in order
        )
        prefix = f"[{spec.vendor_id:<{width}} :{spec.port}] "
        pump = threading.Thread(target=_pump, args=(proc, prefix), daemon=True)
        pump.start()
        children.append((spec, proc, pump))
        print(f"[run_all] started {spec.vendor_id} ({spec.name}) on :{spec.port}, mode {spec.mode}, "
              f"payTo {pay_to}, pid {proc.pid}", flush=True)

    stop = threading.Event()

    def request_stop(signum: int, _frame: Any) -> None:
        stop.set()

    # Set SIGINT explicitly: a background job can inherit it as ignored, and then Python
    # never raises KeyboardInterrupt.
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, request_stop)

    exited: dict[str, int] = {}  # vendors that stopped on their own (crash, port in use, ...)
    try:
        while not stop.is_set() and len(exited) < len(children):
            for spec, proc, _ in children:
                code = proc.poll()
                if code is not None and spec.vendor_id not in exited:
                    exited[spec.vendor_id] = code
                    print(f"[run_all] {spec.vendor_id} exited with code {code}", file=sys.stderr, flush=True)
            stop.wait(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown(children)
    return 1 if any(code != 0 for code in exited.values()) else 0


def _shutdown(children: list[tuple[VendorSpec, subprocess.Popen[str], threading.Thread]]) -> None:
    alive = [(spec, proc) for spec, proc, _ in children if proc.poll() is None]
    if alive:
        print(f"[run_all] stopping {len(alive)} vendor(s)", flush=True)
    for _, proc in alive:
        proc.terminate()  # SIGTERM: uvicorn shuts down gracefully
    deadline = time.monotonic() + SHUTDOWN_GRACE_S
    for spec, proc in alive:
        try:
            proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            print(f"[run_all] {spec.vendor_id} did not stop in {SHUTDOWN_GRACE_S:g}s, killing it", flush=True)
            proc.kill()
            proc.wait()
    for _, _, pump in children:
        pump.join(timeout=1.0)


if __name__ == "__main__":
    sys.exit(main())

"""Single-container trial stack: internal gate/vendors, public limited runner only.

No payments run at startup. The public runner is disabled unless explicitly configured.
Use one container with durable /data; the operator control API is not started.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def commands() -> list[list[str]]:
    return [
        [sys.executable, "-m", "uvicorn", "sekisho_gate.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1"],
        [sys.executable, "agents/vendors/run_all.py", "--only", "vendor-clean", "vendor-sanctioned"],
        [sys.executable, "-m", "uvicorn", "agents.treasury.public_trial:create_app", "--factory", "--host", "0.0.0.0", "--port", os.getenv("PORT", "8200"), "--workers", "1", "--no-access-log"],
    ]


def main() -> int:
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    children: list[subprocess.Popen] = []
    failed = False
    try:
        for command in commands():
            children.append(subprocess.Popen(command, cwd=ROOT))
        while not stop.wait(0.5):
            if any(child.poll() is not None for child in children):
                failed = True
                break
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

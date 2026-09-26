"""C8 treasury control API (docs/api.md, P1): the console's demo bar runs scenarios here.

    make control     (.venv/bin/python agents/treasury/control.py, http://127.0.0.1:8100)

    POST /run        {"scenario": "S1".."S6" or "all"} -> {"run_id"}, or 409 while a run is in progress
    GET  /runs/{id}  {"run_id", "scenario", "status": "running" | "succeeded" | "failed",
                      "lines": [string], "started_at", "finished_at"}

Each run is `scripts/demo.py <scenario>` in a subprocess, with its output captured line by
line (no colours). One run at a time. CORS allows CONSOLE_ORIGIN.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import secrets
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from sekisho_gate.auth import require_operator
from sekisho_gate.config import get_settings
from sekisho_gate.errors import GateError
from pydantic import BaseModel, SecretStr  # noqa: E402

HOST, PORT = "127.0.0.1", 8100
DEMO_SCRIPT = ROOT / "scripts" / "demo.py"
MAX_LINES = 5000  # per run
MAX_RUNS = 50  # finished runs kept in memory
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

Scenario = Literal["S1", "S2", "S3", "S4", "S5", "S6", "all"]


class RunRequest(BaseModel):
    scenario: Scenario


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def demo_command(scenario: str) -> list[str]:
    return [sys.executable, "-u", str(DEMO_SCRIPT), scenario]


def error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": code, "message": message, **extra}, status_code=status)


class Run:
    def __init__(self, scenario: str):
        self.run_id = "run_" + secrets.token_hex(6)
        self.scenario = scenario
        self.status = "running"
        self.lines: list[str] = []
        self.started_at = now_iso()
        self.finished_at: str | None = None
        self.proc: asyncio.subprocess.Process | None = None

    def add(self, line: str) -> None:
        if len(self.lines) < MAX_LINES:
            self.lines.append(_ANSI.sub("", line))
        elif len(self.lines) == MAX_LINES:
            self.lines.append(f"[CONTROL] output truncated after {MAX_LINES} lines")

    def finish(self, status: str) -> None:
        self.status, self.finished_at = status, now_iso()

    def to_json(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "scenario": self.scenario, "status": self.status,
                "lines": list(self.lines), "started_at": self.started_at, "finished_at": self.finished_at}


def create_app(command: Callable[[str], list[str]] = demo_command, origin: str | None = None,
               operator_token: SecretStr | None = None) -> FastAPI:
    if origin is None:
        origin = get_settings().console_origin
    operator_token = operator_token if operator_token is not None else get_settings().sekisho_operator_token
    runs: dict[str, Run] = {}
    state: dict[str, Any] = {"current": None, "tasks": set()}

    async def execute(run: Run) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
        try:
            proc = await asyncio.create_subprocess_exec(
                *command(run.scenario), cwd=str(ROOT), env=env, limit=1 << 20,
                stdin=asyncio.subprocess.DEVNULL,  # a run never waits for keyboard input
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            run.proc = proc
            assert proc.stdout is not None
            while raw := await proc.stdout.readline():
                run.add(raw.decode("utf-8", "replace").rstrip("\r\n"))
            code = await proc.wait()
            run.finish("succeeded" if code == 0 else "failed")
        except Exception as exc:  # noqa: BLE001 - the run fails, the API stays up
            run.add(f"[CONTROL] could not run scenario {run.scenario}: {type(exc).__name__}: {exc}")
            run.finish("failed")
        finally:
            if state["current"] == run.run_id:
                state["current"] = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        for run in runs.values():  # don't leave a demo subprocess behind on shutdown
            if run.status == "running" and run.proc is not None and run.proc.returncode is None:
                run.proc.terminate()

    app = FastAPI(title="Sekisho treasury control", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[origin], allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "Authorization"])

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])
        return error(422, "invalid_request", problems or "invalid request")

    @app.post("/run")
    async def start_run(body: RunRequest, request: Request) -> Any:
        try:
            require_operator(request.headers.get("authorization"), operator_token)
        except GateError as exc:
            return error(exc.status, exc.code, exc.message)
        current = runs.get(state["current"] or "")
        if current is not None and current.status == "running":
            return error(409, "run_in_progress", f"run {current.run_id} ({current.scenario}) is still running",
                         run_id=current.run_id)
        run = Run(body.scenario)
        runs[run.run_id] = run
        state["current"] = run.run_id  # set before any await: one run at a time
        finished = [r for r in runs.values() if r.status != "running"]
        for old in finished[: max(0, len(runs) - MAX_RUNS)]:
            runs.pop(old.run_id, None)
        task = asyncio.create_task(execute(run))
        state["tasks"].add(task)
        task.add_done_callback(state["tasks"].discard)
        return {"run_id": run.run_id}

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> Any:
        run = runs.get(run_id)
        if run is None:
            return error(404, "not_found", f"no run {run_id}")
        return run.to_json()

    return app


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Treasury control API for the console demo bar")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()

"""Treasury control API (docs/api.md): run lifecycle, captured lines, one run at a time (409),
validation and CORS. The demo subprocess is replaced by a tiny Python one-liner."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
import pytest  # noqa: E402

from pydantic import SecretStr
from agents.treasury.control import create_app, demo_command  # noqa: E402

ORIGIN = "http://localhost:3000"


def fake_demo(script: str):
    """A command factory: runs `script` (with SCENARIO bound) instead of scripts/demo.py."""
    return lambda scenario: [sys.executable, "-u", "-c", f"SCENARIO = {scenario!r}\n{script}"]


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://control",
                            headers={"Authorization": "Bearer test-operator-token"})


async def wait_done(http: httpx.AsyncClient, run_id: str, timeout: float = 15.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        body = (await http.get(f"/runs/{run_id}")).json()
        if body["status"] != "running" or asyncio.get_running_loop().time() > deadline:
            return body
        await asyncio.sleep(0.05)


async def test_run_captures_lines_and_succeeds():
    app = create_app(fake_demo("print('[AGENT] start', SCENARIO)\nprint('\\x1b[1;32mPASS\\x1b[0m', SCENARIO)"),
                     origin=ORIGIN, operator_token=SecretStr("test-operator-token"))
    async with client(app) as http:
        r = await http.post("/run", json={"scenario": "S1"})
        assert r.status_code == 200
        run_id = r.json()["run_id"]
        body = await wait_done(http, run_id)
    assert body["run_id"] == run_id and body["scenario"] == "S1" and body["status"] == "succeeded"
    assert body["lines"] == ["[AGENT] start S1", "PASS S1"]  # ANSI colours stripped
    assert body["started_at"].endswith("Z") and body["finished_at"].endswith("Z")


async def test_non_zero_exit_is_failed():
    app = create_app(fake_demo("print('FAIL', SCENARIO)\nraise SystemExit(1)"), origin=ORIGIN, operator_token=SecretStr("test-operator-token"))
    async with client(app) as http:
        run_id = (await http.post("/run", json={"scenario": "all"})).json()["run_id"]
        body = await wait_done(http, run_id)
    assert body["status"] == "failed" and body["lines"] == ["FAIL all"]


async def test_one_run_at_a_time():
    app = create_app(fake_demo("import time\nprint('running', flush=True)\ntime.sleep(1.0)\nprint('done')"),
                     origin=ORIGIN, operator_token=SecretStr("test-operator-token"))
    async with client(app) as http:
        first = (await http.post("/run", json={"scenario": "S2"})).json()["run_id"]
        second = await http.post("/run", json={"scenario": "S3"})
        assert second.status_code == 409
        assert second.json()["error"] == "run_in_progress" and second.json()["run_id"] == first
        running = (await http.get(f"/runs/{first}")).json()
        assert running["status"] == "running" and running["finished_at"] is None
        done = await wait_done(http, first)
        assert done["status"] == "succeeded" and done["lines"] == ["running", "done"]
        third = await http.post("/run", json={"scenario": "S3"})  # the slot is free again
        assert third.status_code == 200
        assert (await wait_done(http, third.json()["run_id"]))["scenario"] == "S3"


async def test_finished_run_frees_the_slot():
    app = create_app(fake_demo("print(SCENARIO)"), origin=ORIGIN, operator_token=SecretStr("test-operator-token"))
    async with client(app) as http:
        a = (await http.post("/run", json={"scenario": "S5"})).json()["run_id"]
        await wait_done(http, a)
        b = await http.post("/run", json={"scenario": "S6"})
        assert b.status_code == 200
        assert (await wait_done(http, b.json()["run_id"]))["lines"] == ["S6"]


async def test_spawn_failure_is_a_failed_run():
    app = create_app(lambda scenario: ["/nonexistent/python", "demo.py", scenario], origin=ORIGIN, operator_token=SecretStr("test-operator-token"))
    async with client(app) as http:
        run_id = (await http.post("/run", json={"scenario": "S1"})).json()["run_id"]
        body = await wait_done(http, run_id)
    assert body["status"] == "failed" and "could not run scenario S1" in body["lines"][0]


async def test_validation_and_not_found():
    app = create_app(fake_demo("print(1)"), origin=ORIGIN, operator_token=SecretStr("test-operator-token"))
    async with client(app) as http:
        bad = await http.post("/run", json={"scenario": "S9"})
        assert bad.status_code == 422 and bad.json()["error"] == "invalid_request"
        missing = await http.get("/runs/run_nope")
        assert missing.status_code == 404 and missing.json()["error"] == "not_found"


async def test_cors_allows_the_console_origin_only():
    app = create_app(fake_demo("print(1)"), origin=ORIGIN, operator_token=SecretStr("test-operator-token"))
    async with client(app) as http:
        pre = await http.options("/run", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                                                   "Access-Control-Request-Headers": "content-type"})
        assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == ORIGIN
        other = await http.get("/runs/x", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in other.headers


def test_demo_command_runs_the_demo_script():
    cmd = demo_command("S2")
    assert cmd[0] == sys.executable and cmd[-2].endswith("scripts/demo.py") and cmd[-1] == "S2"


@pytest.mark.parametrize("configured,header,status", [("", "Bearer test", 503), ("test", "", 401), ("test", "Bearer wrong", 401)])
async def test_run_requires_operator_before_spawning(configured, header, status):
    calls = []
    app = create_app(lambda scenario: calls.append(scenario), origin=ORIGIN, operator_token=SecretStr(configured))
    async with client(app) as http:
        result = await http.post("/run", json={"scenario": "S1"}, headers={"Authorization": header})
        assert result.status_code == status
        assert calls == []

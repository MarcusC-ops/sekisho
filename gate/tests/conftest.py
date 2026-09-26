"""Shared fixtures for the gate tests: settings on a temp DB, fake clients, and an
in-process API client (httpx.ASGITransport). Helpers live in gate_testkit.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from eth_account import Account

sys.path.insert(0, str(Path(__file__).parent))  # importlib mode: make gate_testkit importable

from gate_testkit import (  # noqa: E402
    WEBHOOK_SECRET,
    FakeIntercepta,
    FakeMultiBaas,
    FakeOracle,
    FakeTracer,
    webhook_functions,
)

from sekisho_gate.config import Settings  # noqa: E402


# ---------- fixtures ----------


@pytest.fixture
def make_settings(tmp_path: Path):
    def _make(**overrides: Any) -> Settings:
        base: dict[str, Any] = dict(
            _env_file=None,
            db_path=tmp_path / "gate-test.db",
            demo_mode=True,
            sekisho_operator_token="test-operator-token",
            llm_provider="none",
            llm_model="",
            intercepta_api_key="test-key",
            mb_url="",
            mb_admin_api_key="",
            mb_webhook_secret=WEBHOOK_SECRET,
            gate_screener_pk="",
            officer_pk="",
            buyer_agent_pk="",
            fault_inject="",
            console_origin="http://localhost:3000",
            contracts_rpc_url="http://127.0.0.1:9/unreachable",
            screen_token=True,
            screen_impersonation=True,
        )
        base.update(overrides)
        return Settings(**base)

    return _make


@pytest.fixture
def fakes() -> SimpleNamespace:
    return SimpleNamespace(
        intercepta=FakeIntercepta(),
        oracle=FakeOracle(),
        tracer=FakeTracer(),
        mb=FakeMultiBaas(),
        screener=Account.create(),
        officer=Account.create(),
    )


@pytest.fixture
def make_services(make_settings, fakes):
    from sekisho_gate.services import Services

    built: list[Any] = []

    def _make(*, settings: Settings | None = None, with_mb: bool = False, llm: Any = None, **kw: Any) -> Any:
        verify, parse, _ = webhook_functions()
        svc = Services(
            settings or make_settings(),
            intercepta=kw.pop("intercepta", fakes.intercepta),
            oracle=kw.pop("oracle", fakes.oracle),
            tracer=kw.pop("tracer", fakes.tracer),
            mb=fakes.mb if with_mb else kw.pop("mb", None),
            llm=llm,
            verify_webhook=kw.pop("verify_webhook", verify),
            parse_event=kw.pop("parse_event", parse),
            screener=fakes.screener,
            officer=fakes.officer,
            **kw,
        )
        built.append(svc)
        return svc

    return _make


@pytest.fixture
async def gate(make_services):
    """Factory for a started gate with an HTTP client: `g = await gate(with_mb=True)`."""
    from sekisho_gate.main import create_app

    opened: list[tuple[Any, httpx.AsyncClient]] = []

    async def _open(**kw: Any) -> SimpleNamespace:
        svc = make_services(**kw)
        await svc.start()
        app = create_app(settings=svc.settings, services=svc, configure_logging=False)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gate",
                                   headers={"Authorization": "Bearer test-operator-token"})
        opened.append((svc, client))
        return SimpleNamespace(svc=svc, client=client, app=app)

    yield _open
    for svc, client in opened:
        await client.aclose()
        await svc.stop()

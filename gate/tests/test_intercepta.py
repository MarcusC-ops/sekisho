"""Intercepta client: parsing, no-history handling, bad key, cache, quota (respx only)."""

import json
import logging
import time
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from sekisho_gate.config import Settings
from sekisho_gate.screening.cache import QUOTA_KEY
from sekisho_gate.screening.intercepta import InterceptaClient

pytestmark = pytest.mark.respx(assert_all_called=False)  # unmatched requests still fail

FIX = Path(__file__).parent / "fixtures"
BASE = "https://api.web3antivirus.io"
ADDR = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"
FUNDER = "0x1A2a1c938CE3eC39b6D47113c7955bAa9DD454F2"
TOKEN = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def qs_path(address: str) -> str:
    return f"/api/public/v2/extension/account/{address.lower()}/quick-scan"


# Shape per Intercepta's OpenAPI schema (ToxicScoreShortResponseV2). The values and
# description texts are illustrative: no real response is available without a key.
QS_BODY = {
    "toxicScore": 100,
    "traits": [
        {"name": "sanction_address", "risk": 100, "txsCount": 0, "description": "Address is sanctioned."},
        {"name": "mixer_transfers", "risk": 60, "txsCount": 3, "description": "Has transfers with a mixer."},
        {"name": "fake_phishing_transfer", "risk": 10, "txsCount": 12, "description": "Received phishing transfers."},
    ],
}
TOKEN_BODY = {
    "apiVersion": "2.3.1", "riskScore": 0, "riskLevel": "neutral", "category": "info", "trust": "whitelist",
    "action": "info", "detectors": [{"code": "HIGH_REPUTATION_TOKEN", "description": "High reputation."}],
    "token": {"chainId": "8453", "address": TOKEN.lower(), "symbol": "USDC"},
    "saleTax": {"currentValue": 0, "minValue": 0, "maxValue": 0},
    "buyTax": {"currentValue": 0, "minValue": 0, "maxValue": 0},
}


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        _env_file=None,
        intercepta_base_url=BASE,
        intercepta_api_key=SecretStr("test-key"),
        intercepta_quota=1000,
        intercepta_warn_at=800,
        intercepta_reserve_from=950,
        fault_inject="",
        db_path=tmp_path / "sekisho.db",
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
async def client(settings):
    c = InterceptaClient(settings, http=httpx.AsyncClient())
    yield c
    await c._http.aclose()


async def test_quick_scan_ok(client, respx_mock):
    route = respx_mock.get(BASE + qs_path(ADDR)).mock(return_value=httpx.Response(200, json=QS_BODY))
    out = await client.quick_scan(ADDR)
    assert out.name == "intercepta.quick_scan"
    assert out.status == "ok" and out.live is True and out.error is None
    assert out.data["toxicScore"] == 100
    assert [t["name"] for t in out.data["traits"]] == ["sanction_address", "mixer_transfers", "fake_phishing_transfer"]
    assert out.data["traits"][1] == {"name": "mixer_transfers", "risk": 60, "txsCount": 3,
                                     "description": "Has transfers with a mixer."}  # verbatim
    assert out.raw == QS_BODY
    assert out.summary.startswith("toxicScore 100, 3 traits")
    assert isinstance(out.latency_ms, int)
    assert route.calls.last.request.headers["X-API-KEY"] == "test-key"
    assert client.quota_status()["used"] == 1


@pytest.mark.parametrize("status, body", [
    (404, '{"status":404,"response":"Not found"}'),
    (204, ""), (200, ""), (200, "null"), (200, "{}"), (200, "[]"),
])
async def test_missing_provider_evidence_is_error(client, respx_mock, status, body):
    route = respx_mock.get(BASE + qs_path(ADDR)).mock(
        return_value=httpx.Response(status, text=body)
    )
    out = await client.quick_scan(ADDR)
    assert out.status == "error"
    assert out.data is None
    await client.quick_scan_cached(ADDR)
    assert route.call_count == 2  # errors are never cached


async def test_framework_404_is_an_error_not_clean(client, respx_mock):
    respx_mock.get(BASE + qs_path(ADDR)).mock(
        return_value=httpx.Response(404, json={"statusCode": 404, "message": "Cannot GET /api/x", "error": "Not Found"})
    )
    out = await client.quick_scan(ADDR)
    assert out.status == "error" and "endpoint not found" in out.error


async def test_403_is_bad_key_and_not_retried(client, respx_mock):
    body = (FIX / "intercepta" / "quick_scan_403.json").read_text().strip()
    route = respx_mock.get(BASE + qs_path(ADDR)).mock(
        return_value=httpx.Response(403, text=body, headers={"content-type": "application/json"})
    )
    out = await client.quick_scan(ADDR)
    assert out.status == "error"
    assert out.error.startswith("invalid Intercepta API key (HTTP 403)")
    assert "doesn’t exist" in out.error  # upstream text kept verbatim
    assert out.raw == json.loads(body)
    assert route.call_count == 1
    ok, detail = client.key_status()
    assert ok is False and "invalid Intercepta API key" in detail


async def test_empty_key_makes_no_http_call(tmp_path, respx_mock):
    s = make_settings(tmp_path, intercepta_api_key=SecretStr(""))
    route = respx_mock.get(BASE + qs_path(ADDR)).mock(return_value=httpx.Response(200, json=QS_BODY))
    c = InterceptaClient(s, http=httpx.AsyncClient())
    try:
        for coro in (c.quick_scan(ADDR), c.quick_scan_cached(ADDR), c.deep_scan(ADDR),
                     c.impersonation(ADDR), c.token_scan(TOKEN)):
            out = await coro
            assert out.status == "error" and out.error == "INTERCEPTA_API_KEY is not set"
        assert route.call_count == 0
        assert c.quota_status()["used"] == 0
        assert c.key_status() == (False, "INTERCEPTA_API_KEY is not set")
    finally:
        await c._http.aclose()


async def test_cache_miss_then_hit_then_expiry(client, respx_mock):
    route = respx_mock.get(BASE + qs_path(FUNDER)).mock(return_value=httpx.Response(200, json=QS_BODY))
    first = await client.quick_scan_cached(FUNDER)
    assert first.status == "ok" and first.live is True and route.call_count == 1
    second = await client.quick_scan_cached(FUNDER)
    assert second.status == "ok" and second.live is False and route.call_count == 1
    assert second.data == first.data and second.raw == QS_BODY
    assert second.summary.endswith("(cached)")
    client.cache._clock = lambda: time.time() + 24 * 3600 + 1  # past the 24 h TTL
    third = await client.quick_scan_cached(FUNDER)
    assert third.live is True and route.call_count == 2


async def test_live_scan_skips_cache_read_but_writes_it(client, respx_mock):
    route = respx_mock.get(BASE + qs_path(ADDR)).mock(return_value=httpx.Response(200, json=QS_BODY))
    await client.quick_scan(ADDR, live=True)
    await client.quick_scan(ADDR, live=True)
    assert route.call_count == 2  # the direct scan never reads the cache
    cached = await client.quick_scan_cached(ADDR)
    assert cached.live is False and route.call_count == 2  # but it did write it
    via_cache = await client.quick_scan(ADDR, live=False)
    assert via_cache.live is False and route.call_count == 2


async def test_quota_counts_warns_and_reserve_skips_funders_only(client, respx_mock, caplog):
    respx_mock.get(url__regex=rf"{BASE}/api/public/v2/extension/account/0x[0-9a-f]+/quick-scan").mock(
        return_value=httpx.Response(200, json=QS_BODY)
    )
    client.cache.incr(QUOTA_KEY, 799)
    with caplog.at_level(logging.WARNING, logger="sekisho_gate.screening.intercepta"):
        await client.quick_scan(ADDR)
    assert client.quota_status()["used"] == 800
    assert any("quota" in r.getMessage() for r in caplog.records)

    client.cache.incr(QUOTA_KEY, 150)  # 950 = INTERCEPTA_RESERVE_FROM
    skipped = await client.quick_scan_cached(FUNDER)
    assert skipped.status == "skipped" and "reserve" in skipped.summary
    assert client.quota_status()["used"] == 950  # no call made
    direct = await client.quick_scan(FUNDER)  # the direct live scan always runs
    assert direct.status == "ok" and direct.live is True
    assert client.quota_status() == {"used": 951, "quota": 1000, "remaining": 49, "warn_at": 800, "reserve_from": 950}


async def test_every_http_call_counts_even_failures(client, respx_mock):
    respx_mock.get(BASE + qs_path(ADDR)).mock(return_value=httpx.Response(500, text="oops"))
    respx_mock.get(BASE + qs_path(FUNDER)).mock(side_effect=httpx.ReadTimeout("slow"))
    bad = await client.quick_scan(ADDR)
    slow = await client.quick_scan(FUNDER)
    assert bad.status == "error" and bad.error.startswith("HTTP 500")
    assert slow.status == "error" and slow.error == "timed out after 3 s"
    assert client.quota_status()["used"] == 2


async def test_unexpected_shape_is_an_error(client, respx_mock):
    respx_mock.get(BASE + qs_path(ADDR)).mock(return_value=httpx.Response(200, json={"score": 5}))
    out = await client.quick_scan(ADDR)
    assert out.status == "error" and "unexpected response" in out.error
    assert out.raw == {"score": 5}


async def test_token_scan_is_cached_per_chain(client, respx_mock):
    path = f"/api/public/v2/extension/token-intelligence/token/{TOKEN.lower()}/risks"
    route = respx_mock.get(BASE + path, params={"chainId": "8453"}).mock(
        return_value=httpx.Response(200, json=TOKEN_BODY)
    )
    out = await client.token_scan(TOKEN)
    assert out.name == "intercepta.token" and out.status == "ok" and out.live is True
    assert out.data == {"riskScore": 0, "riskLevel": "neutral", "trust": "whitelist", "action": "info",
                        "detectors": [{"code": "HIGH_REPUTATION_TOKEN", "description": "High reputation."}]}
    again = await client.token_scan(TOKEN, 8453)
    assert again.live is False and route.call_count == 1


async def test_impersonation_and_deep_scan(client, respx_mock):
    imp = f"/api/public/v1/extension/poisoning-attack/check-address/{ADDR.lower()}"
    respx_mock.get(BASE + imp).mock(return_value=httpx.Response(200, json={"isAddressPoisoned": False, "originalAddress": ""}))
    respx_mock.get(BASE + f"/api/public/v2/extension/account/{ADDR.lower()}/toxic-score").mock(
        return_value=httpx.Response(200, json=QS_BODY)
    )
    out = await client.impersonation(ADDR)
    assert out.name == "intercepta.impersonation" and out.status == "ok"
    assert out.data == {"isAddressPoisoned": False, "originalAddress": None}
    deep = await client.deep_scan(ADDR)
    assert deep.name == "intercepta.deep_scan" and deep.data["toxicScore"] == 100


async def test_fault_injection_times_out_without_a_call(tmp_path, respx_mock):
    s = make_settings(tmp_path, fault_inject="intercepta_timeout")
    route = respx_mock.get(BASE + qs_path(ADDR)).mock(return_value=httpx.Response(200, json=QS_BODY))
    c = InterceptaClient(s, http=httpx.AsyncClient())
    try:
        out = await c.quick_scan(ADDR)
        assert out.status == "error" and "FAULT_INJECT" in out.error
        assert route.call_count == 0
    finally:
        await c._http.aclose()


async def test_invalid_address_is_an_error(client):
    out = await client.quick_scan("0xnot-an-address")
    assert out.status == "error" and "not a valid address" in out.error

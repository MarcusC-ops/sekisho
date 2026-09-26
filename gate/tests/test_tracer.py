"""Source-of-funds tracer: normalisation, flags, taint maths, hop 2, failures (respx).

Blockscout fixtures are trimmed real keyless responses for the Ronin Bridge exploiter
(0x098B…2F96). Synthetic scenarios reuse those real item shapes with other addresses
and amounts, so the taint maths is easy to check by hand.
"""

import asyncio
import copy
import json
from collections import Counter
from pathlib import Path

import httpx
import pytest
import yaml
from eth_utils import to_checksum_address
from pydantic import SecretStr

from sekisho_gate.config import REPO_ROOT, Settings
from sekisho_gate.screening import tracer as tracer_mod
from sekisho_gate.screening.cache import QUOTA_KEY
from sekisho_gate.screening.intercepta import InterceptaClient
from sekisho_gate.screening.sanctions import SanctionsOracle
from sekisho_gate.screening.tracer import Tracer, _RateLimiter, label_flags, sender_info

pytestmark = pytest.mark.respx(assert_all_called=False)

FIX = Path(__file__).parent / "fixtures" / "blockscout"
POLICY = yaml.safe_load((REPO_ROOT / "gate" / "policy" / "policy.yaml").read_text())
ETH_RPC = "https://eth-rpc.test"
BASE_RPC = "https://base-rpc.test"
INTERCEPTA = "https://intercepta.test"
RONIN = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"
EMPTY = {"items": [], "next_page_params": None}
TRUE = "0x" + "0" * 63 + "1"
FALSE = "0x" + "0" * 64


def load(name):
    return json.loads((FIX / name).read_text())


TT = load("eth_token_transfers.json")["items"]  # [0] is a real USDC transfer
TX = load("eth_transactions.json")["items"]  # [0] is from "Euler Finance Exploiter 2"
IT = load("eth_internal_transactions.json")["items"]  # [0] is from "Ronin Bridge V1"
EULER = TX[0]["from"]
FIXEDFLOAT = TX[1]["from"]
RONIN_OBJ = TT[2]["from"]  # the exploiter's own address object (a self-transfer)

C = to_checksum_address("0x" + "c0" * 20)  # counterparty
A = to_checksum_address("0x" + "aa" * 20)
D = to_checksum_address("0x" + "dd" * 20)
T = to_checksum_address("0x" + "70" * 20)
U = to_checksum_address("0x" + "75" * 20)
V = to_checksum_address("0x" + "76" * 20)
B = EULER["hash"]


def addr(hash_, *tags, **extra):
    obj = {"hash": hash_, "name": None, "ens_domain_name": None, "is_contract": False, "is_scam": False,
           "reputation": "ok", "public_tags": [], "metadata": None}
    if tags:
        obj["metadata"] = {"tags": [{"name": t, "slug": t.lower().replace(" ", "-"), "tagType": "name",
                                     "ordinal": 10, "meta": {}} for t in tags]}
    obj.update(extra)
    return obj


def usdc(frm, to, units):
    item = copy.deepcopy(TT[0])
    item["from"], item["to"] = frm, {"hash": to}
    item["total"]["value"] = str(int(units * 10**6))
    return item


def native(frm, to, eth):
    item = copy.deepcopy(TX[0])
    item["from"], item["to"], item["value"] = frm, {"hash": to}, str(int(eth * 10**18))
    return item


def internal(frm, to, eth):
    item = copy.deepcopy(IT[0])
    item["from"], item["to"], item["value"] = frm, {"hash": to}, str(int(eth * 10**18))
    return item


def page(*items, next_page=None):
    return {"items": list(items), "next_page_params": next_page}


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        _env_file=None,
        blockscout_base="https://api.blockscout.com",
        blockscout_api_key=SecretStr(""),
        eth_usd_price=4000.0,
        trace_enable_hop2=True,
        eth_mainnet_rpc_url=ETH_RPC,
        base_mainnet_rpc_url=BASE_RPC,
        intercepta_base_url=INTERCEPTA,
        intercepta_api_key=SecretStr(""),
        intercepta_reserve_from=950,
        fault_inject="",
        db_path=tmp_path / "sekisho.db",
    )
    values.update(overrides)
    return Settings(**values)


def mock_feeds(respx_mock, host, address, *, erc20=None, native_=None, internal_=None, status=200):
    routes = {}
    for feed, body in (("token-transfers", erc20), ("transactions", native_), ("internal-transactions", internal_)):
        routes[feed] = respx_mock.route(method="GET", host=host, path=f"/api/v2/addresses/{address}/{feed}").mock(
            return_value=httpx.Response(status, json=body if body is not None else EMPTY)
        )
    return routes


def mock_oracle(respx_mock, sanctioned=()):
    bad = {a.lower() for a in sanctioned}

    def answer(request):
        body = json.loads(request.content)
        calls = body if isinstance(body, list) else [body]
        out = [{"jsonrpc": "2.0", "id": c["id"],
                "result": TRUE if "0x" + c["params"][0]["data"][-40:] in bad else FALSE} for c in calls]
        return httpx.Response(200, json=out if isinstance(body, list) else out[0])

    respx_mock.post(ETH_RPC).mock(side_effect=answer)
    respx_mock.post(BASE_RPC).mock(side_effect=answer)


@pytest.fixture
async def make_tracer(tmp_path):
    made = []

    def factory(budget_s=5.5, **overrides):
        s = make_settings(tmp_path, **overrides)
        http = httpx.AsyncClient()
        oracle = SanctionsOracle(s, http=http)
        intercepta = InterceptaClient(s, http=http)
        tr = Tracer(s, oracle, intercepta, POLICY, http=http, budget_s=budget_s, rate_limit_rps=1000)
        made.append(http)
        return tr

    yield factory
    for http in made:
        await http.aclose()


def scenario(respx_mock, host="eth.blockscout.com"):
    """C gets 1,000 USDC from A, 3 ETH from the Euler exploiter (B) and 2 ETH (internal)
    from D. A was funded by a Tornado-tagged contract (internal tx) and U; D by V."""
    mock_feeds(respx_mock, host, C,
               erc20=page(usdc(addr(A), C, 1000)),
               native_=page(native(EULER, C, 3)),
               internal_=page(internal(addr(D), C, 2)))
    mock_feeds(respx_mock, "base.blockscout.com", C)
    mock_feeds(respx_mock, host, A,
               erc20=page(usdc(addr(U), A, 100)),
               native_=page(native(addr(C), A, 1)),  # money from the counterparty itself: ignored
               internal_=page(internal(addr(T, "Tornado.Cash: Router"), A, 5)))
    mock_feeds(respx_mock, host, D, native_=page(native(addr(V), D, 10)))


# ---------- hop 1 on the real sample ----------


async def test_hop1_on_real_sample(make_tracer, respx_mock):
    mock_feeds(respx_mock, "eth.blockscout.com", RONIN, erc20=load("eth_token_transfers.json"),
               native_=load("eth_transactions.json"), internal_=load("eth_internal_transactions.json"))
    mock_feeds(respx_mock, "base.blockscout.com", RONIN)
    mock_oracle(respx_mock)
    out = await make_tracer(trace_enable_hop2=False).trace(RONIN)

    assert out.name == "trace.source_of_funds" and out.status == "ok" and out.live is None
    d = out.data
    inbound = 25_500_000 + 1e-7 * 4000 + 100 * 4000 + 0.0090648 * 4000 + 2 * 4000 + 173_600 * 4000
    assert d["inbound_usd_traced"] == round(inbound, 2)
    assert [(h["address"], h["tx_count"]) for h in d["hop1"]] == [
        ("0x1A2a1c938CE3eC39b6D47113c7955bAa9DD454F2", 2),  # Ronin Bridge V1: USDC + 173,600 ETH internal
        (EULER["hash"], 1),  # 100 ETH
        (TX[2]["from"]["hash"], 1),  # 2 ETH, untagged
        (FIXEDFLOAT["hash"], 1),  # 0.0090648 ETH
    ]  # the 1e-7 WETH of phishing dust ($0.0004) is counted but not ranked
    usds = [h["usd"] for h in d["hop1"]]
    assert usds == sorted(usds, reverse=True)
    by_label = {h["labels"][0] if h["labels"] else h["address"]: h for h in d["hop1"]}
    assert by_label["Ronin Bridge V1"]["flags"] == [] and by_label["Ronin Bridge V1"]["usd"] == 719_900_000.0
    assert by_label["Euler Finance Exploiter 2"]["flags"] == ["label:exploit"]
    assert by_label["FixedFloat: Hot Wallet 2"]["flags"] == ["label:is_scam", "label:hack", "label:phish"]
    assert "Visit website getether .net to claim rewards" not in by_label
    assert all(h["sanctioned"] is False and h["intercepta"] is None for h in d["hop1"])

    flagged = 100 * 4000 + 0.0090648 * 4000
    assert d["taint_pct"] == round(100 * flagged / inbound, 2) == 0.06
    assert d["taint_usd"] == round(flagged, 2)
    assert d["truncated"] is True  # the native page had next_page_params
    assert d["hop2"] == []
    assert d["paths"][0] == "Euler Finance Exploiter 2 → counterparty (Ethereum, $400,000) [label:exploit]"
    assert any(p.startswith("FixedFloat: Hot Wallet 2 → counterparty (Ethereum, $36.26)") for p in d["paths"])
    notes = " | ".join(d["notes"])
    assert "Dropped 2 zero-value, 2 self-transfers transfers" in notes
    assert "2 senders with only unpriced transfers counted but not ranked" in notes
    assert "1 sender under $1.00 (dust) counted but not ranked" in notes
    assert "hop 2 off (TRACE_ENABLE_HOP2=false)" in notes
    assert "keyless public hosts" in notes
    assert "Intercepta funder scans error for 4 senders: INTERCEPTA_API_KEY is not set" in notes

    # Internal transactions are included: the 173,600 ETH arrived as one.
    internal_rows = [t for t in out.raw["hop1_transfers"] if t["feed"] == "internal"]
    assert internal_rows == [{"from": "0x1A2a1c938CE3eC39b6D47113c7955bAa9DD454F2", "chain_id": 1, "feed": "internal",
                              "symbol": "ETH", "amount": 173600.0, "usd": 694_400_000.0,
                              "tx_hash": IT[0]["transaction_hash"]}]
    assert len(out.raw["sources"]) == 6 and "full Blockscout pages are not stored" in out.raw["note"]


# ---------- taint maths ----------


async def test_hop1_and_hop2_taint(make_tracer, respx_mock):
    scenario(respx_mock)
    mock_oracle(respx_mock)
    out = await make_tracer().trace(C)
    d = out.data
    assert out.status == "ok"
    assert d["inbound_usd_traced"] == 21_000.0  # 1,000 USDC + 3 ETH + 2 ETH at $4,000
    assert [(h["address"], h["usd"], h["flags"]) for h in d["hop1"]] == [
        (B, 12_000.0, ["label:exploit"]),
        (D, 8_000.0, []),
        (A, 1_000.0, []),
    ]
    assert [h["share_pct"] for h in d["hop1"]] == [57.14, 38.1, 4.76]
    hop2 = {(e["via"], e["address"]): e for e in d["hop2"]}
    assert set(hop2) == {(A, T), (A, U), (D, V)}  # C's own payment to A is not a source
    assert hop2[(A, T)]["flags"] == ["label:tornado"] and hop2[(A, T)]["usd"] == 20_000.0
    assert hop2[(A, U)]["flags"] == [] and hop2[(D, V)]["flags"] == []
    assert all(e["chain_id"] == 1 for e in d["hop2"])
    # 12,000 flagged at hop 1 + 0.5 x 1,000 from A, whose funder is flagged.
    assert d["taint_usd"] == 12_500.0
    assert d["taint_pct"] == round(100 * 12_500 / 21_000, 2) == 59.52
    assert d["paths"] == [
        "Euler Finance Exploiter 2 → counterparty (Ethereum, $12,000) [label:exploit]",
        f"Tornado.Cash: Router → {A[:6]}…{A[-4:]} → counterparty (Ethereum, $1,000 x 0.5) [label:tornado]",
    ]
    assert {t["via"] for t in out.raw["hop2_transfers"]} == {A, D}
    assert out.summary == "taint 59.52% of $21,000 traced; 1 of 3 top senders flagged; hop 2 on 2"


async def test_hop2_dust_from_a_phishing_address_does_not_taint_the_via(make_tracer, respx_mock):
    # Found live: a "Phish / Hack" address sent 1e-7 WETH of dust to a bridge contract
    # that funded the counterparty; the binary hop-2 rule then tainted the whole bridge.
    mock_feeds(respx_mock, "eth.blockscout.com", C, erc20=page(usdc(addr(A), C, 1000)))
    mock_feeds(respx_mock, "base.blockscout.com", C)
    dust = copy.deepcopy(TT[1])  # real item: WETH dust from an is_scam "Phish / Hack" sender
    dust["to"] = {"hash": A}
    mock_feeds(respx_mock, "eth.blockscout.com", A, erc20=page(dust), native_=page(native(addr(U), A, 1)))
    mock_oracle(respx_mock)
    out = await make_tracer().trace(C)
    assert [e["address"] for e in out.data["hop2"]] == [U]  # the dust sender is not ranked
    assert out.data["taint_pct"] == 0.0 and out.data["paths"] == []


async def test_hop1_only_taint_when_hop2_disabled(make_tracer, respx_mock):
    scenario(respx_mock)
    mock_oracle(respx_mock)
    out = await make_tracer(trace_enable_hop2=False).trace(C)
    assert out.data["taint_pct"] == round(100 * 12_000 / 21_000, 2) == 57.14
    assert out.data["hop2"] == []


async def test_sanctioned_hop2_sender_via_oracle(make_tracer, respx_mock):
    scenario(respx_mock)
    mock_oracle(respx_mock, sanctioned=[V])  # D's funder is on the sanctions list
    out = await make_tracer().trace(C)
    hop2 = {(e["via"], e["address"]): e for e in out.data["hop2"]}
    assert hop2[(D, V)]["flags"] == ["sanctioned"]
    assert out.data["taint_usd"] == 12_000 + 0.5 * (1_000 + 8_000)


async def test_zero_inbound(make_tracer, respx_mock):
    mock_feeds(respx_mock, "eth.blockscout.com", C)
    mock_feeds(respx_mock, "base.blockscout.com", C)
    out = await make_tracer().trace(C)
    assert out.status == "ok"
    d = out.data
    assert (d["inbound_usd_traced"], d["taint_pct"], d["hop1"], d["hop2"], d["paths"]) == (0.0, 0.0, [], [], [])
    assert d["truncated"] is False
    assert "no priced inbound value traced" in d["notes"]


# ---------- normalisation and labels ----------


async def test_normalisation_rules(make_tracer):
    tr = make_tracer()
    drops = Counter()
    c = C.lower()

    scam = usdc(addr(A), C, 50)
    scam["token"]["reputation"] = "scam"
    assert tr._normalise_item("erc20", 1, scam, c, drops) is None and drops["scam_token"] == 1

    fake = usdc(addr(A), C, 50)
    fake["token"]["address_hash"] = "0x" + "12" * 20  # symbol USDC, not the canonical contract
    row = tr._normalise_item("erc20", 1, fake, c, drops)
    assert row["symbol"] == "USDC" and row["usd"] == 0.0 and drops["lookalike"] == 1

    real = tr._normalise_item("erc20", 1, usdc(addr(A), C, 50), c, drops)
    assert real["usd"] == 50.0 and real["amount"] == 50.0

    weth = usdc(addr(A), C, 0)
    weth["token"].update(address_hash="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", symbol="WETH", decimals="18")
    weth["total"] = {"decimals": "18", "value": str(2 * 10**18)}
    assert tr._normalise_item("erc20", 1, weth, c, drops)["usd"] == 8000.0

    usdbc = usdc(addr(A), C, 7)
    usdbc["token"].update(address_hash="0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA", symbol="USDbC")
    assert tr._normalise_item("erc20", 8453, usdbc, c, drops)["usd"] == 7.0
    assert tr._normalise_item("erc20", 1, usdbc, c, drops)["usd"] == 0.0  # USDbC is a Base token

    other = copy.deepcopy(TT[5])  # a real unpriced token (ILY)
    other["to"] = {"hash": C}
    row = tr._normalise_item("erc20", 1, other, c, drops)
    assert row["usd"] == 0.0 and row["symbol"] == "ILY"  # counted, not weighted

    zero = usdc(addr(A), C, 0)
    assert tr._normalise_item("erc20", 1, zero, c, drops) is None and drops["zero"] == 1
    failed = native(addr(A), C, 1)
    failed["status"], failed["result"] = "error", "Reverted"
    assert tr._normalise_item("native", 1, failed, c, drops) is None and drops["failed"] == 1
    bad_internal = internal(addr(A), C, 1)
    bad_internal["success"] = False
    assert tr._normalise_item("internal", 1, bad_internal, c, drops) is None and drops["failed"] == 2
    self_tx = native(addr(C), C, 1)
    assert tr._normalise_item("native", 1, self_tx, c, drops) is None and drops["self"] == 1
    base_eth = tr._normalise_item("native", 8453, native(addr(A), C, 0.5), c, drops)
    assert base_eth["symbol"] == "ETH" and base_eth["usd"] == 2000.0


def test_labels_come_from_metadata_tags():
    labels, match, is_scam = sender_info(FIXEDFLOAT)
    assert labels[0] == "FixedFloat: Hot Wallet 2"
    assert {"Poisoning Address", "Phish / Hack", "Exchange"} <= set(labels)
    assert is_scam is True
    assert label_flags(match, is_scam, POLICY["trace"]["label_keywords"]) == ["label:is_scam", "label:hack", "label:phish"]

    labels, match, is_scam = sender_info(RONIN_OBJ)
    assert labels == ["Ronin Bridge Exploiter", "SANCTIONED", "BLOCKED", "Exploit"]  # notes are not labels
    assert "OFAC Sanctioned" in match and "ronin-bridge-exploiter" in match  # meta.info and slugs
    # The note text says "hack", but notes are prose and are not matched.
    assert label_flags(match, is_scam, POLICY["trace"]["label_keywords"]) == ["label:exploit"]

    labels, match, is_scam = sender_info(IT[0]["from"])
    assert labels[:2] == ["Ronin Bridge V1", "MainchainGatewayProxy"]
    assert label_flags(match, is_scam, POLICY["trace"]["label_keywords"]) == []

    legacy = addr(A, public_tags=[{"display_name": "Tornado Cash: Router", "label": "tornado"}], ens_domain_name="x.eth")
    labels, match, _ = sender_info(legacy)
    assert labels == ["x.eth", "Tornado Cash: Router"]
    assert label_flags(match, False, ["tornado"]) == ["label:tornado"]


# ---------- Intercepta funder scans ----------


async def test_intercepta_funder_flags(make_tracer, respx_mock):
    scenario(respx_mock)
    mock_oracle(respx_mock)

    def qs(address, body, status=200):
        respx_mock.get(f"{INTERCEPTA}/api/public/v2/extension/account/{address.lower()}/quick-scan").mock(
            return_value=httpx.Response(status, json=body)
        )

    qs(A, {"toxicScore": 30, "traits": [{"name": "mixer_transfers", "risk": 50, "txsCount": 2, "description": "d"},
                                        {"name": "fake_phishing_transfer", "risk": 5, "txsCount": 9, "description": "d"}]})
    qs(B, {"toxicScore": 85, "traits": []})
    qs(D, {"status": 404}, status=404)  # unavailable evidence, never a clean score
    out = await make_tracer(intercepta_api_key=SecretStr("k")).trace(C)
    hop1 = {h["address"]: h for h in out.data["hop1"]}
    assert hop1[A]["flags"] == ["intercepta:mixer_transfers"]  # info traits do not flag
    assert hop1[A]["intercepta"] == {"toxicScore": 30, "traits": ["mixer_transfers", "fake_phishing_transfer"]}
    assert hop1[B]["flags"] == ["intercepta:toxic_score", "label:exploit"]
    assert hop1[D]["flags"] == [] and hop1[D]["intercepta"] is None
    # A is flagged now, so only D goes to hop 2 (its funder V is clean).
    assert {e["via"] for e in out.data["hop2"]} == {D}
    assert out.data["taint_usd"] == 13_000.0


async def test_reserve_skips_funder_scans(make_tracer, respx_mock):
    scenario(respx_mock)
    mock_oracle(respx_mock)
    tr = make_tracer(intercepta_api_key=SecretStr("k"))
    tr.intercepta.cache.incr(QUOTA_KEY, 950)
    out = await tr.trace(C)  # no Intercepta route is mocked: any call would fail the test
    notes = " | ".join(out.data["notes"])
    assert "Intercepta funder scans skipped for 3 senders" in notes
    assert out.data["taint_pct"] == 59.52  # oracle and labels still flag


# ---------- hosts, failures, budget ----------


async def test_pro_api_host_and_key_never_in_urls(make_tracer, respx_mock):
    for feed in ("token-transfers", "transactions", "internal-transactions"):
        respx_mock.route(method="GET", host="api.blockscout.com", path=f"/1/api/v2/addresses/{C}/{feed}").mock(
            return_value=httpx.Response(200, json=page(usdc(addr(A), C, 10)) if feed == "token-transfers" else EMPTY)
        )
        respx_mock.route(method="GET", host="api.blockscout.com", path=f"/8453/api/v2/addresses/{C}/{feed}").mock(
            return_value=httpx.Response(200, json=EMPTY)
        )
    mock_oracle(respx_mock)
    out = await make_tracer(blockscout_api_key=SecretStr("proapi_secret"), trace_enable_hop2=False).trace(C)
    assert out.status == "ok" and out.data["inbound_usd_traced"] == 10.0
    sent = [c.request.url for c in respx_mock.calls if c.request.url.host == "api.blockscout.com"]
    assert len(sent) == 6 and all(u.params["apikey"] == "proapi_secret" for u in sent)
    assert {u.path.split("/")[1] for u in sent} == {"1", "8453"}
    native_call = next(u for u in sent if u.path.endswith("/transactions"))
    assert native_call.params["sort"] == "value" and native_call.params["order"] == "desc"
    dumped = out.model_dump_json()
    assert "proapi_secret" not in dumped
    assert all(s["url"].startswith("https://api.blockscout.com/") for s in out.raw["sources"])


async def test_partial_failure_is_ok_with_notes(make_tracer, respx_mock):
    scenario(respx_mock)
    for feed in ("token-transfers", "transactions", "internal-transactions"):
        respx_mock.route(method="GET", host="base.blockscout.com", path=f"/api/v2/addresses/{C}/{feed}").mock(
            return_value=httpx.Response(403, text="<html><title>Just a moment...</title></html>")
        )
    mock_oracle(respx_mock)
    out = await make_tracer(trace_enable_hop2=False).trace(C)
    assert out.status == "ok"
    assert out.summary.endswith("partial: 3 of 6 feeds failed")
    assert any(n.startswith("Base ERC-20 transfers not traced: HTTP 403 (bot challenge") for n in out.data["notes"])


async def test_all_feeds_failing_is_an_error(make_tracer, respx_mock):
    respx_mock.route(method="GET", host="eth.blockscout.com").mock(return_value=httpx.Response(404, json={}))
    respx_mock.route(method="GET", host="base.blockscout.com").mock(side_effect=httpx.ConnectError("down"))
    out = await make_tracer().trace(C)
    assert out.status == "error" and out.data is None
    assert out.error.startswith("no Blockscout data")


async def test_429_is_retried(make_tracer, respx_mock):
    scenario(respx_mock)
    respx_mock.route(method="GET", host="eth.blockscout.com", path=f"/api/v2/addresses/{C}/token-transfers").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=page(usdc(addr(A), C, 1000)))]
    )
    mock_oracle(respx_mock)
    out = await make_tracer(trace_enable_hop2=False).trace(C)
    assert out.data["inbound_usd_traced"] == 21_000.0


async def test_hop2_timeout_returns_hop1_result(make_tracer, respx_mock, monkeypatch):
    scenario(respx_mock)
    mock_oracle(respx_mock)

    async def slow_hop2(self, *args, **kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(Tracer, "_hop2", slow_hop2)
    out = await make_tracer(budget_s=1.6).trace(C)
    assert out.status == "ok"
    assert "hop 2 timed out; hop-1 result only" in out.data["notes"]
    assert out.data["hop2"] == [] and out.data["taint_pct"] == 57.14
    assert out.latency_ms < 2000


async def test_hop2_skipped_when_budget_is_short(make_tracer, respx_mock, monkeypatch):
    scenario(respx_mock)
    mock_oracle(respx_mock)
    monkeypatch.setattr(tracer_mod, "HOP2_MIN_S", 100.0)
    out = await make_tracer().trace(C)
    assert "hop 2 skipped: time budget used by hop 1; hop-1 result only" in out.data["notes"]


async def test_invalid_address(make_tracer):
    out = await make_tracer().trace("nope")
    assert out.status == "error"


async def test_rate_limiter_allows_a_burst_then_paces():
    limiter = _RateLimiter(rate=10.0, burst=4)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    for _ in range(4):
        assert await limiter.acquire(max_wait=1.0)
    assert loop.time() - t0 < 0.05  # the burst is immediate
    assert await limiter.acquire(max_wait=1.0)
    assert loop.time() - t0 >= 0.09  # the 5th waits about 1 / rate
    assert await limiter.acquire(max_wait=0.0) is False  # would have to wait: refused

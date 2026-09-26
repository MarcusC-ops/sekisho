"""scripts/setup_multibaas.py sends the right requests, is idempotent, keeps the webhook
secret out of stdout, and --dry-run sends nothing (respx only)."""

import importlib.util
import json

import httpx
import pytest
from pydantic import SecretStr

from sekisho_gate.config import REPO_ROOT, Settings

pytestmark = pytest.mark.respx(assert_all_called=False)  # unmatched requests still fail

MB = "https://sekisho.multibaas.test"
API = MB + "/api/v0"
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
SECRET = "whsec_9f8e7d6c5b4a"
REGISTRY = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ESCROW = "0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512"


def load_script():
    spec = importlib.util.spec_from_file_location("setup_multibaas", REPO_ROOT / "scripts" / "setup_multibaas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = load_script()


def ok(result=None, status=200):
    return httpx.Response(status, json={"status": status, "message": "success", "result": result})


def not_found():
    return httpx.Response(404, json={"status": 404, "message": "Not Found"})


def make_settings(**overrides) -> Settings:
    values = dict(_env_file=None, mb_url=MB, mb_admin_api_key=SecretStr("mb-admin-key"),
                  public_gate_url="https://tunnel.example.com", console_origin="http://localhost:3000",
                  usdc_address=USDC)
    values.update(overrides)
    return Settings(**values)


def linked(alias, address, label):
    return ok({"alias": alias, "address": address, "chain": "84532",
               "contracts": [{"label": label, "name": label, "version": "1.0"}]})


def mock_common(respx_mock):
    respx_mock.get(API + "/chains/ethereum/addresses/compliance_registry").mock(
        return_value=linked("compliance_registry", REGISTRY, "compliance_registry"))
    respx_mock.get(API + "/chains/ethereum/addresses/compliance_escrow").mock(
        return_value=linked("compliance_escrow", ESCROW, "compliance_escrow"))
    routes = {}
    for name in ("exposure_by_payee", "released_by_payee"):
        routes[f"put {name}"] = respx_mock.put(API + f"/queries/{name}").mock(return_value=ok())
        routes[f"results {name}"] = respx_mock.get(API + f"/queries/{name}/results").mock(return_value=ok({"rows": []}))
    return routes


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text("MB_URL=https://sekisho.multibaas.test\nMB_WEBHOOK_SECRET=\nPUBLIC_GATE_URL=x\n")
    return path


def body(route, i=-1):
    return json.loads(route.calls[i].request.content)


def test_fresh_deployment_sends_the_right_requests(respx_mock, env_file, capsys):
    routes = mock_common(respx_mock)
    respx_mock.get(API + "/contracts/erc20").mock(return_value=not_found())
    upload = respx_mock.post(API + "/contracts/erc20").mock(return_value=ok({"label": "erc20", "version": "1.0"}))
    respx_mock.get(API + "/chains/ethereum/addresses/usdc").mock(return_value=not_found())
    alias = respx_mock.post(API + "/chains/ethereum/addresses").mock(return_value=ok({"alias": "usdc"}, 201))
    link = respx_mock.post(API + "/chains/ethereum/addresses/usdc/contracts").mock(return_value=ok({"alias": "usdc"}))
    respx_mock.get(API + "/webhooks").mock(return_value=ok([]))
    hook = respx_mock.post(API + "/webhooks").mock(return_value=ok({"id": 1, "label": "sekisho-gate", "secret": SECRET}))
    respx_mock.get(API + "/cors").mock(return_value=ok([]))
    cors = respx_mock.post(API + "/cors").mock(return_value=ok())

    with httpx.Client() as http:
        code = setup.main(["--env-file", str(env_file)], http=http, settings=make_settings())
    out = capsys.readouterr()
    assert code == 0, out.out + out.err

    # Step 4: ABI upload (rawAbi is a JSON string), alias, link with event sync off.
    up = body(upload)
    assert (up["label"], up["contractName"], up["version"]) == ("erc20", "ERC20", "1.0")
    # MultiBaas rejects an omitted bytecode value even for an ABI-only upload.
    # The upload API calls this field `bin`, matching forge-multibaas.
    assert up["bin"] == "0x"
    assert up["language"] == "solidity"
    abi = json.loads(up["rawAbi"])
    assert {e["name"] for e in abi} == {"approve", "allowance", "balanceOf", "decimals", "transfer", "Transfer"}
    assert body(alias) == {"alias": "usdc", "address": USDC}
    assert body(link) == {"label": "erc20", "version": "1.0"}  # no startingBlock: sync off
    assert upload.calls.last.request.headers["Authorization"] == "Bearer mb-admin-key"

    # Step 5: webhook, and its secret in .env but never on screen.
    assert body(hook) == {"label": "sekisho-gate", "url": "https://tunnel.example.com/webhooks/multibaas",
                          "subscriptions": ["event.emitted"]}
    text = env_file.read_text()
    assert f"MB_WEBHOOK_SECRET={SECRET}\n" in text
    assert text.startswith("MB_URL=https://sekisho.multibaas.test\n") and "PUBLIC_GATE_URL=x\n" in text
    assert SECRET not in out.out and SECRET not in out.err

    # Step 6: Event Queries with a bare eventName, inputs by index, lowercase aliases.
    exposure = body(routes["put exposure_by_payee"])
    assert exposure == {
        "events": [{
            "eventName": "Held",
            "select": [{"type": "input", "inputIndex": 3, "alias": "payee"},
                       {"type": "input", "inputIndex": 4, "alias": "total", "aggregator": "add"}],
            "filter": {"fieldType": "contract_address_alias", "operator": "equal", "value": "compliance_escrow"},
        }],
        "groupBy": "payee", "orderBy": "total", "order": "DESC",
    }
    released = body(routes["put released_by_payee"])
    assert released["events"][0]["eventName"] == "Released"
    assert [s["inputIndex"] for s in released["events"][0]["select"]] == [2, 3]

    # CORS.
    assert body(cors) == {"origin": "http://localhost:3000"}


def test_rerun_is_idempotent(respx_mock, env_file, capsys):
    env_file.write_text(f"MB_WEBHOOK_SECRET={SECRET}\n")
    mock_common(respx_mock)
    respx_mock.get(API + "/contracts/erc20").mock(return_value=ok({"label": "erc20", "version": "1.0"}))
    respx_mock.get(API + "/chains/ethereum/addresses/usdc").mock(return_value=linked("usdc", USDC.lower(), "erc20"))
    respx_mock.get(API + "/webhooks").mock(return_value=ok([{
        "id": 4, "label": "sekisho-gate", "url": "https://tunnel.example.com/webhooks/multibaas",
        "subscriptions": ["event.emitted"], "secret": SECRET}]))
    respx_mock.get(API + "/cors").mock(return_value=ok([{"id": 1, "origin": "http://localhost:3000"}]))
    before = env_file.read_text()

    with httpx.Client() as http:
        assert setup.main(["--env-file", str(env_file)], http=http, settings=make_settings()) == 0
    posts = [c.request for c in respx_mock.calls if c.request.method in ("POST", "DELETE")]
    assert posts == []  # nothing created twice (the queries are PUT, which is create-or-update)
    assert env_file.read_text() == before
    assert SECRET not in capsys.readouterr().out


def test_update_webhook_repoints_it(respx_mock, env_file, capsys):
    mock_common(respx_mock)
    respx_mock.get(API + "/contracts/erc20").mock(return_value=ok({"label": "erc20"}))
    respx_mock.get(API + "/chains/ethereum/addresses/usdc").mock(return_value=linked("usdc", USDC, "erc20"))
    respx_mock.get(API + "/cors").mock(return_value=ok([{"id": 1, "origin": "http://localhost:3000"}]))
    respx_mock.get(API + "/webhooks").mock(return_value=ok([{
        "id": 4, "label": "sekisho-gate", "url": "https://old-tunnel.example.com/webhooks/multibaas",
        "subscriptions": ["event.emitted"], "secret": "old-secret"}]))
    put = respx_mock.put(API + "/webhooks/4").mock(return_value=ok({"id": 4, "secret": SECRET}))

    with httpx.Client() as http:
        assert setup.main(["--env-file", str(env_file)], http=http, settings=make_settings()) == 0
    assert put.call_count == 0  # without the flag it only warns
    assert "--update-webhook" in capsys.readouterr().out

    with httpx.Client() as http:
        assert setup.main(["--env-file", str(env_file), "--update-webhook"], http=http, settings=make_settings()) == 0
    assert body(put) == {"label": "sekisho-gate", "url": "https://tunnel.example.com/webhooks/multibaas",
                         "subscriptions": ["event.emitted"]}
    assert f"MB_WEBHOOK_SECRET={SECRET}\n" in env_file.read_text()


def test_query_falls_back_to_the_full_signature(respx_mock, env_file):
    mock_common(respx_mock)
    respx_mock.get(API + "/contracts/erc20").mock(return_value=ok({"label": "erc20"}))
    respx_mock.get(API + "/chains/ethereum/addresses/usdc").mock(return_value=linked("usdc", USDC, "erc20"))
    respx_mock.get(API + "/webhooks").mock(return_value=ok([{
        "id": 4, "label": "sekisho-gate", "url": "https://tunnel.example.com/webhooks/multibaas",
        "subscriptions": ["event.emitted"], "secret": SECRET}]))
    respx_mock.get(API + "/cors").mock(return_value=ok([]))
    respx_mock.post(API + "/cors").mock(return_value=ok())
    put = respx_mock.put(API + "/queries/exposure_by_payee").mock(return_value=ok())
    respx_mock.get(API + "/queries/exposure_by_payee/results").mock(side_effect=[
        httpx.Response(400, json={"status": 400, "message": "event Held not found"}),
        ok({"rows": []}),
    ])
    with httpx.Client() as http:
        assert setup.main(["--env-file", str(env_file)], http=http, settings=make_settings()) == 0
    names = [body(put, i)["events"][0]["eventName"] for i in range(put.call_count)]
    assert names == ["Held", "Held(uint256,bytes32,address,address,uint256)"]


def test_usdc_alias_pointing_elsewhere_is_reported(respx_mock, env_file, capsys):
    mock_common(respx_mock)
    respx_mock.get(API + "/contracts/erc20").mock(return_value=ok({"label": "erc20"}))
    respx_mock.get(API + "/chains/ethereum/addresses/usdc").mock(
        return_value=linked("usdc", "0x0000000000000000000000000000000000000001", "erc20"))
    respx_mock.get(API + "/webhooks").mock(return_value=ok([]))
    respx_mock.post(API + "/webhooks").mock(return_value=ok({"id": 1, "secret": SECRET}))
    respx_mock.get(API + "/cors").mock(return_value=ok([]))
    respx_mock.post(API + "/cors").mock(return_value=ok())
    with httpx.Client() as http:
        assert setup.main(["--env-file", str(env_file)], http=http, settings=make_settings()) == 1
    assert "points at 0x0000000000000000000000000000000000000001" in capsys.readouterr().err


def test_dry_run_sends_nothing_and_redacts(respx_mock, env_file, capsys):
    before = env_file.read_text()
    with httpx.Client() as http:  # no routes: any real request would fail the test
        assert setup.main(["--dry-run", "--env-file", str(env_file)], http=http, settings=make_settings()) == 0
    out = capsys.readouterr().out
    assert len(respx_mock.calls) == 0
    assert env_file.read_text() == before
    assert "mb-admin-key" not in out and "Bearer ***" in out
    for line in ("POST https://sekisho.multibaas.test/api/v0/contracts/erc20",
                 "POST https://sekisho.multibaas.test/api/v0/chains/ethereum/addresses/usdc/contracts",
                 "POST https://sekisho.multibaas.test/api/v0/webhooks",
                 "PUT https://sekisho.multibaas.test/api/v0/queries/exposure_by_payee",
                 "PUT https://sekisho.multibaas.test/api/v0/queries/released_by_payee",
                 "POST https://sekisho.multibaas.test/api/v0/cors"):
        assert line in out


def test_missing_credentials_exit_2(env_file, capsys):
    s = make_settings(mb_url="https://<deployment-id>.multibaas.com")
    assert setup.main(["--env-file", str(env_file)], settings=s) == 2


def test_update_env_file_appends_and_keeps_mode(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\nB=2")
    path.chmod(0o600)
    setup.update_env_file(path, "MB_WEBHOOK_SECRET", "s3cret")
    assert path.read_text() == "A=1\nB=2\nMB_WEBHOOK_SECRET=s3cret\n"
    setup.update_env_file(path, "B", "has space")
    assert 'B="has space"\n' in path.read_text()
    assert setup.read_env_value(path, "B") == "has space"
    assert (path.stat().st_mode & 0o777) == 0o600

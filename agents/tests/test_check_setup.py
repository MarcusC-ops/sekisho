"""Offline setup diagnostics must reject unsafe/missing config without leaking secrets."""
from eth_account import Account

from scripts.check_setup import check_setup, configured
from sekisho_gate.config import Settings


def test_placeholder_values_are_not_configured():
    assert not configured("")
    assert not configured("https://<deployment-id>.multibaas.com")
    assert configured("https://example.multibaas.com")


def test_missing_settings_produce_failures_without_private_values(tmp_path):
    settings = Settings(_env_file=None, llm_provider="none")
    checks = dict(check_setup(settings, tmp_path))
    assert not checks["INTERCEPTA_API_KEY"]
    assert not checks["four distinct role wallets"]
    assert checks["policy file exists"]


def test_mainnet_and_duplicate_roles_fail_even_with_valid_keys(tmp_path):
    # Ephemeral test key stays in memory and is never printed or written.
    key = Account.create().key.hex()
    settings = Settings(_env_file=None, deployer_pk=key, gate_screener_pk=key,
                        officer_pk=key, buyer_agent_pk=key, chain_id=1, x402_network="eip155:1")
    checks = dict(check_setup(settings, tmp_path))
    assert checks["BUYER_AGENT_PK valid"]
    assert not checks["four distinct role wallets"]
    assert not checks["testnet contract and payment chains"]
    assert key not in str(checks)


def test_fixture_config_is_detected_without_modification(tmp_path):
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    config = dashboard / ".env.local"
    content = "export NEXT_PUBLIC_USE_FIXTURES='true' # UI development only\n"
    config.write_text(content)
    settings = Settings(_env_file=None, llm_provider="none")
    assert not dict(check_setup(settings, tmp_path))["dashboard fixtures off in local configuration"]
    assert config.read_text() == content


def test_minimum_setup_keeps_safety_checks_but_drops_stretch_requirements(tmp_path):
    settings = Settings(_env_file=None, llm_provider="none")
    checks = dict(check_setup(settings, tmp_path, minimum=True))
    assert "BLOCKSCOUT_API_KEY" not in checks
    assert "VENDOR_MIXER_PAYTO valid address" not in checks
    assert not checks["INTERCEPTA_API_KEY"]
    assert not checks["SEKISHO_OPERATOR_TOKEN"]
    assert checks["canonical Base Sepolia USDC"]
    assert checks["testnet contract and payment chains"]


def test_different_testnet_and_lookalike_token_do_not_pass_setup(tmp_path):
    settings = Settings(_env_file=None, chain_id=11155111, x402_network="eip155:11155111",
                        usdc_address="0x" + "11" * 20)
    checks = dict(check_setup(settings, tmp_path, minimum=True))
    assert not checks["canonical Base Sepolia USDC"]
    assert not checks["testnet contract and payment chains"]

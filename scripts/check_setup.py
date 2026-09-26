"""Offline setup checks. Prints names/status only, never credentials or private keys.

This does not prove that credentials work or that contracts are deployed. Follow with
make smoke and the live rehearsal once all local configuration checks pass.
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path
from urllib.parse import urlparse

from eth_account import Account
from eth_utils import is_address

from sekisho_gate.config import REPO_ROOT, Settings


def configured(value: object) -> bool:
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    text = str(value).strip()
    return bool(text) and "<" not in text and ">" not in text


def check_setup(settings: Settings, root: Path = REPO_ROOT, *, minimum: bool = False) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    required_keys = ["intercepta_api_key", "mb_admin_api_key", "mb_webhook_secret", "sekisho_operator_token"]
    if not minimum:
        required_keys.append("blockscout_api_key")
    for name in required_keys:
        checks.append((name.upper(), configured(getattr(settings, name))))
    for name in ("mb_url", "public_gate_url"):
        value = getattr(settings, name)
        checks.append((name.upper(), configured(value) and urlparse(value).scheme == "https" and bool(urlparse(value).netloc)))
    addresses: list[str] = []
    for name in ("deployer_pk", "gate_screener_pk", "officer_pk", "buyer_agent_pk"):
        value = getattr(settings, name).get_secret_value()
        try:
            addresses.append(Account.from_key(value).address)
            valid = True
        except (ValueError, TypeError):
            valid = False
        checks.append((name.upper() + " valid", valid))
    checks.append(("four distinct role wallets", len(addresses) == 4 and len(set(addresses)) == 4))
    counterparties = ["vendor_clean_payto", "vendor_sanctioned_payto"]
    if not minimum:
        counterparties += ["vendor_mixer_payto", "rogue_payer_addr"]
    for name in counterparties:
        checks.append((name.upper() + " valid address", is_address(getattr(settings, name))))
    try:
        payment_chain = settings.x402_chain_id
    except (ValueError, IndexError):
        payment_chain = None
    checks.append(("testnet contract and payment chains", settings.chain_id == 84532 and payment_chain == 84532))
    checks.append(("canonical Base Sepolia USDC", settings.usdc_address.lower() == "0x036cbd53842c5426634e7929541ec2318f3dcf7e"))
    checks.append(("policy file exists", settings.policy_path.is_file()))
    checks.append(("fault injection off for normal rehearsal", not settings.fault_inject))
    if settings.llm_provider != "none":
        name = "anthropic_api_key" if settings.llm_provider == "anthropic" else "openai_api_key"
        checks.append((name.upper() + " (or set LLM_PROVIDER=none)", configured(getattr(settings, name))))
    # Check dashboard environment files without importing the demo runner or printing values.
    import os

    fixtures = os.environ.get("NEXT_PUBLIC_USE_FIXTURES", "").strip() == "true"
    for path in (root / "dashboard").glob(".env*"):
        if path.name.endswith(".example") or not path.is_file():
            continue
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip().removeprefix("export ").strip() == "NEXT_PUBLIC_USE_FIXTURES":
                fixtures |= value.split("#")[0].strip().strip("\"'") == "true"
    checks.append(("dashboard fixtures off in local configuration", not fixtures))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum", action="store_true", help="S1/S3 qualification setup; trace key and S2/S5 addresses optional")
    args = parser.parse_args()
    try:
        settings = Settings()
    except Exception:
        # Pydantic's full exception may include input values: never print it here.
        print("FAIL: invalid settings. Check .env types against .env.example; values are hidden.")
        return 1
    checks = check_setup(settings, minimum=args.minimum)
    for label, ok in checks:
        print(f"{'PASS' if ok else 'MISSING/INVALID'}  {label}")
    failed = sum(not ok for _, ok in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} local configuration checks passed.")
    print("This is an offline check. Credential validity, balances, deployments and webhooks still need make smoke.")
    return int(failed > 0)


if __name__ == "__main__":
    sys.exit(main())

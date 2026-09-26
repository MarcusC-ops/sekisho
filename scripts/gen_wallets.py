"""Generate fresh testnet-only keys for the four Sekisho roles into .env (PRD 7.2).

Creates .env from .env.example if it doesn't exist, fills only the *_PK entries that
are empty, and prints each role's address (never its key) so you can fund it.
Run: make wallets
"""

import re
from pathlib import Path

from eth_account import Account

ROOT = Path(__file__).resolve().parents[1]
ENV, EXAMPLE = ROOT / ".env", ROOT / ".env.example"
ROLES = {
    "DEPLOYER_PK": "deploys contracts: needs Base Sepolia ETH",
    "GATE_SCREENER_PK": "writes attestations: needs Base Sepolia ETH",
    "OFFICER_PK": "compliance officer: needs Base Sepolia ETH",
    "BUYER_AGENT_PK": "treasury agent: needs test USDC and a little ETH",
}


def main() -> None:
    if not ENV.exists():
        ENV.write_text(EXAMPLE.read_text())
    ENV.chmod(0o600)
    text = ENV.read_text()
    for var, role in ROLES.items():
        match = re.search(rf"^{var}=(.*)$", text, flags=re.M)
        current = match.group(1).split("#")[0].strip() if match else ""
        if current:
            account, status = Account.from_key(current), "kept"
        else:
            account, status = Account.create(), "new"
            line = f"{var}=0x{account.key.hex().removeprefix('0x')}"
            if match:
                text = re.sub(rf"^{var}=.*$", lambda _: line, text, count=1, flags=re.M)
            else:
                text += f"\n{line}\n"
        print(f"{var:17s} {account.address}  {status:4s}  {role}")
    ENV.write_text(text)
    print("\nFund them: test USDC from https://faucet.circle.com (Base Sepolia) to the treasury")
    print("agent, and Base Sepolia ETH from https://ethglobal.com/faucet/base-sepolia-84532 to all four.")


if __name__ == "__main__":
    main()

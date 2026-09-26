"""Screen only; never signs or sends a payment. Run with a counterparty address."""

import asyncio
import sys

from sekisho import SekishoClient, SekishoError

# website-example:start
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


async def screen_payment(counterparty, gate_url="http://localhost:8000"):
    async with SekishoClient(gate_url) as gate:
        try:
            decision = await gate.screen(
                counterparty=counterparty,
                direction="outbound",
                amount="50000",  # 0.05 USDC, in atomic units
                asset=USDC,
                payment_chain_id=84532,  # Base Sepolia
                source="direct",
                agent_id="my-agent",
            )
        except SekishoError:
            return "HOLD"  # No usable decision: do not sign.
        return decision.verdict
# website-example:end


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python sdk/examples/screen_before_signing.py 0xCOUNTERPARTY")
    verdict = asyncio.run(screen_payment(sys.argv[1]))
    print(f"{verdict}: screening only; no payment signed or sent.")
    raise SystemExit(0 if verdict == "ALLOW" else 1)

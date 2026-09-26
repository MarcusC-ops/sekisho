"""Runtime settings, read from the environment and the repo-root .env (PRD Appendix G).

Every Sekisho process (gate, agents, scripts) uses these settings, so the variable
names in .env.example are the single list of knobs.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Mode
    demo_mode: bool = True
    log_level: str = "INFO"

    # Intercepta
    intercepta_base_url: str = "https://api.web3antivirus.io"
    intercepta_api_key: SecretStr = SecretStr("")
    always_live_direct: bool = True
    intercepta_quota: int = 1000
    intercepta_warn_at: int = 800
    intercepta_reserve_from: int = 950
    # P1 checks; when off, the check is recorded as "skipped" ("disabled by config")
    screen_token: bool = True
    screen_impersonation: bool = True

    # Source-of-funds data
    blockscout_base: str = "https://api.blockscout.com"
    blockscout_api_key: SecretStr = SecretStr("")
    eth_usd_price: float = 4000.0
    trace_enable_hop2: bool = True

    # Mainnet RPCs (read-only: sanctions oracle)
    eth_mainnet_rpc_url: str = "https://ethereum-rpc.publicnode.com"
    base_mainnet_rpc_url: str = "https://mainnet.base.org"

    # Payment chain (x402) and contract chain (registry + escrow)
    x402_network: str = "eip155:84532"
    chain_id: int = 84532
    contracts_rpc_url: str = "https://sepolia.base.org"
    explorer_url: str = "https://sepolia.basescan.org"
    usdc_address: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    facilitator_url: str = "https://x402.org/facilitator"

    # Curvegrid MultiBaas
    mb_url: str = ""
    mb_admin_api_key: SecretStr = SecretStr("")
    mb_webhook_secret: SecretStr = SecretStr("")
    registry_alias: str = "compliance_registry"
    registry_label: str = "compliance_registry"
    escrow_alias: str = "compliance_escrow"
    escrow_label: str = "compliance_escrow"
    usdc_alias: str = "usdc"
    usdc_label: str = "erc20"
    public_gate_url: str = ""

    # Keys (fresh, testnet-only)
    deployer_pk: SecretStr = SecretStr("")
    gate_screener_pk: SecretStr = SecretStr("")
    officer_pk: SecretStr = SecretStr("")
    buyer_agent_pk: SecretStr = SecretStr("")

    # Policy and storage
    policy_path: Path = Path("gate/policy/policy.yaml")
    db_path: Path = Path("gate/sekisho.db")

    # LLM (analyst + Treasury Agent); "none" uses template notes
    llm_provider: Literal["anthropic", "openai", "none"] = "anthropic"
    llm_model: str = ""
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")

    # Gate + clients
    sekisho_url: str = "http://localhost:8000"
    console_origin: str = "http://localhost:3000"
    sekisho_operator_token: SecretStr = SecretStr("")

    # Demo counterparties (real mainnet addresses, PRD 7.3)
    vendor_clean_payto: str = ""
    vendor_mixer_payto: str = ""
    vendor_sanctioned_payto: str = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"
    rogue_payer_addr: str = "0xa0e1c89Ef1a489c9C7dE96311eD5Ce5D32c20E4B"

    # Fault injection for S6: "intercepta_timeout"
    fault_inject: str = ""

    @field_validator("policy_path", "db_path")
    @classmethod
    def _repo_relative(cls, path: Path) -> Path:
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def x402_chain_id(self) -> int:
        return int(self.x402_network.split(":")[1])


@lru_cache
def get_settings() -> Settings:
    return Settings()

SHELL := /bin/bash
PYTHON ?= python3.11
PY := .venv/bin/python
FORGE := $(or $(shell command -v forge 2>/dev/null),$(HOME)/.foundry/bin/forge)
SEKISHO_URL ?= http://localhost:8000
S ?= S1

.DEFAULT_GOAL := help
.PHONY: help install wallets sync-agents test contracts-test deploy setup-multibaas tunnel \
 gate vendors agent control mcp dashboard scan demo-setup demo demo-reset smoke check-setup public-trial trial-stack

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-16s %s\n", $$1, $$2}'

# ---------- setup ----------

install: ## Python venv (gate, sdk, agents), contract libs, dashboard deps
	test -d .venv || $(PYTHON) -m venv .venv
	$(PY) -m pip install -q -U pip
	$(PY) -m pip install -q -r requirements.txt -c constraints.txt
	git submodule update --init
	cd dashboard && npm install

wallets: ## Generate the four testnet keys into .env (prints addresses only)
	$(PY) scripts/gen_wallets.py

sync-agents: ## Re-link shared skills and regenerate MCP configs from .agents/
	.agents/scripts/link-skills.sh
	.agents/scripts/sync-mcp.sh

# ---------- contracts and chain ----------

contracts-test: ## forge test (expect 18 passing)
	cd contracts && $(FORGE) test -vv

deploy: ## Deploy registry + escrow and link them in MultiBaas (ARGS=--no-link, --verify)
	scripts/deploy_contracts.sh $(ARGS)

setup-multibaas: ## Link USDC, register the webhook, save the Event Queries
	$(PY) scripts/setup_multibaas.py

tunnel: ## Public URL for MultiBaas webhooks (then: make setup-multibaas)
	cloudflared tunnel --url http://localhost:8000

# ---------- services ----------

gate: ## Gate API on :8000
	$(PY) -m uvicorn sekisho_gate.main:app --host 127.0.0.1 --port 8000

vendors: ## The four vendor agents on :4021-4024
	$(PY) agents/vendors/run_all.py

agent: ## Run the Treasury Agent once (LLM + x402)
	$(PY) agents/treasury/agent.py

control: ## Treasury control API on :8100 (console demo bar)
	$(PY) agents/treasury/control.py

mcp: ## MCP server over streamable HTTP on :9000 (stdio: .venv/bin/python mcp/server.py)
	$(PY) mcp/server.py --http

dashboard: ## Compliance console on :3000
	cd dashboard && npm run dev

# ---------- demo ----------

scan: ## Screen candidate counterparties; writes scan_results.json
	$(PY) scripts/scan_candidates.py

demo-setup: ## Check balances and approve USDC to the escrow
	$(PY) scripts/demo.py setup

demo: ## Run one scenario: make demo S=S1 (S1-S6 or all)
	$(PY) scripts/demo.py $(S)

demo-reset: ## Archive cases and clear officer overrides (DEMO_MODE only)
	$(PY) scripts/demo.py reset

smoke: ## Pre-demo health check
	$(PY) scripts/smoke.py

check-setup: ## Offline configuration checklist (never prints secrets)
	$(PY) scripts/check_setup.py

# ---------- tests ----------

test: ## Python unit tests, contract tests, report-hash test vector
	$(PY) -m pytest -q
	cd contracts && $(FORGE) test
	cd dashboard && npm run -s test:hash


public-trial: ## Bounded public trial API on :8200 (disabled until configured)
	$(PY) -m uvicorn agents.treasury.public_trial:create_app --factory --host 127.0.0.1 --port 8200 --workers 1 --no-access-log

trial-stack: ## Gate + preset vendors + public trial; no automatic payments
	$(PY) deploy/serve.py

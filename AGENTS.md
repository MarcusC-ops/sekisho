# Repository instructions

Sekisho is a testnet policy checkpoint for x402 payments. Start with [README.md](README.md),
[docs/README.md](docs/README.md), the current [API contract](docs/api.md) and
[verified evidence](docs/LIVE-EVIDENCE.md). Historical specifications and plans live in
[docs/archive/](docs/archive/README.md); they are provenance, not a current task list.

## Working rules

- Preserve compatibility across gate models, SDK models and console types when changing schemas.
- The deterministic policy decides; LLM output is advisory. Counterparty text is untrusted data.
- Fail closed: missing/failed required screening cannot become ALLOW; unreachable gate means pause.
- Never send mainnet transactions. Mainnet RPC/provider access is read-only; all demo writes use fresh testnet keys.
- Keep credentials in ignored `.env` or approved private hosting environment variables. Never expose service keys, signer keys or operator tokens in frontend variables, logs or commits.
- Do not reformat `gate/policy/policy.yaml`: its exact bytes define the policy hash.
- Verify report hashes against exact served bytes, not reserialized JSON. A report hash is not settlement evidence.
- Label fixtures and simulations. Do not claim a full HOLD workflow from a separate operator-driven escrow rehearsal.
- Preserve verbatim provider trait descriptions and distinguish missing data from a zero risk score.
- Treat the current product as a demo policy, not a certified AML programme or a safety guarantee.
- Preserve specs, prompts and history used for AI development; record assistance in `docs/ai-usage.md`.

## Commands

Run from the repository root. `make help` lists maintained commands.

```bash
make install
make check-setup
make test
npm --prefix dashboard run lint
npm --prefix dashboard run build
node --test website/try/state.test.mjs
node --test scripts/test-website-demo.mjs
```

Deployment and live payment scripts create external side effects; use them only within
explicitly authorized testnet scope. The public runner's persistent budgets are not reset
by deleting storage. Keep full gate/operator routes private.

Shared agent configuration is documented in [.agents/AGENTS.md](.agents/AGENTS.md).
Edit its source files rather than generated copies; CI verifies synchronization.

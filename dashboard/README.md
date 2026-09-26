# Sekisho Compliance Console

Private operator console built with the Next.js App Router. It is not the public
trial and is not exposed by the Render trial service. Run all setup from the repository root;
see [the main README](../README.md) for live services and testnet configuration.

```bash
make dashboard                       # gate at localhost:8000, fixtures off
cd dashboard && npm run dev:fixtures  # browser-only UI development, fixture banner on
```

Routes: `/` live decisions; `/cases/[id]` evidence, officer actions and report verification;
`/review` pending holds; `/audit` recent onchain events; `/treasury` balances, Event Queries
and counterparties; `/policy` exact read-only YAML; `/integrate` SDK and MCP snippets.

All network reads use `lib/api.ts` and SWR. SSE updates the caches; reconnect refetches
missed data. Reports are hashed as exact served text, never reserialized JSON.
`fixtures/` contains synthetic development data and is never a substitute for live tests.

Environment (optional `dashboard/.env.local`):

```dotenv
NEXT_PUBLIC_GATE_URL=http://localhost:8000
NEXT_PUBLIC_TREASURY_CONTROL_URL=http://localhost:8100
NEXT_PUBLIC_EXPLORER_URL=https://sepolia.basescan.org
NEXT_PUBLIC_MAINNET_EXPLORER_URL=https://etherscan.io
NEXT_PUBLIC_USE_FIXTURES=false
```

These values are compiled at build time. Never add provider credentials or wallet
keys to this file or the browser. Privileged actions require the separate
`SEKISHO_OPERATOR_TOKEN` configured on the gate/controller. Enter that operator token
through the console's session control; it stays in tab memory and clears on reload.
Keep the console and full gate behind an authenticated operator network or tunnel.
The scenario bar calls the local control API; all compliance and chain data goes through
the gate. Live mode never falls back to synthetic fixtures on a failed request.

```bash
npm --prefix dashboard run lint
npm --prefix dashboard run build
npm --prefix dashboard run test:hash
```

Historical visual reference: [DESIGN.md](../docs/archive/DESIGN.md). Historical interaction reference:
[UX-CONTRACT.md](../docs/archive/UX-CONTRACT.md). `app/tokens.css` owns runtime design tokens.

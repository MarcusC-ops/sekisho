# AI usage

ETHGlobal's AI rule asks every project to say where and how AI tools were used, and to
commit the specs, prompts and plans behind AI-generated work. This is Sekisho's record,
kept up to date as the build goes.

## Tools

- **Codex**: compared the implementation with the supplied PRD and pitch plan, completed
  the missing console routes, added offline configuration checks, and updated setup and
  readiness documentation (prompt 10). Validated unit tests, builds, and browser fixture
  flows. This pass did not deploy contracts or claim live provider validation.
  A subsequent packaging pass (prompt 11) adapted the README, preserved the detailed
  setup guide, created vector/HTML brand assets, captured the real fixture console,
  and updated and read back GitHub description/topics. The user then supplied Investflow as a visual
  reference (prompt 12). Codex inspected it, wrote a Sekisho-specific brand brief, and
  generated an original checkpoint illustration with the built-in imagegen tool. Cover
  typography was composed in HTML and rendered with Chromium. Product screenshots
  are actual fixture-console captures, not generated images.
  Prompt 13 added the static public website from that direction and verified desktop,
  mobile, link, and keyboard behavior before Vercel publication. The gate, contracts,
  and live payment console were not deployed by the website release.
  Prompt 14 added a browser-only guided simulation using canonical UI fixtures, a
  tested fail-closed SDK example, and shared console theme changes. It refreshed
  actual fixture screenshots and rechecked desktop/mobile behavior. Live proof remained
  blocked on service credentials and fresh funded testnet wallets.
  Prompt 15 connected the existing Vercel project to GitHub, configured `website/`
  as its publishing root, and documented automatic production and preview deployments.

- **Claude Code** (Claude Opus 5.5, in the Claude desktop app): the lead engineering
  agent. It split the PRD into workstreams, ran parallel subagents for research and
  building, then reviewed, integrated, tested and committed their output. Every commit
  it made carries a `Co-Authored-By: Claude` trailer. On 26 September a separate Claude Code
  session audited the submission against ETHGlobal's rules and the partner prize
  requirements, then rewrote the README's opening, added the partner integration, team and
  provenance sections, and drafted [SUBMISSION.md](SUBMISSION.md) (prompt 16).
  A later Claude Code session took the project live on Base Sepolia (prompt 17): service
  configuration, contract deployment and MultiBaas linking, the live counterparty scan,
  the rehearsals and the verified-results documentation. Another session added
  `.github/workflows/vercel-deploy.yml`, which gets teammates' pushes to `main` deployed on
  the Hobby-plan Vercel project (prompt 18).
- **Claude** (runtime): the AI analyst writes advisory case notes, and the Treasury Agent
  reasons about which vendor data to buy. Both run behind a provider switch
  (`LLM_PROVIDER`), and the demo also works with `LLM_PROVIDER=none`. The AI never decides
  a verdict: the deterministic policy in `gate/policy/policy.yaml` does.

## Specs, plans and prompts (committed)

| File | What it is |
|---|---|
| [PRD.md](../PRD.md) | Product requirements, written by the team before any code; committed first |
| [PITCH_PLAN.md](../PITCH_PLAN.md) | Pitch and demo plan, written by the team |
| [docs/pitch-deck.md](pitch-deck.md) | The earlier "Wallet Audit Trail" concept that became Sekisho |
| [docs/api.md](api.md) | Gate API contract, written by the lead agent from PRD 9.11 so the workstreams could run in parallel |
| [docs/prompts/](prompts/README.md) | Every prompt: the team's instructions to the lead agent and the lead agent's prompts to each subagent |
| [docs/research/](research/) | Research subagents' memos checking the PRD's API assumptions against real sources (x402 and MCP SDKs; Intercepta, MultiBaas, Blockscout, Chainalysis; agent config conventions), with each correction marked |
| [AGENTS.md](../AGENTS.md) | Standing instructions that every coding agent in this repo reads |

## Where AI wrote code

| Area | Files | How it was made | Team review |
|---|---|---|---|
| Repo structure | `AGENTS.md`, `CLAUDE.md`, `.agents/`, `.pre-commit-config.yaml` | Lead agent, from the agent-agnostic repository guide the team supplied | pending |
| Scaffold | `Makefile`, `.env.example` (PRD Appendix G), packaging, `scripts/gen_wallets.py` | Lead agent | pending |
| Demo policy | `gate/policy/policy.yaml` | PRD Appendix D, byte for byte (hash verified) | pending |
| Contracts | `contracts/src/`, `contracts/test/`, `contracts/script/` | PRD Appendices A to C, which the team had already compiled and tested; installed and re-tested by a subagent (prompt 04) | pending |
| Gate | `gate/sekisho_gate/` | Subagents from PRD Section 9 (prompts 06, 07) | pending |
| SDK and vendor agents | `sdk/`, `agents/vendors/`, `agents/rogue/` | Subagent from PRD 10.1, 10.2, 10.4 (prompt 08) | pending |
| Treasury Agent, demo, MCP | `agents/treasury/`, `scripts/`, `mcp/` | Subagent from PRD 10.3 to 10.5 and 12 (prompt 09) | pending |
| Compliance Console | `dashboard/` | Subagent from PRD 10.6 (prompt 05) | pending |

Before submission, the team replaces each "pending" with who reviewed it, and confirms that
the contracts were deployed and tested by the team.

## Editorial website redesign (26 September 2026)

Codex implemented the user-approved Canvass-inspired branding direction directly in the static website: warm paper palette, editorial typography, everyday payment narrative, responsive diagrams, and sourced institutional-risk context. The four synthetic scenarios and generated SDK example were preserved. See [prompt and implementation plan](prompts/18-editorial-website.md). No Canvass artwork or template code was copied; diagrams are original. This pass does not establish live payment or provider validation.

## Vibrant shared identity (26 September 2026)

At the user's request, Codex applied a cohesive violet/coral/citrus identity to the public website and dashboard. Shared semantic tokens preserve verdict colours, fixture labels and readable operational data. Changes are CSS and refreshed fixture-console screenshots; payment behavior is unchanged. See [prompt and plan](prompts/19-vibrant-shared-brand.md). Verified dashboard build/type checking, lint, 45 report-hash checks, three website state tests, generated examples and desktop/mobile browser layouts across six dashboard routes.

## Codex MVP implementation pass — 26 September 2026

The team asked Codex to evaluate track viability, implement the minimum viable fixes,
parallelize independent work, and test the result. The team authorized fresh testnet
wallets and Base Sepolia transactions only and supplied a backend MultiBaas key locally.

Codex coordinated three parallel workstreams: payment controls, operator authentication,
and screening correctness. Their changes cover SDK/agent decision binding and spending
reservations; gate/control authentication and console token entry; screening deduplication
and missing-provider evidence. Follow-up work added testnet backend write restrictions
and receipt/event validation before payment/hold status changes. Codex integrated the
schemas, added minimum setup checks and the MVP checklist, and ran the combined tests.
The policy YAML bytes were preserved. No provider secrets were committed.

Verification: 446 Python tests, 18 contract tests, dashboard build/lint/type checks,
45 report-hash checks, and local operator-token browser checks. MultiBaas authentication
was checked against Base Sepolia. Live screening, deployment and payment remain pending
credentials/funding. Team review of these changes: **pending**.


## Browser trial and finalisation (26 September 2026)

At the team's request, Codex translated the first-user review into an execution plan and coordinated three parallel workstreams: public trial backend, guided website trial, and pitch/narration. Codex also reconciled earlier payment controls, corrected console financial-state wording, prepared persistent hosting configuration and independently reviewed the combined result. The public service defaults disabled; live provider/payment qualification remains pending. See [prompt](prompts/20-product-finalisation.md), [execution plan](FINALISATION-PLAN.md) and [evidence log](LIVE-EVIDENCE.md). Test results and limitations are recorded in readiness.md. Team review: pending.

With the subsequently supplied Intercepta and Blockscout keys, Codex validated live
read-only provider calls, generated a fresh testnet-only merchant key in ignored .env,
and exercised two 0.05 test-USDC x402 purchases and one blocked purchase. Both settled
transactions needed later receipt-report reconciliation; no extra signatures were
created for reconciliation. Contract attestation and hosted execution remain pending.
Codex updated the deck and public evidence panel with measured results and limitations.

After explicit team authorization and funding, Codex deployed the existing registry
and escrow on Base Sepolia, assigned roles, linked the contracts/USDC in MultiBaas,
and ran live clean/refused purchases plus an explicitly operator-driven escrow
rehearsal. Live integration exposed ABI upload and event-filter issues; Codex fixed
them with regression tests. A bounded webhook ingress was added for the hosted
runner while preserving private operator routes. No mainnet writes occurred.

After explicit approval to upload the existing credentials, Codex configured Render
through the team's Chrome session, connected the public trial URL and exercised the
actual hosted clean/refused flows in Chrome. The clean preset paid 0.05 test USDC;
the flagged preset refused signing. Read-only checks independently matched both
registry attestations and genuine webhook delivery history. Codex updated the public
proof panel, deployment evidence and pitch materials; provider-triggered full-gate
HOLD and new narration/video remain distinct unfinished items.

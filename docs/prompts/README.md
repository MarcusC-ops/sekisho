# Prompts

ETHGlobal requires the prompts behind AI-generated work to be committed. This folder
indexes the recorded development instructions. Paths inside historical prompt text
reflect the layout at that time; current specifications/plans are in [the archive](../archive/README.md).

## Team prompts to the lead agent

The build was driven from one Claude Code session (Claude Opus 5.5, Claude desktop app)
on Fri 25 Sep 2026, starting at 21:55 JST. The team's instructions, verbatim:

1. `https://gist.github.com/davidgibsonp/337be9b80b3f03eccd188235c287bb05 use this structure for this repo.`
   (the agent-agnostic repository guide behind `AGENTS.md` and `.agents/`)
2. `@"PRD (2).md" <original-repository> build this AML idea.` The PRD is
   committed as [PRD.md](../archive/PRD.md), with its companion [PITCH_PLAN.md](../archive/PITCH_PLAN.md).
3. `u can spawn as many subagents as you want by the way`
4. Answers to the lead agent's questions: commit small and often and push at each milestone;
   install the toolchain (Foundry, Python venv, npm).

## Subagent prompts

The lead agent split the PRD into workstreams and gave each one to a subagent. Every
subagent received its own prompt, then worked from `PRD.md`, [AGENTS.md](../../AGENTS.md)
and the API contract in [docs/api.md](../api.md). The lead agent reviewed, integrated and
committed the results.

| # | Subagent | Scope |
|---|---|---|
| 01 | [Verify x402 and MCP SDK APIs](01-verify-x402-and-mcp-sdk-apis.md) | Check the PRD's "confirm on day one" SDK details against x402 2.24.0 and mcp 2.2.0 |
| 02 | [Verify external service APIs](02-verify-external-service-apis.md) | Intercepta, MultiBaas, Blockscout, Chainalysis oracle, x402 facilitator, Base Sepolia USDC |
| 03 | [Research agent config conventions](03-research-agent-config-conventions.md) | AGENTS.md, skills and MCP formats for Claude Code, Cursor and Codex |
| 04 | [Build Foundry contracts workstream](04-build-foundry-contracts-workstream.md) | `contracts/`, deploy script |
| 05 | [Build Next.js compliance console](05-build-next-js-compliance-console.md) | `dashboard/` |
| 06 | [Build gate core](06-build-gate-core-policy-api-sse.md) | Policy engine, reports, pipeline, analyst, attestations, webhooks, API, SSE |
| 07 | [Build gate integration clients](07-build-gate-integration-clients.md) | Intercepta, sanctions oracle, source-of-funds tracer, MultiBaas client, MultiBaas setup |
| 08 | [Build SDK, x402 hooks and vendors](08-build-sdk-x402-hooks-and-vendors.md) | `sdk/`, vendor agents, spoofed payer |
| 09 | [Build treasury agent, demo, MCP](09-build-treasury-agent-demo-mcp.md) | Treasury Agent, demo runner, control API, scan and smoke scripts, MCP server |

The runtime prompts, for the AI analyst and the Treasury Agent, are PRD Appendix E. They
live in `gate/sekisho_gate/analyst/prompts.py` and `agents/treasury/prompts.py`.

## Codex continuation

[10 — Complete console and readiness](10-complete-console-and-readiness.md) records the
user's build assessment and continuation request, the completion plan, and verification
scope. This pass used no subagents.

[11 — Hackathon polish](11-hackathon-polish.md) records the requested README, brand assets,
fixture screenshots, GitHub metadata, and publication pass. This pass used no subagents.

[12 — Investflow direction](12-investflow-direction.md) records the user's new visual reference
and the project-specific design brief.

[13 — Vercel deployment](13-vercel-deployment.md) records the public landing page and
Vercel publication requested after the brand direction.

[14 — Guided product demo](14-guided-product-demo.md) records the approved website,
SDK example, console refinement, and live-proof readiness check.

## Later development and deployment

- [15 — Automatic Git deployments](15-automatic-git-deployments.md)
- [16 — Submission positioning](16-submission-positioning.md)
- [17 — Live stack rehearsal](17-live-stack-rehearsal.md)
- [18 — Teammate Vercel deploys](18-teammate-vercel-deploys.md)
- [18 — Editorial website](18-editorial-website.md)
- [19 — Shared vibrant brand](19-vibrant-shared-brand.md)
- [20 — Product finalisation](20-product-finalisation.md)
- [21 — Public release cleanup](21-public-release-cleanup.md)

The duplicate historical number 18 is retained to avoid rewriting the recorded prompt
identity. Authors and creation times still require the team's confirmation in [AI usage](../ai-usage.md).

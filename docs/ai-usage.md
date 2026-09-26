# AI assistance and provenance

Claude Code and Codex assisted Sekisho under user direction. This document describes
that assistance without treating generated work or automated tests as human sign-off.
The [historical log](archive/ai-development-log.md), [original specifications](archive/README.md)
and [prompts](prompts/README.md) preserve the development record.

## Contributions

| Area | Assisted work |
|---|---|
| Architecture and research | Interpreted the supplied specification; checked x402/MCP and provider interfaces; divided implementation work |
| Gate and SDK | Screening clients, deterministic policy, reports, persistence, x402 hooks, receipt checks and operator authentication |
| Contracts | Implemented/reviewed the supplied registry and escrow design, tests, deployment and MultiBaas integration |
| Agents and hosting | Buyer/vendor tools, public trial limits, Docker/Render configuration, testnet deployment and rehearsals |
| Interface and brand | Console, website, accessible trial states, original SVGs, AI-generated checkpoint illustration, presentation drafts |
| Verification | Unit/integration tests, browser checks, testnet receipts, event/webhook verification and restart persistence checks |
| Documentation | Setup, evidence, sponsor integration explanations, scripts, cleanup and archived development plans |

Relevant source areas are `gate/`, `sdk/`, `agents/`, `contracts/`, `dashboard/`,
`website/`, `deploy/`, `scripts/` and `docs/`. Details are mapped to recorded prompts
and commits. The cleanup moved historical plans into the archive, corrected their
consumers and removed unused files; it did not erase the development history.

## Human direction evidenced in the work session

The user selected the hackathon tracks and product goals, supplied design references,
requested changes to the narrative and UI, obtained provider credentials, funded fresh
testnet wallets, configured account access and approved testnet deployment. Automated
checks are recorded in [readiness](readiness.md) and [live evidence](LIVE-EVIDENCE.md).

## Team confirmation still required

Before submission, the team must truthfully confirm:

- Who wrote or AI-assisted the original PRD, including its embedded contract code,
  and when each was created relative to the event start.
- Any pre-existing project-specific work and the appropriate participation track.
- Who reviewed the code, policy, contracts, documentation and final live demonstration.
- All team members, their roles and social links.

Earlier drafts contain assertions about authorship and timing that are not independently
established by this cleanup. No team review is marked complete merely because an AI
agent inspected a file or a test passed. Do not manufacture or rewrite commit dates.

## Runtime boundary

The deterministic policy decides ALLOW/HOLD/BLOCK. Optional LLM output only supplies
advisory notes; it cannot change the verdict. The hosted trial runs with
`LLM_PROVIDER=none` and uses real provider calls. Development fixtures and simulations
are labelled separately.

## Presentation assets

[Asset provenance](assets/README.md) records original artwork, font licences and fixture
screenshots. AI assisted pitch/script drafting. The final submission video must use a
human voice: Tokyo's published guidance prohibits text-to-speech/AI narration.
See [submission requirements](SUBMISSION.md).

## Repository import

This repository was initialized from an existing local working copy on 27 September
2026. The initial commits group that snapshot by component for review; they are not
a reconstruction of the original development timeline. Previous Git history was not
imported. Historical personal account references were anonymized, current repository
links were updated, and the existing license and development records were retained.

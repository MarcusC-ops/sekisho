# Build Next.js compliance console

Subagent prompt written by the lead agent (Claude Code, Claude Opus 5.5) on 2026-09-25 13:13 UTC.
Local paths are shortened to `<repo>` and `<scratchpad>`; the text is otherwise verbatim.

---

You are the frontend builder for Sekisho, a hackathon project (ETHGlobal Tokyo 2026, due Sun 27 Sep 09:00 JST: work efficiently, P0 first). Sekisho is a compliance checkpoint for AI agent payments: a gate screens the counterparty wallet before an agent pays over x402, then returns ALLOW, HOLD (funds wait in an onchain escrow until a human officer releases or refunds them) or BLOCK (nothing is signed). Every decision is attested onchain through Curvegrid MultiBaas. You are building **C7, the Compliance Console**, which judges and a compliance officer use live on a projector.

Repo: `<repo>`. **You own `dashboard/` only**, so touch nothing outside it. Other agents are building the gate, contracts and agents in parallel. The gate isn't running yet, so build against fixtures.

**Read first:**
- `AGENTS.md` (project rules)
- `docs/api.md`: the API contract, with exact JSON shapes. Mirror it in `dashboard/lib/types.ts`, and do not invent or rename fields.
- `PRD.md` Section 10.6 (the console spec, around line 996), 9.7 (report hashing and Verify), 9.11 and 9.12 (schemas and examples), 11.3 (cut lines) and Appendix F (hash test vector)
- `PITCH_PLAN.md` Section 3 (the live demo script: what is on screen at each moment)

**Stack:** Next.js (latest stable, App Router, TypeScript), npm, SWR for data, `viem` for `keccak256`, `stringToBytes` and `formatUnits`, and `@xyflow/react` for the P1 trace graph. No Tailwind and no component library: every colour, font, radius and spacing is a CSS variable defined in one tokens file (e.g. `app/tokens.css`), because the team's branding arrives later and must be a token swap. Use CSS Modules or plain CSS for components. Required semantic tokens: `--verdict-allow`, `--verdict-hold`, `--verdict-block`, `--surface`, `--text`, `--muted`, `--accent`; add whatever else you need. If the `frontend-design` skill is available to you, use it for design direction.

**Env vars:**
- `NEXT_PUBLIC_GATE_URL` (default `http://localhost:8000`)
- `NEXT_PUBLIC_EXPLORER_URL` (default `https://sepolia.basescan.org`, for txs)
- `NEXT_PUBLIC_MAINNET_EXPLORER_URL` (default `https://etherscan.io`; counterparties are real mainnet addresses)
- `NEXT_PUBLIC_TREASURY_CONTROL_URL` (default `http://localhost:8100`)
- `NEXT_PUBLIC_USE_FIXTURES`: fixtures are used only when this is exactly `true`. The default is off, because fixtures must be off in the submitted build.

Add `dashboard/.env.example` with these.

**Fixtures** (`dashboard/fixtures/`, for UI development only): realistic data covering every demo scenario (PRD Section 5):
- S1 clean vendor ALLOW → PAID, with a seller-side ALLOW of the buyer
- S2 mixer-exposed HOLD → HELD_ESCROWED, with a trace showing a Tornado Cash funder and an analyst note recommending release
- S3 sanctioned BLOCK → REFUSED (Chainalysis true plus the `sanction_address` trait)
- S4 prompt-injection BLOCK, whose `untrusted_context` holds the injection text from PRD 10.2
- S5 inbound tainted-payer BLOCK
- S6 fail-closed HOLD (quick_scan status `error`)

Also include metrics, audit events, treasury, policy (use the exact YAML from PRD Appendix D; its id is `0xd55f2a7678cc2571a18073afd351f2fc13ffe4aa9c570632b94a8190f9c14719`) and report texts. Fixture report texts must be canonical JSON whose viem `keccak256(stringToBytes(text))` equals that case's `report_hash` and the `reportHash` of its `Screened` chain event, so Verify shows "Match" in fixture mode; include one deliberately mismatching case if that's easy. Generate the hashes with a small node script and commit the script. While fixtures are on, show an unmistakable "FIXTURE DATA" banner (the PRD requires synthetic data to be distinguishable from live findings). In fixture mode, simulate SSE by periodically "creating" fixture cases, so the live feed animation can be tested.

**Data layer:** one client module that switches between the gate and fixtures. `EventSource` on `/v1/stream` with automatic reconnect and backoff, plus a small "Live" / "Reconnecting" indicator. SSE events (`case.created`, `case.updated`, `chain.event`, `metrics.updated`) update the SWR caches, so new decisions appear within 1 s without polling.

**Pages** (PRD 10.6 has the full content list per page):
- P0 `/` **Live Decisions**
  - KPI strip: Screened, Allowed, Held, Blocked, Value protected (held + blocked USD), p50 decision time, Intercepta calls used / quota.
  - Decision feed, newest first; new cards animate in. Each card shows: verdict chip; direction ("→ paying" / "← being paid"); counterparty; amount; source (x402, MCP or direct); headline; the top two reasons; latency; an attestation pill (queued → confirmed, with a tx link). Clicking a card opens the case.
- P0 `/cases/[id]`: the most important page.
  - **Header:** verdict, a 0 to 100 risk gauge, headline, counterparty, amount, direction and time.
  - **Decision timeline:** the key component for the Intercepta judges. Vertical steps, each with status and ms, in this order:
    1. "Payment request received (402)", or the direct/MCP equivalent.
    2. One step per check, showing live vs cached.
    3. "Policy v1.0.0: BLOCK (rules)".
    4. The outcome: "No signature produced" / "Signed and settled, tx …" / "Held in escrow, hold #3" / "Released to payee" / "Refunded to payer" / inbound "Refused before verification".
    5. "Attestation confirmed, tx …".
  - **Evidence:** the Intercepta traits table (name, class, risk, txsCount, description **verbatim**), the oracle result per chain, impersonation and the token scan.
  - **Source of funds:** a taint % bar, the hop-1 table (address, labels, USD, share, flags) and the paths list. P1: an @xyflow/react graph with the counterparty in the centre and funders around it, flagged nodes marked.
  - **AI analyst note:** labelled "Advisory, does not decide", with evidence chips, an "Analyst disagrees" flag when `agrees_with_policy` is false, and a "template note" tag when `fallback` is true.
  - **Onchain proof:** report hash, policy id, attestation tx link, a raw JSON toggle, and a **Verify report** button that follows PRD 9.7 exactly. It fetches `/v1/reports/{hash}` as TEXT, hashes the exact served text with viem, and compares the result with both `report_hash` and the onchain `reportHash` from the case's `Screened` chain event. It shows Match or Mismatch, and says what was compared.
  - **Officer actions** (HOLD cases in `HELD_ESCROWED`, or inbound HOLD in `DECIDED`): a note field, Release and Refund, a confirm modal, live progress while the gate runs the override and then the release/refund txs, final tx links, and decoded revert reasons from 409 errors (NotCleared, NotHeld, PayeeBlocked and the others in PRD 9.11 point 6, in human wording). When `/healthz` reports `demo_mode: true`, also show a clearly labelled demo-only "Release without clearance" button that sends `release_unchecked`, so the escrow can be shown refusing with NotCleared.
- P0 `/review` **Hold queue:** HOLD cases awaiting action, with age, counterparty, amount, risk, analyst recommendation and an open button.
- P0 `/audit`: a table of `Screened`, `VerdictOverridden`, `Held`, `Released` and `Refunded` events (time, event, decoded fields, block, tx link, case link), captioned "Indexed by Curvegrid MultiBaas".
- P0 `/treasury`:
  - Balance cards: Treasury Agent USDC balance, In escrow, Paid via x402, Value blocked.
  - "Exposure by payee" as a bar list (plain CSS bars are fine).
  - P1 counterparty book.
  - Caption: "Powered by Curvegrid MultiBaas Event Queries". Tolerate `null` fields and show the `errors[]` messages.
- P1 `/policy`: the YAML read-only, the policy id and version, and the thresholds in plain English.
- P1 **Demo bar** (e.g. collapsible at the bottom of `/`): Run S1 to S6 via `POST {CONTROL}/run`, stream `GET {CONTROL}/runs/{id}` log lines into a small panel, and a Reset button that calls gate `POST /v1/demo/reset`.
- P2 `/integrate`: copy-paste snippets for the SDK hooks (PRD 10.1) and the MCP config (PRD 10.5).

**UX requirements (PRD 10.6):**
- Target 1440×900 and a projector: high contrast, body text ≥ 15px, KPI numbers ≥ 28px.
- Addresses in monospace, shortened as `0x098B…2F96`, with a copy button and a mainnet Etherscan link. Tx hashes link to the Base Sepolia explorer.
- Verdicts are never colour alone: always a text label plus an icon.
- Every panel has loading, empty ("No decisions yet. Run a scenario.") and error states (show the gate's `message`).
- Navigation between all pages. It must look polished and credible to judges, not like a template.

**Quality bar:**
- `npm run build` and `npm run lint` both pass with no type errors.
- Add a tiny test (e.g. `npm run test:hash`, a node script using viem) proving that `keccak256(stringToBytes(<Appendix F canonical text>))` equals `0xfbe83695c30cc9bec0d70c46a9b9a6e7941ef44d8cdf59361458684fe261f653`.
- Run the dev server with fixtures on and confirm every route returns 200 and renders its content (curl the HTML; if browser tools are available to you, take a look). Stop the dev server when done.

**Git:** do not run git commands that write (no add, commit, stash, checkout, reset); the lead commits your work. Don't install anything globally.

**Final report (concise):** files and structure; how to run (dev with fixtures, and against the live gate); env vars; build, lint and test results; which P0/P1/P2 items are done or missing; any API field you needed that `docs/api.md` doesn't have (don't silently add fields).

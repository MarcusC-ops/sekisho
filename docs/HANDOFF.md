# Handoff

Snapshot taken on 14 October 2026 for whoever maintains Sekisho next. It records what
is running, what needs an owner and how to check the repository. Measured product
evidence remains in [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md); verified scope and limits are
in [readiness.md](readiness.md).

## Current state

Sekisho is a working Base Sepolia prototype built for ETHGlobal Tokyo 2026. The hosted
allowed purchase and refused purchase were verified on 26 September 2026. Escrow
release/refund passed in a separate operator rehearsal. The complete provider-triggered
HOLD-to-escrow journey is still unverified. This is a demo policy, not a production
compliance service.

## What is running

Checked from outside, without credentials, on 14 October 2026:

| Surface | Location | Observed |
|---|---|---|
| Static website | [sekisho-phi.vercel.app](https://sekisho-phi.vercel.app/), Vercel, root `website/` | Up, but serving an older build (see below) |
| Public trial runner | [sekisho-trial.onrender.com](https://sekisho-trial.onrender.com/public/readiness), Render, [`render.yaml`](../render.yaml) | `ready: true`, `mode: live`, Base Sepolia, no blockers |
| Contracts | Base Sepolia registry and escrow, addresses in [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md#deployed-contracts-and-escrow-rehearsal) | Not rechecked |
| MultiBaas deployment | Private `MB_URL` | Not checked (needs credentials) |
| Operator console and full gate | Private; never publicly deployed | — |
| CI | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | Last run on `e5385cb` passed all four jobs |

### Production website is behind `main`

The live homepage (last modified 4 October 2026) does not match `website/index.html`.
It links to a previous repository location, `github.com/Ducksss/sekisho`, and still says
live testnet validation is pending. The `/try/` page and scripts match `main`. The Vercel
project therefore appears to deploy from a different repository or commit.

Until it is reconnected, changes under `website/` are not live, including the new icons
and share cards. In Vercel, connect the project to `MarcusC-ops/sekisho` with root
directory `website`, redeploy `main`, then check `/`, `/try/`, `/favicon.ico` and
`/assets/og-home.png`. The runner's CORS origin stays `https://sekisho-phi.vercel.app`.

## Accounts, credentials and spend

Never commit or paste values. Hosted secrets live in Render environment variables;
local ones live in the untracked `.env` described by [`.env.example`](../.env.example).
Who holds each account is not recorded in this repository; confirm it before transfer
and rotate anything held by someone who is leaving.

| Item | Purpose | Notes |
|---|---|---|
| GitHub `MarcusC-ops/sekisho` | Source and CI | Public. Description, website and topics are empty. The social preview must be uploaded manually in repository settings using [social-preview.png](assets/social-preview.png). |
| Vercel project | Static website | Reconnect as described above. |
| Render service `sekisho-trial` and disk `sekisho-data` | Public trial backend | Paid starter plan and 1 GB disk, so it bills until suspended. Single instance only. |
| Intercepta API key | Live screening | Hackathon key with a 1,000-request quota (`INTERCEPTA_QUOTA`). Confirm whether it stays valid after the event. |
| Blockscout API key | Source-of-funds tracing | Free developer key. |
| Curvegrid MultiBaas | Contract calls, events and webhooks | `MB_URL`, `MB_ADMIN_API_KEY`, `MB_WEBHOOK_SECRET`. |
| Four testnet signer keys | Deployer, screener, officer and buyer | Base Sepolia only. The buyer wallet funds public trials. |
| `SEKISHO_OPERATOR_TOKEN` | Officer actions in the private console | Independent random value. |
| LLM provider keys | Optional advisory notes | The hosted trial uses `LLM_PROVIDER=none`. |

The public trial has persistent lifetime limits: 20 runs and 1 test USDC reserved in total
([details](PUBLIC-TRIAL.md#public-run-limits)). Two runs (100,000 atomic units) were recorded
on 26 September; later usage is visible only on the Render disk. Never delete or reset that
database to restore the allowance. If the service is suspended, the trial page shows an
unavailable state and the recorded evidence stays visible.

## Verify a fresh checkout

Prerequisites and configuration are in [SETUP.md](SETUP.md). Results from this machine
on 14 October 2026:

| Command | Result |
|---|---|
| `make install` | Installs Python, submodule and dashboard dependencies; now uses `npm ci`, so it no longer rewrites the lockfile |
| `.venv/bin/python -m pytest -q` | 485 passed |
| `npm --prefix dashboard run lint` and `build` | Passed |
| `npm --prefix dashboard run test:hash` | 45 passed |
| `node --test website/try/state.test.mjs` | 5 passed |
| `node --test scripts/test-website-demo.mjs` | 3 passed |
| `python3 scripts/build_website_demo.py --check` | Excerpts current |
| `.agents/scripts/link-skills.sh check` and `sync-mcp.sh check` | In sync |
| `forge test` | Not run locally (Foundry not installed); CI passed 18 tests on `e5385cb` |

Unit tests mock providers. They do not replace a live rehearsal, which spends provider
quota and testnet funds and needs explicit authorisation.

## Brand and share assets

[Asset provenance](assets/README.md) lists every file and how to re-render it. This pass
added a favicon set, web manifest, Open Graph cards for the homepage and trial page,
a refreshed repository preview, and PNG logo/lockup exports for slides and forms.

## Open items

1. Reconnect and redeploy the Vercel project (above).
2. Set the GitHub description, website and topics, and upload the social preview.
3. The submission deadline was 27 September 2026. The [checklist](SUBMISSION.md) does not
   record what was submitted; confirm it in the ETHGlobal dashboard.
4. Team members, roles, social handles and authorship confirmations in [AI usage](ai-usage.md) remain open.
5. Decide whether to keep paying for the Render service or suspend it.
6. Remaining engineering scope is in [readiness.md](readiness.md#remaining-engineering-scope):
   a genuine provider-triggered HOLD, repeated performance measurement and a production review.

## Rules that protect the evidence

The full list is in [AGENTS.md](../AGENTS.md). The ones most likely to be broken by accident:

- Never reformat `gate/policy/policy.yaml`; its exact bytes define the policy hash.
- Verify report hashes against exact served bytes. A report hash is not settlement evidence.
- Missing or failed required screening never becomes ALLOW.
- Never send mainnet transactions. Mainnet access is read-only.
- Keep simulations and fixtures labelled, and never present the escrow rehearsal as a full HOLD workflow.

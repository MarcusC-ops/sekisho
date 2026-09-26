# Public browser trial

## Current deployment

The [public trial](https://sekisho-phi.vercel.app/try/) connects to the restricted
[Render backend](https://sekisho-trial.onrender.com/public/readiness). Its hosted
paid/refused flows, attestations, webhook deliveries and persistence across redeploy
were verified on 26 September 2026; see [live evidence](LIVE-EVIDENCE.md).
Visitors need no wallet or API credentials. The server funds the bounded testnet run.
Four separate simulations remain available and are explicitly labelled.

The service exposes `/public/readiness`, `POST /public/runs`, an isolated run result,
and authenticated MultiBaas webhook ingress. The full gate and operator console are
private. New deployments default to disabled. Readiness is a configuration gate,
not a guarantee of continuing provider availability or funding.

For local development:

```bash
make public-trial
# Other terminal, for the static page:
python3 -m http.server 3112 --bind 127.0.0.1 --directory website
```

`make public-trial` starts only the runner. `make trial-stack` starts the gate and
preset vendors as well. Neither command makes a payment by itself. The website's
`try/config.mjs` contains the public API origin; use an empty string for simulation
only, or a matching local runner origin for local integration tests. Never put
provider keys, operator tokens, wallet keys or run capabilities in that file.

## Public-run limits

The initial runner permits only server-selected clean/flagged fictional vendors,
50,000 atomic units of canonical Base Sepolia USDC per purchase, and one signature
per run. It does not expose escrow or officer actions. Decisions bind the actual
recipient, asset, amount and network; unavailable evidence pauses signing.

SQLite persists reservations: at most 20 lifetime runs, 1 test USDC total reserved,
3 runs per browser session and 6 per hashed client IP. Session limits alone are not
identity controls; global caps remain the financial boundary. Reverse proxy IP
handling must be configured carefully; never trust arbitrary forwarded headers.

Every admitted run consumes its allowance even if screening refuses or execution
fails. Restarting must not erase the database. A run interrupted by a hard crash
blocks further signing until an operator reconciles the possible onchain outcome.
There is no public reset endpoint. A run ID is an unguessable read capability: avoid
recording it in public logs or sharing it beyond the demo participant.

Admission also reads the gate’s durable provider counter and requires 50 calls of
headroom below the smaller of INTERCEPTA_QUOTA and INTERCEPTA_RESERVE_FROM. An unreadable
counter disables live admission. Direct live Quick Scan must be enabled, and the
signing decision must be no more than 120 seconds old.

The run limit bounds trials, not exact upstream API calls. A single trial may screen
both parties plus supporting evidence. Monitor the gate's durable provider counter
and preserve quota for the judged demonstration.

## Hosting: Render with a persistent disk

`render.yaml` provisions one Docker service with a 1 GB disk at `/data`, in Singapore.
Only the restricted public runner binds externally. The gate and preset vendor
servers listen on loopback. The privileged treasury controller is not started.

The committed Blueprint is a deployment template, not a credential bundle. Review
the service and persistent-disk price displayed by Render before creating another
instance. The existing hosted service has already been provisioned. For a new host:

1. Sign in to Render and connect the Sekisho repository; select its `render.yaml`
   Blueprint. Review the displayed service/disk cost.
2. Keep `PUBLIC_TRIAL_ENABLED=false` and `PUBLIC_TRIAL_LIVE_VERIFIED=false` initially.
3. Add server secrets privately in Render, using `.env.example` as the checklist.
   Never add `.env` to Git or the Docker image. Provider access and wallet funding are
   not tested merely by setting variables.
4. Preserve `DB_PATH=/data/gate.db`, `PUBLIC_TRIAL_DB_PATH=/data/public-trial.db`,
   `SEKISHO_URL=http://127.0.0.1:8000` and one instance. Use only Base Sepolia wallets.
5. Set `PUBLIC_TRIAL_ORIGIN=https://sekisho-phi.vercel.app`. Other marketing aliases
   should link to that canonical trial page instead of broadening CORS blindly.
6. Prove local live S1/S3 and receipt verification first. Set both public trial flags
   to `true` only after reviewing the evidence in [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md).
7. Set the public HTTPS backend URL in `website/try/config.mjs`, deploy the website,
   and repeat the allowed/refused browser acceptance tests.

For another Docker host, use `docker compose -f deploy/compose.yaml up --build -d`.
The local compose port binds to 127.0.0.1; place an HTTPS reverse proxy in front.
The named volume must persist across deploys. Do not scale the SQLite stack across
machines or delete the volume to replenish a budget.

## Operator console, webhooks and attestation

Keep the full gate and console private during the public trial. Use an authenticated
operator network/tunnel for the console. The public trial is not a replacement for
its audit/review screens. Do not expose `/v1/screen`, `/v1/demo/reset` or the treasury
controller without their own quota/access boundary.

The restricted runner exposes only `POST /webhooks/multibaas` for webhook ingress,
forwarding the unchanged body and signature headers to the private gate. The gate
verifies HMAC; the proxy limits body size/time and does not forward operator credentials.
Register the final HTTPS service URL in MultiBaas after deployment. Receipt and
onchain attestation checks remain separate from webhook delivery.
The private operator-console connection remains a separate deployment task.

## Verification

```bash
.venv/bin/python -m pytest agents/tests/test_public_trial.py -q
.venv/bin/python -m pytest -q
node --test website/try/state.test.mjs
node --test scripts/test-website-demo.mjs
npm --prefix dashboard run lint
npm --prefix dashboard run build
```

A deployment is accepted only when the browser requests the intended HTTPS backend,
no secrets or private console routes are exposed, limits survive restart, and one
real paid purchase plus one live refusal/pause is recorded. Docker build and live
cloud execution were verified on Render on 26 September 2026. The live Chrome
payment/refusal, exact attestations and genuine webhook deliveries are recorded in
[LIVE-EVIDENCE.md](LIVE-EVIDENCE.md). After redeployment, a read-only query of `/data/public-trial.db`
confirmed exactly the same two completed cases and 100,000 atomic test-USDC budget
reservation. Restart did not erase the trial history or replenish its allowance.

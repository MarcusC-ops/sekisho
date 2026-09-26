# Sekisho public website

[Website](https://sekisho-phi.vercel.app/) · [Try Sekisho](https://sekisho-phi.vercel.app/try/)

Static HTML, CSS and native JavaScript modules. The website explains Sekisho and
provides two live testnet presets alongside four clearly labelled simulations.
The operational Next.js console is a separate, private application.

## Preview

From the repository root:

```bash
python3 -m http.server 3112 --bind 127.0.0.1 --directory website
```

Open `http://localhost:3112`. No website build or dependency installation is needed.
The committed `try/config.mjs` points to the hosted public runner; that runner allows
the canonical production origin. To develop without live requests, temporarily set
`publicRunnerURL` to an empty string, or configure a separate local runner and its
allowed origin. Simulations never contact the gate or sign payments.

## Maintain the examples

Synthetic scenario inputs live in `dashboard/fixtures/`; displayed and downloadable
Python code comes from the tested SDK example. Regenerate excerpts after editing
these sources:

```bash
python3 scripts/build_website_demo.py
python3 scripts/build_website_demo.py --check
node --test scripts/test-website-demo.mjs
node --test website/try/state.test.mjs
.venv/bin/python -m pytest sdk/tests/test_website_example.py -q
```

Keep fixture and sample-content labels visible. Source assets and font provenance
are documented in [docs/assets](../docs/assets/README.md).

## Live trial boundary

`try/config.mjs` contains only the public HTTPS backend URL. No provider keys,
operator tokens, private keys or run capabilities belong in this file.

The adapter uses `/public/readiness`, `POST /public/runs` and
`GET /public/runs/{run_id}`. Readiness must explicitly report live Base Sepolia mode.
The server selects the payment destination and terms; current evidence determines
the outcome. A live failure is never silently replaced by a simulated success.

Session and idempotency identifiers use sessionStorage. Pending request keys survive
ambiguous network failures so retries do not automatically buy again. Run IDs are
read capabilities and must not be placed in public URLs. Results use textContent,
not provider-supplied HTML. The page accepts no operator token.

A transaction link and seller content appear only for a confirmed `paid` result.
The backend independently checks the exact USDC transfer and the case's payment
status. Report consistency shown here is a server check, not independent browser
verification of an onchain attestation. See [deployment and limits](../docs/PUBLIC-TRIAL.md)
and [recorded live evidence](../docs/LIVE-EVIDENCE.md).

## Deployment and review

The Vercel project uses `website` as its root, static output `.` and no framework
build. Git integration deploys `main`. The Python backend, dashboard, contracts and
private environment files are outside that publishing root.

After deployment, check `/`, `/try/`, asset URLs and the custom 404. Review desktop
and mobile layouts, keyboard focus, scenario reset/back controls, downloads, and
reduced-motion behavior. Check both live and simulated labels and ensure a failed
backend produces a visible unavailable state.

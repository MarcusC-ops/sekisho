# Teammate Vercel deploys

User request to Claude Code (26 September 2026), verbatim: "across sekisho, tenjo,
tradebridge and machi-voucher, can we create a webhook? my teammates want to deploy their
solution and new ui, but they always need me to do so for redployment on vercel". Follow-up,
verbatim: "we can just create a utc timestamp md file so its unique. then when the event
ends, we can just clean it uo".

Finding: the four Vercel projects are on a Hobby team, which builds a private repository's
commits only when the Vercel owner authored them. Vercel's documentation and community
threads say deploy hooks have been held to the same check since May 2026, so a deploy hook
alone would not help.

Plan: add `.github/workflows/vercel-deploy.yml` to each repository. When Vercel blocks a
push to `main`, the workflow commits a UTC-timestamped note to `.github/deploys/` with the
owner as author, then reports Vercel's verdict and the production URL in the run summary.
It leaves alone the pushes Vercel builds by itself, and it can be run by hand to redeploy
`main`.

Scope: GitHub Actions workflow, deployment docs and AI usage records only. No Vercel
setting, secret or product code changed. Verified by running the workflow by hand in each
repository: every note commit was built as a production deployment. No subagents used.


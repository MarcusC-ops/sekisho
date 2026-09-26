# Submission checklist

Current technical evidence: [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md).
The product is a verified hosted testnet MVP, not a complete production compliance system.

## Deadline and delivery

Submit through the ETHGlobal Hacker Dashboard by **27 September 2026, 09:00 JST**.
Select the partner prizes explicitly; the form permits up to three partner organizations.
Choose finalist judging or partner prizes only. Finalist sessions allow four minutes
for the demo and three minutes for questions.

Source: [Tokyo submission and judging instructions](https://ethglobal.com/events/tokyo2026/info/details).
Confirm any organizer updates in the dashboard before submitting.

## Final packaging

- [ ] Review source/history for credentials, then make the repository public and check signed-out access.
- [ ] Confirm team members, roles and social handles in the main README and submission form.
- [ ] Confirm original specification/code timing, reused material, human contributions and review in [AI usage](ai-usage.md).
- [ ] Supply a concise title, description, implementation explanation, live application and repository links.
- [ ] Complete each partner's integration explanation and feedback; link source and measured evidence.
- [ ] Check all submitted links without a signed-in session.
- [ ] Check remaining provider quota, testnet funds and the persistent public-trial allowance.
- [ ] Rehearse the [demo](DEMO.md) and answer questions about limits, enforcement and report hashes.
- [ ] Submit and verify the dashboard confirmation; a draft is not a completed submission.

Keep the verified scope explicit: hosted ALLOW and BLOCK are complete; escrow actions
passed separately; the complete provider-triggered HOLD journey is still unverified.
There is no need to invent that demonstration to meet Intercepta's blocked-or-held requirement.

## Demo video

Tokyo's published guidance calls video optional but strongly encouraged. If supplied:

- Use a human speaker, **not ElevenLabs, text-to-speech or another AI voiceover**.
- Keep the finished recording between **2 and 4 minutes** and at least **720p**.
- Show the real product. Slides can summarize context, but should not replace the demonstration.
- Cut waiting time; do not speed up the recording to fit the limit.
- Do not use a phone recording or music/text instead of spoken explanation.

Aim for 3:30 with the paid/refused sequence and a short limitations statement. Earlier
AI narration and long slide scripts are not suitable submission recordings.

## Intercepta: Safe Agent-to-Agent Payments with x402

[Official requirements](https://ethglobal.com/events/tokyo2026/prizes/intercepta).

| Requirement | Evidence / action |
|---|---|
| Working agent payment flow | Hosted x402 purchase; exact 0.05 test USDC settled |
| Live API evidence decides before signing/acceptance | [Adapter](../gate/sekisho_gate/screening/intercepta.py), [pipeline](../gate/sekisho_gate/screening/pipeline.py), [hooks](../sdk/sekisho/x402_hooks.py) |
| Mainnet risk evidence even for testnet payments | Actual address scans; mainnet sanctions/trace data; payment chain Base Sepolia |
| One payment succeeds, another is blocked or held with visible reason | Hosted PAID and REFUSED cases, canonical evidence and source reasons |
| Public repo, API file links, 3–5 lines of feedback | Links and feedback in [README](../README.md#sponsor-integrations); public visibility still requires owner action |

The separate $500 Continuity prize applies only to eligible existing-product work;
do not select it simply because Sekisho includes an SDK.

## Curvegrid: Best AI Agent Project

[Official requirements](https://ethglobal.com/events/tokyo2026/prizes/curvegrid).
Sekisho's strongest fit is the policy-aware agent payment flow.

The README includes a one-sentence summary, MultiBaas integration and actual feedback,
setup/testing links, and the known team member. Confirm the full team introduction and
social handles. Repository artifacts include contracts, tests and documentation.

Use the exact registry/escrow addresses, indexed Screened events and genuine webhook
receipts in [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md). Explain cumulative deposits separately
from current held funds. Avoid presenting initial Foundry deployment as a MultiBaas
runtime transaction.

## Suggested project description

Sekisho is a policy checkpoint for AI agent payments. It uses live risk evidence to
allow, pause or refuse x402 payments before signing, verifies settlement separately,
and records decision fingerprints through Curvegrid MultiBaas. The hosted Base Sepolia
demo shows a paid purchase and a refused purchase without requiring a visitor wallet.

## Human confirmation

Do not remove unfinished provenance fields merely to make the submission appear complete.
The original specs, prompts and plans remain in the repository archive. Confirm their
actual authorship/timing and distinguish new work from reused code or assets.

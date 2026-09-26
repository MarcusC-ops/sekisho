# Public-release cleanup

## User request

Review repository files, remove unnecessary material, tidy READMEs/documentation before
public release, and remove old material such as the PRD from the final product presentation.

## Applied scope

- Move original specifications, old design/pitch plans, research and chronological
  status reports into `docs/archive/` to preserve required AI-development provenance.
- Replace active documentation with the current hosted payment/refusal evidence,
  setup instructions, limitations and submission requirements.
- Remove unused duplicate assets and broken Makefile targets; retain functional code,
  fixtures, tests and source/licence files used to reproduce assets.
- Update the test and fixture-generator references to the archived PRD.
- Inspect current source and reachable main history for credentials without printing values.
- Preserve unrelated work and publish focused changes on top of the current GitHub head.

Codex coordinated independent documentation and file/reference audits, reviewed the
combined changes, and ran verification. The user will decide when to make the repository
public; this cleanup does not change visibility or certify human authorship/review.

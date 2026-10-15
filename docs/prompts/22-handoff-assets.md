# Handoff assets and repository check

User request to Claude Code (Claude Opus 5.5, Claude desktop app), 14 October 2026,
verbatim: "create assets and stuff. make sure the repo is clean and steady for a handoff".

Plan: rerun every maintained check on a fresh install; compare the live website and
public runner with `main` using read-only requests; add the missing website icons, web
manifest and per-page share cards in the current editorial identity; replace the
repository preview that still showed a previous account handle; export PNG logo and
lockup files; correct HOLD wording that implied escrow; and record the state, owners,
spend and open items in a handoff document.

Scope: repository files only. No deployment, GitHub setting, Vercel or Render change,
live trial run, provider call or transaction. Findings that need account access, such as
the stale Vercel deployment and the empty GitHub metadata, are documented in
[HANDOFF.md](../HANDOFF.md) rather than changed. No subagents used.

## README restructure

Follow-up, verbatim: "follow the https://github.com/othneildrew/Best-README-Template and
make sure all is good too".

Plan: restructure the main README into the template's sections (shields, centred logo,
table of contents, About/Built With, Getting Started, Usage, Roadmap, Contributing,
License, Contact, Acknowledgments, back-to-top links and reference-style badges) while
keeping every verified claim, limitation, sponsor explanation and inbound anchor
(`#run-locally`, `#sponsor-integrations`). Use the recorded trial-evidence panel as the
product screenshot, add the bug and feature issue templates the template links to, and
verify badges, external links, anchors and GitHub's rendering. Contact lists only the
already-confirmed maintainer; no social handles were invented.

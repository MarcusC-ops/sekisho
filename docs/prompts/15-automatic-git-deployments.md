# Automatic Git deployments

User request (26 September 2026): make GitHub pushes automatically update Vercel
for the four selected projects, including wallet-audit-trail (this repository).

Plan: inspect the existing GitHub and Vercel settings, connect the existing `sekisho`
Vercel project to `<original-repository>`, configure `website` as the publishing root,
retain `main` as the production branch, and verify a documentation push creates a
successful GitHub-triggered production deployment. Other branches use previews.

Scope: the existing static public website only. No operational gate, dashboard,
contract, payment, environment-secret, or product behavior changes. Record the
deployment setup and AI assistance in the repository. No subagents used.


# Artwork and presentation assets

Current website styling lives in [editorial.css](../../website/editorial.css) and
[styles.css](../../website/styles.css); console tokens live in
[tokens.css](../../dashboard/app/tokens.css). Historical visual directions are
[archived](../archive/README.md), not active UI specifications.

## Reusable assets

- [logo.svg](logo.svg) and [wordmark.svg](wordmark.svg): original project vector identity.
- [Payment checkpoint](../../website/assets/01-payment-checkpoint.svg) and
  [mobile version](../../website/assets/01-payment-checkpoint-mobile.svg): current website diagram.
- [Before and after](diagrams/02-before-and-after.svg) and
  [institutional stakes](diagrams/03-institutional-stakes.svg): reusable original SVG diagrams for decks.
- [Checkpoint illustration](checkpoint-hero.png): original imagegen artwork; also used by the website.
- [Banner](banner.png) and [social preview](social-preview.png): earlier brand exports,
  reproducible from [presentation.html](source/presentation.html).

## Screenshots and licences

The [decisions](console-decisions.png), [case](console-case.png) and
[treasury](console-treasury.png) PNGs are historical fixture-console screenshots, not
live financial evidence. The website uses compressed [decisions](../../website/assets/console-decisions.webp)
and [case](../../website/assets/console-case.webp) versions and labels them as previews.
The fixture warning remains visible. Current live proof is in [LIVE-EVIDENCE.md](../LIVE-EVIDENCE.md).

The AI-generated checkpoint artwork and original vectors were created for Sekisho;
[the recorded prompt](../prompts/12-investflow-direction.md) describes the initial
visual reference. No paid template artwork was copied. Third-party fonts retain their
licences, including the included [Inter Tight OFL](source/fonts/OFL.txt).
Original project assets use the [repository MIT licence](../../LICENSE).

## Optional reproduction

These helpers are documentation tooling, not runtime dependencies. With Node,
Playwright/Chromium and a fixture console available:

```bash
CONSOLE_URL=http://localhost:3000 node docs/assets/source/capture.cjs
```

`PLAYWRIGHT_MODULE` and `CHROMIUM_EXECUTABLE` select an installed toolchain. The helper
requires the fixture banner; review generated timestamps and screenshots before committing.

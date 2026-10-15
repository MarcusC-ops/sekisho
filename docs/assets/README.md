# Artwork and presentation assets

Current website styling lives in [editorial.css](../../website/editorial.css) and
[styles.css](../../website/styles.css); console tokens live in
[tokens.css](../../dashboard/app/tokens.css). Historical visual directions are
[archived](../archive/README.md), not active UI specifications.

## Reusable assets

- [logo.svg](logo.svg) and [wordmark.svg](wordmark.svg): original project vector identity.
  The console uses the same mark as [icon.svg](../../dashboard/app/icon.svg).
- [logo-1024.png](logo-1024.png), [lockup.png](lockup.png) and [lockup-dark.png](lockup-dark.png):
  raster exports for slides and forms. Lockups have transparent backgrounds; use the dark
  version on dark slides.
- [social-preview.png](social-preview.png): 1280 × 640 repository preview in the current
  editorial identity. Upload it in the GitHub repository settings; it cannot be set from Git.
- [Payment checkpoint](../../website/assets/01-payment-checkpoint.svg) and
  [mobile version](../../website/assets/01-payment-checkpoint-mobile.svg): current website diagram.
- [Before and after](diagrams/02-before-and-after.svg) and
  [institutional stakes](diagrams/03-institutional-stakes.svg): reusable original SVG diagrams for decks.
- [Checkpoint illustration](checkpoint-hero.png) and [banner](banner.png): artwork from the
  earlier navy presentation direction, retained for decks that already use it.

## Website icons and share cards

Served from `website/` and linked from every page head:

| File | Use |
|---|---|
| `favicon.ico` | 16, 32 and 48 px favicon for browsers and crawlers that request it directly |
| `assets/logo.svg` | Scalable favicon |
| `apple-touch-icon.png` | 180 px full-bleed home-screen icon |
| `assets/icon-192.png`, `assets/icon-512.png`, `assets/icon-maskable-512.png` | Web manifest icons; the maskable version keeps the mark inside the safe zone |
| `site.webmanifest` | Name, colours and icons |
| `assets/og-home.png`, `assets/og-try.png` | 1280 × 640 Open Graph cards for `/` and `/try/` |

## Screenshots and licences

[trial-evidence.png](trial-evidence.png) is the recorded hosted testnet evidence panel
from the `/try/` page, used as the README product screenshot. It shows the dated 26 September
2026 results that the page labels as recorded, not a new run.

The [decisions](console-decisions.jpg), [case](console-case.jpg) and
[treasury](console-treasury.png) images are historical fixture-console screenshots, not
live financial evidence. The website uses compressed [decisions](../../website/assets/console-decisions.webp)
and [case](../../website/assets/console-case.webp) versions and labels them as previews.
The fixture warning remains visible. Current live proof is in [LIVE-EVIDENCE.md](../LIVE-EVIDENCE.md).

The AI-generated checkpoint artwork and original vectors were created for Sekisho;
[the recorded prompt](../prompts/12-investflow-direction.md) describes the initial
visual reference. No paid template artwork was copied. Third-party fonts retain their
licences, including the included [Inter Tight OFL](source/fonts/OFL.txt).
Original project assets use the [repository MIT licence](../../LICENSE).

## Reproduction

Every raster above except the checkpoint illustration and the screenshots is rendered from
source in [source/](source/): [social.html](source/social.html) for the share cards,
[brand.html](source/brand.html) for icons and lockups, and
[presentation.html](source/presentation.html) for the banner. These helpers are
documentation tooling, not runtime dependencies. With Node and Playwright/Chromium:

```bash
node docs/assets/source/capture.cjs
CONSOLE_URL=http://localhost:3000 node docs/assets/source/capture.cjs  # also recapture fixture screenshots
TRIAL_URL=https://sekisho-phi.vercel.app/try/ node docs/assets/source/capture.cjs  # also recapture trial-evidence.png
```

Capturing the trial page reads its static recorded panel; it never starts a trial run.

`PLAYWRIGHT_MODULE` and `CHROMIUM_EXECUTABLE` select an installed toolchain. The cards
use Georgia and Hiragino Mincho as system fonts, so other platforms substitute similar
faces. The console capture requires the fixture banner. Review every changed image
before committing, and restore any file that changed only through rendering noise.

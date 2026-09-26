---
version: alpha
name: Sekisho Compliance Console
description: A checkpoint ledger for reviewing agent payments and their evidence.
colors:
  primary: "#315bff"
  background: "#f4f7fc"
  surface: "#ffffff"
  text: "#061234"
  muted: "#536079"
  allow: "#0f6e47"
  hold: "#8a5700"
  block: "#b42a1a"
typography:
  sans:
    fontFamily: '"Atkinson Hyperlegible Next Variable", system-ui, sans-serif'
  mono:
    fontFamily: '"Atkinson Hyperlegible Mono Variable", ui-monospace, monospace'
rounded:
  sm: "6px"
  md: "12px"
  lg: "16px"
spacing:
  page-max: "1400px"
  gutter: "24px"
  section-gap: "24px"
components:
  button: {}
  panel: {}
  table: {}
  dialog: {}
---

# Sekisho design system

## Overview

An operational checkpoint ledger for an officer investigating an AI agent payment.
This is a product console, designed for an English-language live demo and desktop
review, with readable mobile access. The Tokyo event is the presentation venue;
it does not establish a Japanese-market financial service or Japanese localization.
Product facts come from PRD 9.11 and 10.6, docs/api.md, and PITCH_PLAN.md.

Preserve the existing seal/verdict identity and large, legible evidence typography.
Avoid marketing hero layouts, decorative charts, or suggesting that an ALLOW certifies
safety. The distinctive element is the verdict stamp; operational tables stay quiet.

The canonical runtime tokens are dashboard/app/tokens.css. This document mirrors their
intent and selected values; it does not generate CSS. globals.css maps verdict tones and
scrollbar tokens; shared components consume those variables. Verify token changes against
these files together. No new theme or palette is introduced by a feature page.

## Colors

Cool paper surrounds white panels. Dark ink and slate carry text; blue denotes actions
and charts. Green, amber, and red are verdict semantics accompanied by icons and words.
Purple identifies fixture data. A failed read is unavailable, never a fabricated zero.
Light mode is the current supported theme. Forced-color scrollbars use system colors.

## Typography

Inter Tight carries headings at weight 550. Atkinson Hyperlegible Next carries body
text; its mono companion carries
addresses, hashes, and code. Body text is 17px, table text 15px, page titles 28px.
The existing Mincho stack is reserved for seal kanji. Use tabular numerals for balances.
Full addresses remain available by copying and explorer navigation.

## Layout

A 1400px maximum page with 24px gutters, reduced to 16px below 720px. Panels use 24px
section spacing. Treasury has four balance cards, two below 1000px, one below 430px.
Wide tables own horizontal scrolling and expose a keyboard-focusable region. The page
retains normal document scrolling; do not fix ancestor heights to constrain a table.

## Elevation & Depth

Use the existing panel borders and modest card shadows. Reserve raised elevation for
menus and dialogs. Loading and errors belong inside the affected data region.

## Shapes

Controls use 6px corners, panels 12px or 16px according to the shared primitive. Meters
use rounded tracks. Reuse existing controls instead of introducing screen-local variants.

## Components

Panel/DataState own loading, error, stale-with-error, and empty states. Button owns
pending/disabled behavior. DataTable owns read-only table geometry; native anchors own
navigation and native details own event-field disclosure. Use links for audit filters,
with aria-current marking the active filter. No bespoke selects, date inputs, or bulk
selection are needed for these pages.

All focusable controls use the global visible outline. Enabled buttons and disclosures
have pointer and hover feedback. Dialogs use the existing Modal. Scrollbar colors come
from tokens.css globally; geometry-only exceptions may live in component styles.

Motion communicates new decisions and pending work. Respect reduced motion through the
global media query. Dollar values use the shared formatter; timestamps include timezone
in full displays. The tone is literal and operational: Release, Refund, Open case,
Verify report. Intercepta evidence descriptions stay verbatim.

## Do's and Don'ts

- Reuse the case detail workflow for officer actions; queue rows navigate to it.
- Preserve source, freshness, nullable values, and partial-error explanations.
- Do not label cumulative Held events as currently locked funds.
- Do not present fixture data or passing unit tests as live integration proof.

## Marketing direction

[docs/BRAND-DIRECTION.md](docs/BRAND-DIRECTION.md) records the user-requested Investflow
reference and its translation to Sekisho's website and assets. It defines a luminous
blue checkpoint identity. Console tokens now share its midnight and signal-blue palette,
with Inter Tight headings and quieter borders. Verdict colors and operational density remain.

The public marketing surface is implemented separately in `website/`. Its canonical
marketing tokens live in `website/styles.css` and follow the brand direction: midnight
#061234, signal #315bff, ice #eaf2ff, slate #536079, and Inter Tight. It shares original
assets with `docs/assets/`; the operational console retains its own density and tokens.

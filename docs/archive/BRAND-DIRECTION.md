# Sekisho — visual direction

Requested 26 September 2026: distill the taste of
[Investflow](https://investflowtemplate.webflow.io/) for Sekisho's project, website,
and assets. This is a direction brief, not a claim that the console has been restyled.

## The taste in one sentence

**Calm financial infrastructure, lit by a precise blue signal.**

Sekisho should feel composed, spacious, and technically exact. The checkpoint is the
brand's distinctive subject: autonomous payment reaches a boundary, evidence is
considered, and the policy determines whether it can proceed.

## What the reference actually does

Reviewed the template overview, [Home V1](https://investflowtemplate.webflow.io/home-pages/home-v1),
and its [style guide](https://investflowtemplate.webflow.io/template-pages/style-guide)
in a browser, including the hero and the first content section.

- An inset hero with broad rounded corners holds a dark navy field that opens into
  electric blue, ice blue, and white. A faint grid gives the atmosphere structure.
- Headings use Inter Tight with compact tracking and medium/semibold weight. At the
  inspected desktop viewport, the Home V1 hero heading computed to 40px, weight 600,
  44.6px line height, and -0.8px letter spacing. Scale and space do more work than weight.
- Solid blue pill buttons form the clearest accents. Secondary actions stay restrained.
- Large white intervals and thin dividers separate sections. Content sits in a clear
  shared grid; not every paragraph needs a card.
- Pale sculptural forms, translucent materials, repeated fins, and one blue accent give
  the imagery depth. The materials feel smooth and deliberately manufactured.
- Soft reveals and slow movement create atmosphere. They are expendable when they
  delay reading or interfere with reduced-motion preferences.

The published style guide names Inter Tight and a palette including accent #2365FF,
secondary #EBF4FF / #2DB2FF / #1D36B6, and deep neutral #001035. These are observations
of the source; the following Sekisho values are our proposed adaptation.

## Sekisho translation

| Element | Direction |
|---|---|
| Brand idea | A luminous checkpoint: permission to move follows evidence |
| Headline | Before the agent signs. |
| Supporting line | Screen the wallet. Apply the policy. Record the decision. |
| Tone | Short, literal, confident; explain the action and its evidence |
| Mark | Keep the recognizable checkpoint silhouette and the Sekisho name; 関所 is a small signature |
| Hero imagery | One original sculptural checkpoint, with a single blue payment path through a translucent boundary |
| Composition | Dark, quiet copy area; luminous form offset to the right; generous negative space |
| Proof | Real product captures and readable decision trails, with fixture status disclosed |

The difference from the current packaging is material: replace the poster-like three
colored verdict boxes with one spacious image and a short headline. Put the detailed
ALLOW / HOLD / BLOCK explanation below the hero, where it is useful product content.

## Proposed visual tokens

| Token | Value | Role |
|---|---|---|
| Midnight | #061234 | Hero and cover background; strong headings on light surfaces |
| Signal blue | #315BFF | Primary marketing action and focal detail |
| Signal hover | #2445D8 | Hover and pressed emphasis |
| Ice | #EAF2FF | Quiet section tint |
| White | #FFFFFF | Reading and evidence surfaces |
| Slate | #536079 | Supporting copy on light surfaces |
| Hairline | #DCE3F0 | Dividers and subtle borders |
| Cyan light | #9DDEFF | Illustration lighting only, not small text |

Retain the console's semantic allow green, hold amber, block red, and fixture purple.
Blue always identifies an action or the brand, not an ALLOW verdict. Verify contrast
for every actual text/background pairing before implementation.

Marketing headings: Inter Tight 500/600, 48–64px desktop, 36–42px mobile, line height
1.05–1.12, modest negative tracking. Body: 17–18px, line height 1.5–1.65, comfortable
55–65 character measure. Keep the console's Atkinson Hyperlegible and mono evidence
fonts until an intentional app-wide typography change is tested.

Marketing layout: 1200px content maximum; 32px desktop gutters and 20px mobile;
96–128px major section spacing desktop, 56–72px mobile. Hero/media radius 28–32px;
feature surfaces 16–20px; marketing CTA radius 999px. These are proposed values, not
measured source constants or changes already made to runtime tokens.

## Website direction

Audience: agent builders, hackathon judges, and operators evaluating how an agent
payment is screened and reviewed. Primary outcome: understand the checkpoint and
open the working local demo or integration guide.

1. **Hero.** Existing mark and short navigation (How it works, Console, Integrate).
   Headline “Before the agent signs.” Supporting sentence: “Sekisho screens agent
   payments before signing, routes holds to human review, and records decisions onchain.”
   Primary CTA “Explore the console”; secondary “Read the integration guide.” Until a
   hosted demo exists, link to the verified local quick start rather than a dead URL.
   Clearly label testnet/demo status.
2. **Decision boundary.** A horizontal three-step story: screen → decide → attest.
   Explain ALLOW, HOLD, and BLOCK as a compact row, using words and icons with color.
3. **Product proof.** One wide real console screenshot followed by a focused case-review
   detail. Preserve fixture labels until genuine live captures replace them.
4. **Human control.** A restrained split section: evidence and the officer's release/refund
   action. Describe the escrow rule and report verification in concrete language.
5. **Integration.** SDK and MCP entry points, code example, links to actual docs.
   Identify integrated technologies as integrations, not customer endorsements.
6. **Closing invitation.** “Put a checkpoint before your next agent payment.” Link to
   the quick start and repository, followed by the demo-policy and readiness notes.

The public landing page is implemented in `website/` and published at
[getsekisho.vercel.app](https://getsekisho.vercel.app). The operational console's
routes retain their operational behavior. Its shared palette, borders, corners, and
heading typography now follow this direction while keeping Atkinson body text.

## Console direction

Use the same visual family at operational density. White evidence panels, dark navy
headings, quieter borders, more consistent spacing, and a precise blue active state.
Reserve atmospheric artwork for the marketing surface; keep report text, amounts,
addresses, verdicts, and officer actions on solid backgrounds. Retain readable body
sizes, status text, keyboard focus, and confirmation flows. Product behavior remains
governed by [UX-CONTRACT.md](../UX-CONTRACT.md).

## Asset family

- **Repository banner, 1280×640:** mark/name at upper left, short headline beneath;
  original checkpoint sculpture on the right. Keep copy clear at a 640px rendered width.
- **Social card, 1280×640:** same artwork and hierarchy, repo address and testnet label;
  keep essential content inside a 64px safe margin.
- **Website hero:** wide crop with safe copy space and a separate mobile composition;
  do not stretch or crop the checkpoint out of the frame.
- **Logo:** retain a flat vector master for small-size clarity. The 3D object is campaign
  imagery, not a replacement favicon.
- **Product screenshots:** capture the real UI; label fixtures honestly; keep them flat
  and readable rather than embedding them in tiny decorative device mockups.
- **Deck covers:** reuse one consistent checkpoint image and restrained type system.

Use original or licensed artwork. The reference establishes taste; its paid template
assets, stock marks, sample investor metrics, and testimonials are not Sekisho assets.

## Acceptance criteria

The page should feel spacious before it feels decorative. One blue focal point carries
each composition. Headlines remain legible without effects; every screenshot adds
verifiable product understanding. Decorative motion respects reduced motion. No new
claim of deployment, safety certification, customer adoption, or live provider performance
comes from presentation changes. Build and review the website, console, and asset family
as related surfaces with different reading needs.

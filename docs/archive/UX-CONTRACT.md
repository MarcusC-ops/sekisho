# UX contract

## Product context and sources

English-language operational console for a hackathon demonstration, not a certified
financial programme. Primary users are the demonstrator and compliance officer. The
PRD (9.11, 10.6), docs/api.md, and gate models define lifecycle and money semantics.
PITCH_PLAN.md defines the demo journey. No market-specific legal behavior is inferred
from the event location. Accessibility target: WCAG 2.2 AA. Full timestamps use the
viewer's local timezone and include its name.

## Visual contract

DESIGN.md describes the established identity. dashboard/app/tokens.css is the canonical
token source; globals.css and shared components consume it. Only light mode is supported.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Read-only table | components/ui/DataTable.tsx | docs/api.md, this contract | scrollable table | keyboard and narrow-screen check |
| Loading/error/empty | components/ui/Panel.tsx | this contract | stale data with visible error | browser failure paths |
| Navigation | Next Link, AppShell | PRD 10.6 | route, URL filter, cursor | browser back and route checks |
| Form | components/case/OfficerActions.tsx | PRD 9.11 | release/refund | fixture review flow |
| Scrollbar | app/globals.css and tokens.css | DESIGN.md | geometry-only table gutter | computed style |
| Feedback | Panel, OfficerActions, live.ts | docs/api.md | inline alert or status | browser errors and success |
| CRUD | lib/api.ts, OfficerActions, lib/cases.ts | PRD 9.11 | pessimistic officer mutation | review to case to result |
| Dialog | components/ui/Modal.tsx | PRD 9.11 | explicit confirmation | keyboard and Escape |

No new select/listbox, date editor, table selection, or toast provider is introduced.

## Dataset navigation

The hold queue reads 50 HOLD decisions per cursor and displays only pending cases in
that batch. Older holds remains available even when a batch contains no pending cases.
Cursor lives in the URL; latest navigation clears it. SSE revalidates older pages and
updates the first page. Settled holds must disappear from the pending queue.

The audit endpoint exposes a bounded recent window, not cursor pagination. The UI clearly
labels the latest 100 events. Event-type and optional case filters live in the URL; the
event-type filter applies within that window. Counterparty book uses URL page numbers,
20 entries per page, clamped to the available pages. Exposure charts show the top 20
payees and disclose that limit when exceeded. There is no selection or bulk action.

## Flow ledger

| Operation | Trigger | Pending | Success | Failure recovery |
|---|---|---|---|---|
| Review hold | Open case | detail loading | case evidence and officer panel | inline error and retry |
| Officer action | note then Release/Refund then confirm | disabled duplicate submission, tx progress | updated case status and tx links | decoded error, refresh state before retry |
| Audit filter | event-type link | resource loading if needed | matching recent events, selected link | shared error with retry |
| Refresh | Refresh button | disabled while validating | current resource rendered | stale data retained with error |
| Verify | Verify report | verification status | Match/Mismatch against chain hash | explicit unavailable/failure state |

## Resilience and data semantics

No optimistic money mutations. Never turn a missing balance or failed Event Query into
zero. Treasury errors display alongside the available fields. Treasury polls every 60 s
because its chain reads are cached for that interval. Cumulative Held and Released totals
are historical; current outstanding funds are the contract's totalHeld read.

SSE reconnect revalidates caches. The gate decides and authorizes lifecycle changes; UI
button availability is guidance, not security. Existing API supports only the local demo
operator model, not production authentication or multi-tenant access.

## Navigation and accessibility

Every route has a descriptive title and h1. Navigation is semantic links; filters use
aria-current. Tables are semantic and their horizontal scrollers have names and keyboard
focus. Preserve document scrolling. Shared loading and error components announce state;
never move focus on automatic refresh. Full values remain copyable. The existing Modal
owns focus, Escape and restoration. Reduced-motion behavior is global.

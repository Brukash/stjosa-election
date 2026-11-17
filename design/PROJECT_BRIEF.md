# PROJECT BRIEF — St. John's College Jos Alumni Election

MODE: Redesign / Polish (4) · SURFACE: Code-first (C)
STATUS: brief approved by the user ("go ahead with the redesign"), public surface first.
DEPLOY RULE: **Do not push or deploy until the user approves the redesign.** Build and preview locally only.

## Product and audience

Official remote voting platform for the St. John's College Jos Alumni Association.
Two audiences, deliberately separated:

1. **Voters** — alumni, often on a phone, not technical, sometimes low digital confidence.
   They need: what this is, when it closes, what they need (Voter ID), how to vote, proof their vote counted.
2. **Committee officials** — Chairman, Returning Officer, Accreditation Officer, Observer, Super Admin.
   They need the existing admin back office, unchanged in behaviour.

## Visual thesis

A printed civic notice, not a SaaS dashboard: warm paper, one deep institutional green,
an ochre accent used only for status and numbering, editorial serif headlines against a
plain grotesque for reading. Evidence of integrity is stated in plain language and kept
off the voter's path; the cryptographic record lives behind its own page.

## Hierarchy

1. Can I vote, and until when?
2. What do I need to do it (Voter ID from email)?
3. How do I know my vote is secret and counted?

## Type

- Display: **Fraunces** (variable serif, warm, institutional but not stuffy) — headlines only.
- Text: **Public Sans** (neutral civic grotesque) — body, labels, UI.
- Numbers and identifiers: Public Sans with tabular figures; monospace reserved for the evidence page.
- No Georgia, no Segoe UI, no system stacks as the final design.

## Palette (roles, not decoration)

| Token | Value | Role |
| --- | --- | --- |
| `paper` | `#F4EFE3` | page ground (warm off-white) |
| `surface` | `#FFFCF5` | raised card / ballot paper |
| `ink` | `#16241C` | primary text, near-black green |
| `forest` | `#0E3B2A` | brand, primary actions, masthead |
| `moss` | `#2E6B4F` | secondary text/links, hover |
| `ochre` | `#B0731F` | accent: status, numbering, rules of emphasis |
| `clay` | `#8C3B2E` | rare alert/emphasis only |
| `rule` | `#DAD2C0` | hairlines, table rules |

No gradients, no glass, no purple, no glow.

## Layout and signature moment

- Masthead with crest, wordmark, four voter destinations, one admin entry.
- **Signature: the ballot card.** Hero right column is a printed ballot: election name, a ruled
  list of the real positions from the API, a status stamp ("Voting open"), and the closing date.
  It is generated from live data, not a picture, and it is the visual anchor of the page.
- Sections alternate: full-width statement band on paper, then a ruled editorial block.
  Never two identical card grids in a row.

## Copy rules

- Plain words. No "Merkle", "RSA", "AES", "Ed25519", "commitment", "ciphertext", "tally key",
  "cast-as-intended" in voter-facing copy. Those live on `/commitments` and the evidence page.
- No invented statistics, testimonials, member counts, or quotes.
- Never claim a security property in copy that the system does not actually provide.

## Information architecture change

- Top navigation: **Home · Vote · Results · Verify**. `Commitments` moves out of the primary nav
  into the footer and the evidence page, because it is an audit artifact, not a voter task.
- Every technical identifier (election reference, hashes, fingerprints) is removed from the
  hero and homepage. The reference appears only where it is needed (ballot, receipt).

## Constraints

- Preserve all routes, API calls, auth, and voting behaviour. This pass is presentation and
  information architecture only; no backend changes.
- Keep existing global class names (`card`, `btn`, `input`, `pill`, `table`, `kv`, `code`) so the
  admin area keeps working, but retune their values.
- WCAG AA contrast, visible focus, 44px touch targets, keyboard-operable mobile menu.
- Mobile is a first-class layout, not a shrink: masthead must not overlap or clip at 390px.

## Status checklist

| Area | L1 structure | L2 content | L3 wiring | L4 motion | L5 polish |
| --- | --- | --- | --- | --- | --- |
| Tokens + fonts | done | done | — | — | done |
| Masthead / footer / mobile menu | done | done | done | done | done |
| Home | done | done | done | done | done |
| Accredit | done | done | done | done | done |
| Vote (header, empty state) | done | done | done | done | done |
| Vote ballot marking / review / sealed / challenge | done | done | done | done | done |
| Vote receipt (cast state) | done | done | done | done | pending (not seen with real data) |
| Verify | done | done | done | done | done |
| Results | done | done | done | done | partial (declared-results layout unseen) |
| Commitments | done | done | done | done | done |
| Receipt | done | done | done | done | done |
| Admin | tokens inherited only (out of scope) | — | — | — | — |

## Decision log

- 2026-11-17 — Mode 4 + code-first chosen; admin untouched in this pass.
- 2026-11-17 — Removed cryptographic vocabulary from voter surfaces; `/commitments` demoted from nav.
- 2026-11-17 — MITEMS Studio OS repo was not present locally; proceeding on the user's explicit
  instruction ("go ahead") without it, per the authority order in AGENTS.md.
- 2026-11-17 — Pass 1 complete: tokens, fonts, masthead/footer/mobile menu, home, accredit, vote header
  and empty state. Vote marking/review/receipt and the evidence pages are pass 2.
- 2026-11-17 — Verification limit: the browser window would not resize to 1440 after a disconnect;
  widest inspected width is 1280, mobile inspected at true 390 through an iframe harness.
- 2026-11-17 — Pass 2 complete: ballot marking, review, sealed, challenge and cast screens; verify,
  results, commitments, receipt and the election chooser rebuilt. Ballot action bar is `fixed` on
  mobile (sticky was clipped by an ancestor) with a 96px spacer.
- 2026-11-17 — Cleanup pass: removed unused tokens (`leaf`, `gold`, `moss`) and merged the duplicate
  neutrals (`line` → `rule`, `cream` → `paper`, same values, 21 call sites); deleted dead CSS
  (`.prose-note`, `.rule-band`, `.lift`), the unused `hexToBytes`/`clearCredential` in the credential
  lib, an unused `getProfile` import, an unused `Card` import, and un-exported the internal
  `LinkButton`. Ballot card lost its misused `figure/figcaption` wrapper and a filler divider;
  mobile menu now renders a self-contained `MobilePanel` that owns Escape/scroll-lock/focus, with
  one shared link list instead of two copies.
- 2026-11-17 — Genuine 1440 verified (window resize now works): home hero, home lower sections,
  ballot sheet, accredit, verify, results, commitments. No overflow on any public route
  (scrollWidth 1423 of 1440). One typographic fix: candidate manifesto ran ~100 characters a line;
  bio and manifesto now cap at `max-w-[72ch]` inside the row, landing at ~85 characters with a right
  margin, and the text sizes moved 13 → 13.5px and 12.5 → 13px. 390 unchanged (text 295px, no cap).
- 2026-11-17 — Admin verified on the retuned tokens (login, dashboard, register, ballot, counting,
  results at 1440 and 390). One defect found and fixed: the dashboard election selector overflowed
  390 by 35px (`!w-auto` select in a flex row) — now `w-full sm:!w-auto` with `min-w-0`.
  Super Administrator is correctly gated out of the workspace tabs; Chairman sees them.
- 2026-11-17 — Local demo data touched only by accreditation (SJC/AL/2004/002, SJC/AL/2005/003) and
  one prepared-but-never-cast ballot, to inspect the real ballot at 390. No vote was counted; no
  production data or deployment touched.

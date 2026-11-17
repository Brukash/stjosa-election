# REFERENCES

Principles only. No layout, palette, copy, or identity is copied from any of these.

## 1. NYC Votes — voting.nyc (redesign case study)

- **What it is:** New York City Campaign Finance Board's voter-facing site, redesigned for the 2021
  city-wide primary. Case study: `https://www.hannahcusworth.com/nyc-votes`.
- **Observed (from the published case study):** a flexible component system rather than one-off pages;
  accessibility treated as a design input, not a retrofit; the tone is civic and warm instead of
  bureaucratic grey.
- **Principle taken:** *one systematic language across every voter task*, with warmth coming from
  typography and colour rather than decoration.
- **Not taken:** their brand colours, their illustrations, their layout.

## 2. Center for Civic Design — Designing election department websites

- **What it is:** research-backed fieldguide: `https://civicdesign.org/fieldguides/designing-election-department-websites`
- **Observed:** voters read straight down the middle of a page and miss left/right content; links and
  headings phrased as the questions voters actually ask; keep the banner small so content gets the room;
  plain language matters because a large share of adults read below an advanced level.
- **Principle taken:** single reading column for the primary task, question-shaped headings, and a
  masthead that does not eat the first screen.

## 3. CTCL / U.S. Digital Response — Election Website Template

- **What it is:** `https://electionwebsitetemplate.org/` (described by `https://electionexcellence.org/resources/election-website-template`)
- **Observed:** mobile-first by default, modular tiles that can be recombined per page, content
  organised by what the voter is looking for rather than by internal department structure.
- **Principle taken:** mobile is the base layout; pages are composed from a small set of modules.

## 4. U.S. Election Assistance Commission — Effective Design guidance

- **What it is:** `https://www.eac.gov/` design guidance for election administration.
- **Observed:** visually distinct heading levels, good contrast, consistent buttons, clear links,
  one subject per page, simple forms.
- **Principle taken:** the hierarchy must be legible at a glance — size, weight and rule lines do the
  work that colour alone must not.

## Implementation notes

- Wordmark is a text lockup beside the existing crest (`frontend/public/Josa.png`); no new logo invented.
- Type: Fraunces (display) + Public Sans (text), both open-source, served through `next/font`.
- No photography is available, so no stock people are used. The ballot card carries the visual weight.

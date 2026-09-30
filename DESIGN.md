---
name: UndoCI
description: Offline rollback rehearsal evidence in graphite and amber.
colors:
  bg: "#101112"
  panel: "#191b1d"
  line: "#35383c"
  text: "#f2f0ea"
  muted: "#adb1b7"
  amber: "#ffb14a"
  green: "#9dddba"
  red: "#ffada2"
typography:
  display:
    fontFamily: "system-ui, sans-serif"
    fontSize: "clamp(2rem, 5vw, 3.7rem)"
    fontWeight: 700
    lineHeight: 1.08
    letterSpacing: "-.035em"
  headline:
    fontFamily: "system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    letterSpacing: "-.02em"
  body:
    fontFamily: "system-ui, sans-serif"
    fontSize: "16px"
    lineHeight: 1.6
  label:
    fontFamily: "ui-monospace, monospace"
    fontSize: "12px"
    lineHeight: 1.4
    letterSpacing: ".06em"
  code:
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: "13px"
    lineHeight: 1.6
rounded:
  select: "4px"
spacing:
  compact: "12px"
  standard: "24px"
  mobile-gutter: "20px"
  desktop-gutter: "40px"
components:
  verdict:
    textColor: "{colors.amber}"
    typography: "{typography.label}"
    padding: "7px 12px"
  verdict-passed:
    textColor: "{colors.green}"
  verdict-error:
    textColor: "{colors.red}"
  filter:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.select}"
    padding: "8px 12px"
  signature:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    typography: "{typography.code}"
    padding: "18px"
  journal-row:
    padding: "18px 14px"
  journal-row-hover:
    backgroundColor: "{colors.panel}"
---

# Design System: UndoCI

## Overview

**Creative North Star: "The rollback evidence ledger"**

This is a descriptive metaphor derived from the existing report, not a newly approved brand concept. The report pairs a large, plain-language verdict with dense technical evidence. A graphite canvas, restrained amber emphasis, system typography, and fine dividers keep attention on the investigation.

Scope: the incumbent offline report in `src/undoci/templates/report.html`, its generated journal markup in `src/undoci/report.py`, and the rendered `docs/assets/report-preview.png`. The README banner is a related identity asset; its image treatment does not prescribe report layout.

**Key Characteristics:**

- A prominent verdict followed by progressively detailed evidence.
- Flat surfaces and thin structural dividers.
- Monospace identifiers, state labels, and timing.
- Native browser controls and locally embedded assets.

## Colors

### Primary

Amber marks the brand suffix, lifecycle numbering, boundary identifier, retained actions, links, and focus outlines.

### Secondary

Green and red carry outcome meaning in the main verdict and event status. Journal summary status text currently uses the default amber state style regardless of outcome; do not infer a color mapping absent from its markup.

### Neutral

The background is near-black graphite. The panel tone groups signatures, notes, controls, and hovered journal summaries. Pale text carries primary reading; muted text carries context and metadata. The line tone separates structural regions.

**The Evidence Rule.** Keep explicit status and retained/removed text beside color; the implementation does not communicate these distinctions through color alone.

## Typography

System sans-serif handles reading and hierarchy; system monospace handles technical evidence. Font files are not downloaded. The frontmatter records the actual repeated roles rather than a new typographic scale.

The display headline is balanced and constrained to 17 characters per line on desktop, widening to 19 on narrow screens. Supporting descriptions and evidence paragraphs generally stop at 65 characters; trial explanations and footer copy use 75. The wordmark uses bold system type (28px, weight 800) with a contrasting CI suffix. State labels are uppercase.

## Layout

The centered shell includes its gutters within a maximum width of 1180px. Desktop gutters are 40px. The headline pairs a flexible main column with 240px metadata and a 52px gap; the evidence region uses equal columns with a 64px gap. The four-stage lifecycle spans a horizontal ruled band.

At 760px and below, gutters shrink to 20px, headline and evidence stack, metadata becomes a two-column grid, lifecycle items wrap, and journal summaries become two columns. Tables retain a 720px minimum width inside a horizontally scrollable, keyboard-focusable region. Long identifiers wrap.

Print switches the canvas to white and text to black, hides navigation and the filter, and uses darker status emphasis. It does not automatically open collapsed journal entries.

## Elevation & Depth

There are no shadows, gradients, or animated transitions in the report. Tonal panels and one-pixel rules establish grouping without raised cards. Hover changes the journal summary's background immediately.

## Shapes

The report uses rectangular bands, panels, and rows. Verdict labels have a one-pixel outline in their current text color. The native select is the only explicitly rounded control, using the frontmatter radius. Avoid generalizing that radius into a card system.

## Components

### Verdict

A compact outlined state label precedes the large outcome headline. Passed uses green, regression and execution error use red, and inconclusive uses amber.

### Evidence downloads

Three underlined text links expose JSON, JUnit, and the replay manifest. Navigation text is muted by default and becomes primary text on hover. It wraps on narrow screens. There are no custom action buttons.

### Filter

A labeled native select filters rehearsal details by status. It uses the panel background and line border. An empty result message appears when needed, and an `aria-live` count announces changes. The implementation has no search input.

### Signature and action sequence

The failure signature sits in a padded flat panel. Action rows use bottom rules; retained code is amber while removed code is muted and struck through, with an explicit text label for each state.

### Rehearsal journal

Native `details` and `summary` provide expandable rows. A plus/minus marker precedes each trial identifier, with status, action count, and elapsed time alongside. Expanded evidence includes a five-column event table. Focusable links, summaries, selects, and table regions use a two-pixel amber outline offset by five pixels.

## Do's and Don'ts

### Do:

- **Do** preserve text labels alongside status colors.
- **Do** keep identifiers and evidence readable with wrapping or local table scrolling.
- **Do** retain the report's offline system fonts and embedded assets.

### Don't:

- **Don't** replace structural rules with elevated card styling when extending this report.
- **Don't** turn the report's limited evidence into a universal safety claim.
- **Don't** invent new component variants or motion as if they were incumbent tokens.

# Design — StudyThing

A locked design system for this app. Every page redesign reads this file before
emitting code. Do not regenerate per page — extend or amend this file when the
system needs to grow. Produced by `hallmark redesign` (theme: Cobalt, user-named).

## Genre
modern-minimal

## Macrostructure family
- App pages: **Workbench** — persistent side-rail + main content column; hairline-ruled
  sections, function carries the page. No hero, no marketing sections, no enrichment.
- Marketing pages: n/a (this app has none).

## Theme — Cobalt
Cool engineered light, hairlines, one electric-cobalt signal. Never `#fff`, never `#000`.

- `--color-paper`      oklch(98.5% 0.004 250)
- `--color-paper-2`    oklch(96% 0.005 250)
- `--color-paper-3`    oklch(93.5% 0.006 250)
- `--color-ink`        oklch(24% 0.02 258)
- `--color-ink-2`      oklch(34% 0.018 257)   (body text)
- `--color-muted`      oklch(52% 0.015 257)
- `--color-rule`       oklch(91% 0.006 250)
- `--color-rule-2`     oklch(84% 0.008 250)
- `--color-accent`     oklch(58% 0.20 256)    (electric cobalt — the ONE signal)
- `--color-accent-ink` oklch(98.5% 0.004 250) (text on cobalt)
- `--color-focus`      oklch(58% 0.20 256)
- `--color-graphite`   oklch(22% 0.016 260)   (the one dark beat: transcript surfaces)
- `--color-graphite-2` oklch(88% 0.01 250)    (text on graphite)
- `--color-good`       oklch(55% 0.09 155)    (semantic only — status badges)
- `--color-bad`        oklch(52% 0.17 25)     (semantic only — errors)

Accent discipline: cobalt is a signal (< 5% of any viewport) — primary buttons, active
nav tick, focus rings, live-timestamps, the `Done` chip. Never a flood, never gradients.

## Typography
- Display: **Space Grotesk**, weight 500/600, style normal (italic headers banned)
- Body:    **Inter**, weight 400/500
- Mono:    **JetBrains Mono**, weight 400/500 — eyebrows, meta, badges, timestamps, kbd
- Display tracking: -0.01em; mono labels: uppercase, +0.06em tracking
- All-sans. No serif anywhere.

## Spacing
4-point named scale (`--space-*`) in `styles.css`. Pages use tokens, never raw values.

## Motion
- Easing: `cubic-bezier(0.16, 1, 0.3, 1)` (`--ease-out`); durations 150–220ms
- Reveal pattern: none (app — no scroll reveals)
- Hover: 1px border-colour shift to cobalt on focusable surfaces; cobalt underline on links
- Reduced-motion: transitions off, everything fully visible

## Microinteractions stance
- Silent success (no toasts, no celebratory animation)
- Focus rings: 2px cobalt, `:focus-visible` only
- Progress: quiet bar, cobalt fill

## CTA voice
- Primary CTA: solid cobalt, 6px radius (never a pill), verb + destination ("Study", "Assign")
- Secondary CTA: ghost — transparent, ink text, hairline border on hover
- Destructive: ghost, `--color-bad` text on hover

## Per-page allowances
- App pages MUST NOT use enrichment — function carries the page.
- The one dark beat: transcript viewer renders on `--color-graphite` (mono, code-as-hero
  register). Nothing else goes dark.

## What pages MUST share
- The wordmark ("Study**Thing**" — ink + cobalt).
- The accent colour and its placement (≤ 5% per viewport).
- The display + body + mono faces.
- The CTA voice (solid-cobalt / ghost, 6px radius).
- Section head rhythm (Space Grotesk head + JetBrains-Mono meta).

## What pages MAY differ on
- Section order and density within the Workbench family.
- Nothing else — consistency is the goal across app views.

## Legacy token aliases (styles.css)
The app's existing rules reference older names (`--text`, `--muted`, `--accent`,
`--line`, `--good`, `--bad`, `--r-*`, `--serif`/`--sans`). These are **aliases** of the
tokens above — single source of truth stays in the `:root` block of `styles.css`.

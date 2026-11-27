# Design

How Škoda Mate looks and behaves. The tokens themselves live in `skoda_mate/static/style.css` (`:root` and the two dark
blocks). That file is the source of truth for values; this document explains the intent behind them. Code conventions for
pages (shell contract, `h()`, `ui.js` components) are in [docs/DASHBOARD.md](docs/DASHBOARD.md).

## Principles

- **Calm when everything is fine.** A car that is locked, closed and charging as planned shows a short summary line, not a
  wall of green chips. Colour and emphasis are kept for what needs attention.
- **Honest data.** Trips and charges are derived by Mate, not reported by Škoda. Estimates are labelled as estimates, and
  inferred charges say why Mate did not see them live. A missing value renders as "unknown" or "–", never as closed, off or 0.
- **Only real controls.** A button exists only for what the official API can do and this car supports. A feature the car
  lacks shows its reason instead of silently disappearing.
- **One screen, every size.** Mobile first from 360 px; nothing scrolls sideways.

## Colour

The palette follows Škoda's own API documentation: dark emerald `#0e3a2f` and electric green `#78faae`.

| Role | Light | Dark | Use |
|---|---|---|---|
| `--accent` | emerald `#0e3a2f` | electric green `#78faae` | primary buttons, active nav, focus ring |
| `--accent-ink` | white | emerald | text on `--accent` |
| `--accent-soft` | pale green | deep green | good chips, selected rows |
| `--good` / `--warn` / `--bad` / `--info` | | | status text and icons, each with a `-soft` background |
| `--bg` < `--surface` < `--surface-2` < `--surface-3` | | | page, cards, insets, pressed states |
| `--fg` / `--muted` | | | body text, secondary text |
| `--line` / `--control-line` | | | dividers; form-field borders (3:1 against the surface) |
| `--chart-1…4`, `--chart-grid` | | | chart series in a fixed order, grid lines |

Rules:
- Use the variables only. A hard-coded colour breaks one of the three themes: light, dark, or auto (`prefers-color-scheme`,
  overridable with `data-theme`).
- Status is never colour alone: every chip and banner also has an icon or a word.
- Contrast: text at least 4.5:1 (large text 3:1), form-field borders and focus at least 3:1, in both themes. Check with
  `scripts/dom-smoke/a11y_contrast.mjs` and `a11y_axe.mjs` after a palette change.

## Typography

System font stack (`system-ui`, -apple-system, Segoe UI, Roboto); no web fonts. Body 15px/1.5.

| Element | Size | Weight | Notes |
|---|---|---|---|
| `h1` | 24px | 600 | one per page |
| `h2` | 19px | 600 | card titles |
| `h3` | 13px | 600 | muted, sentence case, no letterspacing |
| stat value | large, with a 14px muted unit | 600 | |
| `.small` / `.tiny` | 13px / 12px | | hints, meta, chips |
| car name in the header | 21px (18px on phones) | | |

No uppercase micro-labels and no letter-spacing on small text; hierarchy comes from size and colour, not weight. The scale is
24 / 21 / 19 / 15 / 13 / 12 / 11px over two weights, 400 and 500, with 600 for headings, figures and the label of a primary
action. Numbers are `tabular-nums` (set on `body`) and formatted the same way everywhere. Headings follow document order:
no skipped levels.

## Shape, space, depth

- Radius: `--radius` 12px for cards, `--radius-sm` 8px for inputs, banners and insets; buttons and chips 6 to 8px. Pills are
  reserved for the car switcher and the battery bar, not for every label.
- Spacing: 4px grid. `--gap` 16px between cards; cards pad 20px, the page 24px (16px on phones), sidebar rows 8px by 12px.
  Settings forms use one spacing scale with section dividers, inline form rows with aligned buttons, and capped field widths.
- Depth: the hairline edge does the work on cards (`--shadow` is a 1px whisper, `none` in dark mode); `--shadow-float` is for
  things that truly float above the page (dialogs, sheets, toasts, sticky bars). Depth in dark mode comes from surface steps.
- Cards in a grid row share their height; toggles and actions sit at the card's bottom. A last stat tile that would sit alone
  on a phone row spans the full width instead.

## Layout

- Desktop: a 248px sidebar (`--sidebar`) and a 60px header (`--header`) with car name, plate, health dot, request-budget meter
  and theme switch. With several cars a car switcher shows in the header.
- Below 960px the sidebar becomes a bottom tab bar with 5 entries and a "More" sheet; toasts move above it.
- Grids: `.g2/.g3/.g4` drop to two columns below 960px and to one below 560px.
- Wide tables scroll inside `.scroll-x` (keyboard-reachable), never the page.

## Components

Build pages from `ui.js` (card, stat, chip, button, banner, empty, loading, field, seg, kv, socBar, table, modal,
confirmDialog, toast) so they share these looks:

- **Buttons**: default is outlined on `--surface`; `.primary` fills with `--accent`. Async buttons show a spinner and are
  disabled while busy. Save and Set buttons stay disabled until something changed.
- **Start/Stop controls**: one toggle per function with optimistic state; it explains why it is disabled (e.g. charging while
  unplugged).
- **Chips**: small rounded labels (6px) for state (good / warn / bad / info), always with text, never icon-only.
- **Banners**: for page-level problems or notices, with a soft background, a tinted border and an action link where one helps.
- **Empty, loading and error states** exist for every fetch.
- **Destructive actions** go through `confirmDialog`.
- **Car picture**: Škoda's own render (the API's `renderUrl`) when available, otherwise the drawn silhouette.
- **Maps**: Leaflet with OpenStreetMap tiles, markers sized by importance, an offline fallback that shows the coordinates.

## Motion

Small and quick: `--t-fast` 120ms for colour and transform, `--t-med` 200ms for entrances, easing `--ease`
(`cubic-bezier(.16, 1, .3, 1)`). Motion explains something and nothing else: one entrance per navigation (`.page`), a press
scale of .98, dialogs and toasts arriving from where they sit, a bar that grows because its value changed. No looping
decoration — no pulsing glows, shimmer, drifting stripes, hover lifts or attention shakes; a poll refresh must not animate.
Everything animated turns off under `prefers-reduced-motion`.

## Interaction and accessibility

- Visible focus: a 2px `--accent` outline with an offset, on every focusable element.
- Touch targets: at least 44px on coarse pointers (buttons, inputs, interactive chips).
- A skip link and a `main` landmark on every page; inputs have labels.
- Verify phone layout and console errors with `scripts/dom-smoke/browser_e2e.mjs` against a demo server.

## Voice

- Write **Škoda** with the háček, also in German ("Škodas" for the genitive).
- Plain, short sentences that say what happened and what to do next ("Škoda's request limit is used up; try again in 5 min.").
- Every visible string goes through `t('English')` and has a German entry. `scripts/dom-smoke/i18n_coverage.mjs`,
  `pseudo_pass.mjs` and `german_leaks.mjs` find gaps ([docs/TRANSLATIONS.md](docs/TRANSLATIONS.md)).
- Leave room: other languages run about 40 % longer. Let rows, tabs and chips wrap; never size a control to its English.

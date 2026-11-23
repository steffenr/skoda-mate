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
| `h1` | 24px | 650 | one per page |
| `h2` | 19px | 650 | card titles |
| `h3` | 14px | 600 | muted, uppercase, letter-spaced section labels |
| stat value | large, with a 14px muted unit | 600+ | |
| `.small` / `.tiny` | 13px / 12px | | hints, meta, chips |
| car name in the header | 21px (18px on phones) | | |

Headings use a slight negative letter-spacing (-.01em) and line-height 1.2. Headings follow document order: no skipped levels.

## Shape, space, depth

- Radius: `--radius` 14px for cards, `--radius-sm` 9px for banners and insets, 10px for buttons, pill (`99px`) for chips.
- Spacing: `--gap` 16px between cards; cards pad 18px. Settings forms use one spacing scale with section dividers, inline form
  rows with aligned buttons, and capped field widths.
- Depth: one soft `--shadow` on cards, heavier in dark mode. No stacked shadows.
- Cards in a grid row share their height; toggles and actions sit at the card's bottom. A last stat tile that would sit alone
  on a phone row spans the full width instead.

## Layout

- Desktop: a 236px sidebar (`--sidebar`) and a 60px header (`--header`) with car name, plate, health dot, request-budget meter
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
- **Chips**: small pills for state (good / warn / bad / info), always with text.
- **Banners**: for page-level problems or notices, with a soft background, a tinted border and an action link where one helps.
- **Empty, loading and error states** exist for every fetch.
- **Destructive actions** go through `confirmDialog`.
- **Car picture**: Škoda's own render (the API's `renderUrl`) when available, otherwise the drawn silhouette.
- **Maps**: Leaflet with OpenStreetMap tiles, markers sized by importance, an offline fallback that shows the coordinates.

## Motion

Small and quick: `--t-fast` 120ms for colour and transform, `--t-med` 200ms for shadows and toasts, easing `--ease`
(`cubic-bezier(.16, 1, .3, 1)`). Motion confirms an action (toast in, button press, bar width). Decorative motion such as a
rolling car was tried and removed. Everything animated turns off under `prefers-reduced-motion`.

## Interaction and accessibility

- Visible focus: a 2px `--accent` outline with an offset, on every focusable element.
- Touch targets: at least 44px on coarse pointers (buttons, inputs, interactive chips).
- A skip link and a `main` landmark on every page; inputs have labels.
- Verify phone layout and console errors with `scripts/dom-smoke/browser_e2e.mjs` against a demo server.

## Voice

- Write **Škoda** with the háček, also in German ("Škodas" for the genitive).
- Plain, short sentences that say what happened and what to do next ("Škoda's request limit is used up; try again in 5 min.").
- Every visible string goes through `t('English')` and has a German entry. `scripts/dom-smoke/i18n_coverage.mjs` and
  `german_leaks.mjs` find gaps.

# Solaris — Dynasty Desk

Design spec for the fantasy football dashboard app's UI. This covers the visual system and the first screen (Dashboard / Overview) built so far, plus the full spec for the "Team Colors" feature. Reference mockup (interactive): https://claude.ai/code/artifact/fa9dd103-c093-4019-ac08-1813ea3d3fb5

## 1. Direction

Mid-century modern meets solarpunk, executed as a **WPA / Bauhaus travel-poster** aesthetic: flat color blocks, bold black outlines and rules, no gradients, no drop shadows, no rounded-corner-with-left-border-accent cards. The whole page sits inside a black "picture frame" border, like a mounted print.

The solarpunk half of the brief shows up only in the accent color story (green / yellow / sky-blue) — not in illustration or texture.

## 2. Typography

- **Headlines / titles / section headers / big numbers**: geometric mid-century poster sans, all caps, bold (700–800 weight).
  - Target font: **Tipique Regular** (paid foundry font, not available via Google Fonts).
  - Stand-in used in the mockup: **Jost** (Google Fonts) — closest free match to that lettering style. Swap in the real Tipique font file if/when available; keep Jost as the fallback in the font stack.
  - Applied to: nav wordmark, page title ("Overview"), section titles ("Your Leagues", "Arbitrage Signals"), card league names, stat tile numbers.
- **Everything else (body copy, labels, nav items, badges, captions)**: **Work Sans** (Google Fonts), weights 400–700.

```css
/* headline */
font-family: 'Jost', system-ui, sans-serif;
text-transform: uppercase;

/* body */
font-family: 'Work Sans', system-ui, sans-serif;
```

## 3. Color system

Two groups of tokens: fixed neutrals, and three **dynamic accent slots** that the Team Colors feature rewrites at runtime.

### Fixed tokens

| Token | Value | Use |
|---|---|---|
| `--paper` | `oklch(96% 0.018 80)` | Page/card background (off-white) |
| `--ink` | `oklch(15% 0.012 50)` | Primary text, borders, rules (near-black, warm) |
| `--ink-soft` | `oklch(15% 0.012 50 / 0.55)` | Secondary/muted text |
| `--ink-faint` | `oklch(15% 0.012 50 / 0.18)` | Very light hairlines |
| `--green-deep` | `oklch(40% 0.09 145)` | Link hover (static, not team-driven) |
| `--sky-deep` | `oklch(62% 0.09 230)` | Decorative icon accents (static, not team-driven) |
| `--brown` | `oklch(40% 0.06 50)` | "Hint of brown" accent — Yahoo pending-state, sell-high icon, one status dot |
| `--cream` | `oklch(98% 0.01 85)` | Near-white, for text/icons on dark fills where contrast is already known-safe |

### Dynamic accent tokens

| Token | Default (Team Colors **off**) | Represents |
|---|---|---|
| `--yellow` | `oklch(82% 0.15 95)` (mustard/gold) | **Primary** accent |
| `--green` | `oklch(52% 0.11 145)` | **Secondary** accent |
| `--sky` | `oklch(74% 0.08 230)` | **Tertiary** accent |

These three are consumed throughout the UI via `var(--yellow)`, `var(--green)`, `var(--sky)` — never hardcoded per-component — so that swapping the three values (see §6) re-themes the whole page.

**No drop shadows anywhere.** Depth/hierarchy comes from black borders and rules only:
- Card border: `2.5px solid var(--ink)`, with a heavier `6px` top edge in an accent color.
- Section dividers: `3px solid var(--ink)` full-bleed rules.
- Page frame: outer wrapper `background: var(--ink)` with `16px` padding around the paper-colored content, producing a black picture-frame border.

## 4. Layout

Single flowing page, ~1440px reference width, black-framed as above. Sections top to bottom:

1. **Top bar** — logo mark (circle, accent-primary fill, ink stroke) + wordmark "SOLARIS" / "DYNASTY DESK" tagline, left; nav labels (Dashboard / Leagues / Players / Signals) center, active item underlined `3px solid var(--yellow)`; Team Colors toggle + team picker + user chip, right.
2. **3px black rule.**
3. **Masthead** — small uppercase eyebrow line, then a large headline ("Overview").
4. **3px black rule.**
5. **Stat tiles** — 3 cards in a row, each: `2.5px` ink border, `6px` accent-colored top edge (cycles through primary/secondary/tertiary), big headline-font number, uppercase label, muted caption.
6. **League cards grid** — 4-column grid, cards as described in §5.
7. **Arbitrage Signals** — section title + status badge, intro line, then a bordered list of rows (icon chip + label + tag).
8. **3px black rule, then footer** — source line left, small accent-colored dot row + timestamp right.

### Narrow viewports (phones)

The layout above is the desktop design and is what renders at >720px. It was
originally the *only* layout -- there were no media queries at all, so a phone
got it verbatim and the games broke worst: the `/games` tab row and four game
tables overflowed the viewport, and Pick'em's two team buttons shared one
squeezed table cell, wrapping "Kansas City Chiefs (KC)" over four lines.

At **≤720px** a mobile layer (bottom of `style.css`) rearranges the same
components without changing the design language -- still flat fills, square
corners, `2.5px` ink borders, no shadows. What changes:

- **Page frame** thins to `5px` and `main`'s gutters to `14px`; at the desktop
  values the frame plus gutters cost 88px of a 390px screen before any content.
- **Top bar** goes to three explicit rows: brand + user chip + Log out, then
  the Team Colors picker, then nav as a single horizontal scroll strip
  (eight links can't fit on one line at this width). Without the explicit
  `order`, the picker and Log out each took a row of their own and pushed nav
  to a fourth.
- **Games tab row** fits all five tabs down to 320px on reduced padding, and
  scrolls below that. The Settings tab's `margin-left: auto` comes from
  `.tab-settings`, not an inline style, so this layer can neutralise it.
- **Controls** are all ≥16px and ≥44px tall. 16px is not cosmetic: iOS Safari
  zooms the page in when you focus a smaller field and leaves it zoomed. Four
  selectors (`.team-colors-form select`, `.filter-bar select`,
  `.confidence-select`, `.stack-form input/select`) carry their own font-size
  and have to be named explicitly to be overridden.
- **Team Colors toggle** keeps its spec proportions scaled to 52×28 (18px
  knob, 22px travel) so it's actually hittable.
- **Tables** use one of two utilities, and any new table should pick one:
  - `.table-scroll` (a wrapper div) — the table keeps its columns and scrolls
    inside its own box; the ink border moves to the wrapper. For read-only,
    many-column data tables (Teams' nine columns, Arbitrage, Predictions).
  - `.table-stack` (on the table) — each row becomes a card and each cell a
    "label: value" line read from the cell's `data-label`. For tables with
    inputs or a cell you must tap, where sideways scrolling would hide the
    control: Fantasy Draft, Pick'em picks, group draft board, 501, trivia.
    A cell carrying its own heading or a whole stacked block opts out with
    `.cell-block`.
- **Pick'em matchups** stack the two team buttons full-width (`.pickem-vs`
  becomes a column), which both fixes the four-line team names and turns the
  primary action into a comfortable 48px target.
- **Row hover** is suppressed under `@media (hover: none)` — on a touch screen
  it sticks to whatever you last tapped.

## 5. Components

**Badge / status tag** (e.g. "Sleeper", "ESPN", "Preseason Beta", league-name tags in the signals list): solid accent-color fill, bold uppercase 10–12px text, no border unless it's a hairline `1.5px solid var(--ink)`. Text color is **not** hardcoded — see contrast rule in §6.

**League card**: `var(--paper)` background, `2.5px solid var(--ink)` border, `6px` accent-colored top border (accent depends on platform — see §6), 16px padding, contains: platform badge + small decorative icon (top row), league name + format/season line (middle), status dot + label + roster/record info (bottom row).

**Status dot**: 8px circle, `1.5px solid var(--ink)` border, fill indicates state (pre-draft = primary/yellow, in season = secondary/green, complete = brown, pending = unfilled/outline only).

**Signal row**: 36–40px circular icon chip (solid accent fill, `2px solid var(--ink)` border, contrast-safe icon color), label + description, right-aligned tag badge (accent-colored, contrast-safe text).

**Toggle switch** (Team Colors): 38×20px pill, `2px solid var(--ink)`, track fill `var(--paper)` when off / `var(--ink)` when on, 12px knob that slides via `transform: translateX()`, knob color `var(--ink)` when off / `var(--yellow)` (current primary accent) when on.

## 6. Team Colors feature — full spec

A toggle in the top bar, paired with a team picker (native `<select>` is fine), that re-themes the three dynamic accent tokens to a chosen NFL team's brand colors.

### State

```
teamColorsOn: boolean (default false)
teamId: string (default '', i.e. no team selected)
```

### Color resolution (runs on every render)

```js
const selectedTeam = TEAMS.find(t => t.id === teamId) ?? null;
const useTeam = teamColorsOn && selectedTeam;

const accentPrimary   = useTeam ? selectedTeam.primary   : DEFAULT_YELLOW; // oklch(82% 0.15 95)
const accentSecondary = useTeam ? selectedTeam.secondary : DEFAULT_GREEN;  // oklch(52% 0.11 145)
const accentTertiary  = useTeam
  ? (selectedTeam.tertiary || fallbackTertiary(selectedTeam.primary, selectedTeam.secondary))
  : DEFAULT_SKY; // oklch(74% 0.08 230)
```

These three values get written onto the root element as CSS custom properties (`--yellow`, `--green`, `--sky`), so every existing `var(--yellow|green|sky)` reference in the stylesheet picks them up automatically — no per-component logic needed elsewhere.

Toggling off reverts to the defaults immediately, even if a team is still selected in the picker (nothing destructive — flipping back on re-applies the same team).

### Fallback rule for missing tertiary colors

Several teams only have two official brand colors. When `tertiary` is `null`, compute a fallback of pure white or pure black, picking whichever contrasts better against that team's primary/secondary:

```js
function hexLuminance(hex) {
  const c = hex.replace('#', '');
  const r = parseInt(c.substring(0, 2), 16) / 255;
  const g = parseInt(c.substring(2, 4), 16) / 255;
  const b = parseInt(c.substring(4, 6), 16) / 255;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b; // relative luminance
}

function fallbackTertiary(primary, secondary) {
  const hasLightColor = hexLuminance(primary) > 0.7 || hexLuminance(secondary) > 0.7;
  return hasLightColor ? '#000000' : '#FFFFFF';
}
```

(If both primary and secondary are already dark, fall back to white; if either is already light/near-white, fall back to black to avoid a near-duplicate.)

### Text/icon contrast rule (important — easy to miss)

Several UI elements render text or an icon glyph **on top of** one of the three dynamic accent colors (platform badges, the "Preseason Beta" tag, signal-row league tags, the buy-low check icon). Those were originally hardcoded to black text, which becomes unreadable once an accent turns dark (e.g. a team's near-black primary). Compute per-slot contrast colors and bind them wherever text/an icon sits on an accent background — never hardcode black there:

```js
function textFor(colorHex) {
  // only meaningful for hex team colors; oklch defaults always get black
  if (typeof colorHex === 'string' && colorHex.startsWith('#')) {
    return hexLuminance(colorHex) > 0.55 ? '#000000' : '#FFFFFF';
  }
  return '#000000';
}

const textOnPrimary   = textFor(accentPrimary);
const textOnSecondary = textFor(accentSecondary);
const textOnTertiary  = textFor(accentTertiary);
```

Apply:
- `textOnPrimary` → "Sleeper" badge text, "Preseason Beta" badge text, signal-row league-tag text.
- `textOnTertiary` → "ESPN" badge text.
- `textOnSecondary` → the buy-low signal icon's check-mark stroke (icon sits on a `var(--green)`-filled circle).

Everything else (card borders, status dots, footer dots, decorative card-corner icons) has no text/icon overlapping it, so it can stay as a plain color swap with no contrast logic.

### Which elements map to which slot

| Slot | Default color | Elements driven by it |
|---|---|---|
| **Primary** (`--yellow`) | mustard/gold | Logo mark fill, active-nav underline, Sleeper platform badge + all Sleeper card top-borders, "Pre-Draft" status dot, stat tile 1 top-border + number, "Preseason Beta" badge, signal-row league tags, user-avatar chip fill |
| **Secondary** (`--green`) | mid green | Stat tile 2 top-border + number, "In Season" status dot, some card decorative icons, buy-low signal icon fill |
| **Tertiary** (`--sky`) | sky blue | ESPN platform badge + ESPN card top-borders, stat tile 3 top-border + number, footer dot |

### Team data (all 32 NFL teams)

`primary` / `secondary` are the team's two main brand colors; `tertiary` is `null` where a team has no widely-used third color (triggers the fallback rule above).

```js
const TEAMS = [
  { id: 'ari', name: 'Arizona Cardinals',       primary: '#97233F', secondary: '#000000', tertiary: '#FFB612' },
  { id: 'atl', name: 'Atlanta Falcons',         primary: '#A71930', secondary: '#000000', tertiary: '#A5ACAF' },
  { id: 'bal', name: 'Baltimore Ravens',        primary: '#241773', secondary: '#000000', tertiary: '#9E7C0C' },
  { id: 'buf', name: 'Buffalo Bills',           primary: '#00338D', secondary: '#C60C30', tertiary: null },
  { id: 'car', name: 'Carolina Panthers',       primary: '#0085CA', secondary: '#101820', tertiary: '#BFC0BF' },
  { id: 'chi', name: 'Chicago Bears',           primary: '#0B162A', secondary: '#C83803', tertiary: null },
  { id: 'cin', name: 'Cincinnati Bengals',      primary: '#FB4F14', secondary: '#000000', tertiary: null },
  { id: 'cle', name: 'Cleveland Browns',        primary: '#311D00', secondary: '#FF3C00', tertiary: null },
  { id: 'dal', name: 'Dallas Cowboys',          primary: '#041E42', secondary: '#869397', tertiary: null },
  { id: 'den', name: 'Denver Broncos',          primary: '#FB4F14', secondary: '#002244', tertiary: null },
  { id: 'det', name: 'Detroit Lions',           primary: '#0076B6', secondary: '#B0B7BC', tertiary: '#000000' },
  { id: 'gb',  name: 'Green Bay Packers',       primary: '#203731', secondary: '#FFB612', tertiary: null },
  { id: 'hou', name: 'Houston Texans',          primary: '#03202F', secondary: '#A71930', tertiary: null },
  { id: 'ind', name: 'Indianapolis Colts',      primary: '#002C5F', secondary: '#FFFFFF', tertiary: null },
  { id: 'jax', name: 'Jacksonville Jaguars',    primary: '#006778', secondary: '#000000', tertiary: '#D7A22A' },
  { id: 'kc',  name: 'Kansas City Chiefs',      primary: '#E31837', secondary: '#FFB81C', tertiary: null },
  { id: 'lv',  name: 'Las Vegas Raiders',       primary: '#000000', secondary: '#A5ACAF', tertiary: null },
  { id: 'lac', name: 'Los Angeles Chargers',    primary: '#0080C6', secondary: '#FFC20E', tertiary: '#002244' },
  { id: 'lar', name: 'Los Angeles Rams',        primary: '#003594', secondary: '#FFA300', tertiary: null },
  { id: 'mia', name: 'Miami Dolphins',          primary: '#008E97', secondary: '#FC4C02', tertiary: '#005778' },
  { id: 'min', name: 'Minnesota Vikings',       primary: '#4F2683', secondary: '#FFC62F', tertiary: null },
  { id: 'ne',  name: 'New England Patriots',    primary: '#002244', secondary: '#C60C30', tertiary: '#B0B7BC' },
  { id: 'no',  name: 'New Orleans Saints',      primary: '#D3BC8D', secondary: '#101820', tertiary: null },
  { id: 'nyg', name: 'New York Giants',         primary: '#0B2265', secondary: '#A71930', tertiary: '#A5ACAF' },
  { id: 'nyj', name: 'New York Jets',           primary: '#125740', secondary: '#000000', tertiary: null },
  { id: 'phi', name: 'Philadelphia Eagles',     primary: '#004C54', secondary: '#A5ACAF', tertiary: '#000000' },
  { id: 'pit', name: 'Pittsburgh Steelers',     primary: '#101820', secondary: '#FFB612', tertiary: '#C60C30' },
  { id: 'sf',  name: 'San Francisco 49ers',     primary: '#AA0000', secondary: '#B3995D', tertiary: null },
  { id: 'sea', name: 'Seattle Seahawks',        primary: '#69BE28', secondary: '#002244', tertiary: '#A5ACAF' },
  { id: 'tb',  name: 'Tampa Bay Buccaneers',    primary: '#D50A0A', secondary: '#34302B', tertiary: '#FF7900' },
  { id: 'ten', name: 'Tennessee Titans',        primary: '#0C2340', secondary: '#4B92DB', tertiary: '#C8102E' },
  { id: 'was', name: 'Washington Commanders',   primary: '#5A1414', secondary: '#FFB612', tertiary: null },
];
```

> These hex values are drawn from common public team-color references, not pulled programmatically from an official source this session — spot-check against your own source of truth if pixel-perfect brand accuracy matters.

## 7. Content notes (real data used in the mockup, not placeholders)

The Dashboard screen shows Ian's actual leagues, pulled from prior project research:

- 5 Sleeper leagues: Alumni Committee (1QB, pre-draft, roster #9), Quarantine Dynasty (Superflex, in season, roster #5), an unnamed Sleeper league (Superflex, in season, roster #6), Wisco Dynasty (1QB, in season, roster #3), D‑1 (Superflex, 2025, complete, roster #2).
- 2 ESPN leagues: "The Deep's Dolphins" (8-team, 2025 record 8‑5, 3rd of 8) and "'72 Dolphins" (8-team, 2025 record 3‑10, last of 8).
- A "Yahoo — awaiting API access" ghost card, since that integration is still pending approval.
- Stat tiles: "7 leagues tracked", "6,568 players indexed" (dynastyprocess crosswalk size).
- The Arbitrage Signals list uses generic placeholder entries ("Rookie WR", "Depth-chart veteran", etc.) rather than real player names, labeled "Preseason Beta" — the real buy-low/sell-high model isn't wired up to live data yet.

## 8. Not yet designed

Only the Dashboard/Overview screen exists so far. Still to design, in the same system: league + roster detail view, player detail view, and a dedicated trade-signals/arbitrage board.

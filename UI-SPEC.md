# UI-SPEC — Basketball Live-Stats Broadcast Overlay
**Status:** draft  
**Phase:** 1 — Full redesign of overlay.html  
**Date:** 2026-05-24  
**Produced by:** gsd-ui-researcher

---

## 0. Context Summary

| Property | Value |
|---|---|
| Canvas | 1920 × 1080 px, transparent background |
| Panel position | `left: 1469px`, `bottom: 4px`, `width: 449px` |
| Stack | Plain HTML / CSS / JS — no framework |
| Server | localhost:8081 |
| Data source | `/json/result.json` polled every 10 s |
| Data structure | `result.json` → `{status, quarter, time, home{}, away{}}` |
| Locale | Russian stat labels; English team names/abbreviations |

---

## 1. Design System

**Tool:** none (no shadcn — plain HTML/CSS)  
**Approach:** CSS custom properties as the single source of truth.  
All tokens defined in `:root {}` at the top of `overlay.html`.

---

## 2. Color Tokens

```css
:root {
  /* ── Surfaces ─────────────────────────────────────────── */
  --c-bg-panel:       #0C0501;   /* outermost panel body              */
  --c-bg-scoreboard:  #190A02;   /* scoreboard section                */
  --c-bg-quarters:    #110701;   /* quarter breakdown rows            */
  --c-bg-stat-odd:    #0E0601;   /* stat rows 1, 3, 5, 7 (darker)    */
  --c-bg-stat-even:   #160B02;   /* stat rows 2, 4, 6 (slightly warm) */

  /* ── Brand / Accent ───────────────────────────────────── */
  --c-orange:         #FF6B00;   /* primary accent — orange           */
  --c-orange-bright:  #FF8C2A;   /* highlight, gradient peak          */
  --c-orange-dim:     rgba(255, 107, 0, 0.14);  /* tinted fills       */
  --c-orange-border:  rgba(255, 107, 0, 0.38);  /* divider lines      */
  --c-orange-glow:    rgba(255, 107, 0, 0.22);  /* panel glow spread  */

  /* ── LIVE indicator ───────────────────────────────────── */
  --c-live:           #FF3232;   /* broadcast-standard red            */
  --c-live-ring:      rgba(255, 50, 50, 0.45);  /* pulse ring         */

  /* ── Text ─────────────────────────────────────────────── */
  --c-text-primary:   #FFFFFF;
  --c-text-secondary: #C4C4C4;   /* away team values, secondary info  */
  --c-text-muted:     #888888;   /* dim placeholders (—)              */
  --c-text-label:     #6E6E6E;   /* Russian stat labels               */
  --c-text-abbr-home: #FF6B00;   /* home team abbreviation            */
  --c-text-abbr-away: #D4D4D4;   /* away team abbreviation            */
  --c-text-name:      #7A7A7A;   /* small full team name below abbr   */
  --c-text-qheader:   #FF6B00;   /* Q1/Q2/Q3/Q4/OT column headers    */

  /* ── Borders / Dividers ───────────────────────────────── */
  --c-border-subtle:  rgba(255, 255, 255, 0.06);
  --c-border-section: rgba(255, 107, 0, 0.38);   /* between sections  */
}
```

### 60 / 30 / 10 Split
| Role | Color | Usage |
|---|---|---|
| 60% Dominant surface | `#0C0501` – `#190A02` | Panel body, all rows |
| 30% Secondary surface | `#160B02` – `#110701` | Alternate rows, quarter bg |
| 10% Accent | `#FF6B00` | LIVE dot, abbr, borders, gradient line, labels |

**Accent is reserved for:** top gradient line, section dividers, home-team abbreviation, `Q1–OT` column headers, LIVE label text, stat label separators on hover.  
Accent is **not used** for general text or backgrounds — only structural highlights.

---

## 3. Typography

### Fonts (Google Fonts)
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600&display=swap" rel="stylesheet">
```

| Token | Font | Size | Weight | Line-height | Letter-spacing | Usage |
|---|---|---|---|---|---|---|
| `--t-score` | Bebas Neue | 52px | 400 | 1.0 | 0.02em | Main scoreboard digits |
| `--t-abbr` | Bebas Neue | 40px | 400 | 1.0 | 0.04em | Team abbreviation (3-letter) |
| `--t-status-quarter` | Bebas Neue | 15px | 400 | 1.0 | 0.12em | Quarter label in status bar (Q3, OT) |
| `--t-status-clock` | Bebas Neue | 15px | 400 | 1.0 | 0.06em | Game clock in status bar (5:42) |
| `--t-q-header` | Bebas Neue | 12px | 400 | 1.0 | 0.10em | Q1/Q2/Q3/Q4/OT column headers |
| `--t-q-value` | Bebas Neue | 14px | 400 | 1.0 | 0.04em | Quarter score values |
| `--t-q-tag` | Bebas Neue | 13px | 400 | 1.0 | 0.08em | Team abbr in quarter rows |
| `--t-stat-value` | Bebas Neue | 16px | 400 | 1.0 | 0.02em | Stat values (29/62, 32, etc.) |
| `--t-team-name` | Inter | 9px | 400 | 1.2 | 0.06em | Full team name below abbr |
| `--t-stat-label` | Inter | 9px | 600 | 1.3 | 0.08em | Russian stat labels (uppercase) |
| `--t-live-label` | Inter | 9px | 600 | 1.0 | 0.20em | "LIVE" text next to dot |
| `--t-status-league` | Inter | 9px | 600 | 1.0 | 0.20em | "НБА" league label (status bar) |

**Rule:** Bebas Neue is used for ALL numeric/abbreviation content. Inter is used for ALL body/label/name text.  
**Max weights:** Inter 400 (regular) + Inter 600 (semibold). No other weights.

---

## 4. Spacing Scale

8-point grid. No off-grid values.

| Token | px | Usage |
|---|---|---|
| `--sp-1` | 4px | Icon padding, micro gaps |
| `--sp-2` | 8px | Standard intra-component padding |
| `--sp-3` | 12px | Quarter row vertical padding |
| `--sp-4` | 16px | Scoreboard horizontal padding |
| `--sp-5` | 24px | (reserved, not used in this phase) |

---

## 5. Layout Specifications

### 5.1 Panel Shell
```
width:            449px
background:       var(--c-bg-panel)
border-radius:    3px          ← only concession to rounded corners
overflow:         hidden
box-shadow:       0 0 40px var(--c-orange-glow),
                  0 8px 32px rgba(0,0,0,0.90),
                  inset 0 0 0 1px rgba(255,107,0,0.18)
```
No explicit `border` on the panel — the glow + inner inset shadow provides the orange edge. This avoids the flat "outlined box" look.

### 5.2 Top Accent Line
```
height:           3px
background:       linear-gradient(
                    90deg,
                    transparent    0%,
                    #FF6B00       18%,
                    #FF8C2A       50%,
                    #FF6B00       82%,
                    transparent  100%
                  )
display:          block (full width, no padding)
```
This is the first child inside `.panel`. Creates a premium broadcast "stripe" effect.

### 5.3 Status Bar

```
height:           30px
display:          flex
align-items:      center
justify-content:  space-between
padding:          0 12px
background:       rgba(0,0,0,0.50)   ← semi-transparent, not solid orange
border-bottom:    1px solid var(--c-border-section)
```

**Internal layout (left → right):**
```
[● LIVE]  [Q3 · 5:42]  [НБА]
```
| Slot | Content | Style |
|---|---|---|
| Left | Live indicator (dot + "LIVE" text) | Red dot + Inter 9px/600 orange text |
| Center | `{quarter} · {time}` or "ФИНАЛЬНЫЙ СЧЁТ" | Bebas Neue 15px white, letter-spacing 0.12em |
| Right | League label "НБА" | Inter 9px/600, color `--c-text-label`, letter-spacing 0.20em |

When `status === "over"`: center shows "ФИНАЛЬНЫЙ СЧЁТ" in Bebas Neue 13px `--c-orange`, dot hidden.  
When `quarter` is empty and status is not "live": show "НБА" only, centered.

### 5.4 Scoreboard

```
height:           76px
display:          grid
grid-template-columns: 1fr 130px 1fr
background:       var(--c-bg-scoreboard)
border-bottom:    2px solid var(--c-border-section)
align-items:      center
padding:          0 12px
```

**Home / Away team block (each `1fr` column):**
```
display:          flex
flex-direction:   column
align-items:      center   ← both blocks centered
gap:              2px
```

| Element | Spec |
|---|---|
| Abbreviation | Bebas Neue 40px, `--c-text-abbr-home` (home) / `--c-text-abbr-away` (away) |
| Full name | Inter 9px/400, `--c-text-name`, `text-transform: uppercase`, `letter-spacing: 0.06em`, max 1 line, `overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 130px` |

**Score block (center 130px column):**
```
display:          flex
align-items:      center
justify-content:  center
gap:              0
```
| Element | Spec |
|---|---|
| Home score | Bebas Neue 52px, `--c-text-primary` |
| Separator `:` | Bebas Neue 36px, color `rgba(255,255,255,0.25)`, margin `0 4px`, line-height 1 |
| Away score | Bebas Neue 52px, `--c-text-secondary` |

### 5.5 Quarter Breakdown Table

Three sub-rows stacked:

**Header row (col labels):**
```
height:           22px
display:          grid
grid-template-columns: 70px repeat(5, 1fr)
background:       rgba(0,0,0,0.30)
border-bottom:    1px solid var(--c-border-subtle)
align-items:      center
```
| Col | Content | Style |
|---|---|---|
| Col 0 (70px) | empty | — |
| Cols 1–4 | Q1 Q2 Q3 Q4 | Bebas Neue 12px, `--c-text-qheader`, letter-spacing 0.10em, centered |
| Col 5 | OT | Bebas Neue 12px, `--c-text-qheader`, opacity 0.30 when no OT data |

**Home data row + Away data row:**
```
height:           26px each
display:          grid
grid-template-columns: 70px repeat(5, 1fr)
background:       var(--c-bg-quarters)
border-bottom:    1px solid var(--c-border-subtle)
align-items:      center
```
| Col | Content | Style |
|---|---|---|
| Col 0 (70px) | Team abbr | Bebas Neue 13px, home=`--c-orange`, away=`--c-text-secondary`, text-align right, padding-right 8px, right border `var(--c-border-subtle)` |
| Cols 1–4 | Quarter scores | Bebas Neue 14px, home=`--c-text-primary`, away=`--c-text-secondary`, centered |
| Col 5 | OT score | Same as Q, opacity 0.25 when empty |

Away row has `border-bottom: 2px solid var(--c-border-section)` (stronger close of section).

**Current quarter highlight:** The active quarter column header and both data cells receive:
```css
background: var(--c-orange-dim);  /* subtle warm fill on active quarter column */
color: var(--c-orange);           /* header text brightened */
```
Applied via JS class `.q-active` on the relevant cells.

### 5.6 Stats Table

7 rows × 3 columns.

**Row:**
```
height:           30px
display:          grid
grid-template-columns: 1fr 118px 1fr
padding:          0 10px
align-items:      center
border-bottom:    1px solid var(--c-border-subtle)
```

Alternating backgrounds:
```
odd rows  → background: var(--c-bg-stat-odd)   (#0E0601)
even rows → background: var(--c-bg-stat-even)  (#160B02)
```
Last row: `border-bottom: none`.

| Col | Content | Style |
|---|---|---|
| Left (1fr) | Home stat value | Bebas Neue 16px, `--c-text-primary`, text-align center |
| Center (118px) | Russian label | Inter 9px/600, `--c-text-label`, `text-transform: uppercase`, `letter-spacing: 0.08em`, text-align center, `line-height: 1.3` |
| Right (1fr) | Away stat value | Bebas Neue 16px, `--c-text-secondary`, text-align center |

**Stat rows in order:**
| # | Label | ID suffix |
|---|---|---|
| 1 | БРОСКИ С ИГРЫ | fg |
| 2 | ТРЁХОЧКОВЫЕ | 3p |
| 3 | ШТРАФНЫЕ БРОСКИ | ft |
| 4 | ПОДБОРЫ | reb |
| 5 | ПЕРЕДАЧИ | ast |
| 6 | ПОТЕРИ | tov |
| 7 | ФОЛЫ | pf |

Multi-word labels that wrap (БРОСКИ С ИГРЫ, ШТРАФНЫЕ БРОСКИ): use `<br>` to break at natural word boundary. Row height remains 30px with `line-height: 1.3` — two lines of 9px = 22px total, fits inside 30px row.

---

## 6. Visual Design Details

### 6.1 Panel Border Strategy
No hard `border` property on `.panel`. Instead:
- `box-shadow: inset 0 0 0 1px rgba(255,107,0,0.18)` → subtle inner orange edge
- `box-shadow: 0 0 40px rgba(255,107,0,0.22)` → outer orange glow halo
- `box-shadow: 0 8px 32px rgba(0,0,0,0.90)` → deep drop shadow for depth

### 6.2 Section Dividers
- Between status bar and scoreboard: `border-bottom: 1px solid var(--c-border-section)` on status bar
- Between scoreboard and quarters: `border-bottom: 2px solid var(--c-border-section)` on scoreboard
- Between quarters and stats: `border-bottom: 2px solid var(--c-border-section)` on away quarter row
- Between stat rows: `1px solid var(--c-border-subtle)` — deliberately faint, not calling attention

### 6.3 Stat Row Micro-Separator
Centered label column: add left and right 1px borders using:
```css
.stat-label {
  border-left:  1px solid rgba(255,255,255,0.06);
  border-right: 1px solid rgba(255,255,255,0.06);
}
```
Creates a subtle 3-column separator without harsh lines.

### 6.4 Score Hierarchy
Home score is always full white (`#FFFFFF`). Away score is `#C4C4C4`. This creates instant visual hierarchy without requiring color-coding — leading team remains ambiguous until viewer reads both numbers.

### 6.5 Dim Placeholder (empty data cells)
When a value is empty / not yet played:
```html
<span class="dim">—</span>
```
```css
.dim { color: var(--c-text-muted); opacity: 0.28; }
```

---

## 7. Animation Specifications

### 7.1 LIVE Dot Pulse
```css
.live-dot {
  width:         8px;
  height:        8px;
  border-radius: 50%;
  background:    var(--c-live);       /* #FF3232 */
  position:      relative;
  flex-shrink:   0;
}

.live-dot::after {
  content:       '';
  position:      absolute;
  inset:         -4px;
  border-radius: 50%;
  background:    var(--c-live-ring);  /* rgba(255,50,50,0.45) */
  animation:     live-pulse 1.6s ease-out infinite;
}

@keyframes live-pulse {
  0%   { transform: scale(0.8); opacity: 0.9; }
  70%  { transform: scale(2.0); opacity: 0;   }
  100% { transform: scale(2.0); opacity: 0;   }
}
```
**Behavior:** Pulse hidden when `status === "over"`. The `.live-dot` element is `display: none` in final state.

### 7.2 Data Update Flash
When stat values are updated via JS fetch, apply a brief highlight:
```css
.flash {
  animation: value-flash 0.5s ease-out forwards;
}

@keyframes value-flash {
  0%   { color: var(--c-orange); }
  100% { color: inherit;         }
}
```
Apply `.flash` class in JS `setV()` when the value actually changes (compare to previous). Remove after 600ms.

---

## 8. Responsive / Text Truncation Behaviour

The panel is fixed-width (449px) — no responsive breakpoints. Truncation rules apply to team names only.

| Element | Truncation rule |
|---|---|
| Team full name (scoreboard) | `max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap` |
| Team abbreviation | Never truncates — always 3 chars max by data contract |
| Stat values | Never truncates — max length is "29/62" = 5 chars in Bebas Neue 16px ≈ 42px, well within 1fr column |
| Russian stat labels | Always 2-line max via `<br>` in markup; never overflow |
| Quarter scores | Never truncates — max 3 digits, fits in 1fr of 76px |
| Status bar center | `overflow: hidden; text-overflow: clip; white-space: nowrap` — "ФИНАЛЬНЫЙ СЧЁТ" in Bebas Neue 13px fits at 449px |

---

## 9. DOM Structure Reference

```
.panel
  .top-accent-line          ← 3px gradient stripe
  .status-bar               ← status bar (flex row)
    .live-indicator
      .live-dot
      span.live-text        ← "LIVE"
    .status-center           ← "Q3 · 5:42" or "ФИНАЛЬНЫЙ СЧЁТ"
    .status-league           ← "НБА"
  .scoreboard               ← grid 1fr/130px/1fr
    .team-block.home
      .team-abbr
      .team-name
    .score-block
      span#h-total
      span.sep
      span#a-total
    .team-block.away
      .team-abbr
      .team-name
  .quarters-section
    .q-header               ← header row (empty | Q1 | Q2 | Q3 | Q4 | OT)
    .q-row.home             ← home team quarter data
    .q-row.away             ← away team quarter data
  .stats-section
    .stat-row (×7)
      .stat-val.home
      .stat-label
      .stat-val.away
```

---

## 10. CSS Variable Summary (complete `:root`)

```css
:root {
  /* Panel position (unchanged from original) */
  --panel-left:   1469px;
  --panel-width:   449px;
  --panel-bottom:    4px;

  /* Surfaces */
  --c-bg-panel:       #0C0501;
  --c-bg-scoreboard:  #190A02;
  --c-bg-quarters:    #110701;
  --c-bg-stat-odd:    #0E0601;
  --c-bg-stat-even:   #160B02;

  /* Brand */
  --c-orange:         #FF6B00;
  --c-orange-bright:  #FF8C2A;
  --c-orange-dim:     rgba(255, 107, 0, 0.14);
  --c-orange-border:  rgba(255, 107, 0, 0.38);
  --c-orange-glow:    rgba(255, 107, 0, 0.22);

  /* LIVE */
  --c-live:           #FF3232;
  --c-live-ring:      rgba(255, 50, 50, 0.45);

  /* Text */
  --c-text-primary:   #FFFFFF;
  --c-text-secondary: #C4C4C4;
  --c-text-muted:     #888888;
  --c-text-label:     #6E6E6E;
  --c-text-abbr-home: #FF6B00;
  --c-text-abbr-away: #D4D4D4;
  --c-text-name:      #7A7A7A;
  --c-text-qheader:   #FF6B00;

  /* Borders */
  --c-border-subtle:  rgba(255, 255, 255, 0.06);
  --c-border-section: rgba(255, 107, 0, 0.38);

  /* Spacing */
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
}
```

---

## 11. Copywriting Contract

| Element | Text |
|---|---|
| League label | НБА |
| Live label | LIVE |
| Final state center text | ФИНАЛЬНЫЙ СЧЁТ |
| OT column header | OT |
| Empty value placeholder | — (en dash, U+2014) |
| Quarter column headers | Q1 · Q2 · Q3 · Q4 |
| Stat labels (row order) | БРОСКИ С ИГРЫ / ТРЁХОЧКОВЫЕ / ШТРАФНЫЕ БРОСКИ / ПОДБОРЫ / ПЕРЕДАЧИ / ПОТЕРИ / ФОЛЫ |

All label text is `text-transform: uppercase` in CSS — source markup should use original case (for readability in HTML), CSS handles rendering.

---

## 12. Implementation Notes for Executor

1. **Google Fonts must load before render.** Add `font-display: swap` fallback: `"Arial Narrow", Arial, sans-serif` for Bebas Neue; `system-ui, sans-serif` for Inter.
2. **No `border` on `.panel` itself** — box-shadow only (see §6.1). The original `border: 2px solid #FF6B00` must be removed.
3. **Bebas Neue renders at 1.0 line-height** — always set `line-height: 1` explicitly or numbers will clip on vertical overflow.
4. **Quarter active column highlighting** is a JS responsibility: after updating data, compare `d.quarter` to `"Q1"/"Q2"/"Q3"/"Q4"/"OT"` and add `.q-active` to the corresponding nth-child column cells.
5. **Flash animation** — track previous values in a `prevData` object; only apply `.flash` when `newVal !== prevVal`.
6. **OT column visibility** — header opacity 0.30 default, bumped to 1.0 when `h.ot || a.ot` is non-empty. Both data cells follow same rule.
7. **`setV()` enhancement** — the existing helper must be extended to accept a `flash` flag and manage the `.flash` CSS class lifecycle.
8. **Full team names** are now rendered below abbreviations. `h.name` / `a.name` from `result.json` populate `.team-name` elements. Truncation via CSS (§8), no JS needed.

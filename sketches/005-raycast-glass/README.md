## Variant: Raycast glass

Design stance: a sleek, dark, command-bar-first new tab that feels like a precision
desktop instrument — translucent glass surfaces over a deep dark gradient, vibrant
electric blue → purple → pink gradient accents, and the search field as the hero.

### Key choices

- **Layout** — same skeleton as the base: sticky glass top bar (wordmark left,
  oversized centered command-palette search, action buttons right), chip rows
  (folders incl. nested, special chips, tag chips with glowing dots, session chips),
  responsive card grid (~12 cards), floating glass selection bar.
- **Search as hero** — 48px-tall, ~640px-wide glass input with a 1px glowing
  gradient focus ring (blue → purple → pink), soft indigo glow on focus, and a
  keycap-styled ⌘K hint. It genuinely focuses and glows on click; ⌘K / Ctrl+K
  and `/` both focus it.
- **Glassmorphism** — every surface (top bar, search, chips, cards, selection bar,
  toast) is `rgba(255,255,255,0.05–0.08)` with `backdrop-filter: blur(20px)`
  and 1px `rgba(255,255,255,0.12)` glowing borders plus inset top highlights,
  over a deep dark backdrop with radial blue/purple/pink ambient glows.
- **Typography** — Inter with positive letter-spacing (+0.2px, a Raycast
  signature), weight 500 baseline; Geist Mono for URLs, counts and the ⌘K keycaps.
  The wordmark uses a subtle blue→violet→pink gradient clip.
- **Color** — bg `#0a0c12` deep dark gradient; accent gradient
  `linear-gradient(135deg, #3a7bfd, #8b5cf6, #ec4899)` on focus rings, active
  chip border + underline, keyboard-active card ring, the «Открыть» pill and
  selected checkboxes. Cool-toned per-card dark gradients (blue/teal/purple/
  violet) make the fake screenshots feel alive against the backdrop.
- **Interaction** — cards lift on hover with a colored (indigo) shadow; active
  chips get a gradient border + underline; selection is a soft gradient ring;
  the keyboard-active card carries a gradient ring + multi-layer glow; the
  selection bar is a glass pill with a gradient primary button. All base
  behavior preserved: search filtering, chip toggles, card click → checkbox +
  bar count («3 выбрано — Открыть / Сбросить»), Esc clears, hover ✕/checkbox.

### Trade-offs

- `backdrop-filter` is GPU-heavy on large grids; real usage would cap blur on
  low-end machines.
- Glass translucency reduces contrast on busy screenshots — mitigated here
  because thumbnails are dark and quiet, but real tab screenshots may fight it.
- The glow-heavy treatment is bold; it risks feeling "noir-flashy" versus a
  calmer tool. The gradient is reserved to interactive states to keep it in check.

### Best for

Users who want the new tab to feel like a fast launcher / command palette
(Raycast, Arc, Superwhisker lineage) rather than a quiet document — a power-user
tab manager where search and keyboard flow are the stars.

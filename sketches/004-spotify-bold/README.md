## Variant: Spotify bold

### Design stance

"Library of web pages, not a list of bookmarks." The whole page is treated like a
Spotify music library: a near-black immersive surface (`#121212`) on which the only
real color comes from two places — the functional Spotify Green (`#1ed760`) and the
"album covers" themselves. The card thumbnail is the star: a big, almost-square,
high-contrast block of pure-CSS artwork (dominant hue band + skeleton lines + a
faux-favicon sticker), and the metadata (name, URL, tag dots) sits under it, small
and quiet. The chrome UI recedes into shadow so the grid glows.

### Key choices

- **Layout:** Same skeleton as the base variant — sticky top bar (green uppercase
  wordmark left, centered pill search, action pills right), one wrapping chip row
  (folders incl. nested `↳ Проекты`, special chips, tag chips with colored dots,
  session chips), meta row, then a dense `auto-fill` grid of 12 cards. Cards use a
  square `aspect-ratio` thumb with 8px card padding so the art reads like an album
  cover; the grid packs densely in Spotify's "dark compression" style.
- **Typography:** DM Sans (CircularSp substitute). Compact 11–20px range, a
  bold/regular binary (700–800 vs 400–600). Wordmark is uppercase, heavy (800),
  tight tracking, in brand green. Buttons and section labels use the Spotify
  "system label" voice: uppercase + 1.4px letter-spacing. The count badge and
  "обновлено 21.10 · 14:32" are uppercase-tracked micro type.
- **Color:** Achromatic charcoal ramp (`#121212` / `#181818` / `#1f1f1f`) for all
  UI, white text with `#b3b3b3` muted. Green is strictly functional: active chip,
  selection ring, keyboard-focus ring + glow, primary CTA, the hover play button,
  and the wordmark. Each of the 12 cards carries a distinct dominant hue
  (235/255/35/330/210/10/352/52/150/185/285/305) rendered as a `hsl()` gradient
  with a rotated light band, translucent-white skeleton shapes, and a dark shade
  for depth — the grid reads as a wall of album art, not grey placeholders.
- **Interaction:** All base behaviors preserved — live search filter, folder
  single-select / tag / special / session chip toggles, card click toggles
  checkbox + updates the floating bar ("3 выбрано"), ✕ removes with fade, Esc
  clears selection (then search), `/` focuses search, selection mode pins
  checkboxes, compact grid toggle. Spotify-isms layered on: full-pill (500px+)
  buttons and chips, circular controls (green `＋`, play buttons), heavy shadows
  (`rgba(0,0,0,.5) 0 8px 24px`) instead of borders, inset-border "tactile" search
  pill, `translateY(-4px)` hover lift with a green play button sliding in from the
  thumbnail corner. States: one keyboard-active card (2px green ring + 34px green
  glow), one dimmed archived card (45% opacity, desaturated, "АРХИВ" pill badge),
  3 selected cards with a dark blurred floating pill bar — count, divider, green
  uppercase "▶ Открыть" primary, outlined "Сбросить".

### Trade-offs

- The square thumbs make cards ~40% taller than the 16:10 base variant, so the
  grid holds fewer rows per screen (2 rows of 6–7 at 1440×900 instead of 3).
  Acceptable for a bookmark manager (fewer, bigger, scannable), but heavy tab
  counts will need the compact toggle or a denser "list mode".
- Pure-CSS hue art is deterministic and fast but abstract — it hints at page type
  (docs/code/news/video…) via skeleton shapes rather than looking like the actual
  page, so it's a stronger aesthetic bet than a true screenshot.
- Uppercase green + glowing states are loud by design; for a "calm productivity"
  preference this variant overstates the accent. Green is kept functional (never
  painted on backgrounds) to avoid becoming noise.
- Emoji chip glyphs (🗄 ⭐ 🕘 📋) are inherited from the base content and slightly
  clash with Spotify's iconography — a production pass would swap them for a
  consistent icon set.

### Best for

Users who want the newtab to feel like a media app rather than a utility: the
"show off my tabs" use case — a visually alive home tab where saved pages look
like a personal collection, with selection/bulk-open as the primary workflow.
Great as the bold option in an A/B against the light/minimal variants; risky as a
default for users who open the tab dozens of times a day and want quiet.

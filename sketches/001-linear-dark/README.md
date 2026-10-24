## Variant: Linear dark

Dark-premium rework of Toby's newtab page, modeled on Linear's design language
(near-black canvas, ultra-thin borders, single indigo-violet accent, keyboard-first).
Single self-contained `index.html` — open directly in a browser (`file://`).

### Design stance
Toby is a power tool, not a marketing page. Every pixel should read as
"engineered": a calm near-black field, hairline `rgba(255,255,255,0.05–0.08)`
borders doing the structural work, and one reserved indigo accent (`#5e6ad2` →
`#7170ff`) that appears only on active/selected states. Depth comes from
luminance stepping (surface backgrounds at `rgba(255,255,255,0.02 → 0.05)`),
not drop shadows — the shadow is kept only for the floating selection bar.

### Key choices
- **Layout** — 6-column dense card grid (≈12 cards), sticky translucent top bar,
  single horizontal chip rail (folders → special → tag-dots → sessions, with
  hairline separators). Everything on an 8px rhythm.
- **Typography** — Inter with `font-feature-settings: "cv01","ss03"`; weight 510
  for UI emphasis, 590 for strong labels, negative letter-spacing on card titles.
  Real Russian copy throughout, no lorem.
- **Cards** — fake screenshots are pure CSS (colored browser-tab bar + grey
  text-line skeletons: prose, feed rows with avatars, hero blocks). No images.
  Hover reveals a `✕` and a checkbox; a keyboard-active card gets the indigo
  ring + soft glow; an archived card is dimmed + grayscale.
- **Color** — achromatic cool greys (`#0f1011` bg, `#191a1c` elevated, `#f7f8f8`
  / `#8a8f98` text), muted Linear-style tag dots (blue/green/orange/purple/
  red/yellow), indigo reserved for selection/CTA.
- **Interaction** — vanilla JS: search live-filters cards, chips toggle active,
  card click toggles the checkbox and updates the floating "N выбрано" bar
  (correct Russian pluralization), `Esc` clears search, `⌘K` focuses search,
  "Выбрать" forces checkboxes visible, "Размер" cycles grid density, theme
  button toggles its glyph.

### Trade-offs
- Pure-CSS fake thumbnails read as "wireframe" rather than true page captures;
  the real app would swap in captured screenshots — the CSS is only a stand-in.
- Tag/session filtering is visual-only (toggles state, doesn't actually filter
  the grid) — kept intentionally light for a mockup.
- Light theme is a stub (the toggle animates the glyph only).

### Best for
- Power users who live in the keyboard and want a dense, fast, distraction-free
  command surface for saved tabs.
- The "premium dark dev-tool" brand position: precise, quiet, a single accent.
- Good baseline if Toby wants to distance itself from a generic light-blue
  browser card grid and lean into the "serious tool" tier.

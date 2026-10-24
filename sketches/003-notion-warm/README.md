## Variant: Notion warm

**Stance.** The newtab as a quiet, paper-like shelf — editorial calm instead of a dashboard. Everything lives on warm off-white; chrome (borders, shadows) is reduced to whispers so the card grid itself becomes the focal point. Color appears only as small accents: pastel tag dots and a single soft blue for the keyboard-active ring and selection check.

**Key choices.**

- **Warm neutral system.** Background `#f7f5f2` (warm paper), white card surfaces, whisper borders `1px rgba(0,0,0,.08)`, warm near-black text `#37352f` with muted `#9b978f`. Shadows are multi-layer stacks with sub-0.05 opacity — depth that's felt, not seen.
- **Typography.** Serif display (Source Serif 4 → Georgia fallback) for the "Toby" wordmark only; Inter/system sans for all UI. The serif is a deliberate contrast moment, used once, at a large size — like a printed magazine masthead, not a logo lockup.
- **Curated shelf, not grid.** 7 columns, generous 20px gaps, cards with rounded-top "screenshot" thumbs rendered in pure CSS (warm header bar + grey-brown text lines). Titles are sans medium weight, URLs muted, tag dots small — the card reads as a bookmark you'd find in a well-kept book.
- **Restrained color.** Accent blue `#2383e2` appears only on: the keyboard-active ring, checked checkboxes, and the selection-bar primary button. Tag dots use a warm-friendly pastel set (soft red, blue, green, orange, purple).
- **Chips as soft pills.** Folders are a single-select row; special (Архив/Частые/Избранные), tags, and sessions are toggles. Active chip = warm dark fill, matching Notion's own active-state language.
- **Floating selection bar.** Elevated white pill with a 5-layer deep shadow, bottom center — the only "floating" element on the page.

**Trade-offs.**

- Warm minimalism can read as *inactive* in a power-tool context: less scannable at a glance than a dense dashboard, and the whisper borders make individual cards less tactile.
- One serif moment is subtle — if the wordmark doesn't land, the page looks like a plain Notion clone with cards.
- Pure-CSS fake screenshots are uniform by design (calm > variation); a real app with real favicons/thumbnails would break this look slightly — the layout must tolerate visual noise in the thumbs.
- Generous whitespace costs vertical room: on shorter screens the 12-card shelf needs scrolling.

**Best for.** Users who treat saved tabs as a personal archive/reference ("my second brain") rather than a rapid-launcher; fits the utilitarian Toby concept when the goal is a calm, trustworthy home page that recedes after a glance.

## Variant: Figma playful

### Design stance

The opposite pole of 002 (Vercel light): instead of a monochrome, engineering-precise dashboard, this variant reads like a **colorful corkboard / design-tool canvas**. Light, friendly, multi-color — but still professional: color is organized semantically (every folder family owns a hue), surfaces stay soft and quiet, and the geometry is rounded and bouncy rather than sharp and flat. The dotted background grid subtly echoes a Figma artboard, and dashed focus rings echo Figma's editor selection handles.

### Key choices

- **Layout** — identical skeleton to 002: sticky top bar (wordmark left, centered pill search, action buttons right), chip rows (folders incl. nested «↳ Проекты», specials, tag dots, session chips), ~12-card grid, floating selection bar, same card anatomy (fake-screenshot thumb + name + URL + tag dots + hover ✕/checkbox). Cards are slightly larger (180px min), 14px radius.
- **Typography** — Inter (500–800), heavier than the Vercel variant: 800 wordmark, 700 card names and count, 600 chips. Slight negative tracking for a chunky-friendly feel.
- **Color** — very light cool-grey dotted canvas (#f5f6f8), white surfaces, ink #333 / muted #888. Figma palette used semantically:
  - folder families: **Работа = blue #1e72ff**, **Дома = green #13c33e**, **Проекты = purple #a25dd9**;
  - specials: Архив = orange #f24e1e, Частые = amber #ff8800, Избранные = pink #e9228f;
  - tag dots reuse the same six hues; primary accent is Figma blue #1e72ff.
  Every fake screenshot is tinted by its folder's hue (hue header band + pastel body + skeleton lines), so the grid reads as a colorful shelf; hover lifts cast a soft *colored* shadow in the card's own hue.
- **Interaction** — bouncy: hovers use a springy cubic-bezier with scale 1.02 + lift; chips are pills carrying a tiny colored square of their family hue (active chip fills with the hue); checkboxes become colorful squares in the card's hue when checked; keyboard-active card gets a Figma-blue ring + soft lift + blue glow; the selection bar is a white pill with a blue «Открыть» pill button. Dashed 2px focus outlines (Figma's selection-handle signature) on all interactive elements.
- **Wordmark** — «BlatTabs» with a 4-quadrant rainbow mark (blue/green/amber/purple), the subtle two-tone treatment.

### States shown

- one keyboard-active card (GitHub — blue ring, lift, colored glow);
- one archived card (VK — dimmed, desaturated, «архив» badge);
- 3 checked cards + floating bar: «3 выбрано — Открыть / Сбросить».

### Trade-offs

- **Readability vs. color noise**: six hues in the chip row could feel busy; mitigated by keeping chip bodies white and using only small squares/dots for color, plus muted text.
- **color-mix() dependency**: pastel tints and colored shadows use `color-mix()` (Chromium ≥111); older browsers would lose the per-card tinting (cards fall back to white thumbs).
- **Pastel thumbs vs. real fidelity**: fake screenshots are abstract skeletons, so they look playful but less "real browser" than 002's grey mocks.
- Dark theme is a simple tint-flip of the same system (hue tints get deeper), not a separately tuned palette.

### Best for

Users who want their saved tabs to feel like a **personal creative workspace** rather than an ops dashboard — design teams, students, heavy multi-folder tab collectors who enjoy scanning by color at a glance. Strong when the extension is a daily "home" surface; would be too casual for a dense power-user workflow.

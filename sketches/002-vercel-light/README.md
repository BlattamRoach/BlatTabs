# 002 — Vercel light

## Variant: Vercel light

Monochrome precision newtab in the Vercel / Geist design language. Black-and-white
discipline: `#ffffff` canvas, `#171717` text, 1px `rgba(0,0,0,.08)` shadow-as-border
lines everywhere, sharp 6–8px radii, Geist Sans with tight negative tracking and
Geist Mono for URLs / technical labels. The only color left in the UI is the tag dots
(red / blue / green / orange / purple); one dark `Открыть` button is the single
high-contrast action.

### Stance

The app should feel like *infrastructure*, not decoration. Every element is a
functional control — wordmark, search, chips, cards — sized to a strict 4/8px scale
and separated by hairline borders and whitespace rather than color or shadow
elevation. Density is the point: a 6–7 column card grid at ~180px columns so a full
session of saved tabs reads in one glance. Selection, keyboard navigation and
filtering are first-class: the grid supports a visible keyboard-active ring, a
dimmed archived state, and a floating action bar that appears only when something
is selected.

### Key choices

- **Shadow-as-border.** `box-shadow: 0 0 0 1px rgba(0,0,0,.08)` instead of CSS
  `border` on cards, chips, buttons and the search field — the signature Vercel
  technique. Hover adds a whisper-level lift (`0 2px 10px rgba(0,0,0,.06)`), never
  heavy elevation.
- **One type family, two voices.** Geist Sans for UI (weights 400/500/600/700
  only, negative letter-spacing scaled down with size), Geist Mono for URLs and
  micro-labels. No 700 on body text.
- **Fake screenshots as pure CSS.** Each card thumbnail is a muted grey "page":
  browser bar + favicon dot (single muted hue per site), then a per-type skeleton
  (docs lines, code block, news image block, video play button, map roads, Figma
  frames, grid tiles, Notion bullets, social avatar). No external images, works
  from `file://`.
- **Monochrome discipline.** No accent color in the chrome. Active chip / selected
  card / primary button are `#171717` on white (inverted to white on black in dark
  mode). Tag dots are the sole hue — five muted, desaturated colors that still read
  as color.
- **Keyboard-active state.** One card carries a 1px black ring + 5px soft
  monochrome glow (not a colored focus ring), matching the request; it can move as
  the user interacts.
- **Real Russian content.** Realistic titles and URLs (docs.python.org,
  github.com/BlattamRoach/BlattamToby, habr.com, lenta.ru, yandex.ru/maps…),
  Russian chip labels («Все», «Работа», «Дома», «Проекты», «Архив», «Частые»,
  «Избранные», sessions), Russian selection bar («3 выбрано — Открыть / Сбросить»)
  with correct pluralization.
- **Interactive vanilla JS.** Search filters cards live; folder chips are single-
  select, tag / special / session chips toggle (multi, AND within a group); card
  click toggles its checkbox and updates the floating bar; `Esc` clears selection
  then search; `/` focuses search; «Выбрать» enters a select-all-hover mode;
  «Размер» toggles grid density; 🌙 flips to a full dark theme.
- **Floating selection bar** fixed bottom-center: count + dark `Открыть` + ghost
  `Сбросить`; slides in only when ≥1 selected.

### Trade-offs

- **Restraint over warmth.** Pure monochrome is precise but cold; the user asked to
  move away from the light-blue utilitarian look, which this fully achieves, but it
  trades away all the friendliness of the current app. Tag dots are the deliberate
  safety valve for visual interest.
- **CSS screenshots over real images.** Fast and dependency-free, but the
  thumbnails are abstract skeletons, not true page captures — less "at a glance
  which site is which" than a real screenshot would give.
- **Emoji glyphs for chip icons** (🗄 ⭐ 🕘 📋) keep the file self-contained with no
  icon font, at the cost of not being fully monochrome (they render in the OS
  emoji style).
- **Dense by default.** 6–7 columns favor data-heavy power users on a 1440px
  desktop; on small screens the grid wraps but the top bar becomes the constraint.

### Best for

Developers and power users who treat the newtab as a workbench: high tab volume,
keyboard-first navigation, filter-heavy workflows, and an aesthetic that should
stay out of the way and read as a tool rather than a page.

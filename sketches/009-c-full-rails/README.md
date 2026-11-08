# 009-c — Full-height rails, minimal chrome

Design prototype: the BlatTabs newtab re-laid-out as a **3-column workbench**,
taken to the **"ceiling-to-floor rails, minimal chrome"** stance.

The structural twist: the two side rails run the **full height of the page
(edge to edge, top to bottom)** and are filled with a soft `--rail-bg` tone —
there are **no divider lines** between the columns, the tone shift does all the
separating. There is **no full-width header** — the header (wordmark `BlatTabs` +
centered search) lives **inside the center column** at the top, without a
theme button. The theme toggle exists **only in the left rail**.

## Structure

```
┌───────────────────────────────  viewport (100vh, no page scroll)  ───────────────────────────────┐
│ LEFT 220px       │                CENTER  minmax(0,1fr)  ≈ 70–80%  width                 │ RIGHT 190px │
│ (full height,    │   ┌ in-column header:  BlatTabs · · · [Поиск во вкладках…] · · · /  ┐      │ (full height,│
│  --rail-bg fill) │   └───────────────────────────────────────────────────────────────────┘      │ --rail-bg)  │
│  МЕНЮ            │   [Работа][Личное][Учёба][Dev] [+ Пространство]                              │             │
│  🌙 Тема         │   Работа · 12 / 12                                                       │   ВКЛАДКИ    │
│  ↓ Экспорт       │   ┌────┐ ┌────┐ ┌────┐ ┌────┐ …      tab-card grid (hero) …               │   БРАУЗЕРА   │
│  ↑ Импорт        │   └────┘ └────┘ └────┘ └────┘                                                │  (vertical  │
│  ⚙ Настройки     │   ▾ Проекты · 4   [cards …]                                                 │   watermark) │
│                  │   ▾ Инструменты · 3  [cards …]                                              │   ▭   ▭      │
│                  │   ▾ Чтение · 3     [cards …]                                                │   ▭   ▭      │
│                  │   БЕЗ ГРУППЫ  [cards …]                                                    │  (faint ghost│
│                  │                                                                          │   pills —     │
│  ┌──────────┐    │                                                                          │   скоро)      │
│  │ 👤 Аккаунт│   │                                                                          │             │
│  │ скоро    │   │                                                                          │             │
│  └──────────┘    │                                                                          │             │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **(a) LEFT rail** — full height, 220 px, `--rail-bg` fill, **no divider
  lines**: a compact **hover-reveal control list** —
  `🌙 Тема`, `↓ Экспорт`, `↑ Импорт`, `⚙ Настройки` (no account row in the
  menu). A single reserved **account slot** is pinned to the very bottom
  (future sign-in + sync).
- **(b) CENTER** — ≈70–80 % width. In-column header (wordmark + search only —
  the theme button is gone from here), then the space-chip row, then the
  tab-card grid. The cards are visually faithful to `view.html` (same tokens,
  chip/gbar/card geometry, hover controls, selection look).
- **(c) RIGHT rail** — full height, 190 px, `--rail-bg` fill, a **placeholder
  for the duplicate of the browser's open tabs**: a faint vertical watermark
  `ВКЛАДКИ БРАУЗЕРА` plus a few ghosted pill outlines. Future: the top browser
  tab strip is duplicated here, and tabs can be dragged from it straight into
  the manager.

## Signature interaction — hover-reveal rails

Each left-rail row starts receded: faint icon, muted label, hidden caption.
On hover (or keyboard focus) it:

- fills with the hover surface,
- grows a short **ink accent bar** on the left edge,
- brightens the icon + label to full text color,
- **reveals a caption / affordance** (e.g. Экспорт → “Скачать JSON”) and a
  right `→` affordance.

Controls “recede until touched” — that is the whole point of the stance. The
state is driven by `:hover` **and** `:focus-within`/`:focus-visible`, so it is
reachable by keyboard and can be reproduced deterministically (the `.is-open`
class paints exactly the same pixels as `:hover`).

## What changed from the original C stance (2026-11-07)

1. **Rails swapped** — settings menu moved to the LEFT, the browser-tab
   duplicate placeholder moved to the RIGHT.
2. **Theme button removed from the center header** — the `Тема` row in the
   left rail is the only theme toggle.
3. **No divider lines** — both rails are filled with the soft `--rail-bg`
   tone (light `#f4f2f0`, dark `#292523`) instead of inset shadow hairlines.
4. **Account row removed from the menu list** — only the reserved account
   card at the very bottom of the left rail remains.

## Aesthetic

Airy, generous whitespace, minimal chrome: the columns are separated by tone
(`--rail-bg`) rather than lines, the center column has wide side padding, and
the tabs are the hero while every control stays quiet until touched.

## Theme

- Light: default (`:root` tokens).
- Dark: `data-theme="dark"` (warm-neutral, elevated contrast) — the exact
  palette from `theme.css`. Toggled by the `Тема` row in the left rail
  (moon/sun icon swaps to reflect the state).

## Run

Open `index.html` directly, or serve the folder:

```
python -m http.server 8793 --bind 127.0.0.1
```

then visit <http://127.0.0.1:8793/>.

## Screenshots

- `01-light.png` — light theme, default state.
- `02-dark.png` — dark theme.
- `03-rail-hover.png` — light theme, a left-rail control in its **hover /
  expanded** state (highlighted, ink bar, caption + `→` revealed).

## Notes

- Standalone single file; no external JS (native HTML/CSS/JS only).
- Colors are the `theme.css` design tokens only — no hardcoded hex outside the
  two token blocks. `--rail-bg` is the one new token (light / dark values in
  each block).
- All UI text is Russian. Sample data is representative only (prototype).

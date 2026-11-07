# 009-a — classic three-pane

Design-prototype variant for the BlattamToby newtab: a **classic three-pane workbench**.

- **Full-width sticky header** — wordmark «Toby» left, centered search box, minimal theme-toggle icon far right.
- **LEFT panel (68px)** — essentially empty: a hairline right divider and a faint stacked-tab glyph + vertical «Вкладки» watermark. Reserved for a future duplicate of the browser's top tab strip (drag tabs from it into the manager).
- **CENTER (~77% of viewport width, measured 1112/1440 px)** — the existing content: space-chip row (Работа / Личное / Учёба / Dev), meta row, and the tab-card grid with collapsible group bars, visually faithful to `view.html` (141px min cards, 8px radius, hover-revealed checkbox top-left + ✕ top-right, 2-line name clamp, letter-tile favicon fallback).
- **RIGHT panel (260px)** — a functional settings sidebar, full height, grouped top-to-bottom:
  - **Тема** — light/dark segmented toggle (works; header icon stays in sync).
  - **Данные** — «↓ Экспорт» / «↑ Импорт» buttons.
  - **Настройки** — three visually-inert placeholder rows with toggle states.
  - **Аккаунт** — avatar dot + «Войти» / «Скоро».

Hairline dividers (1px `var(--line2)`) separate the three columns. Both token blocks from `theme.css` are embedded verbatim; no hardcoded hex outside the tokens.

## Interactivity
- Light/dark toggle (header icon or rail segmented control) flips `data-theme="dark"` on `<html>`.
- Space chips switch the active space: active chip inverts, grid re-renders with a staggered fade-in (the signature transition), meta row updates.
- Group bars collapse/expand; cards reveal checkbox/✕ on hover; ✕ removes a card; card click opens the URL.
- Search box (or `/`) filters cards live; `Esc` clears.

## Screenshots (1440×900)
- `screenshots/01-light.png` — light theme, «Работа» space.
- `screenshots/02-dark.png` — dark theme, «Работа» space.
- `screenshots/03-space-switched.png` — «Dev» space active (subset of cards).

Serve: `python -m http.server 8791 --bind 127.0.0.1` from this folder → http://127.0.0.1:8791

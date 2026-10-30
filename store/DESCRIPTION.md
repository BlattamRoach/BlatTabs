# BlattamToby — описание для магазина

## Короткое описание (<= 132 символов)

Менеджер сохранённых вкладок: новая вкладка (Ctrl+T) — карточки, папки, поиск, клавиатура, тёмная тема.

## Полное описание (RU)

**BlattamToby** — менеджер сохранённых вкладок для Chrome. Расширение заменяет пустую страницу новой вкладки: **Ctrl+T** (или кнопка «+») открывает вашу собственную стартовую страницу — сетку карточек со всеми сохранёнными ссылками.

Сохраняйте вкладки одним кликом из popup или горячей клавишей **Ctrl+Shift+S** — и мгновенно возвращайтесь к ним на новой вкладке (Ctrl+T). Пространства и группы синхронизируются между устройствами через `chrome.storage.sync`.

Дизайн — минималистичный монохром в духе Vercel: чёрный/белый/серый, шрифт Geist, тонкие 1px-границы; тёмная тема одним кликом.

### Возможности

- **Сохранение вкладок** — popup «Сохранить вкладку» или Ctrl+Shift+S; дедупликация по URL.
- **Newtab-override** — страница новой вкладки становится вашим менеджером вкладок (Ctrl+T).
- **Папки и вложенные папки** — категории вкладок, папки внутри папок (1 уровень), перенос карточки дропдауном или перетаскиванием.
- **Поиск** — мгновенная фильтрация по имени, заголовку и URL.
- **Drag & drop** — перетаскивание карточек на чипы папок (нативный HTML5 DnD, без библиотек).
- **Reorder карточек** — перетаскивание карточки на другую карточку меняет порядок (верхняя/нижняя половина — перед/после).
- **Массовое открытие** — чекбоксы на карточках + панель «N выбрано / Открыть / Сбросить»; «☑ Выбрать» — все видимые.
- **Клавиатурная навигация** — стрелки по карточкам (с зацикливанием), Enter — открыть, Delete — удалить, Esc — сброс.
- **Тёмная тема** — переключатель 🌙/☀️ в шапке, выбор сохраняется.
- **Горячая клавиша** — Ctrl+Shift+S сохраняет текущую вкладку.
- **Хранилище** — список вкладок — в `chrome.storage.local` (per-device, до ~10 МБ — влезает большая коллекция); пространства и группы — в `chrome.storage.sync` (синхронизация между устройствами).
- **Экспорт / импорт JSON** — перенос коллекции с папками.

### Превью

- Превью 1 — главная страница в светлой теме: папки (включая вложенную), карточки вкладок.
- Превью 2 — та же страница в тёмной теме.
- Превью 3 — поиск активен: сетка отфильтрована по запросу.

## Full description (EN)

**BlattamToby** is a saved-tabs manager for Chrome. It replaces the empty new-tab page: **Ctrl+T** (or the «+» button) opens your own start page — a grid of cards with all your saved links.

Save tabs with one click from the popup or the **Ctrl+Shift+S** hotkey — and jump back to them instantly on the new-tab page (Ctrl+T). Spaces and groups are synchronized across devices via `chrome.storage.sync`.

The design is minimal monochrome, Vercel-style: black/white/grey, Geist font, crisp 1px borders; dark theme in one click.

### Features

- **Save tabs** — popup «Save tab» or Ctrl+Shift+S; deduplication by URL.
- **New-tab override** — the new-tab page becomes your tab manager (Ctrl+T).
- **Folders & nested folders** — categories, folders inside folders (1 level), move cards via the folder dropdown or drag & drop.
- **Search** — instant filter by name, title and URL.
- **Drag & drop** — drag cards onto folder chips (native HTML5 DnD, no libraries).
- **Bulk open** — checkboxes on cards + «N selected / Open / Clear» panel; «☑ Select» for all visible.
- **Keyboard navigation** — arrow keys across cards (wrapping), Enter to open, Delete to remove, Esc to reset.
- **Dark theme** — 🌙/☀️ toggle in the header, choice is persisted.
- **Hotkey** — Ctrl+Shift+S saves the current tab.
- **Storage** — the tab list lives in `chrome.storage.local` (per device, up to ~10 MB — large collections fit); spaces and groups live in `chrome.storage.sync` (across devices).
- **JSON export / import** — migrate your collection with folders.

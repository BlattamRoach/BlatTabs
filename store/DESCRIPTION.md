# BlatTabs — описание для магазина

## Короткое описание (<= 132 символов)

Менеджер сохранённых вкладок: новая вкладка (Ctrl+T) — карточки, папки, поиск, клавиатура, тёмная тема.

## Полное описание (RU)

**BlatTabs** — менеджер сохранённых вкладок для Chrome. Расширение заменяет пустую страницу новой вкладки: **Ctrl+T** (или кнопка «+») открывает вашу собственную стартовую страницу — сетку карточек со всеми сохранёнными ссылками.

Сохраняйте вкладки одним кликом из popup или горячей клавишей **Ctrl+Shift+S** — и мгновенно возвращайтесь к ним на новой вкладке (Ctrl+T). Пространства и группы синхронизируются между устройствами через `chrome.storage.sync`.

Дизайн — минималистичный монохром в духе Vercel: чёрный/белый/серый, шрифт Geist, тонкие 1px-границы; тёмная тема одним кликом.

### Возможности

- **Сохранение вкладок** — popup «Сохранить вкладку» или Ctrl+Shift+S; дедупликация по URL.
- **Newtab-override** — страница новой вкладки становится вашим менеджером вкладок (Ctrl+T).
- **Папки и вложенные папки** — категории вкладок, папки внутри папок (1 уровень), перенос карточки дропдауном или перетаскиванием.
- **Поиск** — мгновенная фильтрация по имени, заголовку и URL.
- **Drag & drop** — перетаскивание карточек на чипы папок (нативный HTML5 DnD, без библиотек).
- **Зеркало вкладок браузера** — правая рейка выводит открытые вкладки браузера в том же порядке, что и верхняя полоса (перетаскивание в рейке переставляет реальные вкладки; открытие и закрытие вкладок обновляет рейку сразу). Перетащите вкладку из рейки в сетку карточек — она сохранится карточкой, браузерная вкладка останется открытой.
- **Перестановка пространств** — перетащите чип пространства на другой чип: по ряду за курсором идёт тёплая слот-заглушка (единственный индикатор вставки, как при перетаскивании карточек); левая половина цели — вставить перед, правая — после; порядок чипов меняется, вкладки и активное пространство остаются на своих местах; дроп в любом месте ряда (зазор между чипами, отступы, кнопка «+ Пространство») — в позицию заглушки (как при перетаскивании карточек). Дроп карточки на чип пространства (перенос вкладки в пространство) — как раньше.
- **Открытие всех вкладок группы** — ⧉ на шапке группы (появляется при наведении): открывает все вкладки группы в новых вкладках браузера; работает и у свёрнутой группы.
- **Reorder карточек** — перетаскивание карточки на другую карточку меняет порядок (верхняя/нижняя половина — перед/после).
- **Массовое открытие и удаление** — чекбоксы на карточках + панель «N выбрано / Открыть / Сбросить / Удалить»; «✕ Удалить» — выбранные вкладки удаляются (с подтверждением).
- **Клавиатурная навигация** — стрелки по карточкам (с зацикливанием), Enter — открыть, Delete — удалить, Esc — сброс.
- **Тёмная тема** — переключатель 🌙/☀️ в шапке, выбор сохраняется.
- **Фон** — своя картинка-фон страницы: выбирается в настройках, видна в обеих темах, хранится на устройстве (до ~4 МБ).
- **Цвет вкладок** — свой цвет карточек сохранённых вкладок: пикер в настройках, работает в обеих темах, хранится на устройстве.
- **Горячая клавиша** — Ctrl+Shift+S сохраняет текущую вкладку.
- **Хранилище** — список вкладок — в `chrome.storage.local` (per-device, до ~10 МБ — влезает большая коллекция); пространства и группы — в `chrome.storage.sync` (синхронизация между устройствами).
- **Экспорт / импорт JSON** — перенос коллекции с папками.

### Превью

- Превью 1 — главная страница в светлой теме: папки (включая вложенную), карточки вкладок.
- Превью 2 — та же страница в тёмной теме.
- Превью 3 — поиск активен: сетка отфильтрована по запросу.

## Full description (EN)

**BlatTabs** is a saved-tabs manager for Chrome. It replaces the empty new-tab page: **Ctrl+T** (or the «+» button) opens your own start page — a grid of cards with all your saved links.

Save tabs with one click from the popup or the **Ctrl+Shift+S** hotkey — and jump back to them instantly on the new-tab page (Ctrl+T). Spaces and groups are synchronized across devices via `chrome.storage.sync`.

The design is minimal monochrome, Vercel-style: black/white/grey, Geist font, crisp 1px borders; dark theme in one click.

### Features

- **Save tabs** — popup «Save tab» or Ctrl+Shift+S; deduplication by URL.
- **New-tab override** — the new-tab page becomes your tab manager (Ctrl+T).
- **Folders & nested folders** — categories, folders inside folders (1 level), move cards via the folder dropdown or drag & drop.
- **Search** — instant filter by name, title and URL.
- **Drag & drop** — drag cards onto folder chips (native HTML5 DnD, no libraries).
- **Browser tabs mirror** — the right rail lists your open browser tabs in the same order as the top strip (dragging them in the rail reorders the real tabs; new tabs and closes update the rail live). Drag a tab from the rail into the card grid to save it as a card — the browser tab stays open.
- **Open all tabs of a group** — the ⧉ button on a group's header (revealed on hover) opens every tab of that group in new browser tabs; works for collapsed groups too.
- **Bulk open & delete** — checkboxes on cards + «N selected / Open / Clear / Delete» panel; «✕ Delete» removes the selection (with confirmation).
- **Keyboard navigation** — arrow keys across cards (wrapping), Enter to open, Delete to remove, Esc to reset.
- **Dark theme** — 🌙/☀️ toggle in the header, choice is persisted.
- **Background image** — pick a custom background image in the settings; it works in both themes and is stored on the device (up to ~4 MB).
- **Tab color** — pick a custom color for saved-tab cards in the settings; it works in both themes and is stored on the device.
- **Hotkey** — Ctrl+Shift+S saves the current tab.
- **Storage** — the tab list lives in `chrome.storage.local` (per device, up to ~10 MB — large collections fit); spaces and groups live in `chrome.storage.sync` (across devices).
- **JSON export / import** — migrate your collection with folders.

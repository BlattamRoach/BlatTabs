# BlattamToby — описание для магазина

## Короткое описание (<= 132 символов)

Менеджер сохранённых вкладок: новая вкладка (Ctrl+T) с карточками, папками, тегами, сессиями, поиском и синхронизацией.

## Полное описание (RU)

**BlattamToby** — менеджер сохранённых вкладок для Chrome. Расширение заменяет пустую страницу новой вкладки: **Ctrl+T** (или кнопка «+») открывает вашу собственную стартовую страницу — сетку карточек со всеми сохранёнными ссылками.

Сохраняйте вкладки одним кликом из popup или горячей клавишей **Ctrl+Shift+S** — и мгновенно возвращайтесь к ним на любом устройстве: данные синхронизируются через `chrome.storage.sync`.

### Возможности

- **Сохранение вкладок** — popup «Сохранить» или Ctrl+Shift+S; дедупликация по URL.
- **Newtab-override** — страница новой вкладки становится вашим менеджером вкладок (Ctrl+T).
- **Папки и вложенные папки** — категории вкладок, папки внутри папок (1 уровень), перенос карточки чипом-дропдауном или перетаскиванием.
- **Теги** — цветовые метки (палитра из 6 цветов), мультивыбор тегов на вкладке, фильтр по тегам.
- **Поиск** — мгновенная фильтрация по имени, заголовку и URL.
- **Drag & drop** — перетаскивание карточек на чипы папок (нативный HTML5 DnD, без библиотек).
- **Массовое открытие** — чекбоксы на карточках + панель «N выбрано / Открыть / Сбросить»; «☑ Выбрать» — все видимые.
- **Клавиатурная навигация** — стрелки по карточкам (с зацикливанием), Enter — открыть, Delete — удалить, Esc — сброс.
- **Тёмная тема** — переключатель 🌙/☀️ в шапке, выбор сохраняется.
- **Размер карточек** — крупный / компактный режим (▦/▤).
- **Скриншоты вкладок** — миниатюра сохранённой вкладки на карточке (снимается при сохранении).
- **Архив закрытых вкладок** — закрытая в браузере вкладка автоматически попадает в архив (приглушённая карточка, кнопка «↩» — вернуть); чип «🗄 Архив».
- **Сессии** — именованные группы вкладок («📋 + Сессия»): фиксация текущего набора ссылок, фильтр по сессии.
- **Рекомендации** — «⭐ Частые» (самые открываемые) и «🕘 Избранные» (недавно открываемые) на основе истории.
- **Горячая клавиша** — Ctrl+Shift+S сохраняет текущую вкладку.
- **Синхронизация** — вкладки, папки, теги и сессии — в `chrome.storage.sync` (синхронизация между устройствами).
- **Экспорт / импорт JSON** — перенос коллекции с папками, тегами и архивом.

### Скриншоты

- `screenshot-1.png` — главная страница в светлой теме: папки (включая вложенную), теги, сессии, карточки со скриншот-миниатюрой и приглушённая архивная вкладка.
- `screenshot-2.png` — та же страница в тёмной теме.
- `screenshot-3.png` — компактный режим карточек.

## Full description (EN)

**BlattamToby** is a saved-tabs manager for Chrome. It replaces the empty new-tab page: **Ctrl+T** (or the «+» button) opens your own start page — a grid of cards with all your saved links.

Save tabs with one click from the popup or the **Ctrl+Shift+S** hotkey — and jump back to them on any device: data is synchronized via `chrome.storage.sync`.

### Features

- **Save tabs** — popup «Save» or Ctrl+Shift+S; deduplication by URL.
- **New-tab override** — the new-tab page becomes your tab manager (Ctrl+T).
- **Folders & nested folders** — categories, folders inside folders (1 level), move cards via the folder dropdown or drag & drop.
- **Tags** — color labels (6-color palette), multi-tag selection per tab, filter by tag.
- **Search** — instant filter by name, title and URL.
- **Drag & drop** — drag cards onto folder chips (native HTML5 DnD, no libraries).
- **Bulk open** — checkboxes on cards + «N selected / Open / Clear» panel; «☑ Select» for all visible.
- **Keyboard navigation** — arrow keys across cards (wrapping), Enter to open, Delete to remove, Esc to reset.
- **Dark theme** — 🌙/☀️ toggle in the header, choice is persisted.
- **Card sizes** — large / compact modes (▦/▤).
- **Tab screenshots** — a thumbnail of the saved tab on its card (captured on save).
- **Closed-tab archive** — closing a browser tab that you saved archives it (dimmed card, «↩» to restore); «🗄 Archive» chip.
- **Sessions** — named tab groups («📋 + Session»): snapshot the current set of links, filter by session.
- **Recommendations** — «⭐ Frequent» (most opened) and «🕘 Favorites» (recently opened) based on history.
- **Hotkey** — Ctrl+Shift+S saves the current tab.
- **Sync** — tabs, folders, tags and sessions live in `chrome.storage.sync` (across devices).
- **JSON export / import** — migrate your collection with folders, tags and archive.

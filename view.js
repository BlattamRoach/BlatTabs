// === Тема (тёмная/светлая) ===
// Состояние — в chrome.storage.local, ключ 'blattam-theme' ('dark'/'light'),
// по умолчанию светлая. Применяем сохранённую тему ДО первого рендера
// (loadData() вызывается в конце файла) — чтобы страница не мигала.

const themeBtn = document.getElementById('theme-btn');
const themeGlyph = themeBtn.querySelector('.glyph');

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  if (themeGlyph) themeGlyph.textContent = theme === 'dark' ? '\u2600\uFE0F' : '\uD83C\uDF19';
}

chrome.storage.local.get(['blattam-theme'], (result) => {
  applyTheme(result['blattam-theme'] === 'dark' ? 'dark' : 'light');
});

themeBtn.addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  chrome.storage.local.set({ 'blattam-theme': next });
});

// === DOM-ссылки ===

const tabsList = document.getElementById('tabs-list');
const emptyState = document.getElementById('empty-state');
const searchInput = document.getElementById('search');
const noResults = document.getElementById('no-results');
const metaLabel = document.getElementById('meta-label');
const metaCount = document.getElementById('meta-count');
const spacesBar = document.getElementById('spaces-bar');
const spaceChips = document.getElementById('space-chips');
const addSpaceBtn = document.getElementById('add-space-btn');

// Модалка (создание/переименование пространства, создание группы)
const spaceModal = document.getElementById('space-modal');
const modalTitle = document.getElementById('modal-title');
const spaceNameInput = document.getElementById('space-name-input');
const modalCancel = document.getElementById('modal-cancel');
const modalConfirm = document.getElementById('modal-confirm');

// Модалка редактирования вкладки (имя / адрес / комментарий)
const editTabModal = document.getElementById('edit-tab-modal');
const editNameInput = document.getElementById('edit-name-input');
const editUrlInput = document.getElementById('edit-url-input');
const editCommentInput = document.getElementById('edit-comment-input');
const editCancel = document.getElementById('edit-cancel');
const editConfirm = document.getElementById('edit-confirm');
let editTabRef = null; // вкладка, открытая в модалке редактирования

// Панель массового выбора
const selectionBar = document.getElementById('selection-bar');
const selectionCount = document.getElementById('selection-count');
const selectBtn = document.getElementById('select-btn');
const openSelectedBtn = document.getElementById('open-selected-btn');
const clearSelectionBtn = document.getElementById('clear-selection-btn');

let allTabs = [];
let allSpaces = [];   // { id, name } — плоский список (без вложенности)
let allGroups = [];   // { id, name, spaceId, collapsed } — группы внутри пространств
let activeSpaceId = ''; // активное пространство (по id — переживает перерисовку)
let modalCallback = null;
let modalAllowEmpty = false; // модалки создания допускают пустое имя (авто-«Пространство N» / «Группа N»)
let selectedUrls = new Set(); // выбор вкладок для массового открытия
let dragSourceUrl = null; // URL перетаскиваемой карточки (для reorder; индексы в payload могут устареть)
let dragSourceCardEl = null; // DOM-элемент перетаскиваемой карточки (исключается из расчёта зазора)
let dragGhostSlot = null; // ghost-slot: пустая заглушка размера карточки на её месте в сетке
let dragSourceGroupId = null; // id перетаскиваемой группы (reorder шапок внутри пространства)
let activeUrl = null; // карточка, выбранная клавиатурой (по URL — переживает перерисовку)
let openModalId = null; // id открытой модалки — чтобы глобальный keydown её не перехватывал

const DEFAULT_SPACE_NAME = 'Мои вкладки';

function genId(prefix) {
  return (prefix || 'x') + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

// Отмечаем открытую/закрытую модалку (для global keydown-гарда)
function setModalOpen(id) {
  openModalId = id || null;
}

function isAnyModalOpen() {
  return openModalId !== null;
}

// === Миграция: legacy-папки → пространства (чистая, идемпотентная) ===
// Вызывается, когда ключ 'blattam-spaces' отсутствует: каждое папки (любой
// вложенности) становится отдельным плоским пространством с тем же именем,
// вкладки перемещаются folderId → spaceId, вкладки без папки (folderId
// null/отсутствует/неизвестная) → пространство «Мои вкладки». Группы не
// создаются — все legacy-вкладки без группы.
function migrateFoldersToSpaces(tabs, spaces, folders) {
  const folderToSpaceId = {};
  (folders || []).forEach(f => {
    if (!f || !f.id) return;
    const sp = { id: genId('sp'), name: f.name };
    spaces.push(sp);
    folderToSpaceId[f.id] = sp.id;
  });
  let defaultSpace = null;
  (tabs || []).forEach(t => {
    if (!t) return;
    if (t.folderId != null && folderToSpaceId[t.folderId]) {
      t.spaceId = folderToSpaceId[t.folderId];
    } else {
      if (!defaultSpace) {
        defaultSpace = { id: genId('sp'), name: DEFAULT_SPACE_NAME };
        spaces.push(defaultSpace);
      }
      t.spaceId = defaultSpace.id;
    }
    t.groupId = null;
    delete t.folderId;
  });
}

// === Загрузка данных ===

function loadData() {
  chrome.storage.sync.get(['blattam-tabs', 'blattam-spaces', 'blattam-groups', 'blattam-last-space', 'blattam-folders'], (result) => {
    const tabs = result['blattam-tabs'] || [];
    const spaces = Array.isArray(result['blattam-spaces']) ? result['blattam-spaces'] : [];
    const groups = Array.isArray(result['blattam-groups']) ? result['blattam-groups'] : [];
    const folders = result['blattam-folders'];

    const updates = {};

    // Миграция legacy (ДО первого рендера): нет 'blattam-spaces', но есть
    // 'blattam-folders' или вкладки с folderId
    if (!Array.isArray(result['blattam-spaces']) && (folders !== undefined || tabs.some(t => t && t.folderId != null))) {
      migrateFoldersToSpaces(tabs, spaces, folders);
      updates['blattam-tabs'] = tabs;
      updates['blattam-spaces'] = spaces;
    }

    // Свежее состояние — всегда есть хотя бы одно пространство
    if (spaces.length === 0) {
      spaces.push({ id: genId('sp'), name: DEFAULT_SPACE_NAME });
      updates['blattam-spaces'] = spaces;
    }

    // Вкладки без spaceId (вручную внесённые данные) — в первое пространство
    let tabsChanged = false;
    tabs.forEach(t => {
      if (t && !t.spaceId) { t.spaceId = spaces[0].id; tabsChanged = true; }
    });
    if (tabsChanged) updates['blattam-tabs'] = tabs;

    // Активное пространство: последнее посещённое (blattam-last-space),
    // если оно ещё существует, иначе первое
    const last = result['blattam-last-space'];
    activeSpaceId = (last && spaces.some(s => s.id === last)) ? last : spaces[0].id;
    if (updates['blattam-spaces'] && last !== activeSpaceId) updates['blattam-last-space'] = activeSpaceId;

    allTabs = tabs;
    allSpaces = spaces;
    allGroups = groups;

    if (Object.keys(updates).length) {
      if (folders !== undefined) chrome.storage.sync.remove('blattam-folders');
      chrome.storage.sync.set(updates);
    }
    renderSpaces();
    renderTabs();
  });
}

// === Пространства (чипы) ===

function spaceLabel() {
  const s = allSpaces.find(x => x.id === activeSpaceId);
  return s ? s.name : DEFAULT_SPACE_NAME;
}

function renderSpaces() {
  spaceChips.innerHTML = '';
  allSpaces.forEach(sp => {
    const chip = document.createElement('button');
    chip.className = 'chip space-chip' + (sp.id === activeSpaceId ? ' active' : '');
    chip.dataset.spaceId = sp.id;

    const name = document.createElement('span');
    name.className = 'chip-name';
    name.textContent = sp.name;
    chip.appendChild(name);

    // Действия (✎ ✕) — видны на hover чипа
    const actions = document.createElement('div');
    actions.className = 'chip-actions';

    const renameBtn = document.createElement('button');
    renameBtn.className = 'chip-icon-btn';
    renameBtn.textContent = '\u270E';
    renameBtn.title = 'Переименовать';
    renameBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      openRenameSpaceModal(sp.id, sp.name);
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'chip-icon-btn';
    deleteBtn.textContent = '\u2715';
    deleteBtn.title = 'Удалить пространство';
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const remaining = allSpaces.filter(s => s.id !== sp.id);
      const targetName = remaining.length ? remaining[0].name : DEFAULT_SPACE_NAME;
      if (confirm(`Удалить пространство "${sp.name}"? Вкладки переместятся в "${targetName}".`)) {
        chrome.runtime.sendMessage({ action: 'delete-space', id: sp.id });
      }
    });

    actions.appendChild(renameBtn);
    actions.appendChild(deleteBtn);
    chip.appendChild(actions);

    // DnD: чип принимает перетаскиваемую карточку
    attachSpaceDrop(chip, sp.id);

    // Клик — переключение пространства
    chip.addEventListener('click', () => switchSpace(sp.id));
    spaceChips.appendChild(chip);
  });
}

// Переключение пространства: активное — JS-переменная, blattam-last-space
// обновляется, чтобы следующий newtab-открыв открылся с тем же пространством
function switchSpace(id) {
  if (!id || id === activeSpaceId) return;
  activeSpaceId = id;
  chrome.storage.sync.set({ 'blattam-last-space': id });
  renderSpaces();
  renderTabs(searchInput.value);
}

// "+ Пространство" — создать пространство (пустое имя → «Пространство N»)
addSpaceBtn.addEventListener('click', () => {
  modalTitle.textContent = 'Новое пространство';
  spaceNameInput.value = '';
  showSpaceModal(true, (name) => {
    chrome.runtime.sendMessage({ action: 'create-space', name }, (result) => {
      // новое пространство становится активным
      if (result && result.id) {
        activeSpaceId = result.id;
        chrome.storage.sync.set({ 'blattam-last-space': result.id });
      }
      renderSpaces();
      renderTabs(searchInput.value);
    });
  });
});

// Модалка: переименовать пространство
function openRenameSpaceModal(spaceId, currentName) {
  modalTitle.textContent = 'Переименовать пространство';
  spaceNameInput.value = currentName;
  showSpaceModal(false, (name) => {
    if (name && name !== currentName) {
      chrome.runtime.sendMessage({ action: 'rename-space', id: spaceId, name });
    }
  });
}

function showSpaceModal(allowEmpty, onConfirm) {
  modalCallback = onConfirm;
  modalAllowEmpty = allowEmpty;
  spaceModal.classList.add('open');
  setModalOpen('space');
  setTimeout(() => spaceNameInput.focus(), 50);
}

modalCancel.addEventListener('click', closeSpaceModal);
spaceModal.addEventListener('click', (e) => {
  if (e.target === spaceModal) closeSpaceModal();
});

function closeSpaceModal() {
  spaceModal.classList.remove('open');
  modalCallback = null;
  modalAllowEmpty = false;
  setModalOpen(null);
}

modalConfirm.addEventListener('click', () => {
  const name = spaceNameInput.value.trim();
  if (!name && !modalAllowEmpty) return;
  if (modalCallback) modalCallback(name);
  closeSpaceModal();
});

spaceNameInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') modalConfirm.click();
  if (e.key === 'Escape') modalCancel.click();
});

// === Модалка: редактирование сохранённой вкладки (имя / адрес / комментарий) ===
function openEditTabModal(tab) {
  editTabRef = tab;
  editNameInput.value = tab.name;
  editUrlInput.value = tab.url;
  editCommentInput.value = tab.comment || '';
  editTabModal.classList.add('open');
  setModalOpen('edit-tab');
  setTimeout(() => { editNameInput.focus(); editNameInput.select(); }, 50);
}

function closeEditTabModal() {
  editTabModal.classList.remove('open');
  editTabRef = null;
  setModalOpen(null);
}

editCancel.addEventListener('click', closeEditTabModal);
// Клик по затемнённому фону НЕ закрывает модалку: при выделении текста
// в поле указатель уносит за окно, и «клик снаружи» бы схлопнул форму.
// Закрытие: Enter (сохранить), «Отмена», Escape.

editConfirm.addEventListener('click', () => {
  if (!editTabRef) return;
  const name = editNameInput.value.trim();
  const url = editUrlInput.value.trim();
  const comment = editCommentInput.value.trim();
  if (!name && !url && !comment) return; // пустая форма — не сохраняем
  // Пустое имя/адрес — старое значение; комментарий пустой — очистить
  chrome.runtime.sendMessage({
    action: 'update-tab',
    index: allTabs.indexOf(editTabRef),
    name: name || editTabRef.name,
    url: url || editTabRef.url,
    comment,
  });
  closeEditTabModal();
});

[editNameInput, editUrlInput, editCommentInput].forEach((inp) => {
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') editConfirm.click();
    if (e.key === 'Escape') editCancel.click();
  });
});

// === Открытие вкладок (единый путь: background создаёт browser-tab) ===

// Открыть одну вкладку: background создаёт browser-tab
function openUrl(url) {
  chrome.runtime.sendMessage({ action: 'open-one', url });
  selectedUrls.delete(url);
  renderTabs(searchInput.value);
}

// Массовое открытие: background открывает каждую вкладку (неактивно)
function openMany(urls) {
  chrome.runtime.sendMessage({ action: 'open-many', urls: urls });
  selectedUrls.clear();
  renderTabs(searchInput.value);
}

// === Фавикон на карточке ===
// Буквенный fallback: первая буквенная/цифровая символа домена
// (github.com → 'g'), иначе '?'.
function faviconFallbackChar(url) {
  let host = '';
  try { host = new URL(url).hostname || ''; } catch (err) { host = ''; }
  if (!host && url) host = String(url).replace(/^[a-z]+:\/\/?/i, '').split('/')[0].split(':')[0];
  const m = (host || '').toLowerCase().match(/[a-zа-яё0-9]/);
  return m ? m[0] : '?';
}

// Буквенная монохромная плитка (span.tab-favicon-fallback)
function makeFaviconFallback(tab, letter) {
  const span = document.createElement('span');
  span.className = 'tab-favicon-fallback';
  span.textContent = letter || '?';
  span.title = tab.url || '';
  return span;
}

// Рендерит <img class="tab-favicon"> (если есть favIconUrl) перед именем,
// иначе буквенный fallback. При ошибке загрузки img — меняет его на
// буквенный fallback (однократно, без повторных попыток).
function appendFavicon(nameEl, tab) {
  const letter = faviconFallbackChar(tab.url);
  if (tab.favIconUrl) {
    const img = document.createElement('img');
    img.className = 'tab-favicon';
    img.src = tab.favIconUrl;
    img.alt = '';
    img.draggable = false;
    img.addEventListener('error', () => {
      if (img.parentNode) img.replaceWith(makeFaviconFallback(tab, letter));
    });
    nameEl.insertBefore(img, nameEl.firstChild);
  } else {
    nameEl.insertBefore(makeFaviconFallback(tab, letter), nameEl.firstChild);
  }
}

// === Группы (сворачиваемые секции внутри пространства) ===

function pluralGroups(n) {
  const a = Math.abs(n) % 100, d = a % 10;
  if (a > 10 && a < 20) return 'групп';
  if (d > 1 && d < 5) return 'группы';
  if (d === 1) return 'группа';
  return 'групп';
}

function pluralVkladok(n) {
  const a = Math.abs(n) % 100, d = a % 10;
  if (a > 10 && a < 20) return 'вкладок';
  if (d > 1 && d < 5) return 'вкладки';
  if (d === 1) return 'вкладка';
  return 'вкладок';
}

// Защита hover-кнопок от drag, «проглотившего» клик: на draggable-родителе
// (шапка группы / карточка) нажатие + движение >~5px запускает drag родителем
// и click по вложенной кнопке теряется (реальный Chrome; синтетический
// .click() это не ловит). Пока мышь нажата на кнопке — снимаем draggable,
// восстанавливаем на mouseup/blur окна (fallback: press, завершённый вне
// окна).
function guardDragOverButtons(parent, selector) {
  parent.addEventListener('mousedown', (e) => {
    const t = e.target;
    if (!(t instanceof Element) || !t.closest(selector)) return;
    parent.draggable = false;
    parent.dataset.pressBtn = '1'; // click-обработчик родителя учитывает
    const restore = () => {
      parent.draggable = true;
      delete parent.dataset.pressBtn;
      window.removeEventListener('mouseup', restore);
      window.removeEventListener('blur', restore);
    };
    window.addEventListener('mouseup', restore);
    window.addEventListener('blur', restore);
  });
}

// Шапка группы «Штрих»: полноширинная (grid-column 1/-1) строка БЕЗ заливки
// — 1px-линия сверху (--line2) + chevron + приглушённое имя (--text-soft, 12px)
// + mono-счётчик + «✕». Всегда видна; клик — свернуть/развернуть (карточки
// уходят из DOM, счётчик на шапке остаётся). Состояние сворачивания — в данных
// (blattam-groups.collapsed), поэтому переживает перерисовку.
function appendGroupBar(g, memberCount) {
  const bar = document.createElement('div');
  bar.className = 'gbar';
  bar.dataset.groupId = g.id;

  const chev = document.createElement('span');
  chev.className = 'chev';
  chev.textContent = g.collapsed ? '\u25B8' : '\u25BE';

  const name = document.createElement('span');
  name.className = 'gname';
  name.textContent = g.name;

  const count = document.createElement('span');
  count.className = 'gcount';
  count.textContent = memberCount + ' ' + pluralVkladok(memberCount);

  const del = document.createElement('button');
  del.className = 'gdel';
  del.textContent = '\u2715';
  del.title = 'Удалить группу';
  del.addEventListener('click', (e) => {
    e.stopPropagation();
    if (confirm(`Удалить группу "${g.name}"? Вкладки останутся в пространстве.`)) {
      chrome.runtime.sendMessage({ action: 'delete-group', id: g.id });
    }
  });

  const gUrls = allTabs.filter(t => t.spaceId === g.spaceId && t.groupId === g.id).map(t => t.url);

  // ☑ — выбрать/снять выбор ВСЕХ вкладок группы (hover-контрол; не сворачивает
  // группу и не стартует drag — stopPropagation)
  const gselect = document.createElement('button');
  gselect.className = 'gselect';
  gselect.textContent = '\u2611';
  gselect.title = 'Выбрать все вкладки группы';
  if (gUrls.length > 0 && gUrls.every(u => selectedUrls.has(u))) gselect.classList.add('on');
  gselect.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleGroupSelection(g);
  });

  // ✎ — инлайн-ренейм группы (hover-контрол, та же идиоматика, что у карточки)
  const grename = document.createElement('button');
  grename.className = 'grename';
  grename.textContent = '\u270E';
  grename.title = 'Переименовать группу';
  grename.addEventListener('click', (e) => {
    e.stopPropagation();
    startGroupRename(g, name);
  });

  bar.appendChild(chev);
  bar.appendChild(name);
  bar.appendChild(count);
  bar.appendChild(gselect);
  bar.appendChild(grename);
  bar.appendChild(del);

  // DnD-источник: шапку можно перетащить на другую шапку (reorder групп
  // внутри пространства). Пейлоад: id группы (у карточки — индекс вкладки).
  bar.draggable = true;
  // Кнопки шапки (☑/✎/✕) не стартуют drag: нажатие на них временно снимает
  // draggable, иначе движение >~5px во время press уносит drag-ом шапку и
  // click по кнопке теряется (реальный Chrome).
  guardDragOverButtons(bar, '.gselect, .grename, .gdel');
  bar.addEventListener('dragstart', (e) => {
    if (!bar.draggable) { e.preventDefault(); return; } // press начался на кнопке
    e.dataTransfer.setData('text/plain', g.id);
    e.dataTransfer.effectAllowed = 'move';
    dragSourceGroupId = g.id;
    bar.classList.add('dragging');
  });
  bar.addEventListener('dragend', () => {
    dragSourceGroupId = null;
    bar.classList.remove('dragging');
    clearGroupReorderIndicators();
  });

  // DnD: шапка принимает только другую шапку — reorder групп (2px-индикатор
  // до/после). Карточка, сброшенная на шапку, больше не уходит в группу
  // (свою семантику дропа карточки сохранил только чип пространства)
  bar.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (dragSourceGroupId) {
      if (dragSourceGroupId === g.id) return; // на себя — не целевая
      const side = reorderSide(bar, e.clientY);
      bar.classList.toggle('drop-before', side === 'before');
      bar.classList.toggle('drop-after', side === 'after');
      return;
    }
    // Пустая/свёрнутая группа (нет видимых карточек): шапка принимает
    // карточку — тёплый армед-подсвет
    if (dragSourceUrl && !groupVisibleCardCount(g.id)) bar.classList.add('drop-over');
  });
  bar.addEventListener('dragleave', () => bar.classList.remove('drop-over', 'drop-before', 'drop-after'));
  bar.addEventListener('drop', (e) => {
    e.preventDefault();
    bar.classList.remove('drop-over', 'drop-before', 'drop-after');
    if (dragSourceGroupId) {
      reorderGroups(dragSourceGroupId, g.id, reorderSide(bar, e.clientY));
      return;
    }
    // Пустая/свёрнутая группа: карточка уходит в группу — в конец списка
    // (anchorIndex null); карточка своей группы — no-op
    if (dragSourceUrl && !groupVisibleCardCount(g.id)) {
      const src = allTabs.find(t => t.url === dragSourceUrl);
      if (src && src.groupId !== g.id) {
        chrome.runtime.sendMessage({ action: 'place-tab', index: allTabs.indexOf(src),
          anchorIndex: null, side: 'after', groupId: g.id });
      }
    }
  });

  bar.addEventListener('click', () => {
    if (bar.dataset.pressBtn) return; // press начался на кнопке и сошёл на шапку — не сворачиваем
    toggleGroupCollapsed(g.id);
  });
  tabsList.appendChild(bar);
}

// Число ВИДИМЫХ карточек группы в #tabs-list (перетаскиваемая скрыта —
// не считается; свёрнутая группа — карточек в DOM нет → 0). По нему
// шапка/слот пустой группы принимают карточку.
function groupVisibleCardCount(groupId) {
  return [...document.querySelectorAll('#tabs-list .tab-card')]
    .filter(c => c.style.display !== 'none' && c.__tab && c.__tab.groupId === groupId).length;
}

// Слот-заглушка пустой развёрнутой группы: полноширинная пунктирная строка
// «Перетащите вкладку сюда» сразу после шапки — видимая drop-цель карточки
// (свёрнутая группа слота не даёт). Drop-семантика как у шапки пустой
// группы: вкладка уходит в группу (place-tab, anchorIndex null — конец
// списка); карточка своей группы — no-op. Слот рендерится во всех ветках
// renderTabs, где группа развёрнута без карточек.
function appendEmptyGroupSlot(g) {
  const slot = document.createElement('div');
  slot.className = 'group-empty-slot';
  slot.dataset.groupId = g.id;
  slot.textContent = 'Перетащите вкладку сюда';
  slot.draggable = false;
  // DnD: слот принимает карточку (перетаскиваемая шапка группы — no-op)
  slot.addEventListener('dragover', (e) => {
    if (dragSourceGroupId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    slot.classList.add('drop-over');
  });
  slot.addEventListener('dragleave', () => slot.classList.remove('drop-over'));
  slot.addEventListener('drop', (e) => {
    e.preventDefault();
    slot.classList.remove('drop-over');
    if (dragSourceGroupId) return;
    const src = allTabs.find(t => t.url === dragSourceUrl);
    if (!src || src.groupId === g.id) return;
    chrome.runtime.sendMessage({ action: 'place-tab', index: allTabs.indexOf(src),
      anchorIndex: null, side: 'after', groupId: g.id });
  });
  tabsList.appendChild(slot);
}

// Сворачивание группы: запись в blattam-groups → onChanged → перерисовка.
// Пишем только при реальном переключении.
function toggleGroupCollapsed(groupId) {
  const g = allGroups.find(x => x.id === groupId);
  if (!g) return;
  g.collapsed = !g.collapsed;
  chrome.storage.sync.set({ 'blattam-groups': allGroups });
}

// ☑ — выбор ВСЕХ вкладок группы (независимо от сворачивания): если все члены
// уже в selectedUrls — снять всех, иначе добавить всех. Выбор завязан на URL,
// переживает перерисовку; перерисовка — с текущим поиском.
function toggleGroupSelection(g) {
  const urls = allTabs.filter(t => t.spaceId === g.spaceId && t.groupId === g.id).map(t => t.url);
  if (urls.length === 0) return;
  const allSelected = urls.every(u => selectedUrls.has(u));
  urls.forEach(u => allSelected ? selectedUrls.delete(u) : selectedUrls.add(u));
  renderTabs(searchInput.value);
}

// ✎ — инлайн-ренейм группы: <input> на месте .gname. Enter/blur — сохранить
// (пустое/whitespace-имя — старое имя, дубли имён допустимы), Esc — отмена.
// Имя пишется в allGroups + blattam-groups (запись в storage → onChanged).
function startGroupRename(g, nameEl) {
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'gname-input';
  input.value = g.name;
  input.autocomplete = 'off';
  nameEl.replaceWith(input);
  input.focus();
  input.select();

  let done = false;
  const finish = (save) => {
    if (done) return;
    done = true;
    const newName = input.value.trim();
    if (save && newName && newName !== g.name) {
      g.name = newName;
      chrome.storage.sync.set({ 'blattam-groups': allGroups });
    }
    renderTabs(searchInput.value);
  };

  input.addEventListener('click', (e) => e.stopPropagation());
  input.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Enter') finish(true);
    if (e.key === 'Escape') finish(false);
  });
  input.addEventListener('blur', () => finish(true));
}

// Reorder групп: вырезаем группу из глобального allGroups и вставляем
// до/после цели (side — по половине целевой шапки). Группы других
// пространств сохраняют относительный порядок; collapsed/члены остаются
// у группы. Drop on себя — no-op. Запись в blattam-groups → onChanged.
function reorderGroups(fromId, toId, side) {
  const from = allGroups.findIndex(x => x.id === fromId);
  const to = allGroups.findIndex(x => x.id === toId);
  if (from === -1 || to === -1 || from === to) return;
  const src = allGroups[from];
  if (src.spaceId !== activeSpaceId) return;
  allGroups.splice(from, 1);
  let insertAt = allGroups.findIndex(x => x.id === toId);
  if (side === 'after') insertAt += 1;
  allGroups.splice(insertAt, 0, src);
  chrome.storage.sync.set({ 'blattam-groups': allGroups });
}

// Снимаем индикаторы reorder со всех шапок групп
function clearGroupReorderIndicators() {
  document.querySelectorAll('.gbar.drop-before, .gbar.drop-after')
    .forEach(b => b.classList.remove('drop-before', 'drop-after'));
}

// «+ Группа» — полноширинная пунктирная строка В КОНЦЕ списка вкладок
// (строится в renderTabs во всех ветках рендера, включая пустое
// пространство; работает и с пустым пространством).
// Пустое имя → «Группа N». Группа создаётся в активном пространстве.
function createGroupInActiveSpace() {
  modalTitle.textContent = 'Новая группа';
  spaceNameInput.value = '';
  showSpaceModal(true, (name) => {
    chrome.runtime.sendMessage({ action: 'create-group', spaceId: activeSpaceId, name }, (group) => {
      if (group && group.id) renderTabs(searchInput.value);
    });
  });
}

// Строит кнопку «+ Группа» (последний элемент #tabs-list)
function appendAddGroupBtn() {
  const btn = document.createElement('button');
  btn.className = 'add-group-row';
  btn.id = 'add-group-btn';
  btn.title = 'Новая группа';
  btn.textContent = '+ Группа';
  btn.addEventListener('click', createGroupInActiveSpace);
  tabsList.appendChild(btn);
}

// === Карточки вкладок ===

// Переместить вкладку: spaceId (в новое пространство, groupId очищается)
// и/или groupId (null — «Без группы»). Индекс — по полному массиву.
function moveTabTo(tab, spaceId, groupId) {
  const idx = allTabs.indexOf(tab);
  if (idx === -1) return;
  const msg = { action: 'move-tab', index: idx };
  if (spaceId !== undefined) msg.spaceId = spaceId;
  if (groupId !== undefined) msg.groupId = groupId;
  chrome.runtime.sendMessage(msg);
}

// Строит карточку вкладки (вызывается для членов групп и негрупповых вкладок)
function appendCard(tab) {
  const card = document.createElement('div');
  card.className = 'tab-card'
    + (selectedUrls.has(tab.url) ? ' selected' : '')
    + (activeUrl === tab.url ? ' kbd-active' : '');
  card.__tab = tab; // ссылка на данные (секционно-чуткий расчёт слота при DnD)

  // Чекбокс массового выбора (hover-контрол, сверху-слева)
  const selectCb = document.createElement('input');
  selectCb.type = 'checkbox';
  selectCb.className = 'tab-select';
  selectCb.checked = selectedUrls.has(tab.url);
  selectCb.title = 'Выбрать для массового открытия';
  selectCb.addEventListener('click', (e) => {
    e.stopPropagation();
    if (selectCb.checked) selectedUrls.add(tab.url);
    else selectedUrls.delete(tab.url);
    card.classList.toggle('selected', selectCb.checked);
    updateSelectionBar();
  });

  // Кнопка удаления (hover-контрол, сверху-справа)
  const deleteBtn = document.createElement('button');
  deleteBtn.className = 'icon-btn tab-remove delete';
  deleteBtn.title = 'Удалить';
  deleteBtn.textContent = '\u2715';
  deleteBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (confirm(`Удалить вкладку "${tab.name}"?`)) {
      allTabs.splice(allTabs.indexOf(tab), 1);
      chrome.storage.sync.set({ 'blattam-tabs': allTabs });
      renderTabs(searchInput.value);
    }
  });

  // Кнопка редактирования (hover-контрол, снизу-справа) — меню «Изменить»
  const editBtn = document.createElement('button');
  editBtn.className = 'tab-edit';
  editBtn.title = 'Редактировать вкладку';
  editBtn.textContent = '\u270E';
  let cardMenu = null;
  const closeCardMenu = () => {
    if (cardMenu) { cardMenu.remove(); cardMenu = null; }
  };
  editBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (cardMenu) { closeCardMenu(); return; } // повторный клик — закрыть
    cardMenu = document.createElement('div');
    cardMenu.className = 'tab-card-menu';
    const changeItem = document.createElement('button');
    changeItem.textContent = 'Изменить';
    changeItem.addEventListener('click', (ev) => {
      ev.stopPropagation();
      closeCardMenu();
      openEditTabModal(tab);
    });
    cardMenu.appendChild(changeItem);
    card.appendChild(cardMenu);
    // Клик вне меню — закрыть
    const onOutside = (ev) => {
      if (cardMenu && !cardMenu.contains(ev.target)) {
        closeCardMenu();
        document.removeEventListener('click', onOutside);
      }
    };
    setTimeout(() => document.addEventListener('click', onOutside), 0);
  });

  // Hover-контролы — absolute, привязаны к карточке
  card.appendChild(selectCb);
  card.appendChild(deleteBtn);
  card.appendChild(editBtn);

  // Тело: имя + URL
  const body = document.createElement('div');
  body.className = 'cbody';

  const nameEl = document.createElement('div');
  nameEl.className = 'cname';
  const nameText = document.createElement('span');
  nameText.className = 'tab-name';
  nameText.textContent = tab.name;
  nameText.title = 'Двойной клик — переименовать';
  nameEl.appendChild(nameText);

  // Фавикон (или буквенный fallback) — перед именем
  appendFavicon(nameEl, tab);

  // Двойной клик по имени → инлайн-редактирование.
  // Одиночный клик по имени открывает вкладку, но с задержкой 300мс,
  // чтобы dblclick успел отменить его.
  let nameClickTimer = null;
  let nameClicks = 0;
  nameEl.addEventListener('click', (e) => {
    e.stopPropagation();
    nameClicks++;
    if (nameClicks === 1) {
      nameClickTimer = setTimeout(() => {
        nameClicks = 0;
        nameClickTimer = null;
        openUrl(tab.url);
      }, 300);
    }
  });
  nameEl.addEventListener('dblclick', (e) => {
    e.stopPropagation();
    if (nameClickTimer) { clearTimeout(nameClickTimer); nameClickTimer = null; }
    nameClicks = 0;
    startRename(tab, nameText, body);
  });

  body.appendChild(nameEl);
  card.appendChild(body);

  // Комментарий (если задан) — внизу внутри карточки, моно, обрезается
  if (tab.comment) {
    const commentEl = document.createElement('div');
    commentEl.className = 'tab-comment';
    commentEl.textContent = tab.comment;
    commentEl.title = tab.comment;
    card.appendChild(commentEl);
  }

  // Клик по карточке — открыть вкладку + снять выбор
  card.addEventListener('click', () => {
    if (card.dataset.pressBtn) return; // press начался на чекбоксе/✕ — не открываем
    openUrl(tab.url);
  });

  // Drag & drop: карточку можно перетащить на чип пространства (переместить)
  // или в зазор между карточками (reorder — глобальные обработчики ниже)
  card.draggable = true;
  // Hover-кнопки (чекбокс/✕/✎) не стартуют drag — то же, что у шапки группы.
  guardDragOverButtons(card, '.tab-select, .tab-remove, .tab-edit');
  card.addEventListener('dragstart', (e) => {
    if (!card.draggable) { e.preventDefault(); return; } // press начался на кнопке
    e.dataTransfer.setData('text/plain', String(allTabs.indexOf(tab)));
    e.dataTransfer.effectAllowed = 'move';
    dragSourceUrl = tab.url;
    dragSourceCardEl = card;
    card.classList.add('dragging');
    // Оригинал исчезает из слота (нативный drag-образ браузера следует за
    // курсором); место занимает тёплая заглушка (ghost-slot) — отложенно:
    // display:none в самом dragstart «залипает» HTML5-drag в Chrome
    setTimeout(() => {
      if (dragSourceUrl !== tab.url) return;
      if (!dragGhostSlot) {
        // Меряем ДО display:none (у скрытой карточки offsetWidth/Height = 0)
        dragGhostSlot = makeGhostSlot(card);
        card.insertAdjacentElement('afterend', dragGhostSlot);
      }
      card.style.display = 'none';
    }, 0);
  });
  card.addEventListener('dragend', () => {
    dragSourceUrl = null;
    dragSourceCardEl = null;
    card.classList.remove('dragging');
    if (card.isConnected) card.style.display = ''; // drag без drop — вернуть карточку в слот
    removeGhostSlot();
    document.querySelectorAll('.space-chip.drag-over').forEach(c => c.classList.remove('drag-over'));
  });

  tabsList.appendChild(card);
}

// Вкладки активного пространства
function spaceTabs() {
  return allTabs.filter(t => t.spaceId === activeSpaceId);
}

// Группы активного пространства (порядок = порядок в blattam-groups)
function spaceGroups() {
  return allGroups.filter(g => g.spaceId === activeSpaceId);
}

// Негрупповая вкладка: groupId отсутствует/пуст, или группы с таким id
// нет в активном пространстве (ветхий groupId)
function isLooseTab(t) {
  if (!t.groupId) return true;
  return !spaceGroups().some(g => g.id === t.groupId);
}

// Текущие видимые карточки активного пространства, в порядке рендера:
// группы по порядку (свёрнутые — вне DOM, их члены пропускаются), затем
// негрупповые. Поиск фильтрует по имени/title/URL.
function visibleTabs(filter = '') {
  const sTabs = spaceTabs();
  const match = (t) => !filter || matchFilter(t, filter);
  const result = [];
  spaceGroups().forEach(g => {
    if (g.collapsed) return;
    sTabs.filter(t => t.groupId === g.id && match(t)).forEach(t => result.push(t));
  });
  sTabs.filter(t => isLooseTab(t) && match(t)).forEach(t => result.push(t));
  return result;
}

function renderTabs(filter = '') {
  tabsList.innerHTML = '';
  // Перерисовка во время перетаскивания уносит заглушку (и заменяет карточку) —
  // сбрасываем ссылку, чтобы ghost-slot не «воскрес» после dragend
  if (dragGhostSlot && !dragGhostSlot.isConnected) dragGhostSlot = null;

  const sTabs = spaceTabs();
  const sGroups = spaceGroups();

  // Если активная (клавиатурная) карточка не в видимом списке — сбрасываем
  const visible = visibleTabs(filter);
  if (activeUrl && !visible.some(t => t.url === activeUrl)) activeUrl = null;

  metaLabel.textContent = spaceLabel();

  if (sTabs.length === 0) {
    if (sGroups.length > 0) {
      // Пространство без вкладок, но с группами — не «пусто»: показываем
      // пустые группы (счётчик «0 вкладок»)
      emptyState.style.display = 'none';
      sGroups.forEach(g => {
        appendGroupBar(g, 0);
        if (!g.collapsed) appendEmptyGroupSlot(g);
      });
      noResults.style.display = 'none';
      metaCount.textContent = '0';
    } else {
      emptyState.style.display = 'block';
      noResults.style.display = 'none';
      metaCount.textContent = '0';
    }
    appendAddGroupBtn();
    updateSelectionBar();
    return;
  }
  emptyState.style.display = 'none';

  let visibleCount = 0;

  // Секции групп (порядок = порядок в массиве)
  sGroups.forEach(g => {
    const members = sTabs.filter(t => t.groupId === g.id);
    appendGroupBar(g, members.length);
    if (!g.collapsed) {
      members.forEach(t => {
        if (filter && !matchFilter(t, filter)) return;
        appendCard(t);
        visibleCount++;
      });
      if (members.length === 0) appendEmptyGroupSlot(g);
    }
  });

  // Негрупповые вкладки — после всех групп (с подписью, если есть группы)
  const loose = sTabs.filter(t => isLooseTab(t) && (!filter || matchFilter(t, filter)));
  if (sGroups.length > 0 && loose.length > 0) {
    const lbl = document.createElement('div');
    lbl.className = 'loose-label';
    lbl.textContent = 'Без группы';
    tabsList.appendChild(lbl);
  }
  loose.forEach(t => {
    appendCard(t);
    visibleCount++;
  });

  // «Ничего не найдено» — только при активном поиске: сворачивание групп
  // (visibleCount === 0 без фильтра) его не показывает
  noResults.style.display = (visibleCount === 0 && filter) ? 'block' : 'none';
  metaCount.textContent = String(visibleCount);
  // «+ Группа» — всегда последним элементом списка
  appendAddGroupBtn();
  updateSelectionBar();
  // Активная карточка видна на экране
  if (activeUrl) {
    const activeCard = tabsList.querySelector('.tab-card.kbd-active');
    if (activeCard) activeCard.scrollIntoView({ block: 'nearest' });
  }
}

function matchFilter(tab, filter) {
  const f = filter.toLowerCase();
  return (tab.name || '').toLowerCase().includes(f) ||
         (tab.title || '').toLowerCase().includes(f) ||
         (tab.url || '').toLowerCase().includes(f);
}

// === Drag & drop: перетаскивание карточки on чип пространства ===

// Чип пространства принимает карточку (перетаскиваемая шапка группы — no-op)
function attachSpaceDrop(chip, spaceId) {
  chip.addEventListener('dragover', (e) => {
    if (dragSourceGroupId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    chip.classList.add('drag-over');
  });
  chip.addEventListener('dragleave', () => chip.classList.remove('drag-over'));
  chip.addEventListener('drop', (e) => {
    e.preventDefault();
    chip.classList.remove('drag-over');
    if (dragSourceGroupId) return;
    const idx = parseInt(e.dataTransfer.getData('text/plain'), 10);
    const tab = allTabs[idx];
    if (tab) moveTabTo(tab, spaceId, undefined);
  });
}

// === Drag & drop: перестановка карточек (reorder), toby-style ===
// Забрали карточку: оригинал исчезает из слота (на его месте — ghost-slot: тёплая пустая
// заглушка размера карточки); нативный drag-образ браузера следует за курсором, клон-призрака нет.
// Заглушка — ЕДИНСТВЕННЫЙ индикатор вставки (2px-линия убрана): она ходит за
// курсором с учётом секций (группы / «Без группы») — встаёт перед карточкой,
// после последней, ДО шапки секции (конец предыдущей) или ПОСЛЕ шапки
// (начало секции). Дроп ставит вкладку в ПОЛНОМ allTabs на позицию заглушки
// (работает под любым фильтром) и задаёт groupId секции заглушки
// (null — «Без группы»); spaceId не меняется. Свою семантику дропа карточки
// сохранил только чип пространства (над ним и над шапкой группы заглушка
// просто стоит до drop/dragend); шапка группы — только reorder групп.

// Ghost-slot: пустая заглушка размера карточки (без текста) — занимает слот
// карточки в сетке; тон — тёплые токены --ghost-bg/--ghost-ring (фон) и
// пунктирный --ghost-ring (контур).
// pointer-events:none — курсор «видит сквозь» заглушку (gap-индекс не дёргается,
// дроп падает на сам список). Инлайн: в тестах <head>-стили view.html не грузятся.
function makeGhostSlot(card) {
  const slot = document.createElement('div');
  slot.className = 'tab-ghost-slot';
  slot.draggable = false;
  slot.style.cssText =
    'pointer-events:none;box-sizing:border-box;background:var(--ghost-bg);' +
    'border-width:1px;border-style:dashed;border-color:var(--ghost-ring);' +
    'border-radius:' + (getComputedStyle(card).borderRadius || '0px');
  slot.style.width = card.offsetWidth + 'px';
  slot.style.height = card.offsetHeight + 'px';
  return slot;
}

// Переносит заглушку в потенциальный слот вставки: anchor — {el, side} из
// slotAnchor(); соседи сдвигаются естественным reflow сетки. Своя (отложенная)
// точка создания — в dragstart; перерисовка во время перетаскивания уносит
// заглушку из DOM — в этом случае её не воссоздаём (drag продолжится без
// заглушки, дроп всё равно сработает).
function moveGhostSlot(anchor) {
  if (!dragSourceUrl || !anchor || !anchor.el) return;
  if (!dragGhostSlot) return;
  if (!dragGhostSlot.isConnected) { dragGhostSlot = null; return; }
  if (anchor.side === 'before') anchor.el.before(dragGhostSlot);
  else anchor.el.after(dragGhostSlot);
}

function removeGhostSlot() {
  if (dragGhostSlot && dragGhostSlot.isConnected) dragGhostSlot.remove();
  dragGhostSlot = null;
}

// Видимые карточки для расчёта зазора: перетаскиваемая карточка
// исключается (она скрыта во время перетаскивания; сетка уже закрыла её слот)
function visibleCards() {
  return [...document.querySelectorAll('#tabs-list .tab-card')]
    .filter(c => c !== dragSourceCardEl && c.style.display !== 'none');
}

// Gap index = how many visible cards the cursor has "passed" (multi-row grid:
// a card is passed when cursor Y is below its bottom, or cursor is on the
// card's row and right of its horizontal center)
function cardGapIndex(clientX, clientY) {
  let idx = 0;
  for (const c of visibleCards()) {
    const r = c.getBoundingClientRect();
    const onRow = clientY >= r.top && clientY <= r.bottom;
    if (clientY > r.bottom || (onRow && clientX > r.left + r.width / 2)) idx++;
  }
  return idx;
}

// Секция вкладки по данным: groupId или null (негрупповая)
function tabGroupOf(t) {
  return t && t.groupId ? t.groupId : null;
}

// Шапка секции, стоящая перед карточкой в списке: .gbar (группа) или
// .loose-label (негрупповая секция); null — карточка в начале списка
function sectionHeaderBefore(card) {
  let el = card.previousElementSibling;
  while (el && !el.classList.contains('gbar') && !el.classList.contains('loose-label'))
    el = el.previousElementSibling;
  return el;
}

// Секция секционной шапки: .gbar — её groupId; .loose-label — null
function headerSection(header) {
  return header && header.classList.contains('gbar') ? (header.dataset.groupId || null) : null;
}

// Позиция заглушки с учётом секций: плоский gap-индекс + Y курсора →
// {el, side}. На границе секций (карточка — первая своей секции, перед ней
// шапка): курсор НИЖЕ середины шапки — начало этой секции (заглушка после
// шапки), ВЫШЕ — конец предыдущей (заглушка до шапки). Остальные позиции —
// перед карточкой / после последней видимой.
function slotAnchor(idx, clientY) {
  const cards = visibleCards();
  if (!cards.length) return null;
  if (idx <= 0) return { el: cards[0], side: 'before' };
  if (idx >= cards.length) return { el: cards[cards.length - 1], side: 'after' };
  const card = cards[idx];
  const header = sectionHeaderBefore(card);
  if (header && tabGroupOf(card.__tab) !== tabGroupOf(cards[idx - 1].__tab)) {
    const r = header.getBoundingClientRect();
    const below = clientY == null || clientY > r.top + r.height / 2;
    return { el: header, side: below ? 'after' : 'before' };
  }
  return { el: card, side: 'before' };
}

// Секция позиции заглушки (groupId или null): карточка — группа её вкладки;
// «после» шапки — секция шапки; «до» шапки — секция карточки, стоящей
// перед шапкой.
function slotSection(anchor) {
  if (anchor.el.classList.contains('tab-card')) return tabGroupOf(anchor.el.__tab);
  if (anchor.side === 'after') return headerSection(anchor.el);
  let prev = anchor.el.previousElementSibling;
  while (prev && !prev.classList.contains('tab-card')) prev = prev.previousElementSibling;
  return prev ? tabGroupOf(prev.__tab) : null;
}

// Первая/последняя вкладка секции в ПОЛНОМ массиве (секция = активное
// пространство + groupId; null — «Без группы»)
function sectionTabFull(section, last) {
  const inSec = allTabs.filter(t => t.spaceId === activeSpaceId && tabGroupOf(t) === section);
  return inSec.length ? inSec[last ? inSec.length - 1 : 0] : null;
}

// Дроп в позицию заглушки: вкладка встаёт в ПОЛНОМ allTabs на позицию слота —
// перед/после якорной вкладки (конец секции — после последней вкладки секции,
// конец списка — в конец) — и получает groupId секции слота (null — «Без
// группы»); spaceId не меняется. Same slot (позиция и группа те же) — no-op.
function placeCardToSlot(src, anchor) {
  if (!anchor || !anchor.el) return;
  const from = allTabs.indexOf(src);
  if (from === -1) return;
  const section = slotSection(anchor);
  let anchorUrl, side = anchor.side;
  if (anchor.el.classList.contains('tab-card') && anchor.side === 'before') {
    anchorUrl = anchor.el.__tab.url;               // перед видимой карточкой X
  } else if (anchor.el.classList.contains('tab-card')) {
    const t = sectionTabFull(section, true);       // конец секции (= конец списка)
    if (!t) return;
    anchorUrl = t.url; side = 'after';
  } else if (anchor.side === 'after') {
    const t = sectionTabFull(section, false);      // начало секции
    if (!t) return;
    anchorUrl = t.url; side = 'before';
  } else {
    const t = sectionTabFull(section, true);       // конец предыдущей секции
    if (!t) return;
    anchorUrl = t.url; side = 'after';
  }
  const anchorIndex = allTabs.findIndex(t => t.url === anchorUrl);
  if (anchorIndex === -1) return;
  let a = anchorIndex > from ? anchorIndex - 1 : anchorIndex;
  const finalAt = side === 'before' ? a : Math.min(a + 1, allTabs.length - 1);
  if (finalAt === from && section === tabGroupOf(src)) return;
  chrome.runtime.sendMessage({ action: 'place-tab', index: from, anchorIndex, side, groupId: section });
}

// Глобальные dragover/drop: нативный drag-образ браузера следует за курсором,
// заглушка — в ближайшую позицию вставки (с учётом секций). Свою семантику дропа
// карточки сохранил только чип пространства (и свой обработчик drop);
// шапка группы — только reorder — над обоими заглушка просто стоит.
document.addEventListener('dragover', (e) => {
  if (!dragSourceUrl || dragSourceGroupId || !e.dataTransfer) return;
  const t = e.target;
  const overSpecial = t && t.closest && (t.closest('.gbar') || t.closest('.space-chip') || t.closest('.group-empty-slot'));
  if (overSpecial || !tabsList.contains(t)) return;
  moveGhostSlot(slotAnchor(cardGapIndex(e.clientX, e.clientY), e.clientY));
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
});

document.addEventListener('drop', (e) => {
  if (!dragSourceUrl || dragSourceGroupId || !e.dataTransfer) return;
  const t = e.target;
  if (!t || !tabsList.contains(t)) return;
  if (t.closest && t.closest('.gbar')) return; // дроп на шапку группы — карточка не переезжает через неё
  if (t.closest && t.closest('.group-empty-slot')) return; // слот пустой группы — свой обработчик шлёт, глобальный не должен
  const src = allTabs.find(tb => tb.url === dragSourceUrl);
  if (!src) return;
  e.preventDefault();
  placeCardToSlot(src, slotAnchor(cardGapIndex(e.clientX, e.clientY), e.clientY));
  removeGhostSlot();
});

// 'before'/'after' — по позиции курсора относительно середины элемента
function reorderSide(card, clientY) {
  const rect = card.getBoundingClientRect();
  return (clientY == null || clientY <= rect.top + rect.height / 2) ? 'before' : 'after';
}

// Двойной клик по имени → инлайн-переименование
function startRename(tab, nameEl, body) {
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'tab-name-input';
  input.value = tab.name;
  input.autocomplete = 'off';
  nameEl.replaceWith(input);
  input.focus();
  input.select();

  let done = false;
  const finish = (save) => {
    if (done) return;
    done = true;
    const newName = input.value.trim();
    if (save && newName && newName !== tab.name) {
      chrome.runtime.sendMessage({ action: 'rename-tab', index: allTabs.indexOf(tab), name: newName });
    }
    renderTabs(searchInput.value);
  };

  input.addEventListener('click', (e) => e.stopPropagation());
  input.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Enter') finish(true);
    if (e.key === 'Escape') finish(false);
  });
  input.addEventListener('blur', () => finish(true));
}

// === Массовое открытие ===

function updateSelectionBar() {
  const n = selectedUrls.size;
  selectionBar.classList.toggle('hidden', n === 0);
  selectionCount.textContent = `${n} выбрано`;
}

// «Выбрать» — toggle: выбрать все видимые / снять выбор с видимых
selectBtn.addEventListener('click', () => {
  const visible = visibleTabs(searchInput.value);
  const allSelected = visible.length > 0 && visible.every(t => selectedUrls.has(t.url));
  visible.forEach(t => allSelected ? selectedUrls.delete(t.url) : selectedUrls.add(t.url));
  renderTabs(searchInput.value);
});

openSelectedBtn.addEventListener('click', () => {
  const urls = allTabs.filter(t => selectedUrls.has(t.url)).map(t => t.url);
  openMany(urls);
});

clearSelectionBtn.addEventListener('click', () => {
  selectedUrls.clear();
  renderTabs(searchInput.value);
});

// «Сбросить фильтры» — в состоянии «ничего не найдено»
const btnResetFilters = document.getElementById('btn-reset-filters');
if (btnResetFilters) {
  btnResetFilters.addEventListener('click', () => {
    searchInput.value = '';
    activeUrl = null;
    renderTabs('');
  });
}

// Поиск
searchInput.addEventListener('input', (e) => {
  renderTabs(e.target.value);
});

// === Keyboard navigation ===
// Стрелки — по карточкам, Enter — открыть, Delete — удалить, Esc — сброс.
// Не перехватывает, пока набран текст или открыта модалка.

function isEditable(el) {
  if (!el) return false;
  const tag = (el.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
  return el.isContentEditable === true;
}

// Движение по видимым карточкам: +1 / -1 шаг
function moveActive(delta) {
  const f = visibleTabs(searchInput.value);
  if (!f.length) return;
  let i = activeUrl ? f.findIndex(t => t.url === activeUrl) : -1;
  if (i === -1) i = delta < 0 ? f.length - 1 : 0; // нет активной → крайняя по направлению
  else i = (i + delta + f.length) % f.length; // зациклено
  activeUrl = f[i].url;
  renderTabs(searchInput.value);
}

function openActiveTab() {
  const f = visibleTabs(searchInput.value);
  const t = f.find(t => t.url === activeUrl) || f[0];
  if (t) openUrl(t.url);
}

function deleteActiveTab() {
  const f = visibleTabs(searchInput.value);
  const t = f.find(t => t.url === activeUrl);
  if (!t) return;
  if (!confirm(`Удалить вкладку "${t.name}"?`)) return;
  allTabs.splice(allTabs.indexOf(t), 1);
  chrome.storage.sync.set({ 'blattam-tabs': allTabs });
  renderTabs(searchInput.value); // onChanged-обработчик обнулит activeUrl, если карточки не осталось
}

document.addEventListener('keydown', (e) => {
  // Модалка работает сама — не перехватываем
  if (spaceModal.classList.contains('open')) return;
  if (isAnyModalOpen()) return;

  // Esc — сброс: поиск, выбор и активная карточка (активное пространство НЕ
  // сбрасывается — нет «Все», к которому можно вернуться). Работает и из поля
  // (например, из поиска) — очищает его и снимает фокус.
  if (e.key === 'Escape') {
    if (searchInput.value) searchInput.value = '';
    const ae = document.activeElement;
    if (ae && ae !== document.body) ae.blur();
    activeUrl = null;
    selectedUrls.clear();
    renderTabs('');
    e.preventDefault();
    return;
  }

  // Остальные клавиши не перехватываем, пока набирается текст
  if (isEditable(document.activeElement)) return;

  switch (e.key) {
    case 'ArrowDown':
    case 'ArrowRight':
      e.preventDefault();
      moveActive(1);
      break;
    case 'ArrowUp':
    case 'ArrowLeft':
      e.preventDefault();
      moveActive(-1);
      break;
    case 'Enter':
      e.preventDefault();
      openActiveTab();
      break;
    case 'Delete':
    case 'Backspace':
      e.preventDefault();
      deleteActiveTab();
      break;
  }
});

// === Автообновление ===

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== 'sync') return;

  if (changes['blattam-tabs']) {
    const newTabs = changes['blattam-tabs'].newValue || [];
    const oldTabs = changes['blattam-tabs'].oldValue || [];
    // Реордер (набор URL тот же, изменился только порядок) — выбор и активная
    // карточка завязаны на URL, поэтому переживают перерисовку
    const sameUrlSet = oldTabs.length === newTabs.length &&
      oldTabs.map(t => t.url).sort().join('|') === newTabs.map(t => t.url).sort().join('|');
    allTabs = newTabs;
    if (!sameUrlSet) selectedUrls.clear(); // набор вкладок изменился — сброс выбора
    renderTabs(searchInput.value);
  }
  if (changes['blattam-spaces']) {
    const newSpaces = changes['blattam-spaces'].newValue || [];
    allSpaces = newSpaces;
    // Активное пространство удалено (например, из другого окна) — переключаемся на первое
    if (!allSpaces.some(s => s.id === activeSpaceId) && allSpaces.length > 0) {
      activeSpaceId = allSpaces[0].id;
      chrome.storage.sync.set({ 'blattam-last-space': activeSpaceId });
    }
    renderSpaces();
    renderTabs(searchInput.value);
  }
  if (changes['blattam-groups']) {
    allGroups = changes['blattam-groups'].newValue || [];
    renderTabs(searchInput.value);
  }
});

// === Экспорт / Импорт (с пространствами и группами) ===

document.getElementById('export-btn').addEventListener('click', () => {
  const data = {
    'blattam-toby': true,
    version: chrome.runtime.getManifest().version,
    exported: new Date().toISOString(),
    spaces: allSpaces,
    groups: allGroups,
    tabs: allTabs
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  a_click(url, `blattam-toby-backup-${new Date().toISOString().slice(0, 10)}.json`);
  URL.revokeObjectURL(url);
});

function a_click(url, download) {
  const a = document.createElement('a');
  a.href = url;
  a.download = download;
  a.click();
}

document.getElementById('import-btn').addEventListener('click', () => {
  document.getElementById('import-input').click();
});

document.getElementById('import-input').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (event) => {
    try {
      const data = JSON.parse(event.target.result);

      if (!data.tabs || !Array.isArray(data.tabs)) {
        alert('Неверный формат файла: отсутствует массив tabs');
        return;
      }

      // Файл без spaces/groups, но с legacy-«folders» — прогоняем ту же миграцию
      // папки → пространства перед слиянием (старые экспорты остаются импортируемыми)
      let fileSpaces = Array.isArray(data.spaces) ? data.spaces : null;
      let fileGroups = Array.isArray(data.groups) ? data.groups : [];
      const fileTabs = data.tabs;
      if (fileSpaces === null && (Array.isArray(data.folders) || fileTabs.some(t => t && t.folderId != null))) {
        fileSpaces = [];
        migrateFoldersToSpaces(fileTabs, fileSpaces, data.folders);
      }

      // Пространства: дедупликация по имени (свои сохраняются), remap id для вкладок/групп
      const spaceIdByName = new Map(allSpaces.map(s => [String(s.name).toLowerCase(), s.id]));
      const spaceIdRemap = new Map();
      let newSpaces = 0;
      (fileSpaces || []).forEach(s => {
        if (!s || !s.name) return;
        const key = String(s.name).toLowerCase();
        if (!spaceIdByName.has(key)) {
          const sp = { id: s.id || genId('sp'), name: s.name };
          allSpaces.push(sp);
          spaceIdByName.set(key, sp.id);
          newSpaces++;
        }
        spaceIdRemap.set(s.id, spaceIdByName.get(key));
      });
      const fallbackSpaceId = allSpaces[0] ? allSpaces[0].id : null;

      // Группы: дедупликация по имени, spaceId — через spaceIdRemap
      const groupIdByName = new Map(allGroups.map(g => [String(g.name).toLowerCase(), g.id]));
      const groupIdRemap = new Map();
      let newGroups = 0;
      (fileGroups || []).forEach(g => {
        if (!g || !g.name) return;
        const key = String(g.name).toLowerCase();
        if (!groupIdByName.has(key)) {
          const ng = {
            id: g.id || genId('g'),
            name: g.name,
            spaceId: spaceIdRemap.get(g.spaceId) || fallbackSpaceId,
            collapsed: !!g.collapsed
          };
          allGroups.push(ng);
          groupIdByName.set(key, ng.id);
          newGroups++;
        }
        groupIdRemap.set(g.id, groupIdByName.get(key));
      });

      const importedTabs = fileTabs.filter(t => t && t.url && t.name);
      const duplicates = importedTabs.filter(t => allTabs.some(existing => existing.url === t.url)).length;
      const newCount = importedTabs.length - duplicates;

      if (!confirm(
        `В файле: пространств — ${(fileSpaces || []).length} (+${newSpaces} новых), ` +
        `групп — ${(fileGroups || []).length} (+${newGroups} новых), ` +
        `вкладок — ${importedTabs.length} (новых: ${newCount}, дубликатов: ${duplicates})\n\nИмпортировать?`
      )) {
        return;
      }

      importedTabs.forEach(t => {
        if (allTabs.some(existing => existing.url === t.url)) return; // дубль по URL
        t.spaceId = spaceIdRemap.get(t.spaceId) || fallbackSpaceId;
        if (t.groupId) t.groupId = groupIdRemap.get(t.groupId) || null;
        delete t.folderId; // legacy-поле — больше не хранится
        allTabs.push(t);
      });

      chrome.storage.sync.set({
        'blattam-tabs': allTabs,
        'blattam-spaces': allSpaces,
        'blattam-groups': allGroups
      });
    } catch (err) {
      alert('Ошибка чтения файла: невалидный JSON');
    }
  };
  reader.readAsText(file);
  e.target.value = '';
});

// === Start ===
loadData();

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

// Шапка группы: полноширинная (grid-column 1/-1), chevron + имя + mono-счётчик
// + «✕». Всегда видна; клик — свернуть/развернуть (карточки уходят из DOM,
// счётчик на шапке остаётся). Состояние сворачивания — в данных
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

  bar.appendChild(chev);
  bar.appendChild(name);
  bar.appendChild(count);
  bar.appendChild(del);

  // DnD-источник: шапку можно перетащить на другую шапку (reorder групп
  // внутри пространства). Пейлоад: id группы (у карточки — индекс вкладки).
  bar.draggable = true;
  bar.addEventListener('dragstart', (e) => {
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

  // DnD: бар группы принимает перетаскиваемую карточку — вкладка уходит в
  // группу (drop-over); ЛИБО другую шапку — reorder (2px-индикатор до/после)
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
    bar.classList.add('drop-over');
  });
  bar.addEventListener('dragleave', () => bar.classList.remove('drop-over', 'drop-before', 'drop-after'));
  bar.addEventListener('drop', (e) => {
    e.preventDefault();
    bar.classList.remove('drop-over', 'drop-before', 'drop-after');
    if (dragSourceGroupId) {
      reorderGroups(dragSourceGroupId, g.id, reorderSide(bar, e.clientY));
      return;
    }
    const idx = parseInt(e.dataTransfer.getData('text/plain'), 10);
    const tab = allTabs[idx];
    if (tab) moveTabTo(tab, undefined, g.id);
  });

  bar.addEventListener('click', () => toggleGroupCollapsed(g.id));
  tabsList.appendChild(bar);
}

// Сворачивание группы: запись в blattam-groups → onChanged → перерисовка.
// Пишем только при реальном переключении.
function toggleGroupCollapsed(groupId) {
  const g = allGroups.find(x => x.id === groupId);
  if (!g) return;
  g.collapsed = !g.collapsed;
  chrome.storage.sync.set({ 'blattam-groups': allGroups });
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

  // Hover-контролы — absolute, привязаны к карточке
  card.appendChild(selectCb);
  card.appendChild(deleteBtn);

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

  // Клик по карточке — открыть вкладку + снять выбор
  card.addEventListener('click', () => {
    openUrl(tab.url);
  });

  // Drag & drop: карточку можно перетащить на чип пространства (переместить)
  // или на другую карточку (перестановка — см. attachCardReorderDrop)
  card.draggable = true;
  card.addEventListener('dragstart', (e) => {
    e.dataTransfer.setData('text/plain', String(allTabs.indexOf(tab)));
    e.dataTransfer.effectAllowed = 'move';
    dragSourceUrl = tab.url;
    card.classList.add('dragging');
  });
  card.addEventListener('dragend', () => {
    dragSourceUrl = null;
    card.classList.remove('dragging');
    clearReorderIndicators();
    document.querySelectorAll('.space-chip.drag-over').forEach(c => c.classList.remove('drag-over'));
    document.querySelectorAll('.gbar.drop-over').forEach(b => b.classList.remove('drop-over'));
  });
  attachCardReorderDrop(card, tab);

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
      sGroups.forEach(g => appendGroupBar(g, 0));
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

// === Drag & drop: перестановка карточек (reorder) ===
// Карточка принимает перетаскиваемую карточку: верхняя половина — вставить
// перед, нижняя — после. Меняется только порядок в 'blattam-tabs' (spaceId/groupId
// не трогается); работает в любом фильтре — позиция считается по полному массиву.

// Снимаем индикаторы reorder со всех карточек
function clearReorderIndicators() {
  document.querySelectorAll('.tab-card.drop-before, .tab-card.drop-after')
    .forEach(c => c.classList.remove('drop-before', 'drop-after'));
}

// 'before'/'after' — по позиции курсора относительно середины карточки
function reorderSide(card, clientY) {
  const rect = card.getBoundingClientRect();
  return (clientY == null || clientY <= rect.top + rect.height / 2) ? 'before' : 'after';
}

// Карточка принимает другую карточку (drop на себя — no-op)
function attachCardReorderDrop(card, tab) {
  card.addEventListener('dragover', (e) => {
    if (!e.dataTransfer || !dragSourceUrl) return;
    const src = allTabs.find(t => t.url === dragSourceUrl);
    if (!src || src === tab) return; // на себя — не целевая
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const side = reorderSide(card, e.clientY);
    card.classList.toggle('drop-before', side === 'before');
    card.classList.toggle('drop-after', side === 'after');
  });
  card.addEventListener('dragleave', () => card.classList.remove('drop-before', 'drop-after'));
  card.addEventListener('drop', (e) => {
    e.preventDefault();
    card.classList.remove('drop-before', 'drop-after');
    if (!e.dataTransfer) return;
    const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
    const src = allTabs[from];
    if (!src || src.url !== dragSourceUrl || src === tab) return; // drop on себя / устаревший индекс — no-op
    chrome.runtime.sendMessage({
      action: 'reorder-tab', fromIndex: from, toIndex: allTabs.indexOf(tab), side: reorderSide(card, e.clientY)
    });
  });
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

const tabsList = document.getElementById('tabs-list');
const emptyState = document.getElementById('empty-state');
const searchInput = document.getElementById('search');
const noResults = document.getElementById('no-results');
const foldersBar = document.getElementById('folders-bar');
const addFolderBtn = document.getElementById('add-folder-btn');

// === Тема (тёмная/светлая) ===
// Состояние — в chrome.storage.local, ключ 'blattam-theme' ('dark'/'light'),
// по умолчанию светлая. Применяем сохранённую тему ДО первого рендера
// (loadData() вызывается в конце файла) — чтобы страница не мигала.

const themeBtn = document.getElementById('theme-btn');

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  themeBtn.textContent = theme === 'dark' ? '☀️' : '🌙';
}

chrome.storage.local.get(['blattam-theme'], (result) => {
  applyTheme(result['blattam-theme'] === 'dark' ? 'dark' : 'light');
});

themeBtn.addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  chrome.storage.local.set({ 'blattam-theme': next });
});

// === Размер карточек (крупный/компактный) ===
// Состояние — в chrome.storage.local, ключ 'blattam-card-size' ('large'/'compact'),
// по умолчанию 'large'. Применяем сохранённый размер ДО первого рендера
// (тот же паттерн, что тема — без мигания). Esc НЕ сбрасывает размер —
// это постоянная настройка, а не фильтры.

const sizeBtn = document.getElementById('size-btn');

function applyCardSize(size) {
  const compact = size === 'compact';
  document.body.classList.toggle('compact-cards', compact);
  sizeBtn.textContent = compact ? '▤ Компактные' : '▦ Крупные';
  sizeBtn.title = compact ? 'Крупные карточки' : 'Компактные карточки';
}

chrome.storage.local.get(['blattam-card-size'], (result) => {
  applyCardSize(result['blattam-card-size'] === 'compact' ? 'compact' : 'large');
});

sizeBtn.addEventListener('click', () => {
  const next = document.body.classList.contains('compact-cards') ? 'large' : 'compact';
  applyCardSize(next);
  chrome.storage.local.set({ 'blattam-card-size': next });
});

// === Скриншоты вкладок ===
// Миниатюры живут в chrome.storage.local под ключом 'blattam-screenshots'
// ({ tabId: dataUrl }); вкладки хранят только hasScreenshot. Загружаем
// лениво после первого рендера и перерисовываем карточки.

const SCREENSHOTS_KEY = 'blattam-screenshots';
let screenshots = {}; // { tabId: dataUrl }

function loadScreenshots() {
  chrome.storage.local.get([SCREENSHOTS_KEY], (result) => {
    screenshots = result[SCREENSHOTS_KEY] || {};
    renderTabs(searchInput.value);
  });
}

// Чистим скриншот удалённой вкладки (view удаляет вкладки напрямую в
// storage.sync, поэтому и скриншот чистим здесь — single source в view-путях)
function removeTabScreenshot(tab) {
  const id = tab && tab.id;
  if (id == null) return;
  delete screenshots[id];
  chrome.storage.local.get([SCREENSHOTS_KEY], (result) => {
    const shots = result[SCREENSHOTS_KEY] || {};
    if (id in shots) {
      delete shots[id];
      chrome.storage.local.set({ [SCREENSHOTS_KEY]: shots });
    }
  });
}

// Модалка
const folderModal = document.getElementById('folder-modal');
const modalTitle = document.getElementById('modal-title');
const folderNameInput = document.getElementById('folder-name-input');
const modalCancel = document.getElementById('modal-cancel');
const modalConfirm = document.getElementById('modal-confirm');

let allTabs = [];
let allFolders = [];
let allTags = [];
let allSessions = [];        // сессии: { id, name, createdAt, tabUrls }
let openStats = {};          // статистика открытий: { url: { opens, lastOpened } } (local)
let activeFolderId = ''; // '' = "Все"
let activeTagId = '';   // '' = без фильтра по тегу
let activeSessionId = ''; // '' = без фильтра по сессии
let archiveOnly = false;  // фильтр «Архив» — только архив закрытых вкладок
let activeSpecial = '';   // '' | 'frequent' | 'favorites' — активный фильтр рекомендаций
let modalCallback = null;
let selectedUrls = new Set(); // выбор вкладок для массового открытия
let activeUrl = null; // карточка, выбранная клавиатурой (по URL — переживает перерисовку)
let openTagDropdownUrl = null; // чья карточка держит открытый дропдаун тегов (по URL — переживает перерисовку)
let openModalId = null; // id открытой модалки — чтобы глобальный keydown её не перехватывал

// Отмечаем открытую/закрытую модалку (для global keydown-гарда)
function setModalOpen(id) {
  openModalId = id || null;
}

function isAnyModalOpen() {
  return openModalId !== null;
}

// === Загрузка данных ===

function loadData() {
  chrome.storage.sync.get(['blattam-tabs', 'blattam-folders', 'blattam-tags', 'blattam-sessions'], (result) => {
    allTabs = result['blattam-tabs'] || [];
    allFolders = result['blattam-folders'] || [];
    allTags = result['blattam-tags'] || [];
    allSessions = result['blattam-sessions'] || [];
    // Статистика открытий — в local (per-device, не sync)
    chrome.storage.local.get(['blattam-stats'], (local) => {
      openStats = local['blattam-stats'] || {};
    });
    renderFolders();
    renderTags();
    renderSessions();
    renderTabs();
    loadScreenshots(); // скриншоты (local) — после первого рендера, потом перерисовка
  });
}

// === Папки ===

function renderFolders() {
  // Удаляем старые чипы (только user folders, не "Все" и не спец-фильтры)
  foldersBar.querySelectorAll('.folder-chip[data-folder-id]:not([data-folder-id=""])').forEach(el => el.remove());
  
  allFolders.forEach(folder => {
    const isNested = folder.parentId != null;
    const chip = document.createElement('button');
    chip.className = 'folder-chip' + (activeFolderId === folder.id ? ' active' : '') + (isNested ? ' nested' : '');
    chip.dataset.folderId = folder.id;
    
    // Иконка папки + имя (вложенные — с «↳»)
    const icon = document.createElement('span');
    icon.textContent = isNested ? '↳' : '📁';
    chip.appendChild(icon);
    
    const name = document.createElement('span');
    name.className = 'chip-name';
    name.textContent = folder.name;
    chip.appendChild(name);
    
    // Действия (✏️ 🗑️)
    const actions = document.createElement('div');
    actions.className = 'chip-actions';
    
    const renameBtn = document.createElement('button');
    renameBtn.className = 'chip-icon-btn';
    renameBtn.textContent = '✎';
    renameBtn.title = 'Переименовать';
    renameBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      openRenameModal(folder.id, folder.name);
    });
    
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'chip-icon-btn';
    deleteBtn.textContent = '✕';
    deleteBtn.title = 'Удалить папку';
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm(`Удалить папку "${folder.name}"? Вкладки переместятся в "Все".`)) {
        chrome.runtime.sendMessage({ action: 'delete-folder', id: folder.id });
      }
    });
    
    actions.appendChild(renameBtn);
    actions.appendChild(deleteBtn);
    chip.appendChild(actions);

    // DnD: чип принимает перетаскиваемую карточку
    attachFolderDrop(chip, folder.id);
    
    // Клик — фильтр по папке
    chip.addEventListener('click', () => {
      activeFolderId = folder.id;
      renderFolders(); // обновить active state
      renderTabs(searchInput.value);
    });
    
    foldersBar.insertBefore(chip, addFolderBtn);
  });
  
  // Обновляем "Все" и спец-фильтры (архив/рекомендации)
  const allChip = foldersBar.querySelector('.folder-chip[data-folder-id=""]');
  if (allChip) {
    allChip.className = 'folder-chip' + (activeFolderId === '' && !archiveOnly && activeSpecial === '' ? ' active' : '');
  }
  markSpecialChipActive();
}

// "+ " — создать папку
addFolderBtn.addEventListener('click', () => openCreateModal());

// Модалка: создать папку
function openCreateModal() {
  modalTitle.textContent = 'Новая папка';
  folderNameInput.value = '';
  showFolderModal((name) => {
    chrome.runtime.sendMessage({ action: 'create-folder', name });
  });
}

// Модалка: переименовать папку
function openRenameModal(folderId, currentName) {
  modalTitle.textContent = 'Переименовать папку';
  folderNameInput.value = currentName;
  showFolderModal((name) => {
    if (name !== currentName) {
      chrome.runtime.sendMessage({ action: 'rename-folder', id: folderId, name });
    }
  });
}

function showFolderModal(onConfirm) {
  modalCallback = onConfirm;
  folderModal.classList.add('open');
  setModalOpen('folder');
  setTimeout(() => folderNameInput.focus(), 50);
}

modalCancel.addEventListener('click', closeFolderModal);
folderModal.addEventListener('click', (e) => {
  if (e.target === folderModal) closeFolderModal();
});

function closeFolderModal() {
  folderModal.classList.remove('open');
  modalCallback = null;
  setModalOpen(null);
}

modalConfirm.addEventListener('click', () => {
  const name = folderNameInput.value.trim();
  if (!name) return;
  if (modalCallback) modalCallback(name);
  closeFolderModal();
});

folderNameInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') modalConfirm.click();
  if (e.key === 'Escape') modalCancel.click();
});

// "Все" чип — клик сбрасывает фильтр (возврат к обычному виду)
foldersBar.querySelector('.folder-chip[data-folder-id=""]').addEventListener('click', () => {
  activeFolderId = '';
  renderFolders();
  renderTabs(searchInput.value);
});

// === Теги (цветовые метки) ===

const TAGS_PALETTE = 6; // количество цветов (токены --tag-1..6 в theme.css)
const tagsBar = document.getElementById('tags-bar');
const addTagBtn = document.getElementById('add-tag-btn');
const tagModal = document.getElementById('tag-modal');
const tagNameInput = document.getElementById('tag-name-input');
const tagColorPalette = document.getElementById('tag-color-palette');
const tagModalCancel = document.getElementById('tag-modal-cancel');
const tagModalConfirm = document.getElementById('tag-modal-confirm');
let selectedTagColor = 1;

// Палитра цветов в модалке (кружки с токенами --tag-N)
function buildTagPalette() {
  tagColorPalette.innerHTML = '';
  for (let i = 1; i <= TAGS_PALETTE; i++) {
    const swatch = document.createElement('button');
    swatch.type = 'button';
    swatch.className = 'tag-swatch' + (i === selectedTagColor ? ' selected' : '');
    swatch.dataset.color = i;
    swatch.title = 'Цвет ' + i;
    swatch.addEventListener('click', () => {
      selectedTagColor = i;
      tagColorPalette.querySelectorAll('.tag-swatch').forEach(s => s.classList.toggle('selected', s === swatch));
    });
    tagColorPalette.appendChild(swatch);
  }
}

function openTagCreateModal() {
  tagNameInput.value = '';
  selectedTagColor = 1;
  buildTagPalette();
  tagModal.classList.add('open');
  setModalOpen('tag');
  setTimeout(() => tagNameInput.focus(), 50);
}

addTagBtn.addEventListener('click', openTagCreateModal);
tagModalCancel.addEventListener('click', closeTagModal);
tagModal.addEventListener('click', (e) => {
  if (e.target === tagModal) closeTagModal();
});

function closeTagModal() {
  tagModal.classList.remove('open');
  setModalOpen(null);
}

tagModalConfirm.addEventListener('click', () => {
  const name = tagNameInput.value.trim();
  if (!name) return;
  chrome.runtime.sendMessage({ action: 'create-tag', name, color: selectedTagColor });
  closeTagModal();
});

tagNameInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') tagModalConfirm.click();
  if (e.key === 'Escape') tagModalCancel.click();
});

// Ряд чипов тегов (клик — фильтр, ✕ — удалить)
function renderTags() {
  tagsBar.querySelectorAll('.tag-chip').forEach(el => el.remove());
  
  allTags.forEach(tag => {
    const chip = document.createElement('button');
    chip.className = 'tag-chip' + (activeTagId === tag.id ? ' active' : '');
    chip.dataset.tagId = tag.id;
    
    const dot = document.createElement('span');
    dot.className = 'tag-dot';
    dot.dataset.color = tag.color;
    chip.appendChild(dot);
    
    const name = document.createElement('span');
    name.className = 'chip-name';
    name.textContent = tag.name;
    chip.appendChild(name);
    
    // ✕ — удалить тег (с confirm; tagIds у вкладок очищает background.js)
    const actions = document.createElement('div');
    actions.className = 'chip-actions';
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'chip-icon-btn';
    deleteBtn.textContent = '✕';
    deleteBtn.title = 'Удалить тег';
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm(`Удалить тег "${tag.name}"?`)) {
        if (activeTagId === tag.id) activeTagId = '';
        chrome.runtime.sendMessage({ action: 'delete-tag', id: tag.id });
      }
    });
    actions.appendChild(deleteBtn);
    chip.appendChild(actions);
    
    // Клик — фильтр по тегу (повторный клик снимает)
    chip.addEventListener('click', () => {
      activeTagId = activeTagId === tag.id ? '' : tag.id;
      renderTags();
      renderTabs(searchInput.value);
    });
    
    tagsBar.insertBefore(chip, addTagBtn);
  });
}

// Цветная точка тега (data-color → --tag-N в CSS)
function makeTagDot(tag) {
  const dot = document.createElement('span');
  dot.className = 'card-tag-dot';
  dot.dataset.color = tag.color;
  dot.title = tag.name;
  return dot;
}

// === Открытие вкладок (единый путь: background создаёт browser-tab и
// считает статистику 'blattam-stats' — view сам не делает chrome.tabs.create) ===

// Открыть одну вкладку: background создаёт browser-tab и инкрементит 'blattam-stats'
function openUrl(url) {
  chrome.runtime.sendMessage({ action: 'open-one', url });
  selectedUrls.delete(url);
  renderTabs(searchInput.value);
}

// Массовое открытие: background открывает каждую вкладку (неактивно) + статистика
function openMany(urls) {
  chrome.runtime.sendMessage({ action: 'open-many', urls: urls });
  selectedUrls.clear();
  renderTabs(searchInput.value);
}

// === Архив закрытых + Рекомендации (спец-фильтры) ===
// Три чипа в ряд папок: «Архив» (только archivedAt), «⭐ Частые» (top-20 by
// opens, opens >= 2), «🕘 Избранные» (top-10 by lastOpened за 7 дней).
// Они взаимоисключающие; «Все» возвращает обычный вид.

const archiveChip = document.getElementById('archive-chip');
const frequentChip = document.getElementById('frequent-chip');
const favoritesChip = document.getElementById('favorites-chip');

function clearSpecials() {
  archiveOnly = false;
  activeSpecial = '';
}

function markSpecialChipActive() {
  if (archiveChip) archiveChip.classList.toggle('active', archiveOnly);
  if (frequentChip) frequentChip.classList.toggle('active', activeSpecial === 'frequent');
  if (favoritesChip) favoritesChip.classList.toggle('active', activeSpecial === 'favorites');
}

// Считаем рекомендации по свежей статистике (local может измениться
// фоном между рендерами): перечитываем 'blattam-stats' перед переключением
function withFreshStats(cb) {
  chrome.storage.local.get(['blattam-stats'], (local) => {
    openStats = local['blattam-stats'] || {};
    cb();
  });
}

if (archiveChip) {
  archiveChip.addEventListener('click', () => {
    archiveOnly = !archiveOnly;
    if (archiveOnly) activeSpecial = '';
    renderFolders();
    renderTabs(searchInput.value);
  });
}
if (frequentChip) {
  frequentChip.addEventListener('click', () => {
    withFreshStats(() => {
      activeSpecial = activeSpecial === 'frequent' ? '' : 'frequent';
      if (activeSpecial) archiveOnly = false;
      renderFolders();
      renderTabs(searchInput.value);
    });
  });
}
if (favoritesChip) {
  favoritesChip.addEventListener('click', () => {
    withFreshStats(() => {
      activeSpecial = activeSpecial === 'favorites' ? '' : 'favorites';
      if (activeSpecial) archiveOnly = false;
      renderFolders();
      renderTabs(searchInput.value);
    });
  });
}

// Наборы URL для рекомендаций (из openStats)
function frequentUrlSet() {
  const entries = Object.entries(openStats)
    .filter(([, v]) => (v.opens || 0) >= 2)
    .sort((a, b) => b[1].opens - a[1].opens);
  return new Set(entries.slice(0, 20).map(([url]) => url));
}

function favoritesUrlSet() {
  const now = Date.now();
  const week = 7 * 24 * 60 * 60 * 1000;
  const entries = Object.entries(openStats)
    .filter(([, v]) => (v.lastOpened || 0) >= now - week)
    .sort((a, b) => b[1].lastOpened - a[1].lastOpened);
  return new Set(entries.slice(0, 10).map(([url]) => url));
}

// === Сессии ===

const sessionsBar = document.getElementById('sessions-bar');
const addSessionBtn = document.getElementById('add-session-btn');
const sessionModal = document.getElementById('session-modal');
const sessionNameInput = document.getElementById('session-name-input');
const sessionModalCancel = document.getElementById('session-modal-cancel');
const sessionModalConfirm = document.getElementById('session-modal-confirm');

// Сессия — именованная группа сохранённых вкладок: { id, name, createdAt, tabUrls }.
// Хранится в chrome.storage.sync под ключом 'blattam-sessions'.

function saveSessions(sessions) {
  allSessions = sessions;
  chrome.storage.sync.set({ 'blattam-sessions': sessions });
  renderSessions();
}

function renderSessions() {
  if (!sessionsBar) return;
  sessionsBar.querySelectorAll('.session-chip').forEach(el => el.remove());
  allSessions.forEach(session => {
    const chip = document.createElement('button');
    chip.className = 'session-chip' + (activeSessionId === session.id ? ' active' : '');
    chip.dataset.sessionId = session.id;
    
    const icon = document.createElement('span');
    icon.textContent = '📋';
    chip.appendChild(icon);
    
    const name = document.createElement('span');
    name.className = 'chip-name';
    name.textContent = session.name;
    chip.appendChild(name);
    
    // Действия: + (добавить видимые) и ✕ (удалить сессию)
    const actions = document.createElement('div');
    actions.className = 'chip-actions';
    
    const addBtn = document.createElement('button');
    addBtn.className = 'chip-icon-btn';
    addBtn.textContent = '+';
    addBtn.title = 'Добавить видимые вкладки в сессию';
    addBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      addVisibleToSession(session.id);
    });
    
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'chip-icon-btn';
    deleteBtn.textContent = '✕';
    deleteBtn.title = 'Удалить сессию';
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm(`Удалить сессию "${session.name}"?`)) {
        if (activeSessionId === session.id) activeSessionId = '';
        saveSessions(allSessions.filter(s => s.id !== session.id));
        renderTabs(searchInput.value);
      }
    });
    
    actions.appendChild(addBtn);
    actions.appendChild(deleteBtn);
    chip.appendChild(actions);
    
    // Клик — фильтр по сессии (повторный клик снимает)
    chip.addEventListener('click', () => {
      activeSessionId = activeSessionId === session.id ? '' : session.id;
      renderSessions();
      renderTabs(searchInput.value);
    });
    
    sessionsBar.insertBefore(chip, addSessionBtn);
  });
}

// Подпись по умолчанию: «Сессия 21.10» (дата в формате ДД.ММ)
function defaultSessionName() {
  const d = new Date();
  const day = String(d.getDate()).padStart(2, '0');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  return `Сессия ${day}.${month}`;
}

// Модалка: создать сессию (захватывает ВСЕ сейчас видимые вкладки)
function openSessionCreateModal() {
  if (!sessionModal) return;
  sessionNameInput.value = '';
  sessionModal.classList.add('open');
  setModalOpen('session');
  setTimeout(() => sessionNameInput.focus(), 50);
}

addSessionBtn.addEventListener('click', openSessionCreateModal);
sessionModalCancel.addEventListener('click', closeSessionModal);
sessionModal.addEventListener('click', (e) => {
  if (e.target === sessionModal) closeSessionModal();
});

function closeSessionModal() {
  sessionModal.classList.remove('open');
  setModalOpen(null);
}

sessionModalConfirm.addEventListener('click', () => {
  const name = sessionNameInput.value.trim() || defaultSessionName();
  const visible = visibleTabs(searchInput.value);
  const session = {
    id: 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
    name,
    createdAt: Date.now(),
    tabUrls: visible.map(t => t.url)
  };
  saveSessions(allSessions.concat(session));
  closeSessionModal();
});

sessionNameInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sessionModalConfirm.click();
  if (e.key === 'Escape') sessionModalCancel.click();
});

// Добавить сейчас видимые вкладки в сессию (без дублей)
function addVisibleToSession(sessionId) {
  const session = allSessions.find(s => s.id === sessionId);
  if (!session) return;
  const visible = visibleTabs(searchInput.value);
  const urls = session.tabUrls.slice();
  visible.forEach(t => {
    if (!urls.includes(t.url)) urls.push(t.url);
  });
  const updated = allSessions.map(s => s.id === sessionId ? Object.assign({}, s, { tabUrls: urls }) : s);
  saveSessions(updated);
}

// === Карточки вкладок ===

function renderTabs(filter = '') {
  tabsList.innerHTML = '';
  
  // Фильтр по папке + поиску
  let filtered = visibleTabs(filter);
  // Если активная (клавиатурная) карточка не в видимом списке — сбрасываем
  if (activeUrl && !filtered.some(t => t.url === activeUrl)) activeUrl = null;
  
  if (allTabs.length === 0) {
    emptyState.style.display = 'block';
    noResults.style.display = 'none';
    renderSessions();
    return;
  }
  emptyState.style.display = 'none';
  
  let visibleCount = 0;
  
  filtered.forEach((tab) => {
    // Поиск по имени/title/URL
    if (filter && !matchFilter(tab, filter)) return;
    visibleCount++;

    const isArchived = tab.archivedAt != null;
    const card = document.createElement('div');
    card.className = 'tab-card'
      + (selectedUrls.has(tab.url) ? ' selected' : '')
      + (activeUrl === tab.url ? ' kbd-active' : '')
      + (isArchived ? ' archived' : '');
    
    // Header
    const header = document.createElement('div');
    header.className = 'tab-header';
    
    if (tab.favIconUrl) {
      const img = document.createElement('img');
      img.src = tab.favIconUrl;
      img.style.width = '16px';
      img.style.height = '16px';
      img.onerror = () => img.remove();
      header.appendChild(img);
    }
    
    // Чекбокс массового выбора
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
    header.appendChild(selectCb);
    
    // Цветные точки тегов вкладки
    const tagsWrap = document.createElement('span');
    tagsWrap.className = 'card-tags';
    (tab.tagIds || []).forEach(tagId => {
      const tag = allTags.find(t => t.id === tagId);
      if (tag) tagsWrap.appendChild(makeTagDot(tag));
    });
    header.appendChild(tagsWrap);
    
    const nameEl = document.createElement('span');
    nameEl.className = 'tab-name';
    nameEl.textContent = tab.name;
    nameEl.title = isArchived
      ? 'Двойной клик — переименовать (вкладка в архиве закрытых)'
      : 'Двойной клик — переименовать';

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
      startRename(tab, nameEl);
    });

    // Actions: переместить в папку + (архив) + теги + удалить
    const actions = document.createElement('div');
    actions.className = 'tab-actions';
    
    // Кнопка "переместить" (📁) — дропдаун папок
    const folderBtn = document.createElement('button');
    folderBtn.className = 'folder-select-btn';
    folderBtn.textContent = '📋';
    folderBtn.title = 'Переместить в папку';
    
    const dropdown = document.createElement('div');
    dropdown.className = 'folder-dropdown';
    
    // "Все" (null)
    const allItem = document.createElement('div');
    allItem.className = 'folder-dd-item all-folder';
    allItem.textContent = '→ Все';
    allItem.addEventListener('click', (e) => {
      e.stopPropagation();
      moveTab(tab, null);
      dropdown.classList.remove('open');
    });
    dropdown.appendChild(allItem);
    
    // Папки (иерархия: вложенные — с отступом и «↳»)
    const appendFolderItem = (folder, depth) => {
      const item = document.createElement('div');
      item.className = 'folder-dd-item' + (depth > 0 ? ' nested' : '');
      item.textContent = `→ ${depth > 0 ? '↳ ' : ''}${folder.name}`;
      if (tab.folderId === folder.id) item.style.fontWeight = 'bold';
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        moveTab(tab, folder.id);
        dropdown.classList.remove('open');
      });
      dropdown.appendChild(item);
      allFolders.filter(f => f.parentId === folder.id).forEach(child => appendFolderItem(child, depth + 1));
    };
    allFolders.filter(f => f.parentId == null).forEach(f => appendFolderItem(f, 0));
    
    folderBtn.appendChild(dropdown);
    folderBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const wasOpen = dropdown.classList.contains('open');
      document.querySelectorAll('.folder-dropdown.open').forEach(dd => dd.classList.remove('open'));
      openTagDropdownUrl = null; // открываем дропдаун папок — закрываем дропдаун тегов
      if (!wasOpen) dropdown.classList.add('open');
    });
    
    actions.appendChild(folderBtn);
    
    // Кнопка тегов (🎨) — дропдаун-чекбоксы (мультиселект тегов вкладки)
    const tagsBtn = document.createElement('button');
    tagsBtn.className = 'folder-select-btn';
    tagsBtn.textContent = '🎨';
    tagsBtn.title = 'Теги вкладки';
    
    const tagDropdown = document.createElement('div');
    tagDropdown.className = 'folder-dropdown tag-dropdown';
    
    if (allTags.length === 0) {
      const emptyItem = document.createElement('div');
      emptyItem.className = 'folder-dd-item all-folder';
      emptyItem.textContent = 'Нет тегов — создайте в «+ Тег»';
      tagDropdown.appendChild(emptyItem);
    } else {
      const tagIds = tab.tagIds || [];
      allTags.forEach(tag => {
        const item = document.createElement('label');
        item.className = 'tag-dd-item';
        
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = tagIds.includes(tag.id);
        cb.addEventListener('click', (e) => e.stopPropagation());
        cb.addEventListener('change', (e) => {
          e.stopPropagation();
          const next = tagIds.slice();
          if (cb.checked) next.push(tag.id);
          else {
            const i = next.indexOf(tag.id);
            if (i !== -1) next.splice(i, 1);
          }
          // Сохраняем без закрытия дропдауна (можно отметить несколько тегов сразу)
          chrome.runtime.sendMessage({ action: 'set-tab-tags', index: allTabs.indexOf(tab), tagIds: next });
        });
        
        const dot = document.createElement('span');
        dot.className = 'card-tag-dot';
        dot.dataset.color = tag.color;
        dot.style.flexShrink = '0';
        
        const labelSpan = document.createElement('span');
        labelSpan.textContent = tag.name;
        
        item.appendChild(cb);
        item.appendChild(dot);
        item.appendChild(labelSpan);
        item.addEventListener('click', (e) => e.stopPropagation());
        tagDropdown.appendChild(item);
      });
    }
    
    tagsBtn.appendChild(tagDropdown);
    if (openTagDropdownUrl === tab.url) tagDropdown.classList.add('open'); // переживает перерисовку
    tagsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const wasOpen = tagDropdown.classList.contains('open');
      document.querySelectorAll('.folder-dropdown.open').forEach(dd => dd.classList.remove('open'));
      openTagDropdownUrl = wasOpen ? null : tab.url;
      if (!wasOpen) tagDropdown.classList.add('open');
    });
    
    actions.appendChild(tagsBtn);
    
    // Кнопка возврата из архива (↩) — только для archivedAt
    if (isArchived) {
      const unarchiveBtn = document.createElement('button');
      unarchiveBtn.className = 'icon-btn unarchive';
      unarchiveBtn.textContent = '↩';
      unarchiveBtn.title = 'Вернуть из архива закрытых';
      unarchiveBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        chrome.runtime.sendMessage({ action: 'unarchive-tab', index: allTabs.indexOf(tab) });
      });
      actions.appendChild(unarchiveBtn);
    }
    
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'icon-btn delete';
    deleteBtn.title = 'Удалить';
    deleteBtn.textContent = '✕';
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm(`Удалить вкладку "${tab.name}"?`)) {
        removeTabScreenshot(tab);
        allTabs.splice(allTabs.indexOf(tab), 1);
        chrome.storage.sync.set({ 'blattam-tabs': allTabs });
        renderTabs(searchInput.value);
      }
    });
    
    actions.appendChild(deleteBtn);
    
    header.appendChild(nameEl);
    header.appendChild(actions);
    
    // URL
    const urlEl = document.createElement('span');
    urlEl.className = 'tab-url';
    urlEl.textContent = tab.url;
    
    card.appendChild(header);
    card.appendChild(urlEl);
    
    // Скриншот-миниатюра сверху карточки (если для вкладки он есть)
    if (tab.id != null && screenshots[tab.id]) {
      const shotImg = document.createElement('img');
      shotImg.className = 'tab-screenshot';
      shotImg.src = screenshots[tab.id];
      shotImg.alt = '';
      card.insertBefore(shotImg, card.firstChild);
    }
    // Клик по карточке — открыть вкладку + снять выбор
    card.addEventListener('click', () => {
      openUrl(tab.url);
    });

    // Drag & drop: карточку можно перетащить на чип папки
    card.draggable = true;
    card.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', String(allTabs.indexOf(tab)));
      e.dataTransfer.effectAllowed = 'move';
      card.classList.add('dragging');
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      document.querySelectorAll('.folder-chip.drag-over').forEach(c => c.classList.remove('drag-over'));
    });
    
    tabsList.appendChild(card);
  });
  
  noResults.style.display = visibleCount === 0 ? 'block' : 'none';
  updateSelectionBar();
  renderSessions(); // сессии перерисовываем вместе с карточками (state не теряется)
  // Активная карточка видна на экране
  if (activeUrl) {
    const activeCard = tabsList.querySelector('.tab-card.kbd-active');
    if (activeCard) activeCard.scrollIntoView({ block: 'nearest' });
  }
}

// Текущие видимые вкладки (фильтр папки + тега + сессии + спец-фильтры + поиск)
function visibleTabs(filter = '') {
  let filtered = allTabs;
  if (activeFolderId !== '') {
    // Фильтр папки включает вложенные папки (рекурсивно)
    const folderIds = [activeFolderId];
    let grew = true;
    while (grew) {
      grew = false;
      allFolders.forEach(f => {
        if (f.parentId && folderIds.includes(f.parentId) && !folderIds.includes(f.id)) {
          folderIds.push(f.id);
          grew = true;
        }
      });
    }
    filtered = filtered.filter(t => folderIds.includes(t.folderId));
  }
  if (activeTagId !== '') {
    filtered = filtered.filter(t => (t.tagIds || []).includes(activeTagId));
  }
  if (activeSessionId !== '') {
    const session = allSessions.find(s => s.id === activeSessionId);
    if (session) {
      const urls = session.tabUrls || [];
      filtered = filtered.filter(t => urls.includes(t.url));
    }
  }
  if (archiveOnly) {
    filtered = filtered.filter(t => t.archivedAt != null);
  } else if (activeSpecial === 'frequent') {
    const set = frequentUrlSet();
    filtered = filtered.filter(t => set.has(t.url));
  } else if (activeSpecial === 'favorites') {
    const set = favoritesUrlSet();
    filtered = filtered.filter(t => set.has(t.url));
  }
  if (filter) {
    filtered = filtered.filter(t => matchFilter(t, filter));
  }
  return filtered;
}

function matchFilter(tab, filter) {
  const f = filter.toLowerCase();
  return (tab.name || '').toLowerCase().includes(f) || 
         (tab.title || '').toLowerCase().includes(f) ||
         (tab.url || '').toLowerCase().includes(f);
}

// Переместить вкладку в папку
function moveTab(tab, folderId) {
  const realIndex = allTabs.indexOf(tab);
  if (realIndex === -1) return;
  chrome.runtime.sendMessage({ action: 'move-tab', index: realIndex, folderId });
}

// === Drag & drop: перетаскивание карточки на чип папки ===

// Чип папки принимает карточку
function attachFolderDrop(chip, folderId) {
  chip.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    chip.classList.add('drag-over');
  });
  chip.addEventListener('dragleave', () => chip.classList.remove('drag-over'));
  chip.addEventListener('drop', (e) => {
    e.preventDefault();
    chip.classList.remove('drag-over');
    const idx = parseInt(e.dataTransfer.getData('text/plain'), 10);
    const tab = allTabs[idx];
    if (tab) moveTab(tab, folderId);
  });
}

// "Все" чип — приём в "Все" (одноразово, чип статический)
attachFolderDrop(foldersBar.querySelector('.folder-chip[data-folder-id=""]'), null);

// Двойной клик по имени → инлайн-переименование
function startRename(tab, nameEl) {
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

const selectionBar = document.getElementById('selection-bar');
const selectionCount = document.getElementById('selection-count');
const selectBtn = document.getElementById('select-btn');
const openSelectedBtn = document.getElementById('open-selected-btn');
const clearSelectionBtn = document.getElementById('clear-selection-btn');

function updateSelectionBar() {
  const n = selectedUrls.size;
  selectionBar.classList.toggle('hidden', n === 0);
  selectionCount.textContent = `${n} выбрано`;
}

// "Выбрать" — toggle: выбрать все видимые / снять выбор с видимых
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

// Поиск
searchInput.addEventListener('input', (e) => {
  renderTabs(e.target.value);
});

// Закрыть дропдауны при клике вне их
document.addEventListener('click', (e) => {
  if (!e.target.closest('.folder-select-btn')) {
    document.querySelectorAll('.folder-dropdown.open').forEach(dd => dd.classList.remove('open'));
    openTagDropdownUrl = null;
  }
});

// === Клавиатурная навигация ===
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
  if (i === -1) i = 0; // нет активной → первая
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
  removeTabScreenshot(t);
  allTabs.splice(allTabs.indexOf(t), 1);
  chrome.storage.sync.set({ 'blattam-tabs': allTabs });
  renderTabs(searchInput.value); // onChanged-обработчик обнулит activeUrl, если карточки не осталось
}

document.addEventListener('keydown', (e) => {
  // Модалка работает сама — не перехватываем
  if (folderModal.classList.contains('open')) return;
  if (sessionModal && sessionModal.classList.contains('open')) return;
  if (isAnyModalOpen()) return;

  // Esc — сброс: сброс выбора, фильтра папки/тега/сессии, архива/рекомендаций,
  // поиска и активной карточки. Работает и из поля (например, из поиска) —
  // очищает его и снимает фокус.
  if (e.key === 'Escape') {
    if (searchInput.value) searchInput.value = '';
    const ae = document.activeElement;
    if (ae && ae !== document.body) ae.blur();
    if (activeFolderId !== '') { activeFolderId = ''; renderFolders(); }
    if (activeTagId !== '') { activeTagId = ''; renderTags(); }
    if (activeSessionId !== '') { activeSessionId = ''; renderSessions(); }
    if (archiveOnly || activeSpecial !== '') { clearSpecials(); renderFolders(); }
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
  if (areaName === 'local') {
    if (changes['blattam-stats']) {
      openStats = changes['blattam-stats'].newValue || {};
      if (activeSpecial !== '') renderTabs(searchInput.value);
    }
    return;
  }
  if (areaName !== 'sync') return;
  
  if (changes['blattam-tabs']) {
    allTabs = changes['blattam-tabs'].newValue || [];
    selectedUrls.clear(); // индексы/набор вкладок изменились — сброс выбора
    renderTabs(searchInput.value);
  }
  if (changes['blattam-folders']) {
    allFolders = changes['blattam-folders'].newValue || [];
    renderFolders();
  }
  if (changes['blattam-tags']) {
    allTags = changes['blattam-tags'].newValue || [];
    // Удаление активного тега сбрасывает фильтр
    if (activeTagId !== '' && !allTags.some(t => t.id === activeTagId)) activeTagId = '';
    renderTags();
    renderTabs(searchInput.value); // точки на карточках изменились
  }
  if (changes['blattam-sessions']) {
    // Новый sync-ключ — fired на всю sync-область, но существующие обработчики
    // выше читают свои ключи, так что они продолжают работать.
    allSessions = changes['blattam-sessions'].newValue || [];
    // Удаление активной сессии сбрасывает фильтр
    if (activeSessionId !== '' && !allSessions.some(s => s.id === activeSessionId)) activeSessionId = '';
    renderSessions();
    renderTabs(searchInput.value); // набор видимых под фильтр сессии изменился
  }
});

// === Экспорт / Импорт (с папками, тегами, сессиями) ===

document.getElementById('export-btn').addEventListener('click', () => {
  const data = {
    'blattam-toby': true,
    version: chrome.runtime.getManifest().version,
    exported: new Date().toISOString(),
    folders: allFolders,
    tags: allTags,
    sessions: allSessions,
    tabs: allTabs
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const date = new Date().toISOString().slice(0, 10);
  a.download = `blattam-toby-backup-${date}.json`;
  a.click();
  URL.revokeObjectURL(url);
});

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
      
      // Импорт папок (с parentId, максимум 1 уровень)
      let importedFoldersCount = 0;
      if (data.folders && Array.isArray(data.folders)) {
        const existingNames = allFolders.map(f => f.name.toLowerCase());
        data.folders.forEach(folder => {
          if (!existingNames.includes(folder.name.toLowerCase())) {
            // Вложенность: родитель должен существовать и не иметь parent сам
            let parentId = folder.parentId || null;
            if (parentId != null && !allFolders.some(f => f.id === parentId && f.parentId == null)) {
              parentId = null;
            }
            allFolders.push({ id: folder.id, name: folder.name, parentId });
            importedFoldersCount++;
          }
        });
      }
      
      // Импорт тегов
      let importedTagsCount = 0;
      if (data.tags && Array.isArray(data.tags)) {
        const existingTagNames = allTags.map(t => t.name.toLowerCase());
        data.tags.forEach(tag => {
          if (tag && tag.id && tag.name && !existingTagNames.includes(String(tag.name).toLowerCase())) {
            const c = parseInt(tag.color, 10);
            allTags.push({
              id: tag.id,
              name: String(tag.name),
              color: Number.isInteger(c) && c >= 1 && c <= 6 ? c : 1
            });
            importedTagsCount++;
          }
        });
      }
      
      // Импорт сессий (по имени — дедупликация)
      let importedSessionsCount = 0;
      if (data.sessions && Array.isArray(data.sessions)) {
        const existingSessionNames = allSessions.map(s => s.name.toLowerCase());
        data.sessions.forEach(session => {
          if (session && session.name && !existingSessionNames.includes(String(session.name).toLowerCase())) {
            allSessions.push({
              id: session.id || ('s' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7)),
              name: String(session.name),
              createdAt: session.createdAt || Date.now(),
              tabUrls: Array.isArray(session.tabUrls) ? session.tabUrls.slice() : []
            });
            importedSessionsCount++;
          }
        });
      }
      
      const importedTabs = data.tabs.filter(t => t.url && t.name);
      let newCount = 0;
      const duplicates = importedTabs.filter(t => allTabs.some(existing => existing.url === t.url)).length;
      newCount = importedTabs.length - duplicates;
      
      if (!confirm(`В файле ${importedFoldersCount + (data.folders ? 1 : 0)} папок (+${importedFoldersCount} новых), ${importedTagsCount} тегов (+${importedTagsCount} новых), ${importedTabs.length} вкладок.\nНовых: ${newCount}, дубликатов: ${duplicates}\n\nИмпортировать?`)) {
        return;
      }
      
      importedTabs.forEach(t => {
        if (!allTabs.some(existing => existing.url === t.url)) {
          // Проверяем что folderId существует
          if (t.folderId && !allFolders.some(f => f.id === t.folderId)) {
            t.folderId = null;
          }
          // Проверяем что tagIds существуют
          if (Array.isArray(t.tagIds)) {
            t.tagIds = t.tagIds.filter(id => allTags.some(tag => tag.id === id));
          } else {
            t.tagIds = [];
          }
          // archivedAt (архив закрытых) переезжает вместе с вкладкой
          allTabs.push(t);
        }
      });
      
      chrome.storage.sync.set({ 
        'blattam-tabs': allTabs,
        'blattam-folders': allFolders,
        'blattam-tags': allTags,
        'blattam-sessions': allSessions
      });
    } catch (err) {
      alert('Ошибка чтения файла: невалидный JSON');
    }
  };
  reader.readAsText(file);
  e.target.value = '';
});

// === Старт ===
loadData();
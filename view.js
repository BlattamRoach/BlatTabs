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
const foldersBar = document.getElementById('folders-bar');
const addFolderBtn = document.getElementById('add-folder-btn');

// Модалка папок (создание/переименование)
const folderModal = document.getElementById('folder-modal');
const modalTitle = document.getElementById('modal-title');
const folderNameInput = document.getElementById('folder-name-input');
const modalCancel = document.getElementById('modal-cancel');
const modalConfirm = document.getElementById('modal-confirm');

// Панель массового выбора
const selectionBar = document.getElementById('selection-bar');
const selectionCount = document.getElementById('selection-count');
const selectBtn = document.getElementById('select-btn');
const openSelectedBtn = document.getElementById('open-selected-btn');
const clearSelectionBtn = document.getElementById('clear-selection-btn');

let allTabs = [];
let allFolders = [];
let activeFolderId = '';     // '' = "Все"
let modalCallback = null;
let selectedUrls = new Set(); // выбор вкладок для массового открытия
let dragSourceUrl = null; // URL перетаскиваемой карточки (для reorder; индексы в payload могут устареть)
let activeUrl = null; // карточка, выбранная клавиатурой (по URL — переживает перерисовку)
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
  chrome.storage.sync.get(['blattam-tabs', 'blattam-folders'], (result) => {
    allTabs = result['blattam-tabs'] || [];
    allFolders = result['blattam-folders'] || [];
    renderFolders();
    renderTabs();
  });
}

// === Папки ===

function folderLabel() {
  if (activeFolderId === '') return 'Все вкладки';
  const f = allFolders.find(x => x.id === activeFolderId);
  return f ? f.name : 'Все вкладки';
}

function renderFolders() {
  // Удаляем старые чипы (только user folders, не "Все")
  foldersBar.querySelectorAll('.folder-chip[data-folder-id]:not([data-folder-id=""])').forEach(el => el.remove());

  allFolders.forEach(folder => {
    const isNested = folder.parentId != null;
    const chip = document.createElement('button');
    chip.className = 'chip folder-chip' + (activeFolderId === folder.id ? ' active' : '') + (isNested ? ' nested' : '');
    chip.dataset.folderId = folder.id;

    // Иконка папки + имя (вложенные — с «↳»)
    const icon = document.createElement('span');
    icon.className = 'em';
    icon.textContent = isNested ? '\u21B3' : '\uD83D\uDCC1';
    chip.appendChild(icon);

    const name = document.createElement('span');
    name.className = 'chip-name';
    name.textContent = folder.name;
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
      openRenameModal(folder.id, folder.name);
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'chip-icon-btn';
    deleteBtn.textContent = '\u2715';
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

  // "Все" чип — активен, когда папка не выбрана
  const allChip = foldersBar.querySelector('.folder-chip[data-folder-id=""]');
  if (allChip) {
    allChip.className = 'chip folder-chip' + (activeFolderId === '' ? ' active' : '');
  }
}

// "+ Папка" — создать папку
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

// "Все" чип — клик сбрасывает фильтр папки (возврат к обычному виду)
foldersBar.querySelector('.folder-chip[data-folder-id=""]').addEventListener('click', () => {
  activeFolderId = '';
  renderFolders();
  renderTabs(searchInput.value);
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
  if (!host && url) host = String(url).replace(/^[a-z]+:\/\/\/?/i, '').split('/')[0].split(':')[0];
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

// === Карточки вкладок ===

function renderTabs(filter = '') {
  tabsList.innerHTML = '';

  // Фильтр по папке + поиску
  const filtered = visibleTabs(filter);
  // Если активная (клавиатурная) карточка не в видимом списке — сбрасываем
  if (activeUrl && !filtered.some(t => t.url === activeUrl)) activeUrl = null;

  if (allTabs.length === 0) {
    emptyState.style.display = 'block';
    noResults.style.display = 'none';
    metaCount.textContent = '0';
    return;
  }
  emptyState.style.display = 'none';

  let visibleCount = 0;

  filtered.forEach((tab) => {
    // Поиск по имени/title/URL
    if (filter && !matchFilter(tab, filter)) return;
    visibleCount++;

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

    const urlEl = document.createElement('div');
    urlEl.className = 'tab-url';
    urlEl.textContent = tab.url;

    body.appendChild(nameEl);
    body.appendChild(urlEl);
    card.appendChild(body);

    // Кнопка-дропдаун папки (hover-контрол, снизу-справа)
    const folderBtn = document.createElement('button');
    folderBtn.className = 'folder-select-btn';
    folderBtn.textContent = '\uD83D\uDCC1';
    folderBtn.title = 'Переместить в папку';

    const dropdown = document.createElement('div');
    dropdown.className = 'folder-dropdown';

    // "Все" (null)
    const allItem = document.createElement('div');
    allItem.className = 'folder-dd-item all-folder';
    allItem.textContent = '\u2192 Все';
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
      item.textContent = `\u2192 ${depth > 0 ? '\u21B3 ' : ''}${folder.name}`;
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
      if (!wasOpen) dropdown.classList.add('open');
    });
    card.appendChild(folderBtn);

    // Клик по карточке — открыть вкладку + снять выбор
    card.addEventListener('click', () => {
      openUrl(tab.url);
    });

    // Drag & drop: карточку можно перетащить на чип папки (переместить в папку)
    // или на другую карточку (переставить порядок — см. attachCardReorderDrop)
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
      document.querySelectorAll('.folder-chip.drag-over').forEach(c => c.classList.remove('drag-over'));
    });
    attachCardReorderDrop(card, tab);

    tabsList.appendChild(card);
  });

  noResults.style.display = visibleCount === 0 ? 'block' : 'none';
  metaLabel.textContent = folderLabel();
  metaCount.textContent = String(visibleCount);
  updateSelectionBar();
  // Активная карточка видна на экране
  if (activeUrl) {
    const activeCard = tabsList.querySelector('.tab-card.kbd-active');
    if (activeCard) activeCard.scrollIntoView({ block: 'nearest' });
  }
}

// Текущие видимые вкладки (фильтр папки + поиск)
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

// === Drag & drop: перестановка карточек (reorder) ===
// Карточка принимает перетаскиваемую карточку: верхняя половина — вставить
// перед, нижняя — после. Меняется только порядок в 'blattam-tabs' (folderId
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

// Карточка принимает другую карточку (drop on self — no-op)
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
    if (!src || src.url !== dragSourceUrl || src === tab) return; // drop on self / stale — no-op
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

// «Сбросить фильтры» — в состоянии «ничего не найдено»
const btnResetFilters = document.getElementById('btn-reset-filters');
if (btnResetFilters) {
  btnResetFilters.addEventListener('click', () => {
    searchInput.value = '';
    activeFolderId = '';
    activeUrl = null;
    renderFolders();
    renderTabs('');
  });
}

// Поиск
searchInput.addEventListener('input', (e) => {
  renderTabs(e.target.value);
});

// Закрыть дропдауны при клике вне их
document.addEventListener('click', (e) => {
  if (!e.target.closest('.folder-select-btn')) {
    document.querySelectorAll('.folder-dropdown.open').forEach(dd => dd.classList.remove('open'));
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
  allTabs.splice(allTabs.indexOf(t), 1);
  chrome.storage.sync.set({ 'blattam-tabs': allTabs });
  renderTabs(searchInput.value); // onChanged-обработчик обнулит activeUrl, если карточки не осталось
}

document.addEventListener('keydown', (e) => {
  // Модалка работает сама — не перехватываем
  if (folderModal.classList.contains('open')) return;
  if (isAnyModalOpen()) return;

  // Esc — сброс: сброс выбора, фильтра папки, поиска и активной
  // карточки. Работает и из поля (например, из поиска) — очищает его
  // и снимает фокус.
  if (e.key === 'Escape') {
    if (searchInput.value) searchInput.value = '';
    const ae = document.activeElement;
    if (ae && ae !== document.body) ae.blur();
    if (activeFolderId !== '') { activeFolderId = ''; renderFolders(); }
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
    if (!sameUrlSet) selectedUrls.clear(); // индексы/набор вкладок изменились — сброс выбора
    renderTabs(searchInput.value);
  }
  if (changes['blattam-folders']) {
    allFolders = changes['blattam-folders'].newValue || [];
    renderFolders();
  }
});

// === Экспорт / Импорт (с папками) ===

document.getElementById('export-btn').addEventListener('click', () => {
  const data = {
    'blattam-toby': true,
    version: chrome.runtime.getManifest().version,
    exported: new Date().toISOString(),
    folders: allFolders,
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

      const importedTabs = data.tabs.filter(t => t.url && t.name);
      let newCount = 0;
      const duplicates = importedTabs.filter(t => allTabs.some(existing => existing.url === t.url)).length;
      newCount = importedTabs.length - duplicates;

      if (!confirm(`В файле ${importedFoldersCount + (data.folders ? 1 : 0)} папок (+${importedFoldersCount} новых), ${importedTabs.length} вкладок.\nНовых: ${newCount}, дубликатов: ${duplicates}\n\nИмпортировать?`)) {
        return;
      }

      importedTabs.forEach(t => {
        if (!allTabs.some(existing => existing.url === t.url)) {
          // Проверяем что folderId существует
          if (t.folderId && !allFolders.some(f => f.id === t.folderId)) {
            t.folderId = null;
          }
          allTabs.push(t);
        }
      });

      chrome.storage.sync.set({
        'blattam-tabs': allTabs,
        'blattam-folders': allFolders
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

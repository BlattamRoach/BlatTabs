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

// === Фон (кастомная картинка-фон) ===
// blattam-bg-image — data URL (большой ключ — только chrome.storage.local;
// лимит ~4 МБ, проверка по длине data URL при выборе файла). Применяем
// сохранённый фон там же, где тему — ДО первого рендера (без «вспышки»).
function applyBackgroundImage(dataUrl) {
  // .center (центр) имеет собственный непрозрачный фон var(--bg), перекрывающий
  // body (рейки — var(--rail-bg)) — картинку вешаем и на body, и на центр:
  // визуально фон за центральной областью (обработчик вешает оба инлайн-стиля,
  // тема не влияет: background-color темы остаётся под картинкой).
  const targets = [document.body, document.getElementById('center-pane')];
  targets.forEach((el) => {
    if (!el) return;
    if (dataUrl) {
      el.style.backgroundImage = 'url("' + dataUrl + '")';
      el.style.backgroundSize = 'cover';
      el.style.backgroundPosition = 'center';
      el.style.backgroundAttachment = 'fixed';
    } else {
      ['background-image', 'background-size', 'background-position', 'background-attachment']
        .forEach((prop) => el.style.removeProperty(prop));
    }
  });
  const preview = document.getElementById('bg-preview');
  const clearBtn = document.getElementById('bg-clear-btn');
  if (preview) {
    preview.style.display = dataUrl ? 'block' : 'none';
    if (dataUrl) preview.src = dataUrl;
  }
  if (clearBtn) clearBtn.style.display = dataUrl ? '' : 'none';
}

chrome.storage.local.get(['blattam-bg-image'], (result) => {
  applyBackgroundImage(result['blattam-bg-image'] || '');
});

// === Цвет вкладок (кастомный фон карточек) ===
// blattam-tab-color — hex (например '#8a6d5c'); пустое значение — токены темы.
// Применяем там же, где тему и фон — ДО первого рендера (без «вспышки»):
// цвет живёт в инлайн-стиле documentElement (переопределяет --tab-card-bg),
// поэтому переживает перерисовку карточек и смену темы (токен сбрасывается).
function themeCardBgHex() {
  // текущий фон карточки темы (для дефолтного значения пикера) — из токена, не литерала
  return getComputedStyle(document.documentElement).getPropertyValue('--card-bg').trim();
}

function applyTabCardColor(hex) {
  const root = document.documentElement;
  if (hex) root.style.setProperty('--tab-card-bg', hex);
  else root.style.removeProperty('--tab-card-bg'); // токены темы возвращают дефолт
  const input = document.getElementById('tab-color-input');
  const resetBtn = document.getElementById('tab-color-reset');
  if (input) {
    const val = hex || themeCardBgHex();
    if (val) input.value = val;
  }
  if (resetBtn) resetBtn.style.display = hex ? '' : 'none';
}

chrome.storage.local.get(['blattam-tab-color'], (result) => {
  applyTabCardColor(result['blattam-tab-color'] || '');
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
const openSelectedBtn = document.getElementById('open-selected-btn');
const clearSelectionBtn = document.getElementById('clear-selection-btn');
const deleteSelectedBtn = document.getElementById('delete-selected-btn');

let allTabs = [];
let allSpaces = [];   // { id, name } — плоский список (без вложенности)
let allGroups = [];   // { id, name, spaceId, collapsed } — группы внутри пространств
let activeSpaceId = ''; // активное пространство (по id — переживает перерисовку)
let modalCallback = null;
let modalAllowEmpty = false; // модалки создания допускают пустое имя (авто-«Пространство N» / «Группа N»)
let selectedUrls = new Set(); // выбор вкладок для массового открытия
// Параметры анимаций pointer-драга (читаются ПЕРЕД каждым использованием —
// тесты могут их обнулить). slideMs — FLIP-сдвиг соседей, settleMs —
// «посадка» клона в слот, liftScale — масштаб подъёма клона.
window.blatamFx = { slideMs: 200, settleMs: 180, liftScale: 1.02 };

let dragSourceUrl = null; // URL перетаскиваемой карточки (для reorder; индексы в payload могут устареть)
let dragSourceCardEl = null; // DOM-элемент перетаскиваемой карточки (исключается из расчёта зазора)
let dragCardSize = null; // размер схваченной карточки (w/h) — снят до хайда (display:none → rects 0×0)
let dragGhostSlot = null; // ghost-slot: пустая заглушка размера карточки на её месте в сетке
let dragSourceGroupId = null; // id перетаскиваемой группы (reorder шапок внутри пространства)
let dragSourceSpaceId = null; // id перетаскиваемого чипа (reorder пространств в ряду чипов)
let dragGhostChipSlot = null; // ghost-slot чипа: тёплая заглушка размера чипа (26px) в ряду
                              // #space-chips — единственный индикатор вставки при drag чипа
let dragWrapHiddenCard = null; // «row-full» группа: крайняя карточка группы, временно
                               // скрытая — тёплая заглушка внутри полной группы дорастила
                               // бы новую строку; скрытие последней карточки держит число
                               // строк постоянным (возврат: заглушка ушла из группы / драг
                               // закончился / перерисовка)
let dragWrapHiddenGroup = null; // groupId той группы: та же карточка держится скрытой,
                                // пока заглушка внутри неё
let dragRowKeepers = [];       // .tab-row-keeper: невидимые карточки-холдеры,
                               // держащие последнюю строку исходной секции, пока
                               // ghost-заглушка уехала из неё (или спрятана)
let dragRowKeeperSection = null; // секция текущих холдеров: groupId (null — без группы)
let dragOverChipTarget = null; // последний target dragover чипа — чтобы отложенное создание
                               // заглушки (dragstart setTimeout) повторило состояние, если
                               // первый dragover уже попал на целевой чип ПЕРЕД таймером
let dragOverChipSide = null; // сторона этого первого dragover ('before'/'after'):
                             // повтор применяется по ЗАПИСАННОЙ стороне — координаты
                             // относятся к ряду ДО reflow, после вставки заглушки
                             // пересчёт по X дал бы противоположную половину
let pendingChipClickAfterDrag = false; // one-shot: ложный клик по чипу-цели рождается
                        // в момент дропа (реальный Chrome: drop → click → dragend) —
                        // вооружаем на dragstart чипа и на drop; гасим ровно ОДИН;
                        // настоящее нажатие (mousedown) сбрасывает флаг раньше клика
let dragBatchUrls = null; // все вкладки, уезжающие с перетаскиваемой карточкой:
                          // выделенный батч (порядок — исходный, из allTabs) или [dragSourceUrl]
let dragOverTarget = null; // последний target dragover — чтобы отложенное создание
                           // заглушки (dragstart setTimeout) повторило состояние, если
                           // первый dragover уже попал на шапку/слот ПЕРЕД таймером
let dragOverTargetXY = null; // координаты этого dragover (clientX/clientY) —
                             // пустая зона карт.области группы повторяется по ГЕОМЕТРИИ,
                             // а не по элементу цели
let lastDragEndAt = 0; // время последнего dragend (карточки или шапки): клик по шапке
                        // сразу после дропа — не действие пользователя, не сворачиваем группу
let pendingGbarClickAfterDrag = false; // one-shot: ложный клик по шапке рождается в момент
                        // дропа — реальный Chrome генерирует его на drop-цели ДО dragend
                        // источника (замер: drop → click → dragend), а не только после;
                        // поэтому флаг вооружаем на dragstart карточки и на drop по шапке
                        // (не только на dragend) — гасим ровно ОДИН такой клик; новое
                        // нажатие мыши (mousedown) раньше его клика сбрасывает флаг
let activeUrl = null; // карточка, выбранная клавиатурой (по URL — переживает перерисовку)
let openModalId = null; // id открытой модалки — чтобы глобальный keydown её не перехватывал
let browserTabs = []; // все открытые вкладки браузера (blattam-browser-tabs, все окна)
let browserWindowId = null; // id этого окна — рейка показывает вкладки только его
let dragSourceBrowserTab = null; // вкладки рейки, которую тянут: {id,url,title,favIconUrl,windowId,index}
let dragBrowserTabGhost = null;const browserTabsList = document.getElementById('browser-tabs-list'); // рейка: список открытых вкладок
const railRight = document.getElementById('rail-right'); // правая рейка — цель дропа карточки (открыть сайт фоном)
let btDragItem = null; // элемент рейки, который тащат (cleanup по id переживает перерисовку)
let btDragHeight = 30; // высота элемента ДО display:none (размер заглушки)
let btDropCommitted = false; // дроп обработан (рейка/центр) — ложный клик гасится
let pendingBtClickAfterDrag = false; // one-shot: ложный post-drop-клик по элементу рейки
let pendingCardClickAfterDrag = false; // one-shot: ложный post-drop-клик по центральной карточке (открыл бы вкладку) — вооружается на dragstart карточки и вкладки рейки
//  // тёплая заглушка рейки (.bt-ghost-slot) на слоте схваченной вкладки

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

// === Миграция: вкладки sync → local (идемпотентная) ===
// blattam-tabs — большой ключ (~10 МБ), живёт в chrome.storage.local
// (per-device; лимит sync 8 КБ/ключ ломал запись ~20+ вкладок). ДО первого
// рендера: если local пуст (нет/пусто), а sync непуст — копируем ключ из sync
// в local и удаляем sync-ключ. Если local заполнен — только чистим stale-sync.
let tabsMigrated = null;
function migrateTabsToLocalStorage() {
  if (tabsMigrated) return tabsMigrated;
  tabsMigrated = (async () => {
    const localData = await chrome.storage.local.get('blattam-tabs');
    const syncData = await chrome.storage.sync.get('blattam-tabs');
    const localTabs = Array.isArray(localData['blattam-tabs']) ? localData['blattam-tabs'] : [];
    const syncTabs = Array.isArray(syncData['blattam-tabs']) ? syncData['blattam-tabs'] : [];
    if (localTabs.length === 0 && syncTabs.length > 0) {
      await chrome.storage.local.set({ 'blattam-tabs': syncTabs });
    }
    if (syncData['blattam-tabs'] !== undefined) {
      await chrome.storage.sync.remove('blattam-tabs');
    }
  })();
  return tabsMigrated;
}

// === Загрузка данных ===

function loadData() {
  (async () => {
    await migrateTabsToLocalStorage(); // ДО первого рендера: вкладки — из local
    const localData = await chrome.storage.local.get(['blattam-tabs']);
    const result = await chrome.storage.sync.get(['blattam-spaces', 'blattam-groups', 'blattam-last-space', 'blattam-folders']);
    const tabs = Array.isArray(localData['blattam-tabs']) ? localData['blattam-tabs'] : [];
    const spaces = Array.isArray(result['blattam-spaces']) ? result['blattam-spaces'] : [];
    const groups = Array.isArray(result['blattam-groups']) ? result['blattam-groups'] : [];
    const folders = result['blattam-folders'];

    const updates = {};       // sync (пространства/группы/last-space)
    const localUpdates = {};  // local (вкладки)

    // Миграция legacy (ДО первого рендера): нет 'blattam-spaces', но есть
    // 'blattam-folders' или вкладки с folderId
    if (!Array.isArray(result['blattam-spaces']) && (folders !== undefined || tabs.some(t => t && t.folderId != null))) {
      migrateFoldersToSpaces(tabs, spaces, folders);
      localUpdates['blattam-tabs'] = tabs;
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
    if (tabsChanged) localUpdates['blattam-tabs'] = tabs;

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
    if (Object.keys(localUpdates).length) {
      chrome.storage.local.set(localUpdates);
    }
    renderSpaces();
    renderTabs();
  })();
}

// === Пространства (чипы) ===

function spaceLabel() {
  const s = allSpaces.find(x => x.id === activeSpaceId);
  return s ? s.name : DEFAULT_SPACE_NAME;
}

function renderSpaces() {
  spaceChips.innerHTML = '';
  // Перерисовка во время drag чипа уносит chip-заглушку из DOM — сбрасываем
  // ссылку, чтобы она не «воскресла» после dragend
  if (dragGhostChipSlot && !dragGhostChipSlot.isConnected) dragGhostChipSlot = null;
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

    // DnD-источник: чип тянем на другой чип — reorder пространств (порядок
    // чипов = порядок массива blattam-spaces). Пейлоад: id пространства
    // (у карточки — индекс вкладки). Кнопки ✎/✕ не стартуют drag:
    // guardDragOverButtons снимает draggable на время press
    chip.draggable = true;
    guardDragOverButtons(chip, '.chip-icon-btn');
    pcdBindChip(chip, sp.id); // pointer-путь (реальный Chrome) — см. ниже
    chip.addEventListener('dragstart', (e) => {
      if (!chip.draggable) { e.preventDefault(); return; } // press начался на кнопке
      // Нативный HTML5-драг отменяется в реальном Chrome (цикл ведёт
      // pointer-путь, см. «Pointer drag of space chips» ниже); синтетический
      // dragstart харнесса (не-trusted) проходит дальше и работает без изменений
      e.preventDefault();
      if (e.isTrusted) return;
      e.dataTransfer.setData('text/plain', sp.id);
      e.dataTransfer.effectAllowed = 'move';
      dragSourceSpaceId = sp.id;
      dragOverChipTarget = null; // свежий драг — целевой dragover ещё не приходил
      dragOverChipSide = null;
      chip.classList.add('dragging');
      // Ложный клик вооружаем уже на dragstart: реальный Chrome генерирует
      // его на drop-цели ДО dragend источника
      pendingChipClickAfterDrag = true;
      // Исходный чип исчезает из ряда (нативный drag-образ браузера следует за
      // курсором); место занимает тёплая заглушка чипа — отложенно:
      // display:none в самом dragstart «залипает» HTML5-drag в Chrome
      setTimeout(() => {
        // Перерисовка во время драга уносит чип из DOM, а поздний drop/dragend
        // уже решил драг — заглушку для отсоединённого чипа не вставляем
        if (dragSourceSpaceId !== sp.id || !chip.isConnected) return;
        if (!dragGhostChipSlot) {
          // Меряем ДО display:none (у скрытого чипа offsetWidth/Height = 0)
          dragGhostChipSlot = makeSpaceGhostSlot(chip);
          chip.insertAdjacentElement('afterend', dragGhostChipSlot);
        }
        chip.style.display = 'none';
        // Гонка: первый dragover мог попасть на целевой чип ПЕРЕД этим таймером
        // (заглушки ещё не существовало). Повторяем его состояние по записанной
        // стороне, иначе свежая заглушка неверно замирает дома.
        if (dragOverChipTarget && dragOverChipTarget.isConnected && dragOverChipTarget !== chip) {
          moveSpaceGhostSlot({ el: dragOverChipTarget, side: dragOverChipSide });
        }
      }, 0);
    });
    chip.addEventListener('dragend', () => {
      lastDragEndAt = Date.now();
      pendingChipClickAfterDrag = true;
      dragSourceSpaceId = null;
      dragOverChipTarget = null; // не держим ссылку на DOM-узел после драга
      dragOverChipSide = null;
      chip.classList.remove('dragging');
      removeSpaceGhostSlot();
      if (chip.isConnected) chip.style.display = ''; // drag без drop — чип обратно в ряд
      document.querySelectorAll('.space-chip.drag-over')
        .forEach(c => c.classList.remove('drag-over'));
    });

    // Клик — переключение пространства. Ложный post-drop клик (без mousedown)
    // гасим ровно один: настоящий press всегда проходит через
    // document-mousedown, сбрасывающий флаг раньше клика
    chip.addEventListener('click', () => {
      if (pendingChipClickAfterDrag) { pendingChipClickAfterDrag = false; return; }
      switchSpace(sp.id);
    });
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

// === Модалка: настройки (FAQ) ===
// Открытие — кнопка «Настройки» в левой рейке. Закрытие — ✕, клик по затемнённому
// фону (как у модалки пространств) и Escape. setModalOpen('settings') делает
// isAnyModalOpen() истинным, поэтому глобальный keydown (modal check → Escape →
// editable-guard) не перехватывает клавиши, пока модалка открыта.
const settingsModal = document.getElementById('settings-modal');
const settingsCloseBtn = document.getElementById('settings-close');
const settingsBtn = document.getElementById('settings-btn');

function openSettingsModal() {
  settingsModal.classList.add('open');
  setModalOpen('settings');
  setSettingsSection('customization'); // при каждом открытии — «Кастомизация»
  // пикер «Цвет вкладок» показывает актуальное значение (из local-хранилища)
  chrome.storage.local.get(['blattam-tab-color'], (r) => {
    applyTabCardColor(r['blattam-tab-color'] || '');
  });
}

function closeSettingsModal() {
  settingsModal.classList.remove('open');
  setModalOpen(null);
}

settingsBtn.addEventListener('click', openSettingsModal);
settingsCloseBtn.addEventListener('click', closeSettingsModal);
settingsModal.addEventListener('click', (e) => {
  if (e.target === settingsModal) closeSettingsModal();
});

// Escape — закрыть (отдельный слушатель: глобальный keydown байлит при открытой модалке)
document.addEventListener('keydown', (e) => {
  if (settingsModal.classList.contains('open') && e.key === 'Escape') closeSettingsModal();
});

// Двухпанное окно: слева навигация разделов («Кастомизация»/«FAQ» — кнопки
// .settings-nav-item), справа — контент; виден только активный
// (#settings-pane-customization / #settings-pane-faq, display:none у неактивной).
// Состояние — module-переменная по id раздела (переживает перерисовку, идемпотентна);
// клик по навигации модалку НЕ закрывает — close-по-фону скоуплен на сам оверлей
// (e.target === settingsModal), а клик по пункту — только по внутренней кнопке.
let settingsSection = 'customization';
const settingsNavItems = [...settingsModal.querySelectorAll('.settings-nav-item')];
function setSettingsSection(id) {
  if (!settingsNavItems.some((b) => b.dataset.section === id)) id = 'customization';
  settingsSection = id;
  settingsNavItems.forEach((b) => b.classList.toggle('active', b.dataset.section === id));
  ['customization', 'faq'].forEach((s) => {
    const pane = document.getElementById('settings-pane-' + s);
    if (pane) pane.style.display = (s === id) ? '' : 'none';
  });
}
settingsNavItems.forEach((btn) => {
  btn.addEventListener('click', () => setSettingsSection(btn.dataset.section));
});

// «Фон» в настройках: картинка → data URL → blattam-bg-image (local).
const bgFileBtn = document.getElementById('bg-file-btn');
const bgFileInput = document.getElementById('bg-file-input');
const bgClearBtn = document.getElementById('bg-clear-btn');

bgFileBtn.addEventListener('click', () => bgFileInput.click());

bgFileInput.addEventListener('change', (e) => {
  const file = e.target.files[0];
  e.target.value = ''; // сброс input — тот же файл можно выбрать повторно
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (event) => {
    const dataUrl = String(event.target.result || '');
    if (dataUrl.length > 4000000) {
      alert('Картинка слишком большая (максимум ~4 МБ)');
      return;
    }
    chrome.storage.local.set({ 'blattam-bg-image': dataUrl });
    applyBackgroundImage(dataUrl);
  };
  reader.readAsDataURL(file);
});

bgClearBtn.addEventListener('click', () => {
  chrome.storage.local.remove('blattam-bg-image');
  applyBackgroundImage('');
});

// «Цвет вкладок» в настройках: пикер → blattam-tab-color (local), live-применение.
const tabColorInput = document.getElementById('tab-color-input');
const tabColorResetBtn = document.getElementById('tab-color-reset');

if (tabColorInput) {
  tabColorInput.addEventListener('input', () => {
    chrome.storage.local.set({ 'blattam-tab-color': tabColorInput.value });
    applyTabCardColor(tabColorInput.value);
  });
}

if (tabColorResetBtn) {
  tabColorResetBtn.addEventListener('click', () => {
    chrome.storage.local.remove('blattam-tab-color');
    applyTabCardColor('');
  });
}

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

// Винительный падеж для «Удалить N …?»: 1 — «вкладку», 2–4 — «вкладки»,
// 5+ и 11–14 — «вкладок»
function pluralVkladki(n) {
  const a = Math.abs(n) % 100, d = a % 10;
  if (d === 1 && a !== 11) return 'вкладку';
  if (d > 1 && d < 5 && (a < 11 || a > 14)) return 'вкладки';
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
  // Свёрнутая группа — полноширинная шапка (gbar-collapsed); развёрнутая —
  // компактная область по ширине содержимого (CSS — view.html, .gbar)
  if (g.collapsed) bar.classList.add('gbar-collapsed');
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
  // ⧉ — открыть ВСЕ вкладки группы в новых вкладках браузера (hover-контрол,
  // тот же путь, что клик по карточке — openUrl для каждой вкладки группы)
  const gopenall = document.createElement('button');
  gopenall.className = 'gopenall';
  gopenall.textContent = '\u29C9';
  gopenall.title = 'Открыть все вкладки группы';
  gopenall.addEventListener('click', (e) => {
    e.stopPropagation();
    allTabs.filter(t => t.spaceId === g.spaceId && t.groupId === g.id).forEach(t => openUrl(t.url));
  });

  bar.appendChild(gselect);
  bar.appendChild(grename);
  bar.appendChild(del);
  bar.appendChild(gopenall);

  // DnD-источник: шапку можно перетащить на другую шапку (reorder групп
  // внутри пространства). Пейлоад: id группы (у карточки — индекс вкладки).
  bar.draggable = true;
  // Кнопки шапки (☑/✎/✕) не стартуют drag: нажатие на них временно снимает
  // draggable, иначе движение >~5px во время press уносит drag-ом шапку и
  // click по кнопке теряется (реальный Chrome).
  guardDragOverButtons(bar, '.gselect, .grename, .gdel, .gopenall');
  bar.addEventListener('dragstart', (e) => {
    if (!bar.draggable) { e.preventDefault(); return; } // press начался на кнопке
    // Нативный HTML5-драг отменяется, когда press ведёт pointer-путь: свой
    // (gbarPointerPress — ставится на pointerdown pointer-путём шапки, более поздняя волна)
    // или чужой pointer-драг пересекает шапку (pdForeignActive). Синтетическая
    // цепочка харнесса (не-trusted) всегда проходит без изменений
    if (e.isTrusted && (gbarPointerPress || pdForeignActive())) { e.preventDefault(); return; }
    e.dataTransfer.setData('text/plain', g.id);
    e.dataTransfer.effectAllowed = 'move';
    dragSourceGroupId = g.id;
    bar.classList.add('dragging');
  });
  bar.addEventListener('dragend', () => {
    lastDragEndAt = Date.now();
    pendingGbarClickAfterDrag = true;
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
    // Ложный клик по шапке рождается в этот момент (до dragend источника):
    // вооружаем one-shot-подавление и уводим тёплую заглушку — собственный
    // drop шапки не проходит через глобальный removeGhostSlot
    pendingGbarClickAfterDrag = true;
    removeGhostSlot();
    if (dragSourceGroupId) {
      reorderGroups(dragSourceGroupId, g.id, reorderSide(bar, e.clientY));
      return;
    }
    // Пустая/свёрнутая группа: карточка уходит в группу — в конец списка
    // (anchorIndex null); карточка своей группы — no-op. Выделенный батч —
    // целиком (place-tabs), если хотя бы одна его вкладка не в этой группе.
    if (dragSourceUrl && !groupVisibleCardCount(g.id)) {
      const src = allTabs.find(t => t.url === dragSourceUrl);
      if (!src) return;
      // Свернутая группа: вкладка в неё ушла — разворачиваем (вкладка видна)
      expandGroupForDrop(g.id);
      const batch = dragBatchUrls && dragBatchUrls.length > 1 ? dragBatchUrls : null;
      if (batch) {
        if (batch.some(u => {
          const t = allTabs.find(x => x.url === u);
          return !t || tabGroupOf(t) !== g.id;
        })) {
          chrome.runtime.sendMessage({ action: 'place-tabs', urls: batch,
            anchorUrl: null, side: 'after', groupId: g.id });
        }
      } else if (src.groupId !== g.id) {
        chrome.runtime.sendMessage({ action: 'place-tab', index: allTabs.indexOf(src),
          anchorIndex: null, side: 'after', groupId: g.id });
      }
    }
  });

  bar.addEventListener('click', () => {
    if (bar.dataset.pressBtn) return; // press начался на кнопке и сошёл на шапку — не сворачиваем
    if (pendingGbarClickAfterDrag) {
      // Ложный клик по шапке: браузер генерирует его в момент дропа —
      // до dragend источника, либо позже (медленная перерисовка — за
      // 500ms-окном lastDragEndAt) — гасим ровно один; реальное нажатие
      // сначала прогонит document-mousedown, который сбросит флаг раньше клика
      pendingGbarClickAfterDrag = false;
      return;
    }
    if (Date.now() - lastDragEndAt < 500) return; // backstop: клик сразу после дропа — не сворачиваем
    toggleGroupCollapsed(g.id);
  });
  tabsList.appendChild(bar);
}

// Число ВИДИМЫХ карточек группы в #tabs-list (схваченная во время драга
// остаётся видимой — считается: пока своя карточка в сетке, собственная
// шапка не вооружается; свёрнутая группа — карточек в DOM нет → 0). По нему
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
    if (!src) return;
    const batch = dragBatchUrls && dragBatchUrls.length > 1 ? dragBatchUrls : null;
    if (batch) {
      // Выделенный батч — в группу целиком, если хоть одна его вкладка не там
      if (batch.some(u => {
        const t = allTabs.find(x => x.url === u);
        return !t || tabGroupOf(t) !== g.id;
      })) {
        chrome.runtime.sendMessage({ action: 'place-tabs', urls: batch,
          anchorUrl: null, side: 'after', groupId: g.id });
      }
    } else if (src.groupId !== g.id) {
      chrome.runtime.sendMessage({ action: 'place-tab', index: allTabs.indexOf(src),
        anchorIndex: null, side: 'after', groupId: g.id });
    }
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

// Дроп вкладки В группу: развёртываем Свёрнутую группу, чтобы вставленная
// вкладка была видна (запись blattam-groups → onChanged → перерисовка).
// No-op, если группа не свёрнута (или неизвестна).
function expandGroupForDrop(groupId) {
  if (groupId == null) return;
  const g = allGroups.find(x => x.id === groupId);
  if (g && g.collapsed) {
    g.collapsed = false;
    chrome.storage.sync.set({ 'blattam-groups': allGroups });
  }
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

// ☑ — выбрать/снять выбор ВСЕХ негрупповых вкладок активного пространства
// (секция «Без группы»; как у групп — независимо от поиска). Все члены уже
// выделены — снять всех, иначе — выделить всех.
function toggleLooseSelection() {
  const urls = allTabs.filter(t => t.spaceId === activeSpaceId && isLooseTab(t)).map(t => t.url);
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

// Reorder пространств: вырезаем перетаскиваемое пространство из глобального
// allSpaces и вставляем до/после цели (side — по половине целевого чипа).
// Порядок чипов = порядок массива blattam-spaces. Drop на себя — no-op.
// Активное пространство и blattam-last-space НЕ меняются. Запись в
// blattam-spaces → onChanged → перерисовка чипов.
function reorderSpaces(fromId, toId, side) {
  const from = allSpaces.findIndex(x => x.id === fromId);
  const to = allSpaces.findIndex(x => x.id === toId);
  if (from === -1 || to === -1 || from === to) return;
  const src = allSpaces[from];
  // no-op-guard: результат сначала на КОПИИ — если последовательность id
  // не изменилась (чип брошен в собственный слот), записи в storage не идёт
  // (ни лишняя перерисовка, ни лишнее событие onChanged)
  const reordered = allSpaces.slice();
  reordered.splice(from, 1);
  let insertAt = reordered.findIndex(x => x.id === toId);
  if (side === 'after') insertAt += 1;
  reordered.splice(insertAt, 0, src);
  if (reordered.every((x, i) => x.id === allSpaces[i].id)) return;
  allSpaces.splice(from, 1);
  insertAt = allSpaces.findIndex(x => x.id === toId);
  if (side === 'after') insertAt += 1;
  allSpaces.splice(insertAt, 0, src);
  chrome.storage.sync.set({ 'blattam-spaces': allSpaces });
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
      chrome.storage.local.set({ 'blattam-tabs': allTabs });
      renderTabs(searchInput.value);
    }
  });

  // Кнопка редактирования (hover-контрол, снизу-справа) — клик СРАЗУ открывает
  // модалку редактирования (промежуточное меню «Изменить» убрано).
  const editBtn = document.createElement('button');
  editBtn.className = 'tab-edit';
  editBtn.title = 'Редактировать вкладку';
  editBtn.textContent = '\u270E';
  editBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    openEditTabModal(tab);
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
    // Ложный post-drop-клик (без mousedown) рождается в момент дропа —
    // гасим ровно один; настоящее нажатие сначала прогонит mousedown
    if (pendingCardClickAfterDrag) { pendingCardClickAfterDrag = false; return; }
    openUrl(tab.url);
  });

  // Drag & drop: карточку можно перетащить на чип пространства (переместить)
  // или в зазор между карточками (reorder — глобальные обработчики ниже)
  card.draggable = true;
  // Hover-кнопки (чекбокс/✕/✎) не стартуют drag — то же, что у шапки группы.
  guardDragOverButtons(card, '.tab-select, .tab-remove, .tab-edit');
  card.addEventListener('dragstart', (e) => {
    if (!card.draggable) { e.preventDefault(); return; } // press начался на кнопке
    // Нативный HTML5-драг заменён pointer-системой (см. «Pointer drag» ниже):
    // preventDefault отменяет нативный drag-образ и всю нативную ленту
    // dragover/drop/dragend в реальном Chrome. Синтетическая диспетч-цепочка
    // DragEvent (тест-харнесс) проходит через этот же обработчик и работает
    // без изменений.
    e.preventDefault();
    if (e.isTrusted) return; // trusted dragstart — нативный HTML5-драг отменён preventDefault,
    // цикл ведёт pointer-путь (см. «Pointer drag»); синтетический dragstart харнесса идёт дальше
    e.dataTransfer.setData('text/plain', String(allTabs.indexOf(tab)));
    e.dataTransfer.effectAllowed = 'move';
    beginCardDrag(tab, card);
  });
  card.addEventListener('dragend', () => endCardDrag(card));
  pdBindCard(card, tab); // pointer-путь (реальный Chrome) — см. «Pointer drag»

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
  if (dragWrapHiddenCard && !dragWrapHiddenCard.isConnected) { dragWrapHiddenCard = null; dragWrapHiddenGroup = null; }
  // Холдеры последней строки (row-keeper) унесены с DOM — сбрасываем трекер,
  // чтобы следующий dragover драга прицепил их заново
  dragRowKeepers.forEach(k => { if (k.isConnected) k.remove(); });
  dragRowKeepers = [];
  dragRowKeeperSection = null;

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

    const lname = document.createElement('span');
    lname.className = 'loose-name';
    lname.textContent = 'Без группы';
    lbl.appendChild(lname);

    // ☑ — выбрать/снять выбор ВСЕХ негрупповых вкладок пространства
    // (аналог ☑ шапки группы; проверяет ПОЛНЫЙ набор, а не видимые)
    const looseAllUrls = sTabs.filter(t => isLooseTab(t)).map(t => t.url);
    const lselect = document.createElement('button');
    lselect.className = 'loose-select';
    lselect.textContent = '\u2611';
    lselect.title = 'Выбрать все вкладки без группы';
    if (looseAllUrls.length > 0 && looseAllUrls.every(u => selectedUrls.has(u))) lselect.classList.add('on');
    lselect.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleLooseSelection();
    });
    lbl.appendChild(lselect);
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

// Чип принимает карточку (перетаскиваемая шапка группы — no-op) и принимает
// чип-реorder: тёплая заглушка чипа .space-ghost-slot — как ghost-slot карточек.
// Исходный чип скрыт (display:none), заглушка ходит за курсором в ряду:
// левая половина целевого чипа — заглушка перед целью, правая — после
// (reorderSideX). 2px-линия на кромке цели убрана — боковых классов на чипах
// при drag чипа нет; единственный индикатор — заглушка. Семантика дропа
// карточки не тронута.
function attachSpaceDrop(chip, spaceId) {
  chip.addEventListener('dragover', (e) => {
    if (dragSourceSpaceId) {
      if (dragSourceSpaceId === spaceId) return; // на себя — не цель
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const side = reorderSideX(chip, e.clientX);
      dragOverChipTarget = chip;
      dragOverChipSide = side;
      moveSpaceGhostSlot({ el: chip, side: side });
      return;
    }
    if (dragSourceGroupId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    chip.classList.add('drag-over');
  });
  chip.addEventListener('dragleave', () => chip.classList.remove('drag-over'));
  chip.addEventListener('drop', (e) => {
    e.preventDefault();
    chip.classList.remove('drag-over');
    if (dragSourceSpaceId) {
      // Ложный клик по цели генерируется в этот момент (до dragend источника):
      // вооружаем one-shot-подавление; chip-заглушка снимается СОБСТВЕННЫМ
      // drop-хендлером (drop чипа не проходит через глобальный document drop),
      // затем reorder
      pendingChipClickAfterDrag = true;
      removeSpaceGhostSlot();
      e.stopPropagation(); // дроп по чипу закоммичен здесь — хендлер ряда
                           // #space-chips не должен коммитить повторно
      reorderSpaces(dragSourceSpaceId, spaceId, reorderSideX(chip, e.clientX));
      return;
    }
    if (dragSourceGroupId) return;
    const batch = dragBatchUrls;
    if (batch && batch.length > 1) {
      // Выделенный батч: уезжают все выделенные вкладки (в пространство, без группы)
      for (const u of batch) {
        const tab = allTabs.find(t => t.url === u);
        if (tab) moveTabTo(tab, spaceId, undefined);
      }
      return;
    }
    const idx = parseInt(e.dataTransfer.getData('text/plain'), 10);
    const tab = allTabs[idx];
    if (tab) moveTabTo(tab, spaceId, undefined);
  });
}

// === Drag & drop: перестановка карточек (reorder), BlatTabs-style ===
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

// Row keeper УБРАН: схваченная карточка скрыта инлайновым display:none, но
// тёплая заглушка (тот же размер, сразу после карточки) занимает её слот — при
// захвате рефлоу нет; когда заглушка уезжает от дома, соседи закрывают
// высвобожденный слот естественным reflow сетки (FLIP-слайд на pointer-пути).

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

// Ghost-slot чипа: тёплая заглушка размера чипа (высота 26px, радиус чипа)
// в ряду #space-chips — ЕДИНСТВЕННЫЙ индикатор вставки при reorder чипов
// (2px-линия убрана), тон и механика — как у ghost-slot карточек:
// фон --ghost-bg, пунктирный контур --ghost-ring. Инлайн-стили — в тестах
// head-стили view.html не грузятся. pointer-events:none — курсор «видит
// сквозь» заглушку (dragover падает на чипы; ряд reflow'ится естественно).
function makeSpaceGhostSlot(chip) {
  const slot = document.createElement('div');
  slot.className = 'space-ghost-slot';
  slot.draggable = false;
  slot.style.cssText =
    'pointer-events:none;box-sizing:border-box;flex:none;background:var(--ghost-bg);' +
    'border-width:1px;border-style:dashed;border-color:var(--ghost-ring);' +
    'border-radius:' + (getComputedStyle(chip).borderRadius || '9999px');
  slot.style.width = chip.offsetWidth + 'px';
  slot.style.height = chip.offsetHeight + 'px';
  return slot;
}

// Переносит chip-заглушку в потенциальный слот вставки ряда: левая половина
// целевого чипа — перед ним, правая — после; соседи сдвигаются естественным
// reflow flex-ряда (заглушка занимает один слот вместо скрытого чипа —
// число элементов ряда не меняется, хвост не дёргается).
function moveSpaceGhostSlot(anchor) {
  if (!dragSourceSpaceId || !anchor || !anchor.el) return;
  if (!dragGhostChipSlot) return;
  if (!dragGhostChipSlot.isConnected) { dragGhostChipSlot = null; return; }
  if (anchor.side === 'before') anchor.el.before(dragGhostChipSlot);
  else anchor.el.after(dragGhostChipSlot);
}

function removeSpaceGhostSlot() {
  if (dragGhostChipSlot && dragGhostChipSlot.isConnected) dragGhostChipSlot.remove();
  dragGhostChipSlot = null;
}

// Ряд пространств (#spaces-bar: span #space-chips display:contents +
// кнопка «+ Пространство» — последний элемент ряда) — цель дропа В ЛЮБОМ
// месте ряда (зазор между чипами, отступы ряда, кнопка «+ Пространство»):
// заглушка чипа pointer-events:none, поэтому дроп по заглушке/фону ряда
// промахивался мимо хендлеров чипов — dragend без дропа, чип возвращался
// домой без reorder. Как у дропа карточек (коммит в любом месте списка):
// позиция дропа = ТЕКУЩАЯ DOM-позиция заглушки (соседние .space-chip;
// кнопка «+ Пространство»/null — не цель). Drag карточки/шапки группы —
// не трогаем (dragSourceSpaceId пуст — без preventDefault, поведение
// byte-for-byte).
spacesBar.addEventListener('dragover', (e) => {
  if (!dragSourceSpaceId) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  // заглушка остаётся на последнем слоте (dragover чипов её и ставят)
});

spacesBar.addEventListener('drop', (e) => {
  if (!dragSourceSpaceId) return;
  e.preventDefault();
  e.stopPropagation(); // дроп по самому чипу уже закоммичен хендлером чипа
  const slot = dragGhostChipSlot;
  if (slot && slot.isConnected) {
    const next = slot.nextElementSibling;
    const prev = slot.previousElementSibling;
    if (next && next.classList.contains('space-chip')) {
      reorderSpaces(dragSourceSpaceId, next.dataset.spaceId, 'before');
    } else if (prev && prev.classList.contains('space-chip')) {
      reorderSpaces(dragSourceSpaceId, prev.dataset.spaceId, 'after');
    }
    // заглушка не у чипов (ряд пуст / заглушка вне ряда) — no-op
  }
  // заглушки нет (крайне короткий драг) — no-op: дроп по чипу закрывает
  // собственным хендлером чипа
  removeSpaceGhostSlot();
});

// (Row keeper и ghostDomSection убраны: схваченная карточка остаётся
// видимой — держит слот и число строк секции; тёплая заглушка её размера
// сразу после неё — индикатор слота вставки.)

// Видимые карточки для расчёта зазора: перетаскиваемая карточка исключается
// (по флагу — во время драга она остаётся видимой), индекс зазора считается по
// карточкам, которые курсор «обогнал» (собственный слот карточки в счёт не идёт)
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

// Слот самой исходной карточки (домой): в исходной секции НЕТ других видимых
// карточек (схваченная исключена из visibleCards — секция читается «пустой»),
// а курсор в полосе исходной секции (от низа её шапки до верха шапки
// следующей секции). Без проверки геометрия прыгает через полосу исходной
// секции в соседнюю — заглушка уезжает, и единственную вкладку нельзя
// вернуть на место.
function slotIsSourceHome(clientY) {
  const card = dragSourceCardEl;
  if (!card || !card.isConnected) return false;
  const srcGroup = tabGroupOf(card.__tab);
  for (const c of visibleCards())
    if (tabGroupOf(c.__tab) === srcGroup) return false;
  const header = sectionHeaderBefore(card);
  let n = card.nextElementSibling;
  while (n && !n.classList.contains('gbar') && !n.classList.contains('loose-label'))
    n = n.nextElementSibling;
  const top = header ? header.getBoundingClientRect().bottom : 0;
  const bottom = n ? n.getBoundingClientRect().top : Infinity;
  return clientY != null && clientY >= top && clientY < bottom;
}

// Позиция заглушки с учётом секций: плоский gap-индекс + Y курсора →
// {el, side}. На границе секций (карточка — первая своей секции, перед ней
// шапка): курсор НИЖЕ середины шапки — начало этой секции (заглушка после
// шапки), ВЫШЕ — конец предыдущей (заглушка до шапки). Остальные позиции —
// перед карточкой / после последней видимой.
function slotAnchor(idx, clientY) {
  const cards = visibleCards();
  if (!cards.length) return null;
  // Домашний слот исходной карточки: заглушка остаётся в слоте схваченной
  // карточки, пока курсор в полосе исходной секции (дроп туда — no-op)
  if (slotIsSourceHome(clientY)) return { el: dragSourceCardEl, side: 'after' };
  if (idx <= 0) return { el: cards[0], side: 'before' };
  if (idx >= cards.length) return { el: cards[cards.length - 1], side: 'after' };
  const card = cards[idx];
  const header = sectionHeaderBefore(card);
  if (header && tabGroupOf(card.__tab) !== tabGroupOf(cards[idx - 1].__tab)) {
    const r = header.getBoundingClientRect();
    const below = clientY == null || clientY > r.top + r.height / 2;
    if (below) return { el: header, side: 'after' };
    // «до» целевой шапки — в конец ПРЕДЫДУЩЕЙ секции (после её последней видимой
    // карточки), а не перед шапкой: между секциями могут стоять свёрнутые группы,
    // и перед шапкой заглушка встала бы в пространство НИЗКОЙ свёрнутой группы
    // (она «раскрывается» с призрачной вкладкой)
    return { el: cards[idx - 1], side: 'after' };
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
  const batch = dragBatchUrls;
  if (batch && batch.length > 1) return placeBatchToSlot(batch, anchorUrl, side, section);
  // Дроп в СВОЁ место исходной карточки (якорь — сама исходная, сторона
  // «после»): no-op — позиция и группа не меняются
  if (anchorUrl === src.url && side === 'after') return;
  let a = anchorIndex > from ? anchorIndex - 1 : anchorIndex;
  const finalAt = side === 'before' ? a : Math.min(a + 1, allTabs.length - 1);
  if (finalAt === from && section === tabGroupOf(src)) return;
  chrome.runtime.sendMessage({ action: 'place-tab', index: from, anchorIndex, side, groupId: section });
  // Свернутая группа-секция слота: вкладка в неё ушла — разворачиваем
  expandGroupForDrop(section);
}

// Перенос выделенного батча в слот: ВСЕ вкладки `batch` (порядок между ними —
// исходный) встают на позицию слота блоком и получают группу секции слота.
// Симуляция по allTabs: если порядок И группы батча не меняются — no-op
// (сообщение не шлётся, перерисовки нет).
function placeBatchToSlot(batch, anchorUrl, side, section) {
  const urlsSet = new Set(batch);
  const moved = allTabs.filter(t => urlsSet.has(t.url));
  if (!moved.length) return;
  const a = allTabs.findIndex(t => t.url === anchorUrl);
  if (a === -1) return;
  let removedBefore = 0;
  for (let i = 0; i < a; i++) if (urlsSet.has(allTabs[i].url)) removedBefore++;
  const at = Math.max(0, Math.min(allTabs.length - moved.length,
    side === 'after' ? a - removedBefore + 1 : a - removedBefore));
  const rest = allTabs.filter(t => !urlsSet.has(t.url));
  const next = rest.slice();
  next.splice(at, 0, ...moved);
  let changed = false;
  for (let i = 0; i < next.length; i++) {
    if (next[i].url !== allTabs[i].url) { changed = true; break; }
    if (urlsSet.has(next[i].url) && section !== tabGroupOf(allTabs[i])) { changed = true; break; }
  }
  if (!changed) return;
  chrome.runtime.sendMessage({ action: 'place-tabs', urls: batch, anchorUrl, side, groupId: section });
  // Свернутая группа-секция слота: батч в неё ушёл — разворачиваем
  expandGroupForDrop(section);
}

// Новое нажатие мыши — реальное действие пользователя: сбрасываем one-shot
// флаг ложного post-drop клика ДО того, как придёт его click (у ложного клика
// после drag mousedown не было)
document.addEventListener('mousedown', () => { pendingGbarClickAfterDrag = false; pendingChipClickAfterDrag = false; pendingCardClickAfterDrag = false; pendingBtClickAfterDrag = false; }, true);

// Глобальные dragover/drop: нативный drag-образ браузера следует за курсором,
// заглушка — в ближайшую позицию вставки (с учётом секций). Свою семантику дропа
// карточки сохранили чип пространства (заглушка над ним замирает) и шапка группы /
// слот пустой группы (вкладка уходит В группу) — над последними заглушку прячем
// целиком: ни «тёплая» заглушка на старом месте, ни дырка на её месте не остаётся.
// Прячет/показывает заглушку по display: display:none освобождает её ячейку
// сетки (сетка перетекает — дырки нет), display:'' возвращает слот. Элемент НЕ
// удаляем из DOM, чтобы moveGhostSlot мог вернуть его в позицию вставки.
function setGhostDisplay(v) {
  if (dragGhostSlot) dragGhostSlot.style.display = v;
}

// Пустая полоса центр.сетки #tabs-list — пространство МЕЖДУ видимыми
// строками карточек, во ВСЕХ секциях (группы + негрупповая): (A) между
// низом шапки секции (.gbar / .loose-label / верх списка) и верхом её
// первой видимой строки; (B) между низом последней видимой строки и верхом
// шапки следующей секции (.gbar — свёрнутой/развёрнутой / .loose-label /
// #add-group-btn / низ списка); (C) вертикальный зазор сетки (row-gap)
// между двумя строками карточек внутри секции. Над полосой — как над
// шапкой: заглушка прячется ЦЕЛИКОМ, дроп — отмена (вкладка возвращается
// в исходный слот, storage не тронут). Пустые ячейки СВОЙ строки (справа
// от последней карточки незаполненной строки, та же полоса Y) — НЕ полоса:
// заглушка остаётся видимой в потенциальном слоте. Видимая заглушка, слот
// пустой группы и row-keeper ЗАНИМАЮТ строку — их строки заняты (иначе
// курсор над собственной строкой заглушки прятал бы её и схлопывал сетку).
// Возвращает id секции под курсором (groupId; «loose» — негрупповая) или null.
function cardAreaEmptyBand(clientX, clientY) {
  if (clientX == null || clientY == null) return null;
  const lr = tabsList.getBoundingClientRect();
  if (clientX < lr.left || clientX > lr.right) return null;
  const g = (dragGhostSlot && dragGhostSlot.isConnected && dragGhostSlot.style.display !== 'none')
    ? dragGhostSlot.getBoundingClientRect() : null;
  const gidOf = el => el.classList.contains('gbar')
    ? (el.dataset.groupId || null) : 'loose';
  const isHeader = el => el.classList.contains('gbar') || el.classList.contains('loose-label');
  // Секции по шапкам в DOM-порядке; содержимое до первой шапки —
  // негрупповая секция без шапки (#add-group-btn — терминатор, не содержимое)
  const sections = [];
  let cur = null;
  for (const el of tabsList.children) {
    if (el.id === 'add-group-btn') { if (cur) cur.nextEl = el; continue; }
    if (isHeader(el)) {
      cur = { id: gidOf(el), topEl: el, nextEl: null, items: [] };
      sections.push(cur);
    } else {
      if (!cur) { cur = { id: 'loose', topEl: null, nextEl: null, items: [] }; sections.push(cur); }
      cur.items.push(el);
    }
  }
  for (let i = 0; i < sections.length; i++) {
    const s2 = sections[i];
    const next = s2.nextEl || (i < sections.length - 1 ? sections[i + 1].topEl : null);
    s2.topBound = s2.topEl ? s2.topEl.getBoundingClientRect().bottom : lr.top;
    s2.nextTop = next ? next.getBoundingClientRect().top : lr.bottom;
  }
  for (const s2 of sections) {
    // Занятые строки секции: видимые карточки + видимая заглушка в ней +
    // слот пустой группы. Row-keeper НЕ занимает строку для полос:
    // он невидим — его строка остаётся пустой полосой (заглушка там
    // спрятана, дроп — отмена)
    const rows = [];
    const addRow = (r) => {
      if (!r || r.height <= 0) return;
      const last = rows[rows.length - 1];
      if (last && Math.abs(last.top - r.top) < 1) { if (r.bottom > last.bottom) last.bottom = r.bottom; }
      else rows.push({ top: r.top, bottom: r.bottom });
    };
    for (const el of s2.items) {
      if (el.classList.contains('tab-card') && el.style.display !== 'none') addRow(el.getBoundingClientRect());
      else if (el.classList.contains('group-empty-slot')) addRow(el.getBoundingClientRect());
    }
    if (g && ghostSlotSectionId() === (s2.id === 'loose' ? null : s2.id)) addRow(g);
    rows.sort((a, b) => a.top - b.top);
    const inBand = (y1, y2) => clientY > y1 && clientY < y2;
    const res = s2.id === 'loose' ? 'loose' : s2.id;
    if (!rows.length) {
      if (inBand(s2.topBound, s2.nextTop)) return res;
      continue;
    }
    if (inBand(s2.topBound, rows[0].top)) return res;
    for (let i = 0; i + 1 < rows.length; i++)
      if (inBand(rows[i].bottom, rows[i + 1].top)) return res;
    if (inBand(rows[rows.length - 1].bottom, s2.nextTop)) return res;
  }
  return null;
}

document.addEventListener('dragover', (e) => {
  if (!dragSourceUrl || dragSourceGroupId || !e.dataTransfer) return;
  // Логика слежения за заглушкой — в trackCardDragAt (общая с pointer-путём).
  // preventDefault/dropEffect — только там, где и раньше: над шапкой/слотом
  // пустой группы, пустой полосой карт.области и в пределах списка.
  if (trackCardDragAt(e.clientX, e.clientY, e.target)) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }
});

document.addEventListener('drop', (e) => {
  if (!dragSourceUrl || dragSourceGroupId || !e.dataTransfer) return;
  const t = e.target;
  if (!t || !tabsList.contains(t)) return;
  if (t.closest && t.closest('.gbar')) return; // дроп на шапку группы — карточка не переезжает через неё
  if (t.closest && t.closest('.group-empty-slot')) return; // слот пустой группы — свой обработчик шлёт, глобальный не должен
  // Пустая полоса сетки (между строками карточек) — ОТМЕНА: no place-tab /
  // place-tabs — вкладка возвращается в исходный слот на dragend (storage не
  // тронут); заглушка снимается, карточка и холдеры — в endCardDrag
  if (cardAreaEmptyBand(e.clientX, e.clientY)) {
    e.preventDefault();
    removeGhostSlot();
    return;
  }
  const src = allTabs.find(tb => tb.url === dragSourceUrl);
  if (!src) return;
  e.preventDefault();
  placeCardToSlot(src, slotAnchor(cardGapIndex(e.clientX, e.clientY), e.clientY));
  removeGhostSlot();
});

// === Карточка → правая рейка: открыть сохранённый сайт новой фоновой вкладкой ===
// Дроп сохранённой карточки по #rail-right — сайт открывается новой фоновой
// вкладкой (chrome.tabs.create, active:false). Сама карточка НЕ меняется:
// без place-tab/place-tabs, без записи в blattam-tabs — она остаётся в своём
// слоте сетки (оба пути драга: HTML5-дроп рейки ниже + commitCardDropAt
// pointer-пути). Выделенный батч: все выделенные сайты открываются фоном.
function openSavedUrlsInBackground(urls) {
  if (!chrome.tabs || typeof chrome.tabs.create !== 'function') return;
  for (const url of urls || []) {
    if (!url) continue;
    try { chrome.tabs.create({ url: url, active: false }); } catch (_) {}
  }
}

// HTML5-путь: рейка — цель дропа только для драга КАРТОЧКИ (dragSourceUrl).
// Собственный драг рейки (dragSourceBrowserTab) идёт своими глобальными
// обработчиками — здесь не трогаем; глобальный document-дроп по рейке не
// коммитится (он принимает только #tabs-list) — двойного срабатывания нет.
// dragover-предупреждение (preventDefault) рейка даёт сама — иначе браузер
// не разрешит drop на ней.
if (railRight) {
  railRight.addEventListener('dragover', (e) => {
    if (!dragSourceUrl || dragSourceGroupId || !e.dataTransfer) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    railRight.classList.add('rail-drag-over'); // тёплый тон: рейка принимает карточку
  });
  // Курсор ушёл с рейки — тёплый тон снят (endCardDrag — страховка на dragend)
  railRight.addEventListener('dragleave', () => {
    railRight.classList.remove('rail-drag-over');
  });
  railRight.addEventListener('drop', (e) => {
    if (!dragSourceUrl || dragSourceGroupId || !e.dataTransfer) return;
    const src = allTabs.find(tb => tb.url === dragSourceUrl);
    if (!src) return;
    e.preventDefault();
    railRight.classList.remove('rail-drag-over'); // коммит — тёплый тон снят
    const urls = (dragBatchUrls && dragBatchUrls.length > 1) ? dragBatchUrls : [src.url];
    openSavedUrlsInBackground(urls);
    removeGhostSlot(); // dragend/endCardDrag довершит очистку
  });
}

// Ядро драга карточки, общее для HTML5-обработчиков и pointer-пути.
// Захват карточки: исходник + флаги ложного клика + батч выбора, затем
// ставим тёплую заглушку (ghost-slot) ПОСЛЕ карточки и прячем саму
// карточку (display:none) — исходник вырван из сетки, единственная видимая
// копия — под курсором (pointer-путь: LIFT-клон .pd-clone; HTML5-путь:
// нативный drag-образ браузера). sync=true — синхронно (pointer-путь);
// HTML5-путь сохраняет отложенное создание setTimeout(0) (хид в момент
// trusted dragstart может заклинить нативный драг — known Chrome quirk).
function beginCardDrag(tab, cardEl, sync) {
  dragSourceUrl = tab.url;
  dragSourceCardEl = cardEl;
  dragOverTarget = null; // свежий драг — целевой dragover ещё не приходил
  dragOverTargetXY = null;
  // Вооружаем подавление ложного клика по шапке уже на dragstart: реальный
  // Chrome генерирует его на drop-цели ДО dragend источника — флаг, поставленный
  // только на dragend, его не поймаешь
  pendingGbarClickAfterDrag = true;
  pendingCardClickAfterDrag = true; // дроп на другую карточку — ложный клик её не открывает
  // Выделенный батч: перетаскивая ЛЮБУЮ выделенную карточку, переезжают ВСЕ
  // выделенные вкладки (батч — в исходном порядке). В рендере — как одна:
  // скрыта только захваченная карточка (display:none), заглушка одна,
  // остальные выделенные карточки остаются видимыми.
  dragBatchUrls = (selectedUrls.size > 1 && selectedUrls.has(tab.url))
    ? allTabs.filter(t => selectedUrls.has(t.url)).map(t => t.url)
    : [tab.url];
  cardEl.classList.add('dragging');
  dragCardSize = { w: cardEl.offsetWidth, h: cardEl.offsetHeight }; // до хайда в applyGhost
  // Состояние «идёт перетаскивание карточки» — для тонировки шапок групп при hover
  document.body.classList.add('dragging-card');
  const applyGhost = () => {
    // Перерисовка во время драга уносит карточку из DOM, а поздний drop/dragend
    // уже решил драг — заглушку для отсоединённой карточки не вставляем
    if (dragSourceUrl !== tab.url || !cardEl.isConnected) return;
    if (!dragGhostSlot) {
      dragGhostSlot = makeGhostSlot(cardEl);
      cardEl.insertAdjacentElement('afterend', dragGhostSlot);
    }
    // Исходник вырван из сетки (тот же паттерн, что рейка/чип-пути: хайд
    // ПОСЛЕ синхронной вставки той же заглушки — без рефлоу): видимая копия
    // только одна — под курсором (pointer-путь: LIFT-клон, его cssText
    // перезаписан pdCreateClone целиком, клон виден; HTML5: нативный
    // drag-образ). Возврат — в endCardDrag (cardEl.style.display = '').
    cardEl.style.display = 'none';
    // Гонка: первый dragover мог попасть на шапку/слот/пустую полосу карт.области
    // группы ПЕРЕД этим таймером (заглушки ещё не существовало). Повторяем
    // состояние по dragOverTarget (зона — по её координатам), иначе свежая
    // заглушка неверно «замигает» дома.
    const overGbarOrSlot = dragOverTarget && dragOverTarget.closest &&
        (dragOverTarget.closest('.gbar') || dragOverTarget.closest('.group-empty-slot'));
    const overRail = dragOverTarget && dragOverTarget.closest &&
        dragOverTarget.closest('#rail-right');
    const overEmptyBand = dragOverTargetXY !== null &&
        cardAreaEmptyBand(dragOverTargetXY[0], dragOverTargetXY[1]) !== null;
    if (overGbarOrSlot || overRail || overEmptyBand) {
      setGhostDisplay('none');
    }
    syncSourceRowKeeper(); // заглушка дома ИЛИ спрятана на старте — пересчёт холдеров
  };
  if (sync) applyGhost();
  else setTimeout(applyGhost, 0);
}

// Конец драга карточки (dragend / конец pointer-драга): заглушка снимается
// первой, затем карточка возвращается в свой слот, сброс исходника и флагов
// ложных кликов.
function endCardDrag(cardEl) {
  lastDragEndAt = Date.now();
  pendingGbarClickAfterDrag = true;
  dragSourceUrl = null;
  dragSourceCardEl = null;
  dragCardSize = null;
  dragBatchUrls = null;
  dragOverTarget = null; // не держим ссылку на DOM-узел после драга
  dragOverTargetXY = null;
  restoreWrapHiddenCard(); // «row-full» группа: вернуть временно скрытую крайнюю карточку
  removeSourceRowKeeper(); // холдеры последней строки — снять (dragend / Escape / cancel)
  // Снимаем состояние «идёт перетаскивание карточки» (тонировка шапок групп)
  document.body.classList.remove('dragging-card');
  if (cardEl) {
    cardEl.classList.remove('dragging');
    cardEl.style.cursor = '';
    removeGhostSlot(); // заглушка снимается первой, затем карточка
                       // возвращается в свой слот
    if (cardEl.isConnected) cardEl.style.display = ''; // возврат карточки (во время драга скрыта display:none)
  }
  document.querySelectorAll('.space-chip.drag-over').forEach(c => c.classList.remove('drag-over'));
  if (railRight) railRight.classList.remove('rail-drag-over'); // рейка: тёплый тон не «залипает» после dragend
}

// === «row-full» группа: заглушка не доращивает новую строку ===
// Драг карточки: тёплая заглушка внутри группы, строки которой ПОЛНЫЕ (число
// реальных карточек группы кратное числу колонок сетки), дорастила бы НОВУЮ
// строку. Чтобы число строк группы осталось постоянным, временно скрываем
// крайнюю карточку группы — заглушка занимает её клетку. Карточка возвращается:
// заглушка ушла из группы / заглушка скрыта (шапка / слот / пустая зона) / драг
// закончился / перерисовка. Новая строка появляется только на реальном дропе
// (в группу уходит настоящая карточка). Только группы: loose-секция — как была.
function gridColumnCount() {
  const cs = getComputedStyle(tabsList);
  if (cs.display !== 'grid') return 0; // не сетка — понятие «полных строк» не применимо
  const gtc = cs.gridTemplateColumns;
  return (gtc && gtc !== 'none') ? gtc.trim().split(/\s+/).length : 0;
}

// Крайняя видимая карточка группы (кроме перетаскиваемой).
function lastVisibleGroupCard(gid) {
  const cards = [...document.querySelectorAll('#tabs-list .tab-card')]
    .filter(c => c.__tab && c.__tab.groupId === gid && c !== dragSourceCardEl &&
                 c.style.display !== 'none');
  return cards.length ? cards[cards.length - 1] : null;
}

function restoreWrapHiddenCard() {
  if (dragWrapHiddenCard) {
    if (dragWrapHiddenCard.isConnected) dragWrapHiddenCard.style.display = '';
    dragWrapHiddenCard = null;
    dragWrapHiddenGroup = null;
  }
}

// === Холдер последней строки исходной секции (row-keeper) ===
// Заглушка УЕХАЛА из исходной секции (в другую секцию или спрятана над
// .gbar / .group-empty-slot / пустой полосой карт.области) — вырванная
// карточка высвободила свою клетку, и последняя строка секции может
// СХОЛОНТЬСЯ, сдвинув всё, что ниже. Пока число строк секции уменьшается,
// хвост держит невидимая карточка-заглушка (.tab-row-keeper, opacity:0,
// pointer-events:none; НЕ .tab-card — groupVisibleCardCount и вооружение
// шапок групп её не видят). Заглушка ВНУТРИ секции — холдер не нужен:
// она сама занимает клетку. Холдер ставится в ХВОСТ исходной секции
// (после последней видимой карточки, после её .gbar, если видимых
// карточек нет, перед #add-group-btn в негрупповой секции) и снимается,
// когда заглушка возвращается в секцию / драг закончился / перерисовка.
// Размер — размер схваченной карточки (dragCardSize, снят до хайда).
// Визуально это «пустая» строка держится всё время драга — удобно для
// быстрого перетаскивания: пространство ниже не елозится.
function ghostSlotSectionId() {
  const g = dragGhostSlot;
  if (!g || !g.isConnected || g.style.display === 'none') return null;
  for (let el = g.previousElementSibling; el; el = el.previousElementSibling) {
    if (el.classList.contains('tab-row-keeper') ||
        el.classList.contains('tab-ghost-slot')) continue;
    if (el.classList.contains('gbar') || el.classList.contains('group-empty-slot'))
      return el.dataset.groupId || null;
    if (el.classList.contains('tab-card')) return el.__tab ? tabGroupOf(el.__tab) : null;
    return null; // .loose-label, «+ Группа» и прочее — негрупповая секция
  }
  return null; // заглушка до первого ребёнка списка — негрупповая секция
}

function makeRowKeeper() {
  const k = document.createElement('div');
  k.className = 'tab-row-keeper';
  k.style.cssText = 'opacity:0;pointer-events:none;';
  const s = dragCardSize;
  if (s && s.w) k.style.width = s.w + 'px';
  if (s && s.h) k.style.height = s.h + 'px';
  return k;
}

function removeSourceRowKeeper() {
  dragRowKeepers.forEach(k => { if (k.isConnected) k.remove(); });
  dragRowKeepers = [];
  dragRowKeeperSection = null;
}

// Пересчёт холдеров после перемещения/скрытия заглушки: подключаются ТОЛЬКО
// когда заглушка НЕ занимает клетку в исходной секции И число отрисованных
// строк этой секции без холдеров МЕНЬШЕ rOrig = ceil(nFull / cols)
// (nFull — ПОЛНОЕ число карточек источника, включая вырванную). Число
// холдеров = rOrig − текущие строки (обычно 1). Не сетка (cols 0) — нет.
function syncSourceRowKeeper() {
  if (!dragSourceUrl || !dragSourceCardEl || !dragSourceCardEl.isConnected) {
    removeSourceRowKeeper();
    return;
  }
  const src = allTabs.find(t => t.url === dragSourceUrl);
  const srcGid = src ? tabGroupOf(src) : null;
  const g = dragGhostSlot;
  const ghostVisible = !!(g && g.isConnected && g.style.display !== 'none');
  if (ghostVisible && ghostSlotSectionId() === srcGid) {
    removeSourceRowKeeper(); // заглушка в секции — сама держит клетку
    return;
  }
  const cols = gridColumnCount();
  if (!cols) { removeSourceRowKeeper(); return; }
  const nFull = allTabs.filter(t => t.spaceId === activeSpaceId && tabGroupOf(t) === srcGid).length;
  const rOrig = Math.ceil(nFull / cols);
  const visible = [...document.querySelectorAll('#tabs-list .tab-card')]
    .filter(c => c !== dragSourceCardEl && c.style.display !== 'none' &&
                 (c.__tab ? tabGroupOf(c.__tab) : null) === srcGid);
  const keepersNeeded = Math.max(0, rOrig - Math.ceil(visible.length / cols));
  if (keepersNeeded === 0) { removeSourceRowKeeper(); return; }
  if (dragRowKeeperSection !== srcGid) removeSourceRowKeeper();
  let anchorEl = null;
  if (srcGid != null) {
    anchorEl = lastVisibleGroupCard(srcGid) ||
      document.querySelector('#tabs-list .gbar[data-group-id="' + srcGid + '"]');
  } else {
    anchorEl = document.getElementById('add-group-btn');
  }
  if (!anchorEl) { removeSourceRowKeeper(); return; }
  while (dragRowKeepers.length < keepersNeeded) {
    const k = makeRowKeeper();
    if (srcGid != null) anchorEl.after(k); else anchorEl.before(k);
    dragRowKeepers.push(k);
  }
  while (dragRowKeepers.length > keepersNeeded) {
    const k = dragRowKeepers.pop();
    if (k.isConnected) k.remove();
  }
  dragRowKeeperSection = srcGid;
}

// Заглушка в группе (anchor — {el, side}): после вставки заглушки группа дорастёт
// НОВУЮ строку — держим скрытой крайнюю карточку (одна и та же, пока заглушка внутри
// группы); иначе — вернуть ранее скрытую. Loose (null) — тоже вернуть.
// Критерий: ПОЛНОЕ число карточек группы nFull (allTabs активного
// пространства, включая перетаскиваемую) — драг внутри группы не меняет числа карточек в ней и новая строка вне возникает; растёт
// только внешняя карточка: видимые + 1 (заглушка) > rOrig*cols.
function updateWrapHiddenCard(anchor) {
  const gid = slotSection(anchor);
  if (gid == null) { restoreWrapHiddenCard(); return; }
  if (dragWrapHiddenCard && dragWrapHiddenGroup === gid &&
      dragWrapHiddenCard.isConnected && dragWrapHiddenCard.style.display === 'none') return;
  restoreWrapHiddenCard();
  const cols = gridColumnCount();
  if (!cols) return; // не сетка — без временного скрытия
  const nFull = allTabs.filter(t => t.spaceId === activeSpaceId && tabGroupOf(t) === gid).length;
  const rOrig = Math.ceil(nFull / cols); // строк группы в до-переносной раскладке
  const visible = [...document.querySelectorAll('#tabs-list .tab-card')]
    .filter(c => c.__tab && c.__tab.groupId === gid && c !== dragSourceCardEl &&
                 c.style.display !== 'none');
  const hideCount = (visible.length + 1) - rOrig * cols; // +1 — клетка заглушки
  if (hideCount > 0) {
    const last = lastVisibleGroupCard(gid);
    if (last) {
      last.style.display = 'none';
      dragWrapHiddenCard = last;
      dragWrapHiddenGroup = gid;
    }
  }
}

// Tracks the card drag at coordinates (clientX, clientY): ghost hidden (over
// .gbar / .group-empty-slot / group card-area empty zone), frozen (over a
// space chip) or moved (slot in the list). Returns true when the point is a
// valid card-drag position (HTML5 dragover needs preventDefault there).
// targetEl — event target (HTML5 path); the pointer path passes null and the
// target is resolved via document.elementFromPoint.
function trackCardDragAt(clientX, clientY, targetEl) {
  if (!dragSourceUrl || dragSourceGroupId) return false;
  const t = targetEl || document.elementFromPoint(clientX, clientY);
  // Тёплый тон правой рейки — цель дропа карточки (открыть сайт фоновой
  // вкладкой). Рейка лежит вне #tabs-list, поэтому проверка стоит ДО всех
  // веток (работает независимо от попадания в список) и сама снимает класс,
  // когда курсор уходит с рейки (любой другой target).
  dragOverTarget = t;
  dragOverTargetXY = [clientX, clientY];
  if (railRight) {
    if (t && t.closest && t.closest('#rail-right')) {
      railRight.classList.add('rail-drag-over');
      // Призрак спрятан целиком — рейка за пределами #tabs-list, у слота нет
      // валидного места вставки (тот же паттерн, что .gbar/.group-empty-slot);
      // строка исходной секции держится условным холдером.
      setGhostDisplay('none');
      restoreWrapHiddenCard(); // заглушка скрыта — новая строка не видна
      syncSourceRowKeeper(); // заглушка спрятана — исходная секция держит строку холдером
      return true;
    }
    railRight.classList.remove('rail-drag-over');
  }
  // Over ANY group header (.gbar) and over an empty-group slot
  // (.group-empty-slot) the card drops INTO that group (own drop handler on
  // the element) — hide the ghost WHOLLY. NOT removeGhostSlot: deferred ghost
  // creation is only in dragstart, a removed ghost never reappears.
  if (t && t.closest && (t.closest('.gbar') || t.closest('.group-empty-slot'))) {
    setGhostDisplay('none');
    restoreWrapHiddenCard(); // заглушка скрыта — новая строка не видна
    syncSourceRowKeeper(); // заглушка спрятана — исходная секция держит строку холдером
    return true;
  }
  // Space chip: ghost stands still in place (behavior unchanged).
  if (t && t.closest && t.closest('.space-chip')) return false;
  // Пустая полоса сетки (полоса А/В/С над любой секцией: выше первой
  // строки / ниже последней / row-gap между строками): hide the ghost wholly.
  // Empty cells of its OWN row — not a band: ghost stays visible in the
  // potential slot (list path below).
  if (cardAreaEmptyBand(clientX, clientY) !== null) {
    setGhostDisplay('none');
    restoreWrapHiddenCard(); // заглушка скрыта — новая строка не видна
    syncSourceRowKeeper(); // заглушка спрятана — исходная секция держит строку холдером
    return true;
  }
  if (!t || !tabsList.contains(t)) return false;
  const anchor = slotAnchor(cardGapIndex(clientX, clientY), clientY);
  setGhostDisplay('');
  if (anchor) {
    // «row-full» группа: до переноса заглушки (и снимка FLIP) держим/снимаем
    // временное скрытие крайней карточки — её рефлоу войдёт в стартовую
    // позицию FLIP-слайда
    updateWrapHiddenCard(anchor);
    // FLIP (pointer path ONLY): when the slot anchor actually CHANGES — record
    // rects of the visible cards before the move, then apply the slide
    // transform after it. One FLIP pass per anchor change. The synthetic
    // HTML5 path never FLIPs — its geometry is untouched.
    const changed = pd && pd.armed &&
        (!pdLastAnchor || pdLastAnchor.el !== anchor.el || pdLastAnchor.side !== anchor.side);
    const firstRects = changed ? snapshotCardRects() : null;
    moveGhostSlot(anchor);
    pdLastAnchor = anchor;
    if (firstRects) applyFlipFrom(firstRects);
  } else {
    restoreWrapHiddenCard(); // заглушка не вставлена — скрытую карточку вернуть
  }
  syncSourceRowKeeper(); // заглушка переехала (или осталась) — пересчёт холдеров
  return true;
}

// FLIP: record rects of visible elements (the drag source is excluded).
// Без аргументов — карточки #tabs-list (card path); selector + excludeEl —
// chip path ('#space-chips .space-chip', скрытый исходный чип).
function snapshotCardRects(selector, excludeEl) {
  const m = new Map();
  const scope = selector || '#tabs-list .tab-card';
  for (const c of document.querySelectorAll(scope)) {
    if (c === excludeEl || c === dragSourceCardEl || c.style.display === 'none') continue;
    m.set(c, c.getBoundingClientRect());
  }
  return m;
}

// FLIP, dnd-kit style (Toby original: transform 200ms ease, same-frame retargeting):
// after the reflow (ghost slot moved) — layout position = post-rect MINUS the in-flight
// transform (getComputedStyle matrix, may be mid-interpolation); the inverse transform
// (pre-reflow visual - layout) is applied with transition:none + a sync flush
// (offsetHeight), then transition 'transform <slideMs>ms ease' + transform:'' — the slide
// starts in the SAME frame as the reflow; on the next anchor change the transition
// retargets from the current interpolated position (no rAF wait, no setTimeout fallback:
// no 33ms freeze, no teleports on fast drags). One transitionend listener per element
// (replaced per pass); it clears the inline transition only while still the latest pass.
function applyFlipFrom(firstRects) {
  const ms = window.blatamFx && window.blatamFx.slideMs;
  if (!ms) return;
  const pending = [];
  for (const entry of firstRects) {
    const el = entry[0], fr = entry[1];
    if (!el.isConnected || el.style.display === 'none') continue;
    const post = el.getBoundingClientRect();
    const cs = getComputedStyle(el).transform;
    const m = (cs && cs !== 'none') ? cs.match(/matrix\(([^)]+)\)/) : null;
    const tx = m ? (parseFloat(m[1].split(',')[4]) || 0) : 0;
    const ty = m ? (parseFloat(m[1].split(',')[5]) || 0) : 0;
    const dx = fr.left - (post.left - tx);
    const dy = fr.top - (post.top - ty);
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) continue;
    pending.push([el, dx, dy]);
  }
  if (!pending.length) return;
  for (const p of pending) {
    p[0].style.transition = 'none';
    p[0].style.transform = 'translate(' + p[1] + 'px,' + p[2] + 'px)';
  }
  for (const p of pending) { void p[0].offsetHeight; } // flush — commit the start values
  for (const p of pending) {
    const el = p[0];
    if (el.__flipClear) el.removeEventListener('transitionend', el.__flipClear);
    el.style.transition = 'transform ' + ms + 'ms ease';
    el.style.transform = '';
    const clear = (ev) => {
      if (ev.propertyName !== 'transform') return;
      el.removeEventListener('transitionend', clear);
      if (el.__flipClear === clear) el.style.transition = '';
    };
    el.__flipClear = clear;
    el.addEventListener('transitionend', clear);
  }
}


// Commits a card drop at coordinates (pointer path): target —
// document.elementFromPoint. Mirrors the HTML5 drop handlers:
// .gbar / .group-empty-slot — the tab goes INTO the group (place-tab /
// place-tabs, end of list), .space-chip — INTO the space (moveTabTo), inside
// #tabs-list — INTO the ghost slot (placeCardToSlot). Returns {rect} — the
// destination rect for the clone settle animation, or null when the point is
// not a valid card drop target (cancel).
function commitCardDropAt(clientX, clientY) {
  if (!dragSourceUrl || dragSourceGroupId) return null;
  const t = document.elementFromPoint(clientX, clientY);
  if (!t || !t.closest) return null;
  const src = allTabs.find(tb => tb.url === dragSourceUrl);
  if (!src) return null;
  const moveIntoGroup = (gid) => {
    const batch = dragBatchUrls && dragBatchUrls.length > 1 ? dragBatchUrls : null;
    if (batch) {
      if (batch.some(u => {
        const tb = allTabs.find(x => x.url === u);
        return !tb || tabGroupOf(tb) !== gid;
      })) chrome.runtime.sendMessage({ action: 'place-tabs', urls: batch,
        anchorUrl: null, side: 'after', groupId: gid });
    } else if (src.groupId !== gid) {
      chrome.runtime.sendMessage({ action: 'place-tab', index: allTabs.indexOf(src),
        anchorIndex: null, side: 'after', groupId: gid });
    }
    // Свернутая группа (шапка/слот принимает карточку): разворачиваем
    expandGroupForDrop(gid);
  };
  const gbar = t.closest('.gbar');
  if (gbar) {
    // The false click on the header is born in this moment (before dragend of
    // the source) — arm the one-shot suppression and take the warm ghost away
    // (like the HTML5 drop on the header does)
    pendingGbarClickAfterDrag = true;
    const rect = gbar.getBoundingClientRect();
    removeGhostSlot();
    // Only an empty/collapsed group (no visible cards) accepts a card
    if (!groupVisibleCardCount(gbar.dataset.groupId)) moveIntoGroup(gbar.dataset.groupId);
    return { rect };
  }
  const slot = t.closest('.group-empty-slot');
  if (slot) {
    const rect = slot.getBoundingClientRect();
    removeGhostSlot();
    moveIntoGroup(slot.dataset.groupId);
    return { rect };
  }
  const chip = t.closest('.space-chip');
  if (chip) {
    const rect = chip.getBoundingClientRect();
    chip.classList.remove('drag-over');
    const batch = dragBatchUrls;
    if (batch && batch.length > 1) {
      for (const u of batch) {
        const tb = allTabs.find(x => x.url === u);
        if (tb) moveTabTo(tb, chip.dataset.spaceId, undefined);
      }
    } else moveTabTo(src, chip.dataset.spaceId, undefined);
    return { rect };
  }
  const rail = t.closest('#rail-right');
  if (rail) {
    if (railRight) railRight.classList.remove('rail-drag-over'); // тёплый тон снят (endCardDrag — страховка)
    // Карточка → рейка: сайт открывается новой фоновой вкладкой, сама
    // карточка не тронута (без записи в storage). Слота в сетке нет — клон
    // «приземляется» у курсора (rect размером с карточку под курсором).
    // Исходник скрыт во время драга (display:none) — rect снят при захвате
    const w = (dragCardSize && dragCardSize.w) ? dragCardSize.w : 160;
    const h = (dragCardSize && dragCardSize.h) ? dragCardSize.h : 84;
    const urls = (dragBatchUrls && dragBatchUrls.length > 1) ? dragBatchUrls : [src.url];
    openSavedUrlsInBackground(urls);
    removeGhostSlot();
    return { rect: { left: clientX - w / 2, top: clientY - h / 2, width: w, height: h } };
  }
  // Пустая полоса сетки (между строками карточек) — not a valid card drop
  // target: cancel (clone settles home, no storage write)
  if (cardAreaEmptyBand(clientX, clientY)) return null;
  if (!tabsList.contains(t)) return null;
  // The ghost slot (when visible) is the destination: measure BEFORE the
  // commit — the commit re-renders and removes the ghost
  let rect = null;
  if (dragGhostSlot && dragGhostSlot.isConnected && dragGhostSlot.style.display !== 'none')
    rect = dragGhostSlot.getBoundingClientRect();
  placeCardToSlot(src, slotAnchor(cardGapIndex(clientX, clientY), clientY));
  removeGhostSlot();
  return { rect };
}

// === Pointer drag (real Chrome UX) ===
// The pointer path replaces the native HTML5 drag image: press on the card +
// move over 8 px — the original disappears from its slot (warm ghost slot in
// its place), a LIFT CLONE (fixed-position copy of the card, scale liftScale
// + drop shadow) tracks the cursor 1:1, the ghost slot walks the grid
// (siblings — FLIP slide of slideMs). On release the state commits
// synchronously and the clone "lands" in the destination over settleMs
// (fade + scale to 0.96). Escape / release outside a drop target — cancel
// (clone returns to the original slot). The HTML5 path (dragstart/dragover/
// drop/dragend) stays for the synthetic test harness.
let pd = null; // active press: {tab, card, rect, startX, startY, ox, oy, armed}
let pdClone = null; // lift clone (copy of the card, position:fixed, in body)
let pdLastAnchor = null; // last ghost-slot anchor (FLIP-pass dedup)
// Свой pointer-путь обрабатывает press на элементе (ставится на pointerdown
// pointer-путём шапки группы / рейки — более поздние волны): guard в dragstart
// убивает trusted нативный драг. Синтетическая цепочка харнесса (untrusted)
// всегда проходит
let gbarPointerPress = false;
let railPointerPress = false;
// Живой pointer-драг ЧУЖОГО элемента (карточка — pd, чип — pcd, рейка — btl;
// состояние гbar добавится в его волне): пересекающий trusted dragstart
// гасится, чтобы не украсть drag-source из-под идущего pointer-драга
function pdForeignActive() {
  return !!(pd && pd.armed) || !!(pcd && pcd.armed) || !!(btl && btl.armed);
}

// Press target is a nested interactive element (button/checkbox/link/label) —
// do not arm the drag (hover controls keep their own job)
function pdInteractiveTarget(el) {
  return !!(el instanceof Element && el.closest('button, input, a, label'));
}

function pdScale() { return (window.blatamFx && window.blatamFx.liftScale) || 1.02; }
function pdSettleMs() { const v = window.blatamFx && window.blatamFx.settleMs; return v == null ? 180 : v; }

// Toby-style autoScroll (original: DndContext autoScroll): during an armed pointer-drag,
// a cursor within 40px of the top/bottom edge of the scrollable container holding the
// cursor (fallback: the source element) scrolls THAT container — linear ramp, up to 20px
// per pointermove. Returns true when it scrolled (caller re-tracks at the same point —
// the geometry moved).
const PD_SCROLL_EDGE = 40, PD_SCROLL_SPEED = 20;
function pdFindScroller(el) {
  let c = el;
  while (c && c !== document.body && c !== document.documentElement) {
    const st = getComputedStyle(c);
    if ((st.overflowY === 'auto' || st.overflowY === 'scroll') && c.scrollHeight > c.clientHeight) return c;
    c = c.parentElement;
  }
  return null;
}
function pdAutoScrollAt(clientX, clientY, sourceEl) {
  const t = document.elementFromPoint(clientX, clientY) || sourceEl;
  const c = t ? pdFindScroller(t) : null;
  if (!c) return false;
  const r = c.getBoundingClientRect();
  let dy = 0;
  if (clientY > r.bottom - PD_SCROLL_EDGE) {
    dy = Math.min(1, (clientY - (r.bottom - PD_SCROLL_EDGE)) / PD_SCROLL_EDGE) * PD_SCROLL_SPEED;
  } else if (clientY < r.top + PD_SCROLL_EDGE) {
    dy = -Math.min(1, ((r.top + PD_SCROLL_EDGE) - clientY) / PD_SCROLL_EDGE) * PD_SCROLL_SPEED;
  }
  if (!dy) return false;
  const ns = Math.max(0, Math.min(c.scrollHeight - c.clientHeight, c.scrollTop + dy));
  if (ns === c.scrollTop) return false;
  c.scrollTop = ns;
  return true;
}

function pdCloneXf(x, y) {
  return 'translate3d(' + x + 'px,' + y + 'px,0) scale(' + pdScale() + ')';
}

// LIFT CLONE: a fixed-position copy of the card (no id; cloneNode copies no
// listeners), card-sized, under the cursor, no transition while dragging
function pdCreateClone(card, rect, x, y) {
  const clone = card.cloneNode(true);
  clone.id = '';
  clone.classList.add('pd-clone');
  clone.style.cssText = 'position:fixed;top:0;left:0;margin:0;box-sizing:border-box;' +
    'width:' + rect.width + 'px;height:' + rect.height + 'px;overflow:hidden;' +
    'z-index:2147483000;pointer-events:none;transition:none;will-change:transform;' +
    'transform:' + pdCloneXf(x, y) +
    ';filter:drop-shadow(0 6px 14px rgba(0,0,0,0.18))';
  document.body.appendChild(clone);
  return clone;
}

function pdCloneMove(x, y) {
  if (pdClone) pdClone.style.transform = pdCloneXf(x, y);
}

// Clone finish: over `ms` — move to the rect, fade out, scale to 0.96 (curve
// cubic-bezier(0.22, 1, 0.36, 1)); ms=0 — removed immediately.
function pdFinishClone(rect, ms) {
  const clone = pdClone;
  pdClone = null;
  if (!clone || !clone.isConnected) return;
  const C = 'cubic-bezier(0.22, 1, 0.36, 1)';
  const finish = () => { if (clone.isConnected) clone.remove(); };
  if (!ms || !rect) { clone.remove(); return; }
  clone.style.transition = 'transform ' + ms + 'ms ' + C + ',opacity ' + ms + 'ms ' + C +
    ',width ' + ms + 'ms ' + C + ',height ' + ms + 'ms ' + C;
  clone.style.transform = 'translate3d(' + rect.left + 'px,' + rect.top + 'px,0) scale(0.96)';
  clone.style.width = rect.width + 'px';
  clone.style.height = rect.height + 'px';
  clone.style.opacity = '0';
  clone.addEventListener('transitionend', (ev) => { if (ev.propertyName === 'transform') finish(); });
  setTimeout(finish, ms + 80); // fallback: remove even if transitionend does not fire
}

function pdTeardown() {
  window.removeEventListener('pointermove', pdOnMove);
  window.removeEventListener('pointerup', pdOnUp);
  window.removeEventListener('pointercancel', pdOnCancel);
  window.removeEventListener('keydown', pdOnKey);
  document.body.style.cursor = '';
}

// Cancel: no commit — the card returns to its slot, the clone "goes home"
function pdCancelEnd() {
  endCardDrag(pd.card);
  pdFinishClone(pd.rect, pdSettleMs());
  pd = null;
}

function pdOnKey(e) {
  if (!pd || !pd.armed || e.key !== 'Escape') return;
  pdTeardown();
  pdCancelEnd();
}

function pdOnCancel(e) {
  if (!pd) return;
  const armed = pd.armed;
  pdTeardown();
  if (armed) pdCancelEnd();
  else pd = null;
}

function pdOnUp(e) {
  if (!pd) return;
  const armed = pd.armed;
  const cardEl = pd.card;
  const homeRect = pd.rect;
  pdTeardown();
  if (!armed) { pd = null; return; } // plain press — the click passes through
  const info = commitCardDropAt(e.clientX, e.clientY);
  endCardDrag(cardEl);
  // Committed — the clone "lands" in the destination; not a valid target —
  // it returns home
  pdFinishClone(info && info.rect ? info.rect : homeRect,
    pdSettleMs());
  pd = null;
}

function pdOnMove(e) {
  if (!pd) return;
  if (!pd.armed) {
    const dx = e.clientX - pd.startX, dy = e.clientY - pd.startY;
    if (dx * dx + dy * dy <= 8 * 8) return; // not a drag until over 8 px
    pd.armed = true;
    pdLastAnchor = null;
    beginCardDrag(pd.tab, pd.card, true);
    pdClone = pdCreateClone(pd.card, pd.rect, e.clientX - pd.ox, e.clientY - pd.oy);
    // Armed: cursor grabbing on body and on the card
    document.body.style.cursor = 'grabbing';
    if (pd.card.isConnected) pd.card.style.cursor = 'grabbing';
  }
  e.preventDefault();
  pdCloneMove(e.clientX - pd.ox, e.clientY - pd.oy);
  pdAutoScrollAt(e.clientX, e.clientY, pd.card);
  trackCardDragAt(e.clientX, e.clientY);
}

function pdBindCard(card, tab) {
  card.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (card.dataset.pressBtn || pdInteractiveTarget(e.target)) return;
    const rect = card.getBoundingClientRect();
    pd = { tab, card, rect, startX: e.clientX, startY: e.clientY,
           ox: e.clientX - rect.left, oy: e.clientY - rect.top, armed: false };
    window.addEventListener('pointermove', pdOnMove);
    window.addEventListener('pointerup', pdOnUp);
    window.addEventListener('pointercancel', pdOnCancel);
    window.addEventListener('keydown', pdOnKey);
  });
}
// === Pointer drag of space chips (real Chrome UX) ===
// Chip-путь зеркалирует карточный: press по чипу + движение больше 8 px —
// нативный drag-образ отменяется (dragstart чипа: preventDefault + e.isTrusted),
// оригинал исчезает из ряда (тёплая .space-ghost-slot в его месте, синхронно —
// без setTimeout), LIFT-КЛОН (.pd-clone в body, position:fixed, liftScale +
// тень) следует за курсором 1:1, ghost-slot ходит по ряду с FLIP-слайдом
// соседних чипов (slideMs). Отпускание: на чип — reorderSpaces (левая/правая
// половина цели), на ряд (зазор/«+ Пространство») — по ТЕКУЩЕЙ DOM-позиции
// заглушки (то же правило, что row-drop), в остальном — cancel (без записи);
// клон «приземляется» в цель за settleMs, при cancel — возвращается домой.
// Escape — cancel. Обычный клик (без движения) по-прежнему переключает
// пространство (click-хендлер не тронут). Своё состояние (pcd) — не пересекается
// с card path (одна мышь); pdCreateClone/pdCloneMove/pdFinishClone/pdScale/
// pdSettleMs/applyFlipFrom общие (pdClone-переменная — безопасно: драг один).
// Синтетическая HTML5-цепочка (не-trusted DragEvents) идёт своим dragstart.
let pcd = null; // active press: {spId, chip, homeRect, startX, startY, ox, oy, armed, lastAnchor}

// .space-chip под точкой (elementFromPoint — клон/заглушка pointer-events:none,
// «видят сквозь» курсор)
function pcdChipAt(x, y) {
  const t = document.elementFromPoint(x, y);
  return t && t.closest ? t.closest('.space-chip') : null;
}

function pcdTeardown() {
  window.removeEventListener('pointermove', pcdOnMove);
  window.removeEventListener('pointerup', pcdOnUp);
  window.removeEventListener('pointercancel', pcdOnCancel);
  window.removeEventListener('keydown', pcdOnKey);
  document.body.style.cursor = '';
}

// Cancel: чип возвращается в ряд, заглушка снята, клон «возвращается домой»
// (p — состояние драга; передаётся из pcdOnUp, где pcd уже обнулён)
function pcdCancelState(p) {
  p = p || pcd;
  pcd = null;
  dragSourceSpaceId = null;
  removeSpaceGhostSlot();
  if (p.chip.isConnected) p.chip.style.display = '';
  pdFinishClone(p.homeRect, pdSettleMs());
}

function pcdOnKey(e) {
  if (!pcd || !pcd.armed || e.key !== 'Escape') return;
  pcdTeardown();
  pcdCancelState();
}

function pcdOnCancel(e) {
  if (!pcd) return;
  const armed = pcd.armed;
  pcdTeardown();
  if (armed) pcdCancelState();
  else pcd = null;
}

// Release: over a chip — reorderSpaces (side by X-half); over the row — commit
// ghost's CURRENT DOM position (neighbouring .space-chip; «+ Пространство»/null
// — not a target; no-op-guard — внутри reorderSpaces); elsewhere — null (cancel).
// Rects измеряются ДО commit — commit ре-рендерит чипы и снимает заглушку.
function pcdCommitAt(x, y, p) {
  const fromId = p.spId;
  const chipEl = pcdChipAt(x, y);
  if (chipEl) {
    // скрытый источник не попадает под курсор — дроп в собственный слот
    // уходит в row-ветку ниже (заглушка дома — no-op)
    const rect = chipEl.getBoundingClientRect();
    reorderSpaces(fromId, chipEl.dataset.spaceId, reorderSideX(chipEl, x));
    return rect;
  }
  const t = document.elementFromPoint(x, y);
  if (t && t.closest && t.closest('#spaces-bar')) {
    const slot = dragGhostChipSlot;
    const rect = (slot && slot.isConnected) ? slot.getBoundingClientRect() : p.homeRect;
    if (slot && slot.isConnected) {
      const next = slot.nextElementSibling;
      const prev = slot.previousElementSibling;
      if (next && next.classList.contains('space-chip')) {
        reorderSpaces(fromId, next.dataset.spaceId, 'before');
      } else if (prev && prev.classList.contains('space-chip')) {
        reorderSpaces(fromId, prev.dataset.spaceId, 'after');
      }
      // заглушка не у чипов (пустой ряд) — no-op
    }
    return rect;
  }
  return null;
}

function pcdOnUp(e) {
  if (!pcd) return;
  const armed = pcd.armed;
  const p = pcd;
  pcd = null;
  pcdTeardown();
  if (!armed) return; // plain press — the click passes through (switch space)
  const rect = pcdCommitAt(e.clientX, e.clientY, p);
  if (rect) {
    dragSourceSpaceId = null;
    removeSpaceGhostSlot();
    // no-op-коммит (порядок не изменился — reorderSpaces не записал):
    // перерисовки не было — чип возвращается в ряд сам
    if (p.chip.isConnected && p.chip.style.display === 'none') p.chip.style.display = '';
    pdFinishClone(rect, pdSettleMs()); // committed — клон «приземляется» в цель
  } else {
    pcdCancelState(p); // вне ряда — cancel
  }
}

// Ghost slot walks the row by the cursor: over a chip — before/after it by the
// half; when the anchor CHANGES — FLIP pass (rect snapshot of visible chips,
// excluding the hidden source, BEFORE the move → move ghost → applyFlipFrom);
// over the row — ghost keeps its DOM position; elsewhere — no anchor (a cancel
// candidate on release)
function pcdTrackAt(x, y) {
  const chipEl = pcdChipAt(x, y);
  if (chipEl) {
    const side = reorderSideX(chipEl, x);
    if (pcd.lastAnchor && pcd.lastAnchor.el === chipEl && pcd.lastAnchor.side === side) return;
    const firstRects = snapshotCardRects('#space-chips .space-chip', pcd.chip);
    moveSpaceGhostSlot({ el: chipEl, side: side });
    pcd.lastAnchor = { el: chipEl, side: side };
    applyFlipFrom(firstRects);
    return;
  }
  const t = document.elementFromPoint(x, y);
  pcd.lastAnchor = (t && t.closest && t.closest('#spaces-bar')) ? { row: true } : null;
}

function pcdOnMove(e) {
  if (!pcd) return;
  if (!pcd.armed) {
    const dx = e.clientX - pcd.startX, dy = e.clientY - pcd.startY;
    if (dx * dx + dy * dy <= 8 * 8) return; // not a drag until over 8 px
    // ARM: меряем rect и заглушку ДО display:none (у скрытого чипа 0-размеры),
    // прячем источник, тёплая заглушка дома, lift-клон под курсором
    const chip = pcd.chip;
    pcd.homeRect = chip.getBoundingClientRect();
    dragSourceSpaceId = pcd.spId;
    pendingChipClickAfterDrag = true; // ложный post-drag клик не переключает пространство
    const ghost = makeSpaceGhostSlot(chip);
    chip.insertAdjacentElement('afterend', ghost);
    dragGhostChipSlot = ghost;
    chip.style.display = 'none';
    pdClone = pdCreateClone(chip, pcd.homeRect, e.clientX - pcd.ox, e.clientY - pcd.oy);
    pcd.armed = true;
    pcd.lastAnchor = null;
    // Armed: cursor grabbing on body and on the chip
    document.body.style.cursor = 'grabbing';
    if (chip.isConnected) chip.style.cursor = 'grabbing';
  }
  e.preventDefault();
  pdCloneMove(e.clientX - pcd.ox, e.clientY - pcd.oy);
  pdAutoScrollAt(e.clientX, e.clientY, pcd.chip);
  pcdTrackAt(e.clientX, e.clientY);
}

function pcdBindChip(chip, spId) {
  chip.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (!chip.draggable) return; // guardDragOverButtons снял draggable — press на ✎/✕
    if (e.target.closest('.chip-icon-btn')) return; // кнопки держат свою работу
    const rect = chip.getBoundingClientRect();
    pcd = { spId: spId, chip: chip, homeRect: rect,
            startX: e.clientX, startY: e.clientY,
            ox: e.clientX - rect.left, oy: e.clientY - rect.top,
            armed: false, lastAnchor: null };
    window.addEventListener('pointermove', pcdOnMove);
    window.addEventListener('pointerup', pcdOnUp);
    window.addEventListener('pointercancel', pcdOnCancel);
    window.addEventListener('keydown', pcdOnKey);
  });
}



// 'before'/'after' — по позиции курсора относительно середины элемента
function reorderSide(card, clientY) {
  const rect = card.getBoundingClientRect();
  return (clientY == null || clientY <= rect.top + rect.height / 2) ? 'before' : 'after';
}

// 'before'/'after' — по курсору относительно ГОРИЗОНТАЛЬНОЙ середины
// элемента (reorder чипов пространств; вертикальная reorderSide для
// шапок групп не тронута)
function reorderSideX(el, clientX) {
  const rect = el.getBoundingClientRect();
  return (clientX == null || clientX <= rect.left + rect.width / 2) ? 'before' : 'after';
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



openSelectedBtn.addEventListener('click', () => {
  const urls = allTabs.filter(t => selectedUrls.has(t.url)).map(t => t.url);
  openMany(urls);
});

clearSelectionBtn.addEventListener('click', () => {
  selectedUrls.clear();
  renderTabs(searchInput.value);
});

// «Удалить» — массовое удаление выделенных вкладок: один confirm
// (русские множественные формы), одна запись в storage, выбор снимается.
// Пустой выбор — no-op; отмена — ничего не меняется.
deleteSelectedBtn.addEventListener('click', () => {
  if (selectedUrls.size === 0) return;
  const n = selectedUrls.size;
  if (!confirm(`Удалить ${n} ${pluralVkladki(n)}?`)) return;
  allTabs = allTabs.filter(t => !selectedUrls.has(t.url));
  chrome.storage.local.set({ 'blattam-tabs': allTabs });
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
  chrome.storage.local.set({ 'blattam-tabs': allTabs });
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
  if (areaName === 'local') {
    // Вкладки — в local (migrate sync → local): в local реагируем только на blattam-tabs
    if (changes['blattam-tabs']) {
      const newTabs = changes['blattam-tabs'].newValue || [];
      const oldTabs = changes['blattam-tabs'].oldValue || [];
      // Группа потеряла последнюю вкладку — автосворачивание: вместо строки
      // «Перетащите вкладку сюда» — свёрнутая шапка с «0 вкладок» (свежесозданная
      // или вручную раскрытая пустая группа остаются раскрытыми — слот = цель дропа)
      let groupsEmptied = false;
      allGroups.forEach(g => {
        if (g.collapsed) return;
        const isMember = (t) => t && t.spaceId === g.spaceId && t.groupId === g.id;
        const before = oldTabs.filter(isMember).length;
        const after = newTabs.filter(isMember).length;
        if (before > 0 && after === 0) { g.collapsed = true; groupsEmptied = true; }
      });
      if (groupsEmptied) chrome.storage.sync.set({ 'blattam-groups': allGroups });
      // Реордер (набор URL тот же, изменился только порядок) — выбор и активная
      // карточка завязаны на URL, поэтому переживают перерисовку
      const sameUrlSet = oldTabs.length === newTabs.length &&
        oldTabs.map(t => t.url).sort().join('|') === newTabs.map(t => t.url).sort().join('|');
      allTabs = newTabs;
      if (!sameUrlSet) selectedUrls.clear(); // набор вкладок изменился — сброс выбора
      renderTabs(searchInput.value);
    }
    // Зеркало открытых вкладок (blattam-browser-tabs) — перерисовка рейки.
    // В драге рейки не перерисовываем (заглушка уйдёт из DOM) — dragend
    // перерисует.
    if (changes['blattam-browser-tabs']) {
      if (dragSourceBrowserTab) return;
      browserTabs = changes['blattam-browser-tabs'].newValue || [];
      renderBrowserTabs();
      return;
    }
    // «Фон»: применяем/снимаем картинку как при записи из настроек, так и
    // при внешнем изменении (другое окно расширения); идемпотентно,
    // перерисовка карточек не нужна.
    if (changes['blattam-bg-image']) {
      applyBackgroundImage(changes['blattam-bg-image'].newValue || '');
    }
    // «Цвет вкладок» (blattam-tab-color): применяем/снимаем кастомный цвет;
    // идемпотентно (инлайн-стиль documentElement), перерисовка карточек не нужна.
    if (changes['blattam-tab-color']) {
      applyTabCardColor(changes['blattam-tab-color'].newValue || '');
    }
    return;
  }
  if (areaName !== 'sync') return;
// 

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
    'blatt-tabs': true,
    version: chrome.runtime.getManifest().version,
    exported: new Date().toISOString(),
    spaces: allSpaces,
    groups: allGroups,
    tabs: allTabs
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  a_click(url, `blatt-tabs-backup-${new Date().toISOString().slice(0, 10)}.json`);
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

      chrome.storage.local.set({ 'blattam-tabs': allTabs });
      chrome.storage.sync.set({
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

// === Правая рейка: живое зеркало открытых вкладок браузера (blattam-browser-tabs) ===
// Единственный реальный источник зеркала — background.js (слушатели chrome.tabs,
// дебаунс ~200 мс); view.js этот ключ НЕ записывает. Рейка показывает вкладки
// ТОЛЬКО этого окна (chrome.windows.getCurrent) в порядке верхней полосы;
// страница newtab (view.html) не показывается. Драг: reorder внутри рейки
// (chrome.tabs.move — верхняя полоса и рейка синхронизируются в обе стороны)
// и дроп в центр (сохранить вкладку карточкой — браузерная вкладка остаётся
// открытой).

// Страница newtab (view.html) — в рейку не попадает
function isOwnNewTab(t) {
  if (!t) return true;
  try {
    const selfUrl = chrome.runtime.getURL('view.html');
    return t.url === selfUrl || t.pendingUrl === selfUrl;
  } catch (err) { return false; }
}

// Начальная загрузка зеркала: окно (windows.getCurrent) + ключ
// blattam-browser-tabs; фолбэк — chrome.tabs.query (первый запуск:
// background зеркало ещё не записал)
function loadBrowserTabs() {
  (async () => {
    if (chrome.windows && chrome.windows.getCurrent) {
      try { const w = await chrome.windows.getCurrent(); browserWindowId = w ? w.id : null; }
      catch (err) { browserWindowId = null; }
    }
    let list = null;
    try {
      const data = await chrome.storage.local.get('blattam-browser-tabs');
      if (Array.isArray(data['blattam-browser-tabs']) && data['blattam-browser-tabs'].length > 0) {
        list = data['blattam-browser-tabs'];
      }
    } catch (err) { list = null; }
    if ((!list || list.length === 0) && chrome.tabs && chrome.tabs.query) {
      try {
        const q = browserWindowId != null ? { windowId: browserWindowId } : {};
        const tabs = await chrome.tabs.query(q);
        if (Array.isArray(tabs)) {
          list = tabs.filter(t => !isOwnNewTab(t))
            .map(t => ({ id: t.id, title: t.title || '', url: t.url || '',
                         favIconUrl: t.favIconUrl || '', windowId: t.windowId, index: t.index }))
            .sort((a, b) => (a.windowId - b.windowId) || (a.index - b.index));
        }
      } catch (err) { list = []; }
    }
    browserTabs = Array.isArray(list) ? list : [];
    renderBrowserTabs();
  })();
}

// Рендер рейки: вкладки этого окна в порядке полосы (index), по id
function renderBrowserTabs() {
  if (!browserTabsList) return;
  // Перерисовка в драге рейки уносит заглушку из DOM — сбрасываем ссылку,
  // чтобы отсоединённая заглушка не «воскресла» после dragend
  if (dragBrowserTabGhost && !dragBrowserTabGhost.isConnected) dragBrowserTabGhost = null;
  const mine = browserTabs
    .filter(t => browserWindowId == null || t.windowId === browserWindowId)
    .slice()
    .sort((a, b) => (a.windowId - b.windowId) || (a.index - b.index));
  browserTabsList.innerHTML = '';
  mine.forEach(t => browserTabsList.appendChild(makeBtItem(t)));
}

// Буквенная плитка фавикона рейки — та же монохромная, что у карточек
function makeBtIconFallback(t) {
  const el = document.createElement('span');
  el.className = 'bt-icon-fallback';
  el.textContent = faviconFallbackChar(t.url || t.title || '');
  return el;
}

// Элемент рейки: фавикон 16px (img; error — буквенная плитка) + обрезанное имя
function makeBtItem(t) {
  const item = document.createElement('div');
  item.className = 'bt-tab';
  item.dataset.id = String(t.id);
  item.draggable = true;
  item.title = t.title || t.url || '';
  if (t.favIconUrl) {
    const img = document.createElement('img');
    img.className = 'bt-icon';
    img.src = t.favIconUrl;
    img.alt = '';
    img.draggable = false;
    img.addEventListener('error', () => { if (img.parentNode) img.replaceWith(makeBtIconFallback(t)); });
    item.appendChild(img);
  } else {
    item.appendChild(makeBtIconFallback(t));
  }
  const label = document.createElement('span');
  label.className = 'bt-title';
  label.textContent = t.title || t.url || '—';
  item.appendChild(label);
  // Клик — переключить браузер на уже открытую вкладку (ложный post-drop-клик гасится one-shot)
  item.addEventListener('click', () => {
    if (pendingBtClickAfterDrag) { pendingBtClickAfterDrag = false; return; }
    focusBrowserTab(t);
  });
  item.addEventListener('dragstart', (e) => onBtDragStart(e, item, t));
  item.addEventListener('dragend', () => onBtDragEnd());
  btlBindItem(item, t); // pointer-путь (реальный Chrome UX)
  return item;
}

// Переключение браузера на уже открытую вкладку: активировать её (chrome.tabs.update
// active) + фокус её окна (chrome.windows.update focused). НЕ открывает новую вкладку.
function focusBrowserTab(t) {
  if (!t || t.id == null) return;
  let done = null;
  if (chrome.tabs && typeof chrome.tabs.update === 'function') {
    try { done = chrome.tabs.update(t.id, { active: true }); } catch (_) { done = null; }
  }
  const focusWindow = () => {
    if (t.windowId != null && chrome.windows && typeof chrome.windows.update === 'function') {
      try { chrome.windows.update(t.windowId, { focused: true }); } catch (_) {}
    }
  };
  if (done && typeof done.then === 'function') done.then(focusWindow).catch(focusWindow);
  else focusWindow();
}

// Заглушка рейки: тёплая (как ghost-slot карточек: --ghost-bg + пунктир
// --ghost-ring), размер элемента. Инлайн — в тестах head-стили view.html
// не грузятся
function makeBtGhostSlot(height) {
  const slot = document.createElement('div');
  slot.className = 'bt-ghost-slot';
  slot.style.cssText =
    'pointer-events:none;box-sizing:border-box;background:var(--ghost-bg);' +
    'border-width:1px;border-style:dashed;border-color:var(--ghost-ring);' +
    'border-radius:6px;width:100%;height:' + (height || 30) + 'px;';
  return slot;
}

function onBtDragStart(e, item, t) {
  // Нативный HTML5-драг отменяется, когда press ведёт pointer-путь: свой
  // (railPointerPress — ставится на pointerdown pointer-путём рейки, более поздняя волна)
  // или чужой pointer-драг пересекает рейку (pdForeignActive). Синтетическая
  // цепочка харнесса (не-trusted) всегда проходит без изменений
  if (e.isTrusted && (railPointerPress || pdForeignActive())) { e.preventDefault(); return; }
  dragSourceBrowserTab = { id: t.id, url: t.url || '', title: t.title || '',
                           favIconUrl: t.favIconUrl || '', windowId: t.windowId, index: t.index };
  btDragItem = item;
  btDragHeight = item.offsetHeight || 30; // меряем ДО display:none
  btDropCommitted = false;
  // Ложный клик по элементу рождается в момент дропа (до dragend) —
  // вооружаем one-shot-подавление
  pendingBtClickAfterDrag = true;
  pendingCardClickAfterDrag = true; // дроп в центр: ложный клик не открывает карточку
  pendingChipClickAfterDrag = true; // дроп на чип: ложный клик не переключает пространство
  if (e.dataTransfer) {
    e.dataTransfer.setData('text/plain', String(t.id));
    e.dataTransfer.effectAllowed = 'move';
  }
  item.style.display = 'none';
  // Отложенно: display:none в самом dragstart «залипает» HTML5-drag в Chrome
  setTimeout(() => {
    // Перерисовка в драге уносит элемент из DOM — отсоединённому заглушку
    // не вставляем
    if (!dragSourceBrowserTab || !btDragItem || !btDragItem.isConnected) return;
    if (!dragBrowserTabGhost) {
      dragBrowserTabGhost = makeBtGhostSlot(btDragHeight);
      btDragItem.before(dragBrowserTabGhost);
    }
  }, 0);
}

// Полный cleanup (идемпотентный): заглушки сняты, источник возвращён в слот,
// рейка перерисована
function onBtDragEnd() {
  const src = dragSourceBrowserTab;
  dragSourceBrowserTab = null;
  btDragItem = null;
  if (!btDropCommitted) pendingBtClickAfterDrag = false; // драг отменён — ложного клика не будет
  btDropCommitted = false;
  if (dragBrowserTabGhost && dragBrowserTabGhost.isConnected) dragBrowserTabGhost.remove();
  dragBrowserTabGhost = null;
  removeGhostSlot(); // центральная заглушка (рейка → центр)
  if (src && browserTabsList) {
    // Источник мог уже перерисоваться (onChanged) — восстановим видимость по id
    const el = browserTabsList.querySelector('.bt-tab[data-id="' + CSS.escape(String(src.id)) + '"]');
    if (el) el.style.display = '';
  }
  renderBrowserTabs(); // идемпотентно
}

// Видимые элементы рейки в DOM-порядке (источник при драге скрыт)
function btVisibleItems() {
  if (!browserTabsList) return [];
  return [...browserTabsList.querySelectorAll('.bt-tab')].filter(el => el.style.display !== 'none');
}

// Слот вставки в рейке (midpoint-правило, как у карточек): первый элемент,
// чья вертикальная середина НИЖЕ курсора — слот перед ним; выше середин всех —
// после последнего
function btSlotAnchor(clientY) {
  const items = btVisibleItems();
  if (!items.length) return null;
  for (const it of items) {
    const r = it.getBoundingClientRect();
    if (clientY != null && clientY < r.top + r.height / 2) return { el: it, side: 'before' };
  }
  return { el: items[items.length - 1], side: 'after' };
}

function moveBtGhostSlot(anchor) {
  if (!dragBrowserTabGhost || !dragBrowserTabGhost.isConnected) return;
  if (!anchor || !anchor.el) { browserTabsList.appendChild(dragBrowserTabGhost); return; }
  if (anchor.side === 'before') anchor.el.before(dragBrowserTabGhost);
  else anchor.el.after(dragBrowserTabGhost);
}

// Новый per-window-индекс перетаскиваемой вкладки по DOM-позиции заглушки
// (порядок рейки = порядок верхней полосы окна)
function btGhostIndex() {
  const ghost = dragBrowserTabGhost;
  const src = dragSourceBrowserTab;
  if (!ghost || !ghost.isConnected) return src ? src.index : 0;
  let pos = 0;
  for (const child of browserTabsList.children) {
    if (child === ghost) break;
    if (child.classList && child.classList.contains('bt-tab') && child.style.display !== 'none') pos++;
  }
  return pos;
}

// Reorder рейки: chrome.tabs.move — зеркало (background) и верхняя полоса
// следуют, onChanged перерисует рейку. Целевой индекс — по РЕАЛЬНОМУ окну:
// рейка не показывает newtab-страницу (view.html), поэтому позиция в рейке —
// НЕ то же, что индекс в окне (view.html занимает слот в окне). Достаём окно,
// вставляем источник в позицию заглушки по числу ВИДИМЫХ вкладок перед ней.
// После chrome.tabs.move перерисовываем рейку НЕМЕДЛЕННО из реального
// окна. В реальном Chrome запись зеркала в background идёт с дебаунсом
// ~200 мс, и пока она не доберётся до view, рейка остаётся в старом
// порядке (мок перерисовывает зеркало синхронно, поэтому в тестах это не
// видно). В storage зеркало view не пишет (единственный источник —
// background) — обновляем только в-памяти список browserTabs + рейку.
function syncRailFromTabs() {
  if (!chrome.tabs || !chrome.tabs.query) return;
  try {
    chrome.tabs.query({}, (tabs) => {
      if (!Array.isArray(tabs)) return;
      browserTabs = tabs
        .filter(t => t && !isOwnNewTab(t))
        .map(t => ({ id: t.id, title: t.title || '', url: t.url || '',
                     favIconUrl: t.favIconUrl || '', windowId: t.windowId, index: t.index }))
        .sort((a, b) => (a.windowId - b.windowId) || (a.index - b.index));
      renderBrowserTabs();
    });
  } catch (err) { /* рейка — вспомогательная, молча пропускаем */ }
}

function commitBtRailMove(src) {
  // Индекс ЗАГЛУШКИ фиксируем синхронно (ЧИСЛО): async-ветка ниже отработает
  // уже ПОСЛЕ cleanup pointer-пути, где заглушка снята — читать DOM-позицию в
  // микрозадаче pointer-путь прочёл бы index источника (no-op). HTML5-путь не
  // тронут: там ghostPos и есть индекс (источник не двигался)
  const ghostPos = typeof btGhostIndex === 'function' ? btGhostIndex() : 0;
  btDropCommitted = true;
  // Снимаем guard ДО записи: onChanged (мок) перерисует рейку сразу
  dragSourceBrowserTab = null;
  if (!chrome.tabs || !chrome.tabs.move) return;
  if (chrome.tabs.query) {
    (async () => {
      const tabs = await new Promise((res) =>
        chrome.tabs.query({ windowId: src.windowId }, (ts) => res(ts || [])));
      const others = tabs.filter(t => t && t.id !== src.id);
      let count = 0, target = others.length;
      for (let i = 0; i < others.length; i++) {
        if (count === ghostPos) { target = i; break; }
        if (!isOwnNewTab(others[i])) count++;
      }
      if (target !== src.index) {
        const p = chrome.tabs.move(src.id, { windowId: src.windowId, index: target });
        if (p && p.then) p.then(() => syncRailFromTabs()).catch(() => {});
        else syncRailFromTabs();
      }
    })().catch(() => {});
  } else if (ghostPos !== src.index) {
    const p = chrome.tabs.move(src.id, { windowId: src.windowId, index: ghostPos });
    if (p && p.then) p.then(() => syncRailFromTabs()).catch(() => {});
    else syncRailFromTabs();
  }
}

// Сохранённая карточка из браузерной вкладки — те же поля, что у
// существующего save-пути (saveCurrentTab): name/url/title/favIconUrl?/spaceId
// (+ groupId секции)
function makeSavedTabFromBrowser(src, section) {
  const tab = {
    name: ((src.title || '').trim() || src.url) || 'Без имени',
    url: src.url,
    title: src.title || '',
    spaceId: activeSpaceId,
    groupId: section
  };
  if (src.favIconUrl) tab.favIconUrl = src.favIconUrl;
  return tab;
}

// Дроп в центр: НОВАЯ карточка в позиции ghost-slot (groupId секции слота,
// null — «Без группы»); браузерная вкладка остаётся открытой, зеркало не
// трогаем
function saveBtToCenter(src, anchor) {
  btDropCommitted = true;
  dragSourceBrowserTab = null;
  let section = null, at = allTabs.length;
  if (anchor && anchor.el) {
    section = slotSection(anchor);
    let anchorUrl, side = anchor.side;
    if (anchor.el.classList.contains('tab-card') && anchor.side === 'before') {
      anchorUrl = anchor.el.__tab.url; // перед видимой карточкой X
    } else if (anchor.el.classList.contains('tab-card')) {
      const t = sectionTabFull(section, true); // конец секции (= конец списка)
      if (t) { anchorUrl = t.url; side = 'after'; }
    } else if (anchor.side === 'after') {
      const t = sectionTabFull(section, false); // начало секции
      if (t) { anchorUrl = t.url; side = 'before'; }
    } else {
      const t = sectionTabFull(section, true); // конец предыдущей секции
      if (t) { anchorUrl = t.url; side = 'after'; }
    }
    if (anchorUrl != null) {
      const a = allTabs.findIndex(t => t.url === anchorUrl);
      if (a !== -1) at = side === 'after' ? a + 1 : a;
    }
  }
  const tabs = allTabs.slice();
  tabs.splice(at, 0, makeSavedTabFromBrowser(src, section));
  chrome.storage.local.set({ 'blattam-tabs': tabs });
  // Свернутая группа-секция слота: новая карточка в неё ушла — разворачиваем
  expandGroupForDrop(section);
  removeGhostSlot();
}

// Дроп на шапку группы (или слот пустой группы): в ту группу, в конец списка
// (семантика drop-пути gbar)
function saveBtToGroup(src, groupId) {
  btDropCommitted = true;
  dragSourceBrowserTab = null;
  const tabs = allTabs.slice();
  tabs.push(makeSavedTabFromBrowser(src, groupId));
  chrome.storage.local.set({ 'blattam-tabs': tabs });
  // Свернутая группа: новая карточка в неё ушла — разворачиваем
  expandGroupForDrop(groupId);
  removeGhostSlot();
}

// Центральная заглушка для драга рейка → центр: ghost-slot карточки, размер
// видимой карточки (создаётся при первом dragover по центральному списку)
function ensureCentralBtGhost() {
  if (dragGhostSlot && dragGhostSlot.isConnected) return;
  const ref = document.querySelector('#tabs-list .tab-card');
  if (!ref) return;
  dragGhostSlot = makeGhostSlot(ref);
}

// Ставит центральную заглушку в слот вставки при драге рейка → центр.
// moveGhostSlot неприменим: он завязан на dragSourceUrl (драг карточки) —
// а источник тут в рейке, а не в секции карточек.
function moveCentralBtGhost(anchor) {
  if (!dragGhostSlot) return;
  if (!anchor || !anchor.el) return;
  if (anchor.side === 'before') anchor.el.before(dragGhostSlot);
  else anchor.el.after(dragGhostSlot);
}

// Глобальный dragover при драге вкладки рейки: рейка — заглушка по
// midpoint-правилу; чип пространства — no-target (заглушка замирает, дроп не
// переключает пространство); шапка группы / слот пустой группы — дроп в группу
// (центральная заглушка скрыта); центральный список — центральная заглушка
// следует, как при драге карточки
document.addEventListener('dragover', (e) => {
  if (!dragSourceBrowserTab || !e.dataTransfer) return;
  const t = e.target;
  const closest = (s) => (t && t.closest) ? t.closest(s) : null;
  if (closest('.space-chip')) return; // no-target
  if (closest('.gbar') || closest('.group-empty-slot')) {
    if (dragGhostSlot) setGhostDisplay('none');
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    return;
  }
  if (closest('#browser-tabs-list')) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    moveBtGhostSlot(btSlotAnchor(e.clientY));
    return;
  }
  if (closest('#tabs-list')) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    ensureCentralBtGhost();
    setGhostDisplay('');
    moveCentralBtGhost(slotAnchor(cardGapIndex(e.clientX, e.clientY), e.clientY));
  }
});

document.addEventListener('drop', (e) => {
  if (!dragSourceBrowserTab || !e.dataTransfer) return;
  const t = e.target;
  const closest = (s) => (t && t.closest) ? t.closest(s) : null;
  const src = dragSourceBrowserTab;
  if (closest('.space-chip')) return; // no-target — отмена
  const gbar = closest('.gbar');
  if (gbar && gbar.dataset.groupId) { e.preventDefault(); saveBtToGroup(src, gbar.dataset.groupId); return; }
  const ges = closest('.group-empty-slot');
  if (ges && ges.dataset.groupId) { e.preventDefault(); saveBtToGroup(src, ges.dataset.groupId); return; }
  if (closest('#browser-tabs-list')) { e.preventDefault(); commitBtRailMove(src); return; }
  if (closest('#tabs-list')) {
    e.preventDefault();
    saveBtToCenter(src, slotAnchor(cardGapIndex(e.clientX, e.clientY), e.clientY));
    return;
  }
  // Повсюду остальном — отмена (dragend снимет заглушки)
});

// Catch-all: перерисовка в драге уносит источник из DOM, и его собственный
// dragend не сработает — cleanup здесь
document.addEventListener('dragend', () => {
  if (dragSourceBrowserTab) onBtDragEnd();
});

// === Pointer drag of rail browser tabs (real Chrome UX) ===
// Путь зеркалирует карточный (pd) и чиповый (pcd): press по элементу рейки
// + движение больше 8 px — нативный HTML5-драг отменяется (guard в
// onBtDragStart: isTrusted и (railPointerPress или pdForeignActive) —
// preventDefault), источник прячется (тёплая .bt-ghost-slot на его месте —
// синхронно, без setTimeout), LIFT-КЛОН (.pd-clone в body, position:fixed,
// liftScale + тень) следует за курсором 1:1, заглушка ходит по рейке по
// midpoint-правилу (btSlotAnchor — то же, что у HTML5-пути) с FLIP-слайдом
// соседей (snapshotCardRects '#browser-tabs-list .bt-tab' + applyFlipFrom).
// Отпускание — те же цели, что у drop-хендлера: шапка группы/слот пустой
// группы — saveBtToGroup, рейка — commitBtRailMove (индекс РЕАЛЬНОГО окна по
// DOM-позиции заглушки), центральный список — saveBtToCenter (тёплая
// центральная заглушка следует за курсором через moveCentralBtGhost),
// чип пространства/повсюду остальном — cancel; клон «приземляется» в цель
// за settleMs, при cancel — возвращается домой. Escape — cancel. Обычный
// клик (без движения) по-прежнему открывает вкладку (click-хендлер не
// тронут). Заглушка — общий dragBrowserTabGhost (синхронная вставка —
// btGhostIndex корректен при коммите). Своё состояние (btl) — не
// пересекается с карточным/чиповым путями (одна мышь);
// pdCreateClone/pdCloneMove/pdFinishClone/pdScale/pdSettleMs/applyFlipFrom
// общие (pdClone — безопасно: драг один). Синтетическая HTML5-цепочка
// (ne-trusted DragEvents) идёт своим dragstart — не тронута.
let btl = null; // активный press: {t, item, homeRect, startX, startY, ox, oy, armed, lastAnchor}

function btlTeardown() {
  window.removeEventListener('pointermove', btlOnMove);
  window.removeEventListener('pointerup', btlOnUp);
  window.removeEventListener('pointercancel', btlOnCancel);
  window.removeEventListener('keydown', btlOnKey);
  document.body.style.cursor = '';
}

// После коммита: центральная заглушка снята самими save-функциями, рейку
// снимаем и перерисовываем (источник мог уже перерисоваться onChanged-ом —
// по id, как в onBtDragEnd)
function btlAfterCommit(p) {
  btDropCommitted = true;
  // Центральная заглушка (рейка → центр) снимается явно: save-функции
  // центра/группы снимают сами, а коммит в рейку — нет, без неё заглушка
  // остаётся в центральном списке (идемпотентно)
  removeGhostSlot();
  if (dragBrowserTabGhost && dragBrowserTabGhost.isConnected) dragBrowserTabGhost.remove();
  dragBrowserTabGhost = null;
  if (p && p.t && browserTabsList) {
    const el = browserTabsList.querySelector('.bt-tab[data-id="' + CSS.escape(String(p.t.id)) + '"]');
    if (el) el.style.display = '';
  }
  renderBrowserTabs();
}

// Cancel: элемент возвращается в рейку, заглушка снята, клон «возвращается
// домой» (p — состояние драга; передаётся из btlOnUp, где btl уже обнулён)
function btlCancelState(p) {
  p = p || btl;
  btl = null;
  railPointerPress = false;
  dragSourceBrowserTab = null;
  btDragItem = null;
  pendingBtClickAfterDrag = false; // драг отменён — ложного клика не будет
  if (dragBrowserTabGhost && dragBrowserTabGhost.isConnected) dragBrowserTabGhost.remove();
  dragBrowserTabGhost = null;
  removeGhostSlot(); // центральная заглушка (рейка → центр) при отмене
  if (p && p.item && p.item.isConnected) p.item.style.display = '';
  renderBrowserTabs();
  if (p) pdFinishClone(p.homeRect, pdSettleMs());
}

function btlOnKey(e) {
  if (!btl || !btl.armed || e.key !== 'Escape') return;
  btlTeardown();
  btlCancelState();
}

function btlOnCancel(e) {
  if (!btl) return;
  const armed = btl.armed;
  btlTeardown();
  if (armed) btlCancelState();
  else { btl = null; railPointerPress = false; }
}

// Commit at (x, y) — те же цели, что у HTML5-дропа (document drop). Rect
// цели (для клон-сета) снимаем ДО commit — commit ре-рендерит рейку и
// снимает заглушки. null — не целевая точка (cancel).
function btlCommitAt(x, y, p) {
  const t = document.elementFromPoint(x, y);
  const closest = (sel) => (t && t.closest) ? t.closest(sel) : null;
  const src = dragSourceBrowserTab;
  if (!src || !t || !t.closest) return null;
  if (closest('.space-chip')) return null; // no-target — отмена (не переключает пространство)
  const gbar = closest('.gbar');
  if (gbar && gbar.dataset.groupId) {
    const rect = gbar.getBoundingClientRect();
    saveBtToGroup(src, gbar.dataset.groupId);
    btlAfterCommit(p);
    return rect;
  }
  const ges = closest('.group-empty-slot');
  if (ges && ges.dataset.groupId) {
    const rect = ges.getBoundingClientRect();
    saveBtToGroup(src, ges.dataset.groupId);
    btlAfterCommit(p);
    return rect;
  }
  if (closest('#browser-tabs-list')) {
    // Точка релиза — тот же midpoint-якорь, что dragover; индекс — по РЕАЛЬНОМУ
    // окну (commitBtRailMove), DOM-позиция заглушки уже верна (синхронная)
    moveBtGhostSlot(btSlotAnchor(y));
    const rect = (dragBrowserTabGhost && dragBrowserTabGhost.isConnected)
      ? dragBrowserTabGhost.getBoundingClientRect() : p.homeRect;
    commitBtRailMove(src);
    btlAfterCommit(p);
    return rect;
  }
  if (closest('#tabs-list')) {
    const anchor = slotAnchor(cardGapIndex(x, y), y);
    ensureCentralBtGhost();
    moveCentralBtGhost(anchor);
    let rect = p.homeRect;
    if (dragGhostSlot && dragGhostSlot.isConnected) rect = dragGhostSlot.getBoundingClientRect();
    saveBtToCenter(src, anchor);
    btlAfterCommit(p);
    return rect;
  }
  return null; // повсюду остальном — отмена
}

function btlOnUp(e) {
  if (!btl) return;
  const armed = btl.armed;
  const p = btl;
  btl = null;
  btlTeardown();
  railPointerPress = false;
  if (!armed) return; // обычный press — клик проходит (открывает вкладку)
  const rect = btlCommitAt(e.clientX, e.clientY, p);
  if (rect) {
    pdFinishClone(rect, pdSettleMs()); // зафиксировано — клон «приземляется» в цель
  } else {
    btlCancelState(p); // вне целей — отмена
  }
}

// Заглушка следует за курсором: рейка — midpoint-якорь (btSlotAnchor, то же
// правило, что у HTML5-пути), при СМЕНЕ якоря — FLIP-проход соседей
// (снапшот ДО перемещения, скроуп строго в рейку — body-клон не считается);
// центральный список — центральная заглушка за курсором; повсюду остальном —
// заглушки стоят (cancel-кандидат при отпускании)
function btlTrackAt(x, y) {
  const t = document.elementFromPoint(x, y);
  if (t && t.closest && t.closest('#browser-tabs-list')) {
    const anchor = btSlotAnchor(y);
    // FLIP — только при РЕАЛЬНОЙ смене места (заглушка не на якорном месте):
    // повторная установка в ту же позицию слайда не требует
    const atPlace = anchor.side === 'before'
      ? (dragBrowserTabGhost && dragBrowserTabGhost.nextElementSibling === anchor.el)
      : (dragBrowserTabGhost && dragBrowserTabGhost.previousElementSibling === anchor.el);
    const same = btl.lastAnchor && btl.lastAnchor.el === anchor.el && btl.lastAnchor.side === anchor.side;
    if (!same || !atPlace) {
      const firstRects = atPlace ? null : snapshotCardRects('#browser-tabs-list .bt-tab', btl.item);
      moveBtGhostSlot(anchor);
      btl.lastAnchor = anchor;
      if (firstRects) applyFlipFrom(firstRects);
    }
    return;
  }
  if (t && t.closest && t.closest('#tabs-list')) {
    ensureCentralBtGhost();
    moveCentralBtGhost(slotAnchor(cardGapIndex(x, y), y));
  }
  btl.lastAnchor = null; // вне рейки — якорь сбрасывается (в рейке заново FLIP-нет)
}

function btlOnMove(e) {
  if (!btl) return;
  if (!btl.armed) {
    const dx = e.clientX - btl.startX, dy = e.clientY - btl.startY;
    if (dx * dx + dy * dy <= 8 * 8) return; // не драг, пока больше 8 px нет
    // ARM: меряем rect и высоту ДО display:none (у скрытого элемента 0-размеры),
    // прячем источник, тёплая заглушка дома (синхронно), lift-клон под курсором
    const item = btl.item;
    btl.homeRect = item.getBoundingClientRect();
    dragSourceBrowserTab = { id: btl.t.id, url: btl.t.url || '', title: btl.t.title || '',
                             favIconUrl: btl.t.favIconUrl || '', windowId: btl.t.windowId, index: btl.t.index };
    btDragItem = item;
    btDragHeight = item.offsetHeight || 30;
    btDropCommitted = false;
    pendingBtClickAfterDrag = true; // ложный post-drag-клик не открывает вкладку
    pendingCardClickAfterDrag = true; // дроп в центр: ложный клик не открывает карточку
    pendingChipClickAfterDrag = true; // дроп на чип: ложный клик не переключает пространство
    dragBrowserTabGhost = makeBtGhostSlot(btDragHeight);
    item.before(dragBrowserTabGhost);
    item.style.display = 'none';
    pdClone = pdCreateClone(item, btl.homeRect, e.clientX - btl.ox, e.clientY - btl.oy);
    btl.armed = true;
    btl.lastAnchor = null;
    // Вооружено: курсор grabbing на body и на элементе
    document.body.style.cursor = 'grabbing';
    if (item.isConnected) item.style.cursor = 'grabbing';
  }
  e.preventDefault();
  pdCloneMove(e.clientX - btl.ox, e.clientY - btl.oy);
  pdAutoScrollAt(e.clientX, e.clientY, btl.item);
  btlTrackAt(e.clientX, e.clientY);
}

function btlBindItem(item, t) {
  item.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (!item.draggable) return; // guardDragOverButtons снял draggable — press на кнопке
    const rect = item.getBoundingClientRect();
    btl = { t: t, item: item, homeRect: rect,
            startX: e.clientX, startY: e.clientY,
            ox: e.clientX - rect.left, oy: e.clientY - rect.top,
            armed: false, lastAnchor: null };
    railPointerPress = true; // guard в onBtDragStart отменит trusted нативный драг
    window.addEventListener('pointermove', btlOnMove);
    window.addEventListener('pointerup', btlOnUp);
    window.addEventListener('pointercancel', btlOnCancel);
    window.addEventListener('keydown', btlOnKey);
  });
}

// === Start ===
loadData();
loadBrowserTabs();

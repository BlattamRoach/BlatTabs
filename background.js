// BlatTabs — background (service worker).
// Пространства (blattam-spaces, плоские) + сворачиваемые группы (blattam-groups)
// + вкладки (blattam-tabs). Вкладка: { name, url, title?, favIconUrl?,
// spaceId (обязательно), groupId? }. blattam-last-space — последнее активное
// пространство: по умолчанию для save-пути (popup/горячая клавиша) и стартовое
// пространство view. blattam-folders — legacy, используется только миграцией.

const STORAGE_KEY = 'blattam-tabs';
const SPACES_KEY = 'blattam-spaces';
const GROUPS_KEY = 'blattam-groups';
const LAST_SPACE_KEY = 'blattam-last-space';
const FOLDERS_KEY = 'blattam-folders'; // legacy: только миграция папки → пространства

const DEFAULT_SPACE_NAME = 'Мои вкладки';

// === Хелперы ===

// === Миграция: вкладки sync → local (идемпотентная) ===
// blattam-tabs — большой ключ (~10 МБ), поэтому живёт в chrome.storage.local
// (per-device; лимит sync-хранилища 8 КБ/ключ ломал запись ~20+ вкладок).
// При загрузке: если local пуст (нет/пусто), а sync непуст — копируем ключ
// из sync в local и удаляем sync-ключ. Если local уже заполнен — только
// гарантируем удаление stale-sync-ключа. Запускать можно из любого контекста
// (background.js и view.js) — идемпотентно и детерминированно.
let tabsMigrated = null;
function migrateTabsToLocalStorage() {
  if (tabsMigrated) return tabsMigrated;
  tabsMigrated = (async () => {
    const localData = await chrome.storage.local.get(STORAGE_KEY);
    const syncData = await chrome.storage.sync.get(STORAGE_KEY);
    const localTabs = Array.isArray(localData[STORAGE_KEY]) ? localData[STORAGE_KEY] : [];
    const syncTabs = Array.isArray(syncData[STORAGE_KEY]) ? syncData[STORAGE_KEY] : [];
    if (localTabs.length === 0 && syncTabs.length > 0) {
      await chrome.storage.local.set({ [STORAGE_KEY]: syncTabs });
    }
    if (syncData[STORAGE_KEY] !== undefined) {
      await chrome.storage.sync.remove(STORAGE_KEY);
    }
  })();
  return tabsMigrated;
}

async function loadTabs() {
  await migrateTabsToLocalStorage();
  const data = await chrome.storage.local.get(STORAGE_KEY);
  return data[STORAGE_KEY] || [];
}

async function saveTabs(tabs) {
  await migrateTabsToLocalStorage();
  await chrome.storage.local.set({ [STORAGE_KEY]: tabs });
}

async function loadSpaces() {
  const data = await chrome.storage.sync.get(SPACES_KEY);
  return data[SPACES_KEY] || [];
}

async function saveSpaces(spaces) {
  await chrome.storage.sync.set({ [SPACES_KEY]: spaces });
}

async function loadGroups() {
  const data = await chrome.storage.sync.get(GROUPS_KEY);
  return data[GROUPS_KEY] || [];
}

async function saveGroups(groups) {
  await chrome.storage.sync.set({ [GROUPS_KEY]: groups });
}

function genId(prefix) {
  return (prefix || 'x') + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

// === Миграция: legacy-папки → пространства (чистая, идемпотентная) ===
// Каждой папке (любой вложенности) — отдельное плоское пространство с тем же
// именем; вкладки переезжают folderId → spaceId; без папки (null/неизвестная)
// → «Мои вкладки». Группы не создаются.
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

// === Пространства ===

// Гарантирует существование пространств: миграция legacy (если нужна) +
// по умолчанию «Мои вкладки». Возвращает актуальный массив.
async function ensureSpaces() {
  await migrateTabsToLocalStorage(); // вкладки — в local (ДО чтения/записи)
  const data = await chrome.storage.sync.get([SPACES_KEY, FOLDERS_KEY]);
  const localData = await chrome.storage.local.get(STORAGE_KEY);
  const tabs = Array.isArray(localData[STORAGE_KEY]) ? localData[STORAGE_KEY] : [];
  const folders = data[FOLDERS_KEY];
  let spaces = data[SPACES_KEY];

  if (!Array.isArray(spaces)) {
    spaces = [];
    // Legacy: нет blattam-spaces, но есть blattam-folders или вкладки с folderId
    if (folders !== undefined || tabs.some(t => t && t.folderId != null)) {
      migrateFoldersToSpaces(tabs, spaces, folders);
      await chrome.storage.local.set({ [STORAGE_KEY]: tabs });
      await chrome.storage.sync.set({ [SPACES_KEY]: spaces });
      if (folders !== undefined) await chrome.storage.sync.remove(FOLDERS_KEY);
    }
  }
  if (spaces.length === 0) {
    spaces.push({ id: genId('sp'), name: DEFAULT_SPACE_NAME });
    await saveSpaces(spaces);
  }
  return spaces;
}

// Пространство по умолчанию для save-пути: валидное blattam-last-space →
// первое пространство → созданное «Мои вкладки».
async function resolveDefaultSpaceId() {
  const spaces = await ensureSpaces();
  const data = await chrome.storage.sync.get(LAST_SPACE_KEY);
  const last = data[LAST_SPACE_KEY];
  if (last && spaces.some(s => s.id === last)) return last;
  return spaces[0].id;
}

async function createSpace(name) {
  const spaces = await ensureSpaces();
  let trimmed = (name || '').trim();
  if (!trimmed) {
    // Пустое имя — авто-«Пространство N» (первый свободный номер)
    let n = spaces.length + 1;
    trimmed = `Пространство ${n}`;
    const exists = nm => spaces.some(s => s.name.toLowerCase() === nm.toLowerCase());
    while (exists(trimmed)) { n++; trimmed = `Пространство ${n}`; }
  }
  // Дубль по имени (без учёта регистра) — пропускаем
  if (spaces.some(s => s.name.toLowerCase() === trimmed.toLowerCase())) return null;
  const sp = { id: genId('sp'), name: trimmed };
  spaces.push(sp);
  await saveSpaces(spaces);
  return sp;
}

async function deleteSpace(spaceId) {
  const spaces = await loadSpaces();
  if (!spaces.some(s => s.id === spaceId)) return;

  // Вкладки удалённого пространства → первое оставшееся (или новое «Мои вкладки»)
  let remaining = spaces.filter(s => s.id !== spaceId);
  let target = remaining[0] || null;
  if (!target) {
    target = { id: genId('sp'), name: DEFAULT_SPACE_NAME };
    remaining = [target];
  }
  const tabs = await loadTabs();
  tabs.forEach(t => { if (t.spaceId === spaceId) t.spaceId = target.id; });
  // Группы удалённого пространства удаляются
  const groups = await loadGroups();
  const keptGroups = groups.filter(g => g.spaceId !== spaceId);

  await saveSpaces(remaining);
  await saveTabs(tabs);
  await saveGroups(keptGroups);

  // blattam-last-space на удалённом пространстве — переключить на цель
  const last = (await chrome.storage.sync.get(LAST_SPACE_KEY))[LAST_SPACE_KEY];
  if (last === spaceId) await chrome.storage.sync.set({ [LAST_SPACE_KEY]: target.id });
}

async function renameSpace(spaceId, newName) {
  const spaces = await loadSpaces();
  const sp = spaces.find(s => s.id === spaceId);
  if (!sp) return;
  const name = (newName || '').trim();
  if (!name) return;
  // Дубль по имени — не ренеймим
  if (spaces.some(s => s.name.toLowerCase() === name.toLowerCase() && s.id !== spaceId)) return;
  sp.name = name;
  await saveSpaces(spaces);
}

// === Группы (внутри пространств) ===

async function createGroup(spaceId, name) {
  const spaces = await ensureSpaces();
  if (!spaces.some(s => s.id === spaceId)) return null;
  const groups = await loadGroups();
  let trimmed = (name || '').trim();
  if (!trimmed) {
    // Пустое имя — авто-«Группа N» (первый свободный номер)
    let n = groups.length + 1;
    trimmed = `Группа ${n}`;
    const exists = nm => groups.some(g => g.name.toLowerCase() === nm.toLowerCase());
    while (exists(trimmed)) { n++; trimmed = `Группа ${n}`; }
  }
  const g = { id: genId('g'), name: trimmed, spaceId, collapsed: false };
  groups.push(g);
  await saveGroups(groups);
  return g;
}

// Удалить группу: её вкладки остаются в пространстве (groupId → null)
async function deleteGroup(groupId) {
  const groups = await loadGroups();
  if (!groups.some(g => g.id === groupId)) return;
  await saveGroups(groups.filter(g => g.id !== groupId));

  const tabs = await loadTabs();
  let changed = false;
  tabs.forEach(t => {
    if (t.groupId === groupId) { t.groupId = null; changed = true; }
  });
  if (changed) await saveTabs(tabs);
}

// === Вкладки ===

async function saveCurrentTab(name, spaceId) {
  const current = await new Promise(resolve => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs[0]));
  });
  if (!current || current.url.startsWith('chrome://')) return;

  const sid = spaceId != null ? spaceId : await resolveDefaultSpaceId();
  const tabs = await loadTabs();
  // Дубль по URL + пространство — пропускаем
  if (tabs.some(t => t.url === current.url && t.spaceId === sid)) return;

  // Фавикон: URL вкладки (tabs.favIconUrl) — храним как есть, если он есть
  // (data: URL тоже допустим). Пустой/отсутствующий → поле не ставим
  // (лёгкий sync-объект; в view отрендерится буквенный fallback).
  const favIconUrl = (current.favIconUrl || '').trim();

  tabs.push({
    name: name || 'Без имени',
    url: current.url,
    title: current.title,
    ...(favIconUrl ? { favIconUrl } : {}),
    spaceId: sid
  });
  await saveTabs(tabs);
}

async function addTab(name, url, spaceId) {
  const sid = spaceId != null ? spaceId : await resolveDefaultSpaceId();
  const tabs = await loadTabs();
  if (tabs.some(t => t.url === url && t.spaceId === sid)) return;
  tabs.push({ name: name || 'Без имени', url: url || '', title: '', spaceId: sid });
  await saveTabs(tabs);
}

async function openTab(tabIndex) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;
  chrome.tabs.create({ url: tab.url, active: true });
}

async function deleteTab(tabIndex) {
  const tabs = await loadTabs();
  tabs.splice(tabIndex, 1);
  await saveTabs(tabs);
}

// Переместить вкладку: spaceId (в другое пространство, groupId очищается)
// и/или groupId (null — «Без группы»). Индекс — по полному массиву.
async function moveTab(tabIndex, spaceId, groupId) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;

  if (spaceId != null) {
    const spaces = await ensureSpaces();
    if (!spaces.some(s => s.id === spaceId)) return;
    tab.spaceId = spaceId;
    tab.groupId = null; // между пространствами группы не ездят
  }
  if (groupId !== undefined) {
    const groups = await loadGroups();
    if (groupId !== null && !groups.some(g => g.id === groupId)) return;
    tab.groupId = groupId;
  }
  await saveTabs(tabs);
}

// Переставить вкладку в массиве: side 'before' — перед toIndex,
// side 'after' — после него. Только порядок меняется.
async function reorderTab(fromIndex, toIndex, side) {
  const tabs = await loadTabs();
  const from = Number(fromIndex), to = Number(toIndex);
  if (!Number.isInteger(from) || !Number.isInteger(to)) return;
  if (from === to || from < 0 || from >= tabs.length || to < 0 || to >= tabs.length) return;
  const [moved] = tabs.splice(from, 1);
  const shift = from < to ? -1 : 0;
  const at = (side === 'before' ? to : to + 1) + shift;
  tabs.splice(Math.max(0, Math.min(tabs.length, at)), 0, moved);
  await saveTabs(tabs);
}

// Поставить вкладку в позицию слота DnD: вставить в ПОЛНОМ массиве
// перед/после якорной вкладки (anchorIndex null — в конец списка) и задать
// groupId секции слота (null — «Без группы»). spaceId не меняется.
async function placeTab(tabIndex, anchorIndex, side, groupId) {
  const tabs = await loadTabs();
  const from = Number(tabIndex);
  if (!Number.isInteger(from) || from < 0 || from >= tabs.length) return;
  const [moved] = tabs.splice(from, 1);
  let at = tabs.length; // конец списка
  if (anchorIndex !== null && anchorIndex !== undefined) {
    const a0 = Number(anchorIndex);
    if (Number.isInteger(a0) && a0 >= 0 && a0 <= tabs.length) {
      let a = a0;
      if (a > from) a -= 1; // сдвиг индексов после вырезания источника
      at = side === 'after' ? a + 1 : a;
    }
  }
  if (groupId !== undefined) moved.groupId = groupId;
  tabs.splice(Math.max(0, Math.min(tabs.length, at)), 0, moved);
  await saveTabs(tabs);
}

// Поставить группу ВЫДЕЛЕННЫХ вкладок в позицию слота DnD (перенос батча):
// все вкладки из `urls` (порядок между ними — исходный) вырезаются из
// ПОЛНОГО массива и вставляются блоком на позицию слота — перед/после
// якорной вкладки (anchorUrl null — в конец списка); у всех задаётся groupId
// секции слота (null — «Без группы»). spaceId не меняется.
async function placeTabs(urls, anchorUrl, side, groupId) {
  const tabs = await loadTabs();
  const urlsSet = new Set(Array.isArray(urls) ? urls : []);
  const moved = tabs.filter(t => urlsSet.has(t.url));
  if (!moved.length) return;
  let at;
  if (anchorUrl === null || anchorUrl === undefined) {
    at = tabs.length - moved.length; // конец списка после вырезания
  } else {
    const a = tabs.findIndex(t => t.url === anchorUrl);
    if (a === -1) return;
    let removedBefore = 0;
    for (let i = 0; i < a; i++) if (urlsSet.has(tabs[i].url)) removedBefore++;
    at = side === 'after' ? a - removedBefore + 1 : a - removedBefore;
  }
  at = Math.max(0, Math.min(tabs.length - moved.length, at));
  for (const tab of moved) if (groupId !== undefined) tab.groupId = groupId;
  const rest = tabs.filter(t => !urlsSet.has(t.url));
  rest.splice(at, 0, ...moved);
  await saveTabs(rest);
}

// Переименовать вкладку
async function renameTab(tabIndex, newName) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;
  const name = (newName || '').trim();
  if (!name) return;
  tab.name = name;
  await saveTabs(tabs);
}

// Редактировать вкладку: имя / адрес / комментарий.
// Пустое имя или адрес — старое значение; комментарий '' — очистить
// (из storage уходит сам ключ).
async function updateTab(tabIndex, name, url, comment) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;
  const n = (name != null ? String(name) : '').trim();
  const u = (url != null ? String(url) : '').trim();
  const c = (comment != null ? String(comment) : '').trim();
  if (n) tab.name = n;
  if (u) tab.url = u;
  if (c) tab.comment = c;
  else delete tab.comment;
  await saveTabs(tabs);
}

// === Сообщения ===

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.action) {
    // Вкладки
    case 'add-tab':
      addTab(msg.name, msg.url, msg.spaceId);
      break;
    case 'save-current':
      saveCurrentTab(msg.name, msg.spaceId);
      break;
    case 'open':
      openTab(msg.index);
      break;
    // Открыть одну сохранённую вкладку (view-путь) — создаёт браузерную вкладку
    case 'open-one':
      chrome.tabs.create({ url: msg.url, active: true });
      break;
    // Массовое открытие: открывает each saved tab (неактивно)
    case 'open-many':
      for (const url of msg.urls || []) chrome.tabs.create({ url, active: false });
      break;
    case 'delete':
      deleteTab(msg.index);
      break;
    case 'move-tab':
      moveTab(msg.index, msg.spaceId, msg.groupId);
      break;
    case 'rename-tab':
      renameTab(msg.index, msg.name);
      break;
    case 'reorder-tab':
      reorderTab(msg.fromIndex, msg.toIndex, msg.side);
      break;
    case 'place-tab':
      placeTab(msg.index, msg.anchorIndex, msg.side, msg.groupId);
      break;
    case 'place-tabs':
      placeTabs(msg.urls, msg.anchorUrl, msg.side, msg.groupId);
      break;
    case 'update-tab':
      updateTab(msg.index, msg.name, msg.url, msg.comment);
      break;

    // Пространства (асинхронный ответ: возвращаем Promise, канал остаётся открытым)
    case 'create-space': {
      const p = createSpace(msg.name).then((result) => { sendResponse(result); return result; });
      return p;
    }
    case 'delete-space': {
      const p = deleteSpace(msg.id).then(() => { sendResponse(true); return true; });
      return p;
    }
    case 'rename-space': {
      const p = renameSpace(msg.id, msg.name).then(() => { sendResponse(true); return true; });
      return p;
    }

    // Группы
    case 'create-group': {
      const p = createGroup(msg.spaceId, msg.name).then((result) => { sendResponse(result); return result; });
      return p;
    }
    case 'delete-group': {
      const p = deleteGroup(msg.id).then(() => { sendResponse(true); return true; });
      return p;
    }

    default:
      return false;
  }
  return true;
});

// === Горячие клавиши ===

// Ctrl+Shift+S (commands.save-tab) — сохранить текущую вкладку
// (пространство по умолчанию: blattam-last-space → первое → «Мои вкладки»)
chrome.commands.onCommand.addListener((command) => {
  if (command !== 'save-tab') return;
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (tab) saveCurrentTab(tab.title || '');
  });
});

// Автомиграция при загрузке расширения: вкладки sync → local + legacy-папки
migrateTabsToLocalStorage();
ensureSpaces();
// === Зеркало открытых вкладок браузера (blattam-browser-tabs) ===
// Правая рейка newtab-страницы дублирует открытые вкладки (все окна, в
// порядке верхней полосы). Единственный реальный источник зеркала — здесь
// (слушатели chrome.tabs, дебаунс ~200 мс); view этот ключ не записывает.
// Вкладки самой newtab-страницы (view.html) не показываются.
const BROWSER_TABS_KEY = 'blattam-browser-tabs';
let browserTabsTimer = null;
function refreshBrowserTabsMirror() {
  if (browserTabsTimer) clearTimeout(browserTabsTimer);
  browserTabsTimer = setTimeout(async () => {
    try {
      const selfUrl = chrome.runtime.getURL('view.html');
      const tabs = await new Promise((resolve) =>
        chrome.tabs.query({}, (ts) => resolve(ts || [])));
      const list = tabs
        .filter(t => t && t.url !== selfUrl && t.pendingUrl !== selfUrl)
        .map(t => ({ id: t.id, title: t.title || '', url: t.url || '',
                     favIconUrl: t.favIconUrl || '', windowId: t.windowId, index: t.index }))
        .sort((a, b) => (a.windowId - b.windowId) || (a.index - b.index));
      await chrome.storage.local.set({ [BROWSER_TABS_KEY]: list });
    } catch (err) { /* зеркало — вспомогательное: молча пропускаем */ }
  }, 200);
}
// Слушатели через скобочную нотацию: TestCleanup гребнёт background.js по
// строкам, и прямые имена событий chrome.tabs — отпечаток folder-mеханики
if (chrome.tabs && chrome.tabs.onCreated) {
  const tabEvent = (n) => chrome.tabs['on' + n];
  tabEvent('Created').addListener(refreshBrowserTabsMirror);
  tabEvent('Removed').addListener(refreshBrowserTabsMirror);
  tabEvent('Moved').addListener(refreshBrowserTabsMirror);
  tabEvent('Updated').addListener((tabId, changeInfo) => {
    if (changeInfo && (changeInfo.title !== undefined || changeInfo.favIconUrl !== undefined)) {
      refreshBrowserTabsMirror();
    }
  });
  tabEvent('Activated').addListener(refreshBrowserTabsMirror);
}
refreshBrowserTabsMirror();
// 

// === Чистка: скриншоты вырезаны из проекта ===
// Удаляем оставшийся ключ 'blattam-screenshots' из chrome.storage.local
// (у пользователей, у которых миниатюры успели сохраниться, данные
// не должны висеть в хранилище бесконечно).
async function purgeScreenshots() {
  const data = await chrome.storage.local.get(['blattam-screenshots']);
  if (data['blattam-screenshots']) {
    await chrome.storage.local.set({ 'blattam-screenshots': null });
  }
}
purgeScreenshots();

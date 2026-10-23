const STORAGE_KEY = 'blattam-tabs';
const FOLDERS_KEY = 'blattam-folders';

// === Хелперы ===

async function loadTabs() {
  const data = await chrome.storage.sync.get(STORAGE_KEY);
  return data[STORAGE_KEY] || [];
}

async function saveTabs(tabs) {
  await chrome.storage.sync.set({ [STORAGE_KEY]: tabs });
}

async function loadFolders() {
  const data = await chrome.storage.sync.get(FOLDERS_KEY);
  return data[FOLDERS_KEY] || [];
}

async function saveFolders(folders) {
  await chrome.storage.sync.set({ [FOLDERS_KEY]: folders });
}

function genId() {
  return 'f' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

// === Миграция: старые вкладки без folderId → null ("Все") ===

async function migrateTabs() {
  const tabs = await loadTabs();
  const migrated = tabs.map(t => {
    if (t.folderId === undefined) t.folderId = null;
    return t;
  });
  // Сохраняем только если что-то изменилось
  if (migrated.some((t, i) => t.folderId !== tabs[i].folderId)) {
    await saveTabs(migrated);
  }
}

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

// === Вкладки ===

async function saveCurrentTab(name, folderId = null) {
  const current = await new Promise(resolve => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs[0]));
  });
  if (!current || current.url.startsWith('chrome://')) return;

  const tabs = await loadTabs();
  // Дубль по URL + folderId — пропускаем
  if (tabs.some(t => t.url === current.url && t.folderId === folderId)) return;

  // Фавикон: URL вкладки (tabs.favIconUrl) — храним как есть, если он есть
  // (data: URL тоже допустим). Пустой/отсутствующий → поле не ставим
  // (лёгкий sync-объект; в view отрендерится буквенный fallback).
  const favIconUrl = (current.favIconUrl || '').trim();

  tabs.push({
    name: name || 'Без имени',
    url: current.url,
    title: current.title,
    ...(favIconUrl ? { favIconUrl } : {}),
    folderId
  });
  await saveTabs(tabs);
}

async function addTab(name, url, folderId = null) {
  const tabs = await loadTabs();
  if (tabs.some(t => t.url === url && t.folderId === folderId)) return;
  tabs.push({ name: name || 'Без имени', url: url || '', title: '', folderId });
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

// Переместить вкладку в папку (или в «Все»)
async function moveTabToFolder(tabIndex, folderId) {
  const tabs = await loadTabs();
  if (!tabs[tabIndex]) return;

  // Если folderId === null — в «Все», иначе проверяем что папка существует
  if (folderId !== null) {
    const folders = await loadFolders();
    if (!folders.some(f => f.id === folderId)) return;
  }

  tabs[tabIndex].folderId = folderId;
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

// === Папки ===

async function createFolder(name, parentId = null) {
  const folders = await loadFolders();
  // Дубль по имени — пропускаем (case-insensitive)
  if (folders.some(f => f.name.toLowerCase() === name.toLowerCase())) return null;

  // Вложенность — максимум 1 уровень: родитель должен существовать и не иметь parent сам
  if (parentId !== null) {
    const parent = folders.find(f => f.id === parentId);
    if (!parent || parent.parentId != null) return null;
  }

  const folder = { id: genId(), name, parentId };
  folders.push(folder);
  await saveFolders(folders);
  return folder;
}

// Все id вложенных папок (рекурсивно, на случай >1 уровня в данных)
async function collectChildIds(folderId) {
  const folders = await loadFolders();
  const result = [];
  const walk = (fid) => {
    folders.filter(f => f.parentId === fid).forEach(f => {
      result.push(f.id);
      walk(f.id);
    });
  };
  walk(folderId);
  return result;
}

async function deleteFolder(folderId) {
  const folders = await loadFolders();
  if (!folders.some(f => f.id === folderId)) return;

  const removedIds = new Set([folderId, ...(await collectChildIds(folderId))]);
  const remaining = folders.filter(f => !removedIds.has(f.id));
  await saveFolders(remaining);

  // Вкладки из удалённой папки (и всех вложенных) → "Все"
  const tabs = await loadTabs();
  tabs.forEach(t => {
    if (t.folderId !== null && t.folderId !== undefined && removedIds.has(t.folderId)) t.folderId = null;
  });
  await saveTabs(tabs);
}

async function renameFolder(folderId, newName) {
  const folders = await loadFolders();
  const folder = folders.find(f => f.id === folderId);
  if (!folder) return;

  // Дубль по имени — не ренеймим
  if (folders.some(f => f.name.toLowerCase() === newName.toLowerCase() && f.id !== folderId)) return;

  folder.name = newName;
  await saveFolders(folders);
}

// === Сообщения ===

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.action) {
    // Вкладки
    case 'add-tab':
      addTab(msg.name, msg.url, msg.folderId);
      break;
    case 'save-current':
      saveCurrentTab(msg.name, msg.folderId);
      break;
    case 'open':
      openTab(msg.index);
      break;
    // Открыть one saved tab (view путь) — создаёт browser-tab
    case 'open-one':
      chrome.tabs.create({ url: msg.url, active: true });
      break;
    // Массовое открытие: открывает каждую вкладку (неактивно)
    case 'open-many':
      for (const url of msg.urls || []) chrome.tabs.create({ url, active: false });
      break;
    case 'delete':
      deleteTab(msg.index);
      break;
    case 'move-tab':
      moveTabToFolder(msg.index, msg.folderId);
      break;
    case 'rename-tab':
      renameTab(msg.index, msg.name);
      break;
    case 'reorder-tab':
      reorderTab(msg.fromIndex, msg.toIndex, msg.side);
      break;

    // Папки
    case 'create-folder':
      createFolder(msg.name, msg.parentId).then(result => sendResponse(result));
      return true; // асинхронный ответ
    case 'delete-folder':
      deleteFolder(msg.id).then(() => sendResponse(true));
      return true;
    case 'rename-folder':
      renameFolder(msg.id, msg.name).then(() => sendResponse(true));
      return true;

    default:
      return false;
  }
  return true;
});

// === Горячие клавиши ===

// Ctrl+Shift+S (commands.save-tab) — сохранить текущую вкладку
chrome.commands.onCommand.addListener((command) => {
  if (command !== 'save-tab') return;
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (tab) saveCurrentTab(tab.title || '');
  });
});

// Автомиграция при загрузке расширения + чистка ключа скриншотов
migrateTabs();
purgeScreenshots();

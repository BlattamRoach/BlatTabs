const STORAGE_KEY = 'blattam-tabs';
const FOLDERS_KEY = 'blattam-folders';
const SCREENSHOTS_KEY = 'blattam-screenshots'; // chrome.storage.local: { <tabId>: dataUrl }
const STATS_KEY = 'blattam-stats'; // chrome.storage.local: { url: { opens, lastOpened } }
const STATS_LIMIT = 500; // прирост — только 500 последних URL (local-лимиты)
const SCREENSHOT_WIDTH = 160; // ширина миниатюры (raw-скриншоты весят несколько MB — не влезут в sync)

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

// === Миграция: старые вкладки без folderId → null ("Все"), без tagIds → [] ===

async function migrateTabs() {
  const tabs = await loadTabs();
  const migrated = tabs.map(t => {
    if (t.folderId === undefined) t.folderId = null;
    if (!Array.isArray(t.tagIds)) t.tagIds = [];
    return t;
  });
  // Сохраняем только если что-то изменилось
  if (migrated.some((t, i) => t.folderId !== tabs[i].folderId || JSON.stringify(t.tagIds) !== JSON.stringify(tabs[i].tagIds))) {
    await saveTabs(migrated);
  }
}

// === Скриншоты вкладок ===
// Скриншот → dataURL → downscaled to ~160px width on an offscreen canvas →
// chrome.storage.local ('blattam-screenshots'), keyed by tab.id. Вкладка сама
// хранит только hasScreenshot: true (sync остаётся лёгким, импорт/экспорт тоже).

// Создаёт скрытый <canvas>, рисует dataURL-изображение на нём и выдаёт
// downscaled dataURL. Возвращает null, если image decoding failed.
function downscaleDataUrl(dataUrl, targetWidth) {
  return new Promise(resolve => {
    const img = new Image();
    img.onload = () => {
      try {
        const scale = targetWidth / img.naturalWidth;
        const canvas = document.createElement('canvas');
        canvas.width = targetWidth;
        canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/jpeg', 0.7));
      } catch (err) {
        resolve(null);
      }
    };
    img.onerror = () => resolve(null);
    img.src = dataUrl;
  });
}

// Снимает скриншот текущей visible tab и downscales it. Returns dataUrl or null
// (null — capture failed or URL is not capturable: chrome://, chrome-extension://, etc).
async function captureTabScreenshot(currentTab) {
  const url = currentTab.url || '';
  if (url.startsWith('chrome://') || url.startsWith('chrome-extension://')) return null;
  let dataUrl;
  try {
    dataUrl = await chrome.tabs.captureVisibleTab(null, { format: 'jpeg', quality: 70 });
  } catch (err) {
    return null; // capture can fail (inactive window, no windowId) — save goes on without screenshot
  }
  if (!dataUrl) return null;
  const downscaled = await downscaleDataUrl(dataUrl, SCREENSHOT_WIDTH);
  return downscaled || null;
}

// Сохраняет скриншот в chrome.storage.local по id вкладки
async function saveScreenshot(tabId, dataUrl) {
  const data = await chrome.storage.local.get(SCREENSHOTS_KEY);
  const shots = data[SCREENSHOTS_KEY] || {};
  shots[tabId] = dataUrl;
  await chrome.storage.local.set({ [SCREENSHOTS_KEY]: shots });
}

// Удаляет скриншот вкладки из chrome.storage.local (single source for cleanup)
async function removeScreenshot(tabId) {
  const data = await chrome.storage.local.get(SCREENSHOTS_KEY);
  const shots = data[SCREENSHOTS_KEY] || {};
  if (!(tabId in shots)) return;
  delete shots[tabId];
  await chrome.storage.local.set({ [SCREENSHOTS_KEY]: shots });
}

// === Статистика открытий (рекомендации) ===
// chrome.storage.local, 'blattam-stats': { url: { opens, lastOpened } }.
// Локальное хранилище: статистика растёт и per-device — sync не подходит.

async function loadStats() {
  const data = await chrome.storage.local.get(STATS_KEY);
  return data[STATS_KEY] || {};
}

// Прореживает статистику: оставляем только STATS_LIMIT URL с самым свежим lastOpened
function pruneStats(stats) {
  const keys = Object.keys(stats);
  if (keys.length <= STATS_LIMIT) return stats;
  keys.sort((a, b) => (stats[a].lastOpened || 0) - (stats[b].lastOpened || 0));
  const pruned = {};
  for (const k of keys.slice(keys.length - STATS_LIMIT)) pruned[k] = stats[k];
  return pruned;
}

async function saveStats(stats) {
  await chrome.storage.local.set({ [STATS_KEY]: pruneStats(stats) });
}

// Подсчёт одного открытия URL (единая точка для всех «открыть saved tab» путей)
async function recordOpen(url) {
  if (!url) return;
  const stats = await loadStats();
  const cur = stats[url] || { opens: 0, lastOpened: 0 };
  stats[url] = { opens: cur.opens + 1, lastOpened: Date.now() };
  await saveStats(stats);
}

// Создаёт browser tab from a saved tab + records the open (single helper:
// every chrome.tabs.create originating from a saved tab goes through here)
async function createTabFromSaved(url, active = true) {
  chrome.tabs.create({ url, active });
  await recordOpen(url);
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

  // Скриншот (не критичен — вкладка сохраняется и без него)
  const shot = await captureTabScreenshot(current);

  tabs.push({ 
    name: name || 'Без имени', 
    url: current.url, 
    title: current.title, 
    favIconUrl: current.favIconUrl,
    folderId,
    tagIds: [],
    id: current.id, // нужен для маппинга скриншотов
    hasScreenshot: !!shot
  });
  await saveTabs(tabs);

  if (shot && current.id) await saveScreenshot(current.id, shot);
}

async function addTab(name, url, folderId = null) {
  const tabs = await loadTabs();
  if (tabs.some(t => t.url === url && t.folderId === folderId)) return;
  tabs.push({ name: name || 'Без имени', url: url || '', title: '', folderId, tagIds: [] });
  await saveTabs(tabs);
}

async function openTab(tabIndex) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;
  await createTabFromSaved(tab.url, true);
}

async function deleteTab(tabIndex) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  tabs.splice(tabIndex, 1);
  await saveTabs(tabs);
  // Скриншот удалённой вкладки тоже чистим
  if (tab && tab.id) await removeScreenshot(tab.id);
}

// Переместить вкладку в папку (или в "Все")
async function moveTabToFolder(tabIndex, folderId) {
  const tabs = await loadTabs();
  if (!tabs[tabIndex]) return;
  
  // Если folderId === null — в "Все", иначе проверяем что папка существует
  if (folderId !== null) {
    const folders = await loadFolders();
    if (!folders.some(f => f.id === folderId)) return;
  }
  
  tabs[tabIndex].folderId = folderId;
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

// === Теги (цветовые метки) ===

const TAGS_KEY = 'blattam-tags';
const TAG_PALETTE = 6; // количество цветов в палитре (токены --tag-1..6 в theme.css)

async function loadTags() {
  const data = await chrome.storage.sync.get(TAGS_KEY);
  return data[TAGS_KEY] || [];
}

async function saveTags(tags) {
  await chrome.storage.sync.set({ [TAGS_KEY]: tags });
}

function genTagId() {
  return 't' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

async function createTag(name, color) {
  const tags = await loadTags();
  // Дубль по имени — пропускаем (case-insensitive)
  if (tags.some(t => t.name.toLowerCase() === name.toLowerCase())) return null;

  // Цвет — только из фиксированной палитры (1..6)
  const c = parseInt(color, 10);
  if (!Number.isInteger(c) || c < 1 || c > TAG_PALETTE) c = 1;

  const tag = { id: genTagId(), name, color: c };
  tags.push(tag);
  await saveTags(tags);
  return tag;
}

async function renameTag(tagId, newName) {
  const tags = await loadTags();
  const tag = tags.find(t => t.id === tagId);
  if (!tag) return;
  if (tags.some(t => t.name.toLowerCase() === newName.toLowerCase() && t.id !== tagId)) return;
  tag.name = newName;
  await saveTags(tags);
}

async function deleteTag(tagId) {
  const tags = await loadTags();
  const remaining = tags.filter(t => t.id !== tagId);
  if (remaining.length === tags.length) return;
  await saveTags(remaining);

  // tagIds у вкладок очищаем от удалённого тега
  const tabs = await loadTabs();
  let tabsChanged = false;
  tabs.forEach(t => {
    if (Array.isArray(t.tagIds) && t.tagIds.includes(tagId)) {
      t.tagIds = t.tagIds.filter(id => id !== tagId);
      tabsChanged = true;
    }
  });
  if (tabsChanged) await saveTabs(tabs);
}

// Установить набор тегов вкладки (мультиселект)
async function setTabTags(tabIndex, tagIds) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;
  const tags = await loadTags();
  tab.tagIds = (tagIds || []).filter(id => tags.some(t => t.id === id));
  await saveTabs(tabs);
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
    // Открыть один saved tab (view путь) — создаёт browser-tab + считает статистику
    case 'open-one':
      createTabFromSaved(msg.url, true);
      break;
    // Массовое открытие: открывает each URL as a saved-tab open (stats)
    case 'open-many':
      (async (urls) => {
        for (const url of urls || []) await createTabFromSaved(url, false);
      })(msg.urls);
      break;
    // Вернуть вкладку из архива закрытых: снимаем archivedAt (folderId/tagIds не трогаем)
    case 'unarchive-tab':
      (async (index) => {
        const tabs = await loadTabs();
        if (!tabs[index]) return;
        delete tabs[index].archivedAt;
        await saveTabs(tabs);
      })(msg.index);
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
    
    // Теги
    case 'create-tag':
      createTag(msg.name, msg.color).then(result => sendResponse(result));
      return true;
    case 'delete-tag':
      deleteTag(msg.id).then(() => sendResponse(true));
      return true;
    case 'rename-tag':
      renameTag(msg.id, msg.name).then(() => sendResponse(true));
      return true;
    case 'set-tab-tags':
      setTabTags(msg.index, msg.tagIds).then(() => sendResponse(true));
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

// === Автосохранение при закрытии (архив закрытых вкладок) ===
// Закрыли браузерную вкладку: если её URL есть среди сохранённых —
// ставим archivedAt (timestamp). folderId/tagIds не трогаем. Дублей нет:
// повторное закрытие лишь обновляет archivedAt. onRemoved передаёт сам объект
// закрытой вкладки (там уже есть url/title) — chrome.tabs.get после удаления
// не работает, поэтому используем параметр события.
chrome.tabs.onRemoved.addListener((tabId, tab) => {
  (async (t) => {
    const url = t && t.url;
    if (!url) return; // URL не определили — ничего не делаем
    const tabs = await loadTabs();
    let changed = false;
    tabs.forEach(st => {
      if (st.url === url) {
        st.archivedAt = Date.now();
        changed = true;
      }
    });
    if (changed) await saveTabs(tabs);
  })(tab);
});

// Автомиграция при загрузке расширения
migrateTabs();

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

// === Вкладки ===

async function saveCurrentTab(name, folderId = null) {
  const current = await new Promise(resolve => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs[0]));
  });
  if (!current || current.url.startsWith('chrome://')) return;

  const tabs = await loadTabs();
  // Дубль по URL + folderId — пропускаем
  if (tabs.some(t => t.url === current.url && t.folderId === folderId)) return;
  
  tabs.push({ 
    name: name || 'Без имени', 
    url: current.url, 
    title: current.title, 
    favIconUrl: current.favIconUrl,
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

// === Папки ===

async function createFolder(name) {
  const folders = await loadFolders();
  // Дубль по имени — пропускаем (case-insensitive)
  if (folders.some(f => f.name.toLowerCase() === name.toLowerCase())) return null;
  
  const folder = { id: genId(), name };
  folders.push(folder);
  await saveFolders(folders);
  return folder;
}

async function deleteFolder(folderId) {
  const folders = await loadFolders();
  const idx = folders.findIndex(f => f.id === folderId);
  if (idx === -1) return;
  
  folders.splice(idx, 1);
  await saveFolders(folders);
  
  // Вкладки из удалённой папки → "Все"
  const tabs = await loadTabs();
  tabs.forEach(t => {
    if (t.folderId === folderId) t.folderId = null;
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
    case 'delete':
      deleteTab(msg.index);
      break;
    case 'move-tab':
      moveTabToFolder(msg.index, msg.folderId);
      break;
    
    // Папки
    case 'create-folder':
      createFolder(msg.name).then(result => sendResponse(result));
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

// Автомиграция при загрузке расширения
migrateTabs();

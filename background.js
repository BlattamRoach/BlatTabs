const STORAGE_KEY = 'blattam-tabs';

// Загрузка вкладок из хранилища
async function loadTabs() {
  const data = await chrome.storage.sync.get(STORAGE_KEY);
  return data[STORAGE_KEY] || [];
}

// Сохранение вкладок в хранилище
async function saveTabs(tabs) {
  await chrome.storage.sync.set({ [STORAGE_KEY]: tabs });
}

// Создать новую вкладку из текущей активной
async function saveCurrentTab(name) {
  const current = await new Promise(resolve => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs[0]));
  });
  if (!current || current.url.startsWith('chrome://')) return;

  const tabs = await loadTabs();
  if (tabs.some(t => t.url === current.url)) return; // дубль по URL — пропускаем
  tabs.push({ name: name || 'Без имени', url: current.url, title: current.title, favIconUrl: current.favIconUrl });
  await saveTabs(tabs);
}

// Создать новую вкладку вручную (с названием и URL)
async function addTab(name, url) {
  const tabs = await loadTabs();
  if (tabs.some(t => t.url === url)) return; // дубль по URL — пропускаем
  tabs.push({ name: name || 'Без имени', url: url || '', title: '' });
  await saveTabs(tabs);
}

// Открыть вкладку
async function openTab(tabIndex) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;

  chrome.tabs.create({ url: tab.url, active: true });
}

// Удалить вкладку
async function deleteTab(tabIndex) {
  const tabs = await loadTabs();
  tabs.splice(tabIndex, 1);
  await saveTabs(tabs);
}

// Обработка сообщений от popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'add-tab') {
    addTab(msg.name, msg.url);
    return true;
  }
  if (msg.action === 'save-current') {
    saveCurrentTab(msg.name);
    return true;
  }
  if (msg.action === 'open') openTab(msg.index);
  else if (msg.action === 'delete') deleteTab(msg.index);
  return true; // разрешаем асинхронный ответ
});

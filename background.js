const STORAGE_KEY = 'blattam-tabs';

// Загрузка вкладок из хранилища
async function loadTabs() {
  const data = await chrome.storage.local.get(STORAGE_KEY);
  return data[STORAGE_KEY] || [];
}

// Сохранение вкладок в хранилище
async function saveTabs(tabs) {
  await chrome.storage.local.set({ [STORAGE_KEY]: tabs });
}

// Создать новую вкладку из текущей активной
async function saveCurrentTab(name) {
  const current = await new Promise(resolve => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs[0]));
  });
  if (!current || current.url.startsWith('chrome://')) return;

  const tabs = await loadTabs();
  tabs.push({ name: name || 'Без имени', url: current.url, title: current.title, favIconUrl: current.favIconUrl });
  await saveTabs(tabs);
}

// Создать новую вкладку вручную (с названием и URL)
async function addTab(name, url) {
  const tabs = await loadTabs();
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

// Отправить сообщение всем открытым страницам расширения
function sendMessageToAll(msg) {
  chrome.tabs.query({ url: chrome.runtime.getURL('view.html') }, (tabs) => {
    for (const tab of tabs) {
      try { chrome.tabs.sendMessage(tab.id, msg); } catch (_) {}
    }
  });
}

// Открыть view с сохранёнными вкладками в текущей вкладке или новом окне
async function openView() {
  const savedTabs = await loadTabs();
  if (savedTabs.length === 0) return;

  chrome.tabs.create({ url: chrome.runtime.getURL('view.html') });
}

// Обработка сообщений от popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'open-view') {
    openView();
    return true;
  }
  if (msg.action === 'add-tab') {
    addTab(msg.name, msg.url).then(() => sendMessageToAll({ action: 'refresh' }));
    return true;
  }
  if (msg.action === 'get-tab-title') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      sendResponse({ tabTitle: tabs[0]?.title ?? '' });
    });
    return true; // разрешаем асинхронный ответ
  }
  if (msg.action === 'open') openTab(msg.index);
  else if (msg.action === 'delete') deleteTab(msg.index).then(() => sendMessageToAll({ action: 'refresh' }));
  return true; // разрешаем асинхронный ответ
});

// Слушатель закрытия браузера
chrome.runtime.onSuspend.addListener(async () => {
  // Хранилище само сохраняет при закрытии
});

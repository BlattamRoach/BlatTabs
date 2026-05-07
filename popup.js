const itemsEl = document.getElementById('items');
const saveBtn = document.getElementById('save-current-tab');
const tabNameInput = document.getElementById('tab-name');
const openViewBtn = document.getElementById('open-view');
const addTabBtn = document.getElementById('add-tab-btn');

async function loadItems() {
  const data = await chrome.storage.local.get('blattam-tabs');
  return data['blattam-tabs'] || [];
}

function render(items) {
  itemsEl.innerHTML = '';

  if (items.length === 0) {
    itemsEl.innerHTML = '<p style="color:#888;font-size:13px;">Нет сохранённых вкладок</p>';
    return;
  }

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const div = document.createElement('div');
    div.className = 'item';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'item-name';
    nameSpan.textContent = item.name + (item.title ? ` — ${item.title}` : '');

    const openBtn = document.createElement('button');
    openBtn.className = 'btn';
    openBtn.textContent = 'Открыть';
    openBtn.onclick = async (e) => {
      e.stopPropagation();
      await chrome.runtime.sendMessage({ action: 'open', index: i });
    };

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'btn btn-delete';
    deleteBtn.textContent = '×';
    deleteBtn.onclick = async (e) => {
      e.stopPropagation();
      await chrome.runtime.sendMessage({ action: 'delete', index: i });
    };

    div.appendChild(nameSpan);
    div.appendChild(openBtn);
    div.appendChild(deleteBtn);

    // Клик по вкладке — открыть
    div.onclick = async () => {
      await chrome.runtime.sendMessage({ action: 'open', index: i });
    };

    itemsEl.appendChild(div);
  }
}

// Слушаем сообщения от background
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'refresh') loadItems().then(render);
  return true; // разрешаем асинхронный ответ
});

// Загрузка при открытии
loadItems().then(render);

// Открыть view с сохранёнными вкладками
openViewBtn.onclick = async () => {
  await chrome.runtime.sendMessage({ action: 'open-view' });
};

// Добавить новую вкладку вручную
addTabBtn.onclick = async () => {
  const name = prompt('Название вкладки:') || 'Без имени';
  const url = prompt('URL (например, https://example.com):');

  if (!name && !url) return;

  chrome.runtime.sendMessage(
    { action: 'add-tab', name, url: url || '' },
    () => loadItems().then(render)
  );
};

// Сохранение текущей вкладки
saveBtn.onclick = async () => {
  const [response, title] = await Promise.all([
    new Promise((resolve) => chrome.runtime.sendMessage({ action: 'get-tab-title' }, resolve)),
    new Promise((resolve) => chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs[0]?.title ?? ''))),
  ]);

  const name = tabNameInput.value.trim() || title || 'Без имени';

  chrome.runtime.sendMessage(
    { action: 'save-current', name },
    () => loadItems().then(render)
  );

  if (response?.tabTitle) tabNameInput.value = response.tabTitle;
};


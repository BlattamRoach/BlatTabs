const itemsEl = document.getElementById('items');
const saveBtn = document.getElementById('save-current-tab');
const tabNameInput = document.getElementById('tab-name');

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

// Сохранение текущей вкладки — автоматически с названием и URL
saveBtn.onclick = async () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab || tab.url.startsWith('chrome://')) return;

    // Подставляем название из заголовка вкладки
    tabNameInput.value = tab.title || '';

    const name = tabNameInput.value.trim() || 'Без имени';
    chrome.runtime.sendMessage(
      { action: 'save-current', name },
      () => loadItems().then(render)
    );
  });
};

// Открыть view с сохранёнными вкладками
document.getElementById('open-view').onclick = async () => {
  await chrome.runtime.sendMessage({ action: 'open-view' });
};

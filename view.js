const tabsList = document.getElementById('tabs-list');
const emptyState = document.getElementById('empty-state');
const searchInput = document.getElementById('search');
const noResults = document.getElementById('no-results');

let allTabs = [];

chrome.storage.sync.get(['blattam-tabs'], (result) => {
  const arr = result['blattam-tabs'] || [];
  allTabs = arr;
  renderTabs();
});

function renderTabs(filter = '') {
  tabsList.innerHTML = '';

  if (allTabs.length === 0) {
    emptyState.style.display = 'block';
    noResults.style.display = 'none';
    return;
  }
  emptyState.style.display = 'none';

  let visibleCount = 0;

  allTabs.forEach((tab, index) => {
    if (filter && !tab.name.toLowerCase().includes(filter.toLowerCase()) && !(tab.title || '').toLowerCase().includes(filter.toLowerCase())) return;
    visibleCount++;

    const card = document.createElement('div');
    card.className = 'tab-card';

    // Header
    const header = document.createElement('div');
    header.className = 'tab-header';

    if (tab.favIconUrl) {
      const img = document.createElement('img');
      img.src = tab.favIconUrl;
      img.style.width = '16px';
      img.style.height = '16px';
      header.appendChild(img);
    }

    const nameEl = document.createElement('span');
    nameEl.className = 'tab-name';
    nameEl.textContent = tab.name;

    // Actions (only delete)
    const actions = document.createElement('div');
    actions.className = 'tab-actions';

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'icon-btn delete';
    deleteBtn.title = 'Удалить';
    deleteBtn.textContent = '✕';
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm(`Удалить вкладку "${tab.name}"?`)) {
        allTabs.splice(allTabs.indexOf(tab), 1);
        chrome.storage.sync.set({ 'blattam-tabs': allTabs });
        renderTabs(searchInput.value);
      }
    });

    actions.appendChild(deleteBtn);

    header.appendChild(nameEl);
    header.appendChild(actions);

    // URL
    const urlEl = document.createElement('span');
    urlEl.className = 'tab-url';
    urlEl.textContent = tab.url;

    card.appendChild(header);
    card.appendChild(urlEl);

    // Клик по карточке — открыть вкладку
    card.addEventListener('click', () => {
      chrome.tabs.create({ url: tab.url, active: true });
    });

    tabsList.appendChild(card);
  });

  noResults.style.display = visibleCount === 0 ? 'block' : 'none';
}

// Поиск по вкладкам
searchInput.addEventListener('input', (e) => {
  renderTabs(e.target.value);
});

// Автообновление при изменении хранилища (например, из popup)
chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === 'sync' && changes['blattam-tabs']) {
    allTabs = changes['blattam-tabs'].newValue || [];
    renderTabs(searchInput.value);
  }
});

// Экспорт в JSON
document.getElementById('export-btn').addEventListener('click', () => {
  const data = {
    'blattam-toby': true,
    version: chrome.runtime.getManifest().version,
    exported: new Date().toISOString(),
    tabs: allTabs
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const date = new Date().toISOString().slice(0, 10);
  a.download = `blattam-toby-backup-${date}.json`;
  a.click();
  URL.revokeObjectURL(url);
});

// Импорт из JSON
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

      // Валидация структуры
      if (!data.tabs || !Array.isArray(data.tabs)) {
        alert('Неверный формат файла: отсутствует массив tabs');
        return;
      }

      const importedTabs = data.tabs.filter(t => t.url && t.name);
      if (importedTabs.length === 0) {
        alert('В файле нет вкладок с URL');
        return;
      }

      // Считаем дубли по URL
      let newCount = 0;
      const duplicates = importedTabs.filter(t => allTabs.some(existing => existing.url === t.url)).length;
      newCount = importedTabs.length - duplicates;

      if (!confirm(`В файле ${importedTabs.length} вкладок.\nНовых: ${newCount}, дубликатов: ${duplicates}\n\nИмпортировать новые?`)) {
        return;
      }

      // Объединяем с детектом дублей
      importedTabs.forEach(t => {
        if (!allTabs.some(existing => existing.url === t.url)) {
          allTabs.push(t);
        }
      });

      chrome.storage.sync.set({ 'blattam-tabs': allTabs });
      renderTabs(searchInput.value);
    } catch (err) {
      alert('Ошибка чтения файла: невалидный JSON');
    }
  };
  reader.readAsText(file);

  // Сбрасываем input чтобы можно было загрузить тот же файл повторно
  e.target.value = '';
});

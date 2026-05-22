const tabsList = document.getElementById('tabs-list');
const emptyState = document.getElementById('empty-state');
const searchInput = document.getElementById('search');
const noResults = document.getElementById('no-results');

let allTabs = [];

chrome.storage.local.get(['blattam-tabs'], (result) => {
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

    // Actions
    const actions = document.createElement('div');
    actions.className = 'tab-actions';

    const openBtn = document.createElement('button');
    openBtn.className = 'icon-btn';
    openBtn.title = 'Открыть';
    openBtn.textContent = '↗';
    openBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      chrome.tabs.create({ url: tab.url, active: true });
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'icon-btn delete';
    deleteBtn.title = 'Удалить';
    deleteBtn.textContent = '✕';
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm(`Удалить вкладку "${tab.name}"?`)) {
        allTabs.splice(allTabs.indexOf(tab), 1);
        chrome.storage.local.set({ 'blattam-tabs': allTabs });
        renderTabs(searchInput.value);
      }
    });

    actions.appendChild(openBtn);
    actions.appendChild(deleteBtn);

    header.appendChild(nameEl);
    header.appendChild(actions);

    // URL
    const urlEl = document.createElement('span');
    urlEl.className = 'tab-url';
    urlEl.textContent = tab.url;

    // Open button
    const openAllBtn = document.createElement('button');
    openAllBtn.className = 'open-btn';
    openAllBtn.textContent = 'Открыть';
    openAllBtn.addEventListener('click', () => chrome.tabs.create({ url: tab.url, active: true }));

    card.appendChild(header);
    card.appendChild(urlEl);
    card.appendChild(openAllBtn);

    // Клик по карточке — открыть вкладку
    header.addEventListener('click', () => {
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
  if (areaName === 'local' && changes['blattam-tabs']) {
    allTabs = changes['blattam-tabs'].newValue || [];
    renderTabs(searchInput.value);
  }
});

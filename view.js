const tabsList = document.getElementById('tabs-list');
const emptyState = document.getElementById('empty-state');
const searchInput = document.getElementById('search');
const noResults = document.getElementById('no-results');
const foldersBar = document.getElementById('folders-bar');
const addFolderBtn = document.getElementById('add-folder-btn');

// Модалка
const folderModal = document.getElementById('folder-modal');
const modalTitle = document.getElementById('modal-title');
const folderNameInput = document.getElementById('folder-name-input');
const modalCancel = document.getElementById('modal-cancel');
const modalConfirm = document.getElementById('modal-confirm');

let allTabs = [];
let allFolders = [];
let activeFolderId = ''; // '' = "Все"
let modalCallback = null;

// === Загрузка данных ===

function loadData() {
  chrome.storage.sync.get(['blattam-tabs', 'blattam-folders'], (result) => {
    allTabs = result['blattam-tabs'] || [];
    allFolders = result['blattam-folders'] || [];
    renderFolders();
    renderTabs();
  });
}

// === Папки ===

function renderFolders() {
  // Удаляем старые чипы (кроме "Все" и "+ Папка")
  foldersBar.querySelectorAll('.folder-chip[data-folder-id]').forEach(el => el.remove());
  
  allFolders.forEach(folder => {
    const chip = document.createElement('button');
    chip.className = 'folder-chip' + (activeFolderId === folder.id ? ' active' : '');
    chip.dataset.folderId = folder.id;
    
    // Иконка папки + имя
    const icon = document.createElement('span');
    icon.textContent = '📁';
    chip.appendChild(icon);
    
    const name = document.createElement('span');
    name.className = 'chip-name';
    name.textContent = folder.name;
    chip.appendChild(name);
    
    // Действия (✏️ 🗑️)
    const actions = document.createElement('div');
    actions.className = 'chip-actions';
    
    const renameBtn = document.createElement('button');
    renameBtn.className = 'chip-icon-btn';
    renameBtn.textContent = '✎';
    renameBtn.title = 'Переименовать';
    renameBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      openRenameModal(folder.id, folder.name);
    });
    
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'chip-icon-btn';
    deleteBtn.textContent = '✕';
    deleteBtn.title = 'Удалить папку';
    deleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm(`Удалить папку "${folder.name}"? Вкладки переместятся в "Все".`)) {
        chrome.runtime.sendMessage({ action: 'delete-folder', id: folder.id });
      }
    });
    
    actions.appendChild(renameBtn);
    actions.appendChild(deleteBtn);
    chip.appendChild(actions);
    
    // Клик — фильтр по папке
    chip.addEventListener('click', () => {
      activeFolderId = folder.id;
      renderFolders(); // обновить active state
      renderTabs(searchInput.value);
    });
    
    foldersBar.insertBefore(chip, addFolderBtn);
  });
  
  // Обновляем "Все" чип
  const allChip = foldersBar.querySelector('.folder-chip[data-folder-id=""]');
  if (allChip) {
    allChip.className = 'folder-chip' + (activeFolderId === '' ? ' active' : '');
  }
}

// "+" — создать папку
addFolderBtn.addEventListener('click', () => openCreateModal());

// Модалка: создать папку
function openCreateModal() {
  modalTitle.textContent = 'Новая папка';
  folderNameInput.value = '';
  showFolderModal((name) => {
    chrome.runtime.sendMessage({ action: 'create-folder', name });
  });
}

// Модалка: переименовать папку
function openRenameModal(folderId, currentName) {
  modalTitle.textContent = 'Переименовать папку';
  folderNameInput.value = currentName;
  showFolderModal((name) => {
    if (name !== currentName) {
      chrome.runtime.sendMessage({ action: 'rename-folder', id: folderId, name });
    }
  });
}

function showFolderModal(onConfirm) {
  modalCallback = onConfirm;
  folderModal.classList.add('open');
  setTimeout(() => folderNameInput.focus(), 50);
}

modalCancel.addEventListener('click', closeFolderModal);
folderModal.addEventListener('click', (e) => {
  if (e.target === folderModal) closeFolderModal();
});

function closeFolderModal() {
  folderModal.classList.remove('open');
  modalCallback = null;
}

modalConfirm.addEventListener('click', () => {
  const name = folderNameInput.value.trim();
  if (!name) return;
  if (modalCallback) modalCallback(name);
  closeFolderModal();
});

folderNameInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') modalConfirm.click();
  if (e.key === 'Escape') modalCancel.click();
});

// "Все" чип — клик сбрасывает фильтр
foldersBar.querySelector('.folder-chip[data-folder-id=""]').addEventListener('click', () => {
  activeFolderId = '';
  renderFolders();
  renderTabs(searchInput.value);
});

// === Карточки вкладок ===

function renderTabs(filter = '') {
  tabsList.innerHTML = '';
  
  // Фильтр по папке
  let filtered = allTabs;
  if (activeFolderId !== '') {
    filtered = allTabs.filter(t => t.folderId === activeFolderId);
  }
  
  if (allTabs.length === 0) {
    emptyState.style.display = 'block';
    noResults.style.display = 'none';
    return;
  }
  emptyState.style.display = 'none';
  
  let visibleCount = 0;
  
  filtered.forEach((tab) => {
    // Поиск по имени/title/URL
    if (filter && !matchFilter(tab, filter)) return;
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
      img.onerror = () => img.remove();
      header.appendChild(img);
    }
    
    const nameEl = document.createElement('span');
    nameEl.className = 'tab-name';
    nameEl.textContent = tab.name;
    
    // Actions: переместить в папку + удалить
    const actions = document.createElement('div');
    actions.className = 'tab-actions';
    
    // Кнопка "переместить" (📁) — дропдаун папок
    const folderBtn = document.createElement('button');
    folderBtn.className = 'folder-select-btn';
    folderBtn.textContent = '📋';
    folderBtn.title = 'Переместить в папку';
    
    const dropdown = document.createElement('div');
    dropdown.className = 'folder-dropdown';
    
    // "Все" (null)
    const allItem = document.createElement('div');
    allItem.className = 'folder-dd-item all-folder';
    allItem.textContent = '→ Все';
    allItem.addEventListener('click', (e) => {
      e.stopPropagation();
      moveTab(tab, null);
      dropdown.classList.remove('open');
    });
    dropdown.appendChild(allItem);
    
    // Папки
    allFolders.forEach(folder => {
      const item = document.createElement('div');
      item.className = 'folder-dd-item';
      item.textContent = `→ ${folder.name}`;
      if (tab.folderId === folder.id) item.style.fontWeight = 'bold';
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        moveTab(tab, folder.id);
        dropdown.classList.remove('open');
      });
      dropdown.appendChild(item);
    });
    
    folderBtn.appendChild(dropdown);
    folderBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      document.querySelectorAll('.folder-dropdown.open').forEach(dd => dd.classList.remove('open'));
      dropdown.classList.toggle('open');
    });
    
    actions.appendChild(folderBtn);
    
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

function matchFilter(tab, filter) {
  const f = filter.toLowerCase();
  return (tab.name || '').toLowerCase().includes(f) || 
         (tab.title || '').toLowerCase().includes(f) || 
         (tab.url || '').toLowerCase().includes(f);
}

// Переместить вкладку в папку
function moveTab(tab, folderId) {
  const realIndex = allTabs.indexOf(tab);
  if (realIndex === -1) return;
  chrome.runtime.sendMessage({ action: 'move-tab', index: realIndex, folderId });
}

// Поиск
searchInput.addEventListener('input', (e) => {
  renderTabs(e.target.value);
});

// Закрыть дропдауны при клике вне их
document.addEventListener('click', (e) => {
  if (!e.target.closest('.folder-select-btn')) {
    document.querySelectorAll('.folder-dropdown.open').forEach(dd => dd.classList.remove('open'));
  }
});

// === Автообновление ===

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== 'sync') return;
  
  if (changes['blattam-tabs']) {
    allTabs = changes['blattam-tabs'].newValue || [];
    renderTabs(searchInput.value);
  }
  if (changes['blattam-folders']) {
    allFolders = changes['blattam-folders'].newValue || [];
    renderFolders();
  }
});

// === Экспорт / Импорт (с папками) ===

document.getElementById('export-btn').addEventListener('click', () => {
  const data = {
    'blattam-toby': true,
    version: chrome.runtime.getManifest().version,
    exported: new Date().toISOString(),
    folders: allFolders,
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
      
      if (!data.tabs || !Array.isArray(data.tabs)) {
        alert('Неверный формат файла: отсутствует массив tabs');
        return;
      }
      
      // Импорт папок
      let importedFoldersCount = 0;
      if (data.folders && Array.isArray(data.folders)) {
        const existingNames = allFolders.map(f => f.name.toLowerCase());
        data.folders.forEach(folder => {
          if (!existingNames.includes(folder.name.toLowerCase())) {
            allFolders.push({ id: folder.id, name: folder.name });
            importedFoldersCount++;
          }
        });
      }
      
      const importedTabs = data.tabs.filter(t => t.url && t.name);
      let newCount = 0;
      const duplicates = importedTabs.filter(t => allTabs.some(existing => existing.url === t.url)).length;
      newCount = importedTabs.length - duplicates;
      
      if (!confirm(`В файле ${importedFoldersCount + (data.folders ? 1 : 0)} папок (+${importedFoldersCount} новых), ${importedTabs.length} вкладок.\nНовых: ${newCount}, дубликатов: ${duplicates}\n\nИмпортировать?`)) {
        return;
      }
      
      importedTabs.forEach(t => {
        if (!allTabs.some(existing => existing.url === t.url)) {
          // Проверяем что folderId существует
          if (t.folderId && !allFolders.some(f => f.id === t.folderId)) {
            t.folderId = null;
          }
          allTabs.push(t);
        }
      });
      
      chrome.storage.sync.set({ 
        'blattam-tabs': allTabs,
        'blattam-folders': allFolders
      });
    } catch (err) {
      alert('Ошибка чтения файла: невалидный JSON');
    }
  };
  reader.readAsText(file);
  e.target.value = '';
});

// === Старт ===
loadData();

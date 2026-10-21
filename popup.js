const saveBtn = document.getElementById('save-current-tab');
const folderSelect = document.getElementById('folder-select');
const savedMsg = document.getElementById('saved-msg');
const addFolderBtn = document.getElementById('popup-add-folder');

// Модалка
const folderModal = document.getElementById('folder-modal');
const folderNameInput = document.getElementById('folder-name-input');
const modalCancel = document.getElementById('modal-cancel');
const modalConfirm = document.getElementById('modal-confirm');

let folders = [];
let lastFolderId = ''; // Помним последнюю выбранную папку

// Загрузка списка папок
function loadFolders() {
  chrome.storage.sync.get(['blattam-folders'], (result) => {
    folders = result['blattam-folders'] || [];
    renderFolders();
  });
}

function renderFolders() {
  // Сохраняем текущий выбор
  const currentVal = folderSelect.value;
  
  folderSelect.innerHTML = '<option value="">Все (без папки)</option>';
  
  // Иерархия: вложенные папки — с «↳»
  const appendFolderOption = (folder, depth) => {
    const opt = document.createElement('option');
    opt.value = folder.id;
    opt.textContent = (depth > 0 ? '↳ ' : '') + folder.name;
    folderSelect.appendChild(opt);
    folders.filter(f => f.parentId === folder.id).forEach(child => appendFolderOption(child, depth + 1));
  };
  folders.filter(f => f.parentId == null).forEach(f => appendFolderOption(f, 0));
  
  // Восстанавливаем выбор или используем последнюю
  if (folders.some(f => f.id === currentVal)) {
    folderSelect.value = currentVal;
  } else if (lastFolderId) {
    folderSelect.value = lastFolderId;
  }
}

// Сохранение вкладки
saveBtn.onclick = () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab || tab.url.startsWith('chrome://')) return;

    const folderId = folderSelect.value || null;
    lastFolderId = folderId || '';

    chrome.runtime.sendMessage({ 
      action: 'save-current', 
      name: tab.title || '',
      folderId 
    });

    savedMsg.classList.add('show');
    setTimeout(() => savedMsg.classList.remove('show'), 2000);
  });
};

// Новая папка из popup
addFolderBtn.addEventListener('click', () => {
  folderNameInput.value = '';
  folderModal.classList.add('open');
  setTimeout(() => folderNameInput.focus(), 50);
});

modalCancel.addEventListener('click', closeModal);
folderModal.addEventListener('click', (e) => {
  if (e.target === folderModal) closeModal();
});

function closeModal() {
  folderModal.classList.remove('open');
}

modalConfirm.addEventListener('click', () => {
  const name = folderNameInput.value.trim();
  if (!name) return;
  
  chrome.runtime.sendMessage({ action: 'create-folder', name }, (result) => {
    // Если папка создана (или была дубль), обновляем список
    loadFolders();
    if (result) {
      folderSelect.value = result.id;
      lastFolderId = result.id;
    }
  });
  
  closeModal();
});

folderNameInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') modalConfirm.click();
  if (e.key === 'Escape') modalCancel.click();
});

// Автообновление папок при изменении из view
chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === 'sync' && changes['blattam-folders']) {
    folders = changes['blattam-folders'].newValue || [];
    renderFolders();
  }
});

// Старт
loadFolders();

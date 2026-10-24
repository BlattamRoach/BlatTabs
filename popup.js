const saveBtn = document.getElementById('save-current-tab');
const spaceSelect = document.getElementById('space-select');
const savedMsg = document.getElementById('saved-msg');
const addSpaceBtn = document.getElementById('popup-add-space');

// Модалка
const spaceModal = document.getElementById('space-modal');
const spaceNameInput = document.getElementById('space-name-input');
const modalCancel = document.getElementById('modal-cancel');
const modalConfirm = document.getElementById('modal-confirm');

let spaces = [];
let lastSpaceId = ''; // Помним последнее выбранное пространство

// Загрузка списка пространств + запомненное blattam-last-space
function loadSpaces() {
  chrome.storage.sync.get(['blattam-spaces', 'blattam-last-space'], (result) => {
    spaces = Array.isArray(result['blattam-spaces']) ? result['blattam-spaces'] : [];
    lastSpaceId = result['blattam-last-space'] || '';
    renderSpaces();
  });
}

function renderSpaces() {
  // Сохраняем текущий выбор
  const currentVal = spaceSelect.value;

  spaceSelect.innerHTML = '';
  spaces.forEach(sp => {
    const opt = document.createElement('option');
    opt.value = sp.id;
    opt.textContent = sp.name;
    spaceSelect.appendChild(opt);
  });

  // Восстанавливаем выбор: текущий → blattam-last-space → первое пространство
  if (spaces.some(sp => sp.id === currentVal)) {
    spaceSelect.value = currentVal;
  } else if (spaces.some(sp => sp.id === lastSpaceId)) {
    spaceSelect.value = lastSpaceId;
  } else if (spaces.length > 0) {
    spaceSelect.value = spaces[0].id;
  }
}

// Сохранение вкладки
saveBtn.onclick = () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab || tab.url.startsWith('chrome://')) return;

    const spaceId = spaceSelect.value || null;
    lastSpaceId = spaceId || '';
    // Popup обновляет blattam-last-space при сохранении
    if (spaceId) chrome.storage.sync.set({ 'blattam-last-space': spaceId });

    chrome.runtime.sendMessage({
      action: 'save-current',
      name: tab.title || '',
      spaceId
    });

    savedMsg.classList.add('show');
    setTimeout(() => savedMsg.classList.remove('show'), 2000);
  });
};

// Новое пространство из popup
addSpaceBtn.addEventListener('click', () => {
  spaceNameInput.value = '';
  spaceModal.classList.add('open');
  setTimeout(() => spaceNameInput.focus(), 50);
});

modalCancel.addEventListener('click', closeModal);
spaceModal.addEventListener('click', (e) => {
  if (e.target === spaceModal) closeModal();
});

function closeModal() {
  spaceModal.classList.remove('open');
}

modalConfirm.addEventListener('click', () => {
  const name = spaceNameInput.value.trim();
  if (!name) return;

  chrome.runtime.sendMessage({ action: 'create-space', name }, (result) => {
    // Если пространство создано, делаем его выбранным
    if (result && result.id) {
      lastSpaceId = result.id;
    }
    renderSpaces();
    // renderSpaces() восстанавливает прежний выбор — переопределяем его
    // только если новое пространство реально в списке
    if (result && result.id && spaces.some(sp => sp.id === result.id)) {
      spaceSelect.value = result.id;
    }
  });

  closeModal();
});

spaceNameInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') modalConfirm.click();
  if (e.key === 'Escape') modalCancel.click();
});

// Автообновление списков при изменении из view
chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== 'sync') return;
  if (changes['blattam-spaces']) {
    spaces = changes['blattam-spaces'].newValue || [];
    renderSpaces();
  }
  if (changes['blattam-last-space'] && changes['blattam-last-space'].newValue) {
    lastSpaceId = changes['blattam-last-space'].newValue;
    renderSpaces();
    // Внешняя смена blattam-last-space (из view) — следим за ней,
    // даже если в popup уже был выбор
    if (spaces.some(sp => sp.id === lastSpaceId)) {
      spaceSelect.value = lastSpaceId;
    }
  }
});

// Старт
loadSpaces();

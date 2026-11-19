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

// === GitHub: аккаунт и синхронизация (панель popup) ===
const githubConnectBtn = document.getElementById('github-connect');
const githubSyncBtn = document.getElementById('github-sync');
const githubClearBtn = document.getElementById('github-clear');
const githubStatusLabel = document.getElementById('github-status');

// Статус: есть токен? → спросить background состояние синка
// (ahead/behind/synced/disconnected/unknown)
function updateGitHubUI() {
  chrome.storage.local.get('github-token', (r) => {
    const hasToken = !!r['github-token'];
    githubConnectBtn.textContent = hasToken ? 'Disconnect GitHub' : 'Connect GitHub';
    if (!hasToken) {
      githubStatusLabel.textContent = 'GitHub: Disconnected';
      return;
    }
    chrome.runtime.sendMessage({ action: 'check-sync-status' }, (status) => {
      const labels = {
        ahead: '⬆️ Local is ahead',
        behind: '⬇️ Remote is ahead',
        synced: '✅ Synced',
        disconnected: 'GitHub: Disconnected',
        unknown: 'GitHub: Unknown status'
      };
      githubStatusLabel.textContent = labels[status] || labels.unknown;
    });
  });
}

githubConnectBtn.onclick = () => {
  chrome.storage.local.get('github-token', (r) => {
    if (r['github-token']) {
      // Отключение: сброс токена в background (removeCachedAuthToken + local)
      chrome.runtime.sendMessage({ action: 'disconnect-github' }, () => updateGitHubUI());
    } else {
      // Подключение: OAuth web-flow СТРОГО со страницы (живой жест)
      const m = chrome.runtime.getManifest();
      const redirectUri = chrome.runtime.getURL('oauth-callback.html');
      const authUrl = 'https://github.com/login/oauth/authorize'
        + '?client_id=' + encodeURIComponent(m.oauth2.client_id)
        + '&scope=' + encodeURIComponent('repo')
        + '&redirect_uri=' + encodeURIComponent(redirectUri);
      chrome.identity.launchWebAuthFlow({ url: authUrl, interactive: true }, (resultUrl) => {
        if (chrome.runtime.lastError) {
          // Auth-окно не открылось — Device Flow (код + обычная вкладка)
          githubStatusLabel.textContent = 'GitHub: Device flow…';
          chrome.runtime.sendMessage({ action: 'device-flow-start' }, (res) => {
            if (!res) {
              chrome.storage.local.get('github-auth-error', (r) => {
                githubStatusLabel.textContent = 'GitHub: ' + (r['github-auth-error'] || 'Connection error');
              });
              return;
            }
            chrome.tabs.create({ url: res.verification_uri, active: true });
            githubStatusLabel.textContent = 'GitHub: введите код ' + res.user_code;
            setTimeout(updateGitHubUI, 300000);
          });
          return;
        }
        if (!resultUrl) return; // окно закрыто/отменено
        const params = new URLSearchParams(new URL(resultUrl).search);
        const code = params.get('code');
        const error = params.get('error');
        if (!code) {
          githubStatusLabel.textContent = error ? 'GitHub: ' + error : 'GitHub: Auth failed';
          return;
        }
        chrome.runtime.sendMessage({ action: 'oauth-exchange', code, redirectUri }, (token) => {
          if (token) {
            chrome.runtime.sendMessage({ action: 'verify-github' }, (res) => {
              if (res && res.success) {
                githubStatusLabel.textContent = 'GitHub: Connected (' + res.user.login + ')';
              } else {
                githubStatusLabel.textContent = 'GitHub: Auth failed';
              }
              updateGitHubUI();
            });
          } else {
            chrome.storage.local.get('github-auth-error', (r) => {
              githubStatusLabel.textContent = 'GitHub: ' + (r['github-auth-error'] || 'Connection error');
            });
          }
        });
      });
    }
  });
};

githubSyncBtn.onclick = () => {
  githubStatusLabel.textContent = '☁️ Syncing...';
  chrome.runtime.sendMessage({ action: 'sync-now' }, (res) => {
    let text = '✅ Synced!';
    if (res) {
      const parts = [];
      if (res.pulled) parts.push('Pull');
      if (res.pushed) parts.push('Push');
      if (parts.length) text = '✅ Synced (' + parts.join(' & ') + ')';
    }
    githubStatusLabel.textContent = text;
    setTimeout(updateGitHubUI, 3000);
  });
};

githubClearBtn.onclick = () => {
  if (!confirm('Reset your cloud data? This clears all tabs in your Gist.')) return;
  chrome.runtime.sendMessage({ action: 'clear-cloud' }, (res) => {
    if (res) githubStatusLabel.textContent = '🧹 Cloud cleared!';
    setTimeout(updateGitHubUI, 3000);
  });
};

// Старт
loadLang().then(function () { loadSpaces(); updateGitHubUI(); });

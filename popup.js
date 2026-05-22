// Сохранить текущую вкладку
document.getElementById('save-current-tab').onclick = async () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab || tab.url.startsWith('chrome://')) return;

    chrome.runtime.sendMessage(
      { action: 'save-current', name: tab.title || '' }
    );

    // Показать подтверждение
    const msg = document.getElementById('saved-msg');
    msg.classList.add('show');
    setTimeout(() => msg.classList.remove('show'), 2000);
  });
};

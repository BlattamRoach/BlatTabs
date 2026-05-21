// Сохранить текущую вкладку
document.getElementById('save-current-tab').onclick = async () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab || tab.url.startsWith('chrome://')) return;

    chrome.runtime.sendMessage(
      { action: 'save-current', name: tab.title || '' },
      () => {}
    );
  });
};

// Открыть view (плюсик / Ctrl+T)
document.getElementById('open-view').onclick = async () => {
  await chrome.runtime.sendMessage({ action: 'open-view' });
};

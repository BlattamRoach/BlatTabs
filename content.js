// Content Script для перехвата Ctrl+T
document.addEventListener('keydown', (e) => {
  // Проверяем Ctrl+T (не на input/textarea, чтобы не мешать вводу)
  const tag = e.target.tagName;
  if ((tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') && !e.ctrlKey) return;

  if (e.key === 't' && e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
    // Не перехватывать если это popup или view расширения
    const iframe = document.querySelector('iframe[src*="chrome-extension"]');
    if (iframe) return;

    e.preventDefault();
    chrome.runtime.sendMessage({ action: 'open-view' });
  }
});

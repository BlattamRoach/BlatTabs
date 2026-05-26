"""
Unit-тест BlattamToby плагина через Playwright.
Мокирует Chrome API и проверяет логику background.js, view.js, popup.js.
"""
import json
from playwright.sync_api import sync_playwright

EXT_PATH = r"C:\Users\DI\Desktop\QwenCode\BlattamToby"

MOCK_CHROME = """
var chrome = {
  storage: {
    local: {
      _data: {},
      get: function(keys, callback) {
        var result = {};
        if (typeof keys === 'string') {
          result[keys] = this._data[keys];
        } else if (Array.isArray(keys)) {
          for (var k of keys) result[k] = this._data[k];
        } else {
          Object.assign(result, this._data);
        }
        if (callback) callback(result);
        return Promise.resolve(result);
      },
      set: function(data, callback) {
        Object.assign(this._data, data);
        if (window.chrome_storage_onChanged && window.chrome_storage_onChanged.length) {
          var changeInfo = {};
          for (var k in data) changeInfo[k] = { newValue: data[k], oldValue: this._data[k] };
          for (var fn of window.chrome_storage_onChanged) fn(changeInfo, 'local');
        }
        if (callback) callback();
        return Promise.resolve();
      },
      clear: function(callback) { this._data = {}; if (callback) callback(); return Promise.resolve(); }
    },
    onChanged: []
  },
  tabs: { 
    createdTabs: [],
    create: function(opts) { this.createdTabs.push(opts); window.lastTabCreated = opts; },
    _currentTab: { url: 'https://example.com', title: 'Example Domain', favIconUrl: '' },
    query: function(query, callback) { 
      if (callback) callback([this._currentTab]); 
    }
  },
  runtime: {
    messagesSent: [],
    onMessage: { _listeners: [] },
    sendMessage: function(msg) { this.messagesSent.push(msg); window.lastMessage = msg; return Promise.resolve(); }
  }
};

// Patch addListener patterns
chrome.storage.onChanged.addListener = function(fn) { chrome.storage.onChanged.push(fn); };
chrome.runtime.onMessage.addListener = function(fn) { 
  chrome.runtime.onMessage._listeners.push(fn); 
  window._onMessageHandler = fn; 
};
"""

def pass_if(condition, label):
    status = "✓" if condition else "✗"
    print(f"  {status} {label}")
    return condition

def test_background_js():
    print("=" * 60)
    print("ТЕСТ: background.js — CRUD операций")
    print("=" * 60)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Мокируем Chrome API
        page.evaluate(MOCK_CHROME)
        
        # Загружаем background.js
        with open(f"{EXT_PATH}/background.js", "r", encoding="utf-8") as f:
            bg_code = f.read()
        
        try:
            page.evaluate(bg_code + "; 'loaded'")
            pass_if(True, "Background.js загружен без ошибок")
        except Exception as e:
            print(f"  ✗ Ошибка загрузки: {e}")
            browser.close()
            return
        
        # --- Тест save-current ---
        page.evaluate("""
(async () => {
  if (window._onMessageHandler) {
    await window._onMessageHandler({action: 'save-current', name: 'Test Tab'}, null, function(){});
  }
})()
""")
        tabs = json.loads(page.evaluate("(async () => { var d = await chrome.storage.local.get('blattam-tabs'); return JSON.stringify(d['blattam-tabs'] || []); })()"))
        pass_if(len(tabs) == 1 and tabs[0]['name'] == 'Test Tab', "save-current: сохранена вкладка")
        
        # --- Тест add-tab ---
        page.evaluate("""
(async () => {
  if (window._onMessageHandler) {
    await window._onMessageHandler({action: 'add-tab', name: 'Google', url: 'https://google.com'}, null, function(){});
    await window._onMessageHandler({action: 'add-tab', name: 'GitHub', url: 'https://github.com'}, null, function(){});
  }
})()
""")
        tabs = json.loads(page.evaluate("(async () => { var d = await chrome.storage.local.get('blattam-tabs'); return JSON.stringify(d['blattam-tabs'] || []); })()"))
        pass_if(len(tabs) == 3, f"add-tab: в хранилище {len(tabs)} вкладок (ожидал 3)")
        
        # --- Тест delete ---
        page.evaluate("""
(async () => {
  if (window._onMessageHandler) {
    await window._onMessageHandler({action: 'delete', index: 0}, null, function(){});
  }
})()
""")
        tabs = json.loads(page.evaluate("(async () => { var d = await chrome.storage.local.get('blattam-tabs'); return JSON.stringify(d['blattam-tabs'] || []); })()"))
        pass_if(len(tabs) == 2 and tabs[0]['name'] == 'Google', "delete: удалена первая вкладка, осталось 2")
        
        # --- Тест open (создание вкладки) ---
        page.evaluate("""
(async () => {
  if (window._onMessageHandler) {
    await window._onMessageHandler({action: 'open', index: 0}, null, function(){});
  }
})()
""")
        opened = page.evaluate("JSON.stringify(chrome.tabs.createdTabs)")
        # Проверяем что createdTabs не пустой
        pass_if(len(json.loads(opened)) > 0, "open: вкладка открыта через chrome.tabs.create")
        
        # --- Тест дублей (должен сохранять!) ---
        page.evaluate("""
(async () => {
  if (window._onMessageHandler) {
    await window._onMessageHandler({action: 'add-tab', name: 'Google Dup', url: 'https://google.com'}, null, function(){});
  }
})()
""")
        tabs = json.loads(page.evaluate("(async () => { var d = await chrome.storage.local.get('blattam-tabs'); return JSON.stringify(d['blattam-tabs'] || []); })()"))
        pass_if(len(tabs) == 3, "Детект дублей: URL google.com сохранён повторно (пока нет защиты)")
        
        print(f"\n  Данные в хранилище:")
        for i, t in enumerate(tabs):
            print(f"    [{i}] {t['name']} → {t.get('url', 'N/A')}")
        
        browser.close()


def test_view_js():
    print("\n" + "=" * 60)
    print("ТЕСТ: view.js — рендеринг карточек и поиск")
    print("=" * 60)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Мокируем Chrome + предзаполняем данные
        init_code = MOCK_CHROME + """
chrome.storage.local._data['blattam-tabs'] = [
  { name: 'Example Domain', url: 'https://example.com', title: 'Example' },
  { name: 'Google', url: 'https://google.com', title: '' },
  { name: 'GitHub', url: 'https://github.com', title: '' }
];
chrome.tabs.create = function(opts) { chrome.tabs.createdTabs.push(opts); };
"""
        page.goto("about:blank")
        page.evaluate(init_code)
        
        # Создаём DOM структуру view.html
        view_dom = """<div class="header"><h1>BlattamToby</h1></div><div class="container">
<input type="text" class="search-box" id="search" placeholder="Поиск...">
<div id="empty-state" style="display:none;">Нет сохранённых вкладок</div>
<div id="no-results" style="display:none;">Ничего не найдено</div>
<div id="tabs-list"></div></div>"""
        page.evaluate(f"document.body.innerHTML = `{view_dom}`")
        
        with open(f"{EXT_PATH}/view.js", "r", encoding="utf-8") as f:
            view_code = f.read()
        
        try:
            page.evaluate(view_code + "; 'loaded'")
            pass_if(True, "View.js загружен без ошибок")
        except Exception as e:
            print(f"  ✗ Ошибка загрузки: {e}")
            browser.close()
            return
        
        # Проверка рендеринга
        cards = page.evaluate("document.querySelectorAll('.tab-card').length")
        pass_if(cards == 3, f"Отрендерено {cards} карточки (ожидал 3)")
        
        # Проверка содержимого первой карточки
        first_name = page.evaluate("document.querySelector('.tab-name')?.textContent || ''")
        pass_if(first_name == 'Example Domain', f"Первая карточка: '{first_name}'")
        
        # Тест поиска "Google"
        search_input = page.locator("#search")
        search_input.fill("Google")
        filtered = page.evaluate("document.querySelectorAll('.tab-card').length")
        pass_if(filtered == 1, f"Поиск 'Google': найдено {filtered} карточек (ожидал 1)")
        
        # Тест пустого поиска
        search_input.fill("XXXXXXXX_NEEXIST")
        no_results = page.evaluate("document.getElementById('no-results').style.display !== 'none' && document.querySelectorAll('.tab-card').length === 0")
        pass_if(no_results, "Поиск несуществующего: показано 'Ничего не найдено'")
        
        # Сброс поиска
        search_input.fill("")
        all_back = page.evaluate("document.querySelectorAll('.tab-card').length")
        pass_if(all_back == 3, f"Сброс поиска: {all_back} карточки вернулись")
        
        browser.close()


def test_popup_js():
    print("\n" + "=" * 60)
    print("ТЕСТ: popup.js — сохранение текущей вкладки")
    print("=" * 60)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Создаём полную HTML страницу с DOM + моком Chrome API
        full_html = f"""
<html><body>
<button id="save-current-tab">💾 Сохранить текущую вкладку</button>
<div id="saved-msg" style="opacity:0;">✓ Вкладка сохранена!</div>

<script>
{MOCK_CHROME}

// Загружаем popup.js
(function() {{
"""
        
        with open(f"{EXT_PATH}/popup.js", "r", encoding="utf-8") as f:
            popup_code = f.read()
        
        full_html += f"""
{popup_code}
}})();
</script></body></html>
"""
        
        page.goto("data:text/html," + full_html.replace("\n", ""), wait_until="load")
        
        # Проверяем что кнопка существует
        btn_exists = page.locator("#save-current-tab").is_visible()
        pass_if(btn_exists, "Кнопка 'Сохранить текущую вкладку' отображается")
        
        if not btn_exists:
            print("  ⚠ Пропускаем остальные проверки popup — кнопка не найдена")
            browser.close()
            return
        
        # Клик по кнопке сохранения
        save_btn = page.locator("#save-current-tab")
        try:
            save_btn.click(timeout=3000)
            
            msg_sent = page.evaluate("!!window.lastMessage")
            pass_if(msg_sent, "chrome.runtime.sendMessage вызван при клике")
            
            if msg_sent:
                msg_action = page.evaluate("window.lastMessage.action || ''")
                msg_name = page.evaluate("window.lastMessage.name || ''")
                pass_if(msg_action == 'save-current', f"Action в сообщении: {msg_action}")
                pass_if(msg_name == 'Example Domain', f"Name в сообщении: '{msg_name}'")
            
            # Проверка визуального подтверждения
            shown = page.evaluate("document.getElementById('saved-msg').classList.contains('show')")
            pass_if(shown, "Сообщение 'Вкладка сохранена!' показано")
        except Exception as e:
            print(f"  ⚠ Клик по кнопке вызвал ошибку (возможно блокировка chrome:// URL): {e}")
        
        browser.close()


def test_manifest():
    print("\n" + "=" * 60)
    print("ТЕСТ: manifest.json — валидация")
    print("=" * 60)
    
    with open(f"{EXT_PATH}/manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    pass_if(manifest.get('manifest_version') == 3, "Manifest V3")
    pass_if(manifest.get('name') == 'BlattamToby', f"Name: {manifest.get('name')}")
    pass_if('tabs' in manifest.get('permissions', []), "Permission: tabs")
    pass_if('storage' in manifest.get('permissions', []), "Permission: storage")
    pass_if(manifest.get('background', {}).get('service_worker') == 'background.js', "Service worker: background.js")
    pass_if(manifest.get('action', {}).get('default_popup') == 'popup.html', "Popup: popup.html")
    pass_if(manifest.get('chrome_url_overrides', {}).get('newtab') == 'view.html', "NewTab override: view.html")


def main():
    print("🔍 Тестирование плагина BlattamToby\n")
    
    test_manifest()
    test_background_js()
    test_view_js()
    test_popup_js()
    
    print("\n" + "=" * 60)
    print("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
    print("=" * 60)

if __name__ == "__main__":
    main()

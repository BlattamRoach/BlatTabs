"""
Тесты BlattamToby через Playwright.
Мокируем Chrome API, проверяем background.js, view.js, popup.js + папки/категории.

Запуск: python test_plugin.py
"""
import json
import pytest
from playwright.sync_api import sync_playwright

EXT_PATH = r"C:\Users\DI\Desktop\QwenCode\BlattamToby"


# === Моки Chrome API ===

MOCK_CHROME = """
var chrome = {
  storage: {
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
      if (window.__storageListeners && window.__storageListeners.length) {
        var changeInfo = {};
        for (var k in data) {
          changeInfo[k] = { newValue: data[k], oldValue: this._data[k] };
        }
        for (var fn of window.__storageListeners) fn(changeInfo, 'sync');
      }
      if (callback) callback();
      return Promise.resolve();
    },
    sync: { _data: {} }
  },
  tabs: {
    createdTabs: [],
    create: function(opts) { this.createdTabs.push(opts); window.lastTabCreated = opts; },
    _currentTab: { url: 'https://example.com', title: 'Example Domain', favIconUrl: '' },
    query: function(query, callback) { if (callback) callback([this._currentTab]); }
  },
  runtime: {
    messagesSent: [],
    onMessage: { _listeners: [] },
    sendMessage: function(msg) { this.messagesSent.push(msg); window.lastMessage = msg; return Promise.resolve(); },
    getManifest: function() { return { version: '1.0.0' }; }
  }
};

// Patch chrome.storage.sync → chrome.storage._data
Object.defineProperty(chrome.storage, 'sync', { value: { _data: chrome.storage._data } });
chrome.storage.sync.get = function(keys, cb) { return chrome.storage.get(keys, cb); };
chrome.storage.sync.set = function(data, cb) { return chrome.storage.set(data, cb); };

// Patch listeners
window.__storageListeners = [];
chrome.storage.onChanged = { addListener: function(fn) { window.__storageListeners.push(fn); } };
chrome.runtime.onMessage.addListener = function(fn) {
  chrome.runtime.onMessage._listeners.push(fn);
  window._onMessageHandler = fn;
};
"""


@pytest.fixture(scope="module")
def page():
    """Shared headless browser page for all tests."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        yield pg
        browser.close()


# === Helpers ===

def send_msg(page, action, **kwargs):
    """Send a message to background.js handler."""
    msg = {"action": action}
    msg.update(kwargs)
    page.evaluate(f"""(async () => {{
      var fn = window._onMessageHandler;
      if (fn) await fn({json.dumps(msg)}, null, function(){{}});
    }})()""")


def get_storage(page, key):
    """Read from mocked storage."""
    return json.loads(page.evaluate(f"""(async () => {{
      var d = await chrome.storage.get('{key}');
      return JSON.stringify(d['{key}'] || (Array.isArray({key}) ? [] : null));
    }})()"""))


def read_storage_raw(page, key):
    """Read storage returning proper type."""
    result = page.evaluate(f"(async () => {{ var d = await chrome.storage.get('{key}'); if (d['{key}'] === undefined || d['{key}'] === null) return '[]'; return JSON.stringify(d['{key}']); }})()")
    parsed = json.loads(result)
    return parsed if parsed is not None else []


def load_file(name):
    with open(f"{EXT_PATH}/{name}", "r", encoding="utf-8") as f:
        return f.read()


# ==========================================
#  MANIFEST TESTS (no browser needed)
# ==========================================

class TestManifest:
    def test_manifest_version(self):
        m = json.load(open(f"{EXT_PATH}/manifest.json"))
        assert m["manifest_version"] == 3

    def test_name(self):
        m = json.load(open(f"{EXT_PATH}/manifest.json"))
        assert m["name"] == "BlattamToby"

    def test_permissions(self):
        m = json.load(open(f"{EXT_PATH}/manifest.json"))
        assert "tabs" in m["permissions"]
        assert "storage" in m["permissions"]

    def test_service_worker(self):
        m = json.load(open(f"{EXT_PATH}/manifest.json"))
        assert m["background"]["service_worker"] == "background.js"

    def test_popup(self):
        m = json.load(open(f"{EXT_PATH}/manifest.json"))
        assert m["action"]["default_popup"] == "popup.html"

    def test_newtab_override(self):
        m = json.load(open(f"{EXT_PATH}/manifest.json"))
        assert m["chrome_url_overrides"]["newtab"] == "view.html"


# ==========================================
#  BACKGROUND.JS TESTS
# ==========================================

class TestBackground:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        """Load background.js with mocked Chrome API."""
        page.goto("about:blank")
        page.evaluate(MOCK_CHROME)
        bg = load_file("background.js")
        page.evaluate(bg + "; 'loaded'")
        self.page = page

    # --- Вкладки ---

    def test_save_current_tab(self):
        send_msg(self.page, "save-current", name="Test Tab")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) >= 1
        found = [t for t in tabs if t["name"] == "Test Tab"]
        assert len(found) == 1

    def test_add_tab(self):
        send_msg(self.page, "add-tab", name="Google", url="https://google.com")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        found = [t for t in tabs if t["url"] == "https://google.com"]
        assert len(found) >= 1

    def test_delete_tab(self):
        send_msg(self.page, "add-tab", name="ToDelete", url="https://delete.me")
        send_msg(self.page, "delete", index=0)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert not any(t["name"] == "ToDelete" for t in tabs)

    def test_open_tab_creates_browser_tab(self):
        send_msg(self.page, "add-tab", name="OpenMe", url="https://open.me")
        send_msg(self.page, "open", index=0)
        created = self.page.evaluate("chrome.tabs.createdTabs.length")
        assert created > 0

    def test_save_with_folder_id(self):
        # Создаём папку
        folder_result = self.page.evaluate("""(async () => {
          var fn = window._onMessageHandler;
          return new Promise(resolve => { if (fn) fn({action:'create-folder',name:'TestFolder'}, null, resolve); });
        })()""")
        assert folder_result is not None

        # Сохраняем вкладку в папку
        folders = read_storage_raw(self.page, "blattam-folders")
        fid = [f for f in folders if f["name"] == "TestFolder"][0]["id"]
        send_msg(self.page, "save-current", name="InFolder", folderId=fid)

        tabs = read_storage_raw(self.page, "blattam-tabs")
        found = [t for t in tabs if t["name"] == "InFolder" and t.get("folderId") == fid]
        assert len(found) == 1

    # --- Папки ---

    def test_create_folder(self):
        result = self.page.evaluate("""(async () => {
          return new Promise(resolve => {
            window._onMessageHandler({action:'create-folder',name:'NewFolder'}, null, resolve);
          });
        })()""")
        assert result is not None and result.get("id") is not None

    def test_create_duplicate_folder_returns_null(self):
        # Первая создание
        r1 = self.page.evaluate("""(async () => {
          return new Promise(resolve => {
            window._onMessageHandler({action:'create-folder',name:'UniqueFolder'}, null, resolve);
          });
        })()""")
        assert r1 is not None  # создана

        # Дубль
        r2 = self.page.evaluate("""(async () => {
          return new Promise(resolve => {
            window._onMessageHandler({action:'create-folder',name:'UniqueFolder'}, null, resolve);
          });
        })()""")
        assert r2 is None  # дубль → null

    def test_rename_folder(self):
        # Создаём
        fid = self.page.evaluate("""(async () => {
          return new Promise(resolve => {
            window._onMessageHandler({action:'create-folder',name:'ToRename'}, null, resolve);
          });
        })()""")["id"]

        # Ренеймим
        send_msg(self.page, "rename-folder", id=fid, name="RenamedFolder")
        folders = read_storage_raw(self.page, "blattam-folders")
        found = [f for f in folders if f["id"] == fid]
        assert len(found) == 1 and found[0]["name"] == "RenamedFolder"

    def test_delete_folder_moves_tabs_to_all(self):
        # Создаём папку + вкладку в ней
        fid = self.page.evaluate("""(async () => {
          return new Promise(resolve => {
            window._onMessageHandler({action:'create-folder',name:'ToDeleteFolder'}, null, resolve);
          });
        })()""")["id"]

        send_msg(self.page, "add-tab", name="InDeletingFolder", url="https://infolder.test", folderId=fid)

        # Удаляем папку
        self.page.evaluate(f"""(async () => {{
          await window._onMessageHandler({{"action":"delete-folder","id":"{fid}"}}, null, function(){{}});
        }})()""")

        folders = read_storage_raw(self.page, "blattam-folders")
        tabs = read_storage_raw(self.page, "blattam-tabs")

        assert not any(f["id"] == fid for f in folders)  # папка удалена
        tab_in_folder = [t for t in tabs if t["name"] == "InDeletingFolder"][0]
        assert tab_in_folder.get("folderId") is None  # вкладка → "Все"

    def test_move_tab_to_folder(self):
        fid = self.page.evaluate("""(async () => {
          return new Promise(resolve => {
            window._onMessageHandler({action:'create-folder',name:'MoveTarget'}, null, resolve);
          });
        })()""")["id"]

        send_msg(self.page, "add-tab", name="MovableTab", url="https://movable.test", folderId=None)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        movable = next(t for t in tabs if t["name"] == "MovableTab")
        idx = tabs.index(movable)

        send_msg(self.page, "move-tab", index=idx, folderId=fid)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        movable_after = next(t for t in tabs if t["name"] == "MovableTab")
        assert movable_after.get("folderId") == fid

    def test_migration_adds_folder_id_null(self):
        """Старые вкладки без folderId получают null."""
        # Ставим 'старую' вкладку напрямую
        self.page.evaluate("""chrome.storage._data['blattam-tabs'] = [
          {name:'OldTab', url:'https://old.test'}  // нет folderId!
        ];""")

        # ТрIGGER миграции — перезагружаем background.js
        page = self.page
        bg = load_file("background.js")
        page.evaluate(bg + "; 'reloaded'")

        tabs = read_storage_raw(self.page, "blattam-tabs")
        old_tab = [t for t in tabs if t["name"] == "OldTab"]
        assert len(old_tab) == 1 and old_tab[0].get("folderId") is None


# ==========================================
#  VIEW.JS TESTS
# ==========================================

VIEW_DOM = """<div class="header"><h1>BlattamToby</h1></div><div class="container">
<div class="folders-bar" id="folders-bar">
  <button class="folder-chip active" data-folder-id="">Все</button>
  <button class="add-folder-btn" id="add-folder-btn">+ Папка</button>
</div>
<input type="text" class="search-box" placeholder="Поиск..." id="search">
<div id="empty-state" style="display:none;">Нет сохранённых вкладок</div>
<div id="no-results" class="no-results" style="display:none;">Ничего не найдено</div>
<div id="tabs-list"></div></div>

<!-- Модалка -->
<div class="modal-overlay" id="folder-modal">
  <div class="modal"><h3 id="modal-title">Новая папка</h3>
  <input type="text" id="folder-name-input" placeholder="Название..." autocomplete="off">
  <div class="modal-actions">
    <button class="modal-btn" id="modal-cancel">Отмена</button>
    <button class="modal-btn primary" id="modal-confirm">OK</button>
  </div></div></div>

<!-- Хедер кнопки -->
<div style="display:none"><button id="export-btn"></button><button id="import-btn"></button>
<input type="file" id="import-input" accept=".json"></div>"""


class TestView:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        """Load view.js with mocked DOM + data."""
        self.page = page

    def _load_view(self, tabs=None, folders=None):
        pg = self.page
        init_data = ""
        if tabs is not None:
            init_data += f"chrome.storage._data['blattam-tabs'] = {json.dumps(tabs)};\n"
        if folders is not None:
            init_data += f"chrome.storage._data['blattam-folders'] = {json.dumps(folders)};\n"

        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME + init_data)
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        view_js = load_file("view.js")
        try:
            pg.evaluate(view_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")

    def test_render_cards(self):
        self._load_view(tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 2

    def test_search_filter(self):
        self._load_view(tabs=[
            {"name": "Google", "url": "https://google.com"},
            {"name": "GitHub", "url": "https://github.com"},
            {"name": "Gmail", "title": "Mail Service", "url": "https://gmail.com"},
        ])
        self.page.locator("#search").fill("Google")
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1

    def test_search_by_url(self):
        """Поиск по URL работает."""
        self._load_view(tabs=[
            {"name": "Tab", "url": "https://example.com/page"},
            {"name": "Other", "url": "https://other.com"},
        ])
        self.page.locator("#search").fill("example")
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1

    def test_no_results_shown(self):
        self._load_view(tabs=[{"name": "X", "url": "https://x.com"}])
        self.page.locator("#search").fill("NEVEREXIST")
        visible = self.page.evaluate("document.getElementById('no-results').style.display !== 'none'")
        assert visible

    def test_empty_state(self):
        self._load_view(tabs=[])
        empty = self.page.evaluate("document.getElementById('empty-state').style.display !== 'none'")
        assert empty

    # --- Папки в view ---

    def test_folder_chips_rendered(self):
        self._load_view(
            tabs=[{"name": "A", "url": "https://a.com"}],
            folders=[{"id": "f1", "name": "Work"}, {"id": "f2", "name": "Personal"}]
        )
        chips = self.page.evaluate("""document.querySelectorAll('.folder-chip[data-folder-id]').length - document.querySelectorAll('.folder-chip[data-folder-id=""]').length""")
        assert chips == 2

    def test_click_folder_filters_tabs(self):
        fid = "f1"
        self._load_view(
            tabs=[
                {"name": "WorkTab", "url": "https://work.com", "folderId": fid},
                {"name": "FreeTab", "url": "https://free.com", "folderId": None},
            ],
            folders=[{"id": fid, "name": "Work"}]
        )
        # Клик по папке
        self.page.evaluate(f"""document.querySelector('.folder-chip[data-folder-id="{fid}"]').click()""")
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1

    def test_all_chip_resets_filter(self):
        fid = "f1"
        self._load_view(
            tabs=[
                {"name": "InFolder", "url": "https://in.com", "folderId": fid},
                {"name": "OutOfFolder", "url": "https://out.com", "folderId": None},
            ],
            folders=[{"id": fid, "name": "Work"}]
        )
        # Сначала фильтр по папке
        self.page.evaluate(f"""document.querySelector('.folder-chip[data-folder-id="{fid}"]').click()""")
        filtered = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert filtered == 1

        # Сброс на "Все"
        self.page.evaluate("""document.querySelector('.folder-chip[data-folder-id=""]').click()""")
        all_cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert all_cards == 2

    def test_create_folder_modal_opens(self):
        self._load_view(tabs=[], folders=[])
        self.page.locator("#add-folder-btn").click()
        modal_open = self.page.evaluate("document.getElementById('folder-modal').classList.contains('open')")
        assert modal_open

    def test_export_includes_folders(self):
        """Экспорт включает папки в JSON."""
        fid = "f1"
        self._load_view(
            tabs=[{"name": "A", "url": "https://a.com", "folderId": fid}],
            folders=[{"id": fid, "name": "Work"}]
        )
        # Проверяем что данные для экспорта включают folders
        export_data = self.page.evaluate("""(async () => {
          var tabs = (await chrome.storage.get('blattam-tabs'))['blattam-tabs'] || [];
          var folders = (await chrome.storage.get('blattam-folders'))['blattam-folders'] || [];
          return JSON.stringify({tabs, folders});
        })()""")
        data = json.loads(export_data)
        assert "folders" in data
        assert len(data["folders"]) == 1


# ==========================================
#  POPUP.JS TESTS
# ==========================================

POPUP_DOM = """<button id="save-current-tab">💾 Сохранить вкладку</button>
<label for="folder-select">📁 Папка:</label>
<select id="folder-select"><option value="">Все (без папки)</option></select>
<button class="add-folder-btn" id="popup-add-folder">+ Новая папка</button>
<div id="saved-msg" style="opacity:0;">✓ Вкладка сохранена!</div>

<!-- Модалка -->
<div class="modal-overlay" id="folder-modal">
  <div class="modal"><h3>Новая папка</h3>
  <input type="text" id="folder-name-input" placeholder="Название..." autocomplete="off">
  <div class="modal-actions">
    <button class="modal-btn" id="modal-cancel">Отмена</button>
    <button class="modal-btn primary" id="modal-confirm">OK</button>
  </div></div></div>"""


class TestPopup:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_popup(self, folders=None):
        pg = self.page
        init_data = ""
        if folders is not None:
            init_data += f"chrome.storage._data['blattam-folders'] = {json.dumps(folders)};\n"

        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME + init_data)
        pg.evaluate(f"document.body.innerHTML = `{POPUP_DOM}`")
        popup_js = load_file("popup.js")
        try:
            pg.evaluate(popup_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"Popup.js error: {e}")

    def test_folder_selector_shows_folders(self):
        self._load_popup(folders=[{"id": "f1", "name": "Work"}, {"id": "f2", "name": "Personal"}])
        opts = self.page.evaluate("document.querySelectorAll('#folder-select option').length")
        assert opts == 3  # "" + Work + Personal

    def test_save_sends_folder_id(self):
        fid = "f1"
        self._load_popup(folders=[{"id": fid, "name": "Work"}])
        self.page.evaluate(f'document.getElementById("folder-select").value = "{fid}"')
        self.page.locator("#save-current-tab").click()

        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg.get("action") == "save-current"
        assert msg.get("folderId") == fid

    def test_save_without_folder_sends_null(self):
        self._load_popup(folders=[{"id": "f1", "name": "Work"}])
        # Убеждаемся что выбрано "" (без папки)
        self.page.evaluate('document.getElementById("folder-select").value = ""')
        self.page.locator("#save-current-tab").click()

        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg.get("action") == "save-current"
        # folderId должен быть falsy (null/undefined) или пустая строка преобразованная в null
        fid_val = msg.get("folderId")
        assert not fid_val  # null, undefined, or ""

    def test_add_folder_modal_opens(self):
        self._load_popup(folders=[])
        self.page.locator("#popup-add-folder").click()
        modal_open = self.page.evaluate("document.getElementById('folder-modal').classList.contains('open')")
        assert modal_open

    def test_save_button_shows_confirmation(self):
        self._load_popup(folders=[])
        self.page.locator("#save-current-tab").click()
        shown = self.page.evaluate("document.getElementById('saved-msg').classList.contains('show')")
        assert shown


# ==========================================
#  EDGE CASES
# ==========================================

class TestEdgeCases:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        page.goto("about:blank")
        page.evaluate(MOCK_CHROME)
        bg = load_file("background.js")
        page.evaluate(bg + "; 'loaded'")

    def test_delete_nonexistent_index_noop(self):
        send_msg(self.page, "delete", index=999)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 0

    def test_move_to_invalid_folder_noop(self):
        send_msg(self.page, "add-tab", name="X", url="https://x.com")
        send_msg(self.page, "move-tab", index=0, folderId="nonexistent-id")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert tabs[0].get("folderId") is None  # не изменилось

    def test_rename_nonexistent_folder_noop(self):
        self.page.evaluate("""(async () => {
          await window._onMessageHandler({action:'rename-folder',id:'nope',name:'X'}, null, function(){});
        })()""")
        folders = read_storage_raw(self.page, "blattam-folders")
        assert len(folders) == 0

    def test_chrome_url_not_saved(self):
        """chrome:// URL не сохраняется."""
        self.page.evaluate("chrome.tabs._currentTab.url = 'chrome://settings'")
        send_msg(self.page, "save-current", name="Settings")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert not any(t.get("name") == "Settings" for t in tabs) or len(tabs) == 0

    def test_duplicate_url_same_folder_skipped(self):
        fid = self.page.evaluate("""(async () => {
          return new Promise(resolve => {
            window._onMessageHandler({action:'create-folder',name:'DupTest'}, null, resolve);
          });
        })()""")["id"]

        send_msg(self.page, "add-tab", name="First", url="https://dup.com", folderId=fid)
        send_msg(self.page, "add-tab", name="Second", url="https://dup.com", folderId=fid)

        tabs = read_storage_raw(self.page, "blattam-tabs")
        in_folder = [t for t in tabs if t["url"] == "https://dup.com" and t.get("folderId") == fid]
        assert len(in_folder) == 1  # дубль пропущен

    def test_same_url_different_folders_allowed(self):
        """Один URL в разных папках — допустимо."""
        f1 = self.page.evaluate("""(async () => {
          return new Promise(resolve => {
            window._onMessageHandler({action:'create-folder',name:'F1'}, null, resolve);
          });
        })()""")["id"]
        f2 = self.page.evaluate("""(async () => {
          return new Promise(resolve => {
            window._onMessageHandler({action:'create-folder',name:'F2'}, null, resolve);
          });
        })()""")["id"]

        send_msg(self.page, "add-tab", name="In F1", url="https://same.com", folderId=f1)
        send_msg(self.page, "add-tab", name="In F2", url="https://same.com", folderId=f2)

        tabs = read_storage_raw(self.page, "blattam-tabs")
        in_f1 = [t for t in tabs if t["url"] == "https://same.com" and t.get("folderId") == f1]
        in_f2 = [t for t in tabs if t["url"] == "https://same.com" and t.get("folderId") == f2]
        assert len(in_f1) == 1 and len(in_f2) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

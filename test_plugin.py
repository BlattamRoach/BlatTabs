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
    sync: { _data: {} },
    local: { _data: {} }
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
    sendMessage: function(msg) {
      this.messagesSent.push(msg);
      window.lastMessage = msg;
      // rename-tab: применяем к storage и шлём onChanged (как делает background в реальности)
      if (msg.action === 'rename-tab') {
        var tabs = chrome.storage._data['blattam-tabs'] || [];
        if (tabs[msg.index] && (msg.name || '').trim()) {
          tabs[msg.index].name = String(msg.name).trim();
          var oldVal = chrome.storage._data['blattam-tabs'];
          chrome.storage._data['blattam-tabs'] = tabs;
          if (window.__storageListeners && window.__storageListeners.length) {
            for (var fn of window.__storageListeners) fn({'blattam-tabs': {newValue: tabs, oldValue: oldVal}}, 'sync');
          }
        }
      }
      // move-tab: применяем folderId и шлём onChanged
      if (msg.action === 'move-tab') {
        var tabs2 = chrome.storage._data['blattam-tabs'] || [];
        if (tabs2[msg.index]) {
          tabs2[msg.index].folderId = msg.folderId;
          var oldVal2 = chrome.storage._data['blattam-tabs'];
          chrome.storage._data['blattam-tabs'] = tabs2;
          if (window.__storageListeners && window.__storageListeners.length) {
            for (var fn of window.__storageListeners) fn({'blattam-tabs': {newValue: tabs2, oldValue: oldVal2}}, 'sync');
          }
        }
      }
      return Promise.resolve();
    },
    getManifest: function() { return { version: '1.0.0' }; }
  }
};

// Patch chrome.storage.sync → chrome.storage._data
Object.defineProperty(chrome.storage, 'sync', { value: { _data: chrome.storage._data } });
chrome.storage.sync.get = function(keys, cb) { return chrome.storage.get(keys, cb); };
chrome.storage.sync.set = function(data, cb) { return chrome.storage.set(data, cb); };

// Patch chrome.storage.local — отдельное хранилище (ключи: 'blattam-theme' и т.п.)
chrome.storage.local.get = function(keys, cb) {
  var result = {};
  if (typeof keys === 'string') {
    result[keys] = this._data[keys];
  } else if (Array.isArray(keys)) {
    for (var k of keys) result[k] = this._data[k];
  } else {
    Object.assign(result, this._data);
  }
  if (cb) cb(result);
  return Promise.resolve(result);
};
chrome.storage.local.set = function(data, cb) {
  var changeInfo = {};
  for (var k in data) changeInfo[k] = { newValue: data[k], oldValue: this._data[k] };
  Object.assign(this._data, data);
  if (window.__storageListeners && window.__storageListeners.length) {
    for (var fn of window.__storageListeners) fn(changeInfo, 'local');
  }
  if (cb) cb();
  return Promise.resolve();
};

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

    def test_rename_tab(self):
        send_msg(self.page, "add-tab", name="Before", url="https://rename.me")
        send_msg(self.page, "rename-tab", index=0, name="After")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        found = [t for t in tabs if t["url"] == "https://rename.me"]
        assert len(found) == 1 and found[0]["name"] == "After"

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

VIEW_DOM = """<div class="header"><h1>BlattamToby</h1>
<div class="header-actions"><button class="action-btn" id="theme-btn" title="Переключить тёмную/светлую тему">🌙</button><button class="action-btn" id="select-btn">☑ Выбрать</button></div></div>
<div class="container">
<div class="folders-bar" id="folders-bar">
  <button class="folder-chip active" data-folder-id="">Все</button>
  <button class="add-folder-btn" id="add-folder-btn">+ Папка</button>
</div>
<div class="search-row"><input type="text" class="search-box" placeholder="Поиск..." id="search"></div>
<div id="empty-state" style="display:none;">Нет сохранённых вкладок</div>
<div id="no-results" class="no-results" style="display:none;">Ничего не найдено</div>
<div id="tabs-list"></div></div>

<!-- Панель выбора -->
<div id="selection-bar" class="selection-bar hidden">
  <span id="selection-count" class="selection-count">0 выбрано</span>
  <button id="open-selected-btn" class="action-btn">Открыть</button>
  <button id="clear-selection-btn" class="action-btn">Сбросить</button>
</div>

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

    def test_dblclick_name_opens_inline_input(self):
        """Двойной клик по имени → инлайн input."""
        self._load_view(tabs=[{"name": "Original", "url": "https://orig.com"}])
        self.page.evaluate("""(() => {
          const el = document.querySelector('.tab-name');
          el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
          el.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
        })()""")
        has_input = self.page.evaluate("!!document.querySelector('.tab-name-input')")
        assert has_input

    def test_rename_saves_on_enter(self):
        """Enter сохраняет новое имя."""
        self._load_view(tabs=[{"name": "OldName", "url": "https://old.com"}])
        self.page.evaluate("""(() => {
          const el = document.querySelector('.tab-name');
          el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
          el.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
        })()""")
        self.page.evaluate("""(() => {
          const inp = document.querySelector('.tab-name-input');
          inp.value = 'NewName';
          inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
        })()""")
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg.get("action") == "rename-tab"
        assert msg.get("name") == "NewName"
        name = self.page.evaluate("document.querySelector('.tab-name').textContent")
        assert name == "NewName"

    def test_rename_cancel_on_escape(self):
        """Escape отменяет переименование."""
        self._load_view(tabs=[{"name": "KeepMe", "url": "https://keep.com"}])
        self.page.evaluate("""(() => {
          const el = document.querySelector('.tab-name');
          el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
          el.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
        })()""")
        self.page.evaluate("""(() => {
          const inp = document.querySelector('.tab-name-input');
          inp.value = 'Changed';
          inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
        })()""")
        name = self.page.evaluate("document.querySelector('.tab-name').textContent")
        assert name == "KeepMe"

    def test_single_click_opens_tab(self):
        """Одиночный клик по имени открывает вкладку (после 300мс)."""
        self._load_view(tabs=[{"name": "OpenTab", "url": "https://opentab.com"}])
        self.page.evaluate("""(() => {
          const el = document.querySelector('.tab-name');
          el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        })()""")
        self.page.wait_for_timeout(400)
        created = self.page.evaluate("chrome.tabs.createdTabs.length")
        assert created == 1
        last_url = self.page.evaluate("chrome.tabs.createdTabs[chrome.tabs.createdTabs.length-1].url")
        assert last_url == "https://opentab.com"

    def test_drag_card_to_folder_chip(self):
        """DnD: карточку на чип папки → move-tab + folderId обновился."""
        self._load_view(
            tabs=[{"name": "DragMe", "url": "https://drag.com", "folderId": None}],
            folders=[{"id": "f1", "name": "Work"}]
        )
        self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const chip = document.querySelector('.folder-chip[data-folder-id="f1"]');
          chip.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          chip.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg.get("action") == "move-tab"
        assert msg.get("folderId") == "f1"
        # После onChanged вкладка в папке
        fids = json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.folderId));
        })()"""))
        assert fids == ["f1"]

    def test_drag_card_to_all_chip(self):
        """DnD: карточку на чип «Все» → folderId = null."""
        self._load_view(
            tabs=[{"name": "DragToAll", "url": "https://dragall.com", "folderId": "f1"}],
            folders=[{"id": "f1", "name": "Work"}]
        )
        self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const chip = document.querySelector('.folder-chip[data-folder-id=""]');
          chip.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          chip.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg.get("action") == "move-tab"
        assert msg.get("folderId") is None
        fids = json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.folderId));
        })()"""))
        assert fids == [None]

    def test_dragstart_sets_payload(self):
        """dragstart кладёт индекс карточки в dataTransfer."""
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        result = self.page.evaluate("""(() => {
          const cards = document.querySelectorAll('.tab-card');
          const dt = new DataTransfer();
          cards[1].dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          return JSON.stringify({
            payload: dt.getData('text/plain'),
            dragging: cards[1].classList.contains('dragging')
          });
        })()""")
        data = json.loads(result)
        assert data["payload"] == "1"
        assert data["dragging"] is True

    # --- Массовое открытие ---

    def test_checkboxes_rendered_on_cards(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        boxes = self.page.evaluate("document.querySelectorAll('.tab-select').length")
        assert boxes == 2

    def test_select_bar_hidden_when_nothing_selected(self):
        self._load_view(tabs=[{"name": "A", "url": "https://a.com"}])
        hidden = self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")
        assert hidden

    def test_checkbox_selects_tab_and_shows_bar(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        self.page.evaluate("document.querySelectorAll('.tab-select')[0].click()")
        hidden = self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")
        count = self.page.evaluate("document.getElementById('selection-count').textContent")
        card_selected = self.page.evaluate("document.querySelectorAll('.tab-card')[0].classList.contains('selected')")
        assert not hidden
        assert "1" in count
        assert card_selected

    def test_open_selected_opens_all_and_clears(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
            {"name": "Third", "url": "https://third.com"},
        ])
        # Выбираем первые две
        self.page.evaluate("document.querySelectorAll('.tab-select')[0].click()")
        self.page.evaluate("document.querySelectorAll('.tab-select')[1].click()")
        self.page.evaluate("document.getElementById('open-selected-btn').click()")
        created = self.page.evaluate("JSON.stringify(chrome.tabs.createdTabs.map(t => t.url))")
        urls = json.loads(created)
        assert "https://first.com" in urls
        assert "https://second.com" in urls
        assert "https://third.com" not in urls
        # Выбор сброшен
        hidden = self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")
        checked = self.page.evaluate("document.querySelectorAll('.tab-select:checked').length")
        assert hidden
        assert checked == 0

    def test_select_btn_selects_all_visible(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
            {"name": "Third", "url": "https://third.com"},
        ])
        self.page.evaluate("document.getElementById('select-btn').click()")
        checked = self.page.evaluate("document.querySelectorAll('.tab-select:checked').length")
        assert checked == 3
        count = self.page.evaluate("document.getElementById('selection-count').textContent")
        assert "3" in count

    def test_select_btn_unselects_all_visible(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        self.page.evaluate("document.getElementById('select-btn').click()")
        self.page.evaluate("document.getElementById('select-btn').click()")
        checked = self.page.evaluate("document.querySelectorAll('.tab-select:checked').length")
        hidden = self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")
        assert checked == 0
        assert hidden

    def test_select_btn_only_affects_visible(self):
        """Под фильтр папки — «Выбрать» трогает только видимые."""
        fid = "f1"
        self._load_view(
            tabs=[
                {"name": "InFolder", "url": "https://infolder.com", "folderId": fid},
                {"name": "FreeTab", "url": "https://free.com", "folderId": None},
            ],
            folders=[{"id": fid, "name": "Work"}]
        )
        # Активируем папку
        self.page.evaluate("document.querySelector('.folder-chip[data-folder-id=\"f1\"]').click()")
        self.page.evaluate("document.getElementById('select-btn').click()")
        checked = self.page.evaluate("document.querySelectorAll('.tab-select:checked').length")
        assert checked == 1

    def test_open_selected_opens_in_background(self):
        """Массовое открытие — вкладки создаются неактивными."""
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        self.page.evaluate("document.getElementById('select-btn').click()")
        self.page.evaluate("document.getElementById('open-selected-btn').click()")
        active = self.page.evaluate("chrome.tabs.createdTabs.filter(t => t.active).length")
        total = self.page.evaluate("chrome.tabs.createdTabs.length")
        assert total == 2
        assert active == 0

    def test_single_click_open_clears_selection(self):
        """Одиночный клик по имени открывает вкладку и снимает выбор."""
        self._load_view(tabs=[{"name": "OpenTab", "url": "https://opentab.com"}])
        self.page.evaluate("document.getElementById('select-btn').click()")
        self.page.evaluate("document.querySelector('.tab-name').click()")
        self.page.wait_for_timeout(400)
        created = self.page.evaluate("chrome.tabs.createdTabs.length")
        hidden = self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")
        assert created == 1
        assert hidden

    def test_storage_change_resets_selection(self):
        """Изменение storage (onChanged) сбрасывает выбор."""
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        self.page.evaluate("document.getElementById('select-btn').click()")
        hidden_before = self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")
        assert not hidden_before
        # Симулируем внешнее изменение (как background.js)
        self.page.evaluate("chrome.storage._data['blattam-tabs'].push({name: 'Third', url: 'https://third.com'})")
        self.page.evaluate("""(() => {
          var tabs = chrome.storage._data['blattam-tabs'];
          for (var fn of window.__storageListeners) fn({'blattam-tabs': {newValue: tabs, oldValue: []}}, 'sync');
        })()""")
        hidden_after = self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")
        assert hidden_after

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
#  KEYBOARD NAVIGATION (view.js)
# ==========================================

class TestKeyboardNav:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
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
        pg.evaluate("window.confirm = () => true;")
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        view_js = load_file("view.js")
        try:
            pg.evaluate(view_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")

    def press(self, key):
        self.page.evaluate(f"document.dispatchEvent(new KeyboardEvent('keydown', {{key: '{key}', bubbles: true, cancelable: true}}))")

    def test_arrow_down_activates_first_card(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        self.press("ArrowDown")
        active = self.page.evaluate("document.querySelectorAll('.tab-card.kbd-active').length")
        assert active == 1
        name = self.page.evaluate("document.querySelector('.tab-card.kbd-active .tab-name').textContent")
        assert name == "First"

    def test_arrow_moves_between_cards(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
            {"name": "Third", "url": "https://third.com"},
        ])
        self.press("ArrowDown")
        self.press("ArrowDown")
        name = self.page.evaluate("document.querySelector('.tab-card.kbd-active .tab-name').textContent")
        assert name == "Second"
        self.press("ArrowUp")
        name = self.page.evaluate("document.querySelector('.tab-card.kbd-active .tab-name').textContent")
        assert name == "First"

    def test_arrow_wraps_around(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        self.press("ArrowDown")
        self.press("ArrowDown")
        self.press("ArrowDown")  # Second → обёртка на First
        name = self.page.evaluate("document.querySelector('.tab-card.kbd-active .tab-name').textContent")
        assert name == "First"  # зациклено

    def test_enter_opens_active_tab(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        self.press("ArrowDown")
        self.press("ArrowDown")
        self.press("Enter")
        created = json.loads(self.page.evaluate("JSON.stringify(chrome.tabs.createdTabs)"))
        assert len(created) == 1
        assert created[0]["url"] == "https://second.com"
        assert created[0].get("active") is True

    def test_enter_without_selection_opens_first(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
        ])
        self.press("Enter")
        created = json.loads(self.page.evaluate("JSON.stringify(chrome.tabs.createdTabs)"))
        assert len(created) == 1
        assert created[0]["url"] == "https://first.com"

    def test_delete_removes_active_tab(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        self.press("ArrowDown")  # First
        self.press("ArrowDown")  # Second
        self.press("Delete")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert [t["name"] for t in tabs] == ["First"]
        # Удалённая карточка не остаётся активной
        active = self.page.evaluate("document.querySelectorAll('.tab-card.kbd-active').length")
        assert active == 0

    def test_escape_resets_search_and_active(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
            {"name": "Second", "url": "https://second.com"},
        ])
        self.page.locator("#search").fill("first")
        self.press("Escape")  # Esc прямо из поля поиска
        assert self.page.evaluate("document.getElementById('search').value") == ""
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        active = self.page.evaluate("document.querySelectorAll('.tab-card.kbd-active').length")
        assert cards == 2
        assert active == 0

    def test_arrows_ignored_while_typing(self):
        self._load_view(tabs=[
            {"name": "First", "url": "https://first.com"},
        ])
        self.page.locator("#search").click()  # фокус в поле
        self.page.evaluate("document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true, cancelable: true}))")
        active = self.page.evaluate("document.querySelectorAll('.tab-card.kbd-active').length")
        assert active == 0

    def test_nav_respects_folder_filter(self):
        fid = "f1"
        self._load_view(
            tabs=[
                {"name": "InFolder", "url": "https://infolder.com", "folderId": fid},
                {"name": "FreeTab", "url": "https://free.com", "folderId": None},
            ],
            folders=[{"id": fid, "name": "Work"}]
        )
        self.page.evaluate(f"document.querySelector('.folder-chip[data-folder-id=\"{fid}\"]').click()")
        self.press("ArrowDown")
        name = self.page.evaluate("document.querySelector('.tab-card.kbd-active .tab-name').textContent")
        assert name == "InFolder"
        self.press("ArrowDown")  # зацикл — остаётся в фильтре
        name = self.page.evaluate("document.querySelector('.tab-card.kbd-active .tab-name').textContent")
        assert name == "InFolder"

    def test_nav_respects_search_filter(self):
        self._load_view(tabs=[
            {"name": "Alpha", "url": "https://alpha.com"},
            {"name": "Beta", "url": "https://beta.com"},
            {"name": "Gamma", "url": "https://gamma.com"},
        ])
        self.page.locator("#search").fill("beta")
        self.page.evaluate("document.getElementById('search').blur()")  # навигация — когда фокус вне поля
        self.press("ArrowDown")
        name = self.page.evaluate("document.querySelector('.tab-card.kbd-active .tab-name').textContent")
        assert name == "Beta"


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

    def test_rename_nonexistent_tab_noop(self):
        send_msg(self.page, "add-tab", name="Keep", url="https://keep2.com")
        send_msg(self.page, "rename-tab", index=999, name="Hacked")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert all(t["name"] != "Hacked" for t in tabs)

    def test_rename_empty_name_noop(self):
        send_msg(self.page, "add-tab", name="Keep2", url="https://keep3.com")
        send_msg(self.page, "rename-tab", index=0, name="   ")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        found = [t for t in tabs if t["url"] == "https://keep3.com"]
        assert len(found) == 1 and found[0]["name"] == "Keep2"

    def test_rename_trims_whitespace(self):
        send_msg(self.page, "add-tab", name="Trim", url="https://trim.com")
        send_msg(self.page, "rename-tab", index=0, name="  Padded  ")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        found = [t for t in tabs if t["url"] == "https://trim.com"]
        assert len(found) == 1 and found[0]["name"] == "Padded"

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


# ==========================================
#  DARK THEME (view.js + theme.css)
# ==========================================

class TestDarkTheme:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_view(self, theme=None, tabs=None):
        pg = self.page
        init_data = ""
        if theme is not None:
            init_data += f"chrome.storage.local._data['blattam-theme'] = {json.dumps(theme)};\n"
        if tabs is not None:
            init_data += f"chrome.storage._data['blattam-tabs'] = {json.dumps(tabs)};\n"
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME + init_data)
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        view_js = load_file("view.js")
        try:
            pg.evaluate(view_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")

    def test_theme_button_exists(self):
        """Кнопка переключателя темы есть в шапке."""
        self._load_view()
        exists = self.page.evaluate("!!document.getElementById('theme-btn')")
        assert exists

    def test_default_theme_is_light(self):
        """По умолчанию (без сохранённого значения) — светлая тема."""
        self._load_view()
        theme = self.page.evaluate("document.documentElement.dataset.theme")
        assert theme == "light"
        icon = self.page.evaluate("document.getElementById('theme-btn').textContent")
        assert icon == "🌙"

    def test_click_switches_to_dark(self):
        """Клик переключает data-theme на dark."""
        self._load_view()
        self.page.evaluate("document.getElementById('theme-btn').click()")
        theme = self.page.evaluate("document.documentElement.dataset.theme")
        assert theme == "dark"
        icon = self.page.evaluate("document.getElementById('theme-btn').textContent")
        assert icon == "☀️"

    def test_theme_saved_to_local_storage(self):
        """После клика значение пишется в chrome.storage.local под ключом 'blattam-theme'."""
        self._load_view()
        self.page.evaluate("document.getElementById('theme-btn').click()")
        saved = self.page.evaluate("chrome.storage.local._data['blattam-theme']")
        assert saved == "dark"

    def test_saved_theme_applied_on_load(self):
        """При загрузке с сохранённой темой data-theme применяется (до рендера)."""
        self._load_view(theme="dark", tabs=[{"name": "A", "url": "https://a.com"}])
        theme = self.page.evaluate("document.documentElement.dataset.theme")
        assert theme == "dark"
        icon = self.page.evaluate("document.getElementById('theme-btn').textContent")
        assert icon == "☀️"
        # Рендер при этом работает
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1

    def test_second_click_returns_to_light(self):
        """Повторный клик возвращает светлую тему и пишет её в storage."""
        self._load_view()
        self.page.evaluate("document.getElementById('theme-btn').click()")
        self.page.evaluate("document.getElementById('theme-btn').click()")
        theme = self.page.evaluate("document.documentElement.dataset.theme")
        assert theme == "light"
        saved = self.page.evaluate("chrome.storage.local._data['blattam-theme']")
        assert saved == "light"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

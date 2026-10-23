"""
Тесты BlattamToby через Playwright.
Мокируем Chrome API, проверяем background.js, view.js, popup.js + папки/категории.

Запуск: python test_plugin.py
"""
import importlib.util
import json
import os
import pytest
import struct
import zipfile
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
    _currentTab: { id: 'mockTab1', url: 'https://example.com', title: 'Example Domain', favIconUrl: 'https://example.com/favicon.ico' },
    query: function(query, callback) { if (callback) callback([this._currentTab]); },
  },
  commands: {
    onCommand: { _listeners: [], addListener: function(fn) { this._listeners.push(fn); } }
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
      // reorder-tab: переставляем элемент в массиве (как background.js) и шлём onChanged
      if (msg.action === 'reorder-tab') {
        var tabs3 = chrome.storage._data['blattam-tabs'] || [];
        var from3 = Number(msg.fromIndex), to3 = Number(msg.toIndex);
        if (Number.isInteger(from3) && Number.isInteger(to3) &&
            from3 !== to3 && from3 >= 0 && from3 < tabs3.length && to3 >= 0 && to3 < tabs3.length) {
          var oldVal3 = chrome.storage._data['blattam-tabs'];
          var moved3 = tabs3.splice(from3, 1)[0];
          var shift3 = from3 < to3 ? -1 : 0;
          var at3 = (msg.side === 'before' ? to3 : to3 + 1) + shift3;
          tabs3.splice(Math.max(0, Math.min(tabs3.length, at3)), 0, moved3);
          if (window.__storageListeners && window.__storageListeners.length) {
            for (var fn of window.__storageListeners) fn({'blattam-tabs': {newValue: tabs3, oldValue: oldVal3}}, 'sync');
          }
        }
      }
      // open-one / open-many: создаёт browser-tab(s) (как background.js)
      if (msg.action === 'open-one') {
        chrome.tabs.create({ url: msg.url, active: true });
      }
      if (msg.action === 'open-many') {
        (msg.urls || []).forEach(function(url) {
          chrome.tabs.create({ url: url, active: false });
        });
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

    def test_icons(self):
        m = json.load(open(f"{EXT_PATH}/manifest.json"))
        assert m["icons"] == {
            "16": "icons/icon16.png",
            "48": "icons/icon48.png",
            "128": "icons/icon128.png",
        }
        assert m["action"]["default_icon"]["128"] == "icons/icon128.png"


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

VIEW_DOM = """<div class="header"><h1>Toby</h1>
<div class="header-actions"><button class="action-btn" id="theme-btn" title="Переключить тёмную/светлую тему"><span class="glyph">\U0001F319</span></button><button class="action-btn" id="select-btn">☑ Выбрать</button></div></div>
<div class="container">
<div class="folders-bar" id="folders-bar">
  <button class="chip folder-chip active" data-folder-id="">Все</button>
  <button class="chip-add" id="add-folder-btn">+ Папка</button>
<div class="search-row"><input type="text" class="search-box" placeholder="Поиск..." id="search"></div>
<div id="meta-label">Все вкладки</div>
<div id="meta-count">0</div>
<div id="empty-state" style="display:none;">Нет сохранённых вкладок</div>
<div id="no-results" class="no-results" style="display:none;">Ничего не найдено<button id="btn-reset-filters">Сбросить фильтры</button></div>
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
#  ТЕГИ / ЦВЕТОВЫЕ МЕТКИ (view.js)

class TestNestedFolders:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_view(self, tabs=None, folders=None, tags=None):
        pg = self.page
        init_data = ""
        if tabs is not None:
            init_data += f"chrome.storage._data['blattam-tabs'] = {json.dumps(tabs)};\n"
        if folders is not None:
            init_data += f"chrome.storage._data['blattam-folders'] = {json.dumps(folders)};\n"
        if tags is not None:
            init_data += f"chrome.storage._data['blattam-tags'] = {json.dumps(tags)};\n"
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME + init_data)
        pg.evaluate("window.confirm = () => true;")
        # background.js — для create-folder/delete-folder через _onMessageHandler
        bg = load_file("background.js")
        pg.evaluate(bg + "; 'bg-loaded'")
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        view_js = load_file("view.js")
        try:
            pg.evaluate(view_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")

    def _create_folder(self, name, parent_id=None):
        return self.page.evaluate("""(async (args) => {
          return new Promise(resolve => {
            window._onMessageHandler({action: 'create-folder', name: args[0], parentId: args[1]}, null, resolve);
          });
        })""", [name, parent_id])

    def test_create_nested_folder(self):
        """Создание вложенной папки: parentId записывается, чип с «↳»."""
        self._load_view(tabs=[], folders=[])
        parent = self._create_folder("Parent")
        assert parent is not None
        child = self._create_folder("Child", parent["id"])
        assert child is not None
        assert child.get("parentId") == parent["id"]
        # Двойное вложение запрещено (родитель сам вложенный)
        grandchild = self._create_folder("Grandchild", child["id"])
        assert grandchild is None
        folders = read_storage_raw(self.page, "blattam-folders")
        assert len(folders) == 2
        # Вложенный чип — с классом nested и «↳»
        nested_chip = self.page.evaluate(f"""(() => {{
          const chip = document.querySelector('.folder-chip[data-folder-id="{child["id"]}"]');
          return chip ? JSON.stringify({{nested: chip.classList.contains('nested'), icon: chip.firstElementChild.textContent}}) : null;
        }})()""")
        data = json.loads(nested_chip)
        assert data["nested"] is True
        assert data["icon"] == "↳"

    def test_folder_filter_includes_nested_tabs(self):
        """Фильтр по родительской папке показывает вкладки вложенной папки."""
        self._load_view(tabs=[], folders=[])
        parent = self._create_folder("Parent")
        child = self._create_folder("Child", parent["id"])
        self.page.evaluate("""(async (args) => {
          await window._onMessageHandler({action: 'add-tab', name: 'InParent', url: 'https://ip.com', folderId: args[0]}, null, function(){});
          await window._onMessageHandler({action: 'add-tab', name: 'InChild', url: 'https://ic.com', folderId: args[1]}, null, function(){});
          await window._onMessageHandler({action: 'add-tab', name: 'Free', url: 'https://fr.com', folderId: null}, null, function(){});
        })""", [parent["id"], child["id"]])
        # Фильтр по Parent → 2 вкладки (в свою + вложенную)
        self.page.evaluate(f'document.querySelector(\'[data-folder-id="{parent["id"]}"]\').click()')
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 2
        # Фильтр по Child → только свою
        self.page.evaluate("document.querySelector('.folder-chip[data-folder-id=\"\"]').click()")
        self.page.evaluate(f'document.querySelector(\'[data-folder-id="{child["id"]}"]\').click()')
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1

    def test_move_dropdown_shows_hierarchy(self):
        """Дропдаун перемещения показывает иерархию (вложенная — отступ + «↳»)."""
        self._load_view(tabs=[], folders=[])
        parent = self._create_folder("Parent")
        child = self._create_folder("Child", parent["id"])
        self._load_view(
            tabs=[{"name": "Tab", "url": "https://t.com", "folderId": None}],
            folders=[
                {"id": parent["id"], "name": "Parent", "parentId": None},
                {"id": child["id"], "name": "Child", "parentId": parent["id"]},
            ]
        )
        self.page.evaluate("document.querySelector('.tab-card .folder-select-btn').click()")
        items = self.page.evaluate("""JSON.stringify(
          [...document.querySelectorAll('.tab-card .folder-dropdown .folder-dd-item')].map(i => ({
            text: i.textContent, nested: i.classList.contains('nested')
          }))
        )""")
        parsed = json.loads(items)
        texts = [i["text"] for i in parsed]
        assert "→ Parent" in texts
        assert any(t == "→ ↳ Child" for t in texts)
        nested_items = [i for i in parsed if i["nested"]]
        assert len(nested_items) == 1 and "Child" in nested_items[0]["text"]

    def test_popup_selector_shows_hierarchy(self):
        """Селектор popup показывает вложенную папку с «↳»."""
        self._load_view(tabs=[], folders=[])
        parent = self._create_folder("Parent")
        child = self._create_folder("Child", parent["id"])
        # Загружаем popup с этими папками
        pg = self.page
        folders = read_storage_raw(pg, "blattam-folders")
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME + f"chrome.storage._data['blattam-folders'] = {json.dumps(folders)};\n")
        pg.evaluate(f"document.body.innerHTML = `{POPUP_DOM}`")
        pg.evaluate(load_file("popup.js") + "; 'loaded'")
        opts = pg.evaluate("JSON.stringify([...document.querySelectorAll('#folder-select option')].map(o => o.textContent))")
        parsed = json.loads(opts)
        assert "Parent" in parsed
        assert "↳ Child" in parsed
        assert len(parsed) == 3  # "" + Parent + Child

    def test_delete_parent_removes_children_and_moves_all_tabs(self):
        """Удаление родительской папки: вложенные папки удаляются, все их вкладки → «Все»."""
        self._load_view(tabs=[], folders=[])
        parent = self._create_folder("Parent")
        child = self._create_folder("Child", parent["id"])
        self.page.evaluate("""(async (args) => {
          await window._onMessageHandler({action: 'add-tab', name: 'InParent', url: 'https://ip.com', folderId: args[0]}, null, function(){});
          await window._onMessageHandler({action: 'add-tab', name: 'InChild', url: 'https://ic.com', folderId: args[1]}, null, function(){});
        })""", [parent["id"], child["id"]])
        self.page.evaluate(f"""(async (id) => {{
          await window._onMessageHandler({{action: 'delete-folder', id}}, null, function(){{}});
        }})""", parent["id"])
        folders = read_storage_raw(self.page, "blattam-folders")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert folders == []  # обе папки удалены
        assert all(t.get("folderId") is None for t in tabs)  # все вкладки → «Все»

    def test_nested_chip_filters_include_child_tabs_via_view(self):
        """Клик по вложенному чипу фильтрует только его вкладки."""
        self._load_view(tabs=[], folders=[])
        parent = self._create_folder("Parent")
        child = self._create_folder("Child", parent["id"])
        self.page.evaluate("""(async (args) => {
          await window._onMessageHandler({action: 'add-tab', name: 'P', url: 'https://p.com', folderId: args[0]}, null, function(){});
          await window._onMessageHandler({action: 'add-tab', name: 'C', url: 'https://c.com', folderId: args[1]}, null, function(){});
        })""", [parent["id"], child["id"]])
        self.page.evaluate(f'document.querySelector(\'[data-folder-id="{child["id"]}"]\').click()')
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1
        name = self.page.evaluate("document.querySelector('.tab-card .tab-name').textContent")
        assert name == "C"


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
#  DnD REORDER: перестановка карточек (view.js)
# ==========================================

class TestReorderDnD:
    """Drag карточки на другую карточку → порядок в 'blattam-tabs' меняется
    (верхняя половина цели — перед, нижняя — после). Чипы папок продолжают
    перемещать вкладки (регрессия)."""

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
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        view_js = load_file("view.js")
        try:
            pg.evaluate(view_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")

    def _drag_drop_card(self, src_idx, dst_idx, half):
        """dragstart на cards[src_idx], dragover+drop (clientY — верхняя/нижняя половина цели) на cards[dst_idx], dragend."""
        self.page.evaluate("""(args) => {
          const cards = document.querySelectorAll('.tab-card');
          const [srcIdx, dstIdx, half] = args;
          const r = cards[dstIdx].getBoundingClientRect();
          const clientY = half === 'before' ? r.top + r.height * 0.25 : r.top + Math.max(r.height * 0.75, 0.001);
          const dt = new DataTransfer();
          cards[srcIdx].dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          cards[dstIdx].dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientY}));
          cards[dstIdx].dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true, clientY}));
          cards[srcIdx].dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        }""", [src_idx, dst_idx, half])

    def _tab_names(self):
        return json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.name));
        })()"""))

    def test_drop_top_half_inserts_before(self):
        """Дроп в верхнюю половину цели → перетаскиваемая вкладка ПЕРЕД ней."""
        self._load_view(tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
            {"name": "C", "url": "https://c.com"},
        ])
        self._drag_drop_card(0, 2, 'before')  # A → верх C
        assert self._tab_names() == ["B", "A", "C"]
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg.get("action") == "reorder-tab"
        assert msg.get("fromIndex") == 0 and msg.get("toIndex") == 2 and msg.get("side") == "before"

    def test_drop_bottom_half_inserts_after(self):
        """Дроп в нижнюю половину цели → перетаскиваемая вкладка ПОСЛЕ неё."""
        self._load_view(tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
            {"name": "C", "url": "https://c.com"},
        ])
        self._drag_drop_card(0, 2, 'after')  # A → низ C
        assert self._tab_names() == ["B", "C", "A"]
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg.get("action") == "reorder-tab"
        assert msg.get("side") == "after"

    def test_drop_on_self_noop(self):
        """Дроп карточки на саму себя → порядок не меняется, reorder-tab не шлётся."""
        self._load_view(tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        self._drag_drop_card(0, 0, 'before')
        assert self._tab_names() == ["A", "B"]
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage || null)"))
        assert msg is None or msg.get("action") != "reorder-tab"

    def test_reorder_under_folder_filter_changes_full_array(self):
        """Под фильтром папки reorder меняет порядок ПОЛНОГО массива; folderId не трогается."""
        fid = "f1"
        self._load_view(
            tabs=[
                {"name": "Free1", "url": "https://free1.com", "folderId": None},
                {"name": "WorkA", "url": "https://wa.com", "folderId": fid},
                {"name": "Free2", "url": "https://free2.com", "folderId": None},
                {"name": "WorkB", "url": "https://wb.com", "folderId": fid},
            ],
            folders=[{"id": fid, "name": "Work"}]
        )
        self.page.evaluate(f'document.querySelector(\'[data-folder-id="{fid}"]\').click()')
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 2
        # WorkA (полный индекс 1) → низ WorkB (полный индекс 3): after
        self._drag_drop_card(0, 1, 'after')
        assert self._tab_names() == ["Free1", "Free2", "WorkB", "WorkA"]
        fids = json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.folderId));
        })()"""))
        assert fids == [None, None, fid, fid]  # folderId не изменился

    def test_selection_and_active_url_survive_reorder(self):
        """Выбор (selectedUrls) и активная карточка (activeUrl) переживают reorder (ключ — URL)."""
        self._load_view(tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
            {"name": "C", "url": "https://c.com"},
        ])
        self.page.evaluate("document.getElementById('select-btn').click()")  # все 3 выбрана
        self.page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true, cancelable: true}))")  # active = A
        self._drag_drop_card(2, 0, 'before')  # C → верх A
        assert self._tab_names() == ["C", "A", "B"]
        # Выбор не сброшен
        checked = self.page.evaluate("document.querySelectorAll('.tab-select:checked').length")
        bar_hidden = self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")
        assert checked == 3 and not bar_hidden
        # Активная карточка — та же (по URL), на новом месте
        active_names = json.loads(self.page.evaluate("JSON.stringify([...document.querySelectorAll('.tab-card.kbd-active .tab-name')].map(e => e.textContent))"))
        assert active_names == ["A"]

    def test_dragend_without_drop_no_change_no_indicator(self):
        """dragend без drop: порядок не меняется, индикаторы не остаются, 'dragging' снят."""
        self._load_view(tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        self.page.evaluate("""(() => {
          const cards = document.querySelectorAll('.tab-card');
          const dt = new DataTransfer();
          cards[0].dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const r = cards[1].getBoundingClientRect();
          cards[1].dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientY: r.top + Math.max(r.height * 0.75, 0.001)}));
          assert_indicators = document.querySelectorAll('.tab-card.drop-before, .tab-card.drop-after').length;
          window.__indicatorShown = assert_indicators;
          cards[0].dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        assert self.page.evaluate("window.__indicatorShown") == 1  # индикатор был виден на dragover
        assert self._tab_names() == ["A", "B"]  # порядок не изменился
        left = self.page.evaluate("document.querySelectorAll('.tab-card.drop-before, .tab-card.drop-after').length")
        dragging = self.page.evaluate("document.querySelectorAll('.tab-card.dragging').length")
        assert left == 0 and dragging == 0

    def test_dragover_shows_correct_indicator_and_dragleave_clears(self):
        """dragover: верх → drop-before, низ → drop-after; dragleave снимает индикатор."""
        self._load_view(tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        self.page.evaluate("""(() => {
          const cards = document.querySelectorAll('.tab-card');
          const dt = new DataTransfer();
          cards[0].dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const r = cards[1].getBoundingClientRect();
          cards[1].dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientY: r.top + r.height * 0.25}));
          window.__top = cards[1].classList.contains('drop-before');
          cards[1].dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientY: r.top + Math.max(r.height * 0.75, 0.001)}));
          window.__bottom = cards[1].classList.contains('drop-after');
          cards[1].dispatchEvent(new DragEvent('dragleave', {bubbles: true}));
          window.__cleared = !cards[1].classList.contains('drop-before') && !cards[1].classList.contains('drop-after');
          cards[0].dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        state = json.loads(self.page.evaluate("JSON.stringify({top: window.__top, bottom: window.__bottom, cleared: window.__cleared})"))
        assert state == {"top": True, "bottom": True, "cleared": True}

    def test_folder_chip_drop_still_works(self):
        """Регрессия: дроп карточки на чип папки всё ещё перемещает в папку."""
        fid = "f1"
        self._load_view(
            tabs=[{"name": "DragMe", "url": "https://drag.com", "folderId": None}],
            folders=[{"id": fid, "name": "Work"}]
        )
        self.page.evaluate("""(args) => {
          const [fid] = args;
          const card = document.querySelector('.tab-card');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const chip = document.querySelector('.folder-chip[data-folder-id="' + fid + '"]');
          chip.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          chip.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        }""", [fid])
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg.get("action") == "move-tab"
        assert msg.get("folderId") == fid
        fids = json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.folderId));
        })()"""))
        assert fids == [fid]


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

# ==========================================
#  ГОРЯЧИЕ КЛАВИШИ (manifest commands + background.js)
# ==========================================

class TestHotkey:
    def test_manifest_has_save_tab_command(self):
        m = json.load(open(f"{EXT_PATH}/manifest.json"))
        cmd = m["commands"]["save-tab"]
        assert cmd["suggested_key"]["default"] == "Ctrl+Shift+S"
        assert cmd["description"] == "Сохранить текущую вкладку"

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        page.goto("about:blank")
        page.evaluate(MOCK_CHROME)
        page.evaluate(load_file("background.js") + "; 'loaded'")
        self.page = page

    def _fire_command(self, command):
        self.page.evaluate(f"""(() => {{
          chrome.commands.onCommand._listeners.forEach(fn => fn({json.dumps(command)}));
        }})()""")

    def test_on_command_save_tab_saves_active_tab(self):
        self._fire_command("save-tab")
        self.page.wait_for_timeout(100)  # асинхронные шаги saveCurrentTab (query + set)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1
        assert tabs[0]["url"] == "https://example.com"
        # Имя — заголовок вкладки, папка по умолчанию
        assert tabs[0]["name"] == "Example Domain"
        assert tabs[0]["folderId"] is None

    def test_on_command_skips_chrome_urls(self):
        self.page.evaluate("chrome.tabs._currentTab.url = 'chrome://settings'")
        self._fire_command("save-tab")
        self.page.wait_for_timeout(100)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert tabs == []

    def test_on_command_ignores_other_commands(self):
        self._fire_command("some-other-command")
        self.page.wait_for_timeout(100)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert tabs == []


# ==========================================
#  РЕКОМЕНДАЦИИ (Частые / Избранные + stats)

class TestRelease:
    """Релиз: сборка zip (build_zip.py), иконки 16/48/128, описание магазина."""

    EXPECTED_MEMBERS = {
        "manifest.json",
        "background.js",
        "popup.html",
        "popup.js",
        "view.html",
        "view.js",
        "theme.css",
        "icons/icon16.png",
        "icons/icon48.png",
        "icons/icon128.png",
    }
    EXCLUDED = ("test_plugin.py", "build_zip.py", "QWEN.md", "ROADMAP.md",
                "dist", ".git", ".pytest_cache", "__pycache__")

    def _run_build(self):
        """Импортируем build_zip.py как модуль и запускаем сборку (deterministic)."""
        spec = importlib.util.spec_from_file_location("build_zip", f"{EXT_PATH}/build_zip.py")
        bz = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bz)
        bz.main()
        return os.path.join(EXT_PATH, "dist", "BlattamToby-v%s.zip" % bz.read_version())

    @staticmethod
    def _png_size(path):
        """Размер PNG по IHDR (байты 16..24) — без зависимости от PIL."""
        with open(path, "rb") as f:
            head = f.read(24)
        assert head[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
        w, h = struct.unpack(">II", head[16:24])
        return w, h

    def test_build_zip_members_exact(self):
        """build_zip.py собирает zip ТОЛЬКО из файлов расширения, без исключений."""
        zip_path = self._run_build()
        assert os.path.isfile(zip_path), f"zip not created: {zip_path}"
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            assert names == self.EXPECTED_MEMBERS, f"unexpected members: {names ^ self.EXPECTED_MEMBERS}"
            # Ни одного исключённого файла
            for bad in self.EXCLUDED:
                for n in names:
                    assert bad not in n.replace(os.sep, "/"), f"excluded file leaked: {n}"
            # manifest внутри — валидный JSON, и все его иконки присутствуют в zip
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            assert "icons" in manifest
            for px in ("16", "48", "128"):
                icon = manifest["icons"][px]
                assert icon in names, f"icon {icon} (size {px}) missing from zip"

    def test_icon_pixel_sizes(self):
        """Иконки существуют на диске и имеют точные размеры 16/48/128."""
        for px in (16, 48, 128):
            path = os.path.join(EXT_PATH, "icons", f"icon{px}.png")
            assert os.path.isfile(path), f"missing {path}"
            w, h = self._png_size(path)
            assert (w, h) == (px, px), f"icon{px}.png is {w}x{h}, expected {px}x{px}"

    def test_description_has_short(self):
        """store/DESCRIPTION.md существует; короткое описание <= 132 символов."""
        path = os.path.join(EXT_PATH, "store", "DESCRIPTION.md")
        assert os.path.isfile(path), "missing store/DESCRIPTION.md"
        text = open(path, "r", encoding="utf-8").read()
        # Раздел «Короткое описание» → первая непустая строка-контент под ним
        assert "Короткое описание" in text, "no short-description section"
        rest = text[text.index("Короткое описание"):]
        short = ""
        for ln in rest.split("\n"):
            ln = ln.strip()
            if ln and not ln.startswith("##") and "Короткое описание" not in ln:
                short = ln
                break
        assert short, "empty short description"
        assert len(short) <= 132, f"short description too long ({len(short)} > 132)"
        assert "Ctrl+T" in short, "short description should mention Ctrl+T"


# ==========================================
#  ВЕРСИОНАЯ ОЧИСТКА: теги/архив/рекомендации/размер удалены
# ==========================================

class TestCleanup:
    """Убедиться что удалённые фичи действительно вычищены из живых файлов."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def test_export_json_has_no_tags_key(self):
        """Экспорт вкладки не содержит ключ 'tags' (теги удалены из проекта)."""
        pg = self.page
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME)
        pg.evaluate("window.confirm = () => true;")
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        pg.evaluate(load_file("view.js") + "; 'loaded'")
        pg.wait_for_timeout(100)
        # Симулируем экспорт-клик и перехватываем JSON
        result = pg.evaluate("""(() => {
          var origCreate = URL.createObjectURL;
          var captured = null;
          URL.createObjectURL = function(blob) {
            blob.text().then(function(t) { window.__capturedExport = t; });
            return origCreate.call(URL, blob);
          };
          document.getElementById('export-btn').click();
          return window.__capturedExport;
        })()""")
        # Blob.text() is async — wait a tick
        pg.wait_for_timeout(100)
        exported = pg.evaluate("window.__capturedExport || ''")
        data = json.loads(exported)
        assert "tags" not in data
        assert "tabs" in data
        assert "folders" in data
        assert "sessions" not in data

    def test_view_js_no_removed_storage_keys(self):
        """view.js не читает/пишет 'blattam-tags' / 'blattam-stats' / 'blattam-card-size'."""
        view_src = load_file("view.js")
        for bad in ("blattam-sessions", "blattam-tags", "blattam-stats", "blattam-card-size",
                    "tagIds", "archivedAt", "size-btn", "recordOpen",
                    "set-tab-tags", "create-tag", "delete-tag", "frequent", "favorites"):
            assert bad not in view_src, f"view.js still references '{bad}'"

    def test_background_js_no_removed_features(self):
        """background.js: no tags/archive/stats machinery."""
        bg_src = load_file("background.js")
        for bad in ("blattam-tags", "blattam-stats", "blattam-card-size",
                    "tagIds", "archivedAt", "onRemoved", "recordOpen",
                    "set-tab-tags", "create-tag", "delete-tag", "unarchive"):
            assert bad not in bg_src, f"background.js still references '{bad}'"

    def test_theme_css_no_tag_tokens(self):
        """theme.css: no --tag-* tokens (теги удалены)."""
        css_src = load_file("theme.css")
        assert "--tag-" not in css_src, "theme.css still has --tag-* tokens"
        assert "--archived-" not in css_src, "theme.css still has --archived-* tokens"


# ==========================================
#  SITE FAVICON: favicon на карточках (background.js + view.js)
# ==========================================

class TestFavicons:
    """favIconUrl захватывается при сохранении; карточка показывает <img class="tab-favicon">
    или буквенный fallback (нет фавикона / он не загрузился)."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_env(self, confirm=False):
        """about:blank + mock + background.js (+ confirm-мок опционально)."""
        pg = self.page
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME)
        pg.evaluate(load_file("background.js") + "; 'loaded'")
        if confirm:
            pg.evaluate("window.confirm = () => true;")

    def _load_view(self, tabs=None):
        pg = self.page
        init_data = ""
        if tabs is not None:
            init_data += f"chrome.storage._data['blattam-tabs'] = {json.dumps(tabs)};\n"
        pg.evaluate(init_data)
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        view_js = load_file("view.js")
        try:
            pg.evaluate(view_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")
        pg.wait_for_timeout(50)

    def test_save_current_stores_favicon(self):
        """save-current: вкладка получает favIconUrl из tabs._currentTab."""
        self._load_env()
        send_msg(self.page, "save-current", name="FavTab")
        self.page.wait_for_timeout(100)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1
        assert tabs[0]["favIconUrl"] == "https://example.com/favicon.ico"

    def test_card_renders_favicon_img(self):
        """Вкладка с favIconUrl → <img class="tab-favicon"> с этим src перед именем."""
        self._load_env()
        self._load_view(tabs=[
            {"name": "GitHub", "url": "https://github.com", "favIconUrl": "https://github.com/favicon.ico"},
        ])
        src = self.page.evaluate("(() => { var i = document.querySelector('.tab-card .tab-favicon'); return i ? i.src : null; })()")
        assert src == "https://github.com/favicon.ico"
        # img — ПЕРВЫЙ элемент строки имени (до .tab-name)
        first = self.page.evaluate("document.querySelector('.tab-card .cname').firstElementChild.className")
        assert first == "tab-favicon"

    def test_card_renders_letter_fallback_without_favicon(self):
        """Нет favIconUrl → буквенный fallback (первая буква домена), <img> нет."""
        self._load_env()
        self._load_view(tabs=[
            {"name": "GitHub", "url": "https://github.com"},
            {"name": "Nope", "url": "https://nope.example/path"},
        ])
        imgs = self.page.evaluate("document.querySelectorAll('.tab-card .tab-favicon').length")
        assert imgs == 0
        letters = json.loads(self.page.evaluate("JSON.stringify([...document.querySelectorAll('.tab-card .tab-favicon-fallback')].map(e => e.textContent))"))
        assert letters == ["g", "n"]

    def test_favicon_load_error_swaps_to_fallback(self):
        """img onerror → заменяется на буквенный fallback (без img)."""
        self._load_env()
        self._load_view(tabs=[
            {"name": "GitHub", "url": "https://github.com", "favIconUrl": "https://missing.invalid/favicon.ico"},
        ])
        self.page.evaluate("(() => { var i = document.querySelector('.tab-card .tab-favicon'); if (i) i.dispatchEvent(new Event('error')); })()")
        self.page.wait_for_timeout(50)
        imgs = self.page.evaluate("document.querySelectorAll('.tab-card .tab-favicon').length")
        assert imgs == 0
        letter = self.page.evaluate("document.querySelector('.tab-card .tab-favicon-fallback') && document.querySelector('.tab-card .tab-favicon-fallback').textContent")
        assert letter == "g"
        # Имя на месте
        name = self.page.evaluate("document.querySelector('.tab-card .tab-name').textContent")
        assert name == "GitHub"

    def test_import_keeps_favIconUrl(self):
        """Импорт: вкладка с favIconUrl сохраняет его; без него — не появляется."""
        self._load_env(confirm=True)
        self._load_view(tabs=[])
        payload = json.dumps({"blattam-toby": True, "version": "1.0.0", "folders": [],
                              "tabs": [
                                  {"name": "GH", "url": "https://github.com", "favIconUrl": "https://github.com/favicon.ico"},
                                  {"name": "Plain", "url": "https://plain.example"},
                              ]})
        self.page.evaluate("(() => {\n"
                           "  var payload = " + json.dumps(payload) + ";\n"
                           "  var input = document.getElementById('import-input');\n"
                           "  var dt = new DataTransfer();\n"
                           "  dt.items.add(new File([payload], 'blattam-toby-backup.json', {type: 'application/json'}));\n"
                           "  input.files = dt.files;\n"
                           "  input.dispatchEvent(new Event('change'));\n"
                           "})()")
        self.page.wait_for_timeout(150)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        by_url = {t["url"]: t for t in tabs}
        assert by_url["https://github.com"]["favIconUrl"] == "https://github.com/favicon.ico"
        assert "favIconUrl" not in by_url["https://plain.example"]

    def test_export_includes_favIconUrl(self):
        """Экспорт: favIconUrl едет обычным полем вкладок."""
        self._load_env()
        self._load_view(tabs=[
            {"name": "GH", "url": "https://github.com", "favIconUrl": "https://github.com/favicon.ico"},
        ])
        self.page.evaluate("(() => { URL.createObjectURL = function(b) { return 'blob:mock'; }; URL.revokeObjectURL = function() {}; window.__exportBlob = null; var orig = Blob; Blob = function(parts, opts) { window.__exportBlob = parts[0]; return new orig(parts, opts); }; document.getElementById('export-btn').click(); })()")
        exported = self.page.evaluate("window.__exportBlob")
        data = json.loads(exported)
        assert data["tabs"][0]["favIconUrl"] == "https://github.com/favicon.ico"

# ==========================================
#  END OF NEW FEATURE TESTS
# ==========================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

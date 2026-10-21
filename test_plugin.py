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
    _currentTab: { id: 'mockTab1', url: 'https://example.com', title: 'Example Domain', favIconUrl: '' },
    query: function(query, callback) { if (callback) callback([this._currentTab]); },
    // onRemoved: хранит зарегистрированные обработчики — тесты дёргают их
    // как (tabId, removedTab) (объект закрытой вкладки с url/title)
    onRemoved: { _listeners: [], addListener: function(fn) { this._listeners.push(fn); } },
    // Мока captureVisibleTab: возвращает крошечный dataURL (1x1 gif);
    // window.__failCapture = true симулирует сбой (неactive window и т.п.)
    captureVisibleTab: function(windowId, options, callback) {
      var p = new Promise(function(resolve, reject) {
        if (window.__failCapture) reject(new Error('captureVisibleTab failed'));
        else resolve('data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==');
      });
      if (typeof options === 'function') { callback = options; options = null; }
      if (callback) { p.then(function(d) { callback(d); }, function(err) { callback(''); }); return; }
      return p;
    }
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
      // set-tab-tags: применяет tagIds (только существующие теги) и шлёт onChanged
      if (msg.action === 'set-tab-tags') {
        var tabs3 = chrome.storage._data['blattam-tabs'] || [];
        var tags = chrome.storage._data['blattam-tags'] || [];
        if (tabs3[msg.index]) {
          tabs3[msg.index].tagIds = (msg.tagIds || []).filter(function(id) {
            return tags.some(function(t) { return t.id === id; });
          });
          var oldVal3 = chrome.storage._data['blattam-tabs'];
          chrome.storage._data['blattam-tabs'] = tabs3;
          if (window.__storageListeners && window.__storageListeners.length) {
            for (var fn of window.__storageListeners) fn({'blattam-tabs': {newValue: tabs3, oldValue: oldVal3}}, 'sync');
          }
        }
      }
      // open-one / open-many: создаёт browser-tab(s) + инкрементит 'blattam-stats'
      // (единый путь, как createTabFromSaved в background.js)
      if (msg.action === 'open-one') {
        chrome.tabs.create({ url: msg.url, active: true });
        chrome.__bgRecordOpen(msg.url);
      }
      if (msg.action === 'open-many') {
        (msg.urls || []).forEach(function(url) {
          chrome.tabs.create({ url: url, active: false });
          chrome.__bgRecordOpen(url);
        });
      }
      // unarchive-tab: снимает archivedAt (как background) и шлёт onChanged
      if (msg.action === 'unarchive-tab') {
        var tabs4 = chrome.storage._data['blattam-tabs'] || [];
        if (tabs4[msg.index] && tabs4[msg.index].archivedAt !== undefined) {
          delete tabs4[msg.index].archivedAt;
          var oldVal4 = chrome.storage._data['blattam-tabs'];
          chrome.storage._data['blattam-tabs'] = tabs4;
          if (window.__storageListeners && window.__storageListeners.length) {
            for (var fn of window.__storageListeners) fn({'blattam-tabs': {newValue: tabs4, oldValue: oldVal4}}, 'sync');
          }
        }
      }
      return Promise.resolve();
    },
    getManifest: function() { return { version: '1.0.0' }; }
  }
};

// Подсчёт открытия URL в 'blattam-stats' (chrome.storage.local) — как
// recordOpen в background.js: +1 к opens, lastOpened = now, prune до 500 URL
chrome.__bgRecordOpen = function(url) {
  if (!url) return;
  var key = 'blattam-stats';
  var stats = chrome.storage.local._data[key] = chrome.storage.local._data[key] || {};
  var cur = stats[url] || { opens: 0, lastOpened: 0 };
  stats[url] = { opens: cur.opens + 1, lastOpened: Date.now() };
  var keys = Object.keys(stats);
  if (keys.length > 500) {
    keys.sort(function(a, b) { return (stats[a].lastOpened || 0) - (stats[b].lastOpened || 0); });
    for (var i = 0; i < keys.length - 500; i++) delete stats[keys[i]];
  }
};

// Асинхронные мутаторы для мока (имитация background.js): create/delete-tag.
// Реально в Chrome эти действия выполняет service worker.
chrome.__bgCreateTag = async function(name, color) {
  var tags = chrome.storage._data['blattam-tags'] || (chrome.storage._data['blattam-tags'] = []);
  if (tags.some(function(t) { return t.name.toLowerCase() === name.toLowerCase(); })) return null;
  var c = parseInt(color, 10);
  if (isNaN(c) || c < 1 || c > 6) c = 1;
  var tag = { id: 't' + Math.random().toString(36).slice(2, 10), name: name, color: c };
  tags.push(tag);
  chrome.storage.set({'blattam-tags': tags});
  return tag;
};
chrome.__bgDeleteTag = async function(tagId) {
  var tags = chrome.storage._data['blattam-tags'] || [];
  var remaining = tags.filter(function(t) { return t.id !== tagId; });
  if (remaining.length === tags.length) return;
  chrome.storage.set({'blattam-tags': remaining});
  var tabs = chrome.storage._data['blattam-tabs'] || [];
  var changed = false;
  tabs.forEach(function(t) {
    if (Array.isArray(t.tagIds) && t.tagIds.indexOf(tagId) !== -1) {
      t.tagIds = t.tagIds.filter(function(id) { return id !== tagId; });
      changed = true;
    }
  });
  if (changed) chrome.storage.set({'blattam-tabs': tabs});
};

// create-tag / delete-tag: применяем к storage и шлём onChanged (как background в реальности)
var _origSendMessage = chrome.runtime.sendMessage;
chrome.runtime.sendMessage = function(msg) {
  if (msg && msg.action === 'create-tag') {
    chrome.__bgCreateTag(msg.name, msg.color);
  } else if (msg && msg.action === 'delete-tag') {
    chrome.__bgDeleteTag(msg.id);
  }
  return _origSendMessage.call(this, msg);
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

VIEW_DOM = """<div class="header"><h1>BlattamToby</h1>
<div class="header-actions"><button class="action-btn" id="size-btn" title="Компактные карточки">▦ Крупные</button><button class="action-btn" id="theme-btn" title="Переключить тёмную/светлую тему">🌙</button><button class="action-btn" id="select-btn">☑ Выбрать</button></div></div>
<div class="container">
<div class="folders-bar" id="folders-bar">
  <button class="folder-chip active" data-folder-id="">Все</button>
  <button class="folder-chip special" id="archive-chip" title="Архив">🗄 Архив</button>
  <button class="folder-chip special" id="frequent-chip" title="Частые">⭐ Частые</button>
  <button class="folder-chip special" id="favorites-chip" title="Избранные">🕘 Избранные</button>
  <button class="add-folder-btn" id="add-folder-btn">+ Папка</button>
</div>
<div class="tags-bar" id="tags-bar">
  <button class="add-tag-btn" id="add-tag-btn">+ Тег</button>
</div>
<div class="sessions-bar" id="sessions-bar">
  <button class="add-session-btn" id="add-session-btn">📋 + Сессия</button>
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

<!-- Модалка: тег -->
<div class="modal-overlay" id="tag-modal">
  <div class="modal"><h3>Новый тег</h3>
  <input type="text" id="tag-name-input" placeholder="Название..." autocomplete="off">
  <div class="tag-color-palette" id="tag-color-palette"></div>
  <div class="modal-actions">
    <button class="modal-btn" id="tag-modal-cancel">Отмена</button>
    <button class="modal-btn primary" id="tag-modal-confirm">OK</button>
  </div></div></div>

<!-- Модалка: сессия -->
<div class="modal-overlay" id="session-modal">
  <div class="modal"><h3>Новая сессия</h3>
  <input type="text" id="session-name-input" placeholder="Название..." autocomplete="off">
  <div class="modal-actions">
    <button class="modal-btn" id="session-modal-cancel">Отмена</button>
    <button class="modal-btn primary" id="session-modal-confirm">OK</button>
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
# ==========================================

class TestTags:
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
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        view_js = load_file("view.js")
        try:
            pg.evaluate(view_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")

    def test_create_tag_via_modal(self):
        """Модалка «+ Тег»: название + цвет → create-tag, чип появляется."""
        self._load_view(tabs=[], tags=[])
        self.page.locator("#add-tag-btn").click()
        assert self.page.evaluate("document.getElementById('tag-modal').classList.contains('open')")
        # Палитра из 6 кружков, выбран первый
        swatches = self.page.evaluate("document.querySelectorAll('#tag-color-palette .tag-swatch').length")
        assert swatches == 6
        assert self.page.evaluate("document.querySelector('#tag-color-palette .tag-swatch.selected').dataset.color") == "1"
        # Выбираем цвет 3, вводим название
        self.page.evaluate("document.querySelector('#tag-color-palette .tag-swatch[data-color=\"3\"]').click()")
        self.page.locator("#tag-name-input").fill("Work")
        # OK → create-tag (мок применяет к storage + шлёт onChanged)
        self.page.locator("#tag-modal-confirm").click()
        self.page.wait_for_timeout(100)  # микрозадачи: async create-tag + storage.set
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "create-tag"
        assert msg["name"] == "Work"
        assert msg["color"] == 3
        # Тег в storage, чип отрендерился
        tags = read_storage_raw(self.page, "blattam-tags")
        assert len(tags) == 1 and tags[0]["name"] == "Work" and tags[0]["color"] == 3
        chips = self.page.evaluate("document.querySelectorAll('.tag-chip[data-tag-id]').length")
        assert chips == 1

    def test_tag_chips_rendered_with_dots(self):
        self._load_view(tabs=[], tags=[
            {"id": "tg1", "name": "Red", "color": 1},
            {"id": "tg2", "name": "Blue", "color": 4},
        ])
        chips = self.page.evaluate("document.querySelectorAll('.tag-chip[data-tag-id]').length")
        assert chips == 2
        colors = self.page.evaluate("""JSON.stringify(
          [...document.querySelectorAll('.tag-chip .tag-dot')].map(d => d.dataset.color)
        )""")
        assert json.loads(colors) == ["1", "4"]

    def test_click_tag_chip_filters_tabs(self):
        self._load_view(
            tabs=[
                {"name": "Tagged", "url": "https://tagged.com", "tagIds": ["tg1"]},
                {"name": "Untagged", "url": "https://untagged.com", "tagIds": []},
            ],
            tags=[{"id": "tg1", "name": "Red", "color": 1}]
        )
        self.page.evaluate("document.querySelector('.tag-chip[data-tag-id=\"tg1\"]').click()")
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1
        names = self.page.evaluate("document.querySelector('.tab-card .tab-name').textContent")
        assert names == "Tagged"
        # Повторный клик снимает фильтр
        self.page.evaluate("document.querySelector('.tag-chip[data-tag-id=\"tg1\"]').click()")
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 2

    def test_tag_filter_combines_with_folder_and_search(self):
        """Фильтр тега работает одновременно с фильтром папки и поиском."""
        fid = "f1"
        self._load_view(
            tabs=[
                {"name": "Work Tagged", "url": "https://wt.com", "folderId": fid, "tagIds": ["tg1"]},
                {"name": "Work Other", "url": "https://wo.com", "folderId": fid, "tagIds": ["tg2"]},
                {"name": "Free Tagged", "url": "https://ft.com", "folderId": None, "tagIds": ["tg1"]},
            ],
            folders=[{"id": fid, "name": "Work"}],
            tags=[{"id": "tg1", "name": "Red", "color": 1}, {"id": "tg2", "name": "Blue", "color": 4}]
        )
        self.page.evaluate(f'document.querySelector(\'[data-folder-id="{fid}"]\').click()')
        self.page.evaluate("document.querySelector('.tag-chip[data-tag-id=\"tg1\"]').click()")
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1
        # Поиск сверху: ничего не найдено
        self.page.locator("#search").fill("nope")
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 0

    def test_card_shows_tag_dots(self):
        self._load_view(
            tabs=[{"name": "Multi", "url": "https://multi.com", "tagIds": ["tg1", "tg3"]}],
            tags=[
                {"id": "tg1", "name": "Red", "color": 1},
                {"id": "tg2", "name": "Blue", "color": 4},
                {"id": "tg3", "name": "Green", "color": 3},
            ]
        )
        colors = self.page.evaluate("""JSON.stringify(
          [...document.querySelectorAll('.tab-card .card-tags .card-tag-dot')].map(d => d.dataset.color)
        )""")
        assert json.loads(colors) == ["1", "3"]

    def test_edit_tab_tags_via_dropdown(self):
        """Дропдаун 🎨: чекбокс отмечает тег → set-tab-tags, точка появляется; снятие — удаляет."""
        self._load_view(
            tabs=[{"name": "Tab", "url": "https://t.com", "tagIds": []}],
            tags=[{"id": "tg1", "name": "Red", "color": 1}, {"id": "tg2", "name": "Blue", "color": 4}]
        )
        # Открываем дропдаун тегов (вторая folder-select-btn)
        self.page.evaluate("document.querySelectorAll('.tab-card .folder-select-btn')[1].click()")
        open_dd = self.page.evaluate("document.querySelector('.tab-card .tag-dropdown').classList.contains('open')")
        assert open_dd
        boxes = self.page.evaluate("document.querySelectorAll('.tab-card .tag-dropdown input[type=checkbox]').length")
        assert boxes == 2
        # Отмечаем оба тега (мультиселект: дропдаун не закрывается)
        self.page.evaluate("(() => { const cb = document.querySelectorAll('.tab-card .tag-dropdown input[type=checkbox]')[0]; cb.click(); cb.dispatchEvent(new Event('change', {bubbles: true})); })()")
        self.page.wait_for_timeout(50)  # re-render после set-tab-tags (state дропдауна переживает его)
        self.page.evaluate("(() => { const cb = document.querySelectorAll('.tab-card .tag-dropdown input[type=checkbox]')[1]; cb.click(); cb.dispatchEvent(new Event('change', {bubbles: true})); })()")
        self.page.wait_for_timeout(50)
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "set-tab-tags"
        assert sorted(msg["tagIds"]) == ["tg1", "tg2"]
        # После onChanged точка рендерится, дропдаун всё ещё открыт
        dots = self.page.evaluate("document.querySelectorAll('.tab-card .card-tags .card-tag-dot').length")
        assert dots == 2
        still_open = self.page.evaluate("document.querySelector('.tab-card .tag-dropdown').classList.contains('open')")
        assert still_open
        # Снимаем первый тег
        self.page.evaluate("(() => { const cb = document.querySelectorAll('.tab-card .tag-dropdown input[type=checkbox]')[0]; cb.click(); cb.dispatchEvent(new Event('change', {bubbles: true})); })()")
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "set-tab-tags"
        assert msg["tagIds"] == ["tg2"]
        dots = self.page.evaluate("document.querySelectorAll('.tab-card .card-tags .card-tag-dot').length")
        assert dots == 1

    def test_delete_tag_clears_tab_tag_ids(self):
        """✕ на чипе (с confirm): тег удаляется, tagIds у вкладок очищаются."""
        self._load_view(
            tabs=[{"name": "Tagged", "url": "https://t.com", "tagIds": ["tg1"]}],
            tags=[{"id": "tg1", "name": "Red", "color": 1}]
        )
        # Мок уже применяет delete-tag к storage и шлёт onChanged
        self.page.evaluate("document.querySelector('.tag-chip .chip-icon-btn').click()")
        self.page.wait_for_timeout(100)  # микрозадачи: async delete-tag + storage.set
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "delete-tag"
        tags = read_storage_raw(self.page, "blattam-tags")
        assert tags == []
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert tabs[0].get("tagIds") == []
        # Чип исчез, точка на карточке исчезла
        chips = self.page.evaluate("document.querySelectorAll('.tag-chip').length")
        dots = self.page.evaluate("document.querySelectorAll('.card-tag-dot').length")
        assert chips == 0
        assert dots == 0

    def test_export_includes_tags(self):
        """Экспорт включает теги (ключ tags)."""
        self._load_view(
            tabs=[{"name": "A", "url": "https://a.com", "tagIds": ["tg1"]}],
            tags=[{"id": "tg1", "name": "Red", "color": 1}]
        )
        data = self.page.evaluate("""(async () => {
          var d = await chrome.storage.get(['blattam-tags', 'blattam-folders', 'blattam-tabs']);
          return JSON.stringify({
            tags: d['blattam-tags'] || [],
            folders: d['blattam-folders'] || [],
            tabs: d['blattam-tabs'] || []
          });
        })()""")
        parsed = json.loads(data)
        assert "tags" in parsed
        assert len(parsed["tags"]) == 1 and parsed["tags"][0]["id"] == "tg1"


# ==========================================
#  ВЛОЖЕННЫЕ ПАПКИ
# ==========================================

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
        self.page.wait_for_timeout(100)  # асинхронные шаги saveCurrentTab (query + capture + set)
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
#  АДАПТИВНЫЕ РАЗМЕРЫ КАРТОЧЕК (view.js)
# ==========================================

class TestCardSize:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_view(self, card_size=None, tabs=None):
        pg = self.page
        init_data = ""
        if card_size is not None:
            init_data += f"chrome.storage.local._data['blattam-card-size'] = {json.dumps(card_size)};\n"
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

    def test_size_button_exists(self):
        """Кнопка переключателя размера есть в шапке."""
        self._load_view()
        exists = self.page.evaluate("!!document.getElementById('size-btn')")
        assert exists

    def test_default_size_is_large(self):
        """По умолчанию (без сохранённого значения) — крупный режим."""
        self._load_view()
        compact = self.page.evaluate("document.body.classList.contains('compact-cards')")
        assert not compact
        label = self.page.evaluate("document.getElementById('size-btn').textContent")
        assert "Крупные" in label

    def test_click_switches_to_compact(self):
        """Клик переключает на компактный: класс compact-cards на body + подпись кнопки."""
        self._load_view(tabs=[{"name": "A", "url": "https://a.com"}])
        self.page.evaluate("document.getElementById('size-btn').click()")
        compact = self.page.evaluate("document.body.classList.contains('compact-cards')")
        assert compact
        label = self.page.evaluate("document.getElementById('size-btn').textContent")
        assert "Компактные" in label
        # Рендер при этом работает
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1

    def test_size_saved_to_local_storage(self):
        """После клика значение пишется в chrome.storage.local под ключом 'blattam-card-size'."""
        self._load_view()
        self.page.evaluate("document.getElementById('size-btn').click()")
        saved = self.page.evaluate("chrome.storage.local._data['blattam-card-size']")
        assert saved == "compact"

    def test_saved_size_applied_on_load(self):
        """При загрузке с сохранённым 'compact' класс применяется (до рендера)."""
        self._load_view(card_size="compact", tabs=[{"name": "A", "url": "https://a.com"}])
        compact = self.page.evaluate("document.body.classList.contains('compact-cards')")
        assert compact
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1

    def test_second_click_returns_to_large(self):
        """Повторный клик возвращает крупный режим и пишет его в storage."""
        self._load_view()
        self.page.evaluate("document.getElementById('size-btn').click()")
        self.page.evaluate("document.getElementById('size-btn').click()")
        compact = self.page.evaluate("document.body.classList.contains('compact-cards')")
        assert not compact
        saved = self.page.evaluate("chrome.storage.local._data['blattam-card-size']")
        assert saved == "large"

    def test_escape_does_not_reset_card_size(self):
        """Esc — глобальный сброс фильтров, НО НЕ сбрасывает размер карточек."""
        self._load_view(tabs=[{"name": "A", "url": "https://a.com"}])
        self.page.evaluate("document.getElementById('size-btn').click()")
        self.page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}))")
        compact = self.page.evaluate("document.body.classList.contains('compact-cards')")
        assert compact


# ==========================================
#  СКРИНШОТЫ ВКЛАДОК (background.js + view.js)
# ==========================================

class TestTabScreenshots:
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

    def _load_view_in_env(self, tabs=None, screenshots=None):
        """view.js поверх уже загруженного env (local._data до рендера)."""
        pg = self.page
        init_data = ""
        if tabs is not None:
            init_data += f"chrome.storage._data['blattam-tabs'] = {json.dumps(tabs)};\n"
        if screenshots is not None:
            init_data += f"chrome.storage.local._data['blattam-screenshots'] = {json.dumps(screenshots)};\n"
        pg.evaluate(init_data)
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        view_js = load_file("view.js")
        try:
            pg.evaluate(view_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")

    def test_save_current_stores_screenshot_in_local(self):
        """save-current: скриншот в chrome.storage.local 'blattam-screenshots' по id;
        вкладка несёт hasScreenshot (не сам dataUrl)."""
        self._load_env()
        send_msg(self.page, "save-current", name="ShotTab")
        self.page.wait_for_timeout(200)  # capture + canvas downscale (image load) + storage
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1
        assert tabs[0]["hasScreenshot"] is True
        # Вкладка несёт только hasScreenshot — dataUrl не попадает в sync
        assert not any(isinstance(v, str) and v.startswith("data:") for t in tabs for v in t.values())
        shots = json.loads(self.page.evaluate("(async () => { var d = await chrome.storage.local.get('blattam-screenshots'); return JSON.stringify(d['blattam-screenshots'] || {}); })()"))
        assert "mockTab1" in shots
        assert shots["mockTab1"].startswith("data:")

    def test_card_renders_screenshot_image(self):
        """Скриншот в local + вкладка с id → <img> миниатюра вверху карточки."""
        self._load_env()
        self._load_view_in_env(
            tabs=[{"name": "Shot", "url": "https://shot.com", "id": "tabX", "hasScreenshot": True}],
            screenshots={"tabX": "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="}
        )
        self.page.wait_for_timeout(50)
        src = self.page.evaluate("(() => { var img = document.querySelector('.tab-card .tab-screenshot'); return img ? img.src : null; })()")
        assert src is not None and src.startswith("data:image/gif")
        # Миниатюра — ПЕРВЫЙ элемент карточки (above the name)
        first = self.page.evaluate("document.querySelector('.tab-card').firstElementChild.className")
        assert first == "tab-screenshot"

    def test_card_renders_without_screenshot(self):
        """Без скриншота карточка как обычно — <img> нет, пустого места нет."""
        self._load_env()
        self._load_view_in_env(
            tabs=[{"name": "NoShot", "url": "https://noshot.com", "id": "tabY", "hasScreenshot": False}]
        )
        self.page.wait_for_timeout(50)
        has_img = self.page.evaluate("!!document.querySelector('.tab-card .tab-screenshot')")
        assert not has_img
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1

    def test_delete_tab_removes_screenshot(self):
        """Удаление вкладки (✕) чистит её скриншот из 'blattam-screenshots'."""
        self._load_env(confirm=True)
        self._load_view_in_env(
            tabs=[{"name": "Del", "url": "https://del.com", "id": "tabZ", "hasScreenshot": True}],
            screenshots={"tabZ": "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="}
        )
        self.page.wait_for_timeout(50)
        self.page.evaluate("document.querySelector('.tab-card .icon-btn.delete').click()")
        self.page.wait_for_timeout(150)
        shots = json.loads(self.page.evaluate("(async () => { var d = await chrome.storage.local.get('blattam-screenshots'); return JSON.stringify(d['blattam-screenshots'] || {}); })()"))
        assert "tabZ" not in shots
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert tabs == []

    def test_capture_failure_does_not_break_save(self):
        """captureVisibleTab упал → вкладка всё равно сохранена, без скриншота."""
        self._load_env()
        self.page.evaluate("window.__failCapture = true")
        send_msg(self.page, "save-current", name="NoShotTab")
        self.page.wait_for_timeout(100)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1
        assert tabs[0]["name"] == "NoShotTab"
        assert tabs[0]["hasScreenshot"] is False
        shots = json.loads(self.page.evaluate("(async () => { var d = await chrome.storage.local.get('blattam-screenshots'); return JSON.stringify(d['blattam-screenshots'] || {}); })()"))
        assert shots == {}

# ==========================================
#  АВТОСХРАНЕНИЕ ПРИ ЗАКРЫТИИ (архив закрытых)
# ==========================================

class TestAutoArchive:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_env(self, tabs=None, local_data=None, confirm=False):
        pg = self.page
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME)
        init_data = ""
        if tabs is not None:
            init_data += f"chrome.storage._data['blattam-tabs'] = {json.dumps(tabs)};\n"
        if local_data is not None:
            for k, v in local_data.items():
                init_data += f"chrome.storage.local._data[{json.dumps(k)}] = {json.dumps(v)};\n"
        pg.evaluate(init_data)
        pg.evaluate(load_file("background.js") + "; 'loaded'")
        if confirm:
            pg.evaluate("window.confirm = () => true;")

    def _fire_on_removed(self, tab_id, url, title=""):
        """Дёрнуть зарегистрированный chrome.tabs.onRemoved-обработчик."""
        self.page.evaluate(f"""(() => {{
          chrome.tabs.onRemoved._listeners.forEach(fn => fn({json.dumps(tab_id)}, {{id: {json.dumps(tab_id)}, url: {json.dumps(url)}, title: {json.dumps(title)}}}));
        }})()""")
        self.page.wait_for_timeout(150)  # async archive-запись (loadTabs + saveTabs)

    def test_on_removed_saved_url_sets_archived_at(self):
        """Закрыли браузерную вкладку, её URL сохранён → archivedAt ставится,
        folderId/tagIds не трогаются."""
        self._load_env(tabs=[
            {"name": "A", "url": "https://a.com", "folderId": "f1", "tagIds": ["t1"]},
        ])
        self._fire_on_removed(42, "https://a.com")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1
        assert isinstance(tabs[0].get("archivedAt"), int)
        # folderId/tagIds на месте — это не дубль, а та же вкладка в архиве
        assert tabs[0].get("folderId") == "f1"
        assert tabs[0].get("tagIds") == ["t1"]
        assert tabs[0]["name"] == "A"

    def test_on_removed_unsaved_url_noop(self):
        """URL не сохранён — ничего не происходит."""
        self._load_env(tabs=[{"name": "A", "url": "https://a.com"}])
        self._fire_on_removed(42, "https://unsaved.com")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1
        assert tabs[0].get("archivedAt") is None
        # storage не изменился — archivedAt не появился ни у кого
        assert not any("archivedAt" in t for t in tabs)

    def test_double_close_refreshes_archived_at_without_duplicates(self):
        """Повторное закрытие: archivedAt обновляется, дублей не создаётся."""
        self._load_env(tabs=[{"name": "A", "url": "https://a.com"}])
        self._fire_on_removed(1, "https://a.com")
        first = read_storage_raw(self.page, "blattam-tabs")[0]["archivedAt"]
        self.page.wait_for_timeout(20)  # чтобы Date.now() отличался
        self._fire_on_removed(2, "https://a.com")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1  # дублей нет
        assert tabs[0]["archivedAt"] >= first  # обновилось (не уменьшилось)

    def test_view_renders_archived_dimmed_and_unarchive_works(self):
        """В view архивная карточка приглушена (класс archived) + ↩ снимает archivedAt."""
        self._load_env(
            tabs=[
                {"name": "Arch", "url": "https://arch.com", "archivedAt": 1234567890},
                {"name": "Live", "url": "https://live.com"},
            ],
            confirm=True
        )
        pg = self.page
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        view_js = load_file("view.js")
        try:
            pg.evaluate(view_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")
        pg.wait_for_timeout(100)  # async loadData
        # Архивная карточка — с классом archived, живая — нет
        arch_class = pg.evaluate("document.querySelectorAll('.tab-card.archived').length")
        assert arch_class == 1
        # ↩-кнопка есть только на архивной
        unarchive_btns = pg.evaluate("document.querySelectorAll('.tab-card .icon-btn.unarchive').length")
        assert unarchive_btns == 1
        # Клик по ↩ — archivedAt снят
        pg.evaluate("document.querySelector('.tab-card .icon-btn.unarchive').click()")
        pg.wait_for_timeout(150)  # mock unarchive-tab + onChanged
        tabs = read_storage_raw(pg, "blattam-tabs")
        arch_tabs = [t for t in tabs if t["name"] == "Arch"]
        assert len(arch_tabs) == 1 and arch_tabs[0].get("archivedAt") is None
        # После перерисовки карточка больше не приглушена
        assert pg.evaluate("document.querySelectorAll('.tab-card.archived').length") == 0

    def test_archive_filter_chip_toggles(self):
        """Чип «Архив» в шапке: показывает только archivedAt-вкладки, повторный клик снимает."""
        self._load_env(tabs=[
            {"name": "Arch", "url": "https://arch.com", "archivedAt": 1234567890},
            {"name": "Live", "url": "https://live.com"},
        ])
        pg = self.page
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        try:
            pg.evaluate(load_file("view.js") + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")
        pg.wait_for_timeout(100)
        # Без фильтра — обе карточки
        assert pg.evaluate("document.querySelectorAll('.tab-card').length") == 2
        # Клик по «Архив» — только архивная
        pg.evaluate("document.getElementById('archive-chip').click()")
        cards = pg.evaluate("document.querySelectorAll('.tab-card').length")
        names = pg.evaluate("document.querySelector('.tab-card .tab-name').textContent")
        assert cards == 1
        assert names == "Arch"
        # Повторный клик — снимает фильтр
        pg.evaluate("document.getElementById('archive-chip').click()")
        assert pg.evaluate("document.querySelectorAll('.tab-card').length") == 2

    def test_export_import_preserves_archived_at(self):
        """archivedAt — поле вкладки: экспорт/импорт переносит его (verify restore)."""
        self._load_env(tabs=[
            {"name": "Arch", "url": "https://arch.com", "archivedAt": 1234567890},
            {"name": "Live", "url": "https://live.com"},
        ], confirm=True)
        pg = self.page
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        try:
            pg.evaluate(load_file("view.js") + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")
        pg.wait_for_timeout(100)
        # Импорт файла, где archivedAt уже стоит (симуляция: data.tabs уже в allTabs
        # → импортировать как новый URL с archivedAt)
        file_json = json.dumps({
            "tabs": [
                {"name": "NewArch", "url": "https://newarch.com", "archivedAt": 9876543210},
                {"name": "NewLive", "url": "https://newlive.com"},
            ]
        })
        # Мокаем FileReader через direct dispatch: simpler — call import logic with file
        pg.evaluate(f"""(() => {{
          const file = new File([{json.dumps(file_json)}], 'backup.json', {{type: 'application/json'}});
          const input = document.getElementById('import-input');
          const dt = new DataTransfer();
          dt.items.add(file);
          input.files = dt.files;
          input.dispatchEvent(new Event('change', {{bubbles: true}}));
        }})()""")
        pg.wait_for_timeout(300)  # FileReader + storage.set
        tabs = read_storage_raw(pg, "blattam-tabs")
        new_arch = [t for t in tabs if t.get("name") == "NewArch"]
        assert len(new_arch) == 1
        assert new_arch[0].get("archivedAt") == 9876543210  # archivedAt перенесён
        new_live = [t for t in tabs if t.get("name") == "NewLive"]
        assert len(new_live) == 1 and new_live[0].get("archivedAt") is None


# ==========================================
#  СЕССИИ (grouping by named tab sets)
# ==========================================

class TestSessions:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_view(self, tabs=None, folders=None, sessions=None, confirm=True):
        pg = self.page
        init_data = ""
        if tabs is not None:
            init_data += f"chrome.storage._data['blattam-tabs'] = {json.dumps(tabs)};\n"
        if folders is not None:
            init_data += f"chrome.storage._data['blattam-folders'] = {json.dumps(folders)};\n"
        if sessions is not None:
            init_data += f"chrome.storage._data['blattam-sessions'] = {json.dumps(sessions)};\n"
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME + init_data)
        pg.evaluate("window.confirm = () => true;")
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        view_js = load_file("view.js")
        try:
            pg.evaluate(view_js + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")
        pg.wait_for_timeout(100)

    def test_create_session_captures_visible_tabs(self):
        """«+ Сессия» → модалка; OK захватывает ВСЕ видимые вкладки в session.tabUrls.
        Пустое имя → «Сессия ДД.ММ»."""
        self._load_view(tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
            {"name": "C", "url": "https://c.com"},
        ])
        pg = self.page
        pg.locator("#add-session-btn").click()
        assert pg.evaluate("document.getElementById('session-modal').classList.contains('open')")
        # Пустое имя → default «Сессия ДД.ММ»
        pg.locator("#session-modal-confirm").click()
        pg.wait_for_timeout(100)  # storage.set + re-render
        sessions = read_storage_raw(pg, "blattam-sessions")
        assert len(sessions) == 1
        s = sessions[0]
        assert s["name"].startswith("Сессия ")  # default name
        assert "Сессия " + pg.evaluate("""(() => {
          const d = new Date();
          return String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0');
        })()""") == s["name"]
        assert set(s["tabUrls"]) == {"https://a.com", "https://b.com", "https://c.com"}
        assert isinstance(s.get("createdAt"), int)
        # Чип сессии отрендерился
        chips = pg.evaluate("document.querySelectorAll('.session-chip[data-session-id]').length")
        assert chips == 1

    def test_session_chips_render(self):
        self._load_view(
            tabs=[{"name": "A", "url": "https://a.com"}],
            sessions=[
                {"id": "s1", "name": "Work", "createdAt": 1000, "tabUrls": ["https://a.com"]},
                {"id": "s2", "name": "Personal", "createdAt": 2000, "tabUrls": []},
            ]
        )
        chips = self.page.evaluate("document.querySelectorAll('.session-chip[data-session-id]').length")
        assert chips == 2
        names = json.loads(self.page.evaluate("""JSON.stringify(
          [...document.querySelectorAll('.session-chip .chip-name')].map(e => e.textContent)
        )"""))
        assert names == ["Work", "Personal"]

    def test_click_session_chip_filters_view(self):
        self._load_view(
            tabs=[
                {"name": "In", "url": "https://in.com"},
                {"name": "Out", "url": "https://out.com"},
            ],
            sessions=[{"id": "s1", "name": "Work", "createdAt": 1000, "tabUrls": ["https://in.com"]}]
        )
        pg = self.page
        assert pg.evaluate("document.querySelectorAll('.tab-card').length") == 2
        pg.evaluate("document.querySelector('.session-chip[data-session-id=\"s1\"]').click()")
        cards = pg.evaluate("document.querySelectorAll('.tab-card').length")
        name = pg.evaluate("document.querySelector('.tab-card .tab-name').textContent")
        assert cards == 1
        assert name == "In"
        # Повторный клик снимает фильтр
        pg.evaluate("document.querySelector('.session-chip[data-session-id=\"s1\"]').click()")
        assert pg.evaluate("document.querySelectorAll('.tab-card').length") == 2

    def test_session_filter_combines_with_folder_and_search(self):
        fid = "f1"
        self._load_view(
            tabs=[
                {"name": "Work In Session", "url": "https://w1.com", "folderId": fid},
                {"name": "Work Out Session", "url": "https://w2.com", "folderId": fid},
                {"name": "Free In Session", "url": "https://f1s.com", "folderId": None},
            ],
            folders=[{"id": fid, "name": "Work"}],
            sessions=[{"id": "s1", "name": "Work", "createdAt": 1000, "tabUrls": ["https://w1.com", "https://f1s.com"]}]
        )
        pg = self.page
        pg.evaluate(f'document.querySelector(\'[data-folder-id="{fid}"]\').click()')
        pg.evaluate("document.querySelector('.session-chip[data-session-id=\"s1\"]').click()")
        cards = pg.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1  # только Work In Session
        # Поиск сверху сужает (ничего не найдено)
        pg.locator("#search").fill("nope")
        assert pg.evaluate("document.querySelectorAll('.tab-card').length") == 0

    def test_add_visible_to_session(self):
        """«+» на чипе сессии добавляет currently visible tabs к session.tabUrls (без дублей)."""
        self._load_view(
            tabs=[
                {"name": "In", "url": "https://in.com"},
                {"name": "Out", "url": "https://out.com"},
            ],
            sessions=[{"id": "s1", "name": "Work", "createdAt": 1000, "tabUrls": ["https://in.com"]}]
        )
        pg = self.page
        # Фильтруем так, чтобы только «In» был видимым
        pg.evaluate("document.querySelector('.session-chip[data-session-id=\"s1\"]').click()")
        # Теперь «+» — добавит видимые (just In, already there) → no change
        pg.evaluate("document.querySelector('.session-chip .chip-icon-btn[title=\"Добавить видимые вкладки в сессию\"]').click()")
        pg.wait_for_timeout(100)
        # Сбрасываем фильтр, «Out» видим, add → both
        pg.evaluate("document.querySelector('.session-chip[data-session-id=\"s1\"]').click()")
        pg.evaluate("document.querySelector('.session-chip .chip-icon-btn[title=\"Добавить видимые вкладки в сессию\"]').click()")
        pg.wait_for_timeout(100)
        sessions = read_storage_raw(pg, "blattam-sessions")
        assert set(sessions[0]["tabUrls"]) == {"https://in.com", "https://out.com"}

    def test_delete_session_with_confirm(self):
        self._load_view(
            tabs=[{"name": "A", "url": "https://a.com"}],
            sessions=[
                {"id": "s1", "name": "Work", "createdAt": 1000, "tabUrls": ["https://a.com"]},
                {"id": "s2", "name": "Keep", "createdAt": 2000, "tabUrls": []},
            ]
        )
        pg = self.page
        # Удалить s1 (first chip's ✕)
        pg.evaluate("document.querySelectorAll('.session-chip')[0].querySelector('.chip-icon-btn[title=\"Удалить сессию\"]').click()")
        pg.wait_for_timeout(100)
        sessions = read_storage_raw(pg, "blattam-sessions")
        assert len(sessions) == 1
        assert sessions[0]["id"] == "s2"
        # Chip count matches
        chips = pg.evaluate("document.querySelectorAll('.session-chip[data-session-id]').length")
        assert chips == 1


# ==========================================
#  РЕКОМЕНДАЦИИ (Частые / Избранные + stats)
# ==========================================

class TestRecommendations:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_env(self, tabs=None, stats=None, confirm=False):
        pg = self.page
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME)
        init_data = ""
        if tabs is not None:
            init_data += f"chrome.storage._data['blattam-tabs'] = {json.dumps(tabs)};\n"
        if stats is not None:
            init_data += f"chrome.storage.local._data['blattam-stats'] = {json.dumps(stats)};\n"
        pg.evaluate(init_data)
        pg.evaluate(load_file("background.js") + "; 'loaded'")
        if confirm:
            pg.evaluate("window.confirm = () => true;")

    def _load_view(self, tabs=None, stats=None):
        self._load_env(tabs=tabs, stats=stats)
        pg = self.page
        pg.evaluate(f"document.body.innerHTML = `{VIEW_DOM}`")
        try:
            pg.evaluate(load_file("view.js") + "; 'loaded'")
        except Exception as e:
            pytest.fail(f"View.js error: {e}")
        pg.wait_for_timeout(100)

    def test_opening_saved_tab_increments_stats(self):
        """Клик по карточке в view → background получает open-one → 'blattam-stats' opens +1, lastOpened set."""
        self._load_view(tabs=[{"name": "A", "url": "https://a.com"}])
        pg = self.page
        # Клик по имени (with 300ms open delay)
        pg.evaluate("document.querySelector('.tab-name').click()")
        pg.wait_for_timeout(400)
        stats = json.loads(pg.evaluate("""(async () => {
          var d = await chrome.storage.local.get('blattam-stats');
          return JSON.stringify(d['blattam-stats'] || {});
        })()"""))
        assert "https://a.com" in stats
        assert stats["https://a.com"]["opens"] == 1
        assert isinstance(stats["https://a.com"]["lastOpened"], int)
        # Повторное открытие → 2
        pg.evaluate("document.querySelector('.tab-name').click()")
        pg.wait_for_timeout(400)
        stats = json.loads(pg.evaluate("""(async () => {
          var d = await chrome.storage.local.get('blattam-stats');
          return JSON.stringify(d['blattam-stats'] || {});
        })()"""))
        assert stats["https://a.com"]["opens"] == 2

    def test_background_open_action_increments_stats(self):
        """background 'open' (by index) тоже идёт через createTabFromSaved → stats."""
        self._load_env(tabs=[{"name": "A", "url": "https://a.com"}])
        send_msg(self.page, "open", index=0)
        self.page.wait_for_timeout(150)
        stats = json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.local.get('blattam-stats');
          return JSON.stringify(d['blattam-stats'] || {});
        })()"""))
        assert stats["https://a.com"]["opens"] == 1

    def test_frequent_filter_shows_top_urls_with_opens_gte_2(self):
        self._load_view(
            tabs=[
                {"name": "Hot", "url": "https://hot.com"},
                {"name": "Cold", "url": "https://cold.com"},
                {"name": "Mid", "url": "https://mid.com"},
            ],
            stats={
                "https://hot.com": {"opens": 10, "lastOpened": 1000},
                "https://mid.com": {"opens": 2, "lastOpened": 1000},
                "https://cold.com": {"opens": 1, "lastOpened": 1000},
            }
        )
        pg = self.page
        assert pg.evaluate("document.querySelectorAll('.tab-card').length") == 3
        pg.evaluate("document.getElementById('frequent-chip').click()")
        pg.wait_for_timeout(100)  # withFreshStats async
        cards = pg.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 2  # только opens >= 2
        names = set(json.loads(pg.evaluate("""JSON.stringify(
          [...document.querySelectorAll('.tab-card .tab-name')].map(e => e.textContent)
        )""")))
        assert names == {"Hot", "Mid"}  # Cold (opens=1) исключён
        # Повторный клик снимает
        pg.evaluate("document.getElementById('frequent-chip').click()")
        pg.wait_for_timeout(100)
        assert pg.evaluate("document.querySelectorAll('.tab-card').length") == 3

    def test_favorites_filter_shows_recent_top10(self):
        import time
        self._load_view(
            tabs=[
                {"name": "Recent", "url": "https://recent.com"},
                {"name": "Old", "url": "https://old.com"},
            ],
            stats={
                # recent: в пределах 7 дней; old: старше 7 дней
                "https://recent.com": {"opens": 1, "lastOpened": int(time.time() * 1000)},
                "https://old.com": {"opens": 50, "lastOpened": 1000},  # давно (1970)
            }
        )
        pg = self.page
        pg.evaluate("document.getElementById('favorites-chip').click()")
        pg.wait_for_timeout(100)
        cards = pg.evaluate("document.querySelectorAll('.tab-card').length")
        name = pg.evaluate("document.querySelector('.tab-card .tab-name').textContent")
        assert cards == 1
        assert name == "Recent"  # Old старше 7 дней — не в favorites

    def test_stats_pruned_to_500_by_last_opened(self):
        """'blattam-stats' не превышает 500 URL: при записи самые старые lastOpened вырезаются."""
        pg = self.page
        # Сгенерируем 501 URL в stats, lastOpened различный
        stats = {}
        for i in range(501):
            stats[f"https://u{i}.com"] = {"opens": 1, "lastOpened": i + 1}  # i+1 → 1..501
        self._load_view(tabs=[], stats=stats)
        # Открываем ещё одну вкладку → recordOpen → prune до 500 (mock прунит сам)
        pg.evaluate("""(() => {
          chrome.__bgRecordOpen('https://new.com');
        })()""")
        stats_after = json.loads(pg.evaluate("""(async () => {
          var d = await chrome.storage.local.get('blattam-stats');
          return JSON.stringify(d['blattam-stats'] || {});
        })()"""))
        assert len(stats_after) == 500
        # Самая старая (lastOpened=1) вырезана, самая новая (lastOpened=501) и new.com остались
        assert "https://u0.com" not in stats_after  # lastOpened=1 (oldest)
        assert "https://u500.com" in stats_after  # lastOpened=501 (newest old)
        assert "https://new.com" in stats_after  # new open


# ==========================================
#  RELEASE TESTS (zip для Chrome Web Store, иконки, описание магазина)
# ==========================================

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
#  END OF NEW FEATURE TESTS
# ==========================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

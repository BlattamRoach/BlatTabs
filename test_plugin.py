r"""
BlattamToby тесты через Playwright.
Мокируем Chrome API; проверяем background.js, view.js, popup.js +
пространства (spaces) и сворачиваемые группы (groups), миграцию legacy-папок.

Запуск: PYTHONDONTWRITEBYTECODE=1 C:\Python314\python.exe test_plugin.py
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
var mockSeq = 100;
var chrome = {
  storage: {
    _data: {},
    _fire: function(changeInfo, area) {
      if (window.__storageListeners && window.__storageListeners.length) {
        for (var fn of window.__storageListeners) fn(changeInfo, area);
      }
    },
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
      var changeInfo = {};
      for (var k in data) {
        changeInfo[k] = { newValue: data[k], oldValue: this._data[k] };
      }
      Object.assign(this._data, data);
      this._fire(changeInfo, 'sync');
      if (callback) callback();
      return Promise.resolve();
    },
    remove: function(keys, callback) {
      var arr = Array.isArray(keys) ? keys : [keys];
      var self = this;
      var changeInfo = {};
      arr.forEach(function(k) {
        if (self._data[k] !== undefined) changeInfo[k] = { oldValue: self._data[k] };
        delete self._data[k];
      });
      this._fire(changeInfo, 'sync');
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
    sendMessage: function(msg, callback) {
      this.messagesSent.push(msg);
      window.lastMessage = msg;
      var response = undefined;

      // rename-tab: применяем к storage и шлём onChanged (как делает background)
      if (msg.action === 'rename-tab') {
        var tabs = chrome.storage._data['blattam-tabs'] || [];
        if (tabs[msg.index] && (msg.name || '').trim()) {
          tabs[msg.index].name = String(msg.name).trim();
          var oldVal = chrome.storage._data['blattam-tabs'];
          chrome.storage._data['blattam-tabs'] = tabs;
          chrome.storage._fire({ 'blattam-tabs': { newValue: tabs, oldValue: oldVal } }, 'sync');
        }
      }
      // move-tab: применяем spaceId/groupId (как делает background)
      if (msg.action === 'move-tab') {
        var tabs2 = chrome.storage._data['blattam-tabs'] || [];
        if (tabs2[msg.index]) {
          if (msg.spaceId !== undefined) { tabs2[msg.index].spaceId = msg.spaceId; tabs2[msg.index].groupId = null; }
          if (msg.groupId !== undefined) tabs2[msg.index].groupId = msg.groupId;
          var oldVal2 = chrome.storage._data['blattam-tabs'];
          chrome.storage._data['blattam-tabs'] = tabs2;
          chrome.storage._fire({ 'blattam-tabs': { newValue: tabs2, oldValue: oldVal2 } }, 'sync');
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
          chrome.storage._fire({ 'blattam-tabs': { newValue: tabs3, oldValue: oldVal3 } }, 'sync');
        }
      }
      // open-one / open-many: создаёт browser-tab(s) (как background.js)
      if (msg.action === 'open-one') {
        chrome.tabs.create({ url: msg.url, active: true });
      }
      if (msg.action === 'open-many') {
        (msg.urls || []).forEach(function(url) { chrome.tabs.create({ url: url, active: false }); });
      }
      // create-space: плоское пространство; пустое имя → «Пространство N»; дубль → нет ответа
      if (msg.action === 'create-space') {
        var sps = chrome.storage._data['blattam-spaces'];
        if (!Array.isArray(sps)) { sps = []; chrome.storage._data['blattam-spaces'] = sps; }
        var nm = String(msg.name || '').trim();
        if (!nm) nm = 'Пространство ' + (sps.length + 1);
        if (!sps.some(function(s) { return s.name.toLowerCase() === nm.toLowerCase(); })) {
          var newsp = { id: 'spmock' + (++mockSeq), name: nm };
          sps.push(newsp);
          chrome.storage._fire({ 'blattam-spaces': { newValue: sps, oldValue: null } }, 'sync');
          response = newsp;
        }
      }
      // delete-space: удаляем, вкладки → первое оставшееся (или новое «Мои вкладки»), группы — удаляем
      if (msg.action === 'delete-space') {
        var sps2 = chrome.storage._data['blattam-spaces'];
        if (Array.isArray(sps2) && sps2.some(function(s) { return s.id === msg.id; })) {
          var remaining = sps2.filter(function(s) { return s.id !== msg.id; });
          var target = remaining[0] || null;
          if (!target) { target = { id: 'spmock' + (++mockSeq), name: 'Мои вкладки' }; remaining = [target]; }
          var tabsD = chrome.storage._data['blattam-tabs'] || [];
          tabsD.forEach(function(t) { if (t && t.spaceId === msg.id) t.spaceId = target.id; });
          var gsD = chrome.storage._data['blattam-groups'] || [];
          var gsKept = gsD.filter(function(g) { return g.spaceId !== msg.id; });
          chrome.storage._data['blattam-spaces'] = remaining;
          chrome.storage._data['blattam-tabs'] = tabsD;
          chrome.storage._data['blattam-groups'] = gsKept;
          chrome.storage._fire({
            'blattam-spaces': { newValue: remaining, oldValue: sps2 },
            'blattam-tabs': { newValue: tabsD, oldValue: null },
            'blattam-groups': { newValue: gsKept, oldValue: gsD }
          }, 'sync');
          response = true;
        }
      }
      // rename-space
      if (msg.action === 'rename-space') {
        var sps4 = chrome.storage._data['blattam-spaces'];
        if (Array.isArray(sps4)) {
          var spR = null;
          for (var i4 = 0; i4 < sps4.length; i4++) if (sps4[i4].id === msg.id) spR = sps4[i4];
          var nmR = String(msg.name || '').trim();
          var clash = spR && sps4.some(function(s) { return s !== spR && s.name.toLowerCase() === nmR.toLowerCase(); });
          if (spR && nmR && !clash) {
            spR.name = nmR;
            chrome.storage._fire({ 'blattam-spaces': { newValue: sps4, oldValue: null } }, 'sync');
            response = true;
          }
        }
      }
      // create-group: группа в пространстве; пустое имя → «Группа N»
      if (msg.action === 'create-group') {
        var sps3 = chrome.storage._data['blattam-spaces'] || [];
        if (sps3.some(function(s) { return s.id === msg.spaceId; })) {
          var gs2 = chrome.storage._data['blattam-groups'];
          if (!Array.isArray(gs2)) { gs2 = []; chrome.storage._data['blattam-groups'] = gs2; }
          var gn = String(msg.name || '').trim();
          if (!gn) gn = 'Группа ' + (gs2.length + 1);
          var ng = { id: 'gmock' + (++mockSeq), name: gn, spaceId: msg.spaceId, collapsed: false };
          gs2.push(ng);
          chrome.storage._fire({ 'blattam-groups': { newValue: gs2, oldValue: null } }, 'sync');
          response = ng;
        }
      }
      // delete-group: удаляем группу; её вкладки остаются в пространстве (groupId → null)
      if (msg.action === 'delete-group') {
        var gs3 = chrome.storage._data['blattam-groups'];
        if (Array.isArray(gs3) && gs3.some(function(g) { return g.id === msg.id; })) {
          var gsNew = gs3.filter(function(g) { return g.id !== msg.id; });
          var tabsG = chrome.storage._data['blattam-tabs'] || [];
          tabsG.forEach(function(t) { if (t && t.groupId === msg.id) t.groupId = null; });
          chrome.storage._data['blattam-groups'] = gsNew;
          chrome.storage._data['blattam-tabs'] = tabsG;
          chrome.storage._fire({
            'blattam-groups': { newValue: gsNew, oldValue: gs3 },
            'blattam-tabs': { newValue: tabsG, oldValue: null }
          }, 'sync');
          response = true;
        }
      }

      if (callback) callback(response);
      return Promise.resolve(response);
    },
    getManifest: function() { return { version: '1.0.0' }; }
  }
};

// Patch chrome.storage.sync → chrome.storage._data
Object.defineProperty(chrome.storage, 'sync', { value: { _data: chrome.storage._data } });
chrome.storage.sync.get = function(keys, cb) { return chrome.storage.get(keys, cb); };
chrome.storage.sync.set = function(data, cb) { return chrome.storage.set(data, cb); };
chrome.storage.sync.remove = function(keys, cb) { return chrome.storage.remove(keys, cb); };

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


def read_storage_raw(page, key):
    """Read storage returning proper type."""
    result = page.evaluate(f"(async () => {{ var d = await chrome.storage.get('{key}'); if (d['{key}'] === undefined || d['{key}'] === null) return '[]'; return JSON.stringify(d['{key}']); }})()")
    parsed = json.loads(result)
    return parsed if parsed is not None else []


def load_file(name):
    with open(f"{EXT_PATH}/{name}", "r", encoding="utf-8") as f:
        return f.read()


# === Хелперы (spaces / groups) ===

def call_msg(page, action, **kwargs):
    """Сообщение обработчику background.js с возвратом ответа (async-действия)."""
    msg = {"action": action}
    msg.update(kwargs)
    return page.evaluate(f"""(async () => {{
      var fn = window._onMessageHandler;
      if (!fn) return null;
      return await fn({json.dumps(msg, ensure_ascii=False)}, null, function(){{}});
    }})()""")


def read_local(page, key):
    return page.evaluate(f"chrome.storage.local._data['{key}']")


def body_dom(html_name):
    """innerHTML <body> из view.html / popup.html (без <script src>)."""
    html = load_file(html_name)
    start = html.index("<body>") + len("<body>")
    end = html.rindex("</body>")
    body = html[start:end]
    for script in ('<script src="view.js"></script>', '<script src="popup.js"></script>'):
        body = body.replace(script, "")
    return body


VIEW_DOM = body_dom("view.html")
POPUP_DOM = body_dom("popup.html")


def load_view(pg, tabs=None, spaces=None, groups=None, folders=None,
              last_space=None, theme=None, confirm=False):
    """about:blank + mock + данные + DOM view.html + view.js."""
    init = []
    if tabs is not None:
        init.append("chrome.storage._data['blattam-tabs'] = " + json.dumps(tabs, ensure_ascii=False) + ";")
    if spaces is not None:
        init.append("chrome.storage._data['blattam-spaces'] = " + json.dumps(spaces, ensure_ascii=False) + ";")
    if groups is not None:
        init.append("chrome.storage._data['blattam-groups'] = " + json.dumps(groups, ensure_ascii=False) + ";")
    if folders is not None:
        init.append("chrome.storage._data['blattam-folders'] = " + json.dumps(folders, ensure_ascii=False) + ";")
    if last_space is not None:
        init.append("chrome.storage._data['blattam-last-space'] = " + json.dumps(last_space) + ";")
    if theme is not None:
        init.append("chrome.storage.local._data['blattam-theme'] = " + json.dumps(theme) + ";")
    if confirm:
        init.append("window.confirm = () => true;")
    pg.goto("about:blank")
    pg.evaluate(MOCK_CHROME + "\n".join(init))
    pg.evaluate("document.body.innerHTML = " + json.dumps(VIEW_DOM))
    try:
        pg.evaluate(load_file("view.js") + "; 'loaded'")
    except Exception as e:
        pytest.fail(f"View.js error: {e}")


def load_popup(pg, spaces=None, last_space=None, confirm=False):
    """about:blank + mock + данные + DOM popup.html + popup.js."""
    init = []
    if spaces is not None:
        init.append("chrome.storage._data['blattam-spaces'] = " + json.dumps(spaces, ensure_ascii=False) + ";")
    if last_space is not None:
        init.append("chrome.storage._data['blattam-last-space'] = " + json.dumps(last_space) + ";")
    if confirm:
        init.append("window.confirm = () => true;")
    pg.goto("about:blank")
    pg.evaluate(MOCK_CHROME + "\n".join(init))
    pg.evaluate("document.body.innerHTML = " + json.dumps(POPUP_DOM))
    try:
        pg.evaluate(load_file("popup.js") + "; 'loaded'")
    except Exception as e:
        pytest.fail(f"Popup.js error: {e}")


# ==========================================
#  MANIFEST TESTS (без браузера)
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
#  BACKGROUND.JS: ВКЛАДКИ
# ==========================================

class TestBackgroundTabs:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        page.goto("about:blank")
        page.evaluate(MOCK_CHROME)
        page.evaluate(load_file("background.js") + "; 'loaded'")

    def _spaces(self):
        return read_storage_raw(self.page, "blattam-spaces")

    def _tabs(self):
        return read_storage_raw(self.page, "blattam-tabs")

    def _first_space_id(self):
        sps = self._spaces()
        assert len(sps) >= 1
        return sps[0]["id"]

    def test_default_space_created_on_load(self):
        """Свежий запуск: создаётся пространство «Мои вкладки»."""
        sps = self._spaces()
        assert len(sps) == 1
        assert sps[0]["name"] == "Мои вкладки"

    def test_save_current_tab_default_space(self):
        send_msg(self.page, "save-current", name="Test Tab")
        tabs = self._tabs()
        assert len(tabs) == 1
        assert tabs[0]["name"] == "Test Tab"
        assert tabs[0]["spaceId"] == self._first_space_id()
        assert "groupId" not in tabs[0]

    def test_save_current_tab_with_space_id(self):
        sp = call_msg(self.page, "create-space", name="Work")
        assert sp and sp.get("id")
        send_msg(self.page, "save-current", name="InWork", spaceId=sp["id"])
        tabs = self._tabs()
        assert len(tabs) == 1
        assert tabs[0]["spaceId"] == sp["id"]

    def test_save_current_skips_chrome_url(self):
        self.page.evaluate("chrome.tabs._currentTab.url = 'chrome://settings'")
        send_msg(self.page, "save-current", name="Settings")
        assert self._tabs() == []

    def test_save_current_no_name_defaults(self):
        send_msg(self.page, "save-current")
        tabs = self._tabs()
        assert len(tabs) == 1
        assert tabs[0]["name"] == "Без имени"

    def test_add_tab_default_space(self):
        send_msg(self.page, "add-tab", name="Google", url="https://google.com")
        tabs = self._tabs()
        assert len(tabs) == 1
        assert tabs[0]["spaceId"] == self._first_space_id()

    def test_add_tab_duplicate_same_space_skipped(self):
        send_msg(self.page, "add-tab", name="First", url="https://dup.com")
        send_msg(self.page, "add-tab", name="Second", url="https://dup.com")
        tabs = [t for t in self._tabs() if t["url"] == "https://dup.com"]
        assert len(tabs) == 1

    def test_add_tab_same_url_other_space_allowed(self):
        sp2 = call_msg(self.page, "create-space", name="Work")
        send_msg(self.page, "add-tab", name="InMain", url="https://same.com")
        send_msg(self.page, "add-tab", name="InWork", url="https://same.com", spaceId=sp2["id"])
        tabs = self._tabs()
        assert len(tabs) == 2
        urls_by_space = {(t["spaceId"], t["url"]) for t in tabs}
        assert (sp2["id"], "https://same.com") in urls_by_space

    def test_open_tab_creates_browser_tab(self):
        send_msg(self.page, "add-tab", name="OpenMe", url="https://open.me")
        send_msg(self.page, "open", index=0)
        assert self.page.evaluate("chrome.tabs.createdTabs.length") == 1

    def test_open_one(self):
        send_msg(self.page, "open-one", url="https://one.example")
        created = json.loads(self.page.evaluate("JSON.stringify(chrome.tabs.createdTabs)"))
        assert len(created) == 1
        assert created[0]["url"] == "https://one.example"
        assert created[0]["active"] is True

    def test_open_many(self):
        send_msg(self.page, "open-many", urls=["https://a.com", "https://b.com", "https://c.com"])
        created = json.loads(self.page.evaluate("JSON.stringify(chrome.tabs.createdTabs)"))
        assert len(created) == 3
        assert all(c["active"] is False for c in created)

    def test_open_many_no_urls_noop(self):
        send_msg(self.page, "open-many", urls=[])
        assert self.page.evaluate("chrome.tabs.createdTabs.length") == 0

    def test_delete_tab(self):
        send_msg(self.page, "add-tab", name="ToDelete", url="https://delete.me")
        send_msg(self.page, "delete", index=0)
        assert not any(t["name"] == "ToDelete" for t in self._tabs())

    def test_rename_tab(self):
        send_msg(self.page, "add-tab", name="Before", url="https://rename.me")
        send_msg(self.page, "rename-tab", index=0, name="After")
        tabs = [t for t in self._tabs() if t["url"] == "https://rename.me"]
        assert len(tabs) == 1 and tabs[0]["name"] == "After"

    def test_rename_tab_trims(self):
        send_msg(self.page, "add-tab", name="Trim", url="https://trim.com")
        send_msg(self.page, "rename-tab", index=0, name="  Padded  ")
        tabs = [t for t in self._tabs() if t["url"] == "https://trim.com"]
        assert tabs[0]["name"] == "Padded"


# ==========================================
#  BACKGROUND.JS: ПРОСТРАНСТВА
# ==========================================

class TestBackgroundSpaces:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        page.goto("about:blank")
        page.evaluate(MOCK_CHROME)
        page.evaluate(load_file("background.js") + "; 'loaded'")

    def _spaces(self):
        return read_storage_raw(self.page, "blattam-spaces")

    def test_create_space_named(self):
        sp = call_msg(self.page, "create-space", name="Work")
        assert sp is not None and sp.get("id") and sp["name"] == "Work"
        names = [s["name"] for s in self._spaces()]
        assert names == ["Мои вкладки", "Work"]

    def test_create_space_trims_name(self):
        sp = call_msg(self.page, "create-space", name="  Work  ")
        assert sp["name"] == "Work"

    def test_create_space_empty_autoname(self):
        sp = call_msg(self.page, "create-space", name="")
        assert sp["name"] == "Пространство 2"

    def test_create_space_autoname_skips_taken(self):
        call_msg(self.page, "create-space", name="Пространство 2")
        sp = call_msg(self.page, "create-space", name="")
        assert sp["name"] == "Пространство 3"

    def test_create_space_duplicate_case_insensitive(self):
        r1 = call_msg(self.page, "create-space", name="Work")
        assert r1 is not None
        r2 = call_msg(self.page, "create-space", name="WORK")
        assert r2 is None
        assert len(self._spaces()) == 2

    def test_delete_space_moves_tabs_to_first_remaining(self):
        b = call_msg(self.page, "create-space", name="B")
        c = call_msg(self.page, "create-space", name="C")
        default = self._spaces()[0]["id"]
        send_msg(self.page, "add-tab", name="InA", url="https://a.com")
        send_msg(self.page, "add-tab", name="InB1", url="https://b1.com", spaceId=b["id"])
        send_msg(self.page, "add-tab", name="InB2", url="https://b2.com", spaceId=b["id"])
        send_msg(self.page, "add-tab", name="InC", url="https://c.com", spaceId=c["id"])

        res = call_msg(self.page, "delete-space", id=b["id"])
        assert res is True

        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 4
        in_b = [t for t in tabs if t["name"] in ("InB1", "InB2")]
        assert all(t["spaceId"] == default for t in in_b)  # → первое оставшееся
        in_c = [t for t in tabs if t["name"] == "InC"][0]
        assert in_c["spaceId"] == c["id"]  # чужое пространство не тронуто
        assert all(s["id"] != b["id"] for s in self._spaces())

    def test_delete_space_last_creates_default(self):
        only = self._spaces()[0]
        send_msg(self.page, "add-tab", name="Lonely", url="https://lonely.com")
        call_msg(self.page, "delete-space", id=only["id"])
        sps = self._spaces()
        assert len(sps) == 1
        assert sps[0]["name"] == "Мои вкладки"
        assert sps[0]["id"] != only["id"]
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1 and tabs[0]["spaceId"] == sps[0]["id"]

    def test_delete_space_removes_groups(self):
        a = self._spaces()[0]
        b = call_msg(self.page, "create-space", name="B")
        ga = call_msg(self.page, "create-group", spaceId=a["id"], name="G-A")
        gb = call_msg(self.page, "create-group", spaceId=b["id"], name="G-B")
        call_msg(self.page, "delete-space", id=b["id"])
        groups = read_storage_raw(self.page, "blattam-groups")
        assert [g["id"] for g in groups] == [ga["id"]]

    def test_delete_space_updates_last_space(self):
        b = call_msg(self.page, "create-space", name="B")
        self.page.evaluate("chrome.storage._data['blattam-last-space'] = '" + b["id"] + "';")
        call_msg(self.page, "delete-space", id=b["id"])
        assert read_storage_raw(self.page, "blattam-last-space") == self._spaces()[0]["id"]

    def test_delete_space_keeps_other_last_space(self):
        a = self._spaces()[0]
        b = call_msg(self.page, "create-space", name="B")
        self.page.evaluate("chrome.storage._data['blattam-last-space'] = '" + a["id"] + "';")
        call_msg(self.page, "delete-space", id=b["id"])
        assert read_storage_raw(self.page, "blattam-last-space") == a["id"]

    def test_rename_space(self):
        a = self._spaces()[0]
        call_msg(self.page, "rename-space", id=a["id"], name="Main")
        sps = [s for s in self._spaces() if s["id"] == a["id"]]
        assert len(sps) == 1 and sps[0]["name"] == "Main"

    def test_rename_space_duplicate_noop(self):
        a = self._spaces()[0]
        b = call_msg(self.page, "create-space", name="B")
        call_msg(self.page, "rename-space", id=b["id"], name=a["name"].upper())
        names = [s["name"] for s in self._spaces()]
        assert names.count("Мои вкладки") == 1 and a["name"].upper() not in names

    def test_rename_space_empty_noop(self):
        a = self._spaces()[0]
        call_msg(self.page, "rename-space", id=a["id"], name="   ")
        sps = [s for s in self._spaces() if s["id"] == a["id"]]
        assert sps[0]["name"] == "Мои вкладки"

    def test_save_uses_last_space(self):
        b = call_msg(self.page, "create-space", name="B")
        self.page.evaluate("chrome.storage._data['blattam-last-space'] = '" + b["id"] + "';")
        send_msg(self.page, "save-current", name="Last")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1 and tabs[0]["spaceId"] == b["id"]

    def test_save_last_space_invalid_falls_back_first(self):
        self.page.evaluate("chrome.storage._data['blattam-last-space'] = 'junk-id';")
        send_msg(self.page, "save-current", name="Fallback")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1 and tabs[0]["spaceId"] == self._spaces()[0]["id"]


# ==========================================
#  BACKGROUND.JS: ГРУППЫ + MOVE/REORDER
# ==========================================

class TestBackgroundGroups:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        page.goto("about:blank")
        page.evaluate(MOCK_CHROME)
        page.evaluate(load_file("background.js") + "; 'loaded'")

    def _spaces(self):
        return read_storage_raw(self.page, "blattam-spaces")

    def _tabs(self):
        return read_storage_raw(self.page, "blattam-tabs")

    def _groups(self):
        return read_storage_raw(self.page, "blattam-groups")

    def test_create_group(self):
        sp = self._spaces()[0]
        g = call_msg(self.page, "create-group", spaceId=sp["id"], name="Dev")
        assert g is not None and g["name"] == "Dev"
        assert g["spaceId"] == sp["id"]
        assert g["collapsed"] is False

    def test_create_group_empty_autoname(self):
        sp = self._spaces()[0]
        g = call_msg(self.page, "create-group", spaceId=sp["id"], name="")
        assert g["name"] == "Группа 1"

    def test_create_group_autoname_skips_taken(self):
        sp = self._spaces()[0]
        call_msg(self.page, "create-group", spaceId=sp["id"], name="Группа 1")
        g = call_msg(self.page, "create-group", spaceId=sp["id"], name="")
        assert g["name"] == "Группа 2"

    def test_create_group_invalid_space_null(self):
        g = call_msg(self.page, "create-group", spaceId="nope", name="Dev")
        assert g is None
        assert self._groups() == []

    def test_delete_group_tabs_stay_in_space(self):
        sp = self._spaces()[0]
        g = call_msg(self.page, "create-group", spaceId=sp["id"], name="Dev")
        send_msg(self.page, "add-tab", name="InG", url="https://ing.com", spaceId=sp["id"])
        idx = [i for i, t in enumerate(self._tabs()) if t["name"] == "InG"][0]
        send_msg(self.page, "move-tab", index=idx, groupId=g["id"])
        call_msg(self.page, "delete-group", id=g["id"])
        tabs = self._tabs()
        assert len(tabs) == 1
        assert tabs[0]["spaceId"] == sp["id"]
        assert tabs[0]["groupId"] is None
        assert self._groups() == []

    def test_move_tab_to_space_clears_group(self):
        sp1 = self._spaces()[0]
        sp2 = call_msg(self.page, "create-space", name="B")
        g = call_msg(self.page, "create-group", spaceId=sp1["id"], name="Dev")
        send_msg(self.page, "add-tab", name="T", url="https://t.com", spaceId=sp1["id"])
        idx = [i for i, t in enumerate(self._tabs()) if t["name"] == "T"][0]
        send_msg(self.page, "move-tab", index=idx, groupId=g["id"])
        send_msg(self.page, "move-tab", index=idx, spaceId=sp2["id"])
        tabs = self._tabs()
        assert tabs[0]["spaceId"] == sp2["id"]
        assert tabs[0]["groupId"] is None  # между пространствами группы не ездят

    def test_move_tab_to_group(self):
        sp = self._spaces()[0]
        g = call_msg(self.page, "create-group", spaceId=sp["id"], name="Dev")
        send_msg(self.page, "add-tab", name="T", url="https://t.com")
        send_msg(self.page, "move-tab", index=0, groupId=g["id"])
        assert self._tabs()[0]["groupId"] == g["id"]

    def test_move_tab_group_null(self):
        sp = self._spaces()[0]
        g = call_msg(self.page, "create-group", spaceId=sp["id"], name="Dev")
        send_msg(self.page, "add-tab", name="T", url="https://t.com")
        send_msg(self.page, "move-tab", index=0, groupId=g["id"])
        send_msg(self.page, "move-tab", index=0, groupId=None)
        assert self._tabs()[0]["groupId"] is None

    def test_move_tab_invalid_space_noop(self):
        sp = self._spaces()[0]
        send_msg(self.page, "add-tab", name="T", url="https://t.com")
        send_msg(self.page, "move-tab", index=0, spaceId="nope")
        assert self._tabs()[0]["spaceId"] == sp["id"]

    def test_move_tab_invalid_group_noop(self):
        send_msg(self.page, "add-tab", name="T", url="https://t.com")
        send_msg(self.page, "move-tab", index=0, groupId="nope")
        assert self._tabs()[0].get("groupId") is None

    def test_reorder_before(self):
        for n in ("A", "B", "C"):
            send_msg(self.page, "add-tab", name=n, url=f"https://{n.lower()}.com")
        send_msg(self.page, "reorder-tab", fromIndex=0, toIndex=2, side="before")
        assert [t["name"] for t in self._tabs()] == ["B", "A", "C"]

    def test_reorder_after(self):
        for n in ("A", "B", "C"):
            send_msg(self.page, "add-tab", name=n, url=f"https://{n.lower()}.com")
        send_msg(self.page, "reorder-tab", fromIndex=0, toIndex=2, side="after")
        assert [t["name"] for t in self._tabs()] == ["B", "C", "A"]

    def test_reorder_up(self):
        for n in ("A", "B", "C"):
            send_msg(self.page, "add-tab", name=n, url=f"https://{n.lower()}.com")
        send_msg(self.page, "reorder-tab", fromIndex=2, toIndex=0, side="before")
        assert [t["name"] for t in self._tabs()] == ["C", "A", "B"]

    def test_reorder_same_index_noop(self):
        for n in ("A", "B"):
            send_msg(self.page, "add-tab", name=n, url=f"https://{n.lower()}.com")
        send_msg(self.page, "reorder-tab", fromIndex=1, toIndex=1, side="before")
        assert [t["name"] for t in self._tabs()] == ["A", "B"]


# ==========================================
#  BACKGROUND.JS: МИГРАЦИЯ LEGACY-ПАПОК + ЧИСТКА
# ==========================================

class TestBackgroundMigration:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_bg(self, init_js=""):
        """Чистая загрузка background.js с предзаполненным хранилищем."""
        pg = self.page
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME + init_js)
        pg.evaluate(load_file("background.js") + "; 'loaded'")

    def test_migration_folders_to_spaces(self):
        init = (
            "chrome.storage._data['blattam-folders'] = "
            "[{id:'f1',name:'Work',parentId:null},{id:'f2',name:'Sub',parentId:'f1'}];\n"
            "chrome.storage._data['blattam-tabs'] = "
            "[{name:'W1',url:'https://w1.com',folderId:'f1'},"
            "{name:'S1',url:'https://s1.com',folderId:'f2'},"
            "{name:'L1',url:'https://l1.com',folderId:null}];"
        )
        self._load_bg(init)
        sps = read_storage_raw(self.page, "blattam-spaces")
        names = sorted(s["name"] for s in sps)
        assert names == ["Sub", "Work", "Мои вкладки"]
        by_name = {s["name"]: s["id"] for s in sps}
        tabs = {t["name"]: t for t in read_storage_raw(self.page, "blattam-tabs")}
        assert tabs["W1"]["spaceId"] == by_name["Work"]
        assert tabs["S1"]["spaceId"] == by_name["Sub"]
        assert tabs["L1"]["spaceId"] == by_name["Мои вкладки"]
        for t in tabs.values():
            assert "folderId" not in t
            assert t["groupId"] is None
        # legacy-ключ удалён
        assert self.page.evaluate("'blattam-folders' in chrome.storage._data") is False

    def test_migration_idempotent(self):
        init = (
            "chrome.storage._data['blattam-folders'] = "
            "[{id:'f1',name:'Work',parentId:null}];\n"
            "chrome.storage._data['blattam-tabs'] = "
            "[{name:'W1',url:'https://w1.com',folderId:'f1'}];"
        )
        self._load_bg(init)
        first = read_storage_raw(self.page, "blattam-spaces")
        # Повторный запуск расширения: повторная миграция не происходит
        self.page.evaluate(load_file("background.js") + "; 'reloaded'")
        second = read_storage_raw(self.page, "blattam-spaces")
        assert [s["id"] for s in first] == [s["id"] for s in second]
        assert len(read_storage_raw(self.page, "blattam-tabs")) == 1

    def test_migration_tabs_with_folder_id_only(self):
        """Нет ключа blattam-folders, но у вкладок folderId — миграция всё равно работает."""
        init = ("chrome.storage._data['blattam-tabs'] = "
                "[{name:'W1',url:'https://w1.com',folderId:'ghost'}];")
        self._load_bg(init)
        sps = read_storage_raw(self.page, "blattam-spaces")
        assert [s["name"] for s in sps] == ["Мои вкладки"]
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert tabs[0]["spaceId"] == sps[0]["id"]

    def test_purge_screenshots(self):
        """Оставшийся blattam-screenshots (local) вычищается при загрузке."""
        self._load_bg("chrome.storage.local._data['blattam-screenshots'] = 'data:image/png;base64,xyz';")
        assert read_local(self.page, "blattam-screenshots") is None


# ==========================================
#  VIEW.JS: РЕНДЕР + ПРОСТРАНСТВА
# ==========================================

class TestViewSpaces:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _chips(self):
        return json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('.space-chip')].map(c => ({name: c.querySelector('.chip-name').textContent, id: c.dataset.spaceId, active: c.classList.contains('active')})))"))

    def test_default_space_created(self):
        load_view(self.page)
        sps = read_storage_raw(self.page, "blattam-spaces")
        assert len(sps) == 1 and sps[0]["name"] == "Мои вкладки"
        chips = self._chips()
        assert len(chips) == 1 and chips[0]["active"]

    def test_cards_render(self):
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 2
        # Вкладки без spaceId получили первое пространство
        tabs = read_storage_raw(self.page, "blattam-tabs")
        sps = read_storage_raw(self.page, "blattam-spaces")
        assert all(t["spaceId"] == sps[0]["id"] for t in tabs)

    def test_space_chips_rendered(self):
        load_view(self.page, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ])
        chips = self._chips()
        assert [c["name"] for c in chips] == ["Main", "Work"]
        assert chips[0]["active"] and not chips[1]["active"]

    def test_active_space_from_last_space(self):
        load_view(self.page, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ], tabs=[{"name": "T", "url": "https://t.com", "spaceId": "sp2"}], last_space="sp2")
        chips = self._chips()
        assert chips[1]["active"]
        label = self.page.evaluate("document.getElementById('meta-label').textContent")
        assert label == "Work"
        # Видим только вкладки сп2
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1

    def test_last_space_invalid_falls_back_first(self):
        load_view(self.page, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ], last_space="junk")
        chips = self._chips()
        assert chips[0]["active"] and not chips[1]["active"]

    def test_switch_space(self):
        load_view(self.page, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ], tabs=[
            {"name": "M", "url": "https://m.com", "spaceId": "sp1"},
            {"name": "W", "url": "https://w.com", "spaceId": "sp2"},
        ])
        self.page.evaluate("document.querySelector('.space-chip[data-space-id=\"sp2\"]').click()")
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1
        names = json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('.tab-card .tab-name')].map(e => e.textContent))"))
        assert names == ["W"]
        assert read_storage_raw(self.page, "blattam-last-space") == "sp2"
        assert self._chips()[1]["active"]

    def test_search_filter(self):
        load_view(self.page, tabs=[
            {"name": "Google", "url": "https://google.com"},
            {"name": "GitHub", "url": "https://github.com"},
        ])
        self.page.locator("#search").fill("Google")
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1

    def test_search_by_url(self):
        load_view(self.page, tabs=[
            {"name": "Tab", "url": "https://example.com/page"},
            {"name": "Other", "url": "https://other.com"},
        ])
        self.page.locator("#search").fill("example")
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1

    def test_search_by_title(self):
        load_view(self.page, tabs=[
            {"name": "Gmail", "title": "Mail Service", "url": "https://gmail.com"},
            {"name": "Other", "url": "https://other.com"},
        ])
        self.page.locator("#search").fill("Mail")
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1

    def test_no_results_shown(self):
        load_view(self.page, tabs=[{"name": "X", "url": "https://x.com"}])
        self.page.locator("#search").fill("NEVEREXIST")
        assert self.page.evaluate("document.getElementById('no-results').style.display !== 'none'")

    def test_reset_filters_button(self):
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        self.page.locator("#search").fill("A")
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1
        self.page.evaluate("document.getElementById('btn-reset-filters').click()")
        assert self.page.locator("#search").input_value() == ""
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 2

    def test_empty_state(self):
        load_view(self.page, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ], tabs=[{"name": "W", "url": "https://w.com", "spaceId": "sp2"}])
        # Активно sp1 (первое) — вкладок там нет
        assert self.page.evaluate("document.getElementById('empty-state').style.display !== 'none'")
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 0
        assert self.page.evaluate("document.getElementById('meta-count').textContent") == "0"

    def test_meta_label_and_count(self):
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
            {"name": "C", "url": "https://c.com"},
        ])
        assert self.page.evaluate("document.getElementById('meta-count').textContent") == "3"
        assert self.page.evaluate("document.getElementById('meta-label').textContent") == "Мои вкладки"

    def test_onchange_active_space_removed_switches(self):
        load_view(self.page, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ], last_space="sp2")
        assert self._chips()[1]["active"]
        # Пространство sp2 исчезает (из другого окна)
        self.page.evaluate("chrome.storage.sync.set({'blattam-spaces': [{id: 'sp1', name: 'Main'}]})")
        chips = self._chips()
        assert len(chips) == 1 and chips[0]["active"]
        assert read_storage_raw(self.page, "blattam-last-space") == "sp1"

    def test_view_migration_legacy_folders(self):
        load_view(self.page,
                  folders=[{"id": "f1", "name": "Work", "parentId": None}],
                  tabs=[
                      {"name": "W1", "url": "https://w1.com", "folderId": "f1"},
                      {"name": "L1", "url": "https://l1.com", "folderId": None},
                  ])
        sps = read_storage_raw(self.page, "blattam-spaces")
        names = sorted(s["name"] for s in sps)
        assert names == ["Work", "Мои вкладки"]
        assert self.page.evaluate("'blattam-folders' in chrome.storage._data") is False
        by_name = {s["name"]: s["id"] for s in sps}
        tabs = {t["name"]: t for t in read_storage_raw(self.page, "blattam-tabs")}
        assert tabs["W1"]["spaceId"] == by_name["Work"]
        assert tabs["L1"]["spaceId"] == by_name["Мои вкладки"]
        # Чипы отрендерились
        assert [c["name"] for c in self._chips()] == ["Work", "Мои вкладки"]


# ==========================================
#  VIEW.JS: МОДАЛКА ПРОСТРАНСТВА (создание / ренейм / удаление)
# ==========================================

class TestViewSpaceModal:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def test_create_space_modal_flow(self):
        load_view(self.page, tabs=[{"name": "A", "url": "https://a.com"}])
        self.page.locator("#add-space-btn").click()
        assert self.page.evaluate("document.getElementById('space-modal').classList.contains('open')")
        assert self.page.evaluate("document.getElementById('modal-title').textContent") == "Новое пространство"
        self.page.locator("#space-name-input").fill("Work")
        self.page.locator("#modal-confirm").click()
        sps = read_storage_raw(self.page, "blattam-spaces")
        assert len(sps) == 2
        new_sp = [s for s in sps if s["name"] == "Work"][0]
        # Новое пространство стало активным + запомнилось
        chips = json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('.space-chip')].map(c => ({name: c.querySelector('.chip-name').textContent, active: c.classList.contains('active')})))"))
        assert chips[1]["name"] == "Work" and chips[1]["active"]
        assert read_storage_raw(self.page, "blattam-last-space") == new_sp["id"]
        # Модалка закрыта
        assert not self.page.evaluate("document.getElementById('space-modal').classList.contains('open')")

    def test_create_space_empty_autoname(self):
        load_view(self.page)
        self.page.locator("#add-space-btn").click()
        self.page.locator("#modal-confirm").click()  # пустое имя допустимо
        sps = read_storage_raw(self.page, "blattam-spaces")
        assert [s["name"] for s in sps] == ["Мои вкладки", "Пространство 2"]

    def test_create_space_duplicate_not_activated(self):
        load_view(self.page, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ])
        self.page.locator("#add-space-btn").click()
        self.page.locator("#space-name-input").fill("WORK")  # дубль без учёта регистра
        self.page.locator("#modal-confirm").click()
        assert len(read_storage_raw(self.page, "blattam-spaces")) == 2  # не создано
        chips = json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('.space-chip')].map(c => c.classList.contains('active')))"))
        assert chips == [True, False]  # активное не изменилось

    def test_create_space_cancel(self):
        load_view(self.page)
        self.page.locator("#add-space-btn").click()
        self.page.locator("#space-name-input").fill("Work")
        self.page.locator("#modal-cancel").click()
        assert len(read_storage_raw(self.page, "blattam-spaces")) == 1
        assert not self.page.evaluate("document.getElementById('space-modal').classList.contains('open')")

    def test_rename_space_via_chip(self):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}])
        self.page.evaluate("document.querySelector('.space-chip .chip-icon-btn').click()")
        assert self.page.evaluate("document.getElementById('modal-title').textContent") == "Переименовать пространство"
        assert self.page.locator("#space-name-input").input_value() == "Main"
        self.page.locator("#space-name-input").fill("Renamed")
        self.page.locator("#modal-confirm").click()
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "rename-space" and msg["id"] == "sp1" and msg["name"] == "Renamed"
        sps = read_storage_raw(self.page, "blattam-spaces")
        assert sps[0]["name"] == "Renamed"
        label = self.page.evaluate("document.getElementById('meta-label').textContent")
        assert label == "Renamed"

    def test_rename_space_no_change_no_message(self):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}])
        self.page.evaluate("document.querySelector('.space-chip .chip-icon-btn').click()")
        self.page.locator("#modal-confirm").click()  # имя не изменено
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage || null)"))
        assert msg is None or msg.get("action") != "rename-space"

    def test_delete_space_via_chip(self):
        load_view(self.page, confirm=True, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ], tabs=[
            {"name": "M", "url": "https://m.com", "spaceId": "sp1"},
            {"name": "W", "url": "https://w.com", "spaceId": "sp2"},
        ], last_space="sp1")
        self.page.evaluate("document.querySelectorAll('.space-chip .chip-icon-btn')[1].click()")  # ✕ у sp1
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "delete-space" and msg["id"] == "sp1"
        sps = read_storage_raw(self.page, "blattam-spaces")
        assert [s["id"] for s in sps] == ["sp2"]
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert all(t["spaceId"] == "sp2" for t in tabs)  # вкладки переехали
        assert read_storage_raw(self.page, "blattam-last-space") == "sp2"  # активное переключилось


# ==========================================
#  VIEW.JS: ГРУППЫ (сворачиваемые секции)
# ==========================================

class TestViewGroups:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}, {"id": "sp2", "name": "Work"}]

    def test_group_bar_rendered(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
        ])
        bars = self.page.evaluate("document.querySelectorAll('.gbar').length")
        assert bars == 1
        name = self.page.evaluate("document.querySelector('.gbar .gname').textContent")
        assert name == "Dev"
        count = self.page.evaluate("document.querySelector('.gbar .gcount').textContent")
        assert count == "2 вкладки"
        chev = self.page.evaluate("document.querySelector('.gbar .chev').textContent")
        assert chev == "\u25BE"  # ▾ развёрнута
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 3
        assert self.page.evaluate("document.getElementById('meta-groups')") is None

    def test_group_collapsed_members_hidden(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": True},
        ], tabs=[
            {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
        ])
        assert self.page.evaluate("document.querySelectorAll('.gbar').length") == 1
        chev = self.page.evaluate("document.querySelector('.gbar .chev').textContent")
        assert chev == "\u25B8"  # ▸ свёрнута
        cards = self.page.evaluate("document.querySelectorAll('.tab-card').length")
        assert cards == 1  # только негрупповая
        count = self.page.evaluate("document.querySelector('.gbar .gcount').textContent")
        assert count == "1 вкладка"  # счётчик на шапке остался

    def test_group_toggle_persists(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"}])
        self.page.evaluate("document.querySelector('.gbar').click()")
        g = read_storage_raw(self.page, "blattam-groups")[0]
        assert g["collapsed"] is True
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 0
        self.page.evaluate("document.querySelector('.gbar').click()")
        g = read_storage_raw(self.page, "blattam-groups")[0]
        assert g["collapsed"] is False
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1

    def test_groups_of_other_space_hidden(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g2", "name": "Other", "spaceId": "sp2", "collapsed": False},
        ], tabs=[
            {"name": "D", "url": "https://d.com", "spaceId": "sp2", "groupId": "g2"},
            {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
        ])
        assert self.page.evaluate("document.querySelectorAll('.gbar').length") == 0
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1
        assert self.page.evaluate("document.getElementById('meta-groups')") is None

    def test_loose_label(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
        ])
        lbl = self.page.evaluate("document.querySelector('.loose-label') && document.querySelector('.loose-label').textContent")
        assert lbl == "Без группы"

    def test_delete_group(self):
        load_view(self.page, confirm=True, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
        ])
        self.page.evaluate("document.querySelector('.gbar .gdel').click()")
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "delete-group" and msg["id"] == "g1"
        assert read_storage_raw(self.page, "blattam-groups") == []
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert all(t["groupId"] is None and t["spaceId"] == "sp1" for t in tabs)
        assert self.page.evaluate("document.querySelectorAll('.gbar').length") == 0
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 2

    def test_meta_groups_plural(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "A", "spaceId": "sp1", "collapsed": False},
            {"id": "g2", "name": "B", "spaceId": "sp1", "collapsed": False},
        ])
        assert self.page.evaluate("document.getElementById('meta-groups')") is None
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g%d" % i, "name": "G%d" % i, "spaceId": "sp1", "collapsed": False}
            for i in range(1, 6)
        ])
        assert self.page.evaluate("document.getElementById('meta-groups')") is None


# ==========================================
#  VIEW.JS: «+ Группа» В МЕТА-СТРОКЕ (модалка создания группы)
# ==========================================

class TestViewGroupCreate:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}, {"id": "sp2", "name": "Work"}]

    def test_create_group_in_empty_space(self):
        # Пустое пространство (0 вкладок) — кнопка работает и создаёт гбар
        load_view(self.page, spaces=self.SP, tabs=[])
        self.page.evaluate("document.getElementById('add-group-btn').click()")
        assert self.page.evaluate("document.getElementById('modal-title').textContent") == "Новая группа"
        assert self.page.evaluate("document.getElementById('space-modal').classList.contains('open')")
        self.page.locator("#space-name-input").fill("NewG")
        self.page.locator("#modal-confirm").click()
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "create-group" and msg["spaceId"] == "sp1" and msg["name"] == "NewG"
        groups = read_storage_raw(self.page, "blattam-groups")
        assert len(groups) == 1 and groups[0]["name"] == "NewG" and groups[0]["spaceId"] == "sp1"
        # Пустая группа отрендерилась («0 вкладок»), empty-state скрыт
        assert self.page.evaluate("document.querySelectorAll('.gbar').length") == 1
        count = self.page.evaluate("document.querySelector('.gbar .gcount').textContent")
        assert count == "0 вкладок"
        assert self.page.evaluate("document.getElementById('empty-state').style.display") == "none"
        # Счётчик групп из мета-строки удалён (id не остаётся)
        assert self.page.evaluate("document.getElementById('meta-groups')") is None

    def test_create_group_empty_name_autoname(self):
        load_view(self.page, spaces=self.SP, tabs=[
            {"name": "T", "url": "https://t.com", "spaceId": "sp1"},
        ])
        self.page.evaluate("document.getElementById('add-group-btn').click()")
        self.page.locator("#modal-confirm").click()
        groups = read_storage_raw(self.page, "blattam-groups")
        assert len(groups) == 1 and groups[0]["name"] == "Группа 1"
        assert groups[0]["spaceId"] == "sp1"
        # Вкладка НЕ перемещена (карточка не участвует в создании)
        assert read_storage_raw(self.page, "blattam-tabs")[0].get("groupId") in (None, "")

    def test_create_group_cancel_noop(self):
        load_view(self.page, spaces=self.SP, tabs=[])
        self.page.evaluate("document.getElementById('add-group-btn').click()")
        self.page.locator("#modal-cancel").click()
        assert read_storage_raw(self.page, "blattam-groups") == []
        assert not self.page.evaluate("document.getElementById('space-modal').classList.contains('open')")
        last = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage || null)"))
        assert last is None or last.get("action") != "create-group"


# ==========================================
#  VIEW.JS: DnD КАРТОЧКИ НА БАР ГРУППЫ (перемещение в группу)
# ==========================================

class TestGroupBarDrop:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _drag_drop_to_gbar(self, src_idx):
        self.page.evaluate("""(args) => {
          const card = document.querySelectorAll('.tab-card')[args];
          const bar = document.querySelector('.gbar');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          bar.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          bar.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        }""", src_idx)

    def test_drop_moves_card_into_group(self):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "T", "url": "https://t.com", "spaceId": "sp1"}])
        self._drag_drop_to_gbar(0)
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "move-tab" and msg["groupId"] == "g1" and msg["index"] == 0
        assert "spaceId" not in msg
        assert read_storage_raw(self.page, "blattam-tabs")[0]["groupId"] == "g1"
        count = self.page.evaluate("document.querySelector('.gbar .gcount').textContent")
        assert count == "1 вкладка"

    def test_drop_on_own_group_noop(self):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "T", "url": "https://t.com", "spaceId": "sp1", "groupId": "g1"}])
        before = json.dumps(read_storage_raw(self.page, "blattam-tabs"), sort_keys=True)
        self._drag_drop_to_gbar(0)
        after = json.dumps(read_storage_raw(self.page, "blattam-tabs"), sort_keys=True)
        assert before == after  # groupId не изменился — состояние то же
        assert read_storage_raw(self.page, "blattam-tabs")[0]["groupId"] == "g1"

    def test_dragover_hint_adds_and_dragleave_removes(self):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "T", "url": "https://t.com", "spaceId": "sp1"}])
        state = json.loads(self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const bar = document.querySelector('.gbar');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          bar.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          const over = bar.classList.contains('drop-over');
          bar.dispatchEvent(new DragEvent('dragleave', {bubbles: true}));
          const left = !bar.classList.contains('drop-over');
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
          return JSON.stringify({over, left});
        })()"""))
        assert state == {"over": True, "left": True}
        # Дроп не трогает состояние сворачивания группы
        assert read_storage_raw(self.page, "blattam-groups")[0]["collapsed"] is False


# ==========================================
#  VIEW.JS: «+ ГРУППА» — СТРОКА В КОНЦЕ СПИСКА ВКЛАДОК
# ==========================================

class TestAddGroupRow:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}]

    def _inject_real_styles(self):
        # Харнес ставит только body.innerHTML — подгружаем настоящие стили
        # (theme.css + <style> view.html), чтобы computed-значения были реальными
        theme = load_file("theme.css")
        html = load_file("view.html")
        style = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate(
            "(styles) => { var st = document.createElement('style'); st.textContent = styles; document.head.appendChild(st); }",
            [theme + "\n" + style])

    def test_add_group_btn_last_child_dashed_full_width(self):
        # Обычное пространство (группа + негрупповая вкладка): кнопка —
        # ПОСЛЕДНИЙ элемент #tabs-list, пунктирная, полноширинная
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
        ])
        self._inject_real_styles()
        d = json.loads(self.page.evaluate("""(() => {
          const list = document.getElementById('tabs-list');
          const btn = document.getElementById('add-group-btn');
          const cs = getComputedStyle(btn);
          return JSON.stringify({
            inList: list.contains(btn),
            isLast: list.lastElementChild === btn,
            borderStyle: cs.borderStyle,
            height: cs.height,
            listW: list.getBoundingClientRect().width,
            btnW: btn.getBoundingClientRect().width
          });
        })()"""))
        assert d["inList"] and d["isLast"], d
        assert d["borderStyle"] == "dashed", d
        assert d["height"] == "40px", d
        assert abs(d["btnW"] - d["listW"]) <= 4, d
        # Кнопка больше не в мета-строке (там только метатитул)
        assert self.page.evaluate("document.querySelector('.metarow #add-group-btn')") is None

    def test_add_group_btn_in_groups_only_space(self):
        # Пространство без вкладок, но с группами: кнопка после пустых гбаров
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ])
        d = json.loads(self.page.evaluate("""(() => {
          const list = document.getElementById('tabs-list');
          const btn = document.getElementById('add-group-btn');
          return JSON.stringify({
            inList: list.contains(btn),
            isLast: list.lastElementChild === btn,
            bars: document.querySelectorAll('.gbar').length
          });
        })()"""))
        assert d["inList"] and d["isLast"] and d["bars"] == 1, d

    def test_add_group_btn_in_fully_empty_space(self):
        # Полностью пустое пространство: кнопка присутствует (рядом с empty-state)
        load_view(self.page, spaces=self.SP, tabs=[])
        d = json.loads(self.page.evaluate("""(() => {
          const list = document.getElementById('tabs-list');
          const btn = document.getElementById('add-group-btn');
          return JSON.stringify({
            inList: list.contains(btn),
            isLast: list.lastElementChild === btn,
            emptyVisible: document.getElementById('empty-state').style.display !== 'none'
          });
        })()"""))
        assert d["inList"] and d["isLast"] and d["emptyVisible"], d

    def test_add_group_btn_opens_group_modal(self):
        # Клик открывает ту же модалку создания группы
        load_view(self.page, spaces=self.SP, tabs=[])
        self.page.evaluate("document.getElementById('add-group-btn').click()")
        assert self.page.evaluate("document.getElementById('modal-title').textContent") == "Новая группа"
        assert self.page.evaluate("document.getElementById('space-modal').classList.contains('open')")


# ==========================================
#  VIEW.JS: КОНТРАСТ КАРТОЧЕК (--card-bg ≠ фон страницы, обе темы)
# ==========================================

class TestCardContrast:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    TABS = [{"name": "T", "url": "https://t.com"}]

    def _inject_real_styles(self):
        # Харнес ставит только body.innerHTML — подгружаем настоящие стили
        # (theme.css + <style> view.html), чтобы computed-значения были реальными
        theme = load_file("theme.css")
        html = load_file("view.html")
        style = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate(
            "(styles) => { var st = document.createElement('style'); st.textContent = styles; document.head.appendChild(st); }",
            [theme + "\n" + style])

    def _backgrounds(self):
        return json.loads(self.page.evaluate("""(() => {
          const cardBg = getComputedStyle(document.querySelector('.tab-card')).backgroundColor;
          const pageBg = getComputedStyle(document.body).backgroundColor;
          return JSON.stringify({cardBg, pageBg});
        })()"""))

    def test_light_card_differs_from_page(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        bgs = self._backgrounds()
        assert bgs["cardBg"] != bgs["pageBg"], bgs

    def test_dark_card_differs_from_page(self):
        load_view(self.page, theme="dark", tabs=self.TABS)
        self._inject_real_styles()
        bgs = self._backgrounds()
        assert bgs["cardBg"] != bgs["pageBg"], bgs


# ==========================================
#  VIEW.JS: КАРТОЧКИ (открытие, ренейм, удаление)
# ==========================================

class TestViewCards:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def test_card_click_opens_tab(self):
        load_view(self.page, tabs=[{"name": "A", "url": "https://a.com"}])
        self.page.evaluate("document.querySelector('.tab-card .cbody').click()")
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "open-one" and msg["url"] == "https://a.com"
        assert self.page.evaluate("chrome.tabs.createdTabs.length") == 1

    def test_name_click_opens_with_delay(self):
        """Одиночный клик по имени открывает вкладку с задержкой 300мс."""
        load_view(self.page, tabs=[{"name": "A", "url": "https://a.com"}])
        self.page.evaluate("document.querySelector('.tab-name').dispatchEvent(new MouseEvent('click', {bubbles: true}))")
        assert self.page.evaluate("chrome.tabs.createdTabs.length") == 0  # сразу — ещё нет
        self.page.wait_for_timeout(400)
        assert self.page.evaluate("chrome.tabs.createdTabs.length") == 1

    def test_dblclick_rename_opens_input(self):
        load_view(self.page, tabs=[{"name": "Original", "url": "https://orig.com"}])
        self.page.evaluate("""(() => {
          const el = document.querySelector('.tab-name');
          el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
          el.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
        })()""")
        assert self.page.evaluate("!!document.querySelector('.tab-name-input')")

    def test_rename_saves_on_enter(self):
        load_view(self.page, tabs=[{"name": "OldName", "url": "https://old.com"}])
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
        assert msg["action"] == "rename-tab" and msg["name"] == "NewName"
        name = self.page.evaluate("document.querySelector('.tab-name').textContent")
        assert name == "NewName"

    def test_rename_cancel_on_escape(self):
        load_view(self.page, tabs=[{"name": "KeepMe", "url": "https://keep.com"}])
        self.page.evaluate("""(() => {
          const el = document.querySelector('.tab-name');
          el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
          el.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
        })()""")
        self.page.evaluate("""(() => {
          const inp = document.querySelector('.tab-name-input');
          inp.value = 'Hacked';
          inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
        })()""")
        name = self.page.evaluate("document.querySelector('.tab-name').textContent")
        assert name == "KeepMe"
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert tabs[0]["name"] == "KeepMe"

    def test_delete_card(self):
        load_view(self.page, confirm=True, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        self.page.evaluate("document.querySelector('.tab-card .tab-remove').click()")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 1 and tabs[0]["name"] == "B"
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1


# ==========================================
#  VIEW.JS: МАССОВОЕ ОТКРЫТИЕ
# ==========================================

class TestViewSelection:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    TABS = [
        {"name": "A", "url": "https://a.com"},
        {"name": "B", "url": "https://b.com"},
        {"name": "C", "url": "https://c.com"},
    ]

    def test_checkbox_selects(self):
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("document.querySelector('.tab-card .tab-select').click()")
        assert self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')") is False
        assert self.page.evaluate("document.getElementById('selection-count').textContent") == "1 выбрано"
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 1

    def test_select_all_button_toggle(self):
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("document.getElementById('select-btn').click()")
        assert self.page.evaluate("document.querySelectorAll('.tab-select:checked').length") == 3
        self.page.evaluate("document.getElementById('select-btn').click()")  # toggle off
        assert self.page.evaluate("document.querySelectorAll('.tab-select:checked').length") == 0

    def test_open_selected(self):
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("document.getElementById('select-btn').click()")
        self.page.evaluate("document.getElementById('open-selected-btn').click()")
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "open-many"
        assert msg["urls"] == ["https://a.com", "https://b.com", "https://c.com"]
        assert self.page.evaluate("chrome.tabs.createdTabs.length") == 3
        # Выбор снят
        assert self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")

    def test_clear_selection(self):
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("document.getElementById('select-btn').click()")
        self.page.evaluate("document.getElementById('clear-selection-btn').click()")
        assert self.page.evaluate("document.querySelectorAll('.tab-select:checked').length") == 0
        assert self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")

    def test_card_click_removes_selection_for_opened(self):
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("document.querySelectorAll('.tab-select')[0].click()")
        self.page.evaluate("document.querySelectorAll('.tab-card .cbody')[0].click()")
        assert self.page.evaluate("document.querySelectorAll('.tab-select:checked').length") == 0


# ==========================================
#  VIEW.JS: КЛАВИАТУРНАЯ НАВИГАЦИЯ
# ==========================================

class TestKeyboardNav:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    TABS = [
        {"name": "A", "url": "https://a.com"},
        {"name": "B", "url": "https://b.com"},
        {"name": "C", "url": "https://c.com"},
    ]

    def _key(self, key, target="document"):
        self.page.evaluate(f"""(() => {{
          const t = {target};
          t.dispatchEvent(new KeyboardEvent('keydown', {{key: '{key}', bubbles: true, cancelable: true}}));
        }})()""")

    def _active_names(self):
        return json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('.tab-card.kbd-active .tab-name')].map(e => e.textContent))"))

    def test_arrow_down_selects_first_then_next(self):
        load_view(self.page, tabs=self.TABS)
        self._key("ArrowDown")
        assert self._active_names() == ["A"]
        self._key("ArrowDown")
        assert self._active_names() == ["B"]

    def test_arrow_down_wraps(self):
        load_view(self.page, tabs=self.TABS)
        for _ in range(4):
            self._key("ArrowDown")
        assert self._active_names() == ["A"]

    def test_arrow_up_wraps(self):
        load_view(self.page, tabs=self.TABS)
        self._key("ArrowUp")
        assert self._active_names() == ["C"]

    def test_arrow_right_left_also_navigate(self):
        load_view(self.page, tabs=self.TABS)
        self._key("ArrowRight")
        assert self._active_names() == ["A"]
        self._key("ArrowLeft")
        assert self._active_names() == ["C"]

    def test_enter_opens_active(self):
        load_view(self.page, tabs=self.TABS)
        self._key("ArrowDown")
        self._key("Enter")
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "open-one" and msg["url"] == "https://a.com"

    def test_delete_removes_active(self):
        load_view(self.page, confirm=True, tabs=self.TABS)
        self._key("ArrowDown")
        self._key("Delete")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert [t["name"] for t in tabs] == ["B", "C"]
        assert self._active_names() == []  # карточка исчезла

    def test_backspace_removes_active(self):
        load_view(self.page, confirm=True, tabs=self.TABS)
        self._key("ArrowDown")
        self._key("Backspace")
        assert [t["name"] for t in read_storage_raw(self.page, "blattam-tabs")] == ["B", "C"]

    def test_esc_resets_search_selection_active(self):
        load_view(self.page, tabs=self.TABS)
        self.page.locator("#search").fill("A")  # видима 1 карточка
        self.page.evaluate("document.getElementById('select-btn').click()")
        self._key("ArrowDown")
        self._key("Escape")
        assert self.page.locator("#search").input_value() == ""
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 3
        assert self.page.evaluate("document.querySelectorAll('.tab-select:checked').length") == 0
        assert self._active_names() == []

    def test_esc_from_search_field_clears_and_blurs(self):
        load_view(self.page, tabs=self.TABS)
        self.page.locator("#search").fill("abc")
        self._key("Escape")
        assert self.page.locator("#search").input_value() == ""
        active = self.page.evaluate("document.activeElement.tagName")
        assert active != "INPUT"

    def test_arrows_ignored_while_typing(self):
        load_view(self.page, tabs=self.TABS)
        self.page.locator("#search").fill("a")  # фокус остаётся в поле
        self._key("ArrowDown")
        assert self._active_names() == []  # поле ввода — навигация не перехватывается

    def test_modal_blocks_navigation(self):
        load_view(self.page, tabs=self.TABS)
        self.page.locator("#add-space-btn").click()
        self._key("ArrowDown")  # модалка открыта — глобальный handler не работает
        assert self._active_names() == []
        # Escape в поле модалки закрывает её
        self.page.evaluate("document.getElementById('space-name-input').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        assert not self.page.evaluate("document.getElementById('space-modal').classList.contains('open')")


# ==========================================
#  VIEW.JS: REORDER ДРОП (карточка → карточка)
# ==========================================

class TestReorderDnD:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _drag_drop_card(self, src_idx, dst_idx, half):
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
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
            {"name": "C", "url": "https://c.com"},
        ])
        self._drag_drop_card(0, 2, 'before')
        assert self._tab_names() == ["B", "A", "C"]
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "reorder-tab"
        assert msg["fromIndex"] == 0 and msg["toIndex"] == 2 and msg["side"] == "before"

    def test_drop_bottom_half_inserts_after(self):
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
            {"name": "C", "url": "https://c.com"},
        ])
        self._drag_drop_card(0, 2, 'after')
        assert self._tab_names() == ["B", "C", "A"]
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["side"] == "after"

    def test_drop_on_self_noop(self):
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        self._drag_drop_card(0, 0, 'before')
        assert self._tab_names() == ["A", "B"]
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage || null)"))
        assert msg is None or msg.get("action") != "reorder-tab"

    def test_reorder_under_space_filter_changes_full_array(self):
        load_view(self.page, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ], tabs=[
            {"name": "Free1", "url": "https://free1.com", "spaceId": "sp1"},
            {"name": "WorkA", "url": "https://wa.com", "spaceId": "sp2"},
            {"name": "Free2", "url": "https://free2.com", "spaceId": "sp1"},
            {"name": "WorkB", "url": "https://wb.com", "spaceId": "sp2"},
        ])
        self.page.evaluate("document.querySelector('.space-chip[data-space-id=\"sp2\"]').click()")
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 2
        self._drag_drop_card(0, 1, 'after')  # WorkA (индекс 1) → под WorkB (индекс 3)
        assert self._tab_names() == ["Free1", "Free2", "WorkB", "WorkA"]
        sids = json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.spaceId));
        })()"""))
        assert sids == ["sp1", "sp1", "sp2", "sp2"]  # пространства не изменились

    def test_selection_and_active_url_survive_reorder(self):
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
            {"name": "C", "url": "https://c.com"},
        ])
        self.page.evaluate("document.getElementById('select-btn').click()")
        self.page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true, cancelable: true}))")
        self._drag_drop_card(2, 0, 'before')  # C → перед A
        assert self._tab_names() == ["C", "A", "B"]
        checked = self.page.evaluate("document.querySelectorAll('.tab-select:checked').length")
        bar_hidden = self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")
        assert checked == 3 and not bar_hidden
        active = json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('.tab-card.kbd-active .tab-name')].map(e => e.textContent))"))
        assert active == ["A"]

    def test_dragend_without_drop_no_change(self):
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        self.page.evaluate("""(() => {
          const cards = document.querySelectorAll('.tab-card');
          const dt = new DataTransfer();
          cards[0].dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const r = cards[1].getBoundingClientRect();
          cards[1].dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientY: r.top + Math.max(r.height * 0.75, 0.001)}));
          window.__indicatorShown = document.querySelectorAll('.tab-card.drop-before, .tab-card.drop-after').length;
          cards[0].dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        assert self.page.evaluate("window.__indicatorShown") == 1
        assert self._tab_names() == ["A", "B"]
        left = self.page.evaluate("document.querySelectorAll('.tab-card.drop-before, .tab-card.drop-after').length")
        dragging = self.page.evaluate("document.querySelectorAll('.tab-card.dragging').length")
        assert left == 0 and dragging == 0

    def test_dragover_indicators_and_dragleave(self):
        load_view(self.page, tabs=[
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
        state = json.loads(self.page.evaluate(
            "JSON.stringify({top: window.__top, bottom: window.__bottom, cleared: window.__cleared})"))
        assert state == {"top": True, "bottom": True, "cleared": True}

    def test_space_chip_drop_moves_tab(self):
        load_view(self.page, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "DragMe", "url": "https://drag.com", "spaceId": "sp1", "groupId": "g1"},
        ])
        self.page.evaluate("""(args) => {
          const card = document.querySelector('.tab-card');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const chip = document.querySelector('.space-chip[data-space-id="' + args + '"]');
          chip.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          chip.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        }""", "sp2")
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "move-tab" and msg["spaceId"] == "sp2"
        tab = read_storage_raw(self.page, "blattam-tabs")[0]
        assert tab["spaceId"] == "sp2" and tab["groupId"] is None


# ==========================================
#  VIEW.JS: DnD ПЕРЕУПОРЯДОЧЕНИЕ ГРУПП (шапка на шапку)
# ==========================================

class TestGroupReorderDnD:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}, {"id": "sp2", "name": "Work"}]

    def _inject_real_styles(self):
        # Харнес ставит только body.innerHTML — подгружаем настоящие стили
        # (theme.css + <style> view.html), чтобы computed-значения были реальными
        theme = load_file("theme.css")
        html = load_file("view.html")
        style = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate(
            "(styles) => { var st = document.createElement('style'); st.textContent = styles; document.head.appendChild(st); }",
            [theme + "\n" + style])

    def _groups(self):
        return json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-groups');
          return JSON.stringify((d['blattam-groups'] || []).map(g => g.name));
        })()"""))

    def _dom_order(self):
        return json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('.gbar .gname')].map(e => e.textContent))"))

    def _drag_drop_gbar(self, src_name, dst_name, half):
        self.page.evaluate("""(args) => {
          const bars = [...document.querySelectorAll('.gbar')];
          const src = bars.find(b => b.querySelector('.gname').textContent === args[0]);
          const dst = bars.find(b => b.querySelector('.gname').textContent === args[1]);
          const r = dst.getBoundingClientRect();
          const clientY = args[2] === 'before' ? r.top + r.height * 0.25 : r.top + Math.max(r.height * 0.75, 0.001);
          const dt = new DataTransfer();
          src.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          dst.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientY}));
          dst.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true, clientY}));
          src.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        }""", [src_name, dst_name, half])

    def test_drag_to_lower_half_moves_group_after(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "gA", "name": "A", "spaceId": "sp1", "collapsed": False},
            {"id": "gB", "name": "B", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "a1", "url": "https://a1.com", "spaceId": "sp1", "groupId": "gA"},
            {"name": "b1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "gB"},
        ])
        assert self._groups() == ["A", "B"]
        self._drag_drop_gbar("A", "B", "after")
        # Порядок в storage и в DOM: B, затем A
        assert self._groups() == ["B", "A"]
        assert self._dom_order() == ["B", "A"]
        # Члены групп не тронуты
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert {t["name"]: t["groupId"] for t in tabs} == {"a1": "gA", "b1": "gB"}

    def test_drag_to_upper_half_moves_group_before(self):
        # Стартовый порядок B, A: перетаскивание A на верхнюю половину B — A до B
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "gB", "name": "B", "spaceId": "sp1", "collapsed": False},
            {"id": "gA", "name": "A", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "b1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "gB"},
            {"name": "a1", "url": "https://a1.com", "spaceId": "sp1", "groupId": "gA"},
        ])
        assert self._groups() == ["B", "A"]
        self._drag_drop_gbar("A", "B", "before")
        assert self._groups() == ["A", "B"]
        assert self._dom_order() == ["A", "B"]

    def test_drop_on_self_noop(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "gA", "name": "A", "spaceId": "sp1", "collapsed": False},
            {"id": "gB", "name": "B", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "a1", "url": "https://a1.com", "spaceId": "sp1", "groupId": "gA"},
            {"name": "b1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "gB"},
        ])
        self._drag_drop_gbar("A", "A", "before")
        assert self._groups() == ["A", "B"]
        assert self._dom_order() == ["A", "B"]
        # Сворачивание не затронуто дропом на себя
        assert all(g["collapsed"] is False for g in read_storage_raw(self.page, "blattam-groups"))

    def test_reorder_keeps_other_space_groups_and_collapsed(self):
        # Группа W другого пространства между A и B в глобальном массиве:
        # порядок W сохраняется, свёрнутость A остаётся у A
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "gA", "name": "A", "spaceId": "sp1", "collapsed": True},
            {"id": "gW", "name": "W", "spaceId": "sp2", "collapsed": False},
            {"id": "gB", "name": "B", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "a1", "url": "https://a1.com", "spaceId": "sp1", "groupId": "gA"},
            {"name": "b1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "gB"},
        ])
        self._drag_drop_gbar("A", "B", "after")
        assert self._groups() == ["W", "B", "A"]
        # В DOM — только группы активного пространства
        assert self._dom_order() == ["B", "A"]
        gs = read_storage_raw(self.page, "blattam-groups")
        by_name = {g["name"]: g for g in gs}
        assert by_name["A"]["collapsed"] is True and by_name["W"]["collapsed"] is False
        assert by_name["A"]["spaceId"] == "sp1" and by_name["B"]["spaceId"] == "sp1"

    def test_dragover_shows_indicator_line_not_drop_over(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "gA", "name": "A", "spaceId": "sp1", "collapsed": False},
            {"id": "gB", "name": "B", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "a1", "url": "https://a1.com", "spaceId": "sp1", "groupId": "gA"},
            {"name": "b1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "gB"},
        ])
        self._inject_real_styles()
        state = json.loads(self.page.evaluate("""(() => {
          const bars = [...document.querySelectorAll('.gbar')];
          const src = bars.find(b => b.querySelector('.gname').textContent === 'A');
          const dst = bars.find(b => b.querySelector('.gname').textContent === 'B');
          const dt = new DataTransfer();
          src.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const r = dst.getBoundingClientRect();
          dst.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientY: r.top + r.height * 0.25}));
          const topLine = dst.classList.contains('drop-before');
          const csTop = getComputedStyle(dst, '::before');
          const lineTop = csTop.height === '2px' && csTop.content !== 'none';
          dst.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientY: r.top + Math.max(r.height * 0.75, 0.001)}));
          const bottomLine = dst.classList.contains('drop-after');
          const noOverBg = !dst.classList.contains('drop-over');
          src.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
          const cleared = !dst.classList.contains('drop-before') && !dst.classList.contains('drop-after');
          return JSON.stringify({topLine, lineTop, bottomLine, noOverBg, cleared});
        })()"""))
        assert state == {"topLine": True, "lineTop": True, "bottomLine": True, "noOverBg": True, "cleared": True}, state


# ==========================================
#  POPUP.JS: ПРОСТРАНСТВА
# ==========================================

class TestPopup:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}, {"id": "sp2", "name": "Work"}]

    def _options(self):
        return json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('#space-select option')].map(o => ({value: o.value, text: o.textContent})))"))

    def test_space_selector_shows_spaces(self):
        load_popup(self.page, spaces=self.SP)
        opts = self._options()
        assert len(opts) == 2
        assert [o["text"] for o in opts] == ["Main", "Work"]

    def test_last_space_preselected(self):
        load_popup(self.page, spaces=self.SP, last_space="sp2")
        assert self.page.evaluate("document.getElementById('space-select').value") == "sp2"

    def test_first_space_fallback(self):
        load_popup(self.page, spaces=self.SP)
        assert self.page.evaluate("document.getElementById('space-select').value") == "sp1"

    def test_save_sends_space_id(self):
        load_popup(self.page, spaces=self.SP)
        self.page.evaluate("document.getElementById('space-select').value = 'sp2'")
        self.page.locator("#save-current-tab").click()
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "save-current"
        assert msg["spaceId"] == "sp2"
        assert msg["name"] == "Example Domain"
        # Последнее пространство запомнилось
        assert read_storage_raw(self.page, "blattam-last-space") == "sp2"
        assert self.page.evaluate("document.getElementById('saved-msg').classList.contains('show')")

    def test_save_shows_confirmation(self):
        load_popup(self.page, spaces=self.SP)
        self.page.locator("#save-current-tab").click()
        assert self.page.evaluate("document.getElementById('saved-msg').classList.contains('show')")

    def test_add_space_modal_flow(self):
        load_popup(self.page, spaces=self.SP[:1])
        self.page.locator("#popup-add-space").click()
        assert self.page.evaluate("document.getElementById('space-modal').classList.contains('open')")
        self.page.locator("#space-name-input").fill("Work")
        self.page.locator("#modal-confirm").click()
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "create-space" and msg["name"] == "Work"
        sps = read_storage_raw(self.page, "blattam-spaces")
        assert len(sps) == 2
        new_id = [s for s in sps if s["name"] == "Work"][0]["id"]
        assert self.page.evaluate("document.getElementById('space-select').value") == new_id
        assert not self.page.evaluate("document.getElementById('space-modal').classList.contains('open')")

    def test_popup_updates_on_spaces_change(self):
        load_popup(self.page, spaces=self.SP[:1])
        self.page.evaluate("chrome.storage.sync.set({'blattam-spaces': " + json.dumps(self.SP, ensure_ascii=False) + "})")
        opts = self._options()
        assert len(opts) == 2

    def test_popup_updates_on_last_space_change(self):
        load_popup(self.page, spaces=self.SP)
        self.page.evaluate("chrome.storage.sync.set({'blattam-last-space': 'sp2'})")
        assert self.page.evaluate("document.getElementById('space-select').value") == "sp2"


# ==========================================
#  EDGE CASES (background.js)
# ==========================================

class TestEdgeCases:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        page.goto("about:blank")
        page.evaluate(MOCK_CHROME)
        page.evaluate(load_file("background.js") + "; 'loaded'")

    def _tabs(self):
        return read_storage_raw(self.page, "blattam-tabs")

    def test_delete_nonexistent_index_noop(self):
        send_msg(self.page, "delete", index=999)
        assert self._tabs() == []

    def test_open_nonexistent_index_noop(self):
        send_msg(self.page, "open", index=999)
        assert self.page.evaluate("chrome.tabs.createdTabs.length") == 0

    def test_move_to_invalid_space_noop(self):
        sp = read_storage_raw(self.page, "blattam-spaces")[0]
        send_msg(self.page, "add-tab", name="X", url="https://x.com")
        send_msg(self.page, "move-tab", index=0, spaceId="nonexistent")
        assert self._tabs()[0]["spaceId"] == sp["id"]

    def test_rename_nonexistent_space_noop(self):
        sps = read_storage_raw(self.page, "blattam-spaces")
        call_msg(self.page, "rename-space", id="nope", name="X")
        assert read_storage_raw(self.page, "blattam-spaces") == sps

    def test_delete_nonexistent_space_noop(self):
        sps = read_storage_raw(self.page, "blattam-spaces")
        call_msg(self.page, "delete-space", id="nope")
        assert read_storage_raw(self.page, "blattam-spaces") == sps

    def test_delete_nonexistent_group_noop(self):
        call_msg(self.page, "delete-group", id="nope")
        assert read_storage_raw(self.page, "blattam-groups") == []

    def test_rename_nonexistent_tab_noop(self):
        send_msg(self.page, "add-tab", name="Keep", url="https://keep2.com")
        send_msg(self.page, "rename-tab", index=999, name="Hacked")
        assert all(t["name"] != "Hacked" for t in self._tabs())

    def test_rename_empty_name_noop(self):
        send_msg(self.page, "add-tab", name="Keep2", url="https://keep3.com")
        send_msg(self.page, "rename-tab", index=0, name="   ")
        tabs = [t for t in self._tabs() if t["url"] == "https://keep3.com"]
        assert len(tabs) == 1 and tabs[0]["name"] == "Keep2"

    def test_reorder_invalid_indices_noop(self):
        for n in ("A", "B"):
            send_msg(self.page, "add-tab", name=n, url=f"https://{n.lower()}.com")
        send_msg(self.page, "reorder-tab", fromIndex=0, toIndex=99, side="before")
        send_msg(self.page, "reorder-tab", fromIndex=-1, toIndex=0, side="before")
        assert [t["name"] for t in self._tabs()] == ["A", "B"]


# ==========================================
#  VIEW.JS: ЭКСПОРТ / ИМПОРТ (spaces + groups)
# ==========================================

class TestViewImportExport:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _export(self):
        self.page.evaluate("""(() => {
          URL.createObjectURL = function(b) { return 'blob:mock'; };
          URL.revokeObjectURL = function() {};
          window.__exportBlob = null;
          var orig = Blob;
          Blob = function(parts, opts) { window.__exportBlob = parts[0]; return new orig(parts, opts); };
          document.getElementById('export-btn').click();
        })()""")
        return json.loads(self.page.evaluate("window.__exportBlob"))

    def _import(self, data):
        payload = json.dumps(data, ensure_ascii=False)
        self.page.evaluate("""(payload) => {
          var input = document.getElementById('import-input');
          var dt = new DataTransfer();
          dt.items.add(new File([payload], 'blattam-toby-backup.json', {type: 'application/json'}));
          input.files = dt.files;
          input.dispatchEvent(new Event('change'));
        }""", payload)
        self.page.wait_for_timeout(150)

    def test_export_shape(self):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "A", "url": "https://a.com", "spaceId": "sp1"}])
        data = self._export()
        assert data["blattam-toby"] is True
        assert "spaces" in data and "groups" in data and "tabs" in data
        assert "tags" not in data and "sessions" not in data and "folders" not in data
        assert len(data["spaces"]) == 1 and len(data["groups"]) == 1 and len(data["tabs"]) == 1

    def test_import_merges_spaces_and_groups(self):
        load_view(self.page, confirm=True,
                  spaces=[{"id": "sp1", "name": "Main"}],
                  groups=[{"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False}],
                  tabs=[{"name": "T1", "url": "https://t1.com", "spaceId": "sp1"}])
        self._import({
            "blattam-toby": True, "version": "1.0.0",
            "spaces": [{"id": "fsp1", "name": "Main"}, {"id": "fsp2", "name": "Work"}],
            "groups": [
                {"id": "fg1", "name": "Dev", "spaceId": "fsp1", "collapsed": False},
                {"id": "fg2", "name": "Ops", "spaceId": "fsp2", "collapsed": True},
            ],
            "tabs": [
                {"name": "Dup", "url": "https://t1.com", "spaceId": "fsp1"},
                {"name": "New", "url": "https://new.com", "spaceId": "fsp2", "groupId": "fg2"},
            ],
        })
        sps = read_storage_raw(self.page, "blattam-spaces")
        assert sorted(s["name"] for s in sps) == ["Main", "Work"]  # 'Main' не продублирован
        work_id = [s for s in sps if s["name"] == "Work"][0]["id"]
        groups = read_storage_raw(self.page, "blattam-groups")
        by_name = {g["name"]: g for g in groups}
        assert sorted(by_name) == ["Dev", "Ops"]
        assert by_name["Dev"]["id"] == "g1"  # своя группа сохранена
        assert by_name["Ops"]["spaceId"] == work_id  # remap через пространство
        assert by_name["Ops"]["collapsed"] is True
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert len(tabs) == 2  # дубль по URL пропущен
        new_t = [t for t in tabs if t["url"] == "https://new.com"][0]
        assert new_t["spaceId"] == work_id
        assert new_t["groupId"] == by_name["Ops"]["id"]

    def test_import_legacy_folders_migrated(self):
        load_view(self.page, confirm=True, tabs=[])
        self._import({
            "blattam-toby": True, "version": "1.0.0",
            "folders": [{"id": "ff1", "name": "Work", "parentId": None}],
            "tabs": [
                {"name": "W", "url": "https://w.com", "folderId": "ff1"},
                {"name": "L", "url": "https://l.com"},
            ],
        })
        sps = read_storage_raw(self.page, "blattam-spaces")
        names = sorted(s["name"] for s in sps)
        assert names == ["Work", "Мои вкладки"]
        by_name = {s["name"]: s["id"] for s in sps}
        tabs = {t["url"]: t for t in read_storage_raw(self.page, "blattam-tabs")}
        assert tabs["https://w.com"]["spaceId"] == by_name["Work"]
        assert tabs["https://l.com"]["spaceId"] == by_name["Мои вкладки"]
        assert "folderId" not in tabs["https://w.com"]

    def test_import_rejects_invalid(self):
        load_view(self.page, tabs=[])
        self._import({"blattam-toby": True, "noTabs": []})
        assert read_storage_raw(self.page, "blattam-tabs") == []


# ==========================================
#  VIEW.JS: ТЁМНАЯ ТЕМА
# ==========================================

class TestDarkTheme:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def test_theme_button_exists(self):
        load_view(self.page)
        assert self.page.evaluate("!!document.getElementById('theme-btn')")

    def test_default_theme_is_light(self):
        load_view(self.page)
        assert self.page.evaluate("document.documentElement.dataset.theme") == "light"
        assert self.page.evaluate("document.querySelector('#theme-btn .glyph').textContent") == "\U0001F319"

    def test_click_switches_to_dark(self):
        load_view(self.page)
        self.page.evaluate("document.getElementById('theme-btn').click()")
        assert self.page.evaluate("document.documentElement.dataset.theme") == "dark"
        assert self.page.evaluate("document.querySelector('#theme-btn .glyph').textContent") == "\u2600\uFE0F"

    def test_theme_saved_to_local_storage(self):
        load_view(self.page)
        self.page.evaluate("document.getElementById('theme-btn').click()")
        assert read_local(self.page, "blattam-theme") == "dark"

    def test_saved_theme_applied_on_load(self):
        load_view(self.page, theme="dark", tabs=[{"name": "A", "url": "https://a.com"}])
        assert self.page.evaluate("document.documentElement.dataset.theme") == "dark"
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1

    def test_second_click_returns_to_light(self):
        load_view(self.page)
        self.page.evaluate("document.getElementById('theme-btn').click()")
        self.page.evaluate("document.getElementById('theme-btn').click()")
        assert self.page.evaluate("document.documentElement.dataset.theme") == "light"
        assert read_local(self.page, "blattam-theme") == "light"


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
        self.page.wait_for_timeout(100)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        sps = read_storage_raw(self.page, "blattam-spaces")
        assert len(tabs) == 1
        assert tabs[0]["url"] == "https://example.com"
        assert tabs[0]["name"] == "Example Domain"
        assert tabs[0]["spaceId"] == sps[0]["id"]
        assert "folderId" not in tabs[0]

    def test_on_command_skips_chrome_urls(self):
        self.page.evaluate("chrome.tabs._currentTab.url = 'chrome://settings'")
        self._fire_command("save-tab")
        self.page.wait_for_timeout(100)
        assert read_storage_raw(self.page, "blattam-tabs") == []

    def test_on_command_ignores_other_commands(self):
        self._fire_command("some-other-command")
        self.page.wait_for_timeout(100)
        assert read_storage_raw(self.page, "blattam-tabs") == []


# ==========================================
#  РЕЛИЗ: zip-сборка, иконки, описание магазина
# ==========================================

class TestRelease:
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
                "dist", ".git", ".pytest_cache", "__pycache__", "sketches")

    def _run_build(self):
        spec = importlib.util.spec_from_file_location("build_zip", f"{EXT_PATH}/build_zip.py")
        bz = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bz)
        bz.main()
        return os.path.join(EXT_PATH, "dist", "BlattamToby-v%s.zip" % bz.read_version())

    @staticmethod
    def _png_size(path):
        with open(path, "rb") as f:
            head = f.read(24)
        assert head[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
        w, h = struct.unpack(">II", head[16:24])
        return w, h

    def test_build_zip_members_exact(self):
        zip_path = self._run_build()
        assert os.path.isfile(zip_path), f"zip not created: {zip_path}"
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            assert names == self.EXPECTED_MEMBERS, f"unexpected members: {names ^ self.EXPECTED_MEMBERS}"
            for bad in self.EXCLUDED:
                for n in names:
                    assert bad not in n.replace(os.sep, "/"), f"excluded file leaked: {n}"
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            assert "icons" in manifest
            for px in ("16", "48", "128"):
                icon = manifest["icons"][px]
                assert icon in names, f"icon {icon} (size {px}) missing from zip"

    def test_icon_pixel_sizes(self):
        for px in (16, 48, 128):
            path = os.path.join(EXT_PATH, "icons", f"icon{px}.png")
            assert os.path.isfile(path), f"missing {path}"
            w, h = self._png_size(path)
            assert (w, h) == (px, px), f"icon{px}.png is {w}x{h}, expected {px}x{px}"

    def test_description_has_short(self):
        path = os.path.join(EXT_PATH, "store", "DESCRIPTION.md")
        assert os.path.isfile(path), "missing store/DESCRIPTION.md"
        text = open(path, "r", encoding="utf-8").read()
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
#  ВЕРСИОНАЯ ОЧИСТКА: папки → пространства (legacy-механика удалена)
# ==========================================

class TestCleanup:
    """Удалённые механики не должны ссылаться на живых файлах:
    вложенные папки (parentId), create/rename/delete-folder, теги/сессии/статистика."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def test_view_js_no_removed_machinery(self):
        src = load_file("view.js")
        for bad in ("blattam-sessions", "blattam-tags", "blattam-stats", "blattam-card-size",
                    "blattam-screenshots", "tagIds", "archivedAt", "recordOpen",
                    "set-tab-tags", "create-tag", "delete-tag", "frequent", "favorites",
                    "parentId", "create-folder", "rename-folder", "delete-folder",
                    "folder-chip", "folderId:"):
            assert bad not in src, f"view.js still references '{bad}'"

    def test_background_js_no_removed_machinery(self):
        src = load_file("background.js")
        for bad in ("blattam-sessions", "blattam-tags", "blattam-stats", "blattam-card-size",
                    "tagIds", "archivedAt", "recordOpen", "set-tab-tags", "create-tag",
                    "delete-tag", "unarchive", "parentId", "create-folder", "rename-folder",
                    "delete-folder", "onRemoved"):
            assert bad not in src, f"background.js still references '{bad}'"

    def test_popup_js_no_folder_machinery(self):
        src = load_file("popup.js")
        for bad in ("blattam-folders", "folderId", "parentId",
                    "create-folder", "rename-folder", "delete-folder", "folder-select"):
            assert bad not in src, f"popup.js still references '{bad}'"

    def test_html_no_folder_ids(self):
        for name in ("view.html", "popup.html"):
            src = load_file(name)
            for bad in ("folder-modal", "add-folder-btn", "popup-add-folder",
                        "folder-name-input", "blattam-folders", 'id="folder-select"'):
                assert bad not in src, f"{name} still references '{bad}'"

    def test_theme_css_no_removed_tokens(self):
        src = load_file("theme.css")
        assert "--tag-" not in src, "theme.css still has --tag-* tokens"
        assert "--archived-" not in src, "theme.css still has --archived-* tokens"


# ==========================================
#  SITE FAVICON (background.js + view.js)
# ==========================================

class TestFavicons:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def test_save_current_stores_favicon(self):
        pg = self.page
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME)
        pg.evaluate(load_file("background.js") + "; 'loaded'")
        send_msg(pg, "save-current", name="FavTab")
        pg.wait_for_timeout(100)
        tabs = read_storage_raw(pg, "blattam-tabs")
        assert len(tabs) == 1
        assert tabs[0]["favIconUrl"] == "https://example.com/favicon.ico"

    def test_card_renders_favicon_img(self):
        load_view(self.page, tabs=[
            {"name": "GitHub", "url": "https://github.com", "favIconUrl": "https://github.com/favicon.ico"},
        ])
        src = self.page.evaluate("(() => { var i = document.querySelector('.tab-card .tab-favicon'); return i ? i.src : null; })()")
        assert src == "https://github.com/favicon.ico"
        first = self.page.evaluate("document.querySelector('.tab-card .cname').firstElementChild.className")
        assert first == "tab-favicon"

    def test_card_renders_letter_fallback(self):
        load_view(self.page, tabs=[
            {"name": "GitHub", "url": "https://github.com"},
            {"name": "Nope", "url": "https://nope.example/path"},
        ])
        assert self.page.evaluate("document.querySelectorAll('.tab-card .tab-favicon').length") == 0
        letters = json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('.tab-card .tab-favicon-fallback')].map(e => e.textContent))"))
        assert letters == ["g", "n"]

    def test_favicon_load_error_swaps_to_fallback(self):
        load_view(self.page, tabs=[
            {"name": "GitHub", "url": "https://github.com", "favIconUrl": "https://missing.invalid/favicon.ico"},
        ])
        self.page.evaluate("(() => { var i = document.querySelector('.tab-card .tab-favicon'); if (i) i.dispatchEvent(new Event('error')); })()")
        self.page.wait_for_timeout(50)
        assert self.page.evaluate("document.querySelectorAll('.tab-card .tab-favicon').length") == 0
        letter = self.page.evaluate("document.querySelector('.tab-card .tab-favicon-fallback') && document.querySelector('.tab-card .tab-favicon-fallback').textContent")
        assert letter == "g"
        assert self.page.evaluate("document.querySelector('.tab-card .tab-name').textContent") == "GitHub"

    def test_import_keeps_favIconUrl(self):
        load_view(self.page, confirm=True, tabs=[])
        self.page.evaluate("""(() => {
          var payload = %s;
          var input = document.getElementById('import-input');
          var dt = new DataTransfer();
          dt.items.add(new File([payload], 'blattam-toby-backup.json', {type: 'application/json'}));
          input.files = dt.files;
          input.dispatchEvent(new Event('change'));
        })()""" % json.dumps(json.dumps({
            "blattam-toby": True, "version": "1.0.0",
            "spaces": [{"id": "sp1", "name": "Main"}],
            "tabs": [
                {"name": "GH", "url": "https://github.com", "favIconUrl": "https://github.com/favicon.ico", "spaceId": "sp1"},
                {"name": "Plain", "url": "https://plain.example", "spaceId": "sp1"},
            ],
        }, ensure_ascii=False)))
        self.page.wait_for_timeout(150)
        tabs = {t["url"]: t for t in read_storage_raw(self.page, "blattam-tabs")}
        assert tabs["https://github.com"]["favIconUrl"] == "https://github.com/favicon.ico"
        assert "favIconUrl" not in tabs["https://plain.example"]

    def test_export_includes_favIconUrl(self):
        load_view(self.page, tabs=[
            {"name": "GH", "url": "https://github.com", "favIconUrl": "https://github.com/favicon.ico"},
        ])
        self.page.evaluate("""(() => {
          URL.createObjectURL = function(b) { return 'blob:mock'; };
          URL.revokeObjectURL = function() {};
          window.__exportBlob = null;
          var orig = Blob;
          Blob = function(parts, opts) { window.__exportBlob = parts[0]; return new orig(parts, opts); };
          document.getElementById('export-btn').click();
        })()""")
        data = json.loads(self.page.evaluate("window.__exportBlob"))
        assert data["tabs"][0]["favIconUrl"] == "https://github.com/favicon.ico"


# ==========================================
#  VIEW.JS: «Ничего не найдено» — ТОЛЬКО при активном поиске
# ==========================================

class TestNoResultsOnlyOnSearch:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}]

    def _load_collapsible(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
        ])

    def test_collapsing_group_does_not_show_no_results(self):
        self._load_collapsible()
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 2
        self.page.evaluate("document.querySelector('.gbar').click()")
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 0
        # Вся группа свёрнута — «Ничего не найдено» НЕ показывается
        assert self.page.evaluate("document.getElementById('no-results').style.display") == "none"
        # Группа осталась наверху списка (не ушла ниже пустого состояния)
        assert self.page.evaluate("document.getElementById('tabs-list').firstElementChild.className") == "gbar"

    def test_no_results_follows_search_after_collapse(self):
        self._load_collapsible()
        self.page.evaluate("document.querySelector('.gbar').click()")
        assert self.page.evaluate("document.getElementById('no-results').style.display") == "none"
        self.page.locator("#search").fill("NEVEREXIST")
        assert self.page.evaluate("document.getElementById('no-results').style.display !== 'none'")
        self.page.locator("#search").fill("")
        assert self.page.evaluate("document.getElementById('no-results').style.display") == "none"


# ==========================================
#  VIEW.JS: ЧИПЫ ПРОСТРАНСТВ 26px + «+ Пространство» в левом краю ряда
# ==========================================

class TestSpaceChipStyles:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    TABS = [{"name": "T", "url": "https://t.com"}]

    def _inject_real_styles(self):
        # Харнес ставит только body.innerHTML — подгружаем настоящие стили
        # (theme.css + <style> view.html), чтобы computed-значения были реальными
        theme = load_file("theme.css")
        html = load_file("view.html")
        style = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate(
            "(styles) => { var st = document.createElement('style'); st.textContent = styles; document.head.appendChild(st); }",
            [theme + "\n" + style])

    def test_space_chip_height_26px(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        assert self.page.evaluate("getComputedStyle(document.querySelector('.space-chip')).height") == "26px"

    def test_add_space_btn_height_26px(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        assert self.page.evaluate("getComputedStyle(document.getElementById('add-space-btn')).height") == "26px"

    def test_add_space_btn_faint_text_style(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        d = json.loads(self.page.evaluate("""(() => {
          const cs = getComputedStyle(document.getElementById('add-space-btn'));
          return JSON.stringify({
            borderStyle: cs.borderStyle,
            backgroundImage: cs.backgroundImage,
            textTransform: cs.textTransform,
            fontFamily: cs.fontFamily
          });
        })()"""))
        assert d["borderStyle"] == "none"
        assert d["backgroundImage"] == "none"
        assert d["textTransform"] == "uppercase"
        assert "mono" in d["fontFamily"].lower()

    def test_add_space_btn_left_edge_in_spaces_bar(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        d = json.loads(self.page.evaluate("""(() => {
          const b = document.getElementById('add-space-btn').getBoundingClientRect();
          const bar = document.getElementById('spaces-bar').getBoundingClientRect();
          return JSON.stringify({btnLeft: b.left, barLeft: bar.left});
        })()"""))
        assert d["btnLeft"] - d["barLeft"] <= 8, d

    def test_add_group_btn_full_width_row_in_tabs_list(self):
        # «+ Группа» больше не в мета-строке — полноширинная строка в #tabs-list
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        d = json.loads(self.page.evaluate("""(() => {
          const list = document.getElementById('tabs-list');
          const btn = document.getElementById('add-group-btn');
          return JSON.stringify({
            inList: list.contains(btn),
            isLast: list.lastElementChild === btn,
            listW: list.getBoundingClientRect().width,
            btnW: btn.getBoundingClientRect().width
          });
        })()"""))
        assert d["inList"] and d["isLast"], d
        assert abs(d["btnW"] - d["listW"]) <= 4, d


# ==========================================
#  VIEW.JS: КАРТОЧКИ ВКЛАДОК 74px (2× высота, контент по центру)
# ==========================================

class TestTabCardHeight:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    TABS = [{"name": "T", "url": "https://t.com"}]

    def _inject_real_styles(self):
        # Харнес ставит только body.innerHTML — подгружаем настоящие стили
        # (theme.css + <style> view.html), чтобы computed-значения были реальными
        theme = load_file("theme.css")
        html = load_file("view.html")
        style = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate(
            "(styles) => { var st = document.createElement('style'); st.textContent = styles; document.head.appendChild(st); }",
            [theme + "\n" + style])

    def test_tab_card_height_74px(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        assert self.page.evaluate("getComputedStyle(document.querySelector('.tab-card')).height") == "74px"

    def test_tab_name_at_top_of_card(self):
        # Имя вкладки — СВЕРХУ карточки (нижняя зона зарезервирована)
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        d = json.loads(self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const name = document.querySelector('.tab-name');
          return JSON.stringify({
            cardH: card.getBoundingClientRect().height,
            nameTop: name.getBoundingClientRect().top - card.getBoundingClientRect().top
          });
        })()"""))
        assert d["cardH"] == 74, d
        assert d["nameTop"] <= 14, d


# ==========================================
#  ЗАПУСК
# ==========================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

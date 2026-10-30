r"""
BlattamToby тесты через Playwright.
Мокируем Chrome API; проверяем background.js, view.js, popup.js +
пространства (spaces) и сворачиваемые группы (groups), миграцию legacy-папок.

Запуск: PYTHONDONTWRITEBYTECODE=1 C:\Python314\python.exe test_plugin.py
"""
import importlib.util
import json
import os
import re
import pytest
import struct
import zipfile
from playwright.sync_api import sync_playwright

EXT_PATH = r"C:\Users\DI\Desktop\QwenCode\BlattamToby"


# === Моки Chrome API ===

MOCK_CHROME = """
var mockSeq = 100;
function cloneVal(v) { return (v === undefined || v === null) ? v : JSON.parse(JSON.stringify(v)); }
var chrome = {
  storage: {
    _data: {},                 // sync area (blattam-spaces/groups/last-space/folders)
    _fire: function(changeInfo, area) {
      if (window.__storageListeners && window.__storageListeners.length) {
        for (var fn of window.__storageListeners) fn(changeInfo, area);
      }
    },
    // Bare chrome.storage.* — area-aware convenience (тесты): 'blattam-tabs'
    // живёт в local, всё остальное — в sync.
    // real Chrome returns STRUCTURED CLONES — не живые ссылки на _data:
    // view.js mutates the read array in place (e.g. tab deletion), so a live
    // reference would make onChanged's oldValue === newValue
    get: function(keys, callback) {
      var self = this;
      var pick = function(k) { return (k === 'blattam-tabs') ? self.local._data : self._data; };
      var result = {};
      if (typeof keys === 'string') {
        result[keys] = cloneVal(pick(keys)[keys]);
      } else if (Array.isArray(keys)) {
        for (var k of keys) result[k] = cloneVal(pick(k)[k]);
      } else {
        Object.keys(self._data).forEach(function(k) { result[k] = cloneVal(self._data[k]); });
        Object.keys(self.local._data).forEach(function(k) { result[k] = cloneVal(self.local._data[k]); });
      }
      if (callback) callback(result);
      return Promise.resolve(result);
    },
    set: function(data, callback) {
      var self = this;
      var syncData = {}, localData = {};
      for (var k in data) {
        if (k === 'blattam-tabs') localData[k] = data[k];
        else syncData[k] = data[k];
      }
      self._setStore(self.local._data, localData, 'local');
      self._setStore(self._data, syncData, 'sync');
      if (callback) callback();
      return Promise.resolve();
    },
    remove: function(keys, callback) {
      var self = this;
      var arr = Array.isArray(keys) ? keys : [keys];
      var syncKeys = [], localKeys = [];
      arr.forEach(function(k) { (k === 'blattam-tabs' ? localKeys : syncKeys).push(k); });
      self._removeStore(self.local._data, localKeys, 'local');
      self._removeStore(self._data, syncKeys, 'sync');
      if (callback) callback();
      return Promise.resolve();
    },
    _setStore: function(store, data, area) {
      var changeInfo = {};
      for (var k in data) {
        // As with real Chrome: oldValue — snapshot BEFORE the change (copy: view.js
        // often passes the same array it just mutated in place)
        changeInfo[k] = { newValue: data[k], oldValue: (store[k] !== undefined ? JSON.parse(JSON.stringify(store[k])) : undefined) };
        store[k] = data[k];
      }
      if (Object.keys(changeInfo).length) this._fire(changeInfo, area);
    },
    _removeStore: function(store, keys, area) {
      var changeInfo = {};
      (keys || []).forEach(function(k) {
        if (store[k] !== undefined) changeInfo[k] = { oldValue: JSON.parse(JSON.stringify(store[k])) };
        delete store[k];
      });
      if (Object.keys(changeInfo).length) this._fire(changeInfo, area);
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
        var tabs = chrome.storage.local._data['blattam-tabs'] || [];
        if (tabs[msg.index] && (msg.name || '').trim()) {
          tabs[msg.index].name = String(msg.name).trim();
          var oldVal = JSON.parse(JSON.stringify(chrome.storage.local._data['blattam-tabs'] || []));
          chrome.storage.local._data['blattam-tabs'] = tabs;
          chrome.storage._fire({ 'blattam-tabs': { newValue: tabs, oldValue: oldVal } }, 'local');
        }
      }
      // move-tab: применяем spaceId/groupId (как делает background)
      if (msg.action === 'move-tab') {
        var tabs2 = chrome.storage.local._data['blattam-tabs'] || [];
        if (tabs2[msg.index]) {
          if (msg.spaceId !== undefined) { tabs2[msg.index].spaceId = msg.spaceId; tabs2[msg.index].groupId = null; }
          if (msg.groupId !== undefined) tabs2[msg.index].groupId = msg.groupId;
          var oldVal2 = JSON.parse(JSON.stringify(chrome.storage.local._data['blattam-tabs'] || []));
          chrome.storage.local._data['blattam-tabs'] = tabs2;
          chrome.storage._fire({ 'blattam-tabs': { newValue: tabs2, oldValue: oldVal2 } }, 'local');
        }
      }
      // reorder-tab: переставляем элемент в массиве (как background.js) и шлём onChanged
      if (msg.action === 'reorder-tab') {
        var tabs3 = chrome.storage.local._data['blattam-tabs'] || [];
        var from3 = Number(msg.fromIndex), to3 = Number(msg.toIndex);
        if (Number.isInteger(from3) && Number.isInteger(to3) &&
            from3 !== to3 && from3 >= 0 && from3 < tabs3.length && to3 >= 0 && to3 < tabs3.length) {
          var oldVal3 = JSON.parse(JSON.stringify(tabs3));
          var moved3 = tabs3.splice(from3, 1)[0];
          var shift3 = from3 < to3 ? -1 : 0;
          var at3 = (msg.side === 'before' ? to3 : to3 + 1) + shift3;
          tabs3.splice(Math.max(0, Math.min(tabs3.length, at3)), 0, moved3);
          chrome.storage._fire({ 'blattam-tabs': { newValue: tabs3, oldValue: oldVal3 } }, 'local');
        }
      }
      // place-tab: полный массив — перед/после якорной вкладки (null — в
      // конец списка), groupId секции слота (null — «Без группы»); как background.js
      if (msg.action === 'place-tab') {
        var tabsP = chrome.storage.local._data['blattam-tabs'] || [];
        var fromP = Number(msg.index);
        if (Number.isInteger(fromP) && fromP >= 0 && fromP < tabsP.length) {
          var oldValP = JSON.parse(JSON.stringify(tabsP));
          var movedP = tabsP.splice(fromP, 1)[0];
          var atP = tabsP.length;
          if (msg.anchorIndex !== null && msg.anchorIndex !== undefined) {
            var aP = Number(msg.anchorIndex);
            if (Number.isInteger(aP) && aP >= 0 && aP <= tabsP.length) {
              if (aP > fromP) aP -= 1;
              atP = msg.side === 'after' ? aP + 1 : aP;
            }
          }
          if (msg.groupId !== undefined) movedP.groupId = msg.groupId;
          tabsP.splice(Math.max(0, Math.min(tabsP.length, atP)), 0, movedP);
          chrome.storage._fire({ 'blattam-tabs': { newValue: tabsP, oldValue: oldValP } }, 'local');
        }
      }
      // place-tabs: батч выделенных вкладок в позицию слота (как background.js)
      if (msg.action === 'place-tabs') {
        var tabsQ = chrome.storage.local._data['blattam-tabs'] || [];
        var oldValQ = JSON.parse(JSON.stringify(tabsQ));
        var urlsQ = Array.isArray(msg.urls) ? msg.urls : [];
        var movedQ = tabsQ.filter(function(t) { return urlsQ.indexOf(t.url) !== -1; });
        if (movedQ.length) {
          var atQ;
          if (msg.anchorUrl === null || msg.anchorUrl === undefined) {
            atQ = tabsQ.length - movedQ.length;
          } else {
            var aQ = -1;
            for (var iQ = 0; iQ < tabsQ.length; iQ++) if (tabsQ[iQ].url === msg.anchorUrl) { aQ = iQ; break; }
            if (aQ === -1) return;
            var removedBeforeQ = 0;
            for (var jQ = 0; jQ < aQ; jQ++) if (urlsQ.indexOf(tabsQ[jQ].url) !== -1) removedBeforeQ++;
            atQ = msg.side === 'after' ? aQ - removedBeforeQ + 1 : aQ - removedBeforeQ;
          }
          atQ = Math.max(0, Math.min(tabsQ.length - movedQ.length, atQ));
          for (var kQ = 0; kQ < movedQ.length; kQ++) if (msg.groupId !== undefined) movedQ[kQ].groupId = msg.groupId;
          var restQ = tabsQ.filter(function(t) { return urlsQ.indexOf(t.url) === -1; });
          restQ.splice(atQ, 0, ...movedQ);
          chrome.storage.local._data['blattam-tabs'] = restQ;
          chrome.storage._fire({ 'blattam-tabs': { newValue: restQ, oldValue: oldValQ } }, 'local');
        }
      }
      // update-tab: имя/адрес/комментарий (как background.js): пустые имя/адрес →
      // старые значения, пустой комментарий → удалить ключ
      if (msg.action === 'update-tab') {
        var tabsU = chrome.storage.local._data['blattam-tabs'] || [];
        if (tabsU[msg.index]) {
          var nU = String(msg.name == null ? '' : msg.name).trim();
          var uU = String(msg.url == null ? '' : msg.url).trim();
          var cU = String(msg.comment == null ? '' : msg.comment).trim();
          if (nU) tabsU[msg.index].name = nU;
          if (uU) tabsU[msg.index].url = uU;
          if (cU) tabsU[msg.index].comment = cU;
          else delete tabsU[msg.index].comment;
          var oldValU = JSON.parse(JSON.stringify(tabsU));
          chrome.storage.local._data['blattam-tabs'] = tabsU;
          chrome.storage._fire({ 'blattam-tabs': { newValue: tabsU, oldValue: oldValU } }, 'local');
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
          var tabsD = chrome.storage.local._data['blattam-tabs'] || [];
          tabsD.forEach(function(t) { if (t && t.spaceId === msg.id) t.spaceId = target.id; });
          var gsD = chrome.storage._data['blattam-groups'] || [];
          var gsKept = gsD.filter(function(g) { return g.spaceId !== msg.id; });
          chrome.storage._data['blattam-spaces'] = remaining;
          chrome.storage.local._data['blattam-tabs'] = tabsD;
          chrome.storage._data['blattam-groups'] = gsKept;
          chrome.storage._fire({
            'blattam-spaces': { newValue: remaining, oldValue: sps2 },
            'blattam-groups': { newValue: gsKept, oldValue: gsD }
          }, 'sync');
          chrome.storage._fire({
            'blattam-tabs': { newValue: tabsD, oldValue: null }
          }, 'local');
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
          var tabsG = chrome.storage.local._data['blattam-tabs'] || [];
          tabsG.forEach(function(t) { if (t && t.groupId === msg.id) t.groupId = null; });
          chrome.storage._data['blattam-groups'] = gsNew;
          chrome.storage.local._data['blattam-tabs'] = tabsG;
          chrome.storage._fire({
            'blattam-groups': { newValue: gsNew, oldValue: gs3 }
          }, 'sync');
          chrome.storage._fire({
            'blattam-tabs': { newValue: tabsG, oldValue: null }
          }, 'local');
          response = true;
        }
      }

      if (callback) callback(response);
      return Promise.resolve(response);
    },
    getManifest: function() { return { version: '1.0.0' }; }
  }
};

// Area-специфичные методы: sync → _data (flat), local → local._data.
// chrome.storage.sync._data — тот же объект, что chrome.storage._data.
chrome.storage.sync = { _data: chrome.storage._data };
chrome.storage.sync.get = function(keys, cb) {
  var r = {};
  if (typeof keys === 'string') r[keys] = cloneVal(chrome.storage._data[keys]);
  else if (Array.isArray(keys)) { for (var k of keys) r[k] = cloneVal(chrome.storage._data[k]); }
  else Object.keys(chrome.storage._data).forEach(function(k) { r[k] = cloneVal(chrome.storage._data[k]); });
  if (cb) cb(r);
  return Promise.resolve(r);
};
chrome.storage.sync.set = function(data, cb) {
  chrome.storage._setStore(chrome.storage._data, data, 'sync');
  if (cb) cb();
  return Promise.resolve();
};
chrome.storage.sync.remove = function(keys, cb) {
  chrome.storage._removeStore(chrome.storage._data, Array.isArray(keys) ? keys : [keys], 'sync');
  if (cb) cb();
  return Promise.resolve();
};
// chrome.storage.local — отдельное хранилище (blattam-tabs, blattam-theme, ...)
chrome.storage.local.get = function(keys, cb) {
  var r = {};
  if (typeof keys === 'string') r[keys] = cloneVal(chrome.storage.local._data[keys]);
  else if (Array.isArray(keys)) { for (var k of keys) r[k] = cloneVal(chrome.storage.local._data[k]); }
  else Object.keys(chrome.storage.local._data).forEach(function(k) { r[k] = cloneVal(chrome.storage.local._data[k]); });
  if (cb) cb(r);
  return Promise.resolve(r);
};
chrome.storage.local.set = function(data, cb) {
  chrome.storage._setStore(chrome.storage.local._data, data, 'local');
  if (cb) cb();
  return Promise.resolve();
};
chrome.storage.local.remove = function(keys, cb) {
  chrome.storage._removeStore(chrome.storage.local._data, Array.isArray(keys) ? keys : [keys], 'local');
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
        init.append("chrome.storage.local._data['blattam-tabs'] = " + json.dumps(tabs, ensure_ascii=False) + ";")
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
#  BACKGROUND.JS: PLACE-TABS (перенос выделенного батча)
# ==========================================

class TestBackgroundPlaceTabs:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        page.goto("about:blank")
        page.evaluate(MOCK_CHROME)
        page.evaluate(load_file("background.js") + "; 'loaded'")

    def _load(self, names):
        sp = read_storage_raw(self.page, "blattam-spaces")[0]
        self.page.evaluate(
            "chrome.storage.local._data['blattam-tabs'] = " + json.dumps(
                [{"name": n, "url": f"https://{n.lower()}.com", "spaceId": sp} for n in names]) + ";")

    def _urls(self):
        return [t["url"] for t in read_storage_raw(self.page, "blattam-tabs")]

    def test_place_tabs_before_anchor(self):
        # [A B C D], батч [A D] перед C → [B A D C] (порядок батча — исходный)
        self._load(["A", "B", "C", "D"])
        send_msg(self.page, "place-tabs",
                 urls=["https://a.com", "https://d.com"],
                 anchorUrl="https://c.com", side="before")
        assert self._urls() == ["https://b.com", "https://a.com", "https://d.com", "https://c.com"]

    def test_place_tabs_after_anchor(self):
        # [A B C D], батч [A D] после C → [B C A D]
        self._load(["A", "B", "C", "D"])
        send_msg(self.page, "place-tabs",
                 urls=["https://a.com", "https://d.com"],
                 anchorUrl="https://c.com", side="after")
        assert self._urls() == ["https://b.com", "https://c.com", "https://a.com", "https://d.com"]

    def test_place_tabs_anchor_null_to_end(self):
        # [A B C], батч [A B] в конец → [C A B]
        self._load(["A", "B", "C"])
        send_msg(self.page, "place-tabs",
                 urls=["https://a.com", "https://b.com"], anchorUrl=None, side="after")
        assert self._urls() == ["https://c.com", "https://a.com", "https://b.com"]

    def test_place_tabs_sets_group_id(self):
        sp = read_storage_raw(self.page, "blattam-spaces")[0]
        g = call_msg(self.page, "create-group", spaceId=sp["id"], name="Dev")
        self._load(["A", "B", "C"])
        send_msg(self.page, "place-tabs",
                 urls=["https://a.com", "https://b.com"],
                 anchorUrl="https://c.com", side="before", groupId=g["id"])
        tabs = {t["url"]: t for t in read_storage_raw(self.page, "blattam-tabs")}
        assert tabs["https://a.com"]["groupId"] == g["id"]
        assert tabs["https://b.com"]["groupId"] == g["id"]
        assert tabs["https://c.com"].get("groupId") in (None, "")

    def test_place_tabs_member_anchor_keeps_order(self):
        # Якорь — член батча: [A B C], батч [A B] перед B → без изменений
        self._load(["A", "B", "C"])
        send_msg(self.page, "place-tabs",
                 urls=["https://a.com", "https://b.com"],
                 anchorUrl="https://b.com", side="before")
        assert self._urls() == ["https://a.com", "https://b.com", "https://c.com"]

    def test_place_tabs_unknown_anchor_noop(self):
        self._load(["A", "B"])
        send_msg(self.page, "place-tabs",
                 urls=["https://a.com"], anchorUrl="https://nope.com", side="before")
        assert self._urls() == ["https://a.com", "https://b.com"]

    def test_place_tabs_empty_urls_noop(self):
        self._load(["A", "B"])
        send_msg(self.page, "place-tabs", urls=[], anchorUrl="https://b.com", side="before")
        assert self._urls() == ["https://a.com", "https://b.com"]


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
            "chrome.storage.local._data['blattam-tabs'] = "
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
            "chrome.storage.local._data['blattam-tabs'] = "
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
        init = ("chrome.storage.local._data['blattam-tabs'] = "
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
#  BACKGROUND.JS: МИГРАЦИЯ ВКЛАДОК sync → local (Stage 1)
# ==========================================

class TestTabsLocalMigration:
    """blattam-tabs живёт в chrome.storage.local; при загрузке ключ из sync
    копируется в local и удаляется из sync (идемпотентно, детерминированно)."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_bg(self, init_js=""):
        pg = self.page
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME + init_js)
        pg.evaluate(load_file("background.js") + "; 'loaded'")

    def _sync_has_tabs(self):
        return self.page.evaluate("'blattam-tabs' in chrome.storage._data") is True

    def test_migration_sync_to_local(self):
        """(a) sync заполнен, local пуст → вкладки читаются из local, sync-ключ удалён."""
        tabs = [{"name": "A", "url": "https://a.com"}, {"name": "B", "url": "https://b.com"}]
        init = "chrome.storage._data['blattam-tabs'] = " + json.dumps(tabs, ensure_ascii=False) + ";"
        self._load_bg(init)
        assert read_local(self.page, "blattam-tabs") == tabs
        assert not self._sync_has_tabs()

    def test_migration_idempotent(self):
        """(b) повторная загрузка ничего не меняет (local остаётся, sync уже пуст)."""
        tabs = [{"name": "A", "url": "https://a.com"}]
        init = "chrome.storage._data['blattam-tabs'] = " + json.dumps(tabs, ensure_ascii=False) + ";"
        self._load_bg(init)
        first = read_local(self.page, "blattam-tabs")
        spaces_first = read_storage_raw(self.page, "blattam-spaces")
        self.page.evaluate(load_file("background.js") + "; 'reloaded'")
        assert read_local(self.page, "blattam-tabs") == first
        assert [s["id"] for s in read_storage_raw(self.page, "blattam-spaces")] == \
               [s["id"] for s in spaces_first]
        assert not self._sync_has_tabs()

    def test_save_and_crud_use_local(self):
        """(c) обычный save/CRUD пишет в local и читает из local (sync не трогается)."""
        self._load_bg("")
        send_msg(self.page, "add-tab", name="New", url="https://new.com")
        tabs = read_local(self.page, "blattam-tabs")
        assert len(tabs) == 1 and tabs[0]["name"] == "New"
        assert not self._sync_has_tabs()
        send_msg(self.page, "rename-tab", index=0, name="Renamed")
        assert read_local(self.page, "blattam-tabs")[0]["name"] == "Renamed"
        send_msg(self.page, "delete", index=0)
        assert read_local(self.page, "blattam-tabs") == []
        assert not self._sync_has_tabs()

    def test_local_wins_stale_sync_removed(self):
        """(d) local уже заполнен + stale sync-ключ → sync удалён, local не тронут."""
        local_tabs = [{"name": "L", "url": "https://l.com"}]
        sync_tabs = [{"name": "S", "url": "https://s.com"}]
        init = (
            "chrome.storage.local._data['blattam-tabs'] = " + json.dumps(local_tabs, ensure_ascii=False) + ";"
            "chrome.storage._data['blattam-tabs'] = " + json.dumps(sync_tabs, ensure_ascii=False) + ";"
        )
        self._load_bg(init)
        assert read_local(self.page, "blattam-tabs") == local_tabs
        assert not self._sync_has_tabs()


# ==========================================
#  VIEW.JS: МИГРАЦИЯ ВКЛАДОК sync → local (Stage 1)
# ==========================================

class TestViewTabsLocalMigration:
    """view.js: миграция blattam-tabs sync → local выполняется ДО первого
    рендера (без мигания) — вкладки читаются из local, sync-ключ удалён."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_view_sync_seeded(self, tabs, spaces):
        """about:blank + mock + данные в СТАРОМ sync + DOM + view.js."""
        pg = self.page
        pg.goto("about:blank")
        pg.evaluate(MOCK_CHROME)
        pg.evaluate(
            "chrome.storage._data['blattam-tabs'] = " + json.dumps(tabs, ensure_ascii=False) + ";"
            "chrome.storage._data['blattam-spaces'] = " + json.dumps(spaces, ensure_ascii=False) + ";")
        pg.evaluate("document.body.innerHTML = " + json.dumps(VIEW_DOM))
        pg.evaluate(load_file("view.js") + "; 'loaded'")
        pg.wait_for_timeout(40)

    def test_view_migration_renders_from_local(self):
        tabs = [
            {"name": "A", "url": "https://a.com", "spaceId": "sp1"},
            {"name": "B", "url": "https://b.com", "spaceId": "sp1"},
        ]
        spaces = [{"id": "sp1", "name": "Main"}]
        self._load_view_sync_seeded(tabs, spaces)
        # Рендер из local после миграции
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 2
        # Вкладки в local, sync-ключ удалён
        assert read_local(self.page, "blattam-tabs") == tabs
        assert self.page.evaluate("'blattam-tabs' in chrome.storage._data") is False


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
        lbl = self.page.evaluate("document.querySelector('.loose-label .loose-name') && document.querySelector('.loose-label .loose-name').textContent")
        assert lbl == "Без группы"
        # ☑-кнопка стоит в той же строке (выбор всех негрупповых вкладок)
        assert self.page.evaluate("document.querySelector('.loose-label .loose-select') !== null")

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
#  VIEW.JS: ДРОП КАРТОЧКИ НА БАР ГРУППЫ (карточка не переезжает в группу)
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

    def test_drop_on_empty_gbar_moves_card_into_group(self):
        # Пустая группа (нет видимых карточек): шапка принимает карточку
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "T", "url": "https://t.com", "spaceId": "sp1"}])
        self._drag_drop_to_gbar(0)
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "place-tab" and msg["anchorIndex"] is None
        assert msg["groupId"] == "g1"
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

    def test_dragover_card_arms_empty_gbar_and_dragleave_clears(self):
        # Пустая группа: dragover карточки армит шапку (drop-over), dragleave снимает
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
        # Dragover не трогает состояние сворачивания группы
        assert read_storage_raw(self.page, "blattam-groups")[0]["collapsed"] is False

    def test_click_right_after_drop_does_not_toggle_collapsed_group(self):
        # Свернутая группа: клик по шапке сразу ПОСЛЕ дропа (некоторые
        # браузеры генерируют клик после drop) группу НЕ раскрывает;
        # вкладка уезжает в группу (счётчик «1 вкладка»)
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": True},
        ], tabs=[{"name": "T", "url": "https://t.com", "spaceId": "sp1"}])
        self._drag_drop_to_gbar(0)
        self.page.wait_for_timeout(30)
        self.page.evaluate("document.querySelector('.gbar').click()")
        self.page.wait_for_timeout(30)
        assert read_storage_raw(self.page, "blattam-tabs")[0]["groupId"] == "g1"
        assert read_storage_raw(self.page, "blattam-groups")[0]["collapsed"] is True
        count = self.page.evaluate("document.querySelector('.gbar .gcount').textContent")
        assert count == "1 вкладка"

    def test_plain_click_on_bar_still_toggles(self):
        # Без драга: клик по шапке как раньше сворачивает/разворачивает
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "T", "url": "https://t.com", "spaceId": "sp1", "groupId": "g1"}])
        self.page.evaluate("document.querySelector('.gbar').click()")
        self.page.wait_for_timeout(30)
        assert read_storage_raw(self.page, "blattam-groups")[0]["collapsed"] is True
        self.page.evaluate("document.querySelector('.gbar').click()")
        self.page.wait_for_timeout(30)
        assert read_storage_raw(self.page, "blattam-groups")[0]["collapsed"] is False

    def test_reorder_drop_then_click_target_bar_no_toggle(self):
        # Шапку перетащили на другую, затем клик по целевой шапке
        # (пост-дроп-клик) — целевая группа не сворачивается
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
            {"id": "g2", "name": "Work", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "A", "url": "https://a.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "B", "url": "https://b.com", "spaceId": "sp1", "groupId": "g2"},
        ])
        self.page.evaluate("""() => {
          const bars = [...document.querySelectorAll('.gbar')];
          const src = bars.find(b => b.dataset.groupId === 'g1');
          const dst = bars.find(b => b.dataset.groupId === 'g2');
          const dt = new DataTransfer();
          src.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          dst.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientY: 0}));
          dst.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true, clientY: 0}));
          src.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        }""")
        self.page.wait_for_timeout(30)
        self.page.evaluate("document.querySelector('.gbar[data-group-id=\"g2\"]').click()")
        self.page.wait_for_timeout(30)
        groups = {g["id"]: g for g in read_storage_raw(self.page, "blattam-groups")}
        assert groups["g1"]["collapsed"] is False and groups["g2"]["collapsed"] is False


# ==========================================
#  VIEW.JS: ЛОЖНЫЙ КЛИК ПО ШАПКЕ ПОСЛЕ ДРОПА (медленная перерисовка)
# ==========================================

class TestPostDropClickSlowRender:
    """Пользователь: 3 группы, первая раскрыта. Карточку из g1 перетаскивают
    в СВЁРНУТУЮ g2 (g3 при этом раскрыта → много видимых карточек →
    renderTabs блокирует поток >500ms). Браузерный post-drop клик по шапке
    g2 приходит ПОСЛЕ перерисовки — за 500ms-окном lastDragEndAt — и без
    one-shot-флага раскрывает g2."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _drag_card_to_g2(self, src_idx=0):
        self.page.evaluate("""(idx) => {
          const card = document.querySelectorAll('.tab-card')[idx];
          const bar = document.querySelector('.gbar[data-group-id="g2"]');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          bar.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          bar.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        }""", src_idx)

    def _load_three_groups(self):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
            {"id": "g2", "name": "Work", "spaceId": "sp1", "collapsed": True},
            {"id": "g3", "name": "More", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "A", "url": "https://a.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "B", "url": "https://b.com", "spaceId": "sp1", "groupId": "g3"},
        ])

    def test_slow_postdrop_click_does_not_open_collapsed_target(self):
        # Ложный post-drop клик (без mousedown) приходит >500ms после
        # dragend — за окном временной защиты: g2 остаётся свёрнутой,
        # а вкладка в ней (groupId = g2)
        self._load_three_groups()
        self._drag_card_to_g2(0)
        self.page.wait_for_timeout(600)
        self.page.evaluate("document.querySelector('.gbar[data-group-id=\\\"g2\\\"]').click()")
        self.page.wait_for_timeout(30)
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert [t for t in tabs if t["url"] == "https://a.com"][0]["groupId"] == "g2"
        groups = {g["id"]: g for g in read_storage_raw(self.page, "blattam-groups")}
        assert groups["g2"]["collapsed"] is True
        # g1 auto-collapse: drop moved its last tab out (g3 keeps its member)
        assert groups["g1"]["collapsed"] is True and groups["g3"]["collapsed"] is False

    def test_plain_click_without_drag_still_toggles(self):
        # Регрессия: без предшествующего драга клик по шапке сворачивает/
        # раскрывает как раньше
        self._load_three_groups()
        self.page.evaluate("document.querySelector('.gbar[data-group-id=\\\"g1\\\"]').click()")
        self.page.wait_for_timeout(30)
        groups = {g["id"]: g for g in read_storage_raw(self.page, "blattam-groups")}
        assert groups["g1"]["collapsed"] is True
        self.page.evaluate("document.querySelector('.gbar[data-group-id=\\\"g1\\\"]').click()")
        self.page.wait_for_timeout(30)
        groups = {g["id"]: g for g in read_storage_raw(self.page, "blattam-groups")}
        assert groups["g1"]["collapsed"] is False

    def test_real_user_click_after_drop_still_toggles(self):
        # Реальное нажатие ПОЛЬЗОВАТЕЛЯ после дропа (mousedown + click,
        # Playwright-клик) не глотается: mousedown сбрасывает one-shot флаг
        # раньше клика, g2 раскрывается ровно один раз
        self._load_three_groups()
        self._drag_card_to_g2(0)
        self.page.wait_for_timeout(600)
        self.page.locator('.gbar[data-group-id="g2"]').click()
        self.page.wait_for_timeout(30)
        groups = {g["id"]: g for g in read_storage_raw(self.page, "blattam-groups")}
        assert groups["g2"]["collapsed"] is False
        # флаг гасится одноразово — второй клик сворачивает обратно
        self.page.locator('.gbar[data-group-id="g2"]').click()
        self.page.wait_for_timeout(30)
        groups = {g["id"]: g for g in read_storage_raw(self.page, "blattam-groups")}
        assert groups["g2"]["collapsed"] is True


class TestPostDropClickBeforeDragend:
    """Реальный Chrome генерирует ложный клик на drop-цели в момент дропа —
    ДО dragend источника (замер: drop → click → dragend). Флаг, поставленный
    только на dragend, его не ловит: свёрнутая целевая группа раскрывалась.
    Плюс: тёплая заглушка (ghost-slot) не должна оставаться в сетке после
    дропа на шапке группы и не должна «воскресать» для отсоединённой карточки."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load_seeded(self):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Work", "spaceId": "sp1", "collapsed": True},
            {"id": "g2", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "A", "url": "https://a.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "B", "url": "https://b.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "C", "url": "https://c.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "S", "url": "https://s.com", "spaceId": "sp1", "groupId": "g2"},
        ])

    def test_spurious_click_at_drop_time_does_not_open_collapsed_target(self):
        # Ложный клик приходит в момент дропа — ДО dragend источника: группа
        # остаётся свёрнутой, а вкладка в неё переезжает
        self._load_seeded()
        self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const bar = document.querySelector('.gbar[data-group-id="g1"]');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          bar.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          bar.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
          // Ложный клик браузера: по (уже перерисованной) шапке, без mousedown
          document.querySelector('.gbar[data-group-id="g1"]').click();
          // И только потом — dragend источника
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        self.page.wait_for_timeout(30)
        groups = {g["id"]: g for g in read_storage_raw(self.page, "blattam-groups")}
        assert groups["g1"]["collapsed"] is True
        # g2 auto-collapse: drop moved its only tab into g1
        assert groups["g2"]["collapsed"] is True
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert [t for t in tabs if t["url"] == "https://s.com"][0]["groupId"] == "g1"
        rendered = self.page.evaluate("""(() => {
          let cur = document.querySelector('.gbar[data-group-id="g1"]').nextElementSibling, n = 0;
          while (cur && !cur.classList.contains('gbar') && !cur.classList.contains('add-group-row')) {
            if (cur.classList.contains('tab-card')) n++;
            cur = cur.nextElementSibling;
          }
          return n;
        })()""")
        assert rendered == 0

    def test_spurious_click_after_slow_render_before_dragend(self):
        # Ложный клик приходит ПОСЛЕ медленной перерисовки (свежий элемент
        # шапки), но всё ещё до dragend источника — one-shot флаг должен
        # пережить перерисовку
        self._load_seeded()
        self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const bar = document.querySelector('.gbar[data-group-id="g1"]');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          bar.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          bar.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
        })()""")
        self.page.wait_for_timeout(600)  # за 500ms-окном lastDragEndAt
        self.page.evaluate("document.querySelector('.gbar[data-group-id=g1]').click()")
        self.page.evaluate("""(() => {
          const cards = document.querySelectorAll('.tab-card');
          if (cards.length) cards[cards.length - 1].dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        self.page.wait_for_timeout(30)
        groups = {g["id"]: g for g in read_storage_raw(self.page, "blattam-groups")}
        assert groups["g1"]["collapsed"] is True
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert [t for t in tabs if t["url"] == "https://s.com"][0]["groupId"] == "g1"

    def test_real_click_after_suppressed_spurious_click_still_toggles(self):
        # Регрессия: реальное нажатие ПОЛЬЗОВАТЕЛЯ после ложного клика
        # (mousedown сбрасывает one-shot флаг раньше клика) сворачивает группу
        self._load_seeded()
        self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const bar = document.querySelector('.gbar[data-group-id="g1"]');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          bar.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
          document.querySelector('.gbar[data-group-id="g1"]').click(); // ложный
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        self.page.wait_for_timeout(600)  # за 500ms-окном lastDragEndAt
        self.page.locator('.gbar[data-group-id="g1"]').click()  # реальное нажатие
        self.page.wait_for_timeout(30)
        groups = {g["id"]: g for g in read_storage_raw(self.page, "blattam-groups")}
        assert groups["g1"]["collapsed"] is False

    def test_ghost_slot_not_created_for_detached_source_card(self):
        # Перерисовка во время драга уносит исходную карточку из DOM: отложенная
        # заглушка для отсоединённой карточки не вставляется (и не «воскресает»
        # при следующем драге — там появится свежая заглушка)
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "T1", "url": "https://t1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "T2", "url": "https://t2.com", "spaceId": "sp1", "groupId": "g1"},
        ])
        self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          card.remove(); // перерисовка унесла карточку ДО отложенного создания заглушки
          return 'ok';
        })()""")
        self.page.wait_for_timeout(20)
        assert self.page.evaluate("document.querySelector('.tab-ghost-slot')") is None
        # Следующий драг: заглушка появляется заново, под живой карточкой
        self.page.evaluate("""(() => {
          const c = document.querySelector('.tab-card');
          const dt = new DataTransfer();
          c.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
        })()""")
        self.page.wait_for_timeout(20)
        assert self.page.evaluate("!!document.querySelector('.tab-ghost-slot')") is True
        self.page.evaluate("(() => { const c = document.querySelector('.tab-card:not(.dragging)') || document.querySelector('.tab-card'); if (c) c.dispatchEvent(new DragEvent('dragend', {bubbles: true})); })()")

    def test_ghost_slot_removed_by_gbar_drop_of_moving_card(self):
        # Дроп карточки на шапку свёрнутой группы (карточка уезжает): тёплая
        # заглушка уходит из сетки, не дожидаясь dragend
        self._load_seeded()
        self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const bar = document.querySelector('.gbar[data-group-id="g1"]');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
        })()""")
        self.page.wait_for_timeout(20)  # отложенная заглушка уже создана
        assert self.page.evaluate("!!document.querySelector('.tab-ghost-slot')") is True
        self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const bar = document.querySelector('.gbar[data-group-id="g1"]');
          const dt = new DataTransfer();
          bar.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          bar.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
        })()""")
        self.page.wait_for_timeout(20)
        assert self.page.evaluate("document.querySelector('.tab-ghost-slot')") is None


# ==========================================
#  VIEW.JS: ПЕРЕНОС ВЫДЕЛЕННОГО БАТЧА (drag одного — уезжают все выделенные)
# ==========================================

class TestSelectedBatchDnD:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}]
    TABS4 = [
        {"name": "A", "url": "https://a.com", "spaceId": "sp1"},
        {"name": "B", "url": "https://b.com", "spaceId": "sp1"},
        {"name": "C", "url": "https://c.com", "spaceId": "sp1"},
        {"name": "D", "url": "https://d.com", "spaceId": "sp1"},
    ]

    def _select(self, idxs):
        self.page.evaluate("""(idxs) => {
          for (const i of idxs) document.querySelectorAll('.tab-card .tab-select')[i].click();
        }""", idxs)

    def _drag_start(self, idx):
        self.page.evaluate("""(idx) => {
          const card = document.querySelectorAll('.tab-card')[idx];
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          window.__batchDt = dt;
        }""", idx)

    def _drop_before_card(self, idx):
        # drop на #tabs-list в левом краю строки карточки idx (anchor — «before» неё)
        self.page.evaluate("""(idx) => {
          const target = document.querySelectorAll('.tab-card')[idx];
          const r = target.getBoundingClientRect();
          document.getElementById('tabs-list').dispatchEvent(new DragEvent('drop', {
            dataTransfer: window.__batchDt, bubbles: true, cancelable: true,
            clientX: r.left + 4, clientY: r.top + r.height / 2
          }));
        }""", idx)

    def _drag_end(self, idx):
        self.page.evaluate("""(idx) => {
          const card = document.querySelectorAll('.tab-card')[idx];
          if (card) card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        }""", idx)

    def test_drag_selected_hides_only_dragged_one_slot(self):
        # Рендер батча «как одна вкладка»: скрыта ТОЛЬКО перетаскиваемая карточка,
        # остальные выделенные видны, заглушка — одна (клон-призрака нет)
        load_view(self.page, spaces=self.SP, tabs=self.TABS4)
        self._select([0, 3])
        self._drag_start(3)
        self.page.wait_for_timeout(50)  # отложенное скрытие + ghost-slot
        d = json.loads(self.page.evaluate("""(() => {
          const cards = [...document.querySelectorAll('.tab-card')];
          return JSON.stringify({
            hidden: cards.filter(c => c.style.display === 'none').length,
            visible: cards.filter(c => c.style.display !== 'none').length,
            slots: document.querySelectorAll('.tab-ghost-slot').length,
            clones: document.querySelectorAll('.tab-ghost').length,
            dragging: cards.filter(c => c.classList.contains('dragging')).length
          });
        })()"""))
        assert d == {"hidden": 1, "visible": 3, "slots": 1, "clones": 0, "dragging": 1}, d
        self._drag_end(3)
        # Без следа: карточка возвращена, заглушка убрана
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 4
        assert self.page.evaluate("document.querySelectorAll('.tab-ghost-slot').length") == 0

    def test_drop_selected_batch_moves_all_in_original_order(self):
        # Выделены A и D; перетаскиваем D «перед B» → батч [A D] уезжает блоком:
        # [A B C D] → [A D B C]; сообщение — place-tabs с исходным порядком батча
        load_view(self.page, spaces=self.SP, tabs=self.TABS4)
        self._select([0, 3])
        self._drag_start(3)
        self.page.wait_for_timeout(50)
        self._drop_before_card(1)  # B
        self.page.wait_for_timeout(30)
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "place-tabs"
        assert msg["urls"] == ["https://a.com", "https://d.com"]  # исходный порядок
        assert msg["anchorUrl"] == "https://b.com" and msg["side"] == "before"
        assert msg["groupId"] is None
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert [t["url"] for t in tabs] == [
            "https://a.com", "https://d.com", "https://b.com", "https://c.com"]
        # Перерисовка: порядок карточек совпадает, выбор (по URL) пережил её
        names = json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('.tab-card .tab-name')].map(e => e.textContent))"))
        assert names == ["A", "D", "B", "C"]
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 2
        self._drag_end(3)

    def test_drop_batch_no_change_is_noop(self):
        # Выделены A и B; перетаскиваем A «перед B» (якорь — член батча):
        # порядок и группы не меняются → ни place-tab, ни place-tabs не шлется
        load_view(self.page, spaces=self.SP, tabs=self.TABS4)
        self._select([0, 1])
        self._drag_start(0)
        self.page.wait_for_timeout(50)
        self._drop_before_card(1)  # B
        self.page.wait_for_timeout(30)
        actions = json.loads(self.page.evaluate(
            "JSON.stringify(chrome.runtime.messagesSent.map(m => m.action))"))
        assert "place-tab" not in actions and "place-tabs" not in actions, actions
        assert [t["url"] for t in read_storage_raw(self.page, "blattam-tabs")] == [
            t["url"] for t in self.TABS4]
        self._drag_end(0)

    def test_drag_unselected_moves_single_tab(self):
        # Выделена только C; перетаскиваем её «перед A» — обычный place-tab
        load_view(self.page, spaces=self.SP, tabs=self.TABS4)
        self._select([2])
        self._drag_start(2)
        self.page.wait_for_timeout(50)
        self._drop_before_card(0)  # A
        self.page.wait_for_timeout(30)
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "place-tab" and msg["anchorIndex"] == 0 and msg["side"] == "before"
        assert [t["url"] for t in read_storage_raw(self.page, "blattam-tabs")] == [
            "https://c.com", "https://a.com", "https://b.com", "https://d.com"]
        self._drag_end(0)

    def test_chip_drop_moves_whole_batch(self):
        # Выделены A и C; дроп на чип другого пространства → move-tab для ОБЕИХ,
        # группы очищаются; невыделенная B остаётся
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}, {"id": "sp2", "name": "Work"}],
                  tabs=self.TABS4)
        self._select([0, 2])
        self._drag_start(0)
        self.page.wait_for_timeout(50)
        self.page.evaluate("""() => {
          const chip = document.querySelector('.space-chip[data-space-id="sp2"]');
          chip.dispatchEvent(new DragEvent('drop', {dataTransfer: window.__batchDt, bubbles: true, cancelable: true}));
        }""")
        self.page.wait_for_timeout(30)
        moves = json.loads(self.page.evaluate(
            "JSON.stringify(chrome.runtime.messagesSent.filter(m => m.action === 'move-tab'))"))
        assert len(moves) == 2, moves
        tabs = read_storage_raw(self.page, "blattam-tabs")
        by_url = {t["url"]: t for t in tabs}
        assert by_url["https://a.com"]["spaceId"] == "sp2"
        assert by_url["https://c.com"]["spaceId"] == "sp2"
        assert by_url["https://b.com"]["spaceId"] == "sp1"
        self._drag_end(0)

    def test_drop_on_empty_group_slot_moves_batch(self):
        # Выделены A и B (без группы); дроп на слот пустой группы → place-tabs
        # целиком в группу (anchorUrl null, в конец списка); счётчик «2 вкладки»
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "A", "url": "https://a.com", "spaceId": "sp1"},
            {"name": "B", "url": "https://b.com", "spaceId": "sp1"},
        ])
        self._select([0, 1])
        self._drag_start(0)
        self.page.wait_for_timeout(50)
        self.page.evaluate("""() => {
          const slot = document.querySelector('.group-empty-slot');
          slot.dispatchEvent(new DragEvent('drop', {dataTransfer: window.__batchDt, bubbles: true, cancelable: true}));
        }""")
        self.page.wait_for_timeout(30)
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "place-tabs"
        assert msg["urls"] == ["https://a.com", "https://b.com"]
        assert msg["anchorUrl"] is None and msg["groupId"] == "g1"
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert all(t["groupId"] == "g1" for t in tabs)
        count = self.page.evaluate("document.querySelector('.gbar .gcount').textContent")
        assert count == "2 вкладки"
        self._drag_end(0)


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

    def _token_rgb(self, css_part, token):
        # Токен hex из текста theme.css → 'rgb(r, g, b)' как отдаёт getComputedStyle
        m = re.search(rf"{token}:\s*#([0-9a-fA-F]{{3,8}})", css_part)
        assert m, token
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return "rgb({0}, {1}, {2})".format(
            int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    def _token_color(self, css_part, token):
        # Токен цвета из theme.css (hex ИЛИ rgba()) → строка как отдаёт getComputedStyle
        m = re.search(rf"{token}:\s*(#[0-9a-fA-F]{{3,8}}|rgba?\([^)]*\))", css_part)
        assert m, token
        v = m.group(1)
        if v.startswith("#"):
            h = v[1:]
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            return "rgb({0}, {1}, {2})".format(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        nums = [x.strip() for x in v.split("(", 1)[1].strip().strip("()").split(",")]
        return "rgba({0}, {1}, {2}, {3})".format(nums[0], nums[1], nums[2], nums[3])

    def test_gbar_hairline_and_drag_slot_warm_tint(self):
        # «Штрих» (обе темы): шапка группы — БЕЗ заливки (прозрачный фон) +
        # 1px-линия сверху (border-top из токена --line2), заглушка перетаскивания
        # (клон-призрака нет) — тёплый тон; computed-значения равны токенам
        # theme.css (значения парсятся из файла, не захардкожены)
        css = load_file("theme.css")
        dark_at = css.index('[data-theme="dark"] {')
        parts = {"light": css[:dark_at], "dark": css[dark_at:]}
        for theme in ("light", "dark"):
            load_view(self.page, theme=theme, spaces=[{"id": "sp1", "name": "Main"}],
                      groups=[{"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False}],
                      tabs=[
                          {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
                          {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
                      ])
            self._inject_real_styles()
            self.page.wait_for_timeout(300)  # конец background-транзишена (.gbar, .1s)
            d = json.loads(self.page.evaluate("""(() => {
              const cs = getComputedStyle(document.querySelector('.gbar'));
              const card = document.querySelector('.tab-card');
              const dt = new DataTransfer();
              card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
              return JSON.stringify({
                barBg: cs.backgroundColor,
                barBorderTopWidth: cs.borderTopWidth,
                barBorderTopStyle: cs.borderTopStyle,
                barBorderTopColor: cs.borderTopColor,
                barShadow: cs.boxShadow,
                noClone: !document.querySelector('.tab-ghost')
              });
            })()"""))
            self.page.wait_for_timeout(50)  # заглушка создаётся отложенно (setTimeout(0) в dragstart)
            s = json.loads(self.page.evaluate("""(() => {
              const slot = document.querySelector('.tab-ghost-slot');
              const card = document.querySelector('.tab-card');
              return JSON.stringify({
                srcHidden: card.style.display === 'none',
                slotBg: slot ? getComputedStyle(slot).backgroundColor : null,
                slotBorder: slot ? getComputedStyle(slot).borderTopStyle + ':' + getComputedStyle(slot).borderTopColor : null
              });
            })()"""))
            fin = json.loads(self.page.evaluate("""(() => {
              const card = document.querySelector('.tab-card');
              card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
              return JSON.stringify({
                noCloneAfter: !document.querySelector('.tab-ghost'),
                slotGone: !document.querySelector('.tab-ghost-slot'),
                srcRestored: card.style.display !== 'none'
              });
            })()"""))
            # «Штрих»: заливки нет — фон прозрачный
            assert d["barBg"] == "rgba(0, 0, 0, 0)", (theme, d)
            # hairline: 1px-линия сверху из токена --line2
            assert d["barBorderTopWidth"] == "1px", (theme, d)
            assert d["barBorderTopStyle"] == "solid", (theme, d)
            assert d["barBorderTopColor"] == self._token_color(parts[theme], "--line2"), (theme, d)
            # Контур-линия шапки убран: тени нет (или нет 1px-контура)
            assert d["barShadow"] == "none" or "1px" not in d["barShadow"], (theme, d)
            # Клон-призрака нет; единственный индикатор — тёплая заглушка
            assert d["noClone"] is True, (theme, d)
            assert s["srcHidden"] is True, (theme, s)
            assert s["slotBg"] == self._token_color(parts[theme], "--ghost-bg"), (theme, s)
            assert s["slotBorder"].startswith("dashed") and self._token_color(parts[theme], "--ghost-ring") in s["slotBorder"], (theme, s)
            # dragend: заглушка убрана, карточка возвращена в слот, без следов
            assert fin["noCloneAfter"] is True and fin["slotGone"] is True and fin["srcRestored"] is True, (theme, fin)

    SCRATCH = r"C:\Users\DI\AppData\Local\hermes\cache\scratch"

    def test_capture_theme_snapshots(self):
        # Снимки «для глаза»: светлая/тёмная тема — (1) группа с шапкой «Штрих»,
        # (2) перетаскивание с тёплой заглушкой
        for theme in ("light", "dark"):
            load_view(self.page, theme=theme, spaces=[{"id": "sp1", "name": "Main"}],
                      groups=[{"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False}],
                      tabs=[
                          {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
                          {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
                          {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
                      ])
            self._inject_real_styles()
            self.page.wait_for_timeout(300)  # конец background-транзишена (.gbar, .1s)
            group_png = self.SCRATCH + f"\\bt_scr_{theme}_group.png"
            self.page.screenshot(path=group_png)
            # Тёплая заглушка: dragstart + dragover в центре той же карточки
            self.page.evaluate("""(() => {
              const card = document.querySelector('#tabs-list .tab-card');
              const dt = new DataTransfer();
              card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true, clientX: 200, clientY: 150}));
              const b = card.getBoundingClientRect();
              document.getElementById('tabs-list').dispatchEvent(new DragEvent('dragover', {
                dataTransfer: dt, bubbles: true, cancelable: true,
                clientX: b.left + b.width / 2, clientY: b.top + b.height / 2
              }));
            })()""")
            self.page.wait_for_timeout(60)
            ghost_png = self.SCRATCH + f"\\bt_scr_{theme}_ghost.png"
            self.page.screenshot(path=ghost_png)
            self.page.evaluate("""(() => {
              document.querySelector('#tabs-list .tab-card')
                .dispatchEvent(new DragEvent('dragend', {bubbles: true}));
            })()""")
            for p in (group_png, ghost_png):
                assert os.path.exists(p), p
                assert os.path.getsize(p) > 5 * 1024, p


# ==========================================
#  VIEW.JS: ШАПКА ГРУППЫ «ШТРИХ» (без заливки: hairline --line2, приглушённое имя)
# ==========================================

class TestGroupBarHairline:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}]
    GROUPS = [{"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False}]
    TABS = [
        {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
    ]
    SCRATCH = r"C:\Users\DI\AppData\Local\hermes\cache\scratch"

    def _inject_real_styles(self):
        # Харнес ставит только body.innerHTML — подгружаем настоящие стили
        # (theme.css + <style> view.html), чтобы computed-значения были реальными
        theme = load_file("theme.css")
        html = load_file("view.html")
        style = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate(
            "(styles) => { var st = document.createElement('style'); st.textContent = styles; document.head.appendChild(st); }",
            [theme + "\n" + style])

    def _parts(self):
        css = load_file("theme.css")
        dark_at = css.index('[data-theme="dark"] {')
        return {"light": css[:dark_at], "dark": css[dark_at:]}

    def _token_color(self, css_part, token):
        # Токен цвета из theme.css (hex ИЛИ rgba()) → строка как отдаёт getComputedStyle
        m = re.search(rf"{token}:\s*(#[0-9a-fA-F]{{3,8}}|rgba?\([^)]*\))", css_part)
        assert m, token
        v = m.group(1)
        if v.startswith("#"):
            h = v[1:]
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            return "rgb({0}, {1}, {2})".format(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        nums = [x.strip() for x in v.split("(", 1)[1].strip().strip("()").split(",")]
        return "rgba({0}, {1}, {2}, {3})".format(nums[0], nums[1], nums[2], nums[3])

    def test_gbar_hairline_computed_styles(self):
        # «Штрих» (обе темы): .gbar — прозрачный фон, высота 26px, hairline сверху
        # (--line2); имя — приглушённое 12px (--text-soft); chevron --text-faint
        parts = self._parts()
        for theme in ("light", "dark"):
            load_view(self.page, theme=theme, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
            self._inject_real_styles()
            self.page.wait_for_timeout(300)
            d = json.loads(self.page.evaluate("""(() => {
              const cs = getComputedStyle(document.querySelector('.gbar'));
              const nm = getComputedStyle(document.querySelector('.gbar .gname'));
              const ch = getComputedStyle(document.querySelector('.gbar .chev'));
              return JSON.stringify({
                barBg: cs.backgroundColor,
                barHeight: cs.height,
                borderTopWidth: cs.borderTopWidth,
                borderTopColor: cs.borderTopColor,
                nameSize: nm.fontSize,
                nameColor: nm.color,
                chevColor: ch.color
              });
            })()"""))
            assert d["barBg"] == "rgba(0, 0, 0, 0)", (theme, d)
            assert d["barHeight"] == "26px", (theme, d)
            assert d["borderTopWidth"] == "1px", (theme, d)
            assert d["borderTopColor"] == self._token_color(parts[theme], "--line2"), (theme, d)
            assert d["nameSize"] == "12px", (theme, d)
            assert d["nameColor"] == self._token_color(parts[theme], "--text-soft"), (theme, d)
            assert d["chevColor"] == self._token_color(parts[theme], "--text-faint"), (theme, d)

    def test_gbar_hover_background_and_controls(self):
        # «Штрих» (обе темы): до hover контролы скрыты; hover — лёгкий фон (--hover)
        # + контролы (☑ ✎ ✕) появляются
        parts = self._parts()
        for theme in ("light", "dark"):
            load_view(self.page, theme=theme, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
            self._inject_real_styles()
            self.page.wait_for_timeout(300)
            self.page.mouse.move(0, 0)  # нейтральная позиция: предыдущий hover(.gbar) не переживает load_view
            self.page.wait_for_timeout(200)  # пересчёт :hover + конец exit-транзишена opacity .12s
            before = self.page.evaluate(
                "getComputedStyle(document.querySelector('.gbar .gselect')).opacity")
            assert before == "0", (theme, before)
            self.page.hover(".gbar")
            self.page.wait_for_timeout(300)  # конец транзишенов background .1s / opacity .12s
            d = json.loads(self.page.evaluate("""(() => {
              const cs = getComputedStyle(document.querySelector('.gbar'));
              const q = s => getComputedStyle(document.querySelector(s)).opacity;
              return JSON.stringify({
                barBg: cs.backgroundColor,
                selOpacity: q('.gbar .gselect'),
                renOpacity: q('.gbar .grename'),
                delOpacity: q('.gbar .gdel')
              });
            })()"""))
            assert d["barBg"] == self._token_color(parts[theme], "--hover"), (theme, d)
            assert d["selOpacity"] == "1", (theme, d)
            assert d["renOpacity"] == "1", (theme, d)
            assert d["delOpacity"] == "1", (theme, d)

    def test_capture_gbar_hairline_snapshots(self):
        # Снимки «для глаза»: светлая/тёмная тема — группа с шапкой «Штрих»
        for theme in ("light", "dark"):
            load_view(self.page, theme=theme, spaces=self.SP, groups=self.GROUPS,
                      tabs=[
                          {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
                          {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
                          {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
                      ])
            self._inject_real_styles()
            self.page.wait_for_timeout(300)
            png = self.SCRATCH + "\\bt_scr_hairline_" + theme + ".png"
            self.page.screenshot(path=png)
            assert os.path.exists(png), png
            assert os.path.getsize(png) > 5 * 1024, png


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
          const dt = new DataTransfer();
          window.__dt = dt;
          cards[srcIdx].dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          // Позиция: 'before' — левая половина цели, 'after' — правая
          const r = cards[dstIdx].getBoundingClientRect();
          const clientX = half === 'before' ? r.left + r.width * 0.25 : r.left + r.width * 0.75;
          const clientY = half === 'before' ? r.top + r.height * 0.25 : r.top + r.height * 0.75;
          cards[dstIdx].dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientX, clientY}));
          cards[dstIdx].dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true, clientX, clientY}));
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
        # place-tab (полный массив + секция): перед якорной вкладкой C
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "place-tab"
        assert msg["index"] == 0 and msg["anchorIndex"] == 2 and msg["side"] == "before"
        assert msg["groupId"] is None

    def test_drop_bottom_half_inserts_after(self):
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
            {"name": "C", "url": "https://c.com"},
        ])
        self._drag_drop_card(0, 2, 'after')
        assert self._tab_names() == ["B", "C", "A"]
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        # конец секции = после последней её вкладки полного массива
        assert msg["action"] == "place-tab"
        assert msg["side"] == "after" and msg["anchorIndex"] == 2

    def test_drop_on_self_noop(self):
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        self._drag_drop_card(0, 0, 'before')
        assert self._tab_names() == ["A", "B"]
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage || null)"))
        assert msg is None or msg.get("action") != "place-tab"

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
        # Выделена только B (не весь батч) — C уезжает одна, выбор и
        # active-карточка переживают перестановку
        self.page.evaluate("document.querySelectorAll('.tab-card .tab-select')[1].click()")
        self.page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true, cancelable: true}))")
        self._drag_drop_card(2, 0, 'before')  # C → перед A
        assert self._tab_names() == ["C", "A", "B"]
        checked = self.page.evaluate("document.querySelectorAll('.tab-select:checked').length")
        bar_hidden = self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')")
        assert checked == 1 and not bar_hidden
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
          window.__dt = dt;
          cards[0].dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const r = cards[1].getBoundingClientRect();
          cards[1].dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientX: r.left + r.width * 0.25, clientY: r.top + r.height * 0.25}));
          // 2px-линия убрана: индикатора-линии нет вообще
          const line = document.querySelector('.tab-gap-line');
          window.__indicatorShown = !!line && line.style.display !== 'none';
          cards[0].dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        assert not self.page.evaluate("window.__indicatorShown")
        assert self._tab_names() == ["A", "B"]
        left = self.page.evaluate("(() => { const l = document.querySelector('.tab-gap-line'); return l && l.style.display !== 'none'; })()")
        dragging = self.page.evaluate("document.querySelectorAll('.tab-card.dragging').length")
        ghost = self.page.evaluate("!!document.querySelector('.tab-ghost')")
        src_display = self.page.evaluate("getComputedStyle(document.querySelectorAll('.tab-card')[0]).display")
        assert not left and dragging == 0 and not ghost
        assert src_display != "none"

    def test_dragover_no_gap_line(self):
        # 2px-линия убрана из перетаскивания карточек: во время dragover
        # индикатор-линия не появляется (единственный индикатор — ghost-slot)
        load_view(self.page, tabs=[
            {"name": "A", "url": "https://a.com"},
            {"name": "B", "url": "https://b.com"},
        ])
        state = self.page.evaluate("""(() => {
          const cards = document.querySelectorAll('.tab-card');
          const dt = new DataTransfer();
          window.__dt = dt;
          cards[0].dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const line = () => {
            const l = document.querySelector('.tab-gap-line');
            return !!l && l.style.display !== 'none';
          };
          const nr = cards[1].getBoundingClientRect();
          // Левая половина B — зазор ПЕРЕД B
          cards[1].dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientX: nr.left + nr.width * 0.25, clientY: nr.top + nr.height * 0.25}));
          const before = line();
          // Правая половина B — зазор ПОСЛЕ B
          cards[1].dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientX: nr.left + nr.width * 0.75, clientY: nr.top + nr.height * 0.75}));
          const after = line();
          // Курсор вне списка
          document.body.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientX: 5, clientY: 5}));
          const cleared = !line();
          cards[0].dispatchEvent(new DragEvent('dragend', {bubbles: true}));
          return JSON.stringify({before, after, cleared});
        })()""")
        s = json.loads(state)
        assert s == {"before": False, "after": False, "cleared": True}

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
#  VIEW.JS: DnD TOBY-STYLE (призрак + 2px-линия в зазоре)
# ==========================================

class TestTobyDnD:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    TABS3 = [
        {"name": "A", "url": "https://a.com"},
        {"name": "B", "url": "https://b.com"},
        {"name": "C", "url": "https://c.com"},
    ]

    def _tab_names(self):
        return json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.name));
        })()"""))

    def _dom_names(self):
        return json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('#tabs-list .tab-card .tab-name')].map(e => e.textContent.trim()))"))

    def _start_drag(self, idx=0):
        """dragstart карточки idx; window.__dt — DataTransfer для следующих событий."""
        self.page.evaluate("""(idx) => {
          const card = document.querySelectorAll('.tab-card')[idx];
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
        }""", idx)
        self.page.wait_for_timeout(50)  # дать таймауту display:none сработать

    def _hover(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('dragover', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _drop(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('drop', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _end_drag(self):
        self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          if (card) card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")

    def _line_rect(self):
        return self.page.evaluate("""(() => {
          const l = document.querySelector('.tab-gap-line');
          if (!l || l.style.display === 'none') return null;
          const r = l.getBoundingClientRect();
          return {left: r.left, right: r.right, top: r.top, height: r.height, width: r.width};
        })()""")

    def _ghost_rect(self):
        return self.page.evaluate("""(() => {
          const g = document.querySelector('.tab-ghost');
          if (!g) return null;
          const r = g.getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2, width: r.width, height: r.height};
        })()""")

    def test_source_hidden_no_clone_warm_slot(self):
        # Клон-призрака нет: оригинал исчез из слота (display:none), в сетке
        # единственный индикатор — заглушка; за курсором — нативный drag-образ
        load_view(self.page, tabs=self.TABS3)
        self._start_drag()
        state = self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          return JSON.stringify({
            display: getComputedStyle(card).display,
            noClone: !document.querySelector('.tab-ghost'),
            slot: !!document.querySelector('.tab-ghost-slot')
          });
        })()""")
        s = json.loads(state)
        assert s["display"] == "none"          # оригинал исчез из слота
        assert s["noClone"] is True            # клон-призрака нет
        assert s["slot"] is True               # заглушка — единственный индикатор
        self._end_drag()

    def test_no_gap_line_between_cards(self):
        # 2px-линия убрана: в зазоре между карточками — только ghost-slot
        load_view(self.page, tabs=self.TABS3)
        self._start_drag()
        # A скрыта: B и C поднялись; зазор между B и C — нижняя половина B
        r = self.page.evaluate("""(() => {
          const c = document.querySelectorAll('.tab-card')[1];
          const b = c.getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        })()""")
        self._hover(r["left"] + r["width"] * 0.75, r["top"] + r["height"] * 0.75)
        out = self.page.evaluate("""(() => {
          const l = document.querySelector('.tab-gap-line');
          const order = [...document.getElementById('tabs-list').children].map(c =>
            c.classList.contains('tab-card') ? 'card' :
            c.classList.contains('tab-ghost-slot') ? 'slot' :
            c.classList.contains('tab-row-keeper') ? 'keeper' : 'other');
          return JSON.stringify({
            line: !!l && l.style.display !== 'none',
            order: order
          });
        })()""")
        s = json.loads(out)
        assert s["line"] is False  # линии нет вообще
        assert s["order"] == ["card", "card", "slot", "card", "other"]  # A (скрыта), B, [заглушка до C], C — без keeper: ghost в секции
        self._end_drag()

    def test_drop_into_gap(self):
        load_view(self.page, tabs=self.TABS3)
        self._start_drag()
        r = self.page.evaluate("""(() => {
          const b = document.querySelectorAll('.tab-card')[1].getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        })()""")
        self._hover(r["left"] + r["width"] * 0.75, r["top"] + r["height"] * 0.75)
        self._drop(r["left"] + r["width"] * 0.75, r["top"] + r["height"] * 0.75)
        self._end_drag()
        assert self._tab_names() == ["B", "A", "C"]
        assert self._dom_names() == ["B", "A", "C"]

    def test_drop_at_start_and_end(self):
        # Очень начало: перед первой видимой карточкой
        load_view(self.page, tabs=self.TABS3)
        self._start_drag()
        # A скрыта — первая видимая это B; зазор перед B = самое начало
        r = self.page.evaluate("""(() => {
          const b = document.querySelectorAll('.tab-card')[1].getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        })()""")
        self._drop(r["left"] + r["width"] * 0.1, r["top"] + r["height"] * 0.5)
        self._end_drag()
        assert self._tab_names() == ["A", "B", "C"]  # A уже первая — no-op, сообщений нет
        # Самую первую карточку в конец
        load_view(self.page, tabs=self.TABS3)
        self._start_drag()
        r = self.page.evaluate("""(() => {
          const b = document.querySelectorAll('.tab-card')[2].getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        })()""")
        self._drop(r["left"] + r["width"] * 0.9, r["top"] + r["height"] * 0.5)
        self._end_drag()
        assert self._tab_names() == ["B", "C", "A"]

    def test_multiline_second_row_inserts_after_first_row(self):
        load_view(self.page, tabs=self.TABS3 + [{"name": "D", "url": "https://d.com"}])
        # 2 колонки: A B / C D (без темы в тестах — сетку задаём инлайном)
        self.page.evaluate("""(() => {
          const l = document.getElementById('tabs-list');
          l.style.display = 'grid';
          l.style.gridTemplateColumns = 'repeat(2, 1fr)';
          l.style.gap = '12px';
        })()""")
        self._start_drag()
        # A скрыта (но остаётся в DOM!): видимая сетка B C / D. Курсор в
        # первом столбце второго ряда (ячейка D, левая половина)
        r = self.page.evaluate("""(() => {
          const cards = [...document.querySelectorAll('.tab-card')];
          const d = cards.find(c => c.querySelector('.tab-name').textContent.trim() === 'D');
          const b = d.getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        })()""")
        self._hover(r["left"] + r["width"] * 0.4, r["top"] + r["height"] * 0.5)
        # 2px-линия убрана — индикатор только заглушка (перед D)
        slot = self.page.evaluate("""(() => {
          const l = document.querySelector('.tab-gap-line');
          const order = [...document.getElementById('tabs-list').children].map(c =>
            c.classList.contains('tab-card') ? 'card' :
            c.classList.contains('tab-ghost-slot') ? 'slot' :
            c.classList.contains('tab-row-keeper') ? 'keeper' : 'other');
          return JSON.stringify({line: !!l && l.style.display !== 'none', order: order});
        })()""")
        s = json.loads(slot)
        assert s["line"] is False
        assert s["order"] == ["card", "card", "card", "slot", "card", "other"]  # без keeper: ghost в той же (loose) секции
        self._drop(r["left"] + r["width"] * 0.4, r["top"] + r["height"] * 0.5)
        self._end_drag()
        # A встаёт после всех карточек первого ряда (B, C) — перед D
        assert self._tab_names() == ["B", "C", "A", "D"]

    def test_group_header_no_gap_line(self):
        # 2px-линия убрана: над карточкой и над шапкой группы линии нет
        # (карточка больше не подсвечивает шапку — заглушка просто стоит)
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
        ])
        self._start_drag(1)  # тащим негрупповую L на шапку группы
        r = self.page.evaluate("""(() => {
          const b = document.querySelectorAll('.tab-card')[0].getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        })()""")
        self._hover(r["left"] + r["width"] * 0.25, r["top"] + r["height"] * 0.5)
        assert self._line_rect() is None  # линии нет вообще
        # Шапка группы: у карточки над ней нет drop-over, заглушка на месте
        self.page.evaluate("""(() => {
          const bar = document.querySelector('.gbar');
          const b = bar.getBoundingClientRect();
          bar.dispatchEvent(new DragEvent('dragover', {
            dataTransfer: window.__dt, bubbles: true, cancelable: true,
            clientX: b.left + b.width / 2, clientY: b.top + b.height / 2
          }));
        })()""")
        state = self.page.evaluate("""(() => {
          const l = document.querySelector('.tab-gap-line');
          return JSON.stringify({
            lineHidden: !l || l.style.display === 'none',
            barOver: document.querySelector('.gbar').classList.contains('drop-over'),
            slotStands: !!document.querySelector('.tab-ghost-slot')
          });
        })()""")
        s = json.loads(state)
        assert s["lineHidden"] is True and s["barOver"] is False and s["slotStands"] is True
        self._end_drag()

    def test_dragend_without_drop_storage_untouched(self):
        load_view(self.page, tabs=self.TABS3[:2])
        self._start_drag()
        r = self.page.evaluate("""(() => {
          const b = document.querySelectorAll('.tab-card')[1].getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        })()""")
        self._hover(r["left"] + r["width"] * 0.25, r["top"] + r["height"] * 0.25)
        assert self.page.evaluate("!!document.querySelector('.tab-ghost-slot')") is True
        self._end_drag()
        assert self._tab_names() == ["A", "B"]
        assert json.loads(self.page.evaluate("JSON.stringify(window.lastMessage || null)")) is None
        assert self._ghost_rect() is None
        assert self.page.evaluate("document.querySelectorAll('.tab-ghost-slot').length") == 0
        assert self._line_rect() is None


# ==========================================
#  VIEW.JS: GHOST-SLOT (заглушка слота карточки при перетаскивании)
# ==========================================

class TestTabGhostSlot:
    """Перетаскивание карточки: на месте оригинала — пустая заглушка того же
    размера (тёплый тон), клон-призрака нет (за курсором — нативный drag-образ
    браузера); заглушка ходит за курсором в потенциальный слот вставки, дроп
    вставляет вкладку в её слот."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    TABS3 = [
        {"name": "A", "url": "https://a.com"},
        {"name": "B", "url": "https://b.com"},
        {"name": "C", "url": "https://c.com"},
    ]

    def _tab_names(self):
        return json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.name));
        })()"""))

    def _start_drag(self, idx=0):
        """dragstart карточки idx (window.__srcCard — её элемент); ждать таймаут
        отложенного display:none + вставки заглушки."""
        self.page.evaluate("""(idx) => {
          const card = document.querySelectorAll('#tabs-list .tab-card')[idx];
          window.__srcCard = card;
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
        }""", idx)
        self.page.wait_for_timeout(50)

    def _hover(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('dragover', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _drop(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('drop', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _end_drag(self):
        """dragend на исходной карточке (как в реальном Chrome)."""
        self.page.evaluate("""(() => {
          const card = window.__srcCard;
          if (card) card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")

    def _card_rect(self, i):
        return self.page.evaluate("""(i) => {
          const b = document.querySelectorAll('#tabs-list .tab-card')[i].getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        }""", i)

    def _slot_order(self):
        """Порядок детей #tabs-list: 'card' / 'slot' / 'keeper' / 'other' (gbar, кнопка)."""
        return json.loads(self.page.evaluate("""(() => JSON.stringify(
          [...document.getElementById('tabs-list').children].map(c =>
            c.classList.contains('tab-card') ? 'card' :
            c.classList.contains('tab-ghost-slot') ? 'slot' :
            c.classList.contains('tab-row-keeper') ? 'keeper' : 'other')))()"""))

    def test_placeholder_appears_at_source_slot_with_card_size(self):
        load_view(self.page, tabs=self.TABS3)
        self._start_drag()  # тащим A
        s = json.loads(self.page.evaluate("""(() => {
          const slot = document.querySelector('.tab-ghost-slot');
          if (!slot) return JSON.stringify({present: false});
          const b = document.querySelectorAll('#tabs-list .tab-card')[1]; // B — видимая карточка
          return JSON.stringify({
            present: true,
            count: document.querySelectorAll('.tab-ghost-slot').length,
            sameWidth: slot.offsetWidth === b.offsetWidth,
            sameHeight: slot.offsetHeight === b.offsetHeight
          });
        })()"""))
        assert s["present"] is True and s["count"] == 1
        assert s["sameWidth"] is True and s["sameHeight"] is True
        # Заглушка в слоте исходной карточки: сразу после A, до B/C
        assert self._slot_order() == ["card", "slot", "card", "card", "other"]

    def test_placeholder_is_empty_silhouette_not_interactive(self):
        load_view(self.page, tabs=self.TABS3)
        self._start_drag()
        s = json.loads(self.page.evaluate("""(() => {
          const slot = document.querySelector('.tab-ghost-slot');
          return JSON.stringify({
            empty: slot.textContent === '' && slot.children.length === 0,
            notDraggable: slot.draggable === false,
            pointerEvents: getComputedStyle(slot).pointerEvents,
            bgUsesToken: slot.style.background.indexOf('var(--ghost-bg)') !== -1,
            borderDashedToken: slot.style.borderStyle === 'dashed' &&
              slot.style.cssText.indexOf('var(--ghost-ring)') !== -1
          });
        })()"""))
        assert s["empty"] is True
        assert s["notDraggable"] is True
        assert s["pointerEvents"] == "none"
        assert s["bgUsesToken"] is True and s["borderDashedToken"] is True
        self._end_drag()

    def test_placeholder_moves_to_later_slots(self):
        load_view(self.page, tabs=self.TABS3)
        self._start_drag()  # A: [card, slot, card, card, other]
        c = self._card_rect(2)
        self._hover(c["left"] + c["width"] * 0.25, c["top"] + c["height"] * 0.25)  # зазор перед C
        assert self._slot_order() == ["card", "card", "slot", "card", "other"]  # без keeper: ghost в секции
        c = self._card_rect(2)
        self._hover(c["left"] + c["width"] * 0.75, c["top"] + c["height"] * 0.75)  # зазор после C
        assert self._slot_order() == ["card", "card", "card", "slot", "other"]  # без keeper: ghost в секции
        self._end_drag()

    def test_placeholder_moves_to_earlier_slots(self):
        tabs4 = self.TABS3 + [{"name": "D", "url": "https://d.com"}]
        load_view(self.page, tabs=tabs4)
        self._start_drag(2)  # C: [A, B, C(none), slot, D]
        assert self._slot_order() == ["card", "card", "card", "slot", "card", "other"]
        a = self._card_rect(0)
        self._hover(a["left"] + a["width"] * 0.25, a["top"] + a["height"] * 0.5)  # самое начало
        assert self._slot_order() == ["slot", "card", "card", "card", "card", "other"]  # без keeper: ghost в секции
        a = self._card_rect(0)
        self._hover(a["left"] + a["width"] * 0.75, a["top"] + a["height"] * 0.5)  # зазор перед B
        assert self._slot_order() == ["card", "slot", "card", "card", "card", "other"]  # без keeper: ghost в секции
        self._end_drag()

    def test_drop_commits_order_and_clears_placeholder(self):
        load_view(self.page, tabs=self.TABS3)
        self._start_drag()  # A
        c = self._card_rect(2)
        x = c["left"] + c["width"] * 0.25
        y = c["top"] + c["height"] * 0.25
        self._hover(x, y)  # заглушка перед C — «забранный таб заменит призрака»
        self._drop(x, y)
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        # place-tab (полный массив + секция): перед якорной вкладкой C
        assert msg["action"] == "place-tab" and msg["index"] == 0 and msg["anchorIndex"] == 2 and msg["side"] == "before"
        self._end_drag()
        assert self._tab_names() == ["B", "A", "C"]
        dom = json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('#tabs-list .tab-card .tab-name')].map(e => e.textContent.trim()))"))
        assert dom == ["B", "A", "C"]  # после перерисовки карточка в новом слоте
        assert self.page.evaluate("document.querySelectorAll('.tab-ghost-slot').length") == 0
        assert self.page.evaluate("!!document.querySelector('.tab-ghost')") is False

    def test_drop_at_original_slot_no_change(self):
        load_view(self.page, tabs=self.TABS3)
        self._start_drag(1)  # B: заглушка в её слоте
        slot = self.page.evaluate("""(() => {
          const b = document.querySelector('.tab-ghost-slot').getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        })()""")
        self._drop(slot["left"] + slot["width"] * 0.5, slot["top"] + slot["height"] * 0.5)
        self._end_drag()
        assert self._tab_names() == ["A", "B", "C"]
        assert json.loads(self.page.evaluate("JSON.stringify(window.lastMessage || null)")) is None
        assert self.page.evaluate("document.querySelectorAll('.tab-ghost-slot').length") == 0
        b_display = self.page.evaluate(
            "getComputedStyle(document.querySelectorAll('#tabs-list .tab-card')[1]).display")
        assert b_display != "none"  # B вернулась в свой слот

    def test_dragend_without_drop_restores_card(self):
        load_view(self.page, tabs=self.TABS3)
        self._start_drag(1)  # B
        a = self._card_rect(0)
        self._hover(a["left"] + a["width"] * 0.25, a["top"] + a["height"] * 0.5)  # заглушка ушла в начало
        assert self._slot_order() == ["slot", "card", "card", "card", "other"]  # без keeper: ghost в секции
        self._end_drag()
        assert self.page.evaluate("document.querySelectorAll('.tab-ghost-slot').length") == 0
        assert self.page.evaluate("!!document.querySelector('.tab-ghost')") is False
        assert self._slot_order() == ["card", "card", "card", "other"]
        b_display = self.page.evaluate(
            "getComputedStyle(document.querySelectorAll('#tabs-list .tab-card')[1]).display")
        assert b_display != "none"
        assert self._tab_names() == ["A", "B", "C"]
        assert json.loads(self.page.evaluate("JSON.stringify(window.lastMessage || null)")) is None

    def test_rerender_mid_drag_removes_placeholder_gracefully(self):
        load_view(self.page, tabs=self.TABS3)
        self._start_drag()
        c = self._card_rect(2)
        self._hover(c["left"] + c["width"] * 0.75, c["top"] + c["height"] * 0.75)  # заглушка в конце
        assert self.page.evaluate("!!document.querySelector('.tab-ghost-slot')") is True
        # Изменение storage «из другого окна» → onChanged → перерисовка во время drag
        self.page.evaluate("chrome.storage.set({'blattam-tabs': chrome.storage.local._data['blattam-tabs']})")
        assert self.page.evaluate("document.querySelectorAll('.tab-ghost-slot').length") == 0
        assert self._tab_names() == ["A", "B", "C"]
        # Перерисовка не воссоздаёт заглушку на следующих dragover
        b = self._card_rect(1)
        self._hover(b["left"] + b["width"] * 0.25, b["top"] + b["height"] * 0.5)
        assert self.page.evaluate("document.querySelectorAll('.tab-ghost-slot').length") == 0
        # Клон-призрака не существует (нативный drag-образ браузера); dragend — без ошибок
        assert self.page.evaluate("!!document.querySelector('.tab-ghost')") is False
        self._end_drag()
        assert self.page.evaluate("!!document.querySelector('.tab-ghost')") is False

    def test_drop_on_space_chip_removes_placeholder(self):
        load_view(self.page, spaces=[
            {"id": "sp1", "name": "Main"},
            {"id": "sp2", "name": "Work"},
        ], tabs=[
            {"name": "D", "url": "https://d.com", "spaceId": "sp1"},
        ])
        self._start_drag()
        self.page.evaluate("""(() => {
          const chip = document.querySelector('.space-chip[data-space-id="sp2"]');
          chip.dispatchEvent(new DragEvent('dragover', {dataTransfer: window.__dt, bubbles: true, cancelable: true}));
          chip.dispatchEvent(new DragEvent('drop', {dataTransfer: window.__dt, bubbles: true, cancelable: true}));
        })()""")
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage)"))
        assert msg["action"] == "move-tab" and msg["spaceId"] == "sp2"
        tab = read_storage_raw(self.page, "blattam-tabs")[0]
        assert tab["spaceId"] == "sp2" and tab["groupId"] is None
        assert self.page.evaluate("document.querySelectorAll('.tab-ghost-slot').length") == 0
        self._end_drag()
        assert self.page.evaluate("!!document.querySelector('.tab-ghost')") is False

    def test_drop_on_gbar_removes_placeholder(self):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "L", "url": "https://l.com", "spaceId": "sp1"},
        ])
        self._start_drag(1)  # негрупповая L
        self.page.evaluate("""(() => {
          const bar = document.querySelector('.gbar');
          bar.dispatchEvent(new DragEvent('dragover', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: 100, clientY: 5}));
          // Пока на шапке — заглушка стоит (дроп карточки на шапку — no-op)
          window.__slotOnGbar = !!document.querySelector('.tab-ghost-slot');
          bar.dispatchEvent(new DragEvent('drop', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: 100, clientY: 5}));
        })()""")
        assert self.page.evaluate("window.__slotOnGbar") is True
        # Дроп на шапку не перемещает карточку в группу — move-tab не отправлен
        msg = json.loads(self.page.evaluate("JSON.stringify(window.lastMessage || null)"))
        assert msg is None or msg.get("action") != "move-tab"
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert [t for t in tabs if t["name"] == "L"][0].get("groupId") is None
        self._end_drag()
        assert self.page.evaluate("document.querySelectorAll('.tab-ghost-slot').length") == 0
        assert self.page.evaluate("!!document.querySelector('.tab-ghost')") is False

    def test_theme_tokens_present_in_both_themes(self):
        css = load_file("theme.css")
        html = load_file("view.html")
        dark_at = css.index('[data-theme="dark"] {')  # сам селектор, не упоминание в комментарии
        light_part, dark_part = css[:dark_at], css[dark_at:]
        # view.html использует тёплые токены в правиле заглушки (без hardcoded hex); клон-призрака больше нет
        rule = html[html.index(".tab-ghost-slot"):]
        rule = rule[:rule.index("}")]
        assert "var(--ghost-bg)" in rule and "var(--ghost-ring)" in rule
        assert re.search(r"#[0-9a-fA-F]{3,8}", rule) is None
        assert ".tab-ghost {" not in html
        # Тёплые акцентные токены — ровно по одному разу в светлой И в тёмной секциях,
        # значения — hex
        for tok in ("--ghost-bg", "--ghost-ring"):
            assert light_part.count(f"{tok}:") == 1, tok
            assert dark_part.count(f"{tok}:") == 1, tok
            assert re.search(rf"{tok}:\s*#[0-9a-fA-F]{{3,8}};", light_part), tok
            assert re.search(rf"{tok}:\s*#[0-9a-fA-F]{{3,8}};", dark_part), tok
        # .gbar — «Штрих»: прозрачная строка, 1px-линия сверху из токена --line2, без hex
        gbar = html[html.index(".gbar {"):]
        gbar = gbar[:gbar.index("}")]
        assert "background: transparent" in gbar
        assert "border-top: 1px solid var(--line2)" in gbar
        assert "var(--gbar-bg)" not in gbar
        assert re.search(r"#[0-9a-fA-F]{3,8}", gbar) is None


class TestDragSlotWarmNoClone:
    """Драг без клон-призрака: единственный индикатор в сетке — тёплая заглушка
    (фон --ghost-bg + пунктирный контур --ghost-ring); образ карточки за
    курсором — нативный drag-образ браузера."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}]
    TABS2 = [
        {"name": "A", "url": "https://a.com", "spaceId": "sp1"},
        {"name": "B", "url": "https://b.com", "spaceId": "sp1"},
    ]

    def _inject_real_styles(self):
        # Харнес ставит только body.innerHTML — подгружаем настоящие стили
        # (theme.css + <style> view.html), чтобы computed-значения были реальными
        theme = load_file("theme.css")
        html = load_file("view.html")
        style = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate(
            "(styles) => { var st = document.createElement('style'); st.textContent = styles; document.head.appendChild(st); }",
            [theme + "\n" + style])

    def _parts(self):
        css = load_file("theme.css")
        dark_at = css.index('[data-theme="dark"] {')
        return {"light": css[:dark_at], "dark": css[dark_at:]}

    def _token_color(self, css_part, token):
        # Токен цвета из theme.css (hex ИЛИ rgba()) → строка как отдаёт getComputedStyle
        m = re.search(rf"{token}:\s*(#[0-9a-fA-F]{{3,8}}|rgba?\([^)]*\))", css_part)
        assert m, token
        v = m.group(1)
        if v.startswith("#"):
            h = v[1:]
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            return "rgb({0}, {1}, {2})".format(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        nums = [x.strip() for x in v.split("(", 1)[1].strip().strip("()").split(",")]
        return "rgba({0}, {1}, {2}, {3})".format(nums[0], nums[1], nums[2], nums[3])

    def _start_drag(self, idx=0):
        self.page.evaluate("""(idx) => {
          const card = document.querySelectorAll('#tabs-list .tab-card')[idx];
          window.__srcCard = card;
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
        }""", idx)
        self.page.wait_for_timeout(50)  # заглушка создаётся отложенно (setTimeout(0) в dragstart)

    def test_no_clone_and_warm_slot(self):
        # Обе темы: клон-призрака нет, оригинал скрыт, заглушка тёплая
        # (фон = --ghost-bg, пунктирный контур = --ghost-ring); dragend —
        # заглушка убрана, карточка возвращена в слот
        for theme in ("light", "dark"):
            load_view(self.page, theme=theme, spaces=self.SP, tabs=self.TABS2)
            self._inject_real_styles()
            self._start_drag()  # A
            s = json.loads(self.page.evaluate("""(() => {
              const slot = document.querySelector('.tab-ghost-slot');
              const card = document.querySelector('#tabs-list .tab-card');
              return JSON.stringify({
                noClone: !document.querySelector('.tab-ghost'),
                srcHidden: card.style.display === 'none',
                slotBg: slot ? getComputedStyle(slot).backgroundColor : null,
                slotBorderStyle: slot ? getComputedStyle(slot).borderStyle : null,
                slotBorderColor: slot ? getComputedStyle(slot).borderTopColor : null
              });
            })()"""))
            assert s["noClone"] is True, (theme, s)
            assert s["srcHidden"] is True, (theme, s)
            parts = self._parts()
            assert s["slotBg"] == self._token_color(parts[theme], "--ghost-bg"), (theme, s)
            assert s["slotBorderStyle"] == "dashed", (theme, s)
            assert s["slotBorderColor"] == self._token_color(parts[theme], "--ghost-ring"), (theme, s)
            self.page.evaluate("""(() => {
              window.__srcCard.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
            })()""")
            a = json.loads(self.page.evaluate("""(() => JSON.stringify({
              noClone: !document.querySelector('.tab-ghost'),
              slotGone: document.querySelectorAll('.tab-ghost-slot').length === 0,
              srcRestored: document.querySelector('#tabs-list .tab-card').style.display !== 'none'
            }))()"""))
            assert a["noClone"] is True and a["slotGone"] is True and a["srcRestored"] is True, (theme, a)

    def test_drop_replaces_slot(self):
        # dragstart A → dragover на B (заглушка в её слоте) → drop: порядок
        # закоммичен (B, A), заглушка убрана, клон-призрака не существовало
        load_view(self.page, spaces=self.SP, tabs=self.TABS2)
        self._start_drag()  # A
        self.page.evaluate("""(() => {
          const b = document.querySelectorAll('#tabs-list .tab-card')[1].getBoundingClientRect();
          const x = b.left + b.width * 0.75, y = b.top + b.height * 0.75;
          document.getElementById('tabs-list').dispatchEvent(new DragEvent('dragover', {
            dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
          document.getElementById('tabs-list').dispatchEvent(new DragEvent('drop', {
            dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
          window.__srcCard.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        names = [t["name"] for t in read_storage_raw(self.page, "blattam-tabs")]
        assert names == ["B", "A"]
        a = json.loads(self.page.evaluate("""(() => JSON.stringify({
          noClone: !document.querySelector('.tab-ghost'),
          slotGone: document.querySelectorAll('.tab-ghost-slot').length === 0
        }))()"""))
        assert a["noClone"] is True and a["slotGone"] is True, a


class TestGroupAwareGhostSlot:
    """Секционно-чуткий ghost-slot: заглушка встаёт в ЛЮБУЮ отрисованную
    позицию (перед/между/после карточек, до шапки секции = конец предыдущей,
    после шапки = начало секции); дроп в область карточек другой группы
    переносит вкладку В ЭТУ группу на позицию заглушки (loose-секция —
    groupId null)."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    def _load(self, groups, tabs):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=groups,
                  tabs=tabs, last_space="sp1")

    def _card_rect(self, name):
        return self.page.evaluate("""(name) => {
          const card = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === name);
          const b = card.getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        }""", name)

    def _rect_of(self, selector):
        return self.page.evaluate("""(sel) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const b = el.getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        }""", selector)

    def _start_drag(self, name):
        self.page.evaluate("""(name) => {
          const card = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === name);
          window.__srcCard = card;
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
        }""", name)
        self.page.wait_for_timeout(50)

    def _hover(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('dragover', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _drop(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('drop', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _end_drag(self):
        self.page.evaluate("""(() => {
          const card = window.__srcCard;
          if (card) card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")

    def _slot_order(self):
        """Порядок детей #tabs-list: 'card' / 'slot' / 'keeper' / 'gbar' / 'other'."""
        return json.loads(self.page.evaluate("""(() => JSON.stringify(
          [...document.getElementById('tabs-list').children].map(c =>
            c.classList.contains('tab-card') ? 'card' :
            c.classList.contains('tab-ghost-slot') ? 'slot' :
            c.classList.contains('tab-row-keeper') ? 'keeper' :
            c.classList.contains('gbar') ? 'gbar' : 'other')))()"""))

    def _dom_names(self):
        return json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('#tabs-list .tab-card .tab-name')].map(e => e.textContent.trim()))"))

    def _names(self):
        return json.loads(self.page.evaluate("""(async () => {
          const d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.name));
        })()"""))

    def _group_of(self, name):
        return self.page.evaluate("""(async (name) => {
          const d = await chrome.storage.get('blattam-tabs');
          const t = (d['blattam-tabs'] || []).find(t => t.name === name);
          return t.groupId;
        })""", name)

    # Вкладки перемешаны в полном массиве (секции не совпадают с порядком
    # массива), чтобы позиции «конец секции / начало секции» отличались от
    # плоского reorder по порядку видимых карточек.
    GROUPS2 = [
        {"id": "g1", "name": "One", "spaceId": "sp1", "collapsed": False},
        {"id": "g2", "name": "Two", "spaceId": "sp1", "collapsed": False},
    ]
    TABS5 = [
        {"name": "A", "url": "https://a.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "D", "url": "https://d.com", "spaceId": "sp1", "groupId": "g2"},
        {"name": "B", "url": "https://b.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "E", "url": "https://e.com", "spaceId": "sp1", "groupId": "g2"},
        {"name": "C", "url": "https://c.com", "spaceId": "sp1", "groupId": "g1"},
    ]

    def test_slot_reaches_end_of_group(self):
        # 1) заглушка встаёт ПОСЛЕ последней карточки g1, ПЕРЕД шапкой g2
        self._load(self.GROUPS2, self.TABS5)
        self._start_drag("A")
        bar = self._rect_of('.gbar[data-group-id="g2"]')
        self._hover(bar["left"] + bar["width"] * 0.5, bar["top"] + 1)  # строка над шапкой g2
        assert self._slot_order() == ["gbar", "card", "card", "card", "slot", "gbar", "card", "card", "other"]  # без keeper: ghost в исходной секции
        self._end_drag()

    def test_drop_commits_end_of_group(self):
        # 1) дроп в конец g1: после последней вкладки g1 в ПОЛНОМ массиве,
        # groupId не меняется
        self._load(self.GROUPS2, self.TABS5)
        self._start_drag("A")
        bar = self._rect_of('.gbar[data-group-id="g2"]')
        self._drop(bar["left"] + bar["width"] * 0.5, bar["top"] + 1)
        assert self._names() == ["D", "B", "E", "C", "A"]
        assert self._group_of("A") == "g1"
        assert self._dom_names() == ["B", "C", "A", "D", "E"]  # A — в конце секции g1
        self._end_drag()

    def test_slot_reaches_end_of_list_and_drop_moves_into_last_group(self):
        # 1+2) конец списка достижим; дроп туда — в последнюю секцию (g2)
        self._load(self.GROUPS2, self.TABS5)
        self._start_drag("A")
        e = self._card_rect("E")
        self._hover(e["left"] + e["width"] * 0.75, e["top"] + e["height"] * 0.75)
        assert self._slot_order() == ["gbar", "card", "card", "card", "keeper", "gbar", "card", "card", "slot", "other"]  # keeper — в конце исходной секции (после C)
        self._drop(e["left"] + e["width"] * 0.75, e["top"] + e["height"] * 0.75)
        assert self._names() == ["D", "B", "E", "A", "C"]
        assert self._group_of("A") == "g2"
        self._end_drag()

    def test_drop_into_other_group_between_cards(self):
        # 2) дроп между D и E — вкладка уходит в g2, позиция = позиция заглушки
        self._load(self.GROUPS2, self.TABS5)
        self._start_drag("A")
        d = self._card_rect("D")
        x, y = d["left"] + d["width"] * 0.75, d["top"] + d["height"] * 0.5
        self._hover(x, y)
        assert self._slot_order() == ["gbar", "card", "card", "card", "keeper", "gbar", "card", "slot", "card", "other"]  # keeper — в конце исходной секции (после C)
        self._drop(x, y)
        assert self._names() == ["D", "B", "A", "E", "C"]
        assert self._group_of("A") == "g2"
        assert self._dom_names() == ["B", "C", "D", "A", "E"]
        self._end_drag()

    def test_drop_into_other_group_at_start(self):
        # 2) дроп ПЕРЕД первой карточкой g2 (заглушка после её шапки)
        self._load(self.GROUPS2, self.TABS5)
        self._start_drag("A")
        d = self._card_rect("D")
        x, y = d["left"] + d["width"] * 0.25, d["top"] + 1
        self._hover(x, y)
        assert self._slot_order() == ["gbar", "card", "card", "card", "keeper", "gbar", "slot", "card", "card", "other"]  # keeper — в конце исходной секции (после C)
        self._drop(x, y)
        assert self._names() == ["A", "D", "B", "E", "C"]
        assert self._group_of("A") == "g2"
        assert self._dom_names() == ["B", "C", "A", "D", "E"]  # A — первой в g2
        self._end_drag()

    def test_drop_into_loose_section(self):
        # 2) дроп в область негрупповых карточек — groupId → null
        tabs = [
            {"name": "A", "url": "https://a.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "L1", "url": "https://l1.com", "spaceId": "sp1"},
            {"name": "B", "url": "https://b.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "L2", "url": "https://l2.com", "spaceId": "sp1"},
        ]
        self._load([{"id": "g1", "name": "One", "spaceId": "sp1", "collapsed": False}], tabs)
        self._start_drag("A")
        l1 = self._card_rect("L1")
        x, y = l1["left"] + l1["width"] * 0.75, l1["top"] + l1["height"] * 0.5
        self._hover(x, y)  # заглушка между L1 и L2
        assert self._slot_order() == ["gbar", "card", "card", "keeper", "other", "card", "slot", "card", "other"]  # keeper — в конце исходной секции (после B)
        self._drop(x, y)
        assert self._names() == ["L1", "B", "A", "L2"]
        assert self._group_of("A") is None
        assert self._dom_names() == ["B", "L1", "A", "L2"]
        self._end_drag()

    def test_drop_into_loose_section_at_start(self):
        # 2) заглушка после подписи «Без группы» (начало loose-секции)
        tabs = [
            {"name": "A", "url": "https://a.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "L1", "url": "https://l1.com", "spaceId": "sp1"},
            {"name": "B", "url": "https://b.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "L2", "url": "https://l2.com", "spaceId": "sp1"},
        ]
        self._load([{"id": "g1", "name": "One", "spaceId": "sp1", "collapsed": False}], tabs)
        self._start_drag("A")
        l1 = self._card_rect("L1")
        x, y = l1["left"] + l1["width"] * 0.25, l1["top"] + 1
        self._hover(x, y)
        assert self._slot_order() == ["gbar", "card", "card", "keeper", "other", "slot", "card", "card", "other"]  # keeper — в конце исходной секции (после B)
        self._drop(x, y)
        assert self._names() == ["A", "L1", "B", "L2"]
        assert self._group_of("A") is None
        self._end_drag()


class TestCollapsedRunGhostSlot:
    """Ghost-slot на границе прогона свёрнутых групп: курсор ниже последней
    карточки раскрытой группы, дальше — (через свёрнутые) ещё раскрытая
    группа. Заглушка встаёт на ГРАНИЦЕ (после последней карточки предыдущей
    секции), а не в пространство НИЗКОЙ свёрнутой группы (из-за неё группа
    выглядела «раскрытой» с призрачной вкладкой); дроп туда переносит
    вкладку в конец предыдущей секции (семантика не меняется)."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    GROUPS5 = [
        {"id": "g1", "name": "One", "spaceId": "sp1", "collapsed": False},
        {"id": "g2", "name": "Two", "spaceId": "sp1", "collapsed": True},
        {"id": "g3", "name": "Three", "spaceId": "sp1", "collapsed": True},
        {"id": "g4", "name": "Four", "spaceId": "sp1", "collapsed": True},
        {"id": "g5", "name": "Five", "spaceId": "sp1", "collapsed": False},
    ]
    TABS12 = [
        {"name": "A", "url": "https://a.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "B", "url": "https://b.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "C", "url": "https://c.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "D", "url": "https://d.com", "spaceId": "sp1", "groupId": "g2"},
        {"name": "E", "url": "https://e.com", "spaceId": "sp1", "groupId": "g2"},
        {"name": "F", "url": "https://f.com", "spaceId": "sp1", "groupId": "g3"},
        {"name": "G", "url": "https://g.com", "spaceId": "sp1", "groupId": "g3"},
        {"name": "H", "url": "https://h.com", "spaceId": "sp1", "groupId": "g4"},
        {"name": "I", "url": "https://i.com", "spaceId": "sp1", "groupId": "g4"},
        {"name": "J", "url": "https://j.com", "spaceId": "sp1", "groupId": "g5"},
        {"name": "K", "url": "https://k.com", "spaceId": "sp1", "groupId": "g5"},
        {"name": "L", "url": "https://l.com", "spaceId": "sp1", "groupId": "g5"},
    ]

    def _load(self):
        load_view(self.page, spaces=[{"id": "sp1", "name": "Main"}], groups=self.GROUPS5,
                  tabs=self.TABS12, last_space="sp1")

    def _start_drag(self, name):
        self.page.evaluate("""(name) => {
          const card = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === name);
          window.__srcCard = card;
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
        }""", name)
        self.page.wait_for_timeout(50)

    def _hover(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('dragover', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _drop(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('drop', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _end_drag(self):
        self.page.evaluate("""(() => {
          const card = window.__srcCard;
          if (card) card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")

    def _slot_order(self):
        return json.loads(self.page.evaluate("""(() => JSON.stringify(
          [...document.getElementById('tabs-list').children].map(c =>
            c.classList.contains('tab-card') ? 'card' :
            c.classList.contains('tab-ghost-slot') ? 'slot' :
            c.classList.contains('tab-row-keeper') ? 'keeper' :
            c.classList.contains('gbar') ? 'gbar' : 'other')))()"""))

    def _rect(self, selector):
        return self.page.evaluate("""(sel) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const b = el.getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        }""", selector)

    def _card_rect(self, name):
        return self.page.evaluate("""(name) => {
          const card = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === name);
          const b = card.getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        }""", name)

    def _region_point(self):
        """Точка в прогоне свёрнутых групп: ниже последней видимой карточки
        g1 (C) и выше шапки g5."""
        c = self._card_rect("C")
        bar5 = self._rect('.gbar[data-group-id="g5"]')
        return (bar5["left"] + bar5["width"] * 0.5,
                (c["top"] + c["height"] + bar5["top"]) / 2)

    def _names(self):
        return json.loads(self.page.evaluate("""(async () => {
          const d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.name));
        })()"""))

    def _group_of(self, name):
        return self.page.evaluate("""(async (name) => {
          const d = await chrome.storage.get('blattam-tabs');
          const t = (d['blattam-tabs'] || []).find(t => t.name === name);
          return t.groupId;
        })""", name)

    def test_ghost_at_boundary_not_in_collapsed_run(self):
        self._load()
        self._start_drag("A")
        x, y = self._region_point()
        self._hover(x, y)
        # Полоса над прогоном свёрнутых групп: заглушка — ВИДИМАЯ в ХВОСТЕ
        # исходной секции g1 (после C), а не «дома» и не в пространстве
        # НИЗКОЙ свёрнутой группы; keeper нет (ghost в исходной секции)
        d = json.loads(self.page.evaluate("""(() => JSON.stringify({
          atHome: window.__srcCard.nextElementSibling === document.querySelector('.tab-ghost-slot'),
          atTail: (() => {
            const c = [...document.querySelectorAll('#tabs-list .tab-card')]
              .find(c => c.querySelector('.tab-name').textContent.trim() === 'C');
            return c.nextElementSibling === document.querySelector('.tab-ghost-slot');
          })(),
          visible: (() => { const s = document.querySelector('.tab-ghost-slot'); return s && getComputedStyle(s).visibility !== 'hidden'; })(),
          keepers: document.querySelectorAll('.tab-row-keeper').length
        }))()"""))
        assert d["atHome"] is False and d["atTail"] is True and d["visible"] is True and d["keepers"] == 0, d
        assert self._slot_order() == ["gbar", "card", "card", "card", "slot", "gbar",
                                      "gbar", "gbar", "gbar", "card", "card", "card", "other"]
        self._end_drag()

    def test_ghost_above_first_collapsed_header(self):
        # Геометрия: верх заглушки выше шапки g2 (в строке g1), а не в
        # прогоне свёрнутых групп
        self._load()
        self._start_drag("A")
        x, y = self._region_point()
        self._hover(x, y)
        slot = self._rect('.tab-ghost-slot')
        bar2 = self._rect('.gbar[data-group-id="g2"]')
        assert slot is not None
        assert slot["top"] < bar2["top"]
        self._end_drag()

    def test_drop_in_collapsed_region_lands_at_end_of_prev_section(self):
        # Дроп в прогон свёрнутых групп: вкладка встаёт в конец g1, группа
        # не меняется (семантика дропа не зависит от позиции заглушки)
        self._load()
        self._start_drag("A")
        x, y = self._region_point()
        self._drop(x, y)
        assert self._names() == ["B", "C", "A", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
        assert self._group_of("A") == "g1"
        self._end_drag()


class TestDragRowReflow:
    """Reflow строк при драге (реальная сетка: theme.css + стили view.html,
    1280x800 → 6 колонок): карточки ЗАКРЫВАЮТ слот скрытой карточки (без
    «дырки» на её месте), а число строк исходной секции фиксировано — его
    держит ghost-slot (ghost в секции) или невидимый row-keeper в КОНЦЕ
    секции (ghost в другой)."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        self._errors = []
        page.on("pageerror", self._on_err)
        yield
        assert not self._errors, self._errors
        page.remove_listener("pageerror", self._on_err)

    def _on_err(self, err):
        self._errors.append(str(err))

    SP = [{"id": "sp1", "name": "Main"}]

    def _load(self, groups, tabs):
        load_view(self.page, spaces=self.SP, groups=groups, tabs=tabs, last_space="sp1")
        css = load_file("theme.css")
        html = load_file("view.html")
        style_block = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate("""(css) => {
          const s = document.createElement('style');
          s.textContent = css;
          document.head.appendChild(s);
        }""", css + style_block)
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.wait_for_timeout(50)

    def _start_drag(self, name):
        self.page.evaluate("""(name) => {
          const card = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === name);
          window.__srcCard = card;
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
        }""", name)
        self.page.wait_for_timeout(50)

    def _card_rect(self, name):
        return self.page.evaluate("""(name) => {
          const card = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === name);
          const b = card.getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        }""", name)

    def _hover(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('dragover', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _end_drag(self):
        self.page.evaluate("""(() => {
          const card = window.__srcCard;
          if (card) card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")

    def _anchor_top(self):
        return self.page.evaluate("document.getElementById('add-group-btn').getBoundingClientRect().top")

    def test_in_section_refill_no_keeper_row_fixed(self):
        # Пример пользователя: группа на 2 строки (6 колонок: 6+1); тащим
        # вкладку из первой строки, заглушка — в КОНЦЕ секции (всё ещё в ней):
        # одинокая вкладка последней строки поднялась в первую строку,
        # исходный слот занят другой карточкой (без дырки), keeper в DOM нет,
        # якорь под списком не сдвинулся
        tabs = [{"name": f"T{i}", "url": f"https://t{i}.com", "spaceId": "sp1", "groupId": "g1"}
                for i in range(1, 8)]
        self._load([{"id": "g1", "name": "G", "spaceId": "sp1", "collapsed": False}], tabs)
        pre = self._anchor_top()
        t1 = self._card_rect("T1")
        t7 = self._card_rect("T7")
        assert t7["top"] > t1["top"], (t1, t7)  # T7 одинокая в последней строке
        self._start_drag("T1")
        self._hover(t7["left"] + t7["width"] * 0.75, t7["top"] + t7["height"] * 0.75)
        d = json.loads(self.page.evaluate("""(() => {
          const slot = document.querySelector('.tab-ghost-slot');
          const find = (n) => [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === n);
          const b2 = find('T2').getBoundingClientRect();
          const b7 = find('T7').getBoundingClientRect();
          return JSON.stringify({
            keepers: document.querySelectorAll('.tab-row-keeper').length,
            slotAtTail: find('T7').nextElementSibling === slot,
            t7Top: b7.top, t2Left: b2.left, t2Top: b2.top,
            top: document.getElementById('add-group-btn').getBoundingClientRect().top
          });
        })()"""))
        assert d["keepers"] == 0, d
        assert d["slotAtTail"], d  # заглушка — в конце секции (после T7)
        assert abs(d["t7Top"] - t1["top"]) < 2, (t1, d)  # T7 поднялась в первую строку
        assert abs(d["t2Left"] - t1["left"]) < 2 and abs(d["t2Top"] - t1["top"]) < 2, (t1, d)  # исходный слот занят T2
        assert abs(d["top"] - pre) < 2, (pre, d["top"])
        self._end_drag()

    def test_cross_section_keeper_at_source_tail(self):
        # Ghost в другой группе: row-keeper в конце исходной секции (после
        # последней видимой карточки), шапка следующей группы не сдвинулась,
        # исходный слот занят другой карточкой
        tabs = [{"name": f"T{i}", "url": f"https://t{i}.com", "spaceId": "sp1", "groupId": "g1"}
                for i in range(1, 8)] + [
            {"name": "U1", "url": "https://u1.com", "spaceId": "sp1", "groupId": "g2"},
            {"name": "U2", "url": "https://u2.com", "spaceId": "sp1", "groupId": "g2"},
        ]
        self._load([{"id": "g1", "name": "G1", "spaceId": "sp1", "collapsed": False},
                    {"id": "g2", "name": "G2", "spaceId": "sp1", "collapsed": False}], tabs)
        pre_bar2 = self.page.evaluate(
            "document.querySelector(\".gbar[data-group-id='g2']\").getBoundingClientRect().top")
        t1 = self._card_rect("T1")
        u1 = self._card_rect("U1")
        self._start_drag("T1")
        self._hover(u1["left"] + u1["width"] * 0.5, u1["top"] + u1["height"] * 0.5)
        d = json.loads(self.page.evaluate("""(() => {
          const k = document.querySelector('.tab-row-keeper');
          const slot = document.querySelector('.tab-ghost-slot');
          const find = (n) => [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === n);
          const b2 = find('T2').getBoundingClientRect();
          const prev = slot ? slot.previousElementSibling : null;
          return JSON.stringify({
            keeperExists: !!k,
            keeperAfterT7: !!k && find('T7').nextElementSibling === k,
            slotAfterBar2: !!prev && prev.classList.contains('gbar') && prev.dataset.groupId === 'g2',
            bar2Top: document.querySelector('.gbar[data-group-id="g2"]').getBoundingClientRect().top,
            t2Left: b2.left, t2Top: b2.top
          });
        })()"""))
        assert d["keeperExists"] and d["keeperAfterT7"], d
        assert d["slotAfterBar2"], d  # заглушка — в начале g2 (после её шапки)
        assert abs(d["bar2Top"] - pre_bar2) < 2, (pre_bar2, d["bar2Top"])
        assert abs(d["t2Left"] - t1["left"]) < 2 and abs(d["t2Top"] - t1["top"]) < 2, (t1, d)
        self._end_drag()

    def test_single_tab_group_keeper_after_gbar(self):
        # Группа ровно с ОДНОЙ вкладкой: тащим её на карточку другой группы —
        # в исходной секции не осталось видимых карточек: keeper стоит за её
        # .gbar, якорь под списком не сдвинулся
        tabs = [
            {"name": "T1", "url": "https://t1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "U1", "url": "https://u1.com", "spaceId": "sp1", "groupId": "g2"},
            {"name": "U2", "url": "https://u2.com", "spaceId": "sp1", "groupId": "g2"},
        ]
        self._load([{"id": "g1", "name": "G1", "spaceId": "sp1", "collapsed": False},
                    {"id": "g2", "name": "G2", "spaceId": "sp1", "collapsed": False}], tabs)
        pre = self._anchor_top()
        u1 = self._card_rect("U1")
        self._start_drag("T1")
        self._hover(u1["left"] + u1["width"] * 0.5, u1["top"] + u1["height"] * 0.5)
        d = json.loads(self.page.evaluate("""(() => {
          const k = document.querySelector('.tab-row-keeper');
          const bar1 = document.querySelector('.gbar[data-group-id="g1"]');
          const slot = document.querySelector('.tab-ghost-slot');
          const prev = slot ? slot.previousElementSibling : null;
          return JSON.stringify({
            keeperExists: !!k,
            keeperAfterBar1: !!k && bar1.nextElementSibling === k,
            slotAfterBar2: !!prev && prev.classList.contains('gbar') && prev.dataset.groupId === 'g2',
            top: document.getElementById('add-group-btn').getBoundingClientRect().top
          });
        })()"""))
        assert d["keeperExists"] and d["keeperAfterBar1"], d
        assert d["slotAfterBar2"], d
        assert abs(d["top"] - pre) < 2, (pre, d["top"])
        self._end_drag()


class TestDragGhostOverCollapsed:
    """Ghost-заглушка над шапками групп: над ЛЮБОЙ шапкой (.gbar — развёрнутой,
    свёрнутой или пустой) заглушка ПРЯЧЕТСЯ ЦЕЛИКОМ (display:none — её ячейка
    сетки освобождается: ни «тёплая» заглушка на старом месте, ни дырки);
    row-keeper держит число строк исходной секции. В полосе прямо над шапкой
    свёрнутой/пустой группы (не сама шапка) — заглушка ВИДИМАЯ в хвосте
    исходной секции (честно: дроп туда ставит вкладку в хвост той же секции).
    Семантика дропа не меняется: дроп на шапку свёрнутой группы переносит
    вкладку в группу, группа остаётся свёрнутой; дроп на развёрнутую шапку —
    no-op."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        self._errors = []
        page.on("pageerror", self._on_err)
        yield
        assert not self._errors, self._errors
        page.remove_listener("pageerror", self._on_err)

    def _on_err(self, err):
        self._errors.append(str(err))

    SP = [{"id": "sp1", "name": "Main"}]
    GROUPS = [
        {"id": "g1", "name": "One", "spaceId": "sp1", "collapsed": False},
        {"id": "g2", "name": "Two", "spaceId": "sp1", "collapsed": True},
        {"id": "g3", "name": "Three", "spaceId": "sp1", "collapsed": False},
    ]
    TABS = [
        {"name": "A", "url": "https://a.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "B", "url": "https://b.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "C", "url": "https://c.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "D", "url": "https://d.com", "spaceId": "sp1", "groupId": "g2"},
        {"name": "E", "url": "https://e.com", "spaceId": "sp1", "groupId": "g2"},
        {"name": "F", "url": "https://f.com", "spaceId": "sp1", "groupId": "g3"},
        {"name": "G", "url": "https://g.com", "spaceId": "sp1", "groupId": "g3"},
    ]

    def _load(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS, last_space="sp1")
        css = load_file("theme.css")
        html = load_file("view.html")
        style_block = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate("""(css) => {
          const s = document.createElement('style');
          s.textContent = css;
          document.head.appendChild(s);
        }""", css + style_block)
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.wait_for_timeout(50)

    def _start_drag(self, name):
        self.page.evaluate("""(name) => {
          const card = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === name);
          window.__srcCard = card;
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
        }""", name)
        self.page.wait_for_timeout(50)

    def _card_rect(self, name):
        return self.page.evaluate("""(name) => {
          const card = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === name);
          const b = card.getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        }""", name)

    def _rect_of(self, selector):
        return self.page.evaluate("""(sel) => {
          const b = document.querySelector(sel).getBoundingClientRect();
          return {left: b.left, top: b.top, width: b.width, height: b.height};
        }""", selector)

    def _dragover_gbar(self, gid):
        self.page.evaluate("""(gid) => {
          const bar = document.querySelector('.gbar[data-group-id="' + gid + '"]');
          const b = bar.getBoundingClientRect();
          bar.dispatchEvent(new DragEvent('dragover', {
            dataTransfer: window.__dt, bubbles: true, cancelable: true,
            clientX: b.left + b.width / 2, clientY: b.top + b.height / 2
          }));
        }""", gid)

    def _hover(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('dragover', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _end_drag(self):
        self.page.evaluate("""(() => {
          const card = window.__srcCard;
          if (card) card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")

    def test_ghost_hidden_over_collapsed_gbar(self):
        # Курсор над шапкой свёрнутой g2 (цель дропа карточки): заглушка
        # ПРЯЧЕТСЯ ЦЕЛИКОМ (display:none) — не «тёплая» заглушка на старом
        # месте, не в хвосте; остаётся там, где была (сразу после A), не
        # удаляется; row-keeper держит число строк исходной секции g1
        self._load()
        self._start_drag("A")
        self._dragover_gbar("g2")
        d = json.loads(self.page.evaluate("""(() => {
          const src = window.__srcCard;
          const slot = document.querySelector('.tab-ghost-slot');
          const c = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === 'C');
          return JSON.stringify({
            hidden: slot && getComputedStyle(slot).display === 'none',
            atHome: src.nextElementSibling === slot,
            notAfterLastG1: c.nextElementSibling !== slot,
            keepers: document.querySelectorAll('.tab-row-keeper').length
          });
        })()"""))
        assert d == {"hidden": True, "atHome": True, "notAfterLastG1": True, "keepers": 1}, d
        self._end_drag()

    def test_ghost_visible_at_tail_in_band_above_collapsed_gbar(self):
        # Курсор в полосе МЕЖДУ последней карточкой g1 и шапкой g2: заглушка —
        # ВИДИМАЯ в ХВОСТЕ исходной секции (после C), честно: дроп туда ставит
        # вкладку в хвост g1. ДОМА (home-snap) заглушка уходит только над самой
        # шапкой свёрнутой/пустой группы
        self._load()
        self._start_drag("A")
        c = self._card_rect("C")
        bar = self._rect_of('.gbar[data-group-id="g2"]')
        self._hover(bar["left"] + bar["width"] * 0.5, (c["top"] + c["height"] + bar["top"]) / 2)
        d = json.loads(self.page.evaluate("""(() => {
          const slot = document.querySelector('.tab-ghost-slot');
          const c = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === 'C');
          const bar = document.querySelector('.gbar[data-group-id="g2"]');
          return JSON.stringify({
            atTail: c.nextElementSibling === slot,
            visible: slot && getComputedStyle(slot).visibility !== 'hidden',
            notHome: window.__srcCard.nextElementSibling !== slot,
            keepers: document.querySelectorAll('.tab-row-keeper').length,
            aboveBar: slot.getBoundingClientRect().top < bar.getBoundingClientRect().top
          });
        })()"""))
        assert d == {"atTail": True, "visible": True, "notHome": True, "keepers": 0, "aboveBar": True}, d
        self._end_drag()

    def test_drop_on_collapsed_gbar_moves_tab_group_stays_collapsed(self):
        # Дроп на шапку свёрнутой g2: вкладка уезжает в g2 (storage),
        # заглушка убрана, ложный клик в момент дропа не раскрывает g2
        self._load()
        self._start_drag("A")
        self.page.evaluate("""(() => {
          const bar = document.querySelector('.gbar[data-group-id="g2"]');
          const b = bar.getBoundingClientRect();
          const x = b.left + b.width / 2, y = b.top + b.height / 2;
          bar.dispatchEvent(new DragEvent('dragover', {
            dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
          bar.dispatchEvent(new DragEvent('drop', {
            dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
          bar.dispatchEvent(new Event('click', {bubbles: true}));  // ложный post-drop клик (до dragend)
        })()""")
        self._end_drag()
        groups = read_storage_raw(self.page, "blattam-groups")
        tabs = read_storage_raw(self.page, "blattam-tabs")
        g2 = [g for g in groups if g["id"] == "g2"][0]
        a = [t for t in tabs if t["name"] == "A"][0]
        assert a["groupId"] == "g2", tabs
        assert g2["collapsed"] is True, g2
        assert self.page.evaluate("document.querySelectorAll('.tab-ghost-slot').length") == 0

    def test_ghost_hidden_over_expanded_gbar(self):
        # Над шапкой группы С видимыми карточками (дроп карточки на неё
        # ничего не делает) заглушка ПРЯЧЕТСЯ ЦЕЛИКОМ (display:none — её
        # ячейка сетки освобождается, сетка перетекает: ни заглушки, ни дырки):
        # остаётся на месте, не возвращается домой, не удаляется
        self._load()
        self._start_drag("A")
        b = self._card_rect("B")
        self._hover(b["left"] + b["width"] * 0.75, b["top"] + b["height"] * 0.75)  # заглушка до C
        self._dragover_gbar("g3")  # развёрнутая g3 (F, G)
        d = json.loads(self.page.evaluate("""(() => {
          const src = window.__srcCard;
          const slot = document.querySelector('.tab-ghost-slot');
          const c = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === 'C');
          return JSON.stringify({
            exists: !!slot,
            hidden: slot && getComputedStyle(slot).display === 'none',
            beforeC: c.previousElementSibling === slot,
            notHome: src.nextElementSibling !== slot
          });
        })()"""))
        assert d == {"exists": True, "hidden": True, "beforeC": True, "notHome": True}, d
        self._end_drag()

class TestOnlyTabHomeDrop:
    """Группа, где перетаскиваемая карточка ЕДИНСТВЕННАЯ: пока карточка скрыта,
    секция «пустая» и геометрия прыгает через полосу исходной секции в соседнюю —
    вкладку нельзя вернуть на место (уезжает в соседнюю группу). Слот над схваченной
    карточкой — это ДОМАШНИЙ слот исходной карточки: дроп — no-op, заглушка не
    уезжает из него, пока курсор в полосе секции."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        self._errors = []
        page.on("pageerror", self._on_err)
        yield
        assert not self._errors, self._errors
        page.remove_listener("pageerror", self._on_err)

    def _on_err(self, err):
        self._errors.append(str(err))

    SP = [{"id": "sp1", "name": "Main"}]

    def _load(self, groups, tabs):
        load_view(self.page, spaces=self.SP, groups=groups, tabs=tabs, last_space="sp1")
        css = load_file("theme.css")
        html = load_file("view.html")
        style_block = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate("""(css) => {
          const s = document.createElement('style');
          s.textContent = css;
          document.head.appendChild(s);
        }""", css + style_block)
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.wait_for_timeout(50)

    def _start_drag(self, name):
        self.page.evaluate("""(name) => {
          const card = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(c => c.querySelector('.tab-name').textContent.trim() === name);
          window.__srcCard = card;
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
        }""", name)
        self.page.wait_for_timeout(50)

    def _home(self):
        # Центр заглушки: после dragstart она ДОМА — в слоте схваченной карточки
        g = self.page.evaluate("""(() => {
          const g = document.querySelector('.tab-ghost-slot');
          const b = g.getBoundingClientRect();
          return {x: b.left + b.width / 2, y: b.top + b.height / 2};
        })()""")
        return g["x"], g["y"]

    def _hover(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('dragover', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _drop(self, x, y):
        self.page.evaluate("""([x, y]) => {
          document.getElementById('tabs-list').dispatchEvent(
            new DragEvent('drop', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
        }""", [x, y])

    def _end_drag(self):
        self.page.evaluate("""(() => {
          const card = window.__srcCard;
          if (card) card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")

    def _tabs_now(self):
        return [(t["name"], t.get("groupId")) for t in read_local(self.page, "blattam-tabs")]

    def test_first_group_only_tab_home_drop_noop(self):
        # Группа с единственной карточкой ПЕРВОЙ в списке: дроп домой не уносит
        # карточку в соседнюю группу (геометрия прыгала через «пустую» исходную
        # секцию к первой видимой карточке следующей группы)
        groups = [{"id": "g1", "name": "G1", "spaceId": "sp1", "collapsed": False},
                  {"id": "g2", "name": "G2", "spaceId": "sp1", "collapsed": False}]
        tabs = [{"name": "T1", "url": "https://t1.com", "spaceId": "sp1", "groupId": "g1"},
                {"name": "B1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "g2"},
                {"name": "B2", "url": "https://b2.com", "spaceId": "sp1", "groupId": "g2"}]
        self._load(groups, tabs)
        self._start_drag("T1")
        x, y = self._home()
        self._hover(x, y)
        self._drop(x, y)
        assert self._tabs_now() == [("T1", "g1"), ("B1", "g2"), ("B2", "g2")]
        self._end_drag()

    def test_last_group_only_tab_home_drop_noop(self):
        # Группа с единственной карточкой ПОСЛЕДНЕЙ в списке: дроп домой (в конец) —
        # no-op (карточка не уезжает вверх и не меняет группу)
        groups = [{"id": "g2", "name": "G2", "spaceId": "sp1", "collapsed": False},
                  {"id": "g1", "name": "G1", "spaceId": "sp1", "collapsed": False}]
        tabs = [{"name": "B1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "g2"},
                {"name": "B2", "url": "https://b2.com", "spaceId": "sp1", "groupId": "g2"},
                {"name": "T1", "url": "https://t1.com", "spaceId": "sp1", "groupId": "g1"}]
        self._load(groups, tabs)
        self._start_drag("T1")
        x, y = self._home()
        self._hover(x, y)
        self._drop(x, y)
        assert self._tabs_now() == [("B1", "g2"), ("B2", "g2"), ("T1", "g1")]
        self._end_drag()

    def test_middle_group_only_tab_home_drop_noop(self):
        # Группа с единственной карточкой между двумя группами: дроп домой — no-op
        # (раньше заглушка прыгала в конец предыдущей группы и дроп менял группу)
        groups = [{"id": "g1", "name": "G1", "spaceId": "sp1", "collapsed": False},
                  {"id": "g2", "name": "G2", "spaceId": "sp1", "collapsed": False},
                  {"id": "g3", "name": "G3", "spaceId": "sp1", "collapsed": False}]
        tabs = [{"name": "B1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "g1"},
                {"name": "B2", "url": "https://b2.com", "spaceId": "sp1", "groupId": "g1"},
                {"name": "T1", "url": "https://t1.com", "spaceId": "sp1", "groupId": "g2"},
                {"name": "C1", "url": "https://c1.com", "spaceId": "sp1", "groupId": "g3"}]
        self._load(groups, tabs)
        self._start_drag("T1")
        x, y = self._home()
        self._hover(x, y)
        self._drop(x, y)
        assert self._tabs_now() == [("B1", "g1"), ("B2", "g1"), ("T1", "g2"), ("C1", "g3")]
        self._end_drag()

    def test_loose_only_tab_home_drop_noop(self):
        # Единственная негрупповая вкладка: дроп домой — no-op, groupId не присваивается
        groups = [{"id": "g1", "name": "G1", "spaceId": "sp1", "collapsed": False}]
        tabs = [{"name": "B1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "g1"},
                {"name": "B2", "url": "https://b2.com", "spaceId": "sp1", "groupId": "g1"},
                {"name": "T1", "url": "https://t1.com", "spaceId": "sp1"}]
        self._load(groups, tabs)
        self._start_drag("T1")
        x, y = self._home()
        self._hover(x, y)
        self._drop(x, y)
        assert self._tabs_now() == [("B1", "g1"), ("B2", "g1"), ("T1", None)]
        self._end_drag()

    def test_only_tab_ghost_stays_home_on_dragover(self):
        # Заглушка не уезжает в соседнюю группу в момент захвата: над слотом схваченной
        # карточки она остаётся дома (видна, в том же месте, не ниже шапки следующей группы)
        groups = [{"id": "g1", "name": "G1", "spaceId": "sp1", "collapsed": False},
                  {"id": "g2", "name": "G2", "spaceId": "sp1", "collapsed": False}]
        tabs = [{"name": "T1", "url": "https://t1.com", "spaceId": "sp1", "groupId": "g1"},
                {"name": "B1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "g2"}]
        self._load(groups, tabs)
        self._start_drag("T1")
        x, y = self._home()
        self._hover(x, y)
        d = json.loads(self.page.evaluate("""(() => {
          const g = document.querySelector('.tab-ghost-slot');
          const src = window.__srcCard;
          const gbar = document.querySelector('.gbar[data-group-id="g2"]');
          return JSON.stringify({
            home: src.nextElementSibling === g,
            display: g.style.display,
            belowG2: g.getBoundingClientRect().top >= gbar.getBoundingClientRect().bottom
          });
        })()"""))
        assert d["home"] and d["display"] != "none" and not d["belowG2"], d
        self._end_drag()

    def test_only_tab_drag_to_other_group_moves(self):
        # Драг ЕДИНСТВЕННОЙ карточки в слот другой группы (не домой) — всё ещё
        # переезжает (карточка уходит в ту группу)
        groups = [{"id": "g1", "name": "G1", "spaceId": "sp1", "collapsed": False},
                  {"id": "g2", "name": "G2", "spaceId": "sp1", "collapsed": False}]
        tabs = [{"name": "T1", "url": "https://t1.com", "spaceId": "sp1", "groupId": "g1"},
                {"name": "B1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "g2"}]
        self._load(groups, tabs)
        self._start_drag("T1")
        b = self.page.evaluate("""(() => {
          const c = [...document.querySelectorAll('#tabs-list .tab-card')]
            .find(x => x.querySelector('.tab-name').textContent.trim() === 'B1');
          const r = c.getBoundingClientRect();
          return {x: r.left + r.width / 2, y: r.top + r.height / 2};
        })()""")
        self._hover(b["x"], b["y"])
        self._drop(b["x"], b["y"])
        tabs_now = self._tabs_now()
        t1 = [t for t in tabs_now if t[0] == "T1"][0]
        assert t1[1] == "g2", tabs_now
        self._end_drag()


class TestEditTab:
    """Редактирование сохранённой вкладки: ✎ внизу-справа → меню «Изменить» →
    модалка (имя/адрес/комментарий) → update-tab в background + комментарий
    внизу карточки."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    TABS = [
        {"id": "t1", "name": "GitHub", "url": "https://github.com"},
        {"id": "t2", "name": "Docs", "url": "https://docs.example.com",
         "comment": "смотреть раздел API"},
    ]

    def _tabs(self):
        return read_storage_raw(self.page, "blattam-tabs")

    def test_edit_icon_bottom_right_hover_only(self):
        load_view(self.page, tabs=self.TABS)
        # Подгружаем реальные стили (как в других computed-тестах)
        self._inject_real_styles()
        # Уводим курсор от карточки — проверяем состояние «без hover»
        cb = self.page.query_selector(".tab-card").bounding_box()
        self.page.mouse.move(max(0, cb["x"] - 20), max(0, cb["y"] - 20))
        self.page.wait_for_timeout(150)
        d = self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const btn = card.querySelector('.tab-edit');
          if (!btn) return JSON.stringify({err: 'no btn'});
          const cr = card.getBoundingClientRect();
          const br = btn.getBoundingClientRect();
          return JSON.stringify({
            opacity: getComputedStyle(btn).opacity,
            position: getComputedStyle(btn).position,
            inBottomRight: br.right > cr.right - 30 && br.bottom > cr.bottom - 30,
          });
        })()""")
        s = json.loads(d)
        assert s["position"] == "absolute"
        assert s["inBottomRight"]
        assert float(s["opacity"]) < 0.5  # без hover — бледная
        # hover → видимая
        btn = self.page.query_selector(".tab-card .tab-edit")
        btn_box = btn.bounding_box()
        self.page.mouse.move(btn_box["x"] + 5, btn_box["y"] + 5)
        self.page.wait_for_timeout(150)
        op = self.page.evaluate("getComputedStyle(document.querySelector('.tab-card .tab-edit')).opacity")
        assert float(op) >= 0.9

    def _inject_real_styles(self):
        theme = load_file("theme.css")
        html = load_file("view.html")
        style = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate(
            "(styles) => { var st = document.createElement('style'); st.textContent = styles; document.head.appendChild(st); }",
            [theme + "\n" + style])

    def test_comment_renders_inside_card_bottom(self):
        load_view(self.page, tabs=self.TABS)
        d = self.page.evaluate("""(() => {
          const cards = [...document.querySelectorAll('.tab-card')];
          const withComment = cards.find(c => c.querySelector('.tab-comment'));
          const c = withComment.querySelector('.tab-comment');
          const card = withComment.getBoundingClientRect();
          const r = c.getBoundingClientRect();
          return JSON.stringify({
            text: c.textContent,
            nearBottom: r.bottom >= card.bottom - 20 && r.top > card.top,
          });
        })()""")
        s = json.loads(d)
        assert s["text"] == "смотреть раздел API"
        assert s["nearBottom"]
        # У первой вкладки без комментария — элемента нет
        assert self.page.evaluate("document.querySelectorAll('.tab-card')[0].querySelector('.tab-comment') === null")

    def test_edit_menu_opens_with_change_item(self):
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("""(() => {
          document.querySelector('.tab-card .tab-edit').click();
        })()""")
        d = self.page.evaluate("""(() => {
          const m = document.querySelector('.tab-card-menu');
          return JSON.stringify({
            menu: !!m,
            item: m ? m.querySelector('button').textContent : null,
          });
        })()""")
        s = json.loads(d)
        assert s["menu"] and s["item"] == "Изменить"

    def test_change_opens_modal_prefilled_and_dark_bg(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        self.page.evaluate("""(() => {
          document.querySelector('.tab-card .tab-edit').click();
          document.querySelector('.tab-card-menu button').click();
        })()""")
        self.page.wait_for_timeout(80)
        d = self.page.evaluate("""(() => {
          const m = document.getElementById('edit-tab-modal');
          return JSON.stringify({
            open: m.classList.contains('open'),
            overlayBg: getComputedStyle(m).backgroundColor,
            name: document.getElementById('edit-name-input').value,
            url: document.getElementById('edit-url-input').value,
            comment: document.getElementById('edit-comment-input').value,
          });
        })()""")
        s = json.loads(d)
        assert s["open"]
        assert s["name"] == "GitHub" and s["url"] == "https://github.com"
        assert s["comment"] == ""
        # Затемнённый фон: rgba(...) с alpha > 0
        assert "rgba" in s["overlayBg"] and s["overlayBg"] != "rgba(0, 0, 0, 0)"

    def test_save_updates_name_url_comment(self):
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("""(() => {
          document.querySelector('.tab-card .tab-edit').click();
          document.querySelector('.tab-card-menu button').click();
        })()""")
        self.page.wait_for_timeout(60)
        self.page.fill("#edit-name-input", "GitHub — репозиторий")
        self.page.fill("#edit-url-input", "https://github.com/blattam")
        self.page.fill("#edit-comment-input", "примечание к вкладке")
        self.page.click("#edit-confirm")
        self.page.wait_for_timeout(150)
        tabs = self._tabs()
        t1 = next(t for t in tabs if t["id"] == "t1")
        assert t1["name"] == "GitHub — репозиторий"
        assert t1["url"] == "https://github.com/blattam"
        assert t1["comment"] == "примечание к вкладке"
        # Модалка закрыта, карточка перерисована с комментарием
        closed = self.page.evaluate("!document.getElementById('edit-tab-modal').classList.contains('open')")
        comment = self.page.evaluate("(() => { const c = document.querySelector('.tab-card .tab-comment'); return c ? c.textContent : null; })()")
        assert closed and comment == "примечание к вкладке"

    def test_empty_fields_keep_old_values(self):
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("""(() => {
          document.querySelector('.tab-card .tab-edit').click();
          document.querySelector('.tab-card-menu button').click();
        })()""")
        self.page.wait_for_timeout(60)
        self.page.fill("#edit-name-input", "")
        self.page.fill("#edit-url-input", "")
        self.page.fill("#edit-comment-input", "только комментарий")
        self.page.click("#edit-confirm")
        self.page.wait_for_timeout(150)
        t1 = next(t for t in self._tabs() if t["id"] == "t1")
        assert t1["name"] == "GitHub" and t1["url"] == "https://github.com"
        assert t1["comment"] == "только комментарий"

    def test_clear_comment_removes_it(self):
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("""(() => {
          const cards = [...document.querySelectorAll('.tab-card')];
          const card = cards.find(c => c.querySelector('.tab-comment'));
          card.querySelector('.tab-edit').click();
          card.querySelector('.tab-card-menu button').click();
        })()""")
        self.page.wait_for_timeout(60)
        self.page.fill("#edit-comment-input", "")
        self.page.click("#edit-confirm")
        self.page.wait_for_timeout(150)
        t2 = next(t for t in self._tabs() if t["id"] == "t2")
        assert "comment" not in t2
        assert self.page.evaluate("document.querySelectorAll('.tab-comment').length") == 0

    def test_cancel_and_escape_close_overlay_click_keeps_open(self):
        # Отмена — storage не трогается
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("""(() => {
          document.querySelector('.tab-card .tab-edit').click();
          document.querySelector('.tab-card-menu button').click();
        })()""")
        self.page.wait_for_timeout(60)
        self.page.fill("#edit-name-input", "X")
        self.page.click("#edit-cancel")
        self.page.wait_for_timeout(100)
        assert next(t for t in self._tabs() if t["id"] == "t1")["name"] == "GitHub"
        # Esc
        self.page.evaluate("""(() => {
          document.querySelector('.tab-card .tab-edit').click();
          document.querySelector('.tab-card-menu button').click();
        })()""")
        self.page.wait_for_timeout(60)
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(100)
        assert self.page.evaluate("!document.getElementById('edit-tab-modal').classList.contains('open')")
        # Клик по затемнённому фону НЕ закрывает модалку (выделение текста в
        # поле уносит указатель за окно — форма не должна схлопываться);
        # значения в полях сохраняются
        self.page.evaluate("""(() => {
          document.querySelector('.tab-card .tab-edit').click();
          document.querySelector('.tab-card-menu button').click();
        })()""")
        self.page.wait_for_timeout(60)
        self.page.fill("#edit-name-input", "X")
        self.page.evaluate("""(() => {
          const m = document.getElementById('edit-tab-modal');
          m.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        })()""")
        self.page.wait_for_timeout(100)
        assert self.page.evaluate("document.getElementById('edit-tab-modal').classList.contains('open')")
        assert self.page.evaluate("document.getElementById('edit-name-input').value") == "X"

    def test_selection_drag_outside_keeps_modal_open(self):
        # Реальный drag-выделение: mousedown в поле → движение за окно → up
        # снаружи: в Chromium клик срабатывает на общем предке (оверлее) —
        # модалка должна остаться открытой
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        self.page.evaluate("""(() => {
          document.querySelector('.tab-card .tab-edit').click();
          document.querySelector('.tab-card-menu button').click();
        })()""")
        self.page.wait_for_timeout(60)
        self.page.fill("#edit-name-input", "Выбор текста")
        box = self.page.query_selector("#edit-name-input").bounding_box()
        self.page.mouse.move(box["x"] + 5, box["y"] + 5)
        self.page.mouse.down()
        self.page.mouse.move(box["x"] + box["width"] + 150, box["y"] - 80, steps=10)
        self.page.mouse.up()
        self.page.wait_for_timeout(100)
        assert self.page.evaluate("document.getElementById('edit-tab-modal').classList.contains('open')")
        assert self.page.evaluate("document.getElementById('edit-name-input').value") == "Выбор текста"

    def test_enter_saves(self):
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("""(() => {
          document.querySelector('.tab-card .tab-edit').click();
          document.querySelector('.tab-card-menu button').click();
        })()""")
        self.page.wait_for_timeout(60)
        self.page.fill("#edit-name-input", "Через Enter")
        self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(150)
        assert next(t for t in self._tabs() if t["id"] == "t1")["name"] == "Через Enter"

    def test_background_update_tab_direct(self):
        init = "chrome.storage.local._data['blattam-tabs'] = " + json.dumps(self.TABS, ensure_ascii=False) + ";"
        self._load_bg(init)
        send_msg(self.page, "update-tab", index=0, name="N", url="https://n.com", comment="c")
        self.page.wait_for_timeout(30)
        tabs = self._tabs()
        assert tabs[0]["name"] == "N" and tabs[0]["url"] == "https://n.com" and tabs[0]["comment"] == "c"
        send_msg(self.page, "update-tab", index=0, name="", url="", comment="")
        self.page.wait_for_timeout(30)
        tabs = self._tabs()
        assert tabs[0]["name"] == "N" and tabs[0]["url"] == "https://n.com" and "comment" not in tabs[0]

    def _load_bg(self, init_js=""):
        self.page.goto("about:blank")
        self.page.evaluate(MOCK_CHROME + init_js)
        self.page.evaluate(load_file("background.js") + "; 'loaded'")

    def test_edit_icon_drag_guard(self):
        # Нажатие на ✎ + движение — не должно стартовать drag карточки
        load_view(self.page, tabs=self.TABS)
        self.page.evaluate("""(() => {
          const btn = document.querySelector('.tab-card .tab-edit');
          const card = btn.closest('.tab-card');
          btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
          window.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        })()""")
        # Пока pressBtn — карточка не открывается кликом
        self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          card.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        })()""")
        # Drag guard: mousedown on btn → draggable=false
        self.page.evaluate("""(() => {
          const btn = document.querySelector('.tab-card .tab-edit');
          const card = btn.closest('.tab-card');
          btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
          window.__draggableDuringPress = card.draggable;
          window.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
          window.__draggableAfter = card.draggable;
        })()""")
        assert self.page.evaluate("window.__draggableDuringPress === false && window.__draggableAfter === true")


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
#  ПУСТАЯ/СВЁРНУТАЯ ГРУППА: ШАПКА И СЛОТ-ЗАГЛУШКА — ЦЕЛИ ДРОПА КАРТОЧКИ
# ==========================================

class TestEmptyGroupDrop:
    """Шапка группы принимает карточку, когда у группы НЕТ ВИДИМЫХ карточек
    (пустая 0 вкладок ИЛИ свёрнутая). Пустая развёрнутая группа рендерит
    видимую пунктирную слот-заглушку «Перетащите вкладку сюда» под шапкой;
    дроп на шапку/слот = place-tab с anchorIndex null (в конец списка) и
    groupId группы. Группы с видимыми карточками — старый no-op."""

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

    def _parts(self):
        css = load_file("theme.css")
        dark_at = css.index('[data-theme="dark"] {')
        return {"light": css[:dark_at], "dark": css[dark_at:]}

    def _token_color(self, css_part, token):
        # Токен цвета из theme.css (hex ИЛИ rgba()) → строка как отдаёт getComputedStyle
        m = re.search(rf"{token}:\s*(#[0-9a-fA-F]{{3,8}}|rgba?\([^)]*\))", css_part)
        assert m, token
        v = m.group(1)
        if v.startswith("#"):
            h = v[1:]
            if len(h) == 3:
                h = "".join(c2 * 2 for c2 in h)
            return "rgb({0}, {1}, {2})".format(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        nums = [x.strip() for x in v.split("(", 1)[1].strip().strip("()").split(",")]
        return "rgba({0}, {1}, {2}, {3})".format(nums[0], nums[1], nums[2], nums[3])

    def _tab_names(self):
        return json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.name));
        })()"""))

    def _group_of(self, name):
        tabs = read_storage_raw(self.page, "blattam-tabs")
        return next((t.get("groupId") for t in tabs if t["name"] == name), "MISSING")

    def _slots(self):
        return json.loads(self.page.evaluate(
            "JSON.stringify([...document.querySelectorAll('.group-empty-slot')].map(s => s.dataset.groupId))"))

    def _bar(self, gname):
        return ("[...document.querySelectorAll('.gbar')].find(b => b.querySelector('.gname').textContent === "
                + json.dumps(gname, ensure_ascii=False) + ")")

    def _drag_card_to(self, src_idx, target_js, armed_key="armed"):
        """dragstart карточки src_idx → dragover+drop на цель (target_js — JS-выражение
        элемента); window.__armed — класс drop-over после dragover."""
        self.page.evaluate("""(args) => {
          const card = document.querySelectorAll('#tabs-list .tab-card')[args[0]];
          const dst = eval(args[1]);
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const r = dst.getBoundingClientRect();
          const x = r.left + r.width / 2, y = r.top + r.height / 2;
          dst.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
          window.__armed = dst.classList.contains('drop-over');
          dst.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        }""", [src_idx, target_js])
        return self.page.evaluate("window.__armed")

    def _last_message(self):
        return json.loads(self.page.evaluate("JSON.stringify(window.lastMessage || null)"))

    def _place_tab_count(self):
        return self.page.evaluate("chrome.runtime.messagesSent.filter(m => m.action === 'place-tab').length")

    # --- рендер слота ---

    def test_slot_rendered_only_for_expanded_empty_group(self):
        load_view(self.page, spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Empty", "spaceId": "sp1", "collapsed": False},
            {"id": "g2", "name": "Full", "spaceId": "sp1", "collapsed": False},
            {"id": "g3", "name": "Coll", "spaceId": "sp1", "collapsed": True},
        ], tabs=[
            {"name": "X", "url": "https://x.com", "spaceId": "sp1", "groupId": "g2"},
            {"name": "Y", "url": "https://y.com", "spaceId": "sp1", "groupId": "g3"},
        ])
        # Слот — только у пустой развёрнутой g1; сразу после её шапки
        assert self._slots() == ["g1"]
        d = json.loads(self.page.evaluate("""(() => {
          const slot = document.querySelector('.group-empty-slot');
          return JSON.stringify({
            text: slot.textContent,
            draggable: slot.draggable,
            afterBar: slot.previousElementSibling.classList.contains('gbar')
          });
        })()"""))
        assert d == {"text": "Перетащите вкладку сюда", "draggable": False, "afterBar": True}, d

    def test_slot_in_space_without_tabs_with_groups(self):
        # Ветка «пространство без вкладок, но с группами»: слот у развёрнутой,
        # нет у свёрнутой
        load_view(self.page, spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Empty", "spaceId": "sp1", "collapsed": False},
            {"id": "g2", "name": "Coll", "spaceId": "sp1", "collapsed": True},
        ], tabs=[])
        assert self._slots() == ["g1"]
        assert self.page.evaluate("document.getElementById('empty-state').style.display") == "none"

    def test_slot_computed_style_tokens_both_themes(self):
        parts = self._parts()
        for theme in ("light", "dark"):
            load_view(self.page, theme=theme, spaces=self.SP[:1], groups=[
                {"id": "g1", "name": "Empty", "spaceId": "sp1", "collapsed": False},
            ], tabs=[{"name": "A", "url": "https://a.com", "spaceId": "sp1"}])
            self._inject_real_styles()
            self.page.wait_for_timeout(150)  # transition .1s — computed после завершения
            d = json.loads(self.page.evaluate("""(() => {
              const slot = document.querySelector('.group-empty-slot');
              const cs = getComputedStyle(slot);
              const tl = document.getElementById('tabs-list').getBoundingClientRect();
              const r = slot.getBoundingClientRect();
              return JSON.stringify({
                h: cs.height,
                cardH: getComputedStyle(document.querySelector('.tab-card')).height,
                borderStyle: cs.borderTopStyle,
                borderColor: cs.borderTopColor,
                radius: cs.borderRadius,
                font: cs.fontFamily,
                color: cs.color,
                fullRow: Math.abs(r.width - tl.width) < 2
              });
            })()"""))
            assert d["h"] == "74px" and d["cardH"] == "74px", (theme, d)
            assert d["borderStyle"] == "dashed", (theme, d)
            assert d["borderColor"] == self._token_color(parts[theme], "--dashed"), (theme, d)
            assert d["radius"] == "8px", (theme, d)
            assert "Geist Mono" in d["font"], (theme, d)
            assert d["color"] == self._token_color(parts[theme], "--text-faint"), (theme, d)
            assert d["fullRow"] is True, (theme, d)

    # --- армед-вид (drop-over) ---

    def test_dragover_slot_arms_warm_and_dragleave_clears(self):
        load_view(self.page, theme="light", spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Empty", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "A", "url": "https://a.com", "spaceId": "sp1"}])
        self._inject_real_styles()
        self.page.evaluate("""(() => {
          const card = document.querySelector('#tabs-list .tab-card');
          const slot = document.querySelector('.group-empty-slot');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const r = slot.getBoundingClientRect();
          slot.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true,
            clientX: r.left + r.width / 2, clientY: r.top + r.height / 2}));
          window.__dt = dt; window.__slot = slot; window.__card = card;
        })()""")
        self.page.wait_for_timeout(150)  # transition .1s — читать после завершения
        armed = json.loads(self.page.evaluate("""(() => {
          const s = {
            over: window.__slot.classList.contains('drop-over'),
            bg: getComputedStyle(window.__slot).backgroundColor,
            borderColor: getComputedStyle(window.__slot).borderTopColor,
            color: getComputedStyle(window.__slot).color
          };
          window.__slot.dispatchEvent(new DragEvent('dragleave', {bubbles: true}));
          s.left = !window.__slot.classList.contains('drop-over');
          window.__card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
          return JSON.stringify(s);
        })()"""))
        parts = self._parts()
        assert armed["over"] is True and armed["left"] is True, armed
        assert armed["bg"] == self._token_color(parts["light"], "--ghost-bg"), armed
        assert armed["borderColor"] == self._token_color(parts["light"], "--ghost-ring"), armed
        assert armed["color"] == self._token_color(parts["light"], "--text-soft"), armed

    def test_dragover_empty_bar_arms_warm(self):
        load_view(self.page, theme="light", spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Empty", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "A", "url": "https://a.com", "spaceId": "sp1"}])
        self._inject_real_styles()
        self.page.evaluate("""(() => {
          const card = document.querySelector('#tabs-list .tab-card');
          const bar = document.querySelector('.gbar');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const r = bar.getBoundingClientRect();
          bar.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true,
            clientX: r.left + r.width / 2, clientY: r.top + r.height / 2}));
          window.__dt = dt; window.__bar = bar; window.__card = card;
        })()""")
        self.page.wait_for_timeout(150)  # transition .1s — читать после завершения
        armed = json.loads(self.page.evaluate("""(() => {
          const s = {
            over: window.__bar.classList.contains('drop-over'),
            bg: getComputedStyle(window.__bar).backgroundColor,
            color: getComputedStyle(window.__bar).color
          };
          window.__card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
          return JSON.stringify(s);
        })()"""))
        parts = self._parts()
        assert armed["over"] is True, armed
        assert armed["bg"] == self._token_color(parts["light"], "--ghost-bg"), armed
        assert armed["color"] == self._token_color(parts["light"], "--text-soft"), armed

    # --- дроп карточки ---

    def test_drop_on_slot_moves_tab_into_group(self):
        load_view(self.page, spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Empty", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "A", "url": "https://a.com", "spaceId": "sp1"}])
        armed = self._drag_card_to(0, "document.querySelector('.group-empty-slot')")
        assert armed is True
        msg = self._last_message()
        assert msg["action"] == "place-tab"
        assert msg["anchorIndex"] is None and msg["side"] == "after"
        assert msg["groupId"] == "g1" and msg["index"] == 0
        assert self._group_of("A") == "g1"

    def test_slot_drop_sends_exactly_one_place_tab(self):
        load_view(self.page, spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Empty", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "A", "url": "https://a.com", "spaceId": "sp1"}])
        self._drag_card_to(0, "document.querySelector('.group-empty-slot')")
        # Глобальный drop обязан bail'ить на слоте — ровно одно сообщение
        assert self._place_tab_count() == 1, self.page.evaluate("JSON.stringify(chrome.runtime.messagesSent)")
        msg = self._last_message()
        assert msg["action"] == "place-tab" and msg["anchorIndex"] is None and msg["groupId"] == "g1"

    def test_drop_on_empty_bar_moves_tab_into_group(self):
        load_view(self.page, spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Empty", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "A", "url": "https://a.com", "spaceId": "sp1"}])
        armed = self._drag_card_to(0, self._bar("Empty"))
        assert armed is True
        msg = self._last_message()
        assert msg["action"] == "place-tab" and msg["anchorIndex"] is None and msg["groupId"] == "g1"
        assert self._group_of("A") == "g1"

    def test_bar_of_group_with_cards_rejects_card(self):
        # Группа С видимыми карточками: dragover — нет drop-over, drop — no-op
        load_view(self.page, spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Full", "spaceId": "sp1", "collapsed": False},
        ], tabs=[
            {"name": "G", "url": "https://g.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "A", "url": "https://a.com", "spaceId": "sp1"},
        ])
        before = json.dumps(read_storage_raw(self.page, "blattam-tabs"), sort_keys=True)
        armed = self._drag_card_to(1, self._bar("Full"))
        assert armed is False
        assert self._last_message() is None
        assert self._place_tab_count() == 0
        after = json.dumps(read_storage_raw(self.page, "blattam-tabs"), sort_keys=True)
        assert before == after
        assert self._group_of("A") is None

    def test_collapsed_group_bar_arms_and_accepts_card(self):
        # Свёрнутая группа (карточки вне DOM): шапка армится, дроп — карточка в группу
        load_view(self.page, spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Coll", "spaceId": "sp1", "collapsed": True},
        ], tabs=[
            {"name": "G", "url": "https://g.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "A", "url": "https://a.com", "spaceId": "sp1"},
        ])
        # G свёрнутой группы вне DOM — карточек в DOM одна (A, index 0)
        armed = self._drag_card_to(0, self._bar("Coll"))
        assert armed is True
        msg = self._last_message()
        assert msg["action"] == "place-tab" and msg["anchorIndex"] is None and msg["groupId"] == "g1"
        assert self._group_of("A") == "g1"
        assert self._group_of("G") == "g1"

    def test_own_single_card_on_own_bar_noop(self):
        # Единственная карточка группы, перетаскивается (display:none) — шапка армится,
        # но дроп на СВОЮ шапку = no-op
        load_view(self.page, spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "A", "url": "https://a.com", "spaceId": "sp1", "groupId": "g1"}])
        self.page.evaluate("""(() => {
          const card = document.querySelector('#tabs-list .tab-card');
          const bar = document.querySelector('.gbar');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          window.__dt = dt; window.__bar = bar;
        })()""")
        self.page.wait_for_timeout(50)  # отложенный display:none (dragstart setTimeout)
        armed = self.page.evaluate("""(() => {
          const r = window.__bar.getBoundingClientRect();
          const x = r.left + r.width / 2, y = r.top + r.height / 2;
          window.__bar.dispatchEvent(new DragEvent('dragover', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
          const a = window.__bar.classList.contains('drop-over');
          window.__bar.dispatchEvent(new DragEvent('drop', {dataTransfer: window.__dt, bubbles: true, cancelable: true, clientX: x, clientY: y}));
          document.querySelector('#tabs-list .tab-card').dispatchEvent(new DragEvent('dragend', {bubbles: true}));
          return a;
        })()""")
        assert armed is True  # единственный перетаскиваемый член → 0 видимых → армед
        assert self._place_tab_count() == 0
        assert self._group_of("A") == "g1"
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1

    # --- смежное поведение не сломано ---

    def test_bar_reorder_works_when_source_is_empty_group(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "gA", "name": "A", "spaceId": "sp1", "collapsed": False},
            {"id": "gB", "name": "B", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "b1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "gB"}])
        self.page.evaluate("""(() => {
          const bars = [...document.querySelectorAll('.gbar')];
          const src = bars.find(b => b.querySelector('.gname').textContent === 'A');
          const dst = bars.find(b => b.querySelector('.gname').textContent === 'B');
          const r = dst.getBoundingClientRect();
          const y = r.top + Math.max(r.height * 0.75, 0.001);
          const dt = new DataTransfer();
          src.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          dst.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true, clientY: y}));
          dst.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true, clientY: y}));
          src.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        })()""")
        names = json.loads(self.page.evaluate("""(async () => {
          var d = await chrome.storage.get('blattam-groups');
          return JSON.stringify((d['blattam-groups'] || []).map(g => g.name));
        })()"""))
        assert names == ["B", "A"], names
        assert self._group_of("b1") == "gB"
        assert self._place_tab_count() == 0

    def test_card_drop_on_space_chip_intact(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Empty", "spaceId": "sp1", "collapsed": False},
        ], tabs=[{"name": "A", "url": "https://a.com", "spaceId": "sp1"}])
        self.page.evaluate("""(args) => {
          const card = document.querySelector('#tabs-list .tab-card');
          const chip = document.querySelector('.space-chip[data-space-id="sp2"]');
          const dt = new DataTransfer();
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          chip.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
          chip.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
          card.dispatchEvent(new DragEvent('dragend', {bubbles: true}));
        }""", "sp2")
        msg = self._last_message()
        assert msg["action"] == "move-tab" and msg["spaceId"] == "sp2"
        tab = read_storage_raw(self.page, "blattam-tabs")[0]
        assert tab["spaceId"] == "sp2" and tab["groupId"] is None

    def test_add_group_row_still_last_element(self):
        load_view(self.page, spaces=self.SP[:1], groups=[
            {"id": "g1", "name": "Empty", "spaceId": "sp1", "collapsed": False},
            {"id": "g2", "name": "Coll", "spaceId": "sp1", "collapsed": True},
        ], tabs=[])
        assert self.page.evaluate("document.getElementById('tabs-list').lastElementChild.id") == "add-group-btn"
        assert self._slots() == ["g1"]
        # Слот — внутри секции группы (между шапкой g1 и шапкой g2)
        assert json.loads(self.page.evaluate(
            "JSON.stringify([...document.getElementById('tabs-list').children].map(e => e.className))")) == \
            ["gbar", "group-empty-slot", "gbar", "add-group-row"]


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
        # data: URL — детерминированная загрузка без сети (onerror не сработает)
        fav = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        load_view(self.page, tabs=[
            {"name": "GitHub", "url": "https://github.com", "favIconUrl": fav},
        ])
        src = self.page.evaluate("(() => { var i = document.querySelector('.tab-card .tab-favicon'); return i ? i.src : null; })()")
        assert src == fav
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
#  VIEW.JS: ИНЛАЙН-РЕНЕЙМ ГРУППЫ (✎ В ШАПКЕ)
# ==========================================

class TestGroupRename:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}]
    GROUPS = [{"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False}]
    TABS = [
        {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
    ]

    def _open_rename_input(self):
        self.page.evaluate("document.querySelector('.gbar .grename').click()")
        assert self.page.evaluate("!!document.querySelector('.gbar .gname-input')")

    def test_rename_input_prefilled_with_current_name(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._open_rename_input()
        # .gname заменён на <input> внутри .gbar, заполнен текущим именем
        val = self.page.evaluate("document.querySelector('.gbar .gname-input').value")
        assert val == "Dev"
        assert self.page.evaluate("!!document.querySelector('.gbar .gname')") is False

    def test_rename_saves_on_enter(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._open_rename_input()
        self.page.evaluate("""(() => {
          const inp = document.querySelector('.gbar .gname-input');
          inp.value = 'NewDev';
          inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
        })()""")
        groups = read_storage_raw(self.page, "blattam-groups")
        assert len(groups) == 1 and groups[0]["name"] == "NewDev"
        assert self.page.evaluate("document.querySelector('.gbar .gname').textContent") == "NewDev"
        # Вкладки группы не тронуты
        tabs = read_storage_raw(self.page, "blattam-tabs")
        assert [t["name"] for t in tabs] == ["D1", "D2"]
        assert all(t["groupId"] == "g1" for t in tabs)
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 2

    def test_rename_cancel_on_escape(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._open_rename_input()
        self.page.evaluate("""(() => {
          const inp = document.querySelector('.gbar .gname-input');
          inp.value = 'Hacked';
          inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
        })()""")
        assert read_storage_raw(self.page, "blattam-groups")[0]["name"] == "Dev"
        assert self.page.evaluate("document.querySelector('.gbar .gname').textContent") == "Dev"

    def test_rename_empty_name_keeps_old(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._open_rename_input()
        self.page.evaluate("""(() => {
          const inp = document.querySelector('.gbar .gname-input');
          inp.value = '   ';
          inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
        })()""")
        assert read_storage_raw(self.page, "blattam-groups")[0]["name"] == "Dev"
        assert self.page.evaluate("document.querySelector('.gbar .gname').textContent") == "Dev"

    def test_rename_click_does_not_toggle_collapse(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 2
        self._open_rename_input()
        # Клик по ✎ не сворачивает группу: состояние в данных и в DOM без изменений
        assert read_storage_raw(self.page, "blattam-groups")[0]["collapsed"] is False
        assert self.page.evaluate("document.querySelector('.gbar .chev').textContent") == "\u25BE"
        self.page.evaluate("document.querySelector('.gbar .gname-input').blur()")
        assert read_storage_raw(self.page, "blattam-groups")[0]["collapsed"] is False
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 2


# ==========================================
#  VIEW.JS: ЧЕКБОКС НА МЕСТЕ ФАВИКОНА ПРИ HOVER / ВЫБОРЕ
# ==========================================

class TestHoverCheckbox:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    # favIconUrl — data:-URL: <img> загружается гарантированно без network-error
    # (иначе onerror-хендлер поменяет img на буквенный fallback и тест станет
    # гонкой с сетью)
    TABS = [
        {"name": "A", "url": "https://a.com", "favIconUrl": "data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="},
        {"name": "B", "url": "https://b.com"},
    ]

    def _inject_real_styles(self):
        # Харнес ставит только body.innerHTML — подгружаем настоящие стили
        # (theme.css + <style> view.html), чтобы computed-значения были реальными
        theme = load_file("theme.css")
        html = load_file("view.html")
        style = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate(
            "(styles) => { var st = document.createElement('style'); st.textContent = styles; document.head.appendChild(st); }",
            [theme + "\n" + style])

    def test_no_hover_favicon_visible_checkbox_faint(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        self.page.mouse.move(0, 0)  # сбрасываем хover-курсор от предыдущих тестов
        self.page.wait_for_timeout(180)  # transition opacity .12s
        d = json.loads(self.page.evaluate("""(() => {
          const cards = document.querySelectorAll('.tab-card');
          return JSON.stringify({
            fav: getComputedStyle(cards[0].querySelector('.tab-favicon')).visibility,
            fb: getComputedStyle(cards[1].querySelector('.tab-favicon-fallback')).visibility,
            sel: getComputedStyle(cards[0].querySelector('.tab-select')).opacity
          });
        })()"""))
        assert d == {"fav": "visible", "fb": "visible", "sel": "0"}, d

    def test_hover_hides_favicon_and_shows_checkbox(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        self.page.locator(".tab-card").first.hover()
        self.page.wait_for_timeout(200)  # transition opacity .12s
        d = json.loads(self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          return JSON.stringify({
            fav: getComputedStyle(card.querySelector('.tab-favicon')).visibility,
            sel: getComputedStyle(card.querySelector('.tab-select')).opacity
          });
        })()"""))
        assert d == {"fav": "hidden", "sel": "1"}, d

    def test_hover_checkbox_occupies_favicon_slot(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        self.page.locator(".tab-card").first.hover()
        self.page.wait_for_timeout(200)
        d = json.loads(self.page.evaluate("""(() => {
          const card = document.querySelector('.tab-card');
          const r = card.querySelector('.tab-select').getBoundingClientRect();
          const cr = card.getBoundingClientRect();
          return JSON.stringify({
            left: r.left - cr.left, top: r.top - cr.top,
            width: r.width, height: r.height
          });
        })()"""))
        # Слот фавикона: 10px/8px от краёв карточки, 15×15, имя не сдвинуто
        assert abs(d["left"] - 10) <= 1, d
        assert abs(d["top"] - 8) <= 1, d
        assert d["width"] == 15 and d["height"] == 15, d

    def test_click_checkbox_while_hovered_selects(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        self.page.locator(".tab-card").first.hover()
        self.page.locator(".tab-card .tab-select").first.click()
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 1
        assert self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')") is False
        assert self.page.evaluate("document.getElementById('selection-count').textContent") == "1 выбрано"

    def test_unhover_selected_keeps_checkbox_unselected_restores_favicon(self):
        load_view(self.page, tabs=self.TABS)
        self._inject_real_styles()
        self.page.locator(".tab-card").first.hover()
        self.page.locator(".tab-card .tab-select").first.click()
        self.page.mouse.move(2, 2)  # unhover: мышь в угол страницы, вне карточек
        self.page.wait_for_timeout(200)
        d = json.loads(self.page.evaluate("""(() => {
          const cards = document.querySelectorAll('.tab-card');
          const sel = cards[0], unsel = cards[1];
          return JSON.stringify({
            selSelOpacity: getComputedStyle(sel.querySelector('.tab-select')).opacity,
            selFavVisibility: getComputedStyle(sel.querySelector('.tab-favicon')).visibility,
            unFavVisibility: getComputedStyle(unsel.querySelector('.tab-favicon-fallback')).visibility,
            unSelOpacity: getComputedStyle(unsel.querySelector('.tab-select')).opacity
          });
        })()"""))
        assert d["selSelOpacity"] == "1", d
        assert d["selFavVisibility"] == "hidden", d
        assert d["unFavVisibility"] == "visible", d
        assert d["unSelOpacity"] == "0", d


# ==========================================
#  VIEW.JS: ☑ ВЫБРАТЬ ВСЕ ВКЛАДКИ ГРУППЫ
# ==========================================

class TestSelectGroup:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}]
    GROUPS = [{"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False}]
    TABS = [
        {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
    ]

    def _click_gselect(self):
        self.page.evaluate("document.querySelector('.gbar .gselect').click()")

    def test_gselect_selects_all_group_tabs(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._click_gselect()
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 2
        assert self.page.evaluate("document.querySelectorAll('.tab-select:checked').length") == 2
        assert self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')") is False
        assert self.page.evaluate("document.getElementById('selection-count').textContent") == "2 выбрано"
        # Кнопка в активном (заполненном) состоянии
        assert self.page.evaluate("document.querySelector('.gbar .gselect').classList.contains('on')")

    def test_gselect_second_click_deselects(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._click_gselect()
        self._click_gselect()
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 0
        assert self.page.evaluate("document.querySelectorAll('.tab-select:checked').length") == 0
        assert self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')") is True
        assert not self.page.evaluate("document.querySelector('.gbar .gselect').classList.contains('on')")

    def test_gselect_add_branch_from_partial(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self.page.evaluate("document.querySelectorAll('.tab-select')[0].click()")
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 1
        self._click_gselect()
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 2
        assert self.page.evaluate("document.getElementById('selection-count').textContent") == "2 выбрано"

    def test_gselect_works_on_collapsed_group(self):
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": True},
        ], tabs=self.TABS)
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 0
        self._click_gselect()
        # Карточек в DOM нет, но выбор стоит на обеих вкладках группы
        assert self.page.evaluate("document.getElementById('selection-count').textContent") == "2 выбрано"
        assert self.page.evaluate("document.querySelector('.gbar .gselect').classList.contains('on')")
        # Разворачиваем — обе карточки отрендерены как selected (выбор пережил перерисовку)
        self.page.evaluate("document.querySelector('.gbar').click()")
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 2

# ==========================================
#  VIEW.JS: КОНТРОЛЫ ГРУППЫ (☑/✎) ПОСЛЕ МАССОВОГО ВЫБОРА
# ==========================================

class TestGroupControlsAfterSelect:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        self.page_errors = []
        page.on("pageerror", lambda err: self.page_errors.append(str(err)))

    SP = [{"id": "sp1", "name": "Main"}]
    GROUPS = [{"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False}]
    TABS = [
        {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
    ]

    def _inject_real_styles(self):
        # Харнес ставит только body.innerHTML — подгружаем настоящие стили
        # (theme.css + <style> view.html), чтобы computed-значения были реальными
        theme = load_file("theme.css")
        html = load_file("view.html")
        style = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate(
            "(styles) => { var st = document.createElement('style'); st.textContent = styles; document.head.appendChild(st); }",
            [theme + "\n" + style])

    def _hover_gbar_opacities(self):
        self.page.hover(".gbar")
        self.page.wait_for_timeout(200)  # transition opacity .12s
        return json.loads(self.page.evaluate("""(() => {
          const bar = document.querySelector('.gbar');
          return JSON.stringify({
            selExists: !!bar.querySelector('.gselect'),
            renExists: !!bar.querySelector('.grename'),
            sel: bar.querySelector('.gselect') ? getComputedStyle(bar.querySelector('.gselect')).opacity : null,
            ren: bar.querySelector('.grename') ? getComputedStyle(bar.querySelector('.grename')).opacity : null
          });
        })()"""))

    def test_controls_stay_working_after_mass_select(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._inject_real_styles()
        # До выбора: hover показывает оба контрола
        assert self._hover_gbar_opacities() == {"selExists": True, "renExists": True, "sel": "1", "ren": "1"}
        # ☑ — массовый выбор всех вкладок группы
        self.page.click(".gbar .gselect")
        assert self.page_errors == [], self.page_errors
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 2
        # После выбора: контролы всё ещё в DOM и видны при hover
        d = self._hover_gbar_opacities()
        assert d == {"selExists": True, "renExists": True, "sel": "1", "ren": "1"}, d
        assert self.page_errors == [], self.page_errors
        # Второй клик по ☑ — снимает выбор, контролы продолжают работать
        self.page.click(".gbar .gselect")
        assert self.page_errors == [], self.page_errors
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 0
        assert self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')") is True
        d2 = self._hover_gbar_opacities()
        assert d2 == {"selExists": True, "renExists": True, "sel": "1", "ren": "1"}, d2

    def test_controls_stay_working_with_search_filter(self):
        # Поиск фильтрует карточки, но контролы группы не теряются
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._inject_real_styles()
        self.page.fill("#search", "d1")
        self.page.click(".gbar .gselect")
        assert self.page_errors == [], self.page_errors
        d = self._hover_gbar_opacities()
        assert d == {"selExists": True, "renExists": True, "sel": "1", "ren": "1"}, d
        # Обе вкладки группы выбраны (независимо от фильтра)
        assert self.page.evaluate("document.getElementById('selection-count').textContent") == "2 выбрано"

    def test_controls_stay_working_on_collapsed_group(self):
        # Свёрнутая группа: карточек в DOM нет, контролы — как всегда
        load_view(self.page, spaces=self.SP, groups=[
            {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": True},
        ], tabs=self.TABS)
        self._inject_real_styles()
        self.page.click(".gbar .gselect")
        assert self.page_errors == [], self.page_errors
        assert self.page.evaluate("document.querySelector('.gbar .gselect').classList.contains('on')")
        d = self._hover_gbar_opacities()
        assert d == {"selExists": True, "renExists": True, "sel": "1", "ren": "1"}, d
        self.page.click(".gbar .gselect")
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 0


# ==========================================
#  VIEW.JS: ЗАЩИТА КНОПОК ОТ DRAG (реальный Chrome: press + движение >~5px
#  на draggable-родителе запускает drag и «проглатывает» click по кнопке;
#  синтетический .click() это не ловит — здесь реальные mouse-события)
# ==========================================

class TestGroupControlsDragGuard:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        self.page_errors = []
        page.on("pageerror", lambda err: self.page_errors.append(str(err)))

    def _arm_drag_counter(self):
        # load_view делает goto(about:blank) — счётчик вешаем после него
        self.page.evaluate("window.__dragStarts = 0; document.addEventListener('dragstart', () => { window.__dragStarts++; }, true);")

    SP = [{"id": "sp1", "name": "Main"}, {"id": "sp2", "name": "Second"}]
    GROUPS = [
        {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False},
        {"id": "g2", "name": "Read", "spaceId": "sp1", "collapsed": False},
    ]
    TABS = [
        {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "R1", "url": "https://r1.com", "spaceId": "sp1", "groupId": "g2"},
    ]

    def _press_with_jitter(self, selector, dx, dy):
        """Реальное нажатие: hover -> down -> движение (dx, dy) -> up."""
        box = self.page.evaluate(f"(() => {{ const r = document.querySelector('{selector}').getBoundingClientRect(); return {{x: r.x + r.width/2, y: r.y + r.height/2}}; }})()")
        self.page.mouse.move(box["x"] - 40, box["y"] - 24, steps=3)
        self.page.wait_for_timeout(60)
        self.page.mouse.move(box["x"], box["y"], steps=2)
        self.page.wait_for_timeout(80)
        self.page.mouse.down()
        self.page.wait_for_timeout(60)
        self.page.mouse.move(box["x"] + dx, box["y"] + dy, steps=2)
        self.page.wait_for_timeout(50)
        self.page.mouse.up()
        self.page.wait_for_timeout(300)

    def test_jittered_gselect_click_selects_without_drag(self):
        # Движение 7px во время press НЕ должно унести клик drag-ом шапки
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._arm_drag_counter()
        self.page.hover(".gbar")
        self._press_with_jitter(".gbar .gselect", 7, 2)
        assert self.page_errors == [], self.page_errors
        assert self.page.evaluate("window.__dragStarts") == 0
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 2
        assert self.page.evaluate("document.querySelector('.gbar .gselect').classList.contains('on')")
        # Группа не свёрнута, шапка без «застрявших» классов
        assert self.page.evaluate("document.querySelector('.gbar').className") == "gbar"
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 3

    def test_jittered_grename_click_opens_input_without_drag(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._arm_drag_counter()
        self.page.hover(".gbar")
        self._press_with_jitter(".gbar .grename", -6, 3)
        assert self.page_errors == [], self.page_errors
        assert self.page.evaluate("window.__dragStarts") == 0
        assert self.page.evaluate("!!document.querySelector('.gbar .gname-input')")
        self.page.evaluate("document.querySelector('.gbar .gname-input').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        assert self.page.evaluate("document.querySelector('.gbar .gname').textContent") == "Dev"

    def test_jittered_card_checkbox_selects_without_drag(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._arm_drag_counter()
        self.page.hover(".tab-card")
        self._press_with_jitter(".tab-card .tab-select", 3, 1)
        assert self.page_errors == [], self.page_errors
        assert self.page.evaluate("window.__dragStarts") == 0
        assert self.page.evaluate("document.querySelector('.tab-card').classList.contains('selected')")
        assert self.page.evaluate("document.getElementById('selection-count').textContent") == "1 выбрано"

    def test_button_press_drift_to_bar_does_not_collapse(self):
        # Press начался на ☑, мышь сошла на шапку, release — группа НЕ сворачивается
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._arm_drag_counter()
        self.page.hover(".gbar")
        self._press_with_jitter(".gbar .gselect", -14, 0)
        assert self.page_errors == [], self.page_errors
        assert self.page.evaluate("window.__dragStarts") == 0
        assert self.page.evaluate("document.querySelector('.gbar .chev').textContent") == "\u25BE"
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 3
        assert read_storage_raw(self.page, "blattam-groups")[0]["collapsed"] is False

    def test_bar_drag_from_name_still_reorders_groups(self):
        # Drag по-прежнему работает от имени/чепрона (не только от кнопок)
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._arm_drag_counter()
        src = self.page.evaluate("(() => { const r = document.querySelector('.gbar .gname').getBoundingClientRect(); return {x: r.x + r.width/2, y: r.y + r.height/2}; })()")
        dst = self.page.evaluate("(() => { const r = document.querySelectorAll('.gbar')[1].getBoundingClientRect(); return {x: r.x + r.width/2, y: r.top + r.height * 0.75}; })()")
        self.page.mouse.move(src["x"], src["y"], steps=3)
        self.page.wait_for_timeout(60)
        self.page.mouse.down()
        self.page.wait_for_timeout(60)
        self.page.mouse.move(dst["x"], dst["y"], steps=10)
        self.page.wait_for_timeout(100)
        self.page.mouse.up()
        self.page.wait_for_timeout(300)
        assert self.page_errors == [], self.page_errors
        assert self.page.evaluate("window.__dragStarts") == 1
        # g1 переехала ПОСЛЕ g2 — порядок в данных
        ids = [g["id"] for g in read_storage_raw(self.page, "blattam-groups")]
        assert ids == ["g2", "g1"], ids

    def test_card_drag_from_name_still_reorders_tabs(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)
        self._arm_drag_counter()
        src = self.page.evaluate("(() => { const c = document.querySelectorAll('.tab-card')[0]; const r = c.getBoundingClientRect(); return {x: r.x + r.width/2, y: r.y + r.height/2}; })()")
        # D2 справа от центра — зазор ПОСЛЕ D2 (ghost-slot держит ряд D2 на месте,
        # поэтому дроп в нижнюю половину с x=центр дал бы «до D2» по правилу gap-индекса)
        dst = self.page.evaluate("(() => { const c = document.querySelectorAll('.tab-card')[1]; const r = c.getBoundingClientRect(); return {x: r.x + r.width * 0.75, y: r.top + r.height * 0.75}; })()")
        self.page.mouse.move(src["x"], src["y"], steps=3)
        self.page.wait_for_timeout(60)
        self.page.mouse.down()
        self.page.wait_for_timeout(60)
        self.page.mouse.move(dst["x"], dst["y"], steps=10)
        self.page.wait_for_timeout(100)
        self.page.mouse.up()
        self.page.wait_for_timeout(300)
        assert self.page_errors == [], self.page_errors
        names = [t["name"] for t in read_storage_raw(self.page, "blattam-tabs")]
        # D1 переехала ПОСЛЕ D2: порядок внутри g1 — D2, D1
        assert names == ["D2", "D1", "R1"], names


# ==========================================
#  VIEW.JS: ☑ «Без группы» — ВЫБОР ВСЕХ НЕГРУППОВЫХ ВКЛАДОК ПРОСТРАНСТВА
# ==========================================

class TestLooseSelectAll:
    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}]
    GROUPS = [{"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False}]
    TABS = [
        {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
        {"name": "L Alpha", "url": "https://la.com", "spaceId": "sp1"},
        {"name": "L Beta", "url": "https://lb.com", "spaceId": "sp1"},
    ]

    def _load(self):
        load_view(self.page, spaces=self.SP, groups=self.GROUPS, tabs=self.TABS)

    def _click(self):
        self.page.evaluate("document.querySelector('.loose-label .loose-select').click()")

    def test_loose_label_rendered_with_select_button(self):
        # Подпись «Без группы» рендерится (группы И негрупповые есть) с кнопкой ☑,
        # в неактивном состоянии
        self._load()
        d = self.page.evaluate("""(() => {
          const lbl = document.querySelector('.loose-label');
          if (!lbl) return null;
          const btn = lbl.querySelector('.loose-select');
          if (!btn) return null;
          return {text: lbl.textContent, glyph: btn.textContent,
                  on: btn.classList.contains('on')};
        })()""")
        assert d is not None
        assert d["glyph"] == "\u2611"
        assert "Без группы" in d["text"]
        assert d["on"] is False

    def test_click_selects_all_loose_tabs_only(self):
        self._load()
        self._click()
        d = json.loads(self.page.evaluate("""(() => {
          const sel = [...document.querySelectorAll('.tab-card.selected')].map(c => c.__tab.url);
          return JSON.stringify({sel,
            barHidden: document.getElementById('selection-bar').classList.contains('hidden'),
            count: document.getElementById('selection-count').textContent});
        })()"""))
        # Выделены ТОЛЬКО негрупповые вкладки; батч-бар виден со счётчиком
        assert sorted(d["sel"]) == ["https://la.com", "https://lb.com"], d
        assert d["barHidden"] is False
        assert d["count"] == "2 выбрано"

    def test_second_click_deselects_all(self):
        self._load()
        self._click()
        self._click()
        assert self.page.evaluate("document.querySelectorAll('.tab-card.selected').length") == 0
        assert self.page.evaluate("document.getElementById('selection-bar').classList.contains('hidden')") is True
        assert not self.page.evaluate("document.querySelector('.loose-label .loose-select').classList.contains('on')")

    def test_button_on_when_all_loose_selected(self):
        # Все негрупповые выделены — кнопка в активном (заполненном) состоянии
        self._load()
        self._click()
        assert self.page.evaluate("document.querySelector('.loose-label .loose-select').classList.contains('on')")

    def test_selection_covers_full_loose_set_under_filter(self):
        # Поиск сужает видимые негрупповые карточки до одной — клик по ☑ всё равно
        # выделяет ПОЛНЫЙ набор негрупповых вкладок пространства, а не видимые
        self._load()
        self.page.evaluate("""(() => {
          const inp = document.getElementById('search');
          inp.value = 'Alpha';
          inp.dispatchEvent(new Event('input', {bubbles: true}));
        })()""")
        assert self.page.evaluate("document.querySelectorAll('.tab-card').length") == 1
        self._click()
        assert self.page.evaluate("document.getElementById('selection-count').textContent") == "2 выбрано"
        # Снимаем фильтр — обе негрупповые вкладки стоят выделенными
        self.page.evaluate("""(() => {
          const inp = document.getElementById('search');
          inp.value = '';
          inp.dispatchEvent(new Event('input', {bubbles: true}));
        })()""")
        d = json.loads(self.page.evaluate("""(() => {
          const sel = [...document.querySelectorAll('.tab-card.selected')].map(c => c.__tab.url);
          return JSON.stringify({sel});
        })()"""))
        assert sorted(d["sel"]) == ["https://la.com", "https://lb.com"], d



class TestDragRowKeeper:
    """Row keeper: невидимый placeholder в КОНЦЕ исходной секции. Пока
    ghost-slot находится в исходной секции (дома или где ещё), сам ghost
    занимает один слот — keeper в DOM не подключается; когда ghost уходит в
    ДРУГУЮ секцию, row-keeper встаёт в конце исходной: карточки закрывают
    высвобожденный слот (без «дырки»), а число строк секции не меняется —
    список под ней не сдвигается при быстром перетаскивании. На dragend —
    без следов."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}]
    TABS3 = [
        {"name": "A", "url": "https://a.com", "spaceId": "sp1"},
        {"name": "B", "url": "https://b.com", "spaceId": "sp1"},
        {"name": "C", "url": "https://c.com", "spaceId": "sp1"},
    ]

    def _start_drag(self, idx):
        self.page.evaluate("""(idx) => {
          const card = document.querySelectorAll('#tabs-list .tab-card')[idx];
          window.__srcCard = card;
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart',
            {dataTransfer: dt, bubbles: true, cancelable: true}));
        }""", idx)
        self.page.wait_for_timeout(50)  # отложенное скрытие карточки + ghost-slot

    def _dragover_card(self, idx):
        self.page.evaluate("""(idx) => {
          const card = document.querySelectorAll('#tabs-list .tab-card')[idx];
          const r = card.getBoundingClientRect();
          card.dispatchEvent(new DragEvent('dragover', {
            dataTransfer: window.__dt, bubbles: true, cancelable: true,
            clientX: r.left + r.width / 2, clientY: r.top + r.height / 2
          }));
        }""", idx)

    def _end_drag(self):
        self.page.evaluate("""(() => {
          const card = window.__srcCard;
          if (card) card.dispatchEvent(new DragEvent('dragend',
            {bubbles: true, cancelable: true}));
        })()""")

    def _anchor_top(self):
        return self.page.evaluate(
            "document.getElementById('add-group-btn').getBoundingClientRect().top")

    def _inject_css(self):
        css = load_file("theme.css")
        html = load_file("view.html")
        style_block = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate("""(css) => {
          const s = document.createElement('style');
          s.textContent = css;
          document.head.appendChild(s);
        }""", css + style_block)

    def test_no_keeper_and_refill_when_ghost_stays_in_section(self):
        # Ghost ушёл от дома, но остаётся В СЕКЦИИ: .tab-row-keeper в DOM нет,
        # слот скрытой карточки закрыт reflow (B встаёт в слот C), якорь под
        # списком не сдвинулся
        load_view(self.page, spaces=self.SP, tabs=self.TABS3)
        self._inject_css()  # реальная сетка: 3 карточки = одна строка
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.wait_for_timeout(50)
        pre = self._anchor_top()
        c_before = json.loads(self.page.evaluate("""(() => {
          const b = document.querySelectorAll('#tabs-list .tab-card')[2].getBoundingClientRect();
          return JSON.stringify({left: b.left, top: b.top});
        })()"""))
        self._start_drag(2)
        self._dragover_card(0)
        d = json.loads(self.page.evaluate("""(() => {
          const src = window.__srcCard;
          const slot = document.querySelector('.tab-ghost-slot');
          const b = document.querySelectorAll('#tabs-list .tab-card')[1];
          const bb = b.getBoundingClientRect();
          return JSON.stringify({
            keepers: document.querySelectorAll('.tab-row-keeper').length,
            srcDisplay: src.style.display,
            slotAtStart: document.getElementById('tabs-list').firstElementChild === slot,
            bLeft: bb.left, bTop: bb.top,
            top: document.getElementById('add-group-btn').getBoundingClientRect().top
          });
        })()"""))
        assert d["keepers"] == 0, d
        assert d["srcDisplay"] == "none", d
        assert d["slotAtStart"], d  # заглушка в начале списка (до A)
        assert abs(d["bLeft"] - c_before["left"]) < 2 and abs(d["bTop"] - c_before["top"]) < 2, (c_before, d)
        assert abs(d["top"] - pre) < 2, (pre, d["top"])
        self._end_drag()

    def test_dragend_removes_keeper_and_restores_card(self):
        # Drag без drop: keeper и ghost-заглушка сняты, карточка снова в слоте
        load_view(self.page, spaces=self.SP, tabs=self.TABS3)
        self._start_drag(2)
        self._dragover_card(0)
        self._end_drag()
        d = json.loads(self.page.evaluate("""(() => JSON.stringify({
          keepers: document.querySelectorAll('.tab-row-keeper').length,
          slots: document.querySelectorAll('.tab-ghost-slot').length,
          srcDisplay: window.__srcCard.style.display,
          srcConnected: window.__srcCard.isConnected,
          cards: document.querySelectorAll('#tabs-list .tab-card').length
        }))()"""))
        assert d["keepers"] == 0 and d["slots"] == 0, d
        assert d["srcDisplay"] == "" and d["srcConnected"] and d["cards"] == 3, d

    def test_no_keeper_while_ghost_at_home(self):
        # Ghost-заглушка стоит СРАЗУ ПОСЛЕ скрытой карточки (дом) — keeper
        # в DOM не подключается
        load_view(self.page, spaces=self.SP, tabs=self.TABS3)
        self._start_drag(0)
        self._dragover_card(0)  # over своей карточке — слот остался дома
        d = json.loads(self.page.evaluate("""(() => JSON.stringify({
          keepers: document.querySelectorAll('.tab-row-keeper').length,
          slotAtHome: window.__srcCard.nextElementSibling ===
            document.querySelector('.tab-ghost-slot')
        }))()"""))
        assert d["keepers"] == 0, d
        assert d["slotAtHome"], d
        self._end_drag()

    def test_cross_section_keeper_at_source_tail_real_grid(self):
        # Реальная сетка (theme.css + стили view.html), 1280 → 6 колонок:
        # группа (2 вкладки) сверху + 13 негрупповых (6+6+1). Последняя вкладка
        # в одиночестве в последней строке перетаскивается в группу: keeper
        # стоит в КОНЦЕ исходной (loose) секции (после последней видимой
        # карточки, не за захваченной), строка не схлопывается — якорь под
        # списком стоит на месте
        tabs = [
            {"name": "M1", "url": "https://m1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "M2", "url": "https://m2.com", "spaceId": "sp1", "groupId": "g1"},
        ] + [
            {"name": f"T{i}", "url": f"https://t{i}.com", "spaceId": "sp1"}
            for i in range(1, 14)
        ]
        load_view(self.page, spaces=self.SP,
                  groups=[{"id": "g1", "name": "G", "spaceId": "sp1", "collapsed": False}],
                  tabs=tabs, last_space="sp1")
        self._inject_css()
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.wait_for_timeout(50)
        pre = self._anchor_top()
        self._start_drag(14)  # последняя негрупповая (одинокая в последней строке)
        self._dragover_card(0)  # карточка группы — за пределами секции
        d = json.loads(self.page.evaluate("""(() => {
          const k = document.querySelector('.tab-row-keeper');
          const tail = document.querySelectorAll('#tabs-list .tab-card')[13];  // T12 — последняя видимая loose
          return JSON.stringify({
            keeperExists: !!k,
            keeperAfterSectionTail: !!k && tail.nextElementSibling === k,
            notAfterSource: !!k && window.__srcCard.nextElementSibling !== k,
            srcHidden: window.__srcCard.style.display === 'none',
            opacity: k ? k.style.opacity : null,
            pointerEvents: k ? k.style.pointerEvents : null,
            top: document.getElementById('add-group-btn').getBoundingClientRect().top
          });
        })()"""))
        assert d["keeperExists"] and d["keeperAfterSectionTail"] and d["notAfterSource"] and d["srcHidden"], d
        assert d["opacity"] == "0" and d["pointerEvents"] == "none", d
        assert abs(d["top"] - pre) < 2, (pre, d["top"])
        self._end_drag()


class TestEmptyGroupAutoCollapse:
    """Автосворачивание: группа, потерявшая ПОСЛЕДНЮЮ вкладку (перенос в
    «Без группы» или удаление ✕), сворачивается сама — вместо шапки с
    «Перетащите вкладку сюда» — свёрнутая шапка «0 вкладок». Пустая группа,
    только что созданная или раскрытая вручную, остаётся развёрнутой
    (слот = цель дропа)."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page

    SP = [{"id": "sp1", "name": "Main"}]
    G1 = {"id": "g1", "name": "Dev", "spaceId": "sp1", "collapsed": False}

    def _collapsed(self):
        return read_storage_raw(self.page, "blattam-groups")[0]["collapsed"]

    def test_last_tab_moved_out_collapses_group(self):
        # Единственная вкладка группы уезжает в «Без группы» (place-tab,
        # groupId null) — группа сворачивается: ▸ + «0 вкладок», слота нет
        load_view(self.page, spaces=self.SP, groups=[dict(self.G1)],
                  tabs=[{"name": "D1", "url": "https://d1.com",
                         "spaceId": "sp1", "groupId": "g1"}])
        self.page.evaluate("""chrome.runtime.sendMessage({action: 'place-tab',
            index: 0, anchorIndex: 1, side: 'after', groupId: null})""")
        self.page.wait_for_timeout(100)
        assert self.page.evaluate("document.querySelector('.gbar .chev').textContent") == "▸"
        assert self.page.evaluate("document.querySelectorAll('.group-empty-slot').length") == 0
        assert self.page.evaluate("document.querySelector('.gbar .gcount').textContent") == "0 вкладок"
        assert self._collapsed() is True

    def test_group_with_two_tabs_stays_expanded(self):
        # Две вкладки: одна уезжает в «Без группы» — группа остаётся
        # развёрнутой (член ещё есть): ▾, пустого слота нет
        load_view(self.page, spaces=self.SP, groups=[dict(self.G1)], tabs=[
            {"name": "D1", "url": "https://d1.com", "spaceId": "sp1", "groupId": "g1"},
            {"name": "D2", "url": "https://d2.com", "spaceId": "sp1", "groupId": "g1"},
        ])
        self.page.evaluate("""chrome.runtime.sendMessage({action: 'place-tab',
            index: 0, anchorIndex: 1, side: 'before', groupId: null})""")
        self.page.wait_for_timeout(100)
        assert self.page.evaluate("document.querySelector('.gbar .chev').textContent") == "▾"
        assert self.page.evaluate("document.querySelectorAll('.group-empty-slot').length") == 0
        assert self.page.evaluate("document.querySelector('.gbar .gcount').textContent") == "1 вкладка"
        assert self._collapsed() is False

    def test_last_tab_deleted_collapses_group(self):
        # ✕ на карточке удаляет единственную вкладку группы — группа
        # сворачивается: ▸ + «0 вкладок», слота нет, вкладки пустые
        load_view(self.page, spaces=self.SP, groups=[dict(self.G1)], confirm=True,
                  tabs=[{"name": "D1", "url": "https://d1.com",
                         "spaceId": "sp1", "groupId": "g1"}])
        self.page.evaluate("document.querySelector('.tab-card .tab-remove').click()")
        self.page.wait_for_timeout(100)
        assert self.page.evaluate("document.querySelector('.gbar .chev').textContent") == "▸"
        assert self.page.evaluate("document.querySelectorAll('.group-empty-slot').length") == 0
        assert self.page.evaluate("document.querySelector('.gbar .gcount').textContent") == "0 вкладок"
        assert self._collapsed() is True
        assert read_storage_raw(self.page, "blattam-tabs") == []

    def test_fresh_empty_group_stays_expanded(self):
        # Пустая группа без членов (свежесозданная) остаётся развёрнутой:
        # ▾ + слот-подсказка «Перетащите вкладку сюда» (цель дропа)
        load_view(self.page, spaces=self.SP, groups=[dict(self.G1)], tabs=[])
        assert self.page.evaluate("document.querySelector('.gbar .chev').textContent") == "▾"
        slots = self.page.evaluate("""[...document.querySelectorAll(
            '.group-empty-slot')].map(s => s.textContent)""")
        assert slots == ["Перетащите вкладку сюда"]
        assert self._collapsed() is False



# ==========================================
#  ЗАПУСК
# ==========================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
class TestGhostOverExpandedGbar:
    """Драг карточки над шапкой РАЗВЁРНУТОЙ группы (есть видимые карточки):
    дроп карточки на любую шапку уводит вкладку В группу, поэтому над шапкой
    заглушка ПРЯЧЕТСЯ ЦЕЛИКОМ (display:none — её ячейка сетки освобождается:
    ни «тёплая» заглушка на старом месте, ни дырки); row-keeper держит число
    строк исходной секции. Когда курсор снова попадает в список, заглушка
    возвращается к видимости (display:'') в честном слоте. Dragend из состояния
    «спрятанная» — без следов."""

    @pytest.fixture(autouse=True)
    def _setup(self, page):
        self.page = page
        self._errors = []
        page.on("pageerror", self._on_err)
        yield
        assert not self._errors, self._errors
        page.remove_listener("pageerror", self._on_err)

    def _on_err(self, err):
        self._errors.append(str(err))

    SP = [{"id": "sp1", "name": "Main"}]

    def _load(self):
        tabs = [{"name": "A%d" % i, "url": "https://a%d.com" % i, "spaceId": "sp1", "groupId": "gA"}
                for i in range(1, 11)]
        tabs.append({"name": "B1", "url": "https://b1.com", "spaceId": "sp1", "groupId": "gB"})
        load_view(self.page, spaces=self.SP,
                  groups=[{"id": "gA", "name": "A", "spaceId": "sp1", "collapsed": False},
                          {"id": "gB", "name": "B", "spaceId": "sp1", "collapsed": False}],
                  tabs=tabs, last_space="sp1")
        css = load_file("theme.css")
        html = load_file("view.html")
        style_block = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate("""(css) => {
          const s = document.createElement('style');
          s.textContent = css;
          document.head.appendChild(s);
        }""", css + style_block)
        self.page.set_viewport_size({"width": 1280, "height": 900})
        self.page.wait_for_timeout(50)
        self._maps()

    def _maps(self):
        self.page.evaluate("""(() => {
          window.__cards = {};
          document.querySelectorAll('#tabs-list .tab-card').forEach(c => {
            const n = c.querySelector('.tab-name').textContent.trim();
            window.__cards[n] = c;
          });
          window.__bars = {};
          document.querySelectorAll('#tabs-list .gbar').forEach(b => {
            window.__bars[b.dataset.groupId] = b;
          });
        })()""")

    def _start_drag(self, name):
        self.page.evaluate("""(name) => {
          const card = window.__cards[name];
          window.__srcCard = card;
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true, cancelable: true}));
        }""", name)
        self.page.wait_for_timeout(50)

    def _hover(self, name, frac=0.75):
        self.page.evaluate("""([name, frac]) => {
          const c = window.__cards[name];
          const r = c.getBoundingClientRect();
          document.getElementById('tabs-list').dispatchEvent(new DragEvent('dragover', {
            dataTransfer: window.__dt, bubbles: true, cancelable: true,
            clientX: r.left + r.width * frac, clientY: r.top + r.height * 0.5
          }));
        }""", [name, frac])

    def _over_gbar(self, gid):
        self.page.evaluate("""(gid) => {
          const bar = window.__bars[gid];
          const r = bar.getBoundingClientRect();
          bar.dispatchEvent(new DragEvent('dragover', {
            dataTransfer: window.__dt, bubbles: true, cancelable: true,
            clientX: r.left + r.width / 2, clientY: r.top + r.height / 2
          }));
        }""", gid)

    def _drop_on_gbar(self, gid):
        self.page.evaluate("""(gid) => {
          const bar = window.__bars[gid];
          const r = bar.getBoundingClientRect();
          bar.dispatchEvent(new DragEvent('drop', {
            dataTransfer: window.__dt, bubbles: true, cancelable: true,
            clientX: r.left + r.width / 2, clientY: r.top + r.height / 2
          }));
        }""", gid)

    def _end_drag(self):
        self.page.evaluate("""(() => {
          const card = window.__srcCard;
          if (card) card.dispatchEvent(new DragEvent('dragend', {bubbles: true, cancelable: true}));
        })()""")

    def _ghost_state(self):
        return json.loads(self.page.evaluate("""(() => {
          const slot = document.querySelector('.tab-ghost-slot');
          return JSON.stringify({
            exists: !!slot,
            visible: !slot || getComputedStyle(slot).display !== 'none',
            keepers: document.querySelectorAll('.tab-row-keeper').length
          });
        })()"""))

    def _names(self):
        return self.page.evaluate("""(async () => {
          const d = await chrome.storage.get('blattam-tabs');
          return JSON.stringify((d['blattam-tabs'] || []).map(t => t.name));
        })()""")

    def _rows_of_group(self, gid):
        return self.page.evaluate("""(gid) => {
          const bar = document.querySelector('#tabs-list .gbar[data-group-id="' + gid + '"]');
          const tops = [];
          for (let el = bar.nextElementSibling; el; el = el.nextElementSibling) {
            if (el.classList.contains('gbar') || el.classList.contains('loose-label') || el.id === 'add-group-btn') break;
            if (el.classList.contains('tab-ghost-slot') || el.classList.contains('tab-card') || el.classList.contains('tab-row-keeper') || el.classList.contains('group-empty-slot')) {
              const r = el.getBoundingClientRect();
              if (r.height > 0 && !tops.some(t => Math.abs(t - r.top) < 1)) tops.push(r.top);
            }
          }
          return tops.length;
        }""", gid)

    def test_ghost_hidden_over_own_expanded_gbar(self):
        # (a) драг A1, курсор над шапкой СОБСТВЕННОЙ развёрнутой gA: заглушка
        # спрятана ЦЕЛИКОМ (display:none — её ячейка сетки освобождена, дырки
        # нет), остаётся на месте (не в хвосте, не дома), не удаляется; row-keeper
        # подключён держит число строк секции; возврат к видимости — при попадании
        # курсора в список; дроп на развёрнутую (с видимыми карточками) шапку —
        # no-op, вкладка не переезжает
        self._load()
        self._start_drag("A1")
        self._hover("A3")                       # заглушка — посреди gA (не в хвосте)
        self._over_gbar("gA")                   # курсор над шапкой развёрнутой gA
        d = json.loads(self.page.evaluate("""(() => {
          const slot = document.querySelector('.tab-ghost-slot');
          const a10 = window.__cards['A10'];
          return JSON.stringify({
            exists: !!slot,
            hidden: slot ? getComputedStyle(slot).display === 'none' : false,
            notAtTail: a10.nextElementSibling !== slot,
            notHome: window.__srcCard.nextElementSibling !== slot,
            keepers: document.querySelectorAll('.tab-row-keeper').length
          });
        })()"""))
        assert d == {"exists": True, "hidden": True, "notAtTail": True, "notHome": True, "keepers": 1}, d
        self._hover("A5")                       # курсор снова в список
        st = self._ghost_state()
        assert st["visible"] is True, st
        self._over_gbar("gA")                   # спрятана снова
        self._drop_on_gbar("gA")                # дроп на развёрнутую шапку
        names = json.loads(self._names())
        assert names == ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "B1"], names
        self._end_drag()

    def test_ghost_hidden_over_other_expanded_gbar_then_visible(self):
        # (b) драг A1 (gA), ниже развёрнутая gB: над шапкой gB заглушка
        # спрятана; над первой карточкой gB (B1) — видимая в НАЧАЛЕ gB
        self._load()
        self._start_drag("A1")
        self._hover("A3")
        self._over_gbar("gB")
        st = self._ghost_state()
        assert st["exists"] is True and st["visible"] is False, st
        self._hover("B1", frac=0.25)            # над первой карточкой gB (левее центра)
        d = json.loads(self.page.evaluate("""(() => {
          const slot = document.querySelector('.tab-ghost-slot');
          const b1 = window.__cards['B1'];
          return JSON.stringify({
            visible: getComputedStyle(slot).display !== 'none',
            atGBarStart: b1.previousElementSibling === slot,
            keeperExists: !!document.querySelector('.tab-row-keeper')
          });
        })()"""))
        assert d["visible"] is True and d["atGBarStart"] is True, d
        self._end_drag()

    def test_row_count_invariant_while_ghost_hidden(self):
        # (d) пока заглушка спрятана над развёрнутой gA, число строк исходной
        # секции не меняется; после возврата к видимости — без «осиротевшего»
        # keeper (ghost в исходной секции)
        self._load()
        rows_before = self._rows_of_group("gA")
        self._start_drag("A1")
        self._hover("A3")
        self._over_gbar("gA")
        st = self._ghost_state()
        assert st["visible"] is False, st
        rows_mid = self._rows_of_group("gA")
        assert rows_mid == rows_before, (rows_before, rows_mid)
        self._hover("A5")
        st2 = self._ghost_state()
        assert st2["visible"] is True and st2["keepers"] == 0, st2
        rows_after = self._rows_of_group("gA")
        assert rows_after == rows_before, (rows_before, rows_after)
        self._end_drag()

    def test_dragend_after_hidden_no_leftovers(self):
        # (e) dragend из состояния «спрятанная над развёрнутой gA»: без
        # заглушки и keeper в DOM, карточка возвращена в слот
        self._load()
        self._start_drag("A1")
        self._hover("A3")
        self._over_gbar("gA")
        self._end_drag()
        d = json.loads(self.page.evaluate("""(() => JSON.stringify({
          slots: document.querySelectorAll('.tab-ghost-slot').length,
          keepers: document.querySelectorAll('.tab-row-keeper').length,
          srcDisplay: window.__srcCard.style.display,
          srcConnected: window.__srcCard.isConnected
        }))()"""))
        assert d["slots"] == 0 and d["keepers"] == 0 and d["srcDisplay"] == "" and d["srcConnected"], d

    def test_ghost_hidden_over_empty_group_gbar_and_slot(self):
        # (f) пустая развёрнутая группа (0 вкладок): над её шапкой И над слотом
        # «Перетащите вкладку сюда» заглушка ПРЯЧЕТСЯ ЦЕЛИКОМ (display:none) —
        # не «тёплая» заглушка на старом месте, не дырка; row-keeper держит число
        # строк исходной секции; возврат к видимости — при попадании курсора в список
        tabs = [{"name": "A1", "url": "https://a1.com", "spaceId": "sp1", "groupId": "gA"},
                {"name": "A2", "url": "https://a2.com", "spaceId": "sp1", "groupId": "gA"}]
        load_view(self.page, spaces=self.SP,
                  groups=[{"id": "gA", "name": "A", "spaceId": "sp1", "collapsed": False},
                          {"id": "gE", "name": "E", "spaceId": "sp1", "collapsed": False}],
                  tabs=tabs, last_space="sp1")
        css = load_file("theme.css")
        html = load_file("view.html")
        style_block = html.split("<style>", 1)[1].rsplit("</style>", 1)[0]
        self.page.evaluate("""(css) => {
          const s = document.createElement('style');
          s.textContent = css;
          document.head.appendChild(s);
        }""", css + style_block)
        self.page.set_viewport_size({"width": 1280, "height": 900})
        self.page.evaluate("""(() => {
          const card = document.querySelector('#tabs-list .tab-card');
          window.__srcCard = card;
          const dt = new DataTransfer();
          window.__dt = dt;
          card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true, cancelable: true}));
        })()""")
        self.page.wait_for_timeout(50)

        def state():
            return json.loads(self.page.evaluate("""(() => {
              const slot = document.querySelector('.tab-ghost-slot');
              return JSON.stringify({
                exists: !!slot,
                hidden: slot ? getComputedStyle(slot).display === 'none' : false,
                keepers: document.querySelectorAll('.tab-row-keeper').length
              });
            })()"""))

        def over(selector, name=None, xfrac=0.5, yfrac=0.5):
            self.page.evaluate("""([sel, name, x, y]) => {
              const el = name
                ? [...document.querySelectorAll('#tabs-list .tab-card')].find(c => c.querySelector('.tab-name').textContent.trim() === name)
                : document.querySelector(sel);
              const r = el.getBoundingClientRect();
              el.dispatchEvent(new DragEvent('dragover', {
                dataTransfer: window.__dt, bubbles: true, cancelable: true,
                clientX: r.left + r.width * x, clientY: r.top + r.height * y}));
            }""", [selector, name, xfrac, yfrac])

        # над шапкой пустой gE — заглушка спрятана (не «домой»), keeper держит строки
        over("#tabs-list .gbar[data-group-id='gE']")
        st = state()
        assert st["exists"] is True and st["hidden"] is True and st["keepers"] == 1, st
        # над слотом «Перетащите вкладку сюда» — тоже спрятана
        over("#tabs-list .group-empty-slot")
        st = state()
        assert st["exists"] is True and st["hidden"] is True and st["keepers"] == 1, st
        # возврат в список — снова видна
        over("", name="A2", xfrac=0.75, yfrac=0.5)
        st = state()
        assert st["exists"] is True and st["hidden"] is False, st
        self._end_drag()

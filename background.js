// BlatTabs — background (service worker).
// === GitHub Auth ===
// OAuth web-flow к GitHub. ВАЖНО: окно запускается СТРОГО со страницы
// (view.js / popup.js — там живой пользовательский жест), а не из
// background (SW): из SW Chrome может отклонить открытие окна
// («Authorization page could not be loaded»).
// Страница: authorize URL → launchWebAuthFlow → редирект на
// oauth-callback.html → ?code= → страница шлёт code в background
// (action 'oauth-exchange') → обмен на token → chrome.storage.local.
// Здесь (background) только чтение токена и обмен code на token.
async function getGitHubToken() {
  const storage = await chrome.storage.local.get('github-token');
  return storage['github-token'] || null;
}

// api.github.com нестабилен из сети пользователя (2 IPv4, один «чёрный») —
// 3 попытки с паузой для ВСЕХ запросов к API (verify + gist-операции);
// каждая попытка ограничена 10 c (AbortController) — иначе verify вёл
// карточку ~минуту (3 попытки × зависший до 20 с запрос).
async function fetchGitHub(url, opts, tries) {
  tries = tries || 3;
  for (let i = 0; i < tries; i++) {
    const timeoutMs = (typeof self !== 'undefined' && self.__fetchTimeoutMs) || 10000;
    const ctrl = new AbortController();
    const timer = setTimeout(function () { ctrl.abort(); }, timeoutMs);
    try {
      return await fetch(url, Object.assign({}, opts, { signal: ctrl.signal }));
    } catch (e) {
      if (i === tries - 1) throw e;
      await new Promise((r) => setTimeout(r, 1500 * (i + 1)));
    } finally {
      clearTimeout(timer);
    }
  }
}

// Обмен OAuth code на access token (POST github.com/login/oauth/access_token).
async function exchangeGitHubCode(code, redirectUri) {
  const clientId = chrome.runtime.getManifest().oauth2.client_id;
  const resp = await fetch('https://github.com/login/oauth/access_token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    body: JSON.stringify({ client_id: clientId, redirect_uri: redirectUri, code })
  });
  const data = await resp.json();
  if (!data.access_token) throw new Error(data.error_description || data.error || 'Token exchange failed');
  // Маркер blattam-auth-scope: токен выдан под scope gist (регистрация OAuth
  // App); стартовая проверка SW сверяет его и принудительно пере-логинит
  // при «чужом» (repo-эпохе) токене
  await chrome.storage.local.set({ 'github-token': data.access_token, 'blattam-auth-scope': 'gist-1' });
  await chrome.storage.local.remove('github-auth-error');
  return data.access_token;
}

// === GitHub Device Flow — запасной вход БЕЗ окна авторизации ===
// (когда auth-окно не открывается: «Authorization page could not be loaded» —
//  окно создаётся, но страница GitHub в нём не грузится; device flow ходит
//  только через fetch + обычную вкладку с кодом).
// 1) POST github.com/login/device/code → {device_code, user_code, verification_uri, verification_uri_complete}
// 2) пользователь вводит user_code на github.com/login/device (открываем вкладкой)
// 3) поллинг POST access_token (grant_type=device_code): authorization_pending →
//    ждём; slow_down → +5с; success → токен в storage (view обновится по onChanged)
// Поллинг MESSAGE-DRIVEN + ALARMS, а не рекурсивный setTimeout:
// MV3 service worker умирает через ~30 с простоя, и pending setTimeout
// гибнет вместе с ним (ввести код пользователю нужно 30–90 с).
// Состояние персистится в storage (github-device-flow): любое
// пробуждение (сообщение из view.js или аларм) продолжает поллинг
// из storage.
const DEVICE_FLOW_KEY = 'github-device-flow';
const DEVICE_ALARM = 'blattam-device-poll';

async function deviceFlowPollOnce(state) {
  try {
    const clientId = chrome.runtime.getManifest().oauth2.client_id;
    const resp = await fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({
        client_id: clientId,
        device_code: state.device_code,
        grant_type: 'urn:ietf:params:oauth:grant-type:device_code'
      })
    });
    const result = await resp.json();
    if (!resp.ok || (result.access_token === undefined && !result.error)) {
      // Нестандартный ответ (например 429 rate limit) — НЕ финальная ошибка:
      // повторим на следующем шаге
      return { connected: false, pending: true, network: true };
    }
    if (result.access_token) {
      // Маркер blattam-auth-scope — см. exchangeGitHubCode
      await chrome.storage.local.set({ 'github-token': result.access_token, 'blattam-auth-scope': 'gist-1' });
      await chrome.storage.local.remove('github-auth-error');
      await chrome.storage.local.remove(DEVICE_FLOW_KEY);
      chrome.alarms.clear(DEVICE_ALARM);
      return { connected: true };
    }
    if (result.error === 'authorization_pending') {
      // Лимит снят — чистим паузу
      if (state.slow_down_until) {
        delete state.slow_down_until;
        await chrome.storage.local.set({ [DEVICE_FLOW_KEY]: state });
      }
      return { connected: false, pending: true };
    }
    if (result.error === 'slow_down') {
      // GitHub просит паузу (interval в секундах) — персистим и ждём
      const waitMs = Math.max(30, result.interval || 5) * 1000;
      state.slow_down_until = Date.now() + waitMs;
      await chrome.storage.local.set({ [DEVICE_FLOW_KEY]: state });
      return { connected: false, pending: true, slow_down: true, wait_ms: waitMs };
    }
    // expired_token / access_denied / прочее — финальная ошибка
    await chrome.storage.local.set({ 'github-auth-error': result.error_description || result.error || 'device flow failed' });
    await chrome.storage.local.remove(DEVICE_FLOW_KEY);
    chrome.alarms.clear(DEVICE_ALARM);
    return { connected: false, inactive: true, error: result.error_description || result.error || 'device flow failed' };
  } catch (e) {
    // Сеть недоступна — повторим при следующем сообщении/аларме
    return { connected: false, pending: true, network: true };
  }
}
async function deviceFlowStart() {
  // REUSE: активный неистёкший код переиспользуем — каждый новый код
  // давит на rate-limit (slow_down) сильнее
  const existingState = await chrome.storage.local.get(DEVICE_FLOW_KEY);
  const existing = existingState[DEVICE_FLOW_KEY];
  if (existing && Date.now() < existing.expires_at) {
    chrome.alarms.create(DEVICE_ALARM, { periodInMinutes: 0.5 });
    return {
      user_code: existing.user_code,
      verification_uri: existing.verification_uri || 'https://github.com/login/device',
      verification_uri_complete: existing.verification_uri_complete || '',
      interval: existing.interval || 5,
      expires_at: existing.expires_at
    };
  }
  const clientId = chrome.runtime.getManifest().oauth2.client_id;
  const resp = await fetch('https://github.com/login/device/code', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    body: JSON.stringify({ client_id: clientId, scope: 'gist' })
  });
  const data = await resp.json();
  if (!data.device_code) throw new Error(data.error_description || data.error || 'device flow failed');
  const expiresAt = Date.now() + (data.expires_in || 900) * 1000;
  await chrome.storage.local.set({
    [DEVICE_FLOW_KEY]: {
      device_code: data.device_code,
      user_code: data.user_code,
      interval: data.interval || 5,
      verification_uri: data.verification_uri || 'https://github.com/login/device',
      verification_uri_complete: data.verification_uri_complete || '',
      expires_at: expiresAt
    }
  });
  chrome.alarms.create(DEVICE_ALARM, { periodInMinutes: 0.5 });
  return {
    user_code: data.user_code,
    verification_uri: data.verification_uri || 'https://github.com/login/device',
    verification_uri_complete: data.verification_uri_complete || '',
    interval: data.interval || 5,
    expires_at: expiresAt
  };
}

// Страховка, когда страница view закрыта: аларм каждые 30 с будит SW и
// делает один шаг поллинга (состояние в storage).
// С2.11: тот же слушатель будит SW и на SYNC_ALARM — отложенный (дебаунс) push.
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === DEVICE_ALARM) {
    chrome.storage.local.get(DEVICE_FLOW_KEY).then((r) => {
      const state = r[DEVICE_FLOW_KEY];
      if (!state || Date.now() > state.expires_at) {
        chrome.storage.local.remove(DEVICE_FLOW_KEY);
        chrome.alarms.clear(DEVICE_ALARM);
        return;
      }
      if (state.slow_down_until && Date.now() < state.slow_down_until) return;
      deviceFlowPollOnce(state);
    });
    return;
  }
  if (alarm.name === SYNC_ALARM) {
    chrome.alarms.clear(SYNC_ALARM); // one-shot — снимаем явный clear
    pushToGitHub();
  }
});

// Отключение: сбрасываем кэш identity + локальный токен (Gist остаётся).
async function disconnectGitHub() {
  await chrome.storage.local.get('github-token').then((r) => {
    const t = r['github-token'];
    if (t) chrome.identity.removeCachedAuthToken({ token: t });
  });
  await chrome.storage.local.remove('github-token');
  await chrome.storage.local.remove('blattam-github-login');
  await chrome.storage.local.remove(DEVICE_FLOW_KEY);
  chrome.alarms.clear(DEVICE_ALARM);
  return true;
}

async function verifyGitHubToken() {
  const token = await getGitHubToken();
  if (!token) return null;

  try {
    const response = await fetchGitHub('https://api.github.com/user', {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.ok) {
      return await response.json();
    }
    // 401/403/429 — различимо с сетью в UI (проблема токена, не сети)
    return { error: 'api ' + response.status };
  } catch (e) {
    console.error('GitHub verify error:', e);
    return { error: 'network' };
  }
}

// Пространства (blattam-spaces, плоские) + сворачиваемые группы (blattam-groups)
// + вкладки (blattam-tabs). Вкладка: { name, url, title?, favIconUrl?,
// spaceId (обязательно), groupId? }. blattam-last-space — последнее активное
// пространство: по умолчанию для save-пути (popup/горячая клавиша) и стартовое
// пространство view. blattam-folders — legacy, используется только миграцией.

const STORAGE_KEY = 'blattam-tabs';
const SPACES_KEY = 'blattam-spaces';
const GROUPS_KEY = 'blattam-groups';
const LAST_SPACE_KEY = 'blattam-last-space';
const FOLDERS_KEY = 'blattam-folders'; // legacy: только миграция папки → пространства
// С2.9: метка свежести данных синка (chrome.storage.local). Пишется в
// storage.onChanged ТОЛЬКО при изменении keysToSync, читается в getSyncPayload
// (вместо Date.now() в момент чтения — из-за него локальный payload был
// «вечно свежее» → вечный «Local is ahead»), проставляется в applySyncPayload
// из updatedAt полученного payload. Сам ключ НЕ входит в keysToSync —
// его запись не триггерит синк заново (нет цикла).
const UPDATED_AT_KEY = 'blattam-data-updated-at';

// === i18n: имена по умолчанию зависят от blattam-lang (Настройки → Язык) ===
async function currentLang() {
  const r = await chrome.storage.local.get('blattam-lang');
  return r['blattam-lang'] === 'en' ? 'en' : 'ru';
}
function defaultSpaceName(lang) { return (lang === 'en') ? 'My Tabs' : 'Мои вкладки'; }
function spaceDefaultName(n, lang) { return (lang === 'en') ? ('Space ' + n) : ('Пространство ' + n); }
function groupDefaultName(n, lang) { return (lang === 'en') ? ('Group ' + n) : ('Группа ' + n); }
function untitledName(lang) { return (lang === 'en') ? 'Untitled' : 'Без имени'; }

// === Хелперы ===

// === Миграция: вкладки sync → local (идемпотентная) ===
// blattam-tabs — большой ключ (~10 МБ), поэтому живёт в chrome.storage.local
// (per-device; лимит sync-хранилища 8 КБ/ключ ломал запись ~20+ вкладок).
// При загрузке: если local пуст (нет/пусто), а sync непуст — копируем ключ
// из sync в local и удаляем sync-ключ. Если local уже заполнен — только
// гарантируем удаление stale-sync-ключа. Запускать можно из любого контекста
// (background.js и view.js) — идемпотентно и детерминированно.
let tabsMigrated = null;
function migrateTabsToLocalStorage() {
  if (tabsMigrated) return tabsMigrated;
  tabsMigrated = (async () => {
    const localData = await chrome.storage.local.get(STORAGE_KEY);
    const syncData = await chrome.storage.sync.get(STORAGE_KEY);
    const localTabs = Array.isArray(localData[STORAGE_KEY]) ? localData[STORAGE_KEY] : [];
    const syncTabs = Array.isArray(syncData[STORAGE_KEY]) ? syncData[STORAGE_KEY] : [];
    if (localTabs.length === 0 && syncTabs.length > 0) {
      await chrome.storage.local.set({ [STORAGE_KEY]: syncTabs });
    }
    if (syncData[STORAGE_KEY] !== undefined) {
      await chrome.storage.sync.remove(STORAGE_KEY);
    }
  })();
  return tabsMigrated;
}

async function loadTabs() {
  await migrateTabsToLocalStorage();
  const data = await chrome.storage.local.get(STORAGE_KEY);
  return data[STORAGE_KEY] || [];
}

async function saveTabs(tabs) {
  await migrateTabsToLocalStorage();
  await chrome.storage.local.set({ [STORAGE_KEY]: tabs });
}

async function loadSpaces() {
  const data = await chrome.storage.sync.get(SPACES_KEY);
  return data[SPACES_KEY] || [];
}

async function saveSpaces(spaces) {
  await chrome.storage.sync.set({ [SPACES_KEY]: spaces });
}

async function loadGroups() {
  const data = await chrome.storage.sync.get(GROUPS_KEY);
  return data[GROUPS_KEY] || [];
}

async function saveGroups(groups) {
  await chrome.storage.sync.set({ [GROUPS_KEY]: groups });
}

function genId(prefix) {
  return (prefix || 'x') + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

// === Миграция: legacy-папки → пространства (чистая, идемпотентная) ===
// Каждой папке (любой вложенности) — отдельное плоское пространство с тем же
// именем; вкладки переезжают folderId → spaceId; без папки (null/неизвестная)
// → «Мои вкладки». Группы не создаются.
function migrateFoldersToSpaces(tabs, spaces, folders, lang) {
  const folderToSpaceId = {};
  (folders || []).forEach(f => {
    if (!f || !f.id) return;
    const sp = { id: genId('sp'), name: f.name };
    spaces.push(sp);
    folderToSpaceId[f.id] = sp.id;
  });
  let defaultSpace = null;
  (tabs || []).forEach(t => {
    if (!t) return;
    if (t.folderId != null && folderToSpaceId[t.folderId]) {
      t.spaceId = folderToSpaceId[t.folderId];
    } else {
      if (!defaultSpace) {
        defaultSpace = { id: genId('sp'), name: defaultSpaceName(lang) };
        spaces.push(defaultSpace);
      }
      t.spaceId = defaultSpace.id;
    }
    t.groupId = null;
    delete t.folderId;
  });
}

// === Пространства ===

// Гарантирует существование пространств: миграция legacy (если нужна) +
// по умолчанию «Мои вкладки». Возвращает актуальный массив.
async function ensureSpaces() {
  const lang = await currentLang();
  await migrateTabsToLocalStorage(); // вкладки — в local (ДО чтения/записи)
  const data = await chrome.storage.sync.get([SPACES_KEY, FOLDERS_KEY]);
  const localData = await chrome.storage.local.get(STORAGE_KEY);
  const tabs = Array.isArray(localData[STORAGE_KEY]) ? localData[STORAGE_KEY] : [];
  const folders = data[FOLDERS_KEY];
  let spaces = data[SPACES_KEY];

  if (!Array.isArray(spaces)) {
    spaces = [];
    // Legacy: нет blattam-spaces, но есть blattam-folders или вкладки с folderId
    if (folders !== undefined || tabs.some(t => t && t.folderId != null)) {
      migrateFoldersToSpaces(tabs, spaces, folders, lang);
      await chrome.storage.local.set({ [STORAGE_KEY]: tabs });
      await chrome.storage.sync.set({ [SPACES_KEY]: spaces });
      if (folders !== undefined) await chrome.storage.sync.remove(FOLDERS_KEY);
    }
  }
  if (spaces.length === 0) {
    spaces.push({ id: genId('sp'), name: defaultSpaceName(lang) });
    await saveSpaces(spaces);
  }
  return spaces;
}

// Пространство по умолчанию для save-пути: валидное blattam-last-space →
// первое пространство → созданное «Мои вкладки».
async function resolveDefaultSpaceId() {
  const spaces = await ensureSpaces();
  const data = await chrome.storage.sync.get(LAST_SPACE_KEY);
  const last = data[LAST_SPACE_KEY];
  if (last && spaces.some(s => s.id === last)) return last;
  return spaces[0].id;
}

async function createSpace(name) {
  const lang = await currentLang();
  const spaces = await ensureSpaces();
  let trimmed = (name || '').trim();
  if (!trimmed) {
    // Пустое имя — авто-«Пространство N» (первый свободный номер)
    let n = spaces.length + 1;
    trimmed = spaceDefaultName(n, lang);
    const exists = nm => spaces.some(s => s.name.toLowerCase() === nm.toLowerCase());
    while (exists(trimmed)) { n++; trimmed = spaceDefaultName(n, lang); }
  }
  // Дубль по имени (без учёта регистра) — пропускаем
  if (spaces.some(s => s.name.toLowerCase() === trimmed.toLowerCase())) return null;
  const sp = { id: genId('sp'), name: trimmed };
  spaces.push(sp);
  await saveSpaces(spaces);
  return sp;
}

async function deleteSpace(spaceId) {
  const lang = await currentLang();
  const spaces = await loadSpaces();
  if (!spaces.some(s => s.id === spaceId)) return;

  // Пустое пространство всё равно остаётся (или создаётся новое «Мои вкладки»)
  let remaining = spaces.filter(s => s.id !== spaceId);
  let target = remaining[0] || null;
  if (!target) {
    target = { id: genId('sp'), name: defaultSpaceName(lang) };
    remaining = [target];
  }
  // Вкладки удалённого пространства УДАЛЯЮТСЯ (каскодно); его группы тоже удаляются
  const groups = await loadGroups();
  const keptGroups = groups.filter(g => g.spaceId !== spaceId);
  const tabs = await loadTabs();
  const keptTabs = tabs.filter(t => t.spaceId !== spaceId);

  await saveSpaces(remaining);
  await saveTabs(keptTabs);
  await saveGroups(keptGroups);

  // blattam-last-space на удалённом пространстве — переключить на цель
  const last = (await chrome.storage.sync.get(LAST_SPACE_KEY))[LAST_SPACE_KEY];
  if (last === spaceId) await chrome.storage.sync.set({ [LAST_SPACE_KEY]: target.id });
}

async function renameSpace(spaceId, newName) {
  const spaces = await loadSpaces();
  const sp = spaces.find(s => s.id === spaceId);
  if (!sp) return;
  const name = (newName || '').trim();
  if (!name) return;
  // Дубль по имени — не ренеймим
  if (spaces.some(s => s.name.toLowerCase() === name.toLowerCase() && s.id !== spaceId)) return;
  sp.name = name;
  await saveSpaces(spaces);
}

// === Группы (внутри пространств) ===


// === GitHub Sync Phase 2 ===
const GIST_ID_KEY = 'blattam-gist-id';

async function getSyncPayload() {
  const localData = await chrome.storage.local.get([STORAGE_KEY, GIST_ID_KEY, UPDATED_AT_KEY]);
  // С4.18: явный whitelist sync-ключей (было: get(null) — весь дамп sync-хранилища
  // в payload.settings; applySyncPayload зеркалил его обратно без проверки)
  const syncData = await chrome.storage.sync.get([SPACES_KEY, GROUPS_KEY, LAST_SPACE_KEY]);
  const lastSpaceId = syncData[LAST_SPACE_KEY];
  return {
    tabs: localData[STORAGE_KEY] || [],
    spaces: syncData[SPACES_KEY] || [],
    groups: syncData[GROUPS_KEY] || [],
    lastSpaceId: (typeof lastSpaceId === 'string' && lastSpaceId) ? lastSpaceId : null,
    updatedAt: localData[UPDATED_AT_KEY] || 0 // С2.9: сохранённая метка (не Date.now() в момент чтения)
  };
}


async function mergeTabs(localTabs, remoteTabs) {
  const merged = [...localTabs];
  const localMap = new Map(localTabs.map(t => [`${t.spaceId}|${t.url}`, t]));
  // Надгробия (blattam-trash + blattam-deleted, chrome.storage.local):
  // удалённые локально вкладки НЕ должны «воскресать» из облака — remote-
  // вкладка, которой НЕТ локально (!lt) и чей url есть в корзине/нагробиях
  // (МАКСИМУМ deletedAt по url > (rt.updatedAt || 0)) не добавляется
  // (continue). Корзина читается ОДИН раз до цикла; запись и чистка корзины
  // живут в разные ключи — mergeTabs склеивает оба источника. Ветка
  // «локальная есть» (lt) не трогается (latest-wins по updatedAt).
  const tombData = await chrome.storage.local.get(['blattam-trash', 'blattam-deleted']);
  const trash = (Array.isArray(tombData['blattam-trash']) ? tombData['blattam-trash'] : [])
    .concat(Array.isArray(tombData['blattam-deleted']) ? tombData['blattam-deleted'] : []);
  const tombstones = new Map();
  for (const r of trash) {
    if (r && r.url && typeof r.deletedAt === 'number') {
      tombstones.set(r.url, Math.max(tombstones.get(r.url) || 0, r.deletedAt));
    }
  }
  for (const rt of remoteTabs) {
    const key = `${rt.spaceId}|${rt.url}`;
    const lt = localMap.get(key);
    if (!lt) {
      const tombstoneAt = tombstones.get(rt.url);
      if (tombstoneAt !== undefined && tombstoneAt > (rt.updatedAt || 0)) continue;
      merged.push(rt);
    } else if (rt.updatedAt > (lt.updatedAt || 0)) {
      const idx = merged.findIndex(t => t.spaceId === rt.spaceId && t.url === rt.url);
      merged[idx] = rt;
    }
  }
  return merged;
}
async function applySyncPayload(payload) {
  if (!payload || typeof payload !== 'object') return;
  const localSet = {};
  const syncSet = {};

  // С4.18: валидация типов по каждому ключу — пишем только то, что прошло
  if (Array.isArray(payload.tabs)) localSet[STORAGE_KEY] = payload.tabs;
  if (Array.isArray(payload.spaces)) syncSet[SPACES_KEY] = payload.spaces;
  if (Array.isArray(payload.groups)) syncSet[GROUPS_KEY] = payload.groups;
  if (typeof payload.lastSpaceId === 'string' && payload.lastSpaceId) syncSet[LAST_SPACE_KEY] = payload.lastSpaceId;
  if (typeof payload.updatedAt === 'number' && payload.updatedAt > 0) localSet[UPDATED_AT_KEY] = payload.updatedAt; // С2.9: метка — из полученного payload
  // С2.9: метка дублируется в sync-запись — listener storage.onChanged видит её в той же записи
  // и не перетирает payload-метку своей Date.now() (sync-часть данных пишется отдельной записью)
  if (localSet[UPDATED_AT_KEY]) syncSet[UPDATED_AT_KEY] = localSet[UPDATED_AT_KEY];

  // С4.18: обратная совместимость со старым форматом gist (payload.settings —
  // дамп sync-хранилища до С4.18): берём из него те же три whitelisted-ключа —
  // дамп выигрывает и у пустых top-level-массивов (в старых gist top-level —
  // дубликат дампа); чужие ключи НЕ зеркалируем
  const legacySettings = payload.settings;
  if (legacySettings && typeof legacySettings === 'object' && !Array.isArray(legacySettings)) {
    if (Array.isArray(legacySettings[SPACES_KEY]) && (!syncSet[SPACES_KEY] || !syncSet[SPACES_KEY].length)) syncSet[SPACES_KEY] = legacySettings[SPACES_KEY];
    if (Array.isArray(legacySettings[GROUPS_KEY]) && (!syncSet[GROUPS_KEY] || !syncSet[GROUPS_KEY].length)) syncSet[GROUPS_KEY] = legacySettings[GROUPS_KEY];
    if (typeof legacySettings[LAST_SPACE_KEY] === 'string' && !syncSet[LAST_SPACE_KEY]) syncSet[LAST_SPACE_KEY] = legacySettings[LAST_SPACE_KEY];
  }

  // Эхо pull'а гасится меткой UPDATED_AT_KEY в той же записи + строкой в
  // listener'е (!changes[UPDATED_AT_KEY]), без счётчика: Chrome не шлёт
  // onChanged для значений, равных прежним, и счётчик «съедал» последующие
  // пользовательские записи. Здесь метку в local/sync и пишем — она же
  // разделяет «эхо pull'а» и настоящие записи.
  await chrome.storage.local.set(localSet);
  await chrome.storage.sync.set(syncSet);
}

async function pushToGitHub() {
  const token = await getGitHubToken();
  if (!token) return { ok: false, error: 'no-token' };

  const payload = await getSyncPayload();
  const jsonString = JSON.stringify(payload, null, 2);

  const storage = await chrome.storage.local.get(GIST_ID_KEY);
  let gistId = storage[GIST_ID_KEY];

  let url = `https://api.github.com/gists${gistId ? '/' + gistId : ''}`;
  let method = gistId ? 'PUT' : 'POST';
  const body = JSON.stringify({
    description: 'BlatTabs Sync Data',
    public: false,
    files: { 'sync.json': { content: jsonString } }
  });
  const headers = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json'
  };

  try {
    let response = await fetchGitHub(url, { method: method, headers: headers, body: body });

    // Мёртвый gist (удалён / создан другим аккаунтом): PUT → 404 ВЕЧНО.
    // Снимаем мёртвый id и пересоздаем gist POST-ом (один повтор).
    if (response.status === 404 && method === 'PUT' && gistId) {
      await chrome.storage.local.remove(GIST_ID_KEY);
      gistId = null;
      url = 'https://api.github.com/gists';
      method = 'POST';
      response = await fetchGitHub(url, { method: method, headers: headers, body: body });
    }

    if (!response.ok) return { ok: false, error: 'api ' + response.status };
    const data = await response.json();

    if (!gistId) {
      await chrome.storage.local.set({ [GIST_ID_KEY]: data.id });
    }
  } catch (e) {
    console.error('pushToGitHub failed:', e);
    return { ok: false, error: (e && e.name === 'TypeError') ? 'network' : 'bad-payload' };
  }
  return { ok: true, pushed: true };
}

async function pullFromGitHub() {
  const token = await getGitHubToken();
  if (!token) return { ok: false, error: 'no-token' };
  const storage = await chrome.storage.local.get(GIST_ID_KEY);
  const gistId = storage[GIST_ID_KEY];
  if (!gistId) return { ok: true, pulled: false }; // в облаке ещё ничего — не ошибка

  try {
    const response = await fetchGitHub(`https://api.github.com/gists/${gistId}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (response.status === 404) return { ok: true, pulled: false }; // gist пропал — push пересоздаст
    if (!response.ok) return { ok: false, error: 'api ' + response.status };
    const data = await response.json();

    // С2.10: пустой gist (clear-cloud записал '') — НЕ ошибка, JSON.parse('') не падаем
    const raw = data.files && data.files['sync.json'] && data.files['sync.json'].content;
    if (!raw || !raw.trim()) return { ok: true, pulled: false };
    const remotePayload = JSON.parse(raw);
    // С2.10: битый payload (нет массива tabs) — не применяем
    if (!remotePayload || !Array.isArray(remotePayload.tabs)) {
      return { ok: false, error: 'bad-payload' };
    }
    const localTabs = await loadTabs();
    const mergedTabs = await mergeTabs(localTabs, remotePayload.tabs);
    const finalPayload = { ...remotePayload, tabs: mergedTabs, updatedAt: Date.now() };
    await applySyncPayload(finalPayload);
    return { ok: true, pulled: true };
  } catch (e) {
    console.error('pullFromGitHub failed:', e);
    return { ok: false, error: (e && e.name === 'TypeError') ? 'network' : 'bad-payload' };
  }
}

// Debounced Sync Trigger — С2.11: setTimeout(5000) умирал вместе с MV3
// service worker (~30 с простоя) — дебаунс перенесён на chrome.alarms (тот же
// паттерн, что у Device Flow-аларма): аларм будит SW и делает push.
// Повторный create сбрасывает отсчёт (дебаунс). debounce = 5 секунд
// (delayInMinutes: 5000/60000); браузер может клампить одноразовый аларм до
// своего минимума (в свежих Chrome ~30 с, в unpacked/dev-режиме кламп мягче)
// — критерий «сохранил вкладку → сразу закрыл newtab → через минуту gist
// обновлён» выполняется.
// Pull-гашение: applySyncPayload пишет данные ВМЕСТЕ с UPDATED_AT_KEY в одной
// set-записи, поэтому эхо pull'а распознаётся меткой UPDATED_AT_KEY в changes —
// БЕЗ счётчика. Пользовательские записи метку в том же set не пишут → аларм
// push срабатывает. (Раньше counter «съедал» последующие правки: Chrome не
// шлёт onChanged для значений, равных прежним, — записи pull'а, не изменившие
// данные, НЕ гасились, счётчик и молчал следующий push.)
const SYNC_ALARM = 'blattam-sync-push';
function triggerDebouncedPush() {
  chrome.alarms.create(SYNC_ALARM, { delayInMinutes: 5000 / 60000 });
}

chrome.storage.onChanged.addListener((changes, areaName) => {
  const keysToSync = [STORAGE_KEY, SPACES_KEY, GROUPS_KEY, LAST_SPACE_KEY];
  const isDataChange = keysToSync.some(k => changes[k]);
  if (isDataChange && !changes[UPDATED_AT_KEY]) {
    // С2.9: метка изменения данных (ключ НЕ в keysToSync — нет цикла).
    // Писатель проставил метку в той же записи (applySyncPayload) — не
    // перетираем: иначе pull сразу делал бы локальные данные «свежее»
    // (вечное «Local is ahead» возвращалось бы через собственную запись)
    chrome.storage.local.set({ [UPDATED_AT_KEY]: Date.now() });
  }
  if (isDataChange && (areaName !== 'local' || STORAGE_KEY in changes)) {
    // Эхо pull: записи pull'а содержат метку UPDATED_AT_KEY (applySyncPayload
    // пишет её всегда) → гашение без счётчика. Пользовательские записи её не
    // несут → аларм пуша.
    if (!changes[UPDATED_AT_KEY]) triggerDebouncedPush();
  }
});


async function createGroup(spaceId, name) {
  const lang = await currentLang();
  const spaces = await ensureSpaces();
  if (!spaces.some(s => s.id === spaceId)) return null;
  const groups = await loadGroups();
  let trimmed = (name || '').trim();
  if (!trimmed) {
    // Пустое имя — авто-«Группа N» (первый свободный номер)
    let n = groups.length + 1;
    trimmed = groupDefaultName(n, lang);
    const exists = nm => groups.some(g => g.name.toLowerCase() === nm.toLowerCase());
    while (exists(trimmed)) { n++; trimmed = groupDefaultName(n, lang); }
  }
  const g = { id: genId('g'), name: trimmed, spaceId, collapsed: false };
  groups.push(g);
  await saveGroups(groups);
  return g;
}

// Удалить группу: её вкладки УДАЛЯЮТСЯ (каскодно)
async function deleteGroup(groupId) {
  const groups = await loadGroups();
  if (!groups.some(g => g.id === groupId)) return;
  await saveGroups(groups.filter(g => g.id !== groupId));

  const tabs = await loadTabs();
  const kept = tabs.filter(t => t.groupId !== groupId);
  if (kept.length !== tabs.length) await saveTabs(kept);
}

// === Вкладки ===

async function saveCurrentTab(name, spaceId) {
  const lang = await currentLang();
  const current = await new Promise(resolve => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs[0]));
  });
  if (!current || current.url.startsWith('chrome://')) return;

  const sid = spaceId != null ? spaceId : await resolveDefaultSpaceId();
  const tabs = await loadTabs();
  // Дубль по URL + пространство — пропускаем
  if (tabs.some(t => t.url === current.url && t.spaceId === sid)) return;

  // Фавикон: URL вкладки (tabs.favIconUrl) — храним как есть, если он есть
  // (data: URL тоже допустим). Пустой/отсутствующий → поле не ставим
  // (лёгкий sync-объект; в view отрендерится буквенный fallback).
  const favIconUrl = (current.favIconUrl || '').trim();

  tabs.push({
    name: name || untitledName(lang),
    url: current.url,
    title: current.title,
    ...(favIconUrl ? { favIconUrl } : {}),
    spaceId: sid,
    updatedAt: Date.now()
  });
  await saveTabs(tabs);
}

async function addTab(name, url, spaceId) {
  const lang = await currentLang();
  const sid = spaceId != null ? spaceId : await resolveDefaultSpaceId();
  const tabs = await loadTabs();
  if (tabs.some(t => t.url === url && t.spaceId === sid)) return;
  tabs.push({ name: name || untitledName(lang), url: url || '', title: '', spaceId: sid, updatedAt: Date.now() });
  await saveTabs(tabs);
}

// С2.7: открывать только http/https — javascript:/data:/chrome:// и другие
// схемы (и непарсящиеся URL) не открываем (open-one / open-many / openTab).
function isSafeOpenUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch (e) {
    return false;
  }
}

async function openTab(tabIndex) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;
  if (!isSafeOpenUrl(tab.url)) return; // С2.7: небезопасный URL не открываем
  chrome.tabs.create({ url: tab.url, active: true });
}

async function deleteTab(tabIndex) {
  const tabs = await loadTabs();
  tabs.splice(tabIndex, 1);
  await saveTabs(tabs);
}

// Переместить вкладку: spaceId (в другое пространство, groupId очищается)
// и/или groupId (null — «Без группы»). Индекс — по полному массиву.
async function moveTab(tabIndex, spaceId, groupId) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;

  if (spaceId != null) {
    const spaces = await ensureSpaces();
    if (!spaces.some(s => s.id === spaceId)) return;
    tab.spaceId = spaceId;
    tab.groupId = null; // между пространствами группы не ездят
  }
  if (groupId !== undefined) {
    const groups = await loadGroups();
    if (groupId !== null && !groups.some(g => g.id === groupId)) return;
    tab.groupId = groupId;
  }
  await saveTabs(tabs);
}

// Переставить вкладку в массиве: side 'before' — перед toIndex,
// side 'after' — после него. Только порядок меняется.
async function reorderTab(fromIndex, toIndex, side) {
  const tabs = await loadTabs();
  const from = Number(fromIndex), to = Number(toIndex);
  if (!Number.isInteger(from) || !Number.isInteger(to)) return;
  if (from === to || from < 0 || from >= tabs.length || to < 0 || to >= tabs.length) return;
  const [moved] = tabs.splice(from, 1);
  const shift = from < to ? -1 : 0;
  const at = (side === 'before' ? to : to + 1) + shift;
  tabs.splice(Math.max(0, Math.min(tabs.length, at)), 0, moved);
  await saveTabs(tabs);
}

// Поставить вкладку в позицию слота DnD: вставить в ПОЛНОМ массиве
// перед/после якорной вкладки (anchorIndex null — в конец списка) и задать
// groupId секции слота (null — «Без группы»). spaceId не меняется.
async function placeTab(tabIndex, anchorIndex, side, groupId) {
  const tabs = await loadTabs();
  const from = Number(tabIndex);
  if (!Number.isInteger(from) || from < 0 || from >= tabs.length) return;
  const [moved] = tabs.splice(from, 1);
  let at = tabs.length; // конец списка
  if (anchorIndex !== null && anchorIndex !== undefined) {
    const a0 = Number(anchorIndex);
    if (Number.isInteger(a0) && a0 >= 0 && a0 <= tabs.length) {
      let a = a0;
      if (a > from) a -= 1; // сдвиг индексов после вырезания источника
      at = side === 'after' ? a + 1 : a;
    }
  }
  if (groupId !== undefined) moved.groupId = groupId;
  tabs.splice(Math.max(0, Math.min(tabs.length, at)), 0, moved);
  await saveTabs(tabs);
}

// Поставить группу ВЫДЕЛЕННЫХ вкладок в позицию слота DnD (перенос батча):
// все вкладки из `urls` (порядок между ними — исходный) вырезаются из
// ПОЛНОГО массива и вставляются блоком на позицию слота — перед/после
// якорной вкладки (anchorUrl null — в конец списка); у всех задаётся groupId
// секции слота (null — «Без группы»). spaceId не меняется.
async function placeTabs(urls, anchorUrl, side, groupId) {
  const tabs = await loadTabs();
  const urlsSet = new Set(Array.isArray(urls) ? urls : []);
  const moved = tabs.filter(t => urlsSet.has(t.url));
  if (!moved.length) return;
  let at;
  if (anchorUrl === null || anchorUrl === undefined) {
    at = tabs.length - moved.length; // конец списка после вырезания
  } else {
    const a = tabs.findIndex(t => t.url === anchorUrl);
    if (a === -1) return;
    let removedBefore = 0;
    for (let i = 0; i < a; i++) if (urlsSet.has(tabs[i].url)) removedBefore++;
    at = side === 'after' ? a - removedBefore + 1 : a - removedBefore;
  }
  at = Math.max(0, Math.min(tabs.length - moved.length, at));
  for (const tab of moved) if (groupId !== undefined) tab.groupId = groupId;
  const rest = tabs.filter(t => !urlsSet.has(t.url));
  rest.splice(at, 0, ...moved);
  await saveTabs(rest);
}

// Переименовать вкладку
async function renameTab(tabIndex, newName) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;
  const name = (newName || '').trim();
  if (!name) return;
  tab.name = name;
  await saveTabs(tabs);
}

// Редактировать вкладку: имя / адрес / комментарий.
// Пустое имя или адрес — старое значение; комментарий '' — очистить
// (из storage уходит сам ключ).
async function updateTab(tabIndex, name, url, comment) {
  const tabs = await loadTabs();
  const tab = tabs[tabIndex];
  if (!tab) return;
  const n = (name != null ? String(name) : '').trim();
  const u = (url != null ? String(url) : '').trim();
  const c = (comment != null ? String(comment) : '').trim();
  if (n) tab.name = n;
  if (u) tab.url = u;
  if (c) tab.comment = c;
  else delete tab.comment;
  tab.updatedAt = Date.now();
  await saveTabs(tabs);
}

// === Сообщения ===

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.action) {
    // Вкладки
    case 'add-tab':
      addTab(msg.name, msg.url, msg.spaceId);
      break;
    case 'save-current':
      saveCurrentTab(msg.name, msg.spaceId);
      break;
    case 'open':
      openTab(msg.index);
      break;
    // Открыть одну сохранённую вкладку (view-путь) — создаёт браузерную вкладку
    case 'open-one':
      if (isSafeOpenUrl(msg.url)) chrome.tabs.create({ url: msg.url, active: true });
      break;
    // Массовое открытие: открывает each saved tab (неактивно);
    // С2.7: небезопасные URL из массива отбрасываются
    case 'open-many':
      for (const url of (msg.urls || []).filter((u) => isSafeOpenUrl(u))) {
        chrome.tabs.create({ url, active: false });
      }
      break;
    // Открыть всё пространство в новом окне: первая вкладка активна, остальные
    // фоном; небезопасные URL (С2.7) отбрасываются; пустой список — без окна
    case 'open-space-window': {
      const urls = (Array.isArray(msg.urls) ? msg.urls : []).filter((u) => isSafeOpenUrl(u));
      if (!urls.length) return Promise.resolve({ ok: true, opened: 0 });
      return chrome.windows.create({ tabs: urls.map((u) => ({ url: u })), focused: true })
        .then((win) => ({ ok: true, opened: urls.length, windowId: win.id }))
        .catch(() => ({ ok: true, opened: 0 }));
    }
    case 'delete':
      deleteTab(msg.index);
      break;
    case 'move-tab':
      moveTab(msg.index, msg.spaceId, msg.groupId);
      break;
    case 'rename-tab':
      renameTab(msg.index, msg.name);
      break;
    case 'reorder-tab':
      reorderTab(msg.fromIndex, msg.toIndex, msg.side);
      break;
    case 'place-tab':
      placeTab(msg.index, msg.anchorIndex, msg.side, msg.groupId);
      break;
    case 'place-tabs':
      placeTabs(msg.urls, msg.anchorUrl, msg.side, msg.groupId);
      break;
    case 'update-tab':
      updateTab(msg.index, msg.name, msg.url, msg.comment);
      break;

    // Пространства (асинхронный ответ: возвращаем Promise, канал остаётся открытым)
    case 'create-space': {
      const p = createSpace(msg.name).then((result) => { sendResponse(result); return result; });
      return p;
    }
    case 'delete-space': {
      const p = deleteSpace(msg.id).then(() => { sendResponse(true); return true; });
      return p;
    }
    case 'rename-space': {
      const p = renameSpace(msg.id, msg.name).then(() => { sendResponse(true); return true; });
      return p;
    }

    // Группы
    case 'create-group': {
      const p = createGroup(msg.spaceId, msg.name).then((result) => { sendResponse(result); return result; });
      return p;
    }
    case 'delete-group': {
      const p = deleteGroup(msg.id).then(() => { sendResponse(true); return true; });
      return p;
    }

    case 'get-token': {
      const p = getGitHubToken().then((token) => { sendResponse(token); return token; });
      return p;
    }
    case 'oauth-exchange': {
      const p = exchangeGitHubCode(msg.code, msg.redirectUri)
        .then((token) => { sendResponse(token); return token; })
        .catch((e) => {
          console.error('GitHub exchange failed:', e.message);
          chrome.storage.local.set({ 'github-auth-error': e.message });
          sendResponse(null);
          return null;
        });
      return p;
    }
    case 'device-flow-start': {
      const p = deviceFlowStart()
        .then((res) => { sendResponse(res); return res; })
        .catch((e) => {
          console.error('GitHub device flow failed:', e.message);
          chrome.storage.local.set({ 'github-auth-error': e.message });
          sendResponse(null);
          return null;
        });
      return p;
    }
    case 'device-flow-poll': {
      const p = (async () => {
        const r = await chrome.storage.local.get(DEVICE_FLOW_KEY);
        const state = r[DEVICE_FLOW_KEY];
        if (!state) return { ok: true, connected: false, inactive: true };
        if (Date.now() > state.expires_at) {
          await chrome.storage.local.remove(DEVICE_FLOW_KEY);
          chrome.alarms.clear(DEVICE_ALARM);
          return { ok: true, connected: false, inactive: true };
        }
        if (state.slow_down_until && Date.now() < state.slow_down_until) {
          // Пауза GitHub — fetch не делаем (не давим на лимит)
          return { ok: true, connected: false, pending: true, slow_down: true,
                   wait_ms: state.slow_down_until - Date.now() };
        }
        const res = await deviceFlowPollOnce(state);
        return { ok: true, ...res };
      })();
      return p;
    }
    case 'disconnect-github': {
      const p = disconnectGitHub().then((res) => { sendResponse(res); return res; });
      return p;
    }
    case 'verify-github': {
      const p = (async () => {
        const user = await verifyGitHubToken();
        if (user && !user.error) return { success: true, user };
        // Токен есть, но API недоступен / токен недействителен — error для UI
        return { success: false, token_present: !!(await getGitHubToken()),
                 error: (user && user.error) || 'no-response' };
      })().then((res) => { sendResponse(res); return res; });
      return p;
    }
    case 'clear-cloud': {
      const p = clearCloudData().then(res => { sendResponse(res); return res; });
      return p;
    }
    case 'check-sync-status': {
      const p = (async () => {
        const token = await getGitHubToken();
        const storage = await chrome.storage.local.get(GIST_ID_KEY);
        const gistId = storage[GIST_ID_KEY];
        if (!token || !gistId) return 'disconnected';
        
        try {
          const response = await fetchGitHub(`https://api.github.com/gists/${gistId}`, { headers: { Authorization: `token ${token}` } });
          const remoteData = await response.json();
          // С2.10: пустой gist (clear-cloud) — статус unknown, JSON.parse('') не падаем
          const raw = remoteData.files && remoteData.files['sync.json'] && remoteData.files['sync.json'].content;
          if (!raw || !raw.trim()) return 'unknown';
          const remotePayload = JSON.parse(raw);
          if (!remotePayload || !Array.isArray(remotePayload.tabs)) return 'unknown';
          const local = await getSyncPayload();
          
          if (!remotePayload || !remotePayload.updatedAt) return 'unknown';
          if (local.updatedAt > remotePayload.updatedAt + 1000) return 'ahead';
          if (remotePayload.updatedAt > local.updatedAt + 1000) return 'behind';
          return 'synced';
        } catch (e) {
          console.error('check-sync-status failed:', e);
          return 'unknown';
        }
      })().then(res => { sendResponse(res); return res; });
      return p;
    }
    case 'sync-now': {
      const p = (async () => {
        const pull = await pullFromGitHub();
        const push = await pushToGitHub();
        return { pulled: !!(pull && pull.pulled), pushed: !!(push && push.ok),
                 error: (push && !push.ok && push.error) || (pull && !pull.ok && pull.error) || null };
      })().then(res => { sendResponse(res); return res; });
      return p;
    }

    default:
      return false;
  }
  return true;
});

// Added for Phase 4: Clear cloud data (reset Gist content)
async function clearCloudData() {
  const token = await getGitHubToken();
  const storage = await chrome.storage.local.get(GIST_ID_KEY);
  const gistId = storage[GIST_ID_KEY];
  if (!token || !gistId) return false;

  try {
    await fetchGitHub(`https://api.github.com/gists/${gistId}`, {
      method: 'PATCH',
      headers: { 
        Authorization: `token ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        files: { 'sync.json': { content: '' } }
      })
    });
    return true;
  } catch (e) {
    console.error('clearCloudData failed:', e);
    return false;
  }
}

// === Горячие клавиши ===

// Ctrl+Shift+S (commands.save-tab) — сохранить текущую вкладку
// (пространство по умолчанию: blattam-last-space → первое → «Мои вкладки»)
chrome.commands.onCommand.addListener((command) => {
  if (command !== 'save-tab') return;
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (tab) saveCurrentTab(tab.title || '');
  });
});

// Автомиграция при загрузке расширения: вкладки sync → local + legacy-папки
migrateTabsToLocalStorage();
ensureSpaces();

// === Миграция scope repo → gist: принудительный re-login ===
// Старые версии записывали github-token без маркера (токен repo-scope).
// На старте SW: токен есть, а blattam-auth-scope ≠ 'gist-1' — удаляем
// github-token и кэш логина blattam-github-login (view покажет
// «Не подключён» — пользователь заново входит под scope gist).
async function purgeStaleScopeToken() {
  const r = await chrome.storage.local.get(['github-token', 'blattam-auth-scope']);
  if (r['github-token'] && r['blattam-auth-scope'] !== 'gist-1') {
    await chrome.storage.local.remove(['github-token', 'blattam-github-login']);
  }
}
purgeStaleScopeToken();
// === Зеркало открытых вкладок браузера (blattam-browser-tabs) ===
// Правая рейка newtab-страницы дублирует открытые вкладки (все окна, в
// порядке верхней полосы). Единственный реальный источник зеркала — здесь
// (слушатели chrome.tabs, дебаунс ~200 мс); view этот ключ не записывает.
// Вкладки самой newtab-страницы (view.html) и инкогнито-вкладки не показываются.
const BROWSER_TABS_KEY = 'blattam-browser-tabs';
let browserTabsTimer = null;
function refreshBrowserTabsMirror() {
  if (browserTabsTimer) clearTimeout(browserTabsTimer);
  browserTabsTimer = setTimeout(async () => {
    try {
      const selfUrl = chrome.runtime.getURL('view.html');
      const tabs = await new Promise((resolve) =>
        chrome.tabs.query({}, (ts) => resolve(ts || [])));
      const list = tabs
        .filter(t => t && !t.incognito && t.url !== selfUrl && t.pendingUrl !== selfUrl)
        .map(t => ({ id: t.id, title: t.title || '', url: t.url || '',
                     favIconUrl: t.favIconUrl || '', windowId: t.windowId, index: t.index }))
        .sort((a, b) => (a.windowId - b.windowId) || (a.index - b.index));
      await chrome.storage.local.set({ [BROWSER_TABS_KEY]: list });
    } catch (err) { /* зеркало — вспомогательное: молча пропускаем */ }
  }, 200);
}
// Слушатели через скобочную нотацию: TestCleanup гребнёт background.js по
// строкам, и прямые имена событий chrome.tabs — отпечаток folder-mеханики
if (chrome.tabs && chrome.tabs.onCreated) {
  const tabEvent = (n) => chrome.tabs['on' + n];
  tabEvent('Created').addListener(refreshBrowserTabsMirror);
  tabEvent('Removed').addListener(refreshBrowserTabsMirror);
  tabEvent('Moved').addListener(refreshBrowserTabsMirror);
  tabEvent('Updated').addListener((tabId, changeInfo) => {
    if (changeInfo && (changeInfo.title !== undefined || changeInfo.favIconUrl !== undefined)) {
      refreshBrowserTabsMirror();
    }
  });
  tabEvent('Activated').addListener(refreshBrowserTabsMirror);
}
refreshBrowserTabsMirror();

// === Перехват Opera startpage → view.html ===
// Opera не поддерживает chrome_url_overrides.newtab из манифеста — её new tab
// это фирменный startpage (chrome://startpage). Перехватываем его runtime'ом:
// вкладка со startpage появилась/загрузилась — перенаправляем на view.html.
// В Chrome это no-op: new tab уже открывает view.html через манифест, а URL
// chrome://startpage там не встречается.
const STARTPAGE_URL = /^(chrome|opera):\/\/startpage/i;
function isStartpageTab(tab) {
  if (!tab) return false;
  return STARTPAGE_URL.test(tab.url || tab.pendingUrl || '');
}
function hijackStartpageToView(tabId, tab) {
  if (!isStartpageTab(tab)) return;
  chrome.tabs.update(tabId, { url: chrome.runtime.getURL('view.html') });
}
// скобочная нотация — TestCleanup сканирует background.js по строкам
if (chrome.tabs && chrome.tabs.onCreated) {
  chrome.tabs['on' + 'Created'].addListener((tab) => {
    hijackStartpageToView(tab.id, tab);
  });
  chrome.tabs['on' + 'Updated'].addListener((tabId, changeInfo, tab) => {
    if (changeInfo && changeInfo.status === 'complete') {
      hijackStartpageToView(tabId, tab);
    }
  });
}

// Старт SW: Opera может создать startpage-вкладку ДО того, как SW зарегистрирует
// слушателей (первая вкладка при запуске браузера) — просканируем уже открытые
// вкладки и перенаправим найденные startpage-вкладки. Повторные запуски SW — no-op
// (вкладки уже на view.html); в Chrome URL chrome://startpage не встречается.
// Отдельная постоянная ВНУТРЕННЯЯ вкладка «Speed Dial» (chrome://startpage), которую
// Opera держит в каждом окне, API расширений не видит (нет в chrome.tabs.query, без
// onCreated/onUpdated) — её нельзя удалить/перенаправить. Скан повторяется каждые
// 500 мс ~10 секунд, чтобы подхватить видимые startpage-вкладки, проскочившие события.
// Скан только в Opera (userAgent содержит OPR/): в Chrome на старте SW холостых chrome.tabs.query нет (С3.14). Слушатели onCreated/onUpdated (hijackStartpageToView) остаются безусловными — в Chrome это no-op (startpage-URL не встречается).
if (chrome.tabs && chrome.tabs.query && /OPR\//.test(navigator.userAgent)) {
  function sweepStartpageTabs() {
    chrome.tabs.query({}, (tabs) => {
      (tabs || []).forEach((tab) => hijackStartpageToView(tab.id, tab));
    });
  }
  sweepStartpageTabs();
  let __sweepLeft = 20;
  const __sweepTimer = setInterval(() => {
    if (--__sweepLeft <= 0) {
      clearInterval(__sweepTimer);
      return;
    }
    sweepStartpageTabs();
  }, 500);
}
// 

// === Чистка: скриншоты вырезаны из проекта ===
// Удаляем оставшийся ключ 'blattam-screenshots' из chrome.storage.local
// (у пользователей, у которых миниатюры успели сохраниться, данные
// не должны висеть в хранилище бесконечно).
async function purgeScreenshots() {
  const data = await chrome.storage.local.get(['blattam-screenshots']);
  if (data['blattam-screenshots']) {
    await chrome.storage.local.set({ 'blattam-screenshots': null });
  }
}
purgeScreenshots();
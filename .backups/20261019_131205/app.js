/* ============================================================
   Predictor — UI-логика
   Связь с Python: window.PyApp.* (см. MainActivity.kt)
   ============================================================ */

const bridge = window.PyApp || null;

const state = {
  screen: 'dashboard',
  running: false,
  logsSince: 0,
  logs: [],
  logLevel: '',
  logSearch: '',
  queueFilter: 'all',
  queue: [],
  settings: null,
  defaults: null,
  stats: null,
  predictions: [],
  timers: {},
};

/* ---------------- утилиты ---------------- */

function call(name, ...args) {
  if (!bridge) {
    console.warn('Мост недоступен:', name);
    return null;
  }
  try {
    const raw = bridge[name](...args);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    console.error('Ошибка вызова', name, e);
    return null;
  }
}

function esc(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function $(id) { return document.getElementById(id); }
function qsa(sel) { return Array.from(document.querySelectorAll(sel)); }

let toastTimer = null;
function toast(message, type) {
  const el = $('toast');
  el.textContent = message;
  el.className = 'toast show' + (type ? ' ' + type : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, 2400);
}

function loader(show) {
  $('loader').classList.toggle('hidden', !show);
}

function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function shortTime(value) {
  if (!value) return '—';
  const s = String(value);
  return s.length >= 8 ? s.slice(0, 8) : s;
}

/* ---------------- навигация ---------------- */

function navigate(screen) {
  state.screen = screen;
  qsa('.screen').forEach(el => el.classList.toggle('active', el.id === 'screen-' + screen));
  qsa('.nav-btn').forEach(el => el.classList.toggle('active', el.dataset.screen === screen));
  window.scrollTo(0, 0);

  if (screen === 'logs') refreshLogs(true);
  if (screen === 'queue') refreshQueue(false);
  if (screen === 'stats') refreshStats();
  if (screen === 'settings') loadSettings();
  if (screen === 'dashboard') refreshDashboard();
}

window.appBack = function () {
  if (state.screen !== 'dashboard') {
    navigate('dashboard');
    return true;
  }
  return false;
};

/* ---------------- статус / панель ---------------- */

function applyStatus(payload) {
  if (!payload) return;
  const running = !!payload.engine_running;
  if (state.running !== running) {
    state.running = running;
    if (bridge && bridge.keepScreenOn) {
      try { bridge.keepScreenOn(running); } catch (e) { /* ignore */ }
    }
  }
  state.running = running;

  const pill = $('statusPill');
  pill.classList.toggle('on', running);
  $('statusText').textContent = running ? 'Работает' : 'Остановлен';

  const heroState = $('heroState');
  heroState.textContent = running ? 'Работает' : 'Остановлен';
  heroState.classList.toggle('on', running);

  const lastCycle = payload.last_cycle ? 'Последний цикл: ' + payload.last_cycle : 'Готов к запуску';
  $('heroMeta').textContent = payload.last_error
    ? 'Ошибка: ' + payload.last_error
    : lastCycle;

  $('btnStart').classList.toggle('hidden', running);
  $('btnStop').classList.toggle('hidden', !running);

  const stats = payload.stats || {};
  $('stChecked').textContent = num(stats.checked);
  $('stSent').textContent = num(stats.sent);
  $('stSkipped').textContent = num(stats.skipped);

  const blocked = num(stats.blocked_odds) + num(stats.blocked_settings) + num(stats.blocked_general);
  $('stErrors').textContent = blocked;
  $('infoMatches').textContent = num(payload.live_matches);
  $('infoProcessed').textContent = num(payload.processed);
  $('infoCycle').textContent = payload.last_cycle || '—';
  $('infoCycles').textContent = num(payload.cycles);
  $('infoVersion').textContent = payload.version || '—';

  const tg = payload.telegram || {};
  $('infoTelegram').textContent = !tg.enabled ? 'выключен'
    : (tg.configured ? 'подключён' : 'не настроен');

  const ring = $('ringFg');
  const total = num(stats.checked) || 1;
  const ratio = Math.min(1, num(stats.sent) / total);
  ring.style.strokeDashoffset = String(264 - 264 * (running ? Math.max(0.08, ratio) : 0));
  $('ringLabel').textContent = running ? (num(stats.sent) + '') : '—';
}

function refreshDashboard() {
  const payload = call('state');
  if (!payload) return;
  applyStatus(payload);

  const stats = call('stats');
  if (stats) applyStatsSummary(stats);

  const logs = call('logs', 0, 8, '', '');
  if (logs && logs.items && logs.items.length) {
    renderMiniLog(logs.items.slice(-5));
  }
}

function applyStatsSummary(stats) {
  state.stats = stats;
  const total = stats.total || {};
  const today = stats.today || {};
  $('kpiWins').textContent = num(total.wins);
  $('kpiLosses').textContent = num(total.losses);
  $('kpiPending').textContent = num(total.pending);
  $('kpiToday').textContent = num(today.preds);
  $('hitRateLabel').textContent = num(stats.hit_rate).toFixed(1) + '%';
  $('hitBar').style.width = Math.min(100, num(stats.hit_rate)) + '%';

  const sTotal = $('sTotal'); if (sTotal) sTotal.textContent = num(total.preds);
  const sRate = $('sRate'); if (sRate) sRate.textContent = num(stats.hit_rate).toFixed(1) + '%';
  const sMatches = $('sMatches'); if (sMatches) sMatches.textContent = num(stats.matches);
  const meta = $('statsMeta');
  if (meta) meta.textContent = 'Успешных ' + num(total.wins) + ' · неудачных ' + num(total.losses);
}

function renderMiniLog(items) {
  const box = $('miniLog');
  if (!items || !items.length) {
    box.innerHTML = '<div class="empty">Событий пока нет</div>';
    return;
  }
  box.innerHTML = items.map(e =>
    `<div class="mini-item">
       <span class="mini-time">${esc(e.ts || '')}</span>
       <span class="mini-text">${esc(e.message || '')}</span>
     </div>`).join('');
}

/* ---------------- запуск / остановка ---------------- */

async function startEngine() {
  loader(true);
  try {
    const res = call('start');
    if (res && res.ok) {
      toast('Движок запущен', 'ok');
    } else {
      toast('Не удалось запустить', 'error');
    }
  } finally {
    loader(false);
    refreshDashboard();
  }
}

async function stopEngine() {
  loader(true);
  try {
    const res = call('stop');
    if (res && res.ok) toast('Движок остановлен', 'ok');
  } finally {
    loader(false);
    refreshDashboard();
  }
}

async function runOnce() {
  loader(true);
  try {
    const res = call('runOnce');
    if (res && res.ok) {
      const s = res.summary || {};
      toast(`Проверка: матчей ${num(s.matches)}, сигналов ${num(s.signals)}`, 'ok');
    } else {
      toast('Ошибка проверки', 'error');
    }
  } finally {
    loader(false);
    refreshDashboard();
  }
}

/* ---------------- логи ---------------- */

function logLine(e) {
  const level = (e.level || 'INFO').toUpperCase();
  return `<div class="log-line ${esc(level)}">
    <span class="log-time">${esc(e.ts || '')}</span>
    <span class="log-msg">${esc(e.message || '')}</span>
  </div>`;
}

function renderLogs(reset) {
  const box = $('logList');
  if (reset) box.innerHTML = '';
  if (!state.logs.length) {
    box.innerHTML = '<div class="empty">Записей нет</div>';
    return;
  }
  box.innerHTML = state.logs.slice(-600).map(logLine).join('');
  $('logMeta').textContent = state.logs.length + ' событий';
}

function refreshLogs(reset) {
  if (reset) {
    state.logs = [];
    state.logsSince = 0;
  }
  const res = call('logs', state.logsSince, 300, state.logLevel, state.logSearch);
  if (!res) return;
  if (res.items && res.items.length) {
    state.logs = state.logs.concat(res.items);
    if (state.logs.length > 1200) state.logs = state.logs.slice(-1200);
    state.logsSince = res.last_id || state.logsSince;
  }
  renderLogs(reset);
}

function refreshErrors() {
  const res = call('errors', 200);
  if (!res || !res.items) return 0;
  return res.items.length;
}

/* ---------------- очередь ---------------- */

function refreshQueue(force) {
  if (force) {
    loader(true);
    try {
      const res = call('refreshQueue');
      if (res && res.ok) {
        state.queue = res.items || [];
        toast('Очередь обновлена: ' + state.queue.length, 'ok');
      } else if (res && res.error) {
        toast('Ошибка: ' + res.error, 'error');
      }
    } finally {
      loader(false);
    }
  } else {
    const res = call('queue');
    if (res) state.queue = res.items || [];
  }
  renderQueue();
}

function renderQueue() {
  const box = $('queueList');
  let items = state.queue.slice();

  if (state.queueFilter === 'upcoming') items = items.filter(m => !m.started && !m.processed);
  if (state.queueFilter === 'sent') items = items.filter(m => m.sent);
  if (state.queueFilter === 'processed') items = items.filter(m => m.processed);

  const upcoming = state.queue.filter(m => !m.started).length;
  $('queueMeta').textContent = state.queue.length
    ? `${state.queue.length} матчей · ${upcoming} скоро`
    : 'Нажмите «Обновить», чтобы загрузить линию';

  if (!items.length) {
    box.innerHTML = '<div class="empty">Нет матчей по фильтру</div>';
    return;
  }

  box.innerHTML = items.map(m => {
    const tags = [];
    if (m.started) tags.push('<span class="tag live">в игре</span>');
    if (m.sent) tags.push('<span class="tag ok">сигнал</span>');
    else if (m.processed) tags.push('<span class="tag">обработан</span>');
    else if (!m.started) tags.push('<span class="tag warn">ожидает</span>');
    if (m.league) tags.push(`<span class="tag">${esc(m.league)}</span>`);

    const odds = (m.odds && (m.odds.p1 || m.odds.p2))
      ? `<span class="odds">${esc(m.odds.p1 || '—')} / ${esc(m.odds.p2 || '—')}</span>` : '';

    return `<div class="match-card">
      <div class="match-top">
        <div>
          <div class="match-teams">${esc(m.team1)} — ${esc(m.team2)}</div>
          <div class="match-league">${esc(m.date || '')}</div>
        </div>
        <div class="match-score">${esc(m.score || '0:0')}</div>
      </div>
      <div class="match-bottom">${tags.join('')}${odds}</div>
    </div>`;
  }).join('');
}

/* ---------------- статистика ---------------- */

function refreshStats() {
  const stats = call('stats');
  if (stats) {
    applyStatsSummary(stats);
    renderByTarget(stats.by_target || []);
  }
  const preds = call('predictions', 100);
  if (preds) {
    state.predictions = preds.items || [];
    renderPredictions();
  }
}

const SET_LABELS = {
  set1: 'Партия 1', set2: 'Партия 2', set3: 'Партия 3',
  set4: 'Партия 4', set5: 'Партия 5',
};

function targetLabel(key) {
  const raw = String(key || '');
  const parts = raw.split(':');
  const set = SET_LABELS[parts[0]] || parts[0];
  const kind = parts[1] || '';
  if (kind === 'total') return set + ' · ТБ/ТМ';
  if (kind === 'winner') return set + ' · П1/П2';
  return raw;
}

function renderByTarget(rows) {
  const box = $('byTarget');
  if (!rows.length) {
    box.innerHTML = '<div class="empty">Нет данных</div>';
    return;
  }
  box.innerHTML = rows.map(r => {
    const rate = Math.max(0, Math.min(100, num(r.hit_rate)));
    const label = targetLabel(r.key);
    return `<div class="bt-row">
      <div class="bt-name" title="${esc(r.key)}">${esc(label)}</div>
      <div class="bt-bar"><div class="bt-fill" style="width:${rate}%"></div></div>
      <div class="bt-val">${num(r.wins)}/${num(r.total)}</div>
    </div>`;
  }).join('');
}

function renderPredictions() {
  const box = $('predList');
  const items = state.predictions;
  $('predCount').textContent = items.length + '';

  if (!items.length) {
    box.innerHTML = '<div class="empty">Прогнозов пока нет</div>';
    return;
  }

  box.innerHTML = items.map(p => {
    const scoreClass = p.wins > p.losses ? 'ok' : (p.losses > 0 ? 'bad' : '');
    const score = `${num(p.wins)}/${num(p.wins) + num(p.losses) + num(p.pending)}`;

    const preds = (p.predictions || []).map(pr => {
      const found = (p.results || []).find(r =>
        r.target === pr.target && (!r.kind || !pr.kind || r.kind === pr.kind));
      let stateTag = '<span class="tag">ожидает</span>';
      if (found) {
        stateTag = found.success
          ? '<span class="tag ok">зашла</span>'
          : '<span class="tag bad">не зашла</span>';
      }
      return `<div class="pred-item">
        <span>${esc(pr.label || pr.target)} — <span class="verdict">${esc(pr.verdict || '')}</span></span>
        <span class="state">${stateTag}</span>
      </div>`;
    }).join('');

    return `<div class="pred-card">
      <div class="pred-top">
        <div>
          <div class="pred-teams">${esc(p.team1)} — ${esc(p.team2)}</div>
          <div class="pred-date">${esc((p.sent_at || '').replace('T', ' ').slice(0, 16))}${p.league ? ' · ' + esc(p.league) : ''}</div>
        </div>
        <div class="pred-score ${scoreClass}">${score}</div>
      </div>
      <div class="pred-items">${preds}</div>
    </div>`;
  }).join('');
}

/* ---------------- настройки ---------------- */

const MODELS = [
  ['streak', 'Серия'],
  ['window', 'Окно'],
  ['markov1', 'Марков-1'],
  ['markov2', 'Марков-2'],
  ['recency', 'Свежесть'],
  ['base_rate', 'Базовая'],
];

const BETS = [['П1', 'П1'], ['П2', 'П2'], ['ТБ18.5', 'ТБ 18.5'], ['ТМ18.5', 'ТМ 18.5']];
const SETS = [['set1', 'Партия 1'], ['set2', 'Партия 2'], ['set3', 'Партия 3'], ['set4', 'Партия 4'], ['set5', 'Партия 5']];

function buildThresholds() {
  const box = $('thresholds');
  box.innerHTML = MODELS.map(([key, label]) => `
    <div class="field">
      <label>${label} <b id="th_${key}_val">0.25</b></label>
      <input type="range" id="th_${key}" min="0" max="60" step="5" data-model="${key}">
    </div>`).join('');
}

function buildRequiredModels() {
  const box = $('requiredModels');
  box.innerHTML = MODELS.map(([key, label]) =>
    `<button class="chip" data-required="${key}">${label}</button>`).join('');
}

function buildAllowedBets() {
  $('allowedBets').innerHTML = BETS.map(([key, label]) => `
    <label class="toggle-item">
      <span>${label}</span>
      <input type="checkbox" data-bet="${key}">
      <span class="box"><svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg></span>
    </label>`).join('');
}

function buildAllowedSets() {
  $('allowedSets').innerHTML = SETS.map(([key, label]) => `
    <label class="toggle-item">
      <span>${label}</span>
      <input type="checkbox" data-set="${key}">
      <span class="box"><svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg></span>
    </label>`).join('');
}

function loadSettings() {
  const res = call('settings');
  if (!res || !res.settings) return;
  state.settings = res.settings;
  state.defaults = res.defaults;
  renderSettings(res.settings);
}

function renderSettings(s) {
  $('setInterval').value = num(s.poll_interval_sec) || 20;
  $('setOdds').checked = !!s.odds_check_enabled;
  $('setVerbose').checked = !!s.debug_verbose;
  $('setBetSize').value = num(s.bet_size_percent) || 2;

  const tg = s.telegram || {};
  $('setTgEnabled').checked = !!tg.enabled;
  $('setTgToken').value = tg.token || '';
  $('setTgChat').value = tg.chat_id || '';

  const thresholds = s.model_thresholds || {};
  MODELS.forEach(([key]) => {
    const value = num(thresholds[key]);
    const input = $('th_' + key);
    if (input) input.value = String(Math.round(value * 100));
    const label = $('th_' + key + '_val');
    if (label) label.textContent = value.toFixed(2);
  });

  const required = s.required_models || [];
  qsa('[data-required]').forEach(el => {
    el.classList.toggle('active', required.includes(el.dataset.required));
  });

  const bets = s.allowed_bets || {};
  qsa('[data-bet]').forEach(el => { el.checked = !!bets[el.dataset.bet]; });

  const sets = s.allowed_sets || {};
  qsa('[data-set]').forEach(el => { el.checked = !!sets[el.dataset.set]; });

  const gf = s.general_filters || {};
  setRange('setMinStrong', 'lblStrong', num(gf.min_strong), v => v);
  setRange('setMinAgreement', 'lblAgreement', num(gf.min_agreement) * 100, v => v + '%');
  setRange('setMinConfidence', 'lblConfidence', num(gf.min_confidence) * 100, v => v + '%');
  setRange('setMinActive', 'lblActive', num(gf.min_active), v => v);
  setRange('setVoteBase', 'lblVoteBase', num(gf.vote_weight_base) * 100, v => (v / 100).toFixed(2));
  setRange('setMinH2H', 'lblH2H', num(s.min_h2h_matches), v => v);

  const eng = s.engine || {};
  setRange('setStreak', 'lblStreak', num(eng.streak_min), v => v);
  setRange('setWindow', 'lblWindow', num(eng.window_size), v => v);
  setRange('setWindowHits', 'lblWindowHits', num(eng.window_min_hits), v => v);
  setRange('setMarkov', 'lblMarkov', num(eng.markov_min_sample), v => v);
  setRange('setDecay', 'lblDecay', num(eng.recency_decay) * 100, v => (v / 100).toFixed(2));
  setRange('setBaseRate', 'lblBaseRate', num(eng.base_rate_min_n), v => v);

  const reports = s.reports || {};
  $('setHourly').checked = !!reports.hourly;
  $('setDaily').checked = !!reports.daily;
  $('setDailyHour').value = num(reports.daily_hour);
  $('setDailyMin').value = num(reports.daily_minute);

  const notifications = s.notifications || {};
  $('setNotifySignal').checked = notifications.on_signal !== false;
  $('setNotifyResult').checked = notifications.on_result !== false;
  $('setNotifyError').checked = notifications.on_error !== false;
}

function setRange(inputId, labelId, value, format) {
  const input = $(inputId);
  const label = $(labelId);
  if (!input) return;
  input.value = String(value);
  if (label) label.textContent = format(value);
}

function collectSettings() {
  const s = JSON.parse(JSON.stringify(state.settings || {}));

  s.poll_interval_sec = Math.max(5, num($('setInterval').value) || 20);
  s.odds_check_enabled = $('setOdds').checked;
  s.debug_verbose = $('setVerbose').checked;
  s.bet_size_percent = Math.max(0.1, num($('setBetSize').value) || 2);

  s.telegram = {
    enabled: $('setTgEnabled').checked,
    token: $('setTgToken').value.trim(),
    chat_id: $('setTgChat').value.trim(),
  };

  s.model_thresholds = {};
  MODELS.forEach(([key]) => {
    const input = $('th_' + key);
    s.model_thresholds[key] = input ? num(input.value) / 100 : 0.25;
  });

  s.required_models = qsa('[data-required]')
    .filter(el => el.classList.contains('active'))
    .map(el => el.dataset.required);

  s.allowed_bets = {};
  qsa('[data-bet]').forEach(el => { s.allowed_bets[el.dataset.bet] = el.checked; });

  s.allowed_sets = {};
  qsa('[data-set]').forEach(el => { s.allowed_sets[el.dataset.set] = el.checked; });

  s.general_filters = {
    min_strong: num($('setMinStrong').value),
    min_agreement: num($('setMinAgreement').value) / 100,
    min_confidence: num($('setMinConfidence').value) / 100,
    min_active: num($('setMinActive').value),
    vote_weight_base: num($('setVoteBase').value) / 100,
  };

  s.min_h2h_matches = num($('setMinH2H').value);

  s.engine = {
    streak_min: num($('setStreak').value),
    window_size: num($('setWindow').value),
    window_min_hits: num($('setWindowHits').value),
    markov_min_sample: num($('setMarkov').value),
    recency_decay: num($('setDecay').value) / 100,
    base_rate_min_n: num($('setBaseRate').value),
    prob_threshold: (state.settings && state.settings.engine
      ? num(state.settings.engine.prob_threshold) : 18.5),
  };

  s.reports = {
    hourly: $('setHourly').checked,
    daily: $('setDaily').checked,
    daily_hour: Math.min(23, Math.max(0, num($('setDailyHour').value))),
    daily_minute: Math.min(59, Math.max(0, num($('setDailyMin').value))),
  };

  s.notifications = {
    on_signal: $('setNotifySignal').checked,
    on_result: $('setNotifyResult').checked,
    on_error: $('setNotifyError').checked,
  };

  return s;
}

function saveSettings() {
  loader(true);
  try {
    const payload = collectSettings();
    const res = call('saveSettings', JSON.stringify(payload));
    if (res && res.ok) {
      state.settings = res.settings;
      toast('Настройки сохранены', 'ok');
    } else {
      toast('Не удалось сохранить', 'error');
    }
  } finally {
    loader(false);
  }
}

function resetSettings() {
  if (!confirm('Сбросить все настройки к значениям по умолчанию?')) return;
  loader(true);
  try {
    const res = call('resetSettings');
    if (res && res.ok) {
      state.settings = res.settings;
      renderSettings(res.settings);
      toast('Настройки сброшены', 'ok');
    }
  } finally {
    loader(false);
  }
}

/* ---------------- экспорт ---------------- */

function exportData(kind) {
  loader(true);
  try {
    const res = call('exportData', kind);
    if (!res || !res.ok) {
      toast('Не удалось подготовить файл', 'error');
      return;
    }
    if (!res.content || !res.content.trim()) {
      toast('Нет данных для экспорта', 'error');
      return;
    }
    call('saveFile', res.filename, res.mime, res.content);
  } finally {
    loader(false);
  }
}

/* ---------------- очистка ---------------- */

function clearData(what) {
  const labels = {
    logs: 'логи', processed: 'историю матчей',
    csv: 'CSV ставок', predictions: 'прогнозы',
  };
  if (!confirm('Очистить ' + (labels[what] || what) + '?')) return;
  const res = call('clearData', what);
  if (res && res.ok) {
    toast('Очищено', 'ok');
    if (what === 'logs') { state.logs = []; state.logsSince = 0; refreshLogs(true); }
    refreshDashboard();
  } else {
    toast('Ошибка очистки', 'error');
  }
}

/* ---------------- события ---------------- */

function bind() {
  qsa('.nav-btn').forEach(btn =>
    btn.addEventListener('click', () => navigate(btn.dataset.screen)));
  qsa('[data-nav]').forEach(btn =>
    btn.addEventListener('click', () => navigate(btn.dataset.nav)));

  $('btnStart').addEventListener('click', startEngine);
  $('btnStop').addEventListener('click', stopEngine);
  $('btnOnce').addEventListener('click', runOnce);
  $('btnRefreshQueue').addEventListener('click', () => refreshQueue(true));

  $('btnTest').addEventListener('click', () => {
    loader(true);
    try {
      const res = call('testConnection');
      if (!res) return;
      const parts = [];
      parts.push('Betcity: ' + (res.betcity ? 'ок (' + num(res.matches) + ')' : 'нет'));
      if (res.telegram === true) parts.push('Telegram: ок');
      if (res.telegram === false) parts.push('Telegram: ошибка');
      toast(parts.join(' · '), res.betcity ? 'ok' : 'error');
    } finally {
      loader(false);
    }
  });

  $('btnClearLogs').addEventListener('click', () => clearData('logs'));
  $('btnExportLogs').addEventListener('click', () => exportData('logs'));
  $('btnResetStats').addEventListener('click', () => {
    if (!confirm('Сбросить счётчики сессии?')) return;
    call('resetStats');
    refreshStats();
    toast('Счётчики сброшены', 'ok');
  });
  $('btnResetSettings').addEventListener('click', resetSettings);
  $('btnSaveSettings').addEventListener('click', saveSettings);

  $('logSearch').addEventListener('input', e => {
    state.logSearch = e.target.value.trim();
    clearTimeout(state.timers.search);
    state.timers.search = setTimeout(() => refreshLogs(true), 320);
  });

  qsa('#logFilters .chip').forEach(chip => chip.addEventListener('click', () => {
    qsa('#logFilters .chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    state.logLevel = chip.dataset.level || '';
    refreshLogs(true);
  }));

  qsa('#queueFilters .chip').forEach(chip => chip.addEventListener('click', () => {
    qsa('#queueFilters .chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    state.queueFilter = chip.dataset.qfilter;
    renderQueue();
  }));

  qsa('[data-export]').forEach(btn =>
    btn.addEventListener('click', () => exportData(btn.dataset.export)));

  qsa('[data-clear]').forEach(btn =>
    btn.addEventListener('click', () => clearData(btn.dataset.clear)));

  // пороги моделей
  document.addEventListener('input', e => {
    const target = e.target;
    if (target && target.dataset && target.dataset.model) {
      const label = $('th_' + target.dataset.model + '_val');
      if (label) label.textContent = (num(target.value) / 100).toFixed(2);
    }
    if (target && target.id === 'setMinStrong') $('lblStrong').textContent = target.value;
    if (target && target.id === 'setMinAgreement') $('lblAgreement').textContent = target.value + '%';
    if (target && target.id === 'setMinConfidence') $('lblConfidence').textContent = target.value + '%';
    if (target && target.id === 'setMinActive') $('lblActive').textContent = target.value;
    if (target && target.id === 'setVoteBase') $('lblVoteBase').textContent = (num(target.value) / 100).toFixed(2);
    if (target && target.id === 'setMinH2H') $('lblH2H').textContent = target.value;
    if (target && target.id === 'setStreak') $('lblStreak').textContent = target.value;
    if (target && target.id === 'setWindow') $('lblWindow').textContent = target.value;
    if (target && target.id === 'setWindowHits') $('lblWindowHits').textContent = target.value;
    if (target && target.id === 'setMarkov') $('lblMarkov').textContent = target.value;
    if (target && target.id === 'setDecay') $('lblDecay').textContent = (num(target.value) / 100).toFixed(2);
    if (target && target.id === 'setBaseRate') $('lblBaseRate').textContent = target.value;
  });

  document.addEventListener('click', e => {
    const chip = e.target.closest('[data-required]');
    if (chip) chip.classList.toggle('active');
  });
}

/* ---------------- периодическое обновление ---------------- */

function startPolling() {
  state.timers.dash = setInterval(() => {
    if (state.screen === 'dashboard') refreshDashboard();
  }, 2500);

  state.timers.logs = setInterval(() => {
    if (state.screen === 'logs') refreshLogs(false);
  }, 1800);

  state.timers.state = setInterval(() => {
    if (state.screen !== 'dashboard') {
      const payload = call('state');
      if (payload) applyStatus(payload);
    }
  }, 5000);
}

/* ---------------- старт ---------------- */

function init() {
  buildThresholds();
  buildRequiredModels();
  buildAllowedBets();
  buildAllowedSets();
  bind();

  const version = call('version');
  if (version) {
    $('brandSub').textContent = 'движок прогнозов · v' + (version.version || '1.0');
  }

  refreshDashboard();
  loadSettings();
  startPolling();
}

document.addEventListener('DOMContentLoaded', init);

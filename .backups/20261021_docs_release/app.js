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
  results: [],
  resultsSummary: null,
  resultsTotal: 0,
  resultsSignature: '',
  resultsFilter: { from: '', to: '', search: '', status: 'all', sport: '' },
  settings: null,
  defaults: null,
  stats: null,
  predictions: [],
  sports: [],
  sport: 'table_tennis',
  sportName: 'Настольный теннис',
  timers: {},
};

state.docs = {
  query: '',
  group: 'all',
  kind: 'all',
  article: '',
  anchor: '',
  metricSport: '',
  metricQuery: '',
  catalogs: {},
};

state.attach = null;

// Резервный справочник: интерфейс работает даже до ответа движка.
const FALLBACK_SPORTS = [
  { id: 'table_tennis', name: 'Настольный теннис', short: 'Наст. теннис', icon: '🏓', has_draw: false, bets: [{ type: 'winner' }, { type: 'total' }] },
  { id: 'football', name: 'Футбол', short: 'Футбол', icon: '⚽', has_draw: true, bets: [{ type: 'winner' }, { type: 'total' }, { type: 'handicap' }, { type: 'btts' }] },
  { id: 'hockey', name: 'Хоккей', short: 'Хоккей', icon: '🏒', has_draw: true, bets: [{ type: 'winner' }, { type: 'total' }, { type: 'handicap' }, { type: 'btts' }] },
  { id: 'basketball', name: 'Баскетбол', short: 'Баскетбол', icon: '🏀', has_draw: false, bets: [{ type: 'winner' }, { type: 'total' }, { type: 'handicap' }] },
  { id: 'volleyball', name: 'Волейбол', short: 'Волейбол', icon: '🏐', has_draw: false, bets: [{ type: 'winner' }, { type: 'total' }, { type: 'handicap' }] },
  { id: 'tennis', name: 'Большой теннис', short: 'Теннис', icon: '🎾', has_draw: false, bets: [{ type: 'winner' }, { type: 'total' }, { type: 'handicap' }] },
];

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

/* ---------------- виды спорта ---------------- */

function sportList() {
  return (state.sports && state.sports.length) ? state.sports : FALLBACK_SPORTS;
}

function sportById(id) {
  return sportList().find(item => item.id === id) || null;
}

function sportName(id) {
  const item = sportById(id);
  return item ? item.name : 'Настольный теннис';
}

function sportShort(id) {
  const item = sportById(id);
  return item ? (item.short || item.name) : 'Наст. теннис';
}

function sportBadge(id) {
  const item = sportById(id || state.sport);
  if (!item) return '';
  return '<span class="tag sport">' + esc(item.icon || '') + ' ' +
    esc(item.short || item.name) + '</span>';
}

function sportChipsHTML(active, allLabel) {
  let html = '';
  if (allLabel != null) {
    html += '<button class="chip' + (active === '' ? ' active' : '') +
      '" data-sport="">' + esc(allLabel) + '</button>';
  }
  html += sportList().map(item =>
    '<button class="chip' + (item.id === active ? ' active' : '') +
    '" data-sport="' + esc(item.id) + '">' + esc(item.icon || '') + ' ' +
    esc(item.short || item.name) + '</button>').join('');
  return html;
}

function renderSportBar() {
  const box = $('sportBar');
  if (!box) return;
  box.innerHTML = sportList().map(item =>
    '<button class="sport-chip' + (item.id === state.sport ? ' active' : '') +
    '" data-sport="' + esc(item.id) + '"><span class="sport-ico">' +
    esc(item.icon || '') + '</span><span>' +
    esc(item.short || item.name) + '</span></button>').join('');
}

function renderSportSelectors() {
  renderSportBar();
  state.sportName = sportName(state.sport);
  const ctorBox = $('ctorSports');
  if (ctorBox) ctorBox.innerHTML = sportChipsHTML(state.sport);
  const setBox = $('setSports');
  if (setBox) setBox.innerHTML = sportChipsHTML(state.sport);
  const resBox = $('resSport');
  if (resBox) resBox.innerHTML = sportChipsHTML(state.resultsFilter.sport, 'Все виды');
  const anBox = $('anSport');
  if (anBox) {
    const active = state.an ? (state.an.filter.sport || '') : '';
    let html = '<button class="chip' + (active === '' ? ' active' : '') +
      '" data-sport="">Активный</button>' +
      '<button class="chip' + (active === 'all' ? ' active' : '') +
      '" data-sport="all">Все</button>';
    html += sportList().map(item =>
      '<button class="chip' + (item.id === active ? ' active' : '') +
      '" data-sport="' + esc(item.id) + '">' + esc(item.icon || '') + ' ' +
      esc(item.short || item.name) + '</button>').join('');
    anBox.innerHTML = html;
  }
  const ctorName = $('ctorSportName');
  if (ctorName) ctorName.textContent = state.sportName;
  const infoSport = $('infoSport');
  if (infoSport) infoSport.textContent = state.sportName;
  updateSportSpecificSettings();
}

function updateSportSpecificSettings() {
  const isTT = state.sport === 'table_tennis';
  ['cardThresholds', 'cardRequired', 'cardBets', 'cardSets'].forEach(id => {
    const el = $(id);
    if (el) el.classList.toggle('hidden', !isTT);
  });
  const note = $('cardTeamNote');
  if (note) note.classList.toggle('hidden', isTT);
}

function updateAnalyzerSportUI() {
  const filterSport = state.an ? (state.an.filter.sport || '') : '';
  const effective = filterSport === 'all' ? '' : (filterSport || state.sport);
  const isAll = !effective;
  const profile = isAll ? null : (sportById(effective) || {});
  const isTT = effective === 'table_tennis';
  const bets = profile ? (profile.bets || []).map(bet => bet.type) : [];
  const showMatch = isAll || !isTT;
  const showSets = isAll || isTT;
  const showHandicap = isAll || bets.indexOf('handicap') >= 0;
  const showBtts = isAll || bets.indexOf('btts') >= 0;
  const kind = state.an ? state.an.filter.kind : 'all';
  const target = state.an ? state.an.filter.target : '';

  qsa('#anTarget [data-target="match"]').forEach(el =>
    el.classList.toggle('hidden', !showMatch));
  qsa('#anTarget [data-target^="set"]').forEach(el =>
    el.classList.toggle('hidden', !showSets));
  qsa('#anKind [data-kind="handicap"]').forEach(el =>
    el.classList.toggle('hidden', !showHandicap));
  qsa('#anKind [data-kind="btts"]').forEach(el =>
    el.classList.toggle('hidden', !showBtts));

  if (!state.an) return;
  if (!showMatch && target === 'match') state.an.filter.target = '';
  if (!showSets && target.indexOf('set') === 0) state.an.filter.target = '';
  if (kind === 'handicap' && !showHandicap) state.an.filter.kind = 'all';
  if (kind === 'btts' && !showBtts) state.an.filter.kind = 'all';

  qsa('#anTarget button').forEach(btn => btn.classList.toggle(
    'active', (btn.dataset.target || '') === state.an.filter.target));
  qsa('#anKind button').forEach(btn => btn.classList.toggle(
    'active', (btn.dataset.kind || 'all') === state.an.filter.kind));
}

function setActiveSport(id) {
  if (!id || id === state.sport) return;
  loader(true);
  try {
    const res = call('setSport', id);
    if (!res || !res.ok) {
      toast('Не удалось переключить вид спорта', 'error');
      return;
    }
    state.sport = res.sport || id;
    state.sportName = res.name || sportName(state.sport);
    if (state.settings) state.settings.active_sport = state.sport;
    state.ctor.sport = state.sport;
    state.queue = [];
    state.resultsSignature = '';
    state.an.filter.sport = '';
    state.an.filter.target = '';
    state.an.filter.kind = 'all';
    renderSportSelectors();
    updateAnalyzerSportUI();
    loadConstructor();
    refreshQueue(true);
    refreshResults();
    refreshStats();
    toast('Вид спорта: ' + state.sportName, 'ok');
  } finally {
    loader(false);
  }
}

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
  if (screen === 'results') refreshResults();
  if (screen === 'stats') refreshStats();
  if (screen === 'settings') loadSettings();
  if (screen === 'constructor') loadConstructor();
  if (screen === 'analyzer') refreshAnalyzer();
  if (screen === 'docs') renderDocs();
  if (screen === 'dashboard') refreshDashboard();
}

window.appBack = function () {
  if (state.screen === 'docs' && state.docs.article) {
    closeDocArticle();
    return true;
  }
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

  if (payload.sport && payload.sport !== state.sport) {
    state.sport = payload.sport;
    state.sportName = payload.sport_name || sportName(payload.sport);
    renderSportSelectors();
    updateAnalyzerSportUI();
  }
  if ($('infoSport')) $('infoSport').textContent = state.sportName;

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
    ? `${state.sportName} · ${state.queue.length} матчей · ${upcoming} скоро`
    : `${state.sportName}: нажмите «Обновить», чтобы загрузить линию`;

  if (!items.length) {
    box.innerHTML = '<div class="empty">Нет матчей по фильтру</div>';
    return;
  }

  box.innerHTML = items.map(m => {
    const tags = [sportBadge(m.sport || state.sport)];
    if (m.started) tags.push('<span class="tag live">в игре</span>');
    if (m.sent) tags.push('<span class="tag ok">сигнал</span>');
    else if (m.processed) tags.push('<span class="tag">обработан</span>');
    else if (!m.started) tags.push('<span class="tag warn">ожидает</span>');
    if (m.league) tags.push(`<span class="tag">${esc(m.league)}</span>`);

    let odds = '';
    if (m.odds && (m.odds.p1 || m.odds.p2)) {
      const parts = [m.odds.p1 || '—'];
      if (m.odds.draw) parts.push(m.odds.draw);
      parts.push(m.odds.p2 || '—');
      odds = `<span class="odds">${parts.map(esc).join(' / ')}` +
        (m.odds.total_line ? ` · тотал ${esc(m.odds.total_line)}` : '') +
        '</span>';
    }

    return `<div class="match-card">
      <div class="match-top">
        <div>
          <div class="match-teams">${esc(m.team1)} — ${esc(m.team2)}</div>
          <div class="match-league">${esc(m.date || '')}</div>
        </div>
        <div class="match-score">${esc(m.score || '0:0')}</div>
      </div>
      <div class="match-bottom">${tags.join('')}${odds}</div>
      ${queueSignal(m.prediction)}
    </div>`;
  }).join('');
}

function queueSignal(pred) {
  if (!pred || !pred.items || !pred.items.length) return '';
  const done = num(pred.wins) + num(pred.losses);
  const summary = done ? `${num(pred.wins)}/${done}` : '—';
  const rows = pred.items.map(it => {
    let res = '<span class="tag">ожидает</span>';
    if (it.success === true) res = `<span class="tag ok">зашла${it.score ? ' · ' + esc(it.score) : ''}</span>`;
    else if (it.success === false) res = `<span class="tag bad">не зашла${it.score ? ' · ' + esc(it.score) : ''}</span>`;
    return `<div class="signal-row">
      <span class="sig-label">${esc(it.label || it.target || '')}</span>
      <span class="sig-verdict">${esc(it.verdict || '')}</span>
      <span class="sig-res">${res}</span>
    </div>`;
  }).join('');
  return `<div class="match-signal">
    <div class="signal-title">Прогноз · ${summary}</div>
    ${rows}
  </div>`;
}

/* ---------------- результаты ---------------- */

function fmtDateTime(value) {
  if (!value) return '—';
  const s = String(value);
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (m) return `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}`;
  return s.replace('T', ' ').slice(0, 16);
}

function localStamp(date) {
  const pad = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function refreshResults() {
  const f = state.resultsFilter;
  const res = call('results', f.from, f.to, f.search, f.status, 500, f.sport || '');
  if (!res) return;
  state.results = res.items || [];
  state.resultsSummary = res.summary || {};
  state.resultsTotal = num(res.total);

  const signature = JSON.stringify(state.results.map(g => [
    g.id, (g.rows || []).length, g.wins, g.losses, g.pending, g.final_score,
  ]));
  renderResultsMeta();
  if (signature !== state.resultsSignature) {
    state.resultsSignature = signature;
    renderResults();
  }
}

function renderResultsMeta() {
  const s = state.resultsSummary || {};
  $('resultsMeta').textContent = state.resultsTotal
    ? `Матчей: ${num(s.games)} · прогнозов: ${num(s.preds)}`
    : 'Нет сохранённых прогнозов';
  $('resGames').textContent = num(s.games);
  $('resPreds').textContent = num(s.preds);
  $('resRate').textContent = num(s.hit_rate).toFixed(1) + '%';
  $('resWins').textContent = num(s.wins);
  $('resLosses').textContent = num(s.losses);
  $('resPending').textContent = num(s.pending);
  $('resShown').textContent = state.results.length;
}

function resultRow(row) {
  let cls = 'pending';
  let badge = '<span class="tag">ожидает</span>';
  if (row.success === true) {
    cls = 'win';
    badge = `<span class="tag ok">зашла${row.score ? ' · ' + esc(row.score) : ''}</span>`;
  } else if (row.success === false) {
    cls = 'loss';
    badge = `<span class="tag bad">не зашла${row.score ? ' · ' + esc(row.score) : ''}</span>`;
  } else if (row.score) {
    badge = `<span class="tag">${esc(row.score)}</span>`;
  }

  const stats = [];
  if (row.confidence != null) stats.push('уверенность ' + num(row.confidence).toFixed(0) + '%');
  if (row.strong != null) stats.push('моделей ' + num(row.strong));
  if (row.agreement != null) stats.push('согласие ' + num(row.agreement).toFixed(0) + '%');
  if (row.kind === 'total' && row.threshold != null) stats.push('порог ' + esc(row.threshold));
  if (row.total != null) stats.push('тотал ' + esc(row.total));

  const reason = row.reason
    ? `<div class="result-reason">${esc(row.reason)}</div>`
    : '<div class="result-reason">Основание не сохранено</div>';

  return `<div class="result-row ${cls}">
    <div class="result-line">
      <span class="result-label">${esc(row.label || row.target || '')}</span>
      <span class="result-verdict">${esc(row.verdict || '')}</span>
      <span class="result-badge">${badge}</span>
    </div>
    ${reason}
    ${stats.length ? `<div class="result-stats">${stats.join(' · ')}</div>` : ''}
  </div>`;
}

function gameResultCard(g) {
  const rows = g.rows || [];
  const scoreText = g.final_score
    ? esc(g.final_score)
    : `${num(g.wins)}/${rows.length}`;
  const meta = [fmtDateTime(g.sent_at), g.league, g.date ? 'матч ' + g.date : '']
    .filter(Boolean).join(' · ');

  return `<div class="result-card">
    <div class="result-top">
      <div>
        <div class="result-teams">${esc(g.team1)} — ${esc(g.team2)}</div>
        <div class="result-meta">${sportBadge(g.sport || state.sport)} ${esc(meta)}</div>
      </div>
      <div class="result-score">${scoreText}</div>
    </div>
    <div class="result-rows">
      ${rows.length ? rows.map(resultRow).join('')
        : '<div class="result-empty">Прогнозы не сохранены</div>'}
    </div>
  </div>`;
}

function renderResults() {
  const box = $('resultsList');
  if (!state.results.length) {
    box.innerHTML = '<div class="empty">Нет игр за выбранный период</div>';
    return;
  }
  box.innerHTML = state.results.map(gameResultCard).join('');
}

function setResultsRange(kind) {
  const f = state.resultsFilter;
  const now = new Date();
  if (kind === 'all') {
    f.from = '';
    f.to = '';
  } else {
    const from = new Date(now);
    from.setHours(0, 0, 0, 0);
    if (kind === '7') from.setDate(from.getDate() - 6);
    if (kind === '30') from.setDate(from.getDate() - 29);
    f.from = localStamp(from);
    f.to = localStamp(now);
  }
  $('resFrom').value = f.from;
  $('resTo').value = f.to;
  qsa('#resQuick .chip').forEach(c => c.classList.toggle('active', c.dataset.quick === kind));
  refreshResults();
}


/* ---------------- статистика ---------------- */

function refreshStats() {
  const stats = call('stats');
  if (stats) {
    applyStatsSummary(stats);
    renderBySport(stats.by_sport || []);
    renderByTarget(stats.by_target || []);
  }
  const preds = call('predictions', 100, state.sport);
  if (preds) {
    state.predictions = preds.items || [];
    renderPredictions();
  }
}

const SET_LABELS = {
  set1: 'Партия 1', set2: 'Партия 2', set3: 'Партия 3',
  set4: 'Партия 4', set5: 'Партия 5',
};

const MATCH_KIND_LABELS = {
  winner: 'исход', total: 'тотал', handicap: 'фора', btts: 'обе забьют',
};

function targetLabel(key) {
  const raw = String(key || '');
  const parts = raw.split(':');
  const kind = parts[1] || '';
  if (parts[0] === 'match') {
    return 'Матч' + (kind ? ' · ' + (MATCH_KIND_LABELS[kind] || kind) : '');
  }
  const set = SET_LABELS[parts[0]] || parts[0];
  if (kind === 'total') return set + ' · ТБ/ТМ';
  if (kind === 'winner') return set + ' · П1/П2';
  if (kind === 'handicap') return set + ' · фора';
  if (kind === 'btts') return set + ' · ОЗ';
  return raw;
}

function renderBySport(rows) {
  const box = $('bySport');
  if (!box) return;
  if (!rows.length) {
    box.innerHTML = '<div class="empty">Нет данных по видам спорта</div>';
    return;
  }
  box.innerHTML = rows.map(r => {
    const rate = Math.max(0, Math.min(100, num(r.hit_rate)));
    const label = r.name || sportShort(r.sport);
    const meta = `${num(r.wins)}/${num(r.wins) + num(r.losses)}` +
      (r.pending ? ` · ${num(r.pending)} ждут` : '');
    return `<div class="bt-row">
      <div class="bt-name" title="${esc(state.sport === r.sport ? 'активный вид спорта' : '')}">
        ${esc(label)}${state.sport === r.sport ? ' · активный' : ''}</div>
      <div class="bt-bar"><div class="bt-fill" style="width:${rate}%"></div></div>
      <div class="bt-val">${esc(meta)}</div>
    </div>`;
  }).join('');
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
          <div class="pred-date">${sportBadge(p.sport || state.sport)} ${esc((p.sent_at || '').replace('T', ' ').slice(0, 16))}${p.league ? ' · ' + esc(p.league) : ''}</div>
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
  if (Array.isArray(res.sports) && res.sports.length) state.sports = res.sports;
  state.sport = res.settings.active_sport || state.sport || 'table_tennis';
  state.sportName = sportName(state.sport);
  state.ctor.sport = state.sport;
  renderSportSelectors();
  updateAnalyzerSportUI();
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

  const mode = s.algorithm_mode === 'constructor' ? 'constructor' : 'builtin';
  state.ctor.mode = mode;
  syncModeUI(mode);
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

  s.algorithm_mode = state.ctor.mode || s.algorithm_mode || 'builtin';
  s.active_sport = state.sport;

  return s;
}

function saveSettings() {
  loader(true);
  try {
    const payload = collectSettings();
    const res = call('saveSettings', JSON.stringify(payload));
    if (res && res.ok) {
      state.settings = res.settings;
      state.ctor.mode = res.settings.algorithm_mode || state.ctor.mode;
      syncModeUI(state.ctor.mode);
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
      state.sport = res.settings.active_sport || 'table_tennis';
      state.sportName = sportName(state.sport);
      state.ctor.sport = state.sport;
      renderSportSelectors();
      updateAnalyzerSportUI();
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
  qsa('[data-doc]').forEach(btn =>
    btn.addEventListener('click', () => openDoc(btn.dataset.doc)));

  bindDocs();
  bindAttach();

  // выбор вида спорта: верхняя панель, конструктор, настройки, фильтры
  ['sportBar', 'ctorSports', 'setSports', 'resSport'].forEach(id => {
    const box = $(id);
    if (!box) return;
    box.addEventListener('click', e => {
      const btn = e.target.closest('[data-sport]');
      if (!btn) return;
      const value = btn.dataset.sport;
      if (id === 'resSport') {
        state.resultsFilter.sport = value || '';
        state.resultsSignature = '';
        qsa('#resSport [data-sport]').forEach(chip =>
          chip.classList.toggle('active', chip === btn));
        refreshResults();
      } else {
        setActiveSport(value);
      }
    });
  });

  const anSportBox = $('anSport');
  if (anSportBox) anSportBox.addEventListener('click', e => {
    const btn = e.target.closest('[data-sport]');
    if (!btn) return;
    state.an.filter.sport = btn.dataset.sport || '';
    qsa('#anSport [data-sport]').forEach(chip =>
      chip.classList.toggle('active', chip === btn));
    updateAnalyzerSportUI();
    refreshAnalyzer();
  });

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

  // результаты: фильтр по дате/времени, поиск и статус
  $('btnExportResults').addEventListener('click', () => exportData('results'));
  $('btnResetResults').addEventListener('click', () => {
    state.resultsFilter = { from: '', to: '', search: '', status: 'all', sport: '' };
    $('resFrom').value = '';
    $('resTo').value = '';
    $('resSearch').value = '';
    qsa('#resStatus .chip').forEach(c => c.classList.toggle('active', c.dataset.status === 'all'));
    qsa('#resQuick .chip').forEach(c => c.classList.toggle('active', c.dataset.quick === 'all'));
    qsa('#resSport [data-sport]').forEach(c => c.classList.toggle('active', c.dataset.sport === ''));
    refreshResults();
  });
  $('resFrom').addEventListener('change', () => {
    state.resultsFilter.from = $('resFrom').value;
    qsa('#resQuick .chip').forEach(c => c.classList.remove('active'));
    refreshResults();
  });
  $('resTo').addEventListener('change', () => {
    state.resultsFilter.to = $('resTo').value;
    qsa('#resQuick .chip').forEach(c => c.classList.remove('active'));
    refreshResults();
  });
  $('resSearch').addEventListener('input', e => {
    state.resultsFilter.search = e.target.value.trim();
    clearTimeout(state.timers.resSearch);
    state.timers.resSearch = setTimeout(refreshResults, 320);
  });
  qsa('#resStatus .chip').forEach(chip => chip.addEventListener('click', () => {
    qsa('#resStatus .chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    state.resultsFilter.status = chip.dataset.status || 'all';
    refreshResults();
  }));
  qsa('#resQuick .chip').forEach(chip =>
    chip.addEventListener('click', () => setResultsRange(chip.dataset.quick)));

  qsa('[data-export]').forEach(btn =>
    btn.addEventListener('click', () => exportData(btn.dataset.export)));

  qsa('[data-clear]').forEach(btn =>
    btn.addEventListener('click', () => clearData(btn.dataset.clear)));

  // конструктор
  qsa('#ctorMode button').forEach(btn =>
    btn.addEventListener('click', () => setMode(btn.dataset.mode)));
  qsa('#setMode button').forEach(btn =>
    btn.addEventListener('click', () => setMode(btn.dataset.mode)));
  $('btnAddRule').addEventListener('click', () => openRuleEditor(-1));
  $('btnPresets').addEventListener('click', openPresets);
  $('btnTestRules').addEventListener('click', testRules);
  $('btnExportRules').addEventListener('click', () => exportData('constructor'));
  $('btnImportRules').addEventListener('click', importRules);
  $('rulesList').addEventListener('click', onRulesListClick);
  $('btnCloseRule').addEventListener('click', closeRuleEditor);
  $('btnRuleCancel').addEventListener('click', closeRuleEditor);
  $('btnRuleSave').addEventListener('click', saveRuleEditor);
  $('btnRuleDelete').addEventListener('click', deleteEditingRule);
  $('btnClosePresets').addEventListener('click', () => $('presetModal').classList.add('hidden'));
  $('presetBody').addEventListener('click', e => {
    const category = e.target.closest('[data-preset-cat]');
    if (category) {
      state.ctor.presetCat = category.dataset.presetCat || '';
      renderPresetList();
      return;
    }
    const card = e.target.closest('[data-preset]');
    if (card) addPreset(num(card.dataset.preset));
  });
  $('presetBody').addEventListener('input', e => {
    if (e.target && e.target.id === 'presetSearch') {
      state.ctor.presetQuery = e.target.value || '';
      renderPresetList();
    }
  });
  $('btnCloseImport').addEventListener('click', () => $('importModal').classList.add('hidden'));
  $('btnImportCancel').addEventListener('click', () => $('importModal').classList.add('hidden'));
  $('btnImportApply').addEventListener('click', applyImport);
  $('ruleModalBody').addEventListener('change', onEditorChange);
  $('ruleModalBody').addEventListener('input', onEditorInput);
  $('ruleModalBody').addEventListener('click', onEditorClick);

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

  // анализатор
  $('btnAnRefresh').addEventListener('click', () => refreshAnalyzer(true));
  $('btnAnExport').addEventListener('click', () => exportData('analyzer'));

  $('anKind').addEventListener('click', e => {
    const btn = e.target.closest('button[data-kind]');
    if (!btn) return;
    state.an.filter.kind = btn.dataset.kind;
    qsa('#anKind button').forEach(b => b.classList.toggle('active', b === btn));
    refreshAnalyzer();
  });
  $('anTarget').addEventListener('click', e => {
    const btn = e.target.closest('button[data-target]');
    if (!btn) return;
    state.an.filter.target = btn.dataset.target;
    qsa('#anTarget button').forEach(b => b.classList.toggle('active', b === btn));
    refreshAnalyzer();
  });
  $('anMinGroup').addEventListener('click', e => {
    const btn = e.target.closest('button[data-min]');
    if (!btn) return;
    state.an.filter.min_group = num(btn.dataset.min);
    qsa('#anMinGroup button').forEach(b => b.classList.toggle('active', b === btn));
    refreshAnalyzer();
  });
  $('anMinLift').addEventListener('click', e => {
    const btn = e.target.closest('button[data-lift]');
    if (!btn) return;
    state.an.filter.min_lift = num(btn.dataset.lift);
    qsa('#anMinLift button').forEach(b => b.classList.toggle('active', b === btn));
    refreshAnalyzer();
  });
  $('btnAnFailMore').addEventListener('click', () => {
    state.an.expanded.failure = !state.an.expanded.failure;
    renderAnList('failure', (state.an.data || {}).failure || []);
  });
  $('btnAnSuccMore').addEventListener('click', () => {
    state.an.expanded.success = !state.an.expanded.success;
    renderAnList('success', (state.an.data || {}).success || []);
  });
  $('anFailures').addEventListener('click', onAnalyzerListClick);
  $('anLimits').addEventListener('click', onAnalyzerListClick);
  $('anSuccesses').addEventListener('click', onAnalyzerListClick);
  $('anCombos').addEventListener('click', onAnalyzerComboClick);
}

function onAnalyzerListClick(event) {
  const btn = event.target.closest('[data-an-add]');
  if (!btn) return;
  const group = btn.dataset.anAdd;
  const row = analyzerRow(group, num(btn.dataset.anIndex));
  if (!row) return;
  analyzerToConstructor([row.condition], group === 'failure', row.text, [row.text]);
}

function onAnalyzerComboClick(event) {
  const btn = event.target.closest('[data-an-combo]');
  if (!btn) return;
  const group = btn.dataset.anCombo;
  const combos = ((state.an.data || {}).combos || {})[group] || [];
  const combo = combos[num(btn.dataset.anIndex)];
  if (!combo) return;
  analyzerToConstructor(combo.conditions, group === 'failure', combo.text,
    combo.texts || [combo.text]);
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

  state.timers.results = setInterval(() => {
    if (state.screen === 'results') refreshResults();
  }, 10000);

  state.timers.ctor = setInterval(() => {
    if (state.screen === 'constructor' && !state.ctor.editing) loadConstructor();
  }, 15000);
}

/* ================= КОНСТРУКТОР ================= */

state.ctor = {
  rules: [],
  catalog: null,
  presets: [],
  stats: null,
  mode: 'builtin',
  sport: 'table_tennis',
  editing: null,
  editingIndex: -1,
  test: null,
  attachNotice: '',
  highlightId: '',
  highlightTimer: null,
};

function ctorSport() {
  return (state.ctor.catalog && state.ctor.catalog.sport) ||
    state.ctor.sport || state.sport || 'table_tennis';
}

function ctorIsTeam() {
  return ctorSport() !== 'table_tennis';
}

function ctorProfile() {
  return sportById(ctorSport()) || {};
}

function sideName(number) {
  return (ctorIsTeam() ? 'Команда ' : 'Игрок ') + number;
}

function metricById(id) {
  return (state.ctor.catalog && state.ctor.catalog.metrics || [])
    .find(m => m.id === id) || null;
}

function metricLabel(metric) {
  if (!metric) return '';
  let text = metric.label || metric.id;
  const values = Object.assign({}, metric.args || {});
  if (values.side) values.side = values.side === 'p2' ? 'игрока 2' : 'игрока 1';
  if (values.set) values.set = values.set + '-й';
  if (values.window) values.window = String(values.window);
  Object.keys(values).forEach(key => {
    text = text.split('{' + key + '}').join(values[key]);
  });
  return text;
}

function metricOptionsHTML(selected) {
  const metrics = (state.ctor.catalog && state.ctor.catalog.metrics) || [];
  const groups = {};
  metrics.forEach(m => { (groups[m.group] = groups[m.group] || []).push(m); });
  return Object.keys(groups).map(group =>
    '<optgroup label="' + esc(group) + '">' + groups[group].map(m =>
      '<option value="' + esc(m.id) + '"' + (m.id === selected ? ' selected' : '') + '>' +
      esc(metricLabel(m)) + '</option>').join('') + '</optgroup>').join('');
}

function defaultValueFor(metric) {
  if (!metric) return 1;
  if (metric.type === 'enum') {
    const opt = (metric.options || [])[0];
    return opt ? opt[0] : '';
  }
  if (metric.type === 'bool') return true;
  if (metric.type === 'number') {
    const line = num((state.ctor.catalog || {}).default_total) ||
      num((ctorProfile() || {}).default_total) || 18.5;
    if ((metric.unit || '') === '%') return 50;
    if (metric.id.indexOf('odds.') === 0) return 1.8;
    if (metric.id === 'page.total_line') return line;
    if (metric.id.indexOf('window') >= 0) return 5;
    if (metric.id.indexOf('match_total') >= 0 || metric.id.indexOf('odds.total') >= 0) {
      return line;
    }
    if (ctorIsTeam()) return line;
    return 19;
  }
  return '';
}

function defaultCondition() {
  const metrics = (state.ctor.catalog && state.ctor.catalog.metrics) || [];
  const preferred = ctorIsTeam() ? 'p.recent.avg_match_total' : 'p.recent.avg_set_total';
  const metric = metrics.find(m => m.id === preferred) || metrics[0];
  if (!metric) return { metric: '', args: {}, op: 'gt', value: 19 };
  const ops = ((state.ctor.catalog.operators || {})[metric.type] || [])[0];
  return {
    metric: metric.id,
    args: Object.assign({}, metric.args || {}),
    op: ops ? ops[0] : 'gt',
    value: defaultValueFor(metric),
  };
}

function newRuleTemplate() {
  const isTeam = ctorIsTeam();
  const line = num((state.ctor.catalog || {}).default_total) ||
    num((ctorProfile() || {}).default_total) || (isTeam ? 2.5 : 18.5);
  return {
    id: 'r_' + Math.random().toString(36).slice(2, 12),
    name: 'Новое правило',
    sport: ctorSport(),
    enabled: true,
    priority: 100,
    stop: false,
    conditions: { logic: 'and', conditions: [defaultCondition()] },
    action: {
      type: 'total',
      targets: isTeam ? ['match'] : [1],
      side: 'over',
      threshold: line,
      confidence: 0.6,
    },
  };
}

function loadConstructor() {
  const res = call('constructor', state.sport);
  if (!res || !res.ok) return;
  state.ctor.sport = res.sport || state.sport;
  state.ctor.catalog = res.catalog || { metrics: [], args: {}, operators: {} };
  state.ctor.presets = res.presets || [];
  state.ctor.rules = res.rules || [];
  state.ctor.stats = res.stats || {};
  state.ctor.mode = res.mode || 'builtin';
  renderSportSelectors();
  renderConstructor();
}

function syncModeUI(mode) {
  state.ctor.mode = mode === 'constructor' ? 'constructor' : 'builtin';
  qsa('#ctorMode button').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.mode === state.ctor.mode));
  qsa('#setMode button').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.mode === state.ctor.mode));
  const hint = $('ctorModeHint');
  if (hint) {
    const enabled = (state.ctor.rules || []).filter(r => r.enabled).length;
    if (state.ctor.mode === 'constructor') {
      hint.textContent = enabled
        ? 'Активен конструктор: включённых правил — ' + enabled + '. Прогнозы отправляются только по ним.'
        : 'Конструктор выбран, но нет включённых правил — прогнозы отправляться не будут.';
    } else {
      hint.textContent = 'Встроенный — ансамбль из 6 моделей. Конструктор — только ваши правила.';
    }
  }
}

function renderConstructor() {
  const c = state.ctor;
  const enabled = (c.rules || []).filter(r => r.enabled).length;
  $('ctorRules').textContent = (c.rules || []).length;
  $('ctorEnabled').textContent = enabled;
  $('ctorFired').textContent = num((c.stats || {}).fired);
  $('ctorSkipped').textContent = num((c.stats || {}).skipped);
  $('ctorMeta').textContent = (c.rules || []).length
    ? `${state.sportName}: правил ${c.rules.length} · включено ${enabled}`
    : `${state.sportName}: правила прогнозов по статистике`;
  const ctorName = $('ctorSportName');
  if (ctorName) ctorName.textContent = state.sportName;
  syncModeUI(c.mode);
  renderRulesList();
}

function renderRulesList() {
  const box = $('rulesList');
  const rules = state.ctor.rules || [];
  if (!rules.length) {
    box.innerHTML = '<div class="empty">Правил пока нет. Нажмите «+ Правило» или выберите шаблон.</div>';
    return;
  }
  const highlightId = state.ctor.highlightId || '';
  box.innerHTML = rules.map((rule, index) => {
    const actionText = rule.action_text || '';
    return `<div class="rule-card ${rule.enabled ? '' : 'disabled'}${highlightId && highlightId === rule.id ? ' highlight' : ''}" data-rule-id="${esc(rule.id || '')}">
      <div class="rule-top">
        <div class="rule-info">
          <div class="rule-name">${esc(rule.name || ('Правило ' + (index + 1)))}</div>
          <div class="rule-badges">
            <span class="badge">${esc(sportShort(rule.sport || state.ctor.sport))}</span>
            <span class="badge ${rule.enabled ? 'ok' : ''}">${rule.enabled ? 'включено' : 'выключено'}</span>
            <span class="badge">приоритет ${num(rule.priority)}</span>
            <span class="badge accent">${esc(actionText)}</span>
            ${rule.stop ? '<span class="badge warn">стоп после правила</span>' : ''}
          </div>
          <div class="rule-summary">${esc(rule.conditions_text || '')}</div>
        </div>
      </div>
      <div class="rule-actions">
        <button class="btn btn-ghost btn-sm" data-ract="edit" data-index="${index}">Изменить</button>
        <button class="btn btn-ghost btn-sm" data-ract="toggle" data-index="${index}">${rule.enabled ? 'Выключить' : 'Включить'}</button>
        <button class="btn btn-ghost btn-sm" data-ract="dup" data-index="${index}">Копия</button>
        <button class="btn btn-ghost btn-sm" data-ract="up" data-index="${index}">↑</button>
        <button class="btn btn-ghost btn-sm" data-ract="down" data-index="${index}">↓</button>
        <button class="btn btn-ghost btn-sm danger" data-ract="del" data-index="${index}">Удалить</button>
      </div>
    </div>`;
  }).join('');

  if (highlightId) {
    const card = box.querySelector('[data-rule-id="' + highlightId + '"]');
    if (card) card.scrollIntoView({ block: 'center' });
    clearTimeout(state.ctor.highlightTimer);
    state.ctor.highlightTimer = setTimeout(() => {
      state.ctor.highlightId = '';
      qsa('.rule-card.highlight').forEach(item => item.classList.remove('highlight'));
    }, 4000);
  }
}

function saveRules(rules, mode, message) {
  loader(true);
  try {
    const payload = { rules: rules, sport: state.ctor.sport || state.sport };
    if (mode) payload.mode = mode;
    const res = call('saveConstructor', JSON.stringify(payload));
    if (!res || !res.ok) {
      const errors = (res && res.errors) || [];
      toast(errors.length ? errors[0] : 'Не удалось сохранить правила', 'error');
      return null;
    }
    state.ctor.rules = res.rules || [];
    state.ctor.mode = res.mode || state.ctor.mode;
    state.ctor.stats = res.stats || state.ctor.stats;
    if (state.settings) state.settings.algorithm_mode = state.ctor.mode;
    renderConstructor();
    if (message) toast(message, 'ok');
    return res;
  } finally {
    loader(false);
  }
}

function setMode(mode) {
  if (mode === 'constructor' && !(state.ctor.rules || []).some(r => r.enabled)) {
    if (!confirm('Нет включённых правил — прогнозы отправляться не будут. Продолжить?')) return;
  }
  const res = call('setAlgorithmMode', mode);
  if (res && res.ok) {
    state.ctor.mode = res.mode;
    if (state.settings) state.settings.algorithm_mode = res.mode;
    syncModeUI(res.mode);
    toast(res.mode === 'constructor' ? 'Включён конструктор' : 'Включён встроенный алгоритм', 'ok');
  } else {
    toast('Не удалось переключить режим', 'error');
  }
}

/* ---------- редактор правила ---------- */

function parsePath(value) {
  try { return JSON.parse(value); } catch (e) { return []; }
}

function groupAt(root, path) {
  if (!path.length) return root.conditions;
  return nodeAt(root, path);
}

function containerFor(root, path) {
  let container = root.conditions.conditions;
  for (let i = 0; i < path.length - 1; i++) {
    const node = container[path[i]];
    if (!node || !node.conditions) return null;
    container = node.conditions;
  }
  return container;
}

function nodeAt(root, path) {
  if (!path.length) return root.conditions;
  const container = containerFor(root, path);
  return container ? container[path[path.length - 1]] : null;
}

function deleteAt(root, path) {
  const container = containerFor(root, path);
  if (container) container.splice(path[path.length - 1], 1);
}

function renderGroupHTML(group, path, isRoot) {
  group = group || { logic: 'and', conditions: [] };
  const logic = group.logic === 'or' ? 'or' : 'and';
  const pathAttr = JSON.stringify(path);
  const children = (group.conditions || []).map((child, index) => {
    const childPath = path.concat([index]);
    if (child && child.metric) return renderConditionHTML(child, childPath);
    return renderGroupHTML(child, childPath, false);
  }).join('');
  return `<div class="cond-group" data-group-path='${pathAttr}'>
    <div class="cond-group-head">
      <div class="segmented small" style="width:auto" data-logic-path='${pathAttr}'>
        <button type="button" data-logic="and" class="${logic === 'and' ? 'active' : ''}">И</button>
        <button type="button" data-logic="or" class="${logic === 'or' ? 'active' : ''}">ИЛИ</button>
      </div>
      <span class="spacer"></span>
      <button type="button" class="link-btn mini" data-add-cond='${pathAttr}'>+ условие</button>
      <button type="button" class="link-btn mini" data-add-group='${pathAttr}'>+ группа</button>
      ${isRoot ? '' : `<button type="button" class="link-btn mini" data-del-group='${pathAttr}'>✕</button>`}
    </div>
    <div class="cond-children">${children || '<div class="field-hint">Нет условий</div>'}</div>
  </div>`;
}

function renderConditionHTML(cond, path) {
  const pathAttr = JSON.stringify(path);
  const metric = metricById(cond.metric) ||
    ((state.ctor.catalog && state.ctor.catalog.metrics) || [])[0] ||
    { id: '', label: '', args: {}, type: 'number' };
  const argDefs = (state.ctor.catalog && state.ctor.catalog.args) || {};
  const args = Object.assign({}, metric.args || {}, cond.args || {});
  const argWidgets = Object.keys(metric.args || {}).map(name => {
    const def = argDefs[name] || {};
    if (def.kind === 'select') {
      const options = (def.options || []).map(o =>
        '<option value="' + esc(o[0]) + '"' +
        (String(args[name]) === String(o[0]) ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('');
      return '<select class="cond-arg" data-arg="' + name + '" data-path=\'' + pathAttr + '\'>' +
        options + '</select>';
    }
    return '<input class="cond-arg" type="number" step="' + esc(def.step || 1) +
      '" data-arg="' + name + '" data-path=\'' + pathAttr + '\' value="' + esc(args[name]) + '">';
  }).join('');
  const operators = ((state.ctor.catalog && state.ctor.catalog.operators) || {})[metric.type] ||
    ((state.ctor.catalog && state.ctor.catalog.operators) || {}).number || [];
  const opWidget = '<select class="cond-op" data-op="1" data-path=\'' + pathAttr + '\'>' +
    operators.map(o => '<option value="' + esc(o[0]) + '"' +
      (cond.op === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('') + '</select>';
  return `<div class="cond-row" data-path='${pathAttr}'>
    <div class="cond-fields">
      <select class="cond-metric" data-metric="1" data-path='${pathAttr}'>${metricOptionsHTML(cond.metric)}</select>
      ${argWidgets}
      ${opWidget}
      ${valueWidgetHTML(cond, metric, pathAttr)}
    </div>
    <div class="cond-foot">
      <label class="mini-toggle">
        <input type="checkbox" data-value-metric-toggle="1" data-path='${pathAttr}'
          ${cond.value_metric ? 'checked' : ''}> сравнить с метрикой
      </label>
      <span class="spacer"></span>
      <button type="button" class="link-btn mini" data-del-cond='${pathAttr}'>удалить условие</button>
    </div>
  </div>`;
}

function valueWidgetHTML(cond, metric, pathAttr) {
  if (cond.op === 'exists' || cond.op === 'not_exists') return '';
  if (cond.value_metric) {
    return '<select class="cond-value" data-value-metric="1" data-path=\'' + pathAttr + '\'>' +
      metricOptionsHTML(cond.value_metric) + '</select>';
  }
  const type = metric.type || 'number';
  if (type === 'number') {
    if (cond.op === 'between') {
      return '<input class="cond-value" type="number" step="0.5" data-value data-path=\'' + pathAttr +
        '\' value="' + esc(cond.value) + '">' +
        '<input class="cond-value" type="number" step="0.5" data-value2 data-path=\'' + pathAttr +
        '\' value="' + esc(cond.value2) + '">';
    }
    return '<input class="cond-value" type="number" step="0.01" data-value data-path=\'' + pathAttr +
      '\' value="' + esc(cond.value) + '">';
  }
  if (type === 'enum') {
    if (cond.op === 'in' || cond.op === 'not_in') {
      const text = Array.isArray(cond.value) ? cond.value.join(', ') : (cond.value || '');
      return '<input class="cond-value" type="text" data-value data-path=\'' + pathAttr +
        '\' value="' + esc(text) + '" placeholder="значение1, значение2">';
    }
    const options = (metric.options || []).map(o =>
      '<option value="' + esc(o[0]) + '"' +
      (String(cond.value) === String(o[0]) ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('');
    return '<select class="cond-value" data-value data-path=\'' + pathAttr + '\'>' +
      options + '</select>';
  }
  if (type === 'bool') {
    return '<select class="cond-value" data-value data-path=\'' + pathAttr + '\'>' +
      '<option value="true"' + (cond.value === true ? ' selected' : '') + '>да</option>' +
      '<option value="false"' + (cond.value === false ? ' selected' : '') + '>нет</option></select>';
  }
  const isList = cond.op === 'in' || cond.op === 'not_in';
  const text = Array.isArray(cond.value) ? cond.value.join(', ') : (cond.value || '');
  return '<input class="cond-value" type="text" data-value data-path=\'' + pathAttr +
    '\' value="' + esc(text) + '"' + (isList ? ' placeholder="значение1, значение2"' : '') + '>';
}

function actionTypeOptions() {
  const hasDraw = !!ctorProfile().has_draw;
  const options = [];
  if (ctorIsTeam()) {
    options.push(['winner', hasDraw
      ? 'Исход матча (П1 / ничья / П2)'
      : 'Победитель матча (П1 / П2)']);
    options.push(['total', 'Тотал матча (ТБ / ТМ)']);
    options.push(['handicap', 'Фора матча (Ф1 / Ф2)']);
    const bets = ((state.ctor.catalog || {}).bets || []).map(bet => bet.type);
    if (bets.indexOf('btts') >= 0) {
      options.push(['btts', 'Обе забьют (да / нет)']);
    }
  } else {
    options.push(['total', 'Тотал партии (ТБ / ТМ)']);
    options.push(['winner', 'Победитель партии (П1 / П2)']);
  }
  options.push(['skip', 'Пропустить матч']);
  return options;
}

function renderActionExtra(action) {
  const type = action.type || 'total';
  if (type === 'skip') {
    return '<div class="field-hint">Матч будет пропущен без прогноза.</div>';
  }
  const isTeam = ctorIsTeam();
  const profile = ctorProfile();
  const line = num(action.threshold) ||
    num((state.ctor.catalog || {}).default_total) ||
    num(profile.default_total) || (isTeam ? 2.5 : 18.5);
  const confidence = Math.round((num(action.confidence) || 0.6) * 100);
  const side = action.side || 'auto';

  let html = '';
  if (!isTeam) {
    const targets = action.targets || [1];
    const isAuto = targets.indexOf('auto') >= 0;
    const chips = [1, 2, 3, 4, 5].map(n =>
      '<button type="button" class="chip' +
      ((!isAuto && targets.indexOf(n) >= 0) ? ' active' : '') +
      '" data-target="' + n + '">' + n + '-я</button>').join('') +
      '<button type="button" class="chip' + (isAuto ? ' active' : '') +
      '" data-target="auto">Авто</button>';
    html += '<div class="field"><label>Партии</label>' +
      '<div class="chips" id="ruleTargets">' + chips + '</div></div>';
  } else {
    html += '<div class="field"><label>Область ставки</label>' +
      '<div class="scope-note">Матч целиком: исход, тотал, фора и «обе забьют» ' +
      'считаются по итоговому счёту.</div></div>';
  }

  let sideOptions;
  if (type === 'total') {
    sideOptions = [['auto', 'Авто (по статистике)'], ['over', 'ТБ — больше'],
      ['under', 'ТМ — меньше']];
  } else if (type === 'handicap') {
    sideOptions = [['auto', 'Авто (по статистике)'],
      ['p1', sideName(1) + ' (Ф1)'], ['p2', sideName(2) + ' (Ф2)']];
  } else if (type === 'btts') {
    sideOptions = [['auto', 'Авто (по статистике)'], ['yes', 'Да'],
      ['no', 'Нет']];
  } else if (isTeam) {
    sideOptions = [['auto', 'Авто (по статистике)'],
      ['p1', sideName(1) + ' (П1)']];
    if (profile.has_draw) sideOptions.push(['x', 'Ничья (X)']);
    sideOptions.push(['p2', sideName(2) + ' (П2)']);
  } else {
    sideOptions = [['auto', 'Авто (по статистике)'],
      ['p1', sideName(1) + ' (П1)'], ['p2', sideName(2) + ' (П2)']];
  }

  html += '<div class="field"><label>Ставка</label>' +
    '<select id="ruleSide">' + sideOptions.map(o =>
      '<option value="' + o[0] + '"' + (side === o[0] ? ' selected' : '') +
      '>' + esc(o[1]) + '</option>').join('') + '</select></div>';

  if (type === 'total') {
    html += '<div class="field"><label>Порог тотала</label>' +
      '<input type="number" id="ruleThreshold" step="0.5" value="' +
      esc(line) + '">' +
      '<div class="field-hint">Сравнение с суммой голов/очков матча.</div></div>';
  }
  if (type === 'handicap') {
    const value = (action.value === undefined || action.value === null)
      ? 0 : num(action.value);
    html += '<div class="field"><label>Значение форы</label>' +
      '<input type="number" id="ruleHandicap" step="0.5" value="' +
      esc(value) + '">' +
      '<div class="field-hint">Для Ф1 укажите отрицательное значение ' +
      '(например −1.5), для Ф2 — положительное (+1.5).</div></div>';
  }

  html += '<div class="field"><label>Уверенность прогноза ' +
    '<b id="ruleConfVal">' + confidence + '%</b></label>' +
    '<input type="range" id="ruleConf" min="5" max="99" step="1" value="' +
    confidence + '"></div>';
  return html;
}

function renderRuleEditor() {
  const rule = state.ctor.editing;
  if (!rule) return;
  const action = rule.action || {};
  const type = action.type || 'total';
  const options = actionTypeOptions();
  $('ruleModalBody').innerHTML = `
    ${state.ctor.attachNotice ? `<div class="rule-notice">${esc(state.ctor.attachNotice)}</div>` : ''}
    <div class="field"><label>Название правила</label>
      <input type="text" id="ruleName" value="${esc(rule.name || '')}"></div>
    <div class="field-hint mb">${esc(state.sportName)} · правила этого вида спорта</div>
    <div class="field-row">
      <div class="field" style="flex:0 0 96px"><label>Приоритет</label>
        <input type="number" id="rulePriority" value="${num(rule.priority)}"></div>
      <div class="rule-flags">
        <label><input type="checkbox" id="ruleEnabled" ${rule.enabled ? 'checked' : ''}> включено</label>
        <label><input type="checkbox" id="ruleStop" ${rule.stop ? 'checked' : ''}> стоп после правила</label>
      </div>
    </div>
    <div class="field">
      <label>Условия — когда прогнозировать</label>
      ${renderGroupHTML(rule.conditions, [], true)}
      <div class="field-hint mt">«И» — все условия, «ИЛИ» — любое из условий. Группы можно вкладывать.</div>
    </div>
    <div class="field">
      <label>Действие — что прогнозировать</label>
      <select id="ruleType">
        ${options.map(o => '<option value="' + o[0] + '"' +
          (type === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('')}
      </select>
    </div>
    <div id="actionExtra">${renderActionExtra(action)}</div>`;
  const typeEl = $('ruleType');
  if (typeEl && typeEl.value !== type) typeEl.value = type;
  $('btnRuleDelete').style.visibility = state.ctor.editingIndex >= 0 ? 'visible' : 'hidden';
}

function applyMetricDefaults(node, metricId) {
  const metric = metricById(metricId);
  node.metric = metricId;
  node.args = Object.assign({}, (metric && metric.args) || {});
  const operators = ((state.ctor.catalog.operators || {})[metric.type] || []);
  if (!operators.some(o => o[0] === node.op)) {
    node.op = operators.length ? operators[0][0] : 'gt';
  }
  delete node.value_metric;
  delete node.value_args;
  delete node.value2;
  node.value = defaultValueFor(metric);
}

function openRuleEditor(index, prefill) {
  if (!state.ctor.catalog) { loadConstructor(); }
  state.ctor.attachNotice = '';
  if (index >= 0 && state.ctor.rules[index]) {
    state.ctor.editing = JSON.parse(JSON.stringify(state.ctor.rules[index]));
    if (prefill && prefill.append && Array.isArray(prefill.conditions) && prefill.conditions.length) {
      if (!state.ctor.editing.conditions ||
          !Array.isArray(state.ctor.editing.conditions.conditions)) {
        state.ctor.editing.conditions = { logic: 'and', conditions: [] };
      }
      const root = state.ctor.editing.conditions;
      prefill.conditions.forEach(cond => {
        root.conditions.push(JSON.parse(JSON.stringify(cond)));
      });
      state.ctor.attachNotice = prefill.notice || 'Условие добавлено. Проверьте правило и сохраните.';
    }
  } else {
    state.ctor.editing = newRuleTemplate();
    if (prefill) {
      if (prefill.name) state.ctor.editing.name = prefill.name;
      if (Array.isArray(prefill.conditions) && prefill.conditions.length) {
        state.ctor.editing.conditions = {
          logic: 'and',
          conditions: JSON.parse(JSON.stringify(prefill.conditions)),
        };
      }
      if (prefill.action) {
        Object.assign(state.ctor.editing.action, prefill.action);
      }
    }
    index = -1;
  }
  state.ctor.editingIndex = index;
  $('ruleModalTitle').textContent = index >= 0 ? 'Правило' : 'Новое правило';
  renderRuleEditor();
  $('ruleModal').classList.remove('hidden');
}

function closeRuleEditor() {
  $('ruleModal').classList.add('hidden');
  state.ctor.editing = null;
  state.ctor.editingIndex = -1;
  state.ctor.attachNotice = '';
}

function onEditorInput(event) {
  const rule = state.ctor.editing;
  if (!rule) return;
  const target = event.target;
  if (!target) return;
  if (target.id === 'ruleName') { rule.name = target.value; return; }
  if (target.id === 'rulePriority') { rule.priority = num(target.value); return; }
  if (target.id === 'ruleConf') {
    rule.action.confidence = num(target.value) / 100;
    const label = $('ruleConfVal');
    if (label) label.textContent = target.value + '%';
    return;
  }
  if (target.id === 'ruleThreshold') { rule.action.threshold = num(target.value); return; }
  if (target.id === 'ruleHandicap') { rule.action.value = num(target.value); return; }
  if (target.dataset && target.dataset.arg && target.dataset.path) {
    const node = nodeAt(rule, parsePath(target.dataset.path));
    if (node) {
      node.args = node.args || {};
      node.args[target.dataset.arg] = target.value;
    }
    return;
  }
  if (target.dataset && target.dataset.path && target.dataset.value !== undefined) {
    const node = nodeAt(rule, parsePath(target.dataset.path));
    if (node) node.value = target.value;
    return;
  }
  if (target.dataset && target.dataset.path && target.dataset.value2 !== undefined) {
    const node = nodeAt(rule, parsePath(target.dataset.path));
    if (node) node.value2 = target.value;
  }
}

function onEditorChange(event) {
  const rule = state.ctor.editing;
  if (!rule) return;
  const target = event.target;
  if (!target) return;
  if (target.id === 'ruleType') {
    const next = target.value;
    rule.action.type = next;
    const isTeam = ctorIsTeam();
    if (isTeam) {
      rule.action.targets = ['match'];
    } else if (!Array.isArray(rule.action.targets) || !rule.action.targets.length) {
      rule.action.targets = [1];
    }
    rule.action.side = 'auto';
    if (next === 'total' && !num(rule.action.threshold)) {
      rule.action.threshold = num((state.ctor.catalog || {}).default_total) ||
        num(ctorProfile().default_total) || (isTeam ? 2.5 : 18.5);
    }
    if (next === 'handicap' &&
        (rule.action.value === undefined || rule.action.value === null)) {
      rule.action.value = 0;
    }
    renderRuleEditor();
    return;
  }
  if (target.id === 'ruleSide') { rule.action.side = target.value; return; }
  if (target.id === 'ruleEnabled') { rule.enabled = target.checked; return; }
  if (target.id === 'ruleStop') { rule.stop = target.checked; return; }
  if (target.dataset && target.dataset.metric && target.dataset.path) {
    const node = nodeAt(rule, parsePath(target.dataset.path));
    if (node) { applyMetricDefaults(node, target.value); renderRuleEditor(); }
    return;
  }
  if (target.dataset && target.dataset.op && target.dataset.path) {
    const node = nodeAt(rule, parsePath(target.dataset.path));
    if (node) {
      node.op = target.value;
      if (node.op !== 'between') delete node.value2;
      renderRuleEditor();
    }
    return;
  }
  if (target.dataset && target.dataset.valueMetric && target.dataset.path) {
    const node = nodeAt(rule, parsePath(target.dataset.path));
    if (node) { node.value_metric = target.value; renderRuleEditor(); }
    return;
  }
  if (target.dataset && target.dataset.valueMetricToggle && target.dataset.path) {
    const node = nodeAt(rule, parsePath(target.dataset.path));
    if (node) {
      if (target.checked) {
        const metrics = (state.ctor.catalog.metrics || []);
        node.value_metric = metrics.length ? metrics[0].id : '';
        node.value_args = {};
      } else {
        delete node.value_metric;
        delete node.value_args;
      }
      renderRuleEditor();
    }
    return;
  }
  if (target.dataset && target.dataset.path && target.dataset.value !== undefined) {
    const node = nodeAt(rule, parsePath(target.dataset.path));
    if (node) node.value = target.value;
  }
}

function onEditorClick(event) {
  const rule = state.ctor.editing;
  if (!rule) return;
  const logicBtn = event.target.closest('[data-logic]');
  if (logicBtn) {
    const holder = logicBtn.closest('[data-logic-path]');
    if (holder) {
      const group = groupAt(rule, parsePath(holder.dataset.logicPath));
      if (group) { group.logic = logicBtn.dataset.logic; renderRuleEditor(); }
    }
    return;
  }
  const addCond = event.target.closest('[data-add-cond]');
  if (addCond) {
    const group = groupAt(rule, parsePath(addCond.dataset.addCond));
    if (group) {
      group.conditions = group.conditions || [];
      group.conditions.push(defaultCondition());
      renderRuleEditor();
    }
    return;
  }
  const addGroup = event.target.closest('[data-add-group]');
  if (addGroup) {
    const group = groupAt(rule, parsePath(addGroup.dataset.addGroup));
    if (group) {
      group.conditions = group.conditions || [];
      group.conditions.push({ logic: 'or', conditions: [defaultCondition()] });
      renderRuleEditor();
    }
    return;
  }
  const delCond = event.target.closest('[data-del-cond]');
  if (delCond) {
    deleteAt(rule, parsePath(delCond.dataset.delCond));
    renderRuleEditor();
    return;
  }
  const delGroup = event.target.closest('[data-del-group]');
  if (delGroup) {
    deleteAt(rule, parsePath(delGroup.dataset.delGroup));
    renderRuleEditor();
    return;
  }
  const targetBtn = event.target.closest('[data-target]');
  if (targetBtn) {
    const value = targetBtn.dataset.target;
    let targets = (rule.action.targets || []).slice();
    if (value === 'auto') {
      targets = ['auto'];
    } else {
      targets = targets.filter(t => t !== 'auto');
      const number = parseInt(value, 10);
      if (targets.indexOf(number) >= 0) targets = targets.filter(t => t !== number);
      else targets.push(number);
      targets = Array.from(new Set(targets)).sort((a, b) => a - b);
      if (!targets.length) targets = [1];
    }
    rule.action.targets = targets;
    renderRuleEditor();
  }
}

function syncEditorFromDOM(rule) {
  const nameEl = $('ruleName');
  if (nameEl) rule.name = nameEl.value;
  const priorityEl = $('rulePriority');
  if (priorityEl) rule.priority = num(priorityEl.value);
  const typeEl = $('ruleType');
  if (typeEl) rule.action.type = typeEl.value;
  const sideEl = $('ruleSide');
  if (sideEl) rule.action.side = sideEl.value;
  const thresholdEl = $('ruleThreshold');
  if (thresholdEl) rule.action.threshold = num(thresholdEl.value);
  const handicapEl = $('ruleHandicap');
  if (handicapEl) rule.action.value = num(handicapEl.value);
  const confEl = $('ruleConf');
  if (confEl) rule.action.confidence = num(confEl.value) / 100;
  const enabledEl = $('ruleEnabled');
  if (enabledEl) rule.enabled = enabledEl.checked;
  const stopEl = $('ruleStop');
  if (stopEl) rule.stop = stopEl.checked;
  // аргументы и значения условий
  qsa('#ruleModalBody .cond-row').forEach(row => {
    const node = nodeAt(rule, parsePath(row.dataset.path));
    if (!node) return;
    const metricSel = row.querySelector('[data-metric]');
    if (metricSel) node.metric = metricSel.value;
    row.querySelectorAll('[data-arg]').forEach(el => {
      node.args = node.args || {};
      node.args[el.dataset.arg] = el.value;
    });
    const opSel = row.querySelector('[data-op]');
    if (opSel) node.op = opSel.value;
    const valueMetricSel = row.querySelector('[data-value-metric]');
    if (valueMetricSel) {
      node.value_metric = valueMetricSel.value;
    } else {
      const valueEl = row.querySelector('[data-value]');
      if (valueEl) {
        node.value = valueEl.type === 'checkbox' ? valueEl.checked : valueEl.value;
      }
      const value2El = row.querySelector('[data-value2]');
      if (value2El) node.value2 = value2El.value;
    }
  });
}

function saveRuleEditor() {
  const rule = state.ctor.editing;
  if (!rule) return;
  syncEditorFromDOM(rule);
  const rootConditions = (rule.conditions && rule.conditions.conditions) || [];
  if (!rootConditions.length) {
    toast('Добавьте хотя бы одно условие', 'error');
    return;
  }
  if (!rule.name || !rule.name.trim()) rule.name = 'Правило ' + ((state.ctor.rules || []).length + 1);
  const rules = JSON.parse(JSON.stringify(state.ctor.rules || []));
  if (state.ctor.editingIndex >= 0) rules[state.ctor.editingIndex] = rule;
  else rules.push(rule);
  const res = saveRules(rules, null, 'Правило сохранено');
  if (res) closeRuleEditor();
}

function deleteEditingRule() {
  if (state.ctor.editingIndex < 0) { closeRuleEditor(); return; }
  if (!confirm('Удалить правило?')) return;
  const rules = (state.ctor.rules || []).slice();
  rules.splice(state.ctor.editingIndex, 1);
  const res = saveRules(rules, null, 'Правило удалено');
  if (res) closeRuleEditor();
}

function onRulesListClick(event) {
  const btn = event.target.closest('[data-ract]');
  if (!btn) return;
  const index = num(btn.dataset.index);
  const action = btn.dataset.ract;
  const rules = (state.ctor.rules || []).slice();
  if (action === 'edit') { openRuleEditor(index); return; }
  if (action === 'toggle') {
    rules[index].enabled = !rules[index].enabled;
    saveRules(rules, null, rules[index].enabled ? 'Правило включено' : 'Правило выключено');
    return;
  }
  if (action === 'dup') {
    const copy = JSON.parse(JSON.stringify(rules[index]));
    copy.id = 'r_' + Math.random().toString(36).slice(2, 12);
    copy.name = (copy.name || 'Правило') + ' (копия)';
    rules.splice(index + 1, 0, copy);
    saveRules(rules, null, 'Правило скопировано');
    return;
  }
  if (action === 'del') {
    if (!confirm('Удалить правило?')) return;
    rules.splice(index, 1);
    saveRules(rules, null, 'Правило удалено');
    return;
  }
  if (action === 'up' && index > 0) {
    const tmp = rules[index - 1]; rules[index - 1] = rules[index]; rules[index] = tmp;
    saveRules(rules, null, null);
    return;
  }
  if (action === 'down' && index < rules.length - 1) {
    const tmp = rules[index + 1]; rules[index + 1] = rules[index]; rules[index] = tmp;
    saveRules(rules, null, null);
  }
}

function presetCategories() {
  const categories = [];
  (state.ctor.presets || []).forEach(preset => {
    const category = preset.category || 'Другое';
    if (categories.indexOf(category) < 0) categories.push(category);
  });
  return categories;
}

function renderPresetList() {
  const list = $('presetList');
  if (!list) return;
  const query = (state.ctor.presetQuery || '').trim().toLowerCase();
  const category = state.ctor.presetCat || '';
  const items = [];
  (state.ctor.presets || []).forEach((preset, index) => {
    if (category && (preset.category || 'Другое') !== category) return;
    if (query) {
      const haystack = [preset.name, preset.description, preset.category,
        preset.source].join(' ').toLowerCase();
      if (haystack.indexOf(query) < 0) return;
    }
    items.push({ preset, index });
  });
  qsa('#presetCats .chip').forEach(chip => {
    chip.classList.toggle('active', (chip.dataset.presetCat || '') === category);
  });
  list.innerHTML = items.length ? items.map(item =>
    '<div class="preset-card" data-preset="' + item.index + '">' +
    '<div class="preset-top">' +
    '<span class="preset-badge">' + esc(item.preset.category || 'Шаблон') + '</span>' +
    '<span class="preset-plus">Добавить +</span></div>' +
    '<h4>' + esc(item.preset.name) + '</h4>' +
    '<p>' + esc(item.preset.description || '') + '</p>' +
    (item.preset.source ? '<div class="preset-src">' +
      esc(item.preset.source) + '</div>' : '') +
    '</div>').join('')
    : '<div class="empty">Ничего не найдено. Измените запрос или категорию.</div>';
}

function openPresets() {
  const body = $('presetBody');
  const presets = state.ctor.presets || [];
  if (!presets.length) {
    body.innerHTML = '<div class="empty">Шаблонов нет</div>';
    $('presetModal').classList.remove('hidden');
    return;
  }
  if (state.ctor.presetCat == null) state.ctor.presetCat = '';
  if (state.ctor.presetQuery == null) state.ctor.presetQuery = '';
  const categories = presetCategories();
  body.innerHTML =
    '<div class="preset-tools">' +
    '<input class="input" id="presetSearch" type="search" ' +
    'placeholder="Поиск: тотал, форма, очные, П1…" value="' +
    esc(state.ctor.presetQuery) + '">' +
    '<div class="chips wrap preset-cats" id="presetCats">' +
    '<button class="chip" data-preset-cat="">Все ' + num(presets.length) +
    '</button>' +
    categories.map(category =>
      '<button class="chip" data-preset-cat="' + esc(category) + '">' +
      esc(category) + ' ' +
      num(presets.filter(p => (p.category || 'Другое') === category).length) +
      '</button>').join('') +
    '</div></div>' +
    '<div id="presetList"></div>' +
    '<div class="preset-note">Шаблоны для вида «' + esc(state.sportName) +
    '» собраны из публичных стратегий и рыночных ориентиров. ' +
    'Это стартовые точки: после добавления проверьте правило кнопкой ' +
    '«Тест на линии», а свою историю — во вкладке «Анализ».</div>';
  renderPresetList();
  $('presetModal').classList.remove('hidden');
}

function addPreset(index) {
  const preset = (state.ctor.presets || [])[index];
  if (!preset) return;
  const rule = JSON.parse(JSON.stringify(preset.rule || {}));
  rule.id = 'r_' + Math.random().toString(36).slice(2, 12);
  rule.enabled = true;
  rule.priority = 100;
  rule.stop = false;
  const res = saveRules((state.ctor.rules || []).concat([rule]), null, 'Шаблон добавлен');
  if (res) {
    $('presetModal').classList.add('hidden');
    openRuleEditor((state.ctor.rules || []).length - 1);
  }
}

function renderTestResults(res) {
  const box = $('ctorTest');
  box.classList.remove('hidden');
  if (!res || !res.ok) {
    box.innerHTML = '<div class="card-head"><h3>Проверка на линии</h3></div>' +
      '<div class="empty">' + esc((res && res.error) || 'Ошибка проверки') + '</div>';
    return;
  }
  if (!res.items || !res.items.length) {
    box.innerHTML = '<div class="card-head"><h3>Проверка на линии</h3></div>' +
      '<div class="empty">Нет подходящих матчей в линии</div>';
    return;
  }
  const items = res.items.map(item => {
    const fired = (item.fired || []).map(f =>
      '<div class="test-line ok">✔ ' + esc(f.name) + '</div>' +
      (f.details || []).slice(0, 3).map(d =>
        '<div class="test-sub">· ' + esc(d) + '</div>').join('')).join('');
    const noFired = (!item.fired || !item.fired.length)
      ? '<div class="test-line">Правила не сработали</div>' : '';
    const skipped = item.skip
      ? '<div class="test-line bad">⏭ Пропуск матча: ' + esc(item.skip.rule) + '</div>' : '';
    const predictions = (item.predictions || []).map(p =>
      '<div class="test-line"><b>' + esc(p.label) + '</b>: ' + esc(p.verdict) +
      ' · уверенность ' + num(p.confidence) + '%</div>' +
      '<div class="test-sub">' + esc(p.reason) + '</div>').join('');
    return `<div class="test-item">
      <div class="test-title">${esc(item.team1)} — ${esc(item.team2)}</div>
      <div class="test-sub">${esc(item.league || '')} · ${esc(item.date || '')} ·
        очных: ${num(item.h2h)} · игр: ${num(item.recent1)}/${num(item.recent2)}</div>
      ${fired}${noFired}${skipped}${predictions}</div>`;
  }).join('');
  box.innerHTML = '<div class="card-head"><h3>Проверка на линии</h3>' +
    '<span class="muted">матчей: ' + num(res.checked) + '</span></div>' + items;
}

function testRules() {
  loader(true);
  const box = $('ctorTest');
  box.classList.remove('hidden');
  box.innerHTML = '<div class="card-head"><h3>Проверка на линии</h3></div>' +
    '<div class="empty">Проверяю матчи…</div>';
  setTimeout(() => {
    try {
      const res = call('testConstructor',
        JSON.stringify({ rules: state.ctor.rules, sport: state.ctor.sport || state.sport }), 5);
      renderTestResults(res);
    } finally {
      loader(false);
    }
  }, 40);
}

function importRules() {
  $('importText').value = '';
  $('importModal').classList.remove('hidden');
}

function applyImport() {
  let data;
  try {
    data = JSON.parse($('importText').value);
  } catch (e) {
    toast('Некорректный JSON', 'error');
    return;
  }
  const rules = Array.isArray(data) ? data : (data && data.rules);
  if (!Array.isArray(rules)) {
    toast('Не найден список правил', 'error');
    return;
  }
  const res = saveRules(rules, null, 'Правила импортированы');
  if (res) $('importModal').classList.add('hidden');
}

/* ================= АНАЛИЗАТОР ================= */

state.an = {
  data: null,
  filter: { kind: 'all', target: '', min_group: 3, min_lift: 20, sport: '' },
  expanded: { failure: false, success: false },
};

const AN_VISIBLE = 5;
const AN_INVERSE = {
  gt: 'lte', gte: 'lt', lt: 'gte', lte: 'gt',
  eq: 'neq', neq: 'eq', is: 'neq',
  contains: 'not_contains', not_contains: 'contains',
  in: 'not_in', not_in: 'in',
};

function fmtShare(value) {
  return Math.round(num(value)) + '%';
}

function refreshAnalyzer(keepExpanded) {
  if (!bridge) return;
  const data = call('analyzer', JSON.stringify(state.an.filter));
  if (!data) return;
  state.an.data = data;
  if (!keepExpanded) {
    state.an.expanded.failure = false;
    state.an.expanded.success = false;
  }
  renderAnalyzer();
}

function analyzerRowHTML(row, group, index) {
  const fail = group === 'failure';
  const share = fail ? row.loss_share : row.win_share;
  const other = fail ? row.win_share : row.loss_share;
  const hits = fail ? row.loss_hits : row.win_hits;
  const total = fail ? row.loss_n : row.win_n;
  const width = Math.min(100, Math.max(3, num(share)));
  const examples = (row.examples || [])
    .slice(0, 2)
    .map(item => {
      const parts = ['<b>' + esc(item.teams) + '</b>'];
      if (item.verdict) parts.push(esc(item.verdict));
      if (item.score) parts.push(esc(item.score));
      if (item.total !== null && item.total !== undefined && item.total !== '') {
        parts.push('тотал ' + esc(item.total));
      }
      return parts.join(' · ');
    })
    .join('<br>');
  const extra = (row.examples || []).length > 2
    ? ' <span class="an-share-note">ещё ' + ((row.examples || []).length - 2) + '</span>'
    : '';
  return `<div class="an-row">
    <div class="an-row-head">
      <div class="an-title">${esc(row.text)}</div>
      <div class="an-share ${fail ? 'bad' : 'ok'}">${fmtShare(share)}</div>
    </div>
    <div class="an-bar"><span class="${fail ? 'bad' : 'ok'}" style="width:${width}%"></span></div>
    <div class="an-meta">${fail ? 'неудачи' : 'удачи'} ${hits} из ${total} · ${fail ? 'удачи' : 'неудачи'} ${fmtShare(other)} · разница ${num(Math.abs(row.lift))} п.п. · покрытие ${num(row.coverage)}%</div>
    ${examples ? `<div class="an-ex">${examples}${extra}</div>` : ''}
    ${fail ? '<div class="an-reco">Чтобы не ловить такие матчи, добавьте обратное условие в правило.</div>' : ''}
    <div class="an-actions">
      <button class="btn btn-ghost btn-sm" data-an-add="${group}" data-an-index="${index}">${fail ? 'Исключить в правиле' : 'Как в удачах'}</button>
    </div>
  </div>`;
}

function renderAnLimits(rows) {
  const top = (rows || []).slice(0, 3);
  $('anLimitCard').classList.toggle('hidden', !top.length);
  $('anLimitCount').textContent = top.length;
  $('anLimits').innerHTML = top.map((row, index) =>
    `<div class="an-limit">
      <div class="an-limit-text">${esc(row.text)}</div>
      <div class="an-limit-meta">встречалось при неудачах в ${fmtShare(row.loss_share)}
        случаев · разница ${num(Math.abs(row.lift))} п.п.</div>
      <button class="btn btn-ghost btn-sm" data-an-add="failure" data-an-index="${index}">Исключить в правиле</button>
    </div>`).join('');
}

function renderAnList(group, rows) {
  const fail = group === 'failure';
  const box = $(fail ? 'anFailures' : 'anSuccesses');
  const count = $(fail ? 'anFailCount' : 'anSuccCount');
  const more = $(fail ? 'btnAnFailMore' : 'btnAnSuccMore');
  count.textContent = rows.length;
  const expanded = !!state.an.expanded[group];
  const visible = expanded ? rows : rows.slice(0, AN_VISIBLE);
  box.innerHTML = visible.length
    ? visible.map((row, i) => analyzerRowHTML(row, group, i)).join('')
    : `<div class="an-empty">${fail
        ? 'Выраженных признаков неудач не найдено.'
        : 'Выраженных признаков удач не найдено.'}</div>`;
  more.classList.toggle('hidden', rows.length <= AN_VISIBLE);
  more.textContent = expanded
    ? 'Свернуть'
    : 'Показать все (' + rows.length + ')';
}

function renderAnCombos(combos) {
  const box = $('anCombos');
  const groups = [
    ['failure', 'Неудачи', combos.failure || [], 'bad'],
    ['success', 'Удачи', combos.success || [], 'ok'],
  ];
  const parts = [];
  groups.forEach(([group, title, rows, tone]) => {
    if (!rows.length) return;
    parts.push(`<div class="an-sub">${title}</div>`);
    rows.forEach((combo, i) => {
      const texts = (combo.texts || [combo.text]);
      const share = group === 'failure' ? combo.loss_share : combo.win_share;
      const hits = group === 'failure' ? combo.loss_hits : combo.win_hits;
      const total = group === 'failure' ? combo.loss_n : combo.win_n;
      parts.push(`<div class="an-row">
        <div class="an-row-head">
          <div class="an-title">${texts.map(esc).join(' <span class="an-share-note">И</span> ')}</div>
          <div class="an-share ${tone}">${fmtShare(share)}</div>
        </div>
        <div class="an-bar"><span class="${tone}" style="width:${Math.min(100, Math.max(3, num(share)))}%"></span></div>
        <div class="an-meta">${group === 'failure' ? 'неудачи' : 'удачи'} ${hits} из ${total} · разница ${num(Math.abs(combo.lift))} п.п.</div>
        <div class="an-actions">
          <button class="btn btn-ghost btn-sm" data-an-combo="${group}" data-an-index="${i}">В конструктор</button>
        </div>
      </div>`);
    });
  });
  $('anCombosCard').classList.toggle('hidden', !parts.length);
  box.innerHTML = parts.join('');
}

function renderAnMeans(means) {
  const box = $('anMeans');
  $('anMeansCard').classList.toggle('hidden', !means.length);
  box.innerHTML = means.map(item => {
    const unit = item.unit || '';
    const delta = num(item.delta);
    return `<div class="an-mean">
      <div class="an-mean-label">${esc(item.label || item.metric)}</div>
      <div class="an-mean-val">
        <span class="ok">${item.win_mean}${unit}</span>
        <span class="muted"> / </span>
        <span class="bad">${item.loss_mean}${unit}</span>
        <span class="an-share-note">${delta > 0 ? '+' : ''}${delta}${unit}</span>
      </div>
    </div>`;
  }).join('');
}

function renderAnalyzer() {
  const data = state.an.data || {};
  const obs = data.observations || {};
  const total = num(obs.total);
  $('anObs').textContent = total;
  $('anWins').textContent = num(obs.wins);
  $('anLosses').textContent = num(obs.losses);
  $('anCoverage').textContent = num(obs.with_stats);
  const sportValue = (data.options || {}).sport || '';
  const sportLabel = !sportValue ? 'все виды спорта'
    : (sportById(sportValue) ? sportName(sportValue) : sportValue);
  $('anMeta').textContent = data.generated_at
    ? 'Обновлено ' + data.generated_at + ' · ' + sportLabel
    : 'Что общего у удачных и неудачных прогнозов · ' + sportLabel;

  const hint = data.hint
    || (data.ok === false ? 'Ошибка анализа: ' + (data.error || 'неизвестная') : '');
  $('anHintCard').classList.toggle('hidden', !hint);
  $('anHint').textContent = hint;

  renderAnList('failure', data.failure || []);
  renderAnLimits(data.failure || []);
  renderAnList('success', data.success || []);

  const combos = data.combos || { failure: [], success: [] };
  renderAnCombos(combos);

  renderAnMeans(data.means || []);
  updateAnalyzerSportUI();
}

function analyzerRow(group, index) {
  const data = state.an.data || {};
  const rows = data[group] || [];
  return rows[index] || null;
}

function analyzerToConstructor(conditions, invert, name, texts) {
  if (!Array.isArray(conditions) || !conditions.length) return;
  const prepared = JSON.parse(JSON.stringify(conditions)).map(cond => {
    if (invert) {
      const inverse = AN_INVERSE[cond.op];
      if (inverse) cond.op = inverse;
    }
    return cond;
  });
  const sport = (((state.an.data || {}).options || {}).sport) || state.sport;
  state.attach = {
    conditions: prepared,
    invert: !!invert,
    name: name || '',
    texts: (Array.isArray(texts) && texts.length) ? texts : [name || 'Условие анализатора'],
    sport: sport,
    rules: [],
    loading: true,
    error: '',
  };
  $('attachBody').innerHTML = '';
  $('attachModal').classList.remove('hidden');
  loadAttachRules(sport);
}

/* ================= ДОБАВЛЕНИЕ УСЛОВИЯ В ПРАВИЛО ================= */

function bindAttach() {
  ['btnCloseAttach', 'btnAttachCancel'].forEach(id => {
    const el = $(id);
    if (el) el.addEventListener('click', closeAttach);
  });
  const body = $('attachBody');
  if (!body) return;
  body.addEventListener('click', e => {
    const newBtn = e.target.closest('[data-attach-new]');
    if (newBtn) { attachAsNew(); return; }
    const ruleBtn = e.target.closest('[data-attach-rule]');
    if (ruleBtn) { attachToRule(num(ruleBtn.dataset.attachRule)); return; }
    const sportBtn = e.target.closest('[data-attach-sport]');
    if (sportBtn) { loadAttachRules(sportBtn.dataset.attachSport); return; }
  });
}

function closeAttach() {
  const modal = $('attachModal');
  if (modal) modal.classList.add('hidden');
  state.attach = null;
}

function loadAttachRules(sport) {
  const a = state.attach;
  if (!a) return;
  a.sport = sport || a.sport || state.sport;
  a.loading = true;
  a.error = '';
  renderAttachBody();
  try {
    let res = null;
    const sameSport = a.sport === (state.ctor.sport || state.sport);
    if (sameSport && (state.ctor.rules || []).length) {
      res = { ok: true, rules: state.ctor.rules, catalog: state.ctor.catalog };
    } else {
      res = call('constructor', a.sport);
    }
    if (res && res.ok) {
      a.rules = res.rules || [];
      a.catalog = res.catalog || null;
    } else {
      a.error = 'Не удалось загрузить правила этого вида спорта.';
      a.rules = [];
      a.catalog = null;
    }
  } finally {
    a.loading = false;
    renderAttachBody();
  }
}

function attachRuleCount(rule) {
  const root = (rule && rule.conditions) || {};
  return Array.isArray(root.conditions) ? root.conditions.length : 0;
}

function attachCompatibility(attach) {
  if (!attach || !attach.catalog) return { ok: true, missing: [] };
  const known = {};
  (attach.catalog.metrics || []).forEach(metric => { known[metric.id] = true; });
  const missing = (attach.conditions || [])
    .filter(cond => cond && cond.metric && !known[cond.metric]);
  return { ok: !missing.length, missing: missing };
}

function renderAttachBody() {
  const a = state.attach;
  const body = $('attachBody');
  if (!a || !body) return;
  const chips = sportList().map(item =>
    '<button class="chip' + (item.id === a.sport ? ' active' : '') +
    '" data-attach-sport="' + esc(item.id) + '">' + esc(item.icon || '') + ' ' +
    esc(item.short || item.name) + '</button>').join('');
  const preview = a.texts.map(text => '<li>' + esc(text) + '</li>').join('');
  const compat = attachCompatibility(a);
  let rulesHTML = '';
  if (a.loading) {
    rulesHTML = '<div class="empty">Загружаю правила…</div>';
  } else if (a.error) {
    rulesHTML = '<div class="empty bad">' + esc(a.error) + '</div>';
  } else if (!compat.ok) {
    rulesHTML = '<div class="empty bad">Условие относится к другому виду спорта: ' +
      esc(compat.missing.map(item => item.metric).join(', ')) +
      '. Выберите вид спорта, из которого получено условие.</div>';
  } else if (!a.rules.length) {
    rulesHTML = '<div class="empty">У этого вида спорта пока нет правил — создайте первое.</div>';
  } else {
    rulesHTML = a.rules.map((rule, index) => {
      const skip = (rule.action || {}).type === 'skip';
      return `<button class="attach-rule ${rule.enabled ? '' : 'off'}" data-attach-rule="${index}">
        <div class="attach-rule-top">
          <span class="attach-rule-name">${esc(rule.name || ('Правило ' + (index + 1)))}</span>
          <span class="badge ${rule.enabled ? 'ok' : ''}">${rule.enabled ? 'вкл' : 'выкл'}</span>
        </div>
        <div class="attach-rule-action">${esc(rule.action_text || rule.summary || '')}</div>
        <div class="attach-rule-meta">условий: ${attachRuleCount(rule)} · приоритет ${num(rule.priority)}${rule.stop ? ' · стоп' : ''}</div>
        ${skip ? '<div class="attach-rule-note">Правило-пропуск: условие сузит фильтр пропуска.</div>' : ''}
      </button>`;
    }).join('');
  }
  const actionsHTML = compat.ok
    ? `<button class="btn btn-primary btn-block mt" data-attach-new="1">＋ Создать новое правило</button>
       <div class="attach-list-head">Или добавить в существующее
         <span class="badge">${a.loading ? '…' : a.rules.length}</span></div>
       <div class="attach-list">${rulesHTML}</div>`
    : `<div class="doc-callout warn mt">${rulesHTML}</div>`;
  body.innerHTML = `
    <div class="attach-preview">
      <div class="attach-label">${a.invert
        ? 'Условие будет инвертировано — исключаем проблемный признак'
        : 'Условие будет добавлено без изменений'}</div>
      <ul>${preview}</ul>
    </div>
    <div class="field">
      <label>Вид спорта правил</label>
      <div class="chips wrap">${chips}</div>
      <div class="field-hint">Правила хранятся отдельно для каждого вида спорта.</div>
    </div>
    ${actionsHTML}`;
}

function ensureSportThen(sport, callback) {
  if (sport && sport !== state.sport) {
    setActiveSport(sport);
    if (state.sport !== sport) {
      toast('Не удалось переключить вид спорта', 'error');
      return;
    }
  }
  if (!state.ctor.catalog) loadConstructor();
  callback();
}

function attachAsNew() {
  const a = state.attach;
  if (!a) return;
  const data = {
    sport: a.sport,
    conditions: JSON.parse(JSON.stringify(a.conditions)),
    invert: a.invert,
    name: a.name,
  };
  closeAttach();
  ensureSportThen(data.sport, () => {
    const prefix = data.invert ? 'Не как в неудачах: ' : 'Как в удачах: ';
    navigate('constructor');
    openRuleEditor(-1, {
      name: prefix + (data.name || 'условие анализатора'),
      conditions: data.conditions,
    });
    toast('Создано новое правило из анализатора', 'ok');
  });
}

function attachRuleKey(cond) {
  return [
    cond.metric || '',
    JSON.stringify(cond.args || {}),
    cond.op || '',
    JSON.stringify(cond.value),
    JSON.stringify(cond.value2),
    cond.value_metric || '',
    JSON.stringify(cond.value_args || {}),
  ].join('|');
}

function attachToRule(index) {
  const a = state.attach;
  if (!a) return;
  const chosen = (a.rules || [])[index];
  if (!chosen) return;
  const data = {
    sport: a.sport,
    ruleID: chosen.id,
    ruleName: chosen.name || '',
    conditions: JSON.parse(JSON.stringify(a.conditions)),
    invert: a.invert,
  };
  closeAttach();
  ensureSportThen(data.sport, () => {
    const rules = state.ctor.rules || [];
    const idx = rules.findIndex(rule => rule.id === data.ruleID);
    if (idx < 0) {
      navigate('constructor');
      toast('Правило не найдено — список мог измениться', 'error');
      return;
    }
    const rule = rules[idx];
    const root = (rule.conditions && Array.isArray(rule.conditions.conditions))
      ? rule.conditions.conditions : [];
    const known = root.map(attachRuleKey);
    const add = data.conditions.filter(cond => known.indexOf(attachRuleKey(cond)) < 0);
    navigate('constructor');
    if (!add.length) {
      toast('Такое условие уже есть в правиле «' + (rule.name || '') + '»', 'error');
      return;
    }
    state.ctor.highlightId = rule.id;
    openRuleEditor(idx, {
      append: true,
      conditions: add,
      notice: data.invert
        ? 'Добавлено условие из анализатора с инверсией (исключаем неудачи). Проверьте правило и сохраните.'
        : 'Добавлено условие из анализатора. Проверьте правило и сохраните.',
    });
    toast('Условие добавлено в правило «' + (rule.name || '') + '»', 'ok');
  });
}

/* ================= ДОКУМЕНТАЦИЯ ================= */

function docData() {
  return window.APP_DOCS || { groups: [], kinds: [], articles: [] };
}

function docGroups() { return docData().groups || []; }
function docKinds() { return docData().kinds || []; }
function docArticles() { return docData().articles || []; }

function docById(id) {
  return docArticles().find(article => article.id === id) || null;
}

function docGroupTitle(id) {
  const group = docGroups().find(item => item.id === id);
  return group ? group.title : '';
}

function docKindTitle(id) {
  const kind = docKinds().find(item => item.id === id);
  return kind ? kind.title : 'Статья';
}

function bindDocs() {
  const search = $('docsSearch');
  if (search) search.addEventListener('input', e => {
    state.docs.query = e.target.value;
    renderDocHome();
  });

  const groups = $('docsGroups');
  if (groups) groups.addEventListener('click', e => {
    const btn = e.target.closest('[data-doc-group]');
    if (!btn) return;
    state.docs.group = btn.dataset.docGroup || 'all';
    renderDocHome();
  });

  const kinds = $('docsKinds');
  if (kinds) kinds.addEventListener('click', e => {
    const btn = e.target.closest('[data-doc-kind]');
    if (!btn) return;
    state.docs.kind = btn.dataset.docKind || 'all';
    renderDocHome();
  });

  ['docsList', 'docsQuick'].forEach(id => {
    const box = $(id);
    if (!box) return;
    box.addEventListener('click', e => {
      const btn = e.target.closest('[data-doc-open]');
      if (!btn) return;
      openDoc(btn.dataset.docOpen, btn.dataset.docAnchor || '');
    });
  });

  const home = $('btnDocsHome');
  if (home) home.addEventListener('click', closeDocArticle);

  const article = $('docsArticle');
  if (article) {
    article.addEventListener('click', e => {
      const back = e.target.closest('[data-doc-back]');
      if (back) { closeDocArticle(); return; }
      const section = e.target.closest('[data-doc-section]');
      if (section) { scrollDocSection(section.dataset.docSection); return; }
      const open = e.target.closest('[data-doc-open]');
      if (open) { openDoc(open.dataset.docOpen, open.dataset.docAnchor || ''); return; }
      const sport = e.target.closest('[data-doc-metric-sport]');
      if (sport) {
        state.docs.metricSport = sport.dataset.docMetricSport || state.sport;
        state.docs.metricQuery = '';
        renderDocMetrics();
      }
    });
    article.addEventListener('input', e => {
      if (e.target && e.target.id === 'docMetricSearch') {
        state.docs.metricQuery = e.target.value;
        renderDocMetricsList();
      }
    });
  }
}

function openDoc(id, anchor) {
  if (!id || !docById(id)) return;
  closeRuleEditor();
  closeAttach();
  const preset = $('presetModal');
  if (preset) preset.classList.add('hidden');
  const imp = $('importModal');
  if (imp) imp.classList.add('hidden');

  state.docs.article = id;
  state.docs.anchor = anchor || '';
  if (state.screen !== 'docs') navigate('docs');
  else renderDocs();
  window.scrollTo(0, 0);
  if (anchor) setTimeout(() => scrollDocSection(anchor), 80);
}

function closeDocArticle() {
  state.docs.article = '';
  state.docs.anchor = '';
  renderDocs();
  window.scrollTo(0, 0);
}

function scrollDocSection(sectionId) {
  if (!sectionId) return;
  const el = document.getElementById('docsec-' + state.docs.article + '-' + sectionId);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderDocs() {
  const home = $('docsHome');
  const articleBox = $('docsArticle');
  if (!home || !articleBox) return;
  const article = docById(state.docs.article);
  const homeBtn = $('btnDocsHome');
  if (homeBtn) homeBtn.classList.toggle('hidden', !article);
  const meta = $('docsMeta');
  if (meta) {
    meta.textContent = article
      ? docGroupTitle(article.group) + ' · ' + docKindTitle(article.kind)
      : 'Полное руководство по приложению · v' + (docData().version || '');
  }
  if (article) {
    home.classList.add('hidden');
    articleBox.classList.remove('hidden');
    renderDocArticle(article);
  } else {
    articleBox.classList.add('hidden');
    home.classList.remove('hidden');
    renderDocHome();
  }
}

function docPlain(html) {
  return String(html || '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&[a-z]+;/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function docTerms() {
  return String(state.docs.query || '').toLowerCase()
    .split(/\s+/).map(term => term.trim()).filter(term => term.length > 1);
}

function docEscapeRegExp(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function docHighlight(text, terms) {
  const safe = esc(text);
  if (!terms || !terms.length) return safe;
  const pattern = terms.map(docEscapeRegExp).filter(Boolean).join('|');
  if (!pattern) return safe;
  try {
    return safe.replace(new RegExp('(' + pattern + ')', 'gi'), '<mark>$1</mark>');
  } catch (e) {
    return safe;
  }
}

function docSnippet(text, terms) {
  const plain = docPlain(text);
  if (!plain) return '';
  const lower = plain.toLowerCase();
  let pos = -1;
  terms.forEach(term => {
    const index = lower.indexOf(term);
    if (index >= 0 && (pos < 0 || index < pos)) pos = index;
  });
  if (pos < 0) return plain.slice(0, 150) + (plain.length > 150 ? '…' : '');
  const start = Math.max(0, pos - 60);
  const end = Math.min(plain.length, pos + 110);
  return (start > 0 ? '…' : '') + plain.slice(start, end) +
    (end < plain.length ? '…' : '');
}

function docFiltered() {
  const terms = docTerms();
  const group = state.docs.group || 'all';
  const kind = state.docs.kind || 'all';
  const base = docArticles().filter(article =>
    (group === 'all' || article.group === group) &&
    (kind === 'all' || article.kind === kind));
  if (!terms.length) {
    return base.map(article => ({ article: article, hits: [] }));
  }
  return base.map(article => {
    const haystack = [
      article.title, article.summary, (article.tags || []).join(' '),
      docGroupTitle(article.group), docKindTitle(article.kind),
      (article.sections || []).map(section =>
        section.title + ' ' + docPlain(section.html)).join(' '),
    ].join(' ').toLowerCase();
    if (!terms.every(term => haystack.indexOf(term) >= 0)) return null;
    const hits = (article.sections || []).map(section => {
      const text = section.title + ' ' + docPlain(section.html);
      const lower = text.toLowerCase();
      const found = terms.some(term => lower.indexOf(term) >= 0);
      if (!found) return null;
      return {
        id: section.id,
        title: section.title,
        snippet: docSnippet(text, terms),
      };
    }).filter(Boolean);
    return { article: article, hits: hits };
  }).filter(Boolean).sort((left, right) => {
    const leftTitle = terms.some(term => left.article.title.toLowerCase().indexOf(term) >= 0);
    const rightTitle = terms.some(term => right.article.title.toLowerCase().indexOf(term) >= 0);
    if (leftTitle !== rightTitle) return leftTitle ? -1 : 1;
    return right.hits.length - left.hits.length;
  });
}

function renderDocHome() {
  const data = docData();
  const terms = docTerms();

  const groupBox = $('docsGroups');
  if (groupBox) {
    groupBox.innerHTML = [{ id: 'all', title: 'Все разделы', icon: '📂' }]
      .concat(docGroups()).map(group => {
        const count = group.id === 'all'
          ? docArticles().length
          : docArticles().filter(article => article.group === group.id).length;
        return '<button class="chip' + ((state.docs.group || 'all') === group.id ? ' active' : '') +
          '" data-doc-group="' + esc(group.id) + '">' +
          esc((group.icon || '') + ' ' + group.title) + ' · ' + count + '</button>';
      }).join('');
  }

  const kindBox = $('docsKinds');
  if (kindBox) {
    kindBox.innerHTML = [{ id: 'all', title: 'Все типы' }]
      .concat(docKinds()).map(kind =>
        '<button class="chip' + ((state.docs.kind || 'all') === kind.id ? ' active' : '') +
        '" data-doc-kind="' + esc(kind.id) + '">' + esc(kind.title) + '</button>').join('');
  }

  const search = $('docsSearch');
  if (search && search.value !== state.docs.query) search.value = state.docs.query;

  const results = docFiltered();
  const count = $('docsCount');
  if (count) {
    const total = data.articles ? data.articles.length : 0;
    count.textContent = terms.length
      ? 'Найдено статей: ' + results.length + ' из ' + total
      : 'Статей: ' + results.length + (state.docs.group === 'all' && state.docs.kind === 'all'
        ? ' · обновлено ' + (data.updated || '') : '');
  }

  const quick = $('docsQuick');
  if (quick) {
    const show = !terms.length && (state.docs.group || 'all') === 'all' &&
      (state.docs.kind || 'all') === 'all';
    quick.classList.toggle('hidden', !show);
    if (show) {
      quick.innerHTML = `
        <button class="doc-quick-card" data-doc-open="start-workflow">
          <span class="doc-quick-ico">🔁</span>
          <span><b>Главный цикл настройки</b><small>включить → подождать → разобрать → уточнить</small></span>
        </button>
        <button class="doc-quick-card" data-doc-open="rules-fields">
          <span class="doc-quick-ico">🧩</span>
          <span><b>Все поля правила</b><small>что означает каждая настройка</small></span>
        </button>
        <button class="doc-quick-card" data-doc-open="analysis-apply">
          <span class="doc-quick-ico">🔍</span>
          <span><b>Перенести находку</b><small>новое правило или добавление в существующее</small></span>
        </button>
        <button class="doc-quick-card" data-doc-open="faq">
          <span class="doc-quick-ico">❓</span>
          <span><b>Частые вопросы</b><small>нет прогнозов, пустой анализ, ошибки</small></span>
        </button>`;
    }
  }

  const list = $('docsList');
  if (!list) return;
  if (!results.length) {
    list.innerHTML = `<div class="empty">Ничего не найдено.
      <button class="link-btn" data-doc-reset="1">Сбросить поиск и фильтры</button></div>`;
    return;
  }
  list.innerHTML = results.map(result => {
    const article = result.article;
    const hit = result.hits[0];
    const snippet = hit ? hit.snippet : article.summary;
    const hitTitles = result.hits.slice(0, 3).map(item =>
      '<span>' + docHighlight(item.title, terms) + '</span>').join('');
    const more = result.hits.length > 3
      ? '<span class="doc-hit-more">+' + (result.hits.length - 3) + '</span>' : '';
    return `<button class="doc-card" data-doc-open="${esc(article.id)}"
        data-doc-anchor="${esc(hit ? hit.id : '')}">
      <div class="doc-card-top">
        <span class="doc-kind ${esc(article.kind)}">${esc(docKindTitle(article.kind))}</span>
        <span class="doc-card-group">${esc(docGroupTitle(article.group))}</span>
      </div>
      <div class="doc-card-title">${docHighlight(article.title, terms)}</div>
      <div class="doc-card-summary">${docHighlight(snippet || '', terms)}</div>
      ${hitTitles ? `<div class="doc-card-hits">${hitTitles}${more}</div>` : ''}
    </button>`;
  }).join('');
  const reset = list.querySelector('[data-doc-reset]');
  if (reset) reset.addEventListener('click', () => {
    state.docs.query = '';
    state.docs.group = 'all';
    state.docs.kind = 'all';
    renderDocHome();
  });
}

function renderDocArticle(article) {
  const box = $('docsArticle');
  if (!box) return;
  const all = docArticles();
  const index = all.indexOf(article);
  const prev = index > 0 ? all[index - 1] : null;
  const next = index >= 0 && index < all.length - 1 ? all[index + 1] : null;
  const related = all.filter(item => item.group === article.group && item.id !== article.id).slice(0, 3);
  const toc = (article.sections || []).map(section =>
    '<button data-doc-section="' + esc(section.id) + '">' + esc(section.title) + '</button>').join('');
  const sections = (article.sections || []).map(section =>
    `<section class="doc-section" id="docsec-${esc(article.id)}-${esc(section.id)}">
      <h3>${esc(section.title)}</h3>
      ${section.html}
    </section>`).join('');
  const nav = [
    prev ? `<button class="doc-nav-btn" data-doc-open="${esc(prev.id)}">
      <small>← Предыдущая</small><b>${esc(prev.title)}</b></button>` : '<span></span>',
    next ? `<button class="doc-nav-btn next" data-doc-open="${esc(next.id)}">
      <small>Следующая →</small><b>${esc(next.title)}</b></button>` : '<span></span>',
  ].join('');

  box.innerHTML = `
    <div class="doc-article-head">
      <button class="link-btn doc-back" data-doc-back="1">← Все статьи</button>
      <div class="doc-card-top">
        <span class="doc-kind ${esc(article.kind)}">${esc(docKindTitle(article.kind))}</span>
        <span class="doc-card-group">${esc(docGroupTitle(article.group))}</span>
      </div>
      <h3 class="doc-article-title">${esc(article.title)}</h3>
      <p class="doc-article-summary">${esc(article.summary)}</p>
      <div class="doc-tags">${(article.tags || []).map(tag =>
        '<span class="doc-tag">' + esc(tag) + '</span>').join('')}</div>
    </div>
    <nav class="doc-toc">
      <div class="doc-toc-title">Содержание</div>
      <div class="doc-toc-links">${toc}</div>
    </nav>
    <div class="doc-body">${sections}</div>
    <div class="doc-nav">${nav}</div>
    ${related.length ? `<div class="doc-related">
      <div class="doc-toc-title">Смотрите также</div>
      ${related.map(item => `<button class="doc-related-link" data-doc-open="${esc(item.id)}">
        ${esc(item.title)}</button>`).join('')}
    </div>` : ''}`;

  mountDocDynamic();
}

/* ---------- динамический справочник метрик ---------- */

function renderDocMetrics() {
  const box = document.querySelector('[data-doc-dynamic="metrics"]');
  if (!box) return;
  const sport = state.docs.metricSport || state.sport;
  state.docs.metricSport = sport;
  const chips = sportList().map(item =>
    '<button class="chip' + (item.id === sport ? ' active' : '') +
    '" data-doc-metric-sport="' + esc(item.id) + '">' + esc(item.icon || '') + ' ' +
    esc(item.short || item.name) + '</button>').join('');
  box.innerHTML = `
    <div class="doc-metric-tools">
      <div class="chips wrap">${chips}</div>
      <input type="search" id="docMetricSearch" autocomplete="off"
             value="${esc(state.docs.metricQuery || '')}"
             placeholder="Поиск метрики: тотал, форма, кэф, очные…">
    </div>
    <div id="docMetricsList" class="doc-metrics">
      <div class="empty">Загружаю справочник…</div>
    </div>`;
  loadDocCatalog(sport);
}

function loadDocCatalog(sport) {
  const list = $('docMetricsList');
  if (!list) return;
  let catalog = state.docs.catalogs[sport];
  if (!catalog) {
    const res = call('constructor', sport);
    if (res && res.ok && res.catalog) {
      catalog = res.catalog;
      state.docs.catalogs[sport] = catalog;
    }
  }
  if (!catalog) {
    list.innerHTML = '<div class="empty">Справочник недоступен без движка. ' +
      'Откройте приложение на телефоне.</div>';
    return;
  }
  renderDocMetricsList();
}

function docMetricType(type) {
  return { number: 'число', string: 'текст', enum: 'список', bool: 'да/нет' }[type] || 'значение';
}

function docMetricPreview(metric) {
  return String(metric.label || metric.id || '').replace(/\{(\w+)\}/g, (all, key) => {
    const value = (metric.args || {})[key];
    if (value === undefined || value === null || value === '') return '…';
    if (key === 'side') {
      if (value === 'p1') return 'игрока 1';
      if (value === 'p2') return 'игрока 2';
      return value;
    }
    if (key === 'set') return value + '-й';
    return value;
  });
}

function renderDocMetricsList() {
  const list = $('docMetricsList');
  if (!list) return;
  const sport = state.docs.metricSport || state.sport;
  const catalog = state.docs.catalogs[sport];
  if (!catalog) return;
  const terms = String(state.docs.metricQuery || '').toLowerCase()
    .split(/\s+/).filter(term => term.length > 0);
  const metrics = (catalog.metrics || []).filter(metric => {
    if (!terms.length) return true;
    const haystack = [
      metric.id, metric.label, metric.group, metric.hint,
      JSON.stringify(metric.args || {}), metric.unit,
    ].join(' ').toLowerCase();
    return terms.every(term => haystack.indexOf(term) >= 0);
  });

  if (!metrics.length) {
    list.innerHTML = '<div class="empty">Метрики не найдены. Попробуйте другой запрос.</div>';
    return;
  }

  const groups = [];
  metrics.forEach(metric => {
    const name = metric.group || 'Прочее';
    let group = groups.find(item => item.name === name);
    if (!group) { group = { name: name, items: [] }; groups.push(group); }
    group.items.push(metric);
  });

  const argDefs = catalog.args || {};
  list.innerHTML = groups.map((group, groupIndex) => {
    const rows = group.items.map(metric => {
      const args = Object.keys(metric.args || {}).map(key => {
        const def = argDefs[key] || {};
        return esc(def.label || key) + ': ' + esc((metric.args || {})[key]);
      });
      return `<div class="doc-metric">
        <div class="doc-metric-head">
          <span class="doc-metric-name">${esc(docMetricPreview(metric))}</span>
          ${metric.unit ? `<span class="doc-metric-unit">${esc(metric.unit)}</span>` : ''}
        </div>
        <div class="doc-metric-meta">
          <code>${esc(metric.id)}</code>
          <span class="doc-metric-type">${esc(docMetricType(metric.type))}</span>
          ${args.length ? `<span class="doc-metric-args">${args.join(' · ')}</span>` : ''}
        </div>
        ${metric.hint ? `<div class="doc-metric-hint">${esc(metric.hint)}</div>` : ''}
      </div>`;
    }).join('');
    return `<details class="doc-metric-group"${(terms.length || groupIndex < 2) ? ' open' : ''}>
      <summary>${esc(group.name)} <span class="badge">${group.items.length}</span></summary>
      <div class="doc-metric-list">${rows}</div>
    </details>`;
  }).join('') + `<div class="doc-metric-total muted">Метрик: ${metrics.length} · ${esc(catalog.sport_name || sport)}</div>`;
}

function mountDocDynamic() {
  const box = document.querySelector('[data-doc-dynamic="metrics"]');
  if (!box) return;
  renderDocMetrics();
}


/* ---------------- старт ---------------- */

function init() {
  buildThresholds();
  buildRequiredModels();
  buildAllowedBets();
  buildAllowedSets();
  renderSportSelectors();
  updateAnalyzerSportUI();
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

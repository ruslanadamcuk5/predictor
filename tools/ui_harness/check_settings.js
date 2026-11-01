/* Проверка сохранения настроек и AI-карточки без браузера.
   Запуск: node tools/ui_harness/check_settings.js
   Стенд подменяет документ и PyApp, поэтому проверяется настоящий app.js. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..', '..');
const SRC = fs.readFileSync(
  path.join(ROOT, 'app', 'src', 'main', 'assets', 'www', 'app.js'), 'utf8');

const elements = new Map();
function makeElement(id) {
  return {
    id, value: '', checked: false, textContent: '', innerHTML: '',
    className: '', hidden: false, dataset: {}, style: {},
    classList: {
      add() {}, remove() {},
      toggle() {}, contains() { return false; },
    },
    addEventListener() {}, removeEventListener() {},
    appendChild() {}, removeChild() {}, focus() {}, blur() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; },
  };
}
function element(id) {
  if (!elements.has(id)) elements.set(id, makeElement(id));
  return elements.get(id);
}

const documentStub = {
  getElementById: element,
  querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener() {},
  activeElement: null,
  body: makeElement('body'),
  documentElement: makeElement('html'),
};

let saved = null;
const bridge = {
  settings() {
    return JSON.stringify({
      settings: JSON.parse(JSON.stringify(saved || {})),
      defaults: {},
      sports: [],
    });
  },
  saveSettings(payload) {
    saved = JSON.parse(payload);
    return JSON.stringify({ ok: true, settings: saved });
  },
};

global.window = {
  PyApp: bridge,
  addEventListener() {},
  matchMedia() { return { matches: false, addEventListener() {} }; },
  localStorage: { getItem() { return ''; }, setItem() {} },
  navigator: { userAgent: 'node' },
  location: { href: 'http://localhost/' },
};
global.document = documentStub;

vm.runInThisContext(SRC + `
;globalThis.__ui = {
  state, collectSettings, collectAiSettings, loadSettings, saveSettings,
  renderSettings, renderAiSettings, num,
};
`);

const ui = global.__ui;
let failures = 0;
function check(name, condition, detail) {
  if (condition) {
    console.log('  OK   ' + name);
  } else {
    failures += 1;
    console.log('  FAIL ' + name + (detail === undefined ? '' :
      ' :: ' + JSON.stringify(detail)));
  }
}

// --- исходное состояние: как будто настройки уже сохранены раньше ---
ui.state.sports = [
  { id: 'table_tennis', short: 'Наст. теннис', name: 'Настольный теннис',
    bets: [{ type: 'winner' }, { type: 'total' }] },
  { id: 'football', short: 'Футбол', name: 'Футбол',
    bets: [{ type: 'winner' }, { type: 'total' }] },
];
ui.state.settings = {
  poll_interval_sec: 99,
  max_matches_per_sport: 1,
  neural: { enabled: false, min_samples: 10, auto_train: false },
  ai: { provider: 'gemini', enabled: false },
};
ui.state.ai.sports = ['table_tennis'];
ui.state.ai.markets = { table_tennis: ['total'], football: ['winner'] };
ui.state.ai.provider = 'gemini';

element('setInterval').value = '20';
element('setPerSport').value = '9';
element('setNnEnabled').checked = true;
element('setNnAutoTrain').checked = true;
element('setNnKeepBest').checked = true;
element('setNnFreeze').checked = false;
element('setNnMinSamples').value = '75';
element('setNnConfidence').value = '55';
element('setNnSets').value = '3';
element('setOdds').checked = true;
element('setVerbose').checked = false;
element('setBetSize').value = '2';
element('setAiEnabled').checked = true;
element('setAiBaseUrl').value = 'https://example.test/v1';
element('setAiModel').value = 'model-x';
element('setAiKey').value = 'key-x';
element('setAiTimeout').value = '90';
element('setAiThinking').checked = true;
element('setAiAutoPredict').checked = true;
element('setAiEmbed').checked = false;
element('setAiPerCycle').value = '2';
element('setAiPerDay').value = '40';
element('setAiConfidence').value = '60';

const aiOnly = ui.collectAiSettings();
check('collectAiSettings возвращает только блок ai',
  Object.keys(aiOnly).join(',') === 'ai', Object.keys(aiOnly));
check('выбранный вид ИИ сохраняется в настройках',
  JSON.stringify(aiOnly.ai.sports) === JSON.stringify(['table_tennis']),
  aiOnly.ai.sports);
check('рынки ИИ сохраняются',
  JSON.stringify(aiOnly.ai.markets.table_tennis) === JSON.stringify(['total']),
  aiOnly.ai.markets);

const payload = ui.collectSettings();
check('интервал из формы не перезаписывается снимком',
  payload.poll_interval_sec === 20, payload.poll_interval_sec);
check('лимит матчей из формы не перезаписывается снимком',
  payload.max_matches_per_sport === 9, payload.max_matches_per_sport);
check('нейросеть из формы не перезаписывается блоком ИИ',
  payload.neural.enabled === true && payload.neural.min_samples === 75,
  payload.neural);
check('ИИ сохраняется вместе с остальными настройками',
  payload.ai.model === 'model-x' && payload.ai.api_key === 'key-x',
  payload.ai);

// --- пересохранение: ответ сервера — источник правды для формы ---
ui.state.settings = payload;
ui.saveSettings();
check('после сохранения настройки пришли с сервера',
  ui.state.settings.poll_interval_sec === 20
  && ui.state.settings.ai.model === 'model-x', ui.state.settings);
check('после сохранения модель осталась в поле',
  element('setAiModel').value === 'model-x', element('setAiModel').value);
check('после сохранения виды ИИ остались выбранными',
  JSON.stringify(ui.state.ai.sports) === JSON.stringify(['table_tennis']),
  ui.state.ai.sports);

// --- фоновый опрос статуса не должен затирать форму ---
ui.renderAiSettings({
  enabled: false, ready: false, provider: 'custom',
  sports_selected: ['football'], markets: { football: ['total'] },
  has_key: false, provider_label: 'Свой endpoint', model: 'other',
});
check('фоновый статус не меняет включённость ИИ',
  element('setAiEnabled').checked === true, element('setAiEnabled').checked);
check('фоновый статус не меняет модель в поле',
  element('setAiModel').value === 'model-x', element('setAiModel').value);
check('фоновый статус не меняет выбранные виды',
  JSON.stringify(ui.state.ai.sports) === JSON.stringify(['table_tennis']),
  ui.state.ai.sports);
check('фоновый статус обновляет бейдж',
  element('setAiBadge').textContent === 'выкл',
  element('setAiBadge').textContent);

if (failures) {
  console.log('\nUI SETTINGS FAILED: ' + failures);
  process.exit(1);
}
console.log('\nUI SETTINGS OK');

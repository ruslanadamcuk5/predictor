/* Заглушка Python-моста для проверки UI в браузере */
(function () {
  const now = () => new Date().toTimeString().slice(0, 8);
  const settings = {
    running: true,
    active_sport: "table_tennis",
    poll_interval_sec: 20,
    odds_check_enabled: true,
    debug_verbose: true,
    bet_size_percent: 2.0,
    telegram: { enabled: true, token: "", chat_id: "" },
    model_thresholds: { streak: 0.25, window: 0.25, markov1: 0.25, markov2: 0.25, recency: 0.25, base_rate: 0.25 },
    required_models: ["streak", "window"],
    allowed_bets: { "П1": true, "П2": true, "ТБ18.5": true, "ТМ18.5": false },
    allowed_sets: { set1: true, set2: true, set3: true, set4: false, set5: false },
    general_filters: { min_strong: 2, min_agreement: 0.4, min_confidence: 0.2, min_active: 2, vote_weight_base: 0.3 },
    min_h2h_matches: 5,
    engine: { streak_min: 3, window_size: 10, window_min_hits: 6, markov_min_sample: 5, recency_decay: 0.85, base_rate_min_n: 10, prob_threshold: 18.5 },
    reports: { hourly: true, daily: true, daily_hour: 23, daily_minute: 55 },
    notifications: { on_signal: true, on_error: true, on_result: true },
    auto_rules: { enabled: false, min_precision: 60, min_samples: 6, max_rules: 4 },
    max_matches_per_sport: 10,
    neural: { enabled: false, auto_train: true, min_samples: 50, min_confidence: 0.55, sets: 3,
      sports: ["table_tennis", "football", "hockey", "basketball", "volleyball", "tennis"],
      markets: {} },
    ai: { enabled: false, provider: "gemini", base_url: "", model: "", api_key: "",
      timeout: 90, auto_predict: false, per_cycle: 1, per_day: 40, min_confidence: 0.5 },
  };

  const nnMarketsOf = (id) => {
    const item = sports.find(s => s.id === id) || sports[0];
    const types = [];
    (item.bets || []).forEach(bet => {
      if (bet && bet.type && types.indexOf(bet.type) < 0) types.push(bet.type);
    });
    return types;
  };

  const aiProviders = [
    { id: "gemini", label: "Gemini (бесплатный tier)", base_url: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-3.8-flash" },
    { id: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-flash" },
    { id: "groq", label: "Groq", base_url: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile" },
    { id: "openrouter", label: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "deepseek/deepseek-chat" },
    { id: "custom", label: "Свой endpoint", base_url: "", model: "" },
  ];

  const aiStatus = () => ({
    enabled: !!settings.ai.enabled,
    ready: !!settings.ai.enabled && !!settings.ai.api_key,
    provider: settings.ai.provider,
    provider_label: (aiProviders.find(p => p.id === settings.ai.provider) || aiProviders[0]).label,
    base_url: settings.ai.base_url || (aiProviders.find(p => p.id === settings.ai.provider) || aiProviders[0]).base_url,
    model: settings.ai.model || (aiProviders.find(p => p.id === settings.ai.provider) || aiProviders[0]).model,
    has_key: !!settings.ai.api_key,
    timeout: settings.ai.timeout,
    auto_predict: !!settings.ai.auto_predict,
    per_cycle: settings.ai.per_cycle,
    per_day: settings.ai.per_day,
    min_confidence: settings.ai.min_confidence,
    used_today: 7,
    quota_left: Math.max(0, settings.ai.per_day - 7),
    providers: aiProviders,
  });

  const aiAnswers = {
    explain: "Матч: команда 1 в хорошей форме (4 победы из 5), очные встречи в её пользу (3 из 5).\nКоэффициенты дают перевес примерно 52% на П1, линия тотала чуть ниже среднего тотала последних игр.\n\nРиски: у команды 2 сильная защита в последних матчах, поэтому исход может оказаться ничейным.",
    draft: '{\n  "name": "П1 при высоком проценте побед",\n  "conditions": {\n    "logic": "and",\n    "conditions": [\n      {"metric": "p.recent.win_rate", "op": "gte", "value": 60, "args": {"side": "p1", "window": 5}}\n    ]\n  },\n  "action": {"type": "winner", "side": "p1", "target": ["auto"]},\n  "enabled": true\n}',
    digest: "1. Зашло лучше по тоталу: 7 из 9 (78%) — это ваш самый устойчивый рынок.\n2. Исход матча слабее: 4 из 11 (36%), порог 55% слишком мягкий.\n3. Настольный теннис даёт больше сигналов, чем командные виды.\n4. Поднимите порог уверенности для вида «winner» до 60%.\n5. Следите за линией форы: 2 из 3 ф��р не зашли.",
    review: "critical: правило №2 противоречит правилу №5 — оба срабатывают на один рынок, но требуют противоположного.\n\nпрочее:\n• Условие «p.recent.win_rate ≥ 58» встречается в 4 правилах — возможно, лучше вынести в общее.\n• Рынок «фора» есть только у командных видов, проверьте, нет ли такого правила у настольного тенниса.\n• Порог 60% по виду «total» срабатывает редко.",
  };

  const aiJobs = {};
  const aiMessages = [
    { role: "assistant", text: "Здравствуйте! Я помощник Predictor. Знаю текущее состояние приложения: правила, нейросеть, результаты и настройки. Спрашивайте о чём угодно — от «почему нет прогнозов» до «как настроить правила под хоккей».", at: "2026-10-22T11:00:00" },
  ];
  const aiAlerts = [
    { id: "nn_overfit_football", severity: "critical",
      title: "Нейросеть по виду «Футбол» переобучается",
      text: "Из последних 4 обучений 2 новых модели хуже прежних (точность падает). Остановите автоматическое обучение: иначе сеть начнёт запоминать, а не обобщать.",
      action: { type: "neural_freeze", label: "Заморозить обучение" }, sport: "football" },
    { id: "rule_bad_r2", severity: "warn",
      title: "Правило «ТБ 2.5: оба играют верх» чаще проигрывает",
      text: "Условие «Средний тотал матча ≥ 2.5» встречается в 78% неудачных прогнозов и почти не встречается в удачных. Это кандидат на исключение.",
      action: { type: "rule_disable", label: "Выключить правило", sport: "football", rule_id: "r2" }, sport: "football" },
    { id: "poll_fast", severity: "info",
      title: "Слишком частый опрос линии",
      text: "Интервал 10 с при шести видах спорта — это лишний трафик и батарея. 20–30 с обычно достаточно.",
      action: { type: "interval_up", label: "Поставить 30 с" }, sport: "" },
  ];

  const nnStatus = () => {
    const history = [
      { at: "2026-10-20T08:00:00", accuracy: 0.52, baseline: 0.5, lift: 0.02, samples: 120, rejected: false },
      { at: "2026-10-21T08:00:00", accuracy: 0.56, baseline: 0.5, lift: 0.06, samples: 148, rejected: false },
      { at: "2026-10-21T18:00:00", accuracy: 0.54, baseline: 0.5, lift: 0.04, samples: 165, rejected: true },
      { at: "2026-10-22T08:00:00", accuracy: 0.61, baseline: 0.52, lift: 0.09, samples: 214, rejected: false },
    ];
    return {
      enabled: !!settings.neural.enabled,
      auto_train: settings.neural.auto_train !== false,
      keep_best: settings.neural.keep_best !== false,
      freeze: !!settings.neural.freeze,
      plateau_rounds: 3,
      min_samples: settings.neural.min_samples,
      min_confidence: settings.neural.min_confidence,
      sets: settings.neural.sets,
      sports_selected: (settings.neural.sports || []).slice(),
      market_labels: { winner: "Победитель", total: "Тотал", handicap: "Фора", btts: "Обе забьют" },
      total_samples: 214,
      pending: 37,
      dropped: 4,
      ready_sports: 3,
      trained: true,
      training: false,
      last_train_at: "2026-10-22T11:04:00",
      updated_at: now(),
      sports: sports.map((item, index) => {
        const rolled = nnRolledBack === item.id;
        const accuracy = rolled ? 0.56 : ([0.61, 0.57, 0.54, 0, 0, 0][index] || 0);
        return {
        sport: item.id, name: item.name, short: item.short, icon: item.icon,
        samples: [96, 58, 31, 12, 9, 8][index] || 0,
        pending: [6, 9, 7, 5, 5, 5][index] || 0,
        accuracy: accuracy,
        baseline: [0.52, 0.5, 0.5, 0, 0, 0][index] || 0,
        lift: [0.09, 0.07, 0.04, 0, 0, 0][index] || 0,
        winner_accuracy: [0.63, 0.59, 0.55, 0, 0, 0][index] || 0,
        val_samples: [18, 12, 7, 0, 0, 0][index] || 0,
        epochs: 12,
        trained_at: "2026-10-22T11:04:00",
        selected: (settings.neural.sports || []).indexOf(item.id) >= 0,
        markets: nnMarketsOf(item.id),
        markets_enabled: (settings.neural.markets && settings.neural.markets[item.id]) ||
          nnMarketsOf(item.id),
        ready: index < 3,
        history: index < 3 ? history : [],
        trend: rolled ? "down" : (index === 0 ? "up" : (index === 1 ? "down" : "flat")),
        plateau: index === 2,
        has_backup: index < 2 && !rolled,
        backup_accuracy: index === 0 ? 0.56 : (index === 1 ? 0.54 : 0),
      };
      }),
    };
  };

  const sports = [
    { id: "table_tennis", name: "Настольный теннис", short: "Наст. теннис", icon: "🏓", has_draw: false, bets: [{ type: "winner" }, { type: "total" }] },
    { id: "football", name: "Футбол", short: "Футбол", icon: "⚽", has_draw: true, bets: [{ type: "winner" }, { type: "total" }, { type: "handicap" }, { type: "btts" }] },
    { id: "hockey", name: "Хоккей", short: "Хоккей", icon: "🏒", has_draw: true, bets: [{ type: "winner" }, { type: "total" }, { type: "handicap" }, { type: "btts" }] },
    { id: "basketball", name: "Баскетбол", short: "Баскетбол", icon: "🏀", has_draw: false, bets: [{ type: "winner" }, { type: "total" }, { type: "handicap" }] },
    { id: "volleyball", name: "Волейбол", short: "Волейбол", icon: "🏐", has_draw: false, bets: [{ type: "winner" }, { type: "total" }, { type: "handicap" }] },
    { id: "tennis", name: "Большой теннис", short: "Теннис", icon: "🎾", has_draw: false, bets: [{ type: "winner" }, { type: "total" }, { type: "handicap" }] },
  ];

  let logId = 0;
  const logs = [];
  let nnRolledBack = "";
  const messages = [
    ["INFO", "Движок запущен (интервал 20 с)"],
    ["INFO", "📊 Всего матчей: 24, скоро: 7"],
    ["INFO", "Анализ: Иванов А. vs Петров С."],
    ["INFO", "      ✅ Партия 1 (П1/П2): П1 | Модели: streak=T1(71%), window=T1(64%)"],
    ["INFO", "✅ Сигналов: 2 (Иванов А. vs Петров С.)"],
    ["WARNING", "Telegram не настроен — сигнал сохранён локально"],
    ["INFO", "Анализ: Сидоров К. vs Кузнецов Д."],
    ["INFO", "      ⛔ Партия 1 (ТБ18.5/ТМ18.5): agreement 12.0% < 20%"],
    ["ERROR", "Очередь: таймаут соединения с d.betcity.by"],
    ["INFO", "Цикл завершён: проверено 7, сигналов 2"],
  ];
  messages.forEach(([level, message]) => {
    logId += 1;
    logs.push({ id: logId, ts: now(), ts_full: "2026-10-19 " + now(), level, message });
  });

  const queue = [
    { match_id: "1", sport: "table_tennis", sport_name: "Наст. теннис", team1: "Иванов А.", team2: "Петров С.", league: "Pro League", date: "19.10 14:30", score: "0:0", started: false, processed: false, sent: true, odds: { p1: 1.72, p2: 2.05 },
      prediction: { sent_at: "2026-10-19T14:30:00", wins: 1, losses: 1, pending: 0, items: [
        { target: "set1", kind: "winner", label: "Партия 1 (П1/П2)", verdict: "П1", success: true, score: "11:7", total: 18 },
        { target: "set1", kind: "total", label: "Партия 1 (ТБ18.5/ТМ18.5)", verdict: "ТБ 18.5", success: false, score: "11:7", total: 18 },
      ] } },
    { match_id: "2", sport: "table_tennis", sport_name: "Наст. теннис", team1: "Сидоров К.", team2: "Кузнецов Д.", league: "TT Cup", date: "19.10 14:45", score: "1:1", started: true, processed: false, sent: false, odds: { p1: 1.95, p2: 1.82 } },
    { match_id: "3", sport: "table_tennis", sport_name: "Наст. теннис", team1: "Морозов И.", team2: "Волков П.", league: "Setka Cup", date: "19.10 15:00", score: "0:0", started: false, processed: true, sent: false, odds: { p1: 2.10, p2: 1.68 } },
    { match_id: "4", sport: "football", sport_name: "Футбол", team1: "Спартак М", team2: "Зенит", league: "РПЛ", date: "19.10 18:00", score: "0:0", started: false, processed: false, sent: false, odds: { p1: 2.05, p2: 3.10, draw: 3.40, total_line: 2.5 } },
    { match_id: "5", sport: "hockey", sport_name: "Хоккей", team1: "ЦСКА", team2: "Ак Барс", league: "КХЛ", date: "19.10 19:30", score: "1:2", started: true, processed: false, sent: true, odds: { p1: 1.80, p2: 2.20, draw: 3.60, total_line: 4.5 } },
  ];

  const results = [
    { id: "a", sport: "table_tennis", sport_name: "Наст. теннис", team1: "Иванов А.", team2: "Петров С.", league: "Pro League", date: "19.10",
      sent_at: "2026-10-19T14:30:00", wins: 2, losses: 1, pending: 0, checked: true,
      from_cache: true,
      final_score: "11:7 9:11 11:5",
      rows: [
        { target: "set1", kind: "winner", label: "Партия 1 (П1/П2)", verdict: "П1", reason: "Модели: streak=T1(71%), window=T1(64%), markov1=T1(58%)", confidence: 62, agreement: 71, strong: 4, success: true, score: "11:7", total: 18 },
        { target: "set1", kind: "total", label: "Партия 1 (ТБ18.5/ТМ18.5)", verdict: "ТБ 18.5", reason: "Модели: markov1=TO(52%), base_rate=TO(48%), recency=TO(55%)", confidence: 44, agreement: 55, strong: 3, threshold: 18.5, success: false, score: "11:7", total: 18, checked_from: "cache" },
        { target: "match", kind: "winner", label: "🤖 Матч (П1/П2)", verdict: "П1", reason: "ИИ: у Иванова стабильнее приём", confidence: 58, agreement: null, strong: null, success: true, score: "4:1", total: 5, source: "ai" },
      ] },
    { id: "b", sport: "table_tennis", sport_name: "Наст. теннис", team1: "Сидоров К.", team2: "Кузнецов Д.", league: "TT Cup", date: "18.10",
      sent_at: "2026-10-18T09:15:00", wins: 1, losses: 0, pending: 1, checked: false, final_score: "",
      rows: [
        { target: "set2", kind: "winner", label: "Партия 2 (П1/П2)", verdict: "П2", reason: "Модели: window=T2(58%), streak=T2(61%)", confidence: 51, agreement: 60, strong: 3, success: true, score: "9:11", total: 20 },
        { target: "set3", kind: "winner", label: "Партия 3 (П1/П2)", verdict: "П1", reason: "Модели: markov2=T1(57%)", confidence: 55, agreement: 64, strong: 2, success: null, score: "", total: null },
        { target: "match", kind: "winner", label: "🤖 Матч (П1/П2)", verdict: "П2", reason: "ИИ: у Кузнецова лучше подача", confidence: 54, agreement: null, strong: null, success: null, score: "", total: null, source: "ai" },
      ] },
  ];

  const predictions = [
    {
      id: "a", sport: "table_tennis", sport_name: "Наст. теннис", team1: "Иванов А.", team2: "Петров С.", league: "Pro League", date: "19.10",
      sent_at: "2026-10-19T14:30:00", wins: 1, losses: 1, pending: 0, checked: true,
      predictions: [
        { target: "set1", label: "Партия 1 (П1/П2)", verdict: "П1" },
        { target: "set1", label: "Партия 1 (ТБ18.5/ТМ18.5)", verdict: "ТБ 18.5" },
      ],
      results: [
        { target: "set1", success: true, score: "11:7" },
      ],
    },
    {
      id: "b", sport: "table_tennis", sport_name: "Наст. теннис", team1: "Сидоров К.", team2: "Кузнецов Д.", league: "TT Cup", date: "19.10",
      sent_at: "2026-10-19T13:10:00", wins: 2, losses: 0, pending: 1, checked: false,
      predictions: [
        { target: "set1", label: "Партия 1 (П1/П2)", verdict: "П2" },
        { target: "set2", label: "Партия 2 (П1/П2)", verdict: "П2" },
        { target: "set2", label: "Партия 2 (ТБ18.5/ТМ18.5)", verdict: "ТМ 18.5" },
      ],
      results: [
        { target: "set1", success: true },
        { target: "set2", success: true },
      ],
    },
  ];

  const stats = {
    matches: 2,
    total: { preds: 5, wins: 3, losses: 1, pending: 1 },
    today: { preds: 5, wins: 3, losses: 1, pending: 1 },
    hit_rate: 75.0,
    today_hit_rate: 75.0,
    by_target: [
      { key: "set1:total", total: 2, wins: 1, losses: 1, hit_rate: 50.0 },
      { key: "set1:winner", total: 2, wins: 2, losses: 0, hit_rate: 100.0 },
      { key: "set2:winner", total: 1, wins: 1, losses: 0, hit_rate: 100.0 },
    ],
    by_sport: [
      { sport: "table_tennis", name: "Наст. теннис", preds: 5, wins: 3, losses: 1, pending: 1, hit_rate: 75.0 },
      { sport: "football", name: "Футбол", preds: 2, wins: 1, losses: 1, pending: 0, hit_rate: 50.0 },
    ],
  };

  const ctorCatalog = {
    sport: "table_tennis",
    sport_name: "Настольный теннис",
    default_total: 18.5,
    period_word: "Партия",
    bets: [{ type: "winner" }, { type: "total" }],
    metrics: [
      { id: "h2h.count", label: "Сколько очных встреч найдено", group: "Очные встречи", type: "number", args: {}, unit: "", hint: "" },
      { id: "h2h.win_rate", label: "Процент побед {side} в очных за {window}", group: "Очные встречи", type: "number", args: { side: "p1", window: 10 }, unit: "%" },
      { id: "h2h.streak", label: "Текущая серия побед {side} в очных", group: "Очные встречи", type: "number", args: { side: "p1" }, unit: "игр" },
      { id: "h2h.last_winner", label: "Победитель последней очной встречи", group: "Очные встречи", type: "enum", args: {}, options: [["p1", "Игрок 1"], ["p2", "Игрок 2"]] },
      { id: "h2h.over_rate", label: "Доля ТБ{threshold} в {set} партии очных за {window}", group: "Очные встречи", type: "number", args: { window: 10, set: 1, threshold: 18.5 }, unit: "%" },
      { id: "p.recent.win_rate", label: "Процент побед {side} за {window} игр", group: "Форма игрока", type: "number", args: { side: "p1", window: 5 }, unit: "%" },
      { id: "p.recent.avg_set_total", label: "Средний тотал партии {side} за {window} игр", group: "Форма игрока", type: "number", args: { side: "p1", window: 5 }, unit: "очк." },
      { id: "p.recent.set_win_rate", label: "Процент побед {side} в {set} партии за {window} игр", group: "Форма игрока", type: "number", args: { side: "p1", window: 5, set: 1 }, unit: "%" },
      { id: "p.recent.last_result", label: "Результат последней игры {side}", group: "Форма игрока", type: "enum", args: { side: "p1" }, options: [["win", "Победа"], ["loss", "Поражение"]] },
      { id: "cmp.avg_set_total_mean", label: "Средний тотал партии по форме обоих за {window} игр", group: "Сравнение игроков", type: "number", args: { window: 5 }, unit: "очк." },
      { id: "cmp.win_rate_lead", label: "Кто лучше по проценту побед за {window} игр", group: "Сравнение игроков", type: "enum", args: { window: 5 }, options: [["p1", "Игрок 1"], ["p2", "Игрок 2"], ["tie", "Равно"]] },
      { id: "odds.p1", label: "Коэффициент на игрока 1", group: "Коэффициенты", type: "number", args: {} },
      { id: "odds.p2", label: "Коэффициент на игрока 2", group: "Коэффициенты", type: "number", args: {} },
      { id: "odds.available", label: "Коэффициенты доступны", group: "Коэффициенты", type: "bool", args: {} },
      { id: "match.league", label: "Название лиги", group: "Матч", type: "string", args: {} },
      { id: "match.minutes_to_start", label: "Минут до начала матча", group: "Матч", type: "number", args: {}, unit: "мин" },
    ],
    args: {
      side: { label: "Игрок", kind: "select", default: "p1", options: [["p1", "Игрок 1"], ["p2", "Игрок 2"]] },
      window: { label: "Игр", kind: "number", default: 5, min: 1, max: 20, step: 1 },
      set: { label: "Партия", kind: "select", default: 1, options: [[1, "1-я"], [2, "2-я"], [3, "3-я"], [4, "4-я"], [5, "5-я"]] },
      threshold: { label: "Тотал", kind: "number", default: 18.5, min: 0, max: 100, step: 0.5 },
    },
    operators: {
      number: [["gt", "Больше"], ["gte", "Больше или равно"], ["lt", "Меньше"], ["lte", "Меньше или равно"], ["eq", "Равно"], ["neq", "Не равно"], ["between", "Между"], ["exists", "Есть данные"], ["not_exists", "Нет данных"]],
      string: [["eq", "Равно"], ["neq", "Не равно"], ["contains", "Содержит"], ["not_contains", "Не содержит"], ["in", "Одно из"], ["not_in", "Не одно из"], ["starts_with", "Начинается с"], ["ends_with", "Заканчивается на"], ["exists", "Есть"], ["not_exists", "Нет"]],
      enum: [["eq", "Равно"], ["neq", "Не равно"], ["in", "Одно из"], ["not_in", "Не одно из"], ["exists", "Есть"], ["not_exists", "Нет"]],
      bool: [["is", "Равно"], ["exists", "Есть"], ["not_exists", "Нет"]],
    },
    enum_labels: {},
    side_labels: { p1: "игрока 1", p2: "игрока 2" },
  };

  let ctorRules = [
    {
      id: "r1", name: "ТБ 18.5: форма + последняя очная", enabled: true, priority: 100, stop: false,
      conditions: { logic: "and", conditions: [
        { metric: "h2h.last_winner", args: {}, op: "eq", value: "p1" },
        { metric: "p.recent.avg_set_total", args: { side: "p1", window: 5 }, op: "gt", value: 19 },
      ] },
      action: { type: "total", targets: [1], side: "over", threshold: 18.5, confidence: 0.65 },
      summary: "ЕСЛИ Победитель последней очной встречи = Игрок 1 И Средний тотал партии игрока 1 за 5 игр > 19 очк. → ТБ 18.5, партии 1",
      conditions_text: "Победитель последней очной встречи (= Игрок 1) = Игрок 1 И Средний тотал партии игрока 1 (> 19)",
      action_text: "ТБ 18.5, партии 1",
    },
    {
      id: "r2", name: "Пропуск: кэф ниже 1.5", enabled: false, priority: 90, stop: false,
      conditions: { logic: "or", conditions: [
        { metric: "odds.p1", args: {}, op: "lt", value: 1.5 },
        { metric: "odds.p2", args: {}, op: "lt", value: 1.5 },
      ] },
      action: { type: "skip", targets: [1], side: "auto", threshold: 18.5, confidence: 0.6 },
      summary: "ЕСЛИ (Коэффициент на игрока 1 < 1.5 ИЛИ Коэффициент на игрока 2 < 1.5) → пропустить матч",
      conditions_text: "Коэффициент на игрока 1 < 1.5 ИЛИ Коэффициент на игрока 2 < 1.5",
      action_text: "пропустить матч",
    },
  ];

  let autoEnabled = false;
  const autoConfig = { min_precision: 60, min_samples: 6, max_rules: 4 };
  const autoSeed = [
    {
      id: "auto_demo1", name: "Авто · ТБ 18.5, партии 1 · 72.7% (n=11)",
      enabled: true, action_text: "ТБ 18.5, партии 1",
      precision: 72.7, coverage: 45.8, matched: 11, wins: 8, losses: 3,
      updated_at: "21.10.2026 09:40", skip: false,
    },
    {
      id: "auto_demo2", name: "Авто · П1, партии 2 · 66.7% (n=9)",
      enabled: true, action_text: "П1, партии 2",
      precision: 66.7, coverage: 37.5, matched: 9, wins: 6, losses: 3,
      updated_at: "21.10.2026 09:40", skip: false,
    },
    {
      id: "auto_demo3", name: "Авто-фильтр · пропустить матч (n=4)",
      enabled: true, action_text: "пропустить матч",
      precision: 100, coverage: 16.7, matched: 4, wins: 0, losses: 4,
      updated_at: "21.10.2026 09:40", skip: true,
    },
  ];

  function autoCtorRules() {
    return [
      {
        id: "auto_demo1", name: "Авто · ТБ 18.5, партии 1",
        enabled: true, priority: 110, stop: false, sport: settings.active_sport, auto: true,
        conditions: { logic: "and", conditions: [
          { metric: "p.recent.over_rate", args: { side: "p1", window: 5, threshold: 18.5 }, op: "gte", value: 60 },
        ] },
        action: { type: "total", targets: [1], side: "over", threshold: 18.5, confidence: 0.62 },
        summary: "Авто: доля ТБ 18.5 у игрока 1 за 5 игр ≥ 60% → ТБ 18.5, партии 1",
        conditions_text: "доля ТБ 18.5 у игрока 1 за 5 игр ≥ 60%",
        action_text: "ТБ 18.5, партии 1",
        precision: 72.7, coverage: 45.8, matched: 11, wins: 8, losses: 3,
      },
      {
        id: "auto_demo2", name: "Авто · П1, партии 2",
        enabled: true, priority: 105, stop: false, sport: settings.active_sport, auto: true,
        conditions: { logic: "and", conditions: [
          { metric: "p.recent.win_rate", args: { side: "p2", window: 5 }, op: "lte", value: 40 },
        ] },
        action: { type: "winner", targets: [2], side: "p1", threshold: 18.5, confidence: 0.61 },
        summary: "Авто: доля побед игрока 2 за 5 игр ≤ 40% → П1, партии 2",
        conditions_text: "доля побед игрока 2 за 5 игр ≤ 40%",
        action_text: "П1, партии 2",
        precision: 66.7, coverage: 37.5, matched: 9, wins: 6, losses: 3,
      },
      {
        id: "auto_demo3", name: "Авто-фильтр · пропустить матч",
        enabled: true, priority: 120, stop: true, sport: settings.active_sport, auto: true,
        conditions: { logic: "and", conditions: [
          { metric: "odds.p2", args: {}, op: "lt", value: 1.5 },
        ] },
        action: { type: "skip", targets: [1], side: "auto", threshold: 18.5, confidence: 0.6 },
        summary: "Авто-фильтр: коэффициент П2 < 1.5 → пропустить матч",
        conditions_text: "коэффициент П2 < 1.5",
        action_text: "пропустить матч",
        precision: 100, coverage: 16.7, matched: 4, wins: 0, losses: 4,
      },
    ];
  }

  function autoPayload() {
    return {
      ok: true, enabled: autoEnabled, mode: autoEnabled ? "constructor" : "builtin",
      engine_running: true, sport: settings.active_sport,
      sport_name: (sports.find(s => s.id === settings.active_sport) || sports[0]).name,
      min_precision: autoConfig.min_precision, min_samples: autoConfig.min_samples,
      max_rules: autoConfig.max_rules, interval_sec: 180,
      generated: autoEnabled ? autoSeed.length : 0,
      observations: autoEnabled ? 24 : 0,
      groups: [], updated_at: autoEnabled ? "21.10.2026 09:40" : "",
      rules: autoEnabled ? autoSeed : [],
      hint: autoEnabled
        ? "Правила пересчитываются каждые 3 минуты и после каждого нового результата."
        : "Авто-формирование выключено. Включите его, чтобы правила обновлялись сами.",
    };
  }

  const ctorPresets = [
    { name: "ТБ 18.5: оба верховые", category: "Тоталы", description: "У каждого ТБ 18.5 в партиях проходит минимум в 60% последних игр.", source: "PingPongBets · Over/Under", rule: { name: "ТБ 18.5: оба верховые", conditions: { logic: "and", conditions: [{ metric: "p.recent.over_rate", args: { side: "p1", window: 5, threshold: 18.5 }, op: "gte", value: 60 }] }, action: { type: "total", targets: [1, 2], side: "over", threshold: 18.5, confidence: 0.62 } } },
    { name: "ТБ 18.5: очные верховые", category: "Тоталы", description: "В 7 из 10 очных 1-я партия была ТБ 18.5.", source: "Table Tennis Totals", rule: { name: "ТБ 18.5: очные верховые", conditions: { logic: "and", conditions: [{ metric: "h2h.over_rate", args: { window: 10, set: 1, threshold: 18.5 }, op: "gte", value: 70 }] }, action: { type: "total", targets: [1], side: "over", threshold: 18.5, confidence: 0.64 } } },
    { name: "П1: форма + серия", category: "Победитель", description: "Игрок 1 берёт 60%+ последних игр и идёт на серии 2+ побед.", source: "SmartBettingGuide", rule: { name: "П1: форма + серия", conditions: { logic: "and", conditions: [{ metric: "p.recent.win_rate", args: { side: "p1", window: 5 }, op: "gte", value: 60 }] }, action: { type: "winner", targets: [1], side: "p1", threshold: 18.5, confidence: 0.6 } } },
    { name: "П2: очное доминирование", category: "Победитель", description: "Игрок 2 выиграл 60%+ очных при их количестве от пяти.", source: "Table Tennis Totals", rule: { name: "П2: очное доминирование", conditions: { logic: "and", conditions: [{ metric: "h2h.win_rate", args: { side: "p2", window: 10 }, op: "gte", value: 60 }] }, action: { type: "winner", targets: [1], side: "p2", threshold: 18.5, confidence: 0.62 } } },
    { name: "Пропуск: мало очных", category: "Фильтры", description: "Меньше трёх очных встреч — статистике нельзя доверять.", source: "Table Tennis Totals", rule: { name: "Пропуск: мало очных", conditions: { logic: "and", conditions: [{ metric: "h2h.count", args: {}, op: "lt", value: 3 }] }, action: { type: "skip", targets: [1], side: "auto", threshold: 18.5, confidence: 0.6 } } },
    { name: "ТБ 18.5: равные + верховые", category: "Комбинированные", description: "Ровная форма ±15 п.п. и средний тотал обоих от 18.5.", source: "DeuceLab · рынки", rule: { name: "ТБ 18.5: равные + верховые", conditions: { logic: "and", conditions: [{ metric: "cmp.win_rate_diff", args: { window: 5 }, op: "lte", value: 15 }, { metric: "cmp.avg_set_total_mean", args: { window: 5 }, op: "gte", value: 18.5 }] }, action: { type: "total", targets: [1, 2], side: "over", threshold: 18.5, confidence: 0.6 } } },
  ];

  function withSummaries(rules) {
    return rules.map(r => Object.assign({}, r, {
      summary: r.summary || ("ЕСЛИ " + (r.conditions_text || "условия") + " → " + (r.action_text || "")),
    }));
  }

  function analyzerRow(metric, args, op, value, text, lossShare, winShare, lossHits, winHits, examples) {
    const n = 12;
    return {
      metric, args, op, value,
      condition: { metric, args, op, value },
      text, unit: "%",
      coverage: 91.7,
      win_hits: winHits, win_n: n, win_share: winShare,
      loss_hits: lossHits, loss_n: n, loss_share: lossShare,
      lift: Math.round((winShare - lossShare) * 10) / 10,
      failure_score: Math.round(Math.max(0, lossShare - winShare) * lossShare) / 100,
      success_score: Math.round(Math.max(0, winShare - lossShare) * winShare) / 100,
      examples,
    };
  }

  const analyzerExamples = [
    { teams: "Иванов А. — Петров С.", verdict: "ТБ 18.5", score: "11:6, 9:11, 11:4", total: 21, sent_at: "18.10 14:30" },
    { teams: "Сидоров К. — Кузнецов Д.", verdict: "ТМ 18.5", score: "5:11, 11:8, 7:11", total: 15, sent_at: "18.10 16:10" },
    { teams: "Морозов И. — Волков П.", verdict: "П1", score: "11:9, 8:11, 11:7", total: 23, sent_at: "18.10 18:45" },
  ];

  function analyzerPayload(opts) {
    opts = opts || {};
    const kind = opts.kind || "all";
    const target = opts.target || "";
    const minGroup = Number(opts.min_group || 3);
    const minLift = Number(opts.min_lift || 20);
    const base = {
      ok: true,
      options: { kind, target, min_group: minGroup, min_lift: minLift, min_hits: 2,
        sport: opts.sport === "all" ? "" : (opts.sport || settings.active_sport) },
      observations: { total: 24, wins: 12, losses: 12, with_stats: 31 },
      min_group: minGroup,
      sufficient: true,
      generated_at: "20.10.2026 12:34",
    };
    if (target && target !== "set1") {
      return Object.assign({}, base, {
        observations: { total: 0, wins: 0, losses: 0, with_stats: 31 },
        sufficient: false,
        hint: "Мало данных для вывода: нужно минимум " + minGroup +
              " удачных и " + minGroup + " неудачных прогнозов, а сейчас 0 и 0.",
        failure: [], success: [], combos: { failure: [], success: [] }, means: [],
      });
    }
    if (kind === "winner") {
      return Object.assign({}, base, {
        observations: { total: 0, wins: 0, losses: 0, with_stats: 31 },
        sufficient: false,
        hint: "Мало данных для вывода: нужно минимум " + minGroup +
              " удачных и " + minGroup + " неудачных прогнозов, а сейчас 0 и 0.",
        failure: [], success: [], combos: { failure: [], success: [] }, means: [],
      });
    }
    const failure = [
      analyzerRow("p.recent.avg_set_total", { side: "p1", window: 5 }, "lte", 16,
        "Средний тотал партии игрока 1 за 5 игр ≤ 16", 100, 0, 12, 0, analyzerExamples),
      analyzerRow("p.recent.over_rate", { side: "p1", window: 5, threshold: 18.5 }, "lte", 20,
        "Доля ТБ18.5 в партиях игрока 1 за 5 игр ≤ 20%", 91.7, 8.3, 11, 1, analyzerExamples.slice(0, 1)),
      analyzerRow("h2h.avg_set_total", { window: 10 }, "lte", 17,
        "Средний тотал партии в очных встречах ≤ 17", 83.3, 16.7, 10, 2, analyzerExamples.slice(0, 2)),
      analyzerRow("p.recent.avg_match_total", { side: "p1", window: 5 }, "lte", 34,
        "Средний тотал матча игрока 1 за 5 игр ≤ 34", 75, 25, 9, 3, analyzerExamples),
      analyzerRow("odds.p1", { side: "p1" }, "gte", 2.3,
        "Кэф на игрока 1 ≥ 2.30", 66.7, 33.3, 8, 4, analyzerExamples.slice(0, 1)),
      analyzerRow("p.recent.win_rate", { side: "p1", window: 5 }, "lte", 40,
        "Доля побед игрока 1 за 5 игр ≤ 40%", 58.3, 25, 7, 3, analyzerExamples),
      analyzerRow("cmp.avg_set_total_lead", {}, "eq", "p2",
        "Средний тотал партии больше у игрока 2", 50, 33.3, 6, 4, analyzerExamples),
    ];
    const success = [
      analyzerRow("p.recent.avg_set_total", { side: "p1", window: 5 }, "gte", 20,
        "Средний тотал партии игрока 1 за 5 игр ≥ 20", 0, 100, 0, 12, analyzerExamples),
      analyzerRow("p.recent.over_rate", { side: "p1", window: 5, threshold: 18.5 }, "gte", 80,
        "Доля ТБ18.5 в партиях игрока 1 за 5 игр ≥ 80%", 8.3, 91.7, 1, 11, analyzerExamples.slice(0, 1)),
      analyzerRow("h2h.last_winner", {}, "is", "p1",
        "Последняя очная встреча за игроком 1", 16.7, 83.3, 2, 10, analyzerExamples.slice(0, 2)),
      analyzerRow("p.recent.avg_set_points", { side: "p1", window: 5 }, "gte", 6,
        "Средние очки игрока 1 в партии ≥ 6", 25, 75, 3, 9, analyzerExamples),
      analyzerRow("cmp.win_rate_lead", {}, "eq", "p1",
        "Доля побед выше у игрока 1", 33.3, 66.7, 4, 8, analyzerExamples.slice(0, 1)),
      analyzerRow("p.recent.streak", { side: "p1" }, "gte", 3,
        "Серия побед игрока 1 ≥ 3", 25, 58.3, 3, 7, analyzerExamples),
      analyzerRow("odds.favorite", {}, "is", "p1",
        "Фаворит букмекера — игрок 1", 33.3, 50, 4, 6, analyzerExamples),
    ];
    const combo = (left, right, winShare, lossShare) => ({
      conditions: [left.condition, right.condition],
      texts: [left.text, right.text],
      text: left.text + " И " + right.text,
      win_hits: Math.round(winShare / 100 * 12), win_n: 12, win_share: winShare,
      loss_hits: Math.round(lossShare / 100 * 12), loss_n: 12, loss_share: lossShare,
      lift: Math.round((winShare - lossShare) * 10) / 10,
      score: Math.round((winShare - lossShare) * winShare) / 100,
    });
    return Object.assign({}, base, {
      failure: failure,
      success: success,
      combos: {
        failure: [
          combo(failure[1], failure[4], 0, 83.3),
          combo(failure[0], failure[2], 8.3, 75),
        ],
        success: [
          combo(success[0], success[2], 83.3, 0),
        ],
      },
      means: [
        { metric: "p.recent.over_rate", args: { side: "p1", window: 5, threshold: 18.5 },
          label: "Доля ТБ18.5 в партиях игрока 1 за 5 игр", unit: "%",
          win_mean: 92.5, loss_mean: 14.6, delta: 77.9, normalized: 2,
          win_n: 12, loss_n: 12 },
        { metric: "p.recent.avg_set_total", args: { side: "p1", window: 5 },
          label: "Средний тотал партии игрока 1 за 5 игр", unit: "",
          win_mean: 21.4, loss_mean: 15.8, delta: 5.6, normalized: 1.71,
          win_n: 12, loss_n: 12 },
        { metric: "h2h.avg_match_total", args: { window: 10 },
          label: "Средний тотал матча в очных встречах", unit: "",
          win_mean: 74.2, loss_mean: 71.5, delta: 2.7, normalized: 0.44,
          win_n: 12, loss_n: 12 },
      ],
    });
  }

  window.PyApp = {
    constructor: (sport) => {
      const profile = sports.find(s => s.id === sport) || sports[0];
      const extra = autoEnabled
        ? autoCtorRules().filter(rule => !ctorRules.some(item => item.id === rule.id))
        : [];
      const rules = ctorRules.concat(extra);
      return JSON.stringify({
        ok: true, sport: profile.id, sport_name: profile.name,
        mode: "constructor", rules: withSummaries(rules),
        catalog: Object.assign({}, ctorCatalog, {
          sport: profile.id, sport_name: profile.name,
          default_total: profile.id === "table_tennis" ? 18.5 : (profile.id === "football" ? 2.5 : 5.5),
          bets: profile.bets,
        }),
        presets: ctorPresets,
        stats: { rules: rules.length, matches: 12, fired: 5, skipped: 2 },
        file: "/data/constructor_rules.json",
      });
    },
    setSport: (sport) => {
      const profile = sports.find(s => s.id === sport) || sports[0];
      settings.active_sport = profile.id;
      return JSON.stringify({ ok: true, sport: profile.id, name: profile.name });
    },
    saveConstructor: (json) => {
      try {
        const data = JSON.parse(json);
        ctorRules = (data.rules || []).map((r, i) => Object.assign({}, r, {
          summary: "ЕСЛИ " + (r.conditions && r.conditions.conditions ? r.conditions.conditions.length : 0) + " условие(й) → " + ((r.action && r.action.type) || ""),
          conditions_text: "условие(я): " + (r.conditions && r.conditions.conditions ? r.conditions.conditions.length : 0),
          action_text: (r.action && r.action.type) === "skip" ? "пропустить матч" : "ТБ/ТМ партии",
        }));
        return JSON.stringify({ ok: true, errors: [], rules: withSummaries(ctorRules), mode: data.mode || "constructor", stats: { rules: ctorRules.length, matches: 12, fired: 5, skipped: 2 } });
      } catch (e) {
        return JSON.stringify({ ok: false, errors: ["Некорректный JSON"], rules: withSummaries(ctorRules) });
      }
    },
    setAlgorithmMode: (mode) => JSON.stringify({ ok: true, mode: mode === "constructor" ? "constructor" : "builtin" }),
    testConstructor: () => JSON.stringify({
      ok: true, checked: 2, items: [
        { team1: "Иванов А.", team2: "Петров С.", league: "Pro League", date: "19.10 14:30",
          h2h: 10, recent1: 5, recent2: 5,
          fired: [{ id: "r1", name: "ТБ 18.5: форма + последняя очная", details: ["Средний тотал партии игрока 1 (= 21.4) > 19"] }],
          skip: null,
          predictions: [{ label: "Партия 1 (ТБ18.5/ТМ18.5)", verdict: "ТБ 18.5", confidence: 65, reason: "Конструктор · «ТБ 18.5: форма»: Средний тотал партии игрока 1 (= 21.4) > 19" }] },
        { team1: "Сидоров К.", team2: "Кузнецов Д.", league: "TT Cup", date: "19.10 15:00",
          h2h: 4, recent1: 5, recent2: 4, fired: [], skip: null, predictions: [] },
      ],
    }),
    state: () => JSON.stringify({
      running: true, engine_running: true, stats: {
        checked: 18, sent: 3, skipped: 11, blocked_odds: 1, blocked_settings: 2, blocked_general: 1,
        no_h2h: 0, short_seq: 0, no_top: 0, by_target: {},
      },
      last_cycle: now(), last_error: null, live_matches: 24,
      live_by_sport: { table_tennis: 6, football: 5, hockey: 4, basketball: 3, volleyball: 3, tennis: 3 },
      processed: 12,
      sport: settings.active_sport, sport_name: (sports.find(s => s.id === settings.active_sport) || sports[0]).name,
      telegram_configured: false, cycles: 6, started_at: "19.10.2026 14:20",
      telegram: { enabled: true, configured: false },
      neural: nnStatus(),
      ai: aiStatus(),
      advice: aiAlerts,
      paths: { data: "/data/user/0/by.betcity.predictor/files/predictor_data", log: "…", csv: "…" },
      version: "1.11.0",
    }),
    start: () => JSON.stringify({ ok: true, running: true }),
    stop: () => JSON.stringify({ ok: true, running: false }),
    runOnce: () => JSON.stringify({ ok: true, summary: { matches: 24, upcoming: 7, signals: 2, sports: 6, deferred: 3, by_sport: { table_tennis: 6, football: 5, hockey: 4, basketball: 3, volleyball: 3, tennis: 3 }, error: null } }),
    version: () => JSON.stringify({ version: "1.11.0" }),
    settings: () => JSON.stringify({ settings, defaults: settings, sports }),
    saveSettings: (json) => {
      try {
        const data = JSON.parse(json);
        Object.keys(data).forEach((key) => {
          if (key === "neural") settings.neural = Object.assign({}, settings.neural, data.neural);
          else settings[key] = data[key];
        });
        return JSON.stringify({ ok: true, settings });
      } catch (e) {
        return JSON.stringify({ ok: false, error: String(e) });
      }
    },
    resetSettings: () => JSON.stringify({ ok: true, settings }),
    logs: (since, limit, level, search) => {
      let items = logs.filter(e => e.id > since);
      if (level) items = items.filter(e => e.level === level);
      if (search) items = items.filter(e => e.message.toLowerCase().includes(search.toLowerCase()));
      return JSON.stringify({ items, last_id: items.length ? items[items.length - 1].id : since });
    },
    clearLogs: () => JSON.stringify({ ok: true }),
    errors: (limit) => JSON.stringify({ items: logs.filter(e => e.level === "ERROR").slice(-limit) }),
    queue: () => JSON.stringify({ items: queue.slice(), total: queue.length, upcoming: 2, ts: now(), error: null }),
    refreshQueue: () => JSON.stringify({ ok: true, items: queue.slice(), ts: now() }),
    clearProcessed: () => JSON.stringify({ ok: true }),
    predictions: (limit, sport) => {
      let items = predictions.slice();
      if (sport) items = items.filter(p => p.sport === sport);
      return JSON.stringify({ items: items.slice(0, limit), total: items.length });
    },
    results: (start, end, search, status, limit, sport) => {
      let items = results.slice();
      if (sport) items = items.filter(g => g.sport === sport);
      const needle = String(search || "").toLowerCase();
      if (needle) items = items.filter(g =>
        (g.team1 + " " + g.team2).toLowerCase().includes(needle) ||
        String(g.league || "").toLowerCase().includes(needle));
      if (start) items = items.filter(g => g.sent_at >= start);
      if (end) items = items.filter(g => g.sent_at <= end);
      if (status === "win") items = items.filter(g => g.wins > 0 && g.losses === 0);
      if (status === "loss") items = items.filter(g => g.losses > 0);
      if (status === "pending") items = items.filter(g => g.pending > 0);
      const preds = items.reduce((n, g) => n + g.rows.length, 0);
      const wins = items.reduce((n, g) => n + g.wins, 0);
      const losses = items.reduce((n, g) => n + g.losses, 0);
      const pending = items.reduce((n, g) => n + g.pending, 0);
      const finished = wins + losses;
      const aiRows = items.reduce((n, g) =>
        n + g.rows.filter(r => r.source === "ai").length, 0);
      const aiWins = items.reduce((n, g) =>
        n + g.rows.filter(r => r.source === "ai" && r.success === true).length, 0);
      const aiLosses = items.reduce((n, g) =>
        n + g.rows.filter(r => r.source === "ai" && r.success === false).length, 0);
      return JSON.stringify({
        items, total: items.length,
        summary: { games: items.length, preds, wins, losses, pending,
          hit_rate: finished ? Math.round(wins / finished * 1000) / 10 : 0,
          ai_preds: aiRows, ai_wins: aiWins, ai_losses: aiLosses,
          ai_pending: aiRows - aiWins - aiLosses,
          from_cache: items.filter(g => g.from_cache).length },
      });
    },
    stats: () => JSON.stringify(stats),
    analyzer: (payload) => {
      let opts = {};
      try { opts = JSON.parse(payload || "{}"); } catch (e) { opts = {}; }
      return JSON.stringify(analyzerPayload(opts));
    },
    autoRules: (payload) => {
      let opts = {};
      try { opts = JSON.parse(payload || "{}"); } catch (e) { opts = {}; }
      const action = String(opts.action || "status").toLowerCase();
      if (action === "enable" || action === "on") autoEnabled = true;
      if (action === "disable" || action === "off") autoEnabled = false;
      if (action === "configure") {
        if (opts.min_precision !== undefined) autoConfig.min_precision = Number(opts.min_precision);
        if (opts.min_samples !== undefined) autoConfig.min_samples = Number(opts.min_samples);
        if (opts.max_rules !== undefined) autoConfig.max_rules = Number(opts.max_rules);
      }
      return JSON.stringify(autoPayload());
    },
    neural: (payload) => {
      let opts = {};
      try { opts = JSON.parse(payload || "{}"); } catch (e) { opts = {}; }
      const action = String(opts.action || "status").toLowerCase();
      if (action === "enable" || action === "on") settings.neural.enabled = true;
      if (action === "disable" || action === "off") settings.neural.enabled = false;
      if (action === "train" || action === "run" || action === "update") {
        settings.neural.enabled = true;
      }
      if (action === "reset" || action === "clear") {
        settings.neural.enabled = false;
      }
      if (action === "rollback") {
        nnRolledBack = opts.sport || "";
      }
      if (action === "configure") {
        ["min_samples", "min_confidence", "sets"].forEach((key) => {
          if (opts[key] !== undefined) settings.neural[key] = Number(opts[key]);
        });
        if (opts.sports !== undefined) settings.neural.sports = (opts.sports || []).slice();
        if (opts.markets !== undefined) settings.neural.markets = opts.markets || {};
        if (opts.auto_train !== undefined) settings.neural.auto_train = !!opts.auto_train;
      }
      return JSON.stringify({ ok: true, action, status: nnStatus() });
    },
    ai: (payload) => {
      let opts = {};
      try { opts = JSON.parse(payload || "{}"); } catch (e) { opts = {}; }
      const action = String(opts.action || "status").toLowerCase();
      if (action === "status") {
        return JSON.stringify({ ok: true, status: aiStatus() });
      }
      if (action === "test") {
        if (!settings.ai.api_key) {
          return JSON.stringify({ ok: false, error: "Не задан ключ API" });
        }
        return JSON.stringify({ ok: true, text: "работает" });
      }
      if (action === "job") {
        const job = aiJobs[opts.id];
        if (!job) return JSON.stringify({ ok: false, error: "Задача не найдена" });
        return JSON.stringify({ ok: true, job: opts.id, status: job.status, text: job.text, error: job.error || "" });
      }
      if (action === "messages") {
        return JSON.stringify({ ok: true, messages: aiMessages });
      }
      if (action === "inspect") {
        return JSON.stringify({ ok: true, alerts: aiAlerts });
      }
      if (action === "apply") {
        const act = (opts.payload && opts.payload.action) || {};
        return JSON.stringify({ ok: true, message: "Действие выполнено: " + (act.label || act.type || ""), alerts: aiAlerts });
      }
      if (action === "chat") {
        const question = (opts.payload && opts.payload.question) || "";
        aiMessages.push({ role: "user", text: question, at: "2026-10-22T12:00:00" });
        const answer = "По вашему вопросу «" + question + "»:\n\n1. Сейчас активный вид — настольный теннис, правил включено 3, примеров нейросети 214, точность 61% при базе 52%.\n2. Ошибок в логе за последний час — 2, это не критично.\n3. Что делать: добавьте шаблоны для хоккея (кнопка «Шаблоны» в «Правилах»), иначе по нему прогнозов не будет.\n4. Нейросеть по футболу переобучается — я бы заморозил обучение кнопкой в карточке «Помощник».";
        aiMessages.push({ role: "assistant", text: answer, at: "2026-10-22T12:00:01" });
        const jobId = "mock_chat_" + Object.keys(aiJobs).length;
        aiJobs[jobId] = { status: "done", text: answer, error: "" };
        return JSON.stringify({ ok: true, job: jobId });
      }
      const answers = aiAnswers;
      const text = answers[action] || "Демо-ответ модели.";
      const jobId = "mock_" + action + "_" + Object.keys(aiJobs).length;
      aiJobs[jobId] = { status: "done", text: text, error: "" };
      return JSON.stringify({ ok: true, job: jobId });
    },
    resetStats: () => JSON.stringify({ ok: true }),
    testConnection: () => JSON.stringify({ betcity: true, telegram: null, matches: 24, error: null }),
    exportData: (kind) => JSON.stringify({
      ok: true, filename: kind + "_test.txt", mime: "text/plain",
      content: "Тестовый экспорт: " + kind,
    }),
    clearData: (what) => JSON.stringify({ ok: true, cleared: [what] }),
    saveFile: () => { },
    shareFile: () => { },
    toast: (m) => console.log("toast:", m),
    notifySignal: () => { },
    keepScreenOn: () => { },
    platform: () => "browser",
  };
})();

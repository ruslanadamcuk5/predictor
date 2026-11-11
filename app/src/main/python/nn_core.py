# -*- coding: utf-8 -*-
"""Нейросеть Predictor: признаки, метки и обучение.

Модуль не зависит от Android и не ходит в сеть. Три части:

1. **Признаки** — фиксированный вектор чисел, собранный из метрик
   конструктора (``constructor_engine.evaluate_metric``). Один и тот же
   список признаков используется при обучении и при прогнозе, поэтому
   сеть видит ровно те сигналы, что и правила пользователя.
2. **Метки** — что фактически случилось в матче: победитель, ничья,
   тотал. Считаются из финального счёта Betcity.
3. **Многослойный персептрон** с сигмоидными выходами: одна голова на
   каждый рынок (П1 / П2 / ничья / тотал). Обучение — mini-batch SGD с
   импульсом, только на чистом Python, без внешних пакетов.

Сеть работает по видам спорта раздельно: у настольного тенниса признаки
по партиям, у командных видов — по матчу.
"""

from __future__ import annotations

import math
import random

import constructor_engine as ctor
import sports

# --------------------------------------------------------------------------
# признаки
# --------------------------------------------------------------------------

# Признаки командных видов: форма, очные встречи, коэффициенты, линия.
TEAM_FEATURES = [
    ("p.recent.win_rate", {"side": "p1", "window": 5}),
    ("p.recent.win_rate", {"side": "p2", "window": 5}),
    ("p.recent.draw_rate", {"side": "p1", "window": 5}),
    ("p.recent.draw_rate", {"side": "p2", "window": 5}),
    ("p.recent.avg_match_total", {"side": "p1", "window": 5}),
    ("p.recent.avg_match_total", {"side": "p2", "window": 5}),
    ("p.recent.trend_total", {"side": "p1", "window": 5}),
    ("p.recent.trend_total", {"side": "p2", "window": 5}),
    ("p.recent.avg_margin", {"side": "p1", "window": 5}),
    ("p.recent.avg_margin", {"side": "p2", "window": 5}),
    ("p.recent.days_since_last", {"side": "p1"}),
    ("p.recent.days_since_last", {"side": "p2"}),
    ("h2h.count", {}),
    ("h2h.win_rate", {"side": "p1", "window": 10}),
    ("h2h.draw_rate", {"window": 10}),
    ("h2h.avg_match_total", {"window": 10}),
    ("h2h.avg_match_margin", {"window": 10}),
    ("h2h.days_since_last", {}),
    ("odds.implied_p1", {}),
    ("odds.implied_p2", {}),
    ("odds.implied_draw", {}),
    ("odds.total_line", {}),
    ("odds.handicap", {}),
    ("odds.handicap_p1", {}),
    ("odds.handicap_p2", {}),
    ("page.total_line", {}),
    ("page.over_share_last5", {}),
    ("p.recent.btts_rate", {"side": "p1", "window": 5}),
    ("p.recent.btts_rate", {"side": "p2", "window": 5}),
    ("h2h.btts_rate", {"window": 10}),
    ("p.recent.match_over_rate", {"side": "p1", "window": 5}),
    ("p.recent.match_over_rate", {"side": "p2", "window": 5}),
]

# Признаки настольного тенниса: статистика по партиям.
TT_FEATURES = [
    ("p.recent.set_win_rate", {"side": "p1", "window": 5, "set": 1}),
    ("p.recent.set_win_rate", {"side": "p2", "window": 5, "set": 1}),
    ("p.recent.set_avg_total", {"side": "p1", "window": 5, "set": 1}),
    ("p.recent.set_avg_total", {"side": "p2", "window": 5, "set": 1}),
    ("p.recent.set_avg_points", {"side": "p1", "window": 5, "set": 1}),
    ("p.recent.set_avg_points", {"side": "p2", "window": 5, "set": 1}),
    ("p.recent.set_over_rate",
     {"side": "p1", "window": 5, "set": 1, "threshold": 18.5}),
    ("p.recent.set_over_rate",
     {"side": "p2", "window": 5, "set": 1, "threshold": 18.5}),
    ("p.recent.first_set_win_rate", {"side": "p1", "window": 5}),
    ("p.recent.first_set_win_rate", {"side": "p2", "window": 5}),
    ("p.recent.avg_match_total", {"side": "p1", "window": 5}),
    ("p.recent.avg_match_total", {"side": "p2", "window": 5}),
    ("p.recent.days_since_last", {"side": "p1"}),
    ("p.recent.days_since_last", {"side": "p2"}),
    ("h2h.count", {}),
    ("h2h.set_win_rate", {"side": "p1", "window": 10, "set": 1}),
    ("h2h.avg_set_total", {"window": 10, "set": 1}),
    ("h2h.avg_set_points", {"side": "p1", "window": 10, "set": 1}),
    ("h2h.avg_sets", {"window": 10}),
    ("h2h.days_since_last", {}),
    ("odds.implied_p1", {}),
    ("odds.implied_p2", {}),
    ("odds.total_line", {}),
    ("page.total_line", {}),
    ("page.over_share_last5", {}),
]

TEAM_HEADS = ["p1", "p2", "draw", "over", "handicap", "btts"]
TT_HEADS = ["p1", "p2", "over"]

# Типы рынков, которые сеть умеет прогнозировать, и их подписи.
MARKET_LABELS = {
    "winner": "Победитель",
    "total": "Тотал",
    "handicap": "Фора",
    "btts": "Обе забьют",
}

# Версия правил разметки. Строки выборки без версии (или со старой
# версией) могли быть размечены прежним парсером счёта; их не обучаем
# вслепую, а сохраняем в архиве.
LABEL_VERSION = 3

# Ревизия обучения. 1.29 добавила отдельные модели рынков (тотал, фора,
# обе забьют) и диагностику по рынкам, поэтому старые модели нужно один
# раз переобучить: у них ещё нет проверки специалистов на отложенных
# матчах.
TRAIN_REVISION = 3

# Версия вектора признаков. 1 — «сырые» метрики конструктора, 2 — они же
# плюс производные разности (линия тотала, фора, форма, коэффициенты).
# Старые модели читаются с версией 1, чтобы не сломать уже собранные
# прогнозы; новые всегда обучаются на версии 2.
FEATURE_VERSION = 2

# Минимум обучающих примеров на голову, чтобы рынок давал прогноз.
# Рынок без покрытия или без перевеса над «всегда самый частый класс»
# молчит: редкие и случайные сигналы не должны выглядеть уверенными.
MARKET_MIN_TRAIN_SAMPLES = 20
# Минимальный перевес над «всегда самый частый класс». 1 п.п. — это шум
# на выборке в сотни матчей; 2 п.п. уже отличимы от случайности.
MARKET_MIN_LIFT = 0.02
# Дополнительный перевес за каждую долю строк со старой разметкой.
# Футбол/теннис/волейбол до 1.25 могли размечаться по счёту периода,
# поэтому при legacy_risk ≈ 1 рынку нужно на 3 п.п. больше.
MARKET_LEGACY_LIFT = 0.03
# Виды спорта, где прежний парсер мог взять счёт периода за итог матча.
# Их строки без LABEL_VERSION не выбрасываем (данных и так мало), но
# учим с пониженным весом: сигнал есть, доверия меньше.
LEGACY_RISK_SPORTS = ("football", "tennis", "volleyball")
LEGACY_SAMPLE_WEIGHT = 0.35
# Пределы температуры калибровки: 1.0 — вероятности уже честные,
# больше 1 — модель была слишком самоуверенна и её ответы сжимаются.
TEMPERATURE_RANGE = (0.35, 5.0)
# Если класс почти всегда один (ничьих нет, обе забьют всегда «нет»),
# базовый уровень близок к 100%, и требовать перевеса бессмысленно:
# достаточно не ошибаться на этом классе.
MARKET_DEGENERATE_BASELINE = 0.9

# Рынки, для которых можно обучать отдельную модель. Победитель сюда не
# входит: его голова — основа текущей сети, и её нельзя менять незаметно.
SPECIALIST_HEADS = {"total": "over", "handicap": "handicap",
                    "btts": "btts"}
# Минимум проверочных исходов у отдельной модели рынка: на двух-трёх
# матчах «перевес» — это случайность.
SPECIALIST_MIN_VAL_SAMPLES = 8


def required_lift(meta):
    """Какой перевес над базой нужен рынку с такой долей старой разметки."""
    try:
        risk = float((meta or {}).get("legacy_risk") or 0.0)
    except (TypeError, ValueError):
        risk = 0.0
    risk = min(1.0, max(0.0, risk))
    return MARKET_MIN_LIFT + MARKET_LEGACY_LIFT * risk


def head_ready(meta, head):
    """Готова ли голова рынка к прогнозам по своей выборке.

    Модель без отчёта по головам считается неготовой: это старая модель,
    которую нужно переобучить. Иначе рынки без проверенного перевеса
    продолжали бы давать прогнозы «по инерции».

    Чем выше доля строк со старой разметкой (``legacy_risk``), тем больше
    нужен перевес над базой: непроверенные метки не должны превращаться
    в уверенные сигналы.
    """
    meta = meta or {}
    coverage = meta.get("head_train_samples") or {}
    if not isinstance(coverage, dict) or head not in coverage:
        return False
    try:
        samples = int(coverage.get(head) or 0)
    except (TypeError, ValueError):
        samples = 0
    if samples < MARKET_MIN_TRAIN_SAMPLES:
        return False
    accuracy = (meta.get("head_accuracy") or {}).get(head)
    baseline = (meta.get("head_baseline") or {}).get(head)
    if accuracy is None or baseline is None:
        return False
    try:
        accuracy = float(accuracy)
        baseline = float(baseline)
        required = required_lift(meta)
        if baseline >= MARKET_DEGENERATE_BASELINE:
            return accuracy >= baseline - MARKET_MIN_LIFT
        return accuracy >= baseline + required
    except (TypeError, ValueError):
        return False


def market_kinds(sport):
    """Рынки, доступные нейросети для вида спорта."""
    sport = sports.normalize_sport(sport)
    bets = sports.profile(sport).get("bets") or []
    kinds = []
    if "winner2" in bets or "winner3" in bets:
        kinds.append("winner")
    if "total" in bets:
        kinds.append("total")
    if "handicap" in bets:
        kinds.append("handicap")
    if "btts" in bets:
        kinds.append("btts")
    return kinds

# Длина вектора признаков: список метрик + доля доступных метрик.
# Для настольного тенниса добавляется номер партии (1..5 -> 0.2..1.0).


def feature_spec(sport):
    """Возвращает (список (metric_id, args), раскладка, признаков)."""
    sport = sports.normalize_sport(sport)
    if sport == "table_tennis":
        return TT_FEATURES, TT_HEADS, "tt"
    return TEAM_FEATURES, TEAM_HEADS, "team"


def feature_size(sport):
    spec, _heads, layout = feature_spec(sport)
    return len(spec) + 1 + (1 if layout == "tt" else 0)


def set_slot(sport):
    """Индекс слота с номером партии (только для настольного тенниса)."""
    spec, _heads, layout = feature_spec(sport)
    if layout != "tt":
        return -1
    return len(spec) + 1


# Производные признаки: разности «команда минус линия/фора», сравнение
# формы и вероятностей из коэффициентов. Сырые метрики по отдельности
# слабо связаны с исходом (средний тотал сам по себе ничего не говорит),
# а их разность с линией рынка — говорит. Список фиксирован, поэтому
# размер вектора не зависит от вида спорта: отсутствующие метрики дают
# нули и просто не участвуют.
DERIVED_FEATURES = 13


def expand_features(sport, x):
    """Дополняет вектор признаков производными разностями (версия 2).

    Функция обязана быть чистой и детерминированной: тот же вектор
    признаков используется и при обучении, и при прогнозе. Индексы
    берутся из ``feature_spec`` по именам метрик, поэтому порядок
    признаков можно менять без пересчёта сохранённых моделей.
    """
    sport = sports.normalize_sport(sport)
    spec, _heads, _layout = feature_spec(sport)
    values = list(x or [])
    index = {}
    for position, (name, _args) in enumerate(spec):
        index.setdefault(name, []).append(position)

    def one(name, default=0.0):
        positions = index.get(name) or []
        if positions and positions[0] < len(values):
            try:
                return float(values[positions[0]])
            except (TypeError, ValueError):
                return default
        return default

    def pair(name):
        positions = index.get(name) or []
        out = []
        for position in positions[:2]:
            try:
                out.append(float(values[position]))
            except (TypeError, ValueError, IndexError):
                out.append(0.0)
        while len(out) < 2:
            out.append(0.0)
        return out[0], out[1]

    # Линия тотала: сначала из коэффициентов, иначе со страницы, иначе
    # стандартная для вида — ровно так же, как размечен тотал.
    line = one("odds.total_line")
    if line <= 0.0:
        line = one("page.total_line")
    if line <= 0.0:
        try:
            line = float(sports.default_total(sport))
        except (TypeError, ValueError):
            line = 0.0
    handicap = one("odds.handicap")
    avg_total_1, avg_total_2 = pair("p.recent.avg_match_total")
    avg_margin_1, avg_margin_2 = pair("p.recent.avg_margin")
    win_rate_1, win_rate_2 = pair("p.recent.win_rate")
    btts_1, btts_2 = pair("p.recent.btts_rate")
    days_1, days_2 = pair("p.recent.days_since_last")
    h2h_total = one("h2h.avg_match_total", one("h2h.avg_set_total"))
    h2h_margin = one("h2h.avg_match_margin")
    h2h_btts = one("h2h.btts_rate")
    # У настольного тенниса средний тотал очной встречи — это тотал
    # партии, а линия в коэффициентах — тотал матча. Сравнивать их
    # напрямую нельзя: берём линию партии.
    h2h_line = tt_line(line) if sport == "table_tennis" else line
    implied_1 = one("odds.implied_p1")
    implied_2 = one("odds.implied_p2")
    implied_draw = one("odds.implied_draw")
    over_share = one("page.over_share_last5")
    return values + [
        avg_total_1 - line,
        avg_total_2 - line,
        (avg_total_1 + avg_total_2) / 2.0 - line,
        h2h_total - h2h_line,
        avg_margin_1 - handicap,
        avg_margin_2 - handicap,
        h2h_margin - handicap,
        win_rate_1 - win_rate_2,
        (btts_1 + btts_2) / 2.0 - h2h_btts,
        implied_1 - implied_2,
        implied_draw,
        over_share - 0.5,
        days_1 - days_2,
    ]


def model_features(model, features):
    """Признаки в версии, на которой обучалась модель."""
    version = 1
    try:
        version = int((model or {}).get("feature_version") or 1)
    except (TypeError, ValueError):
        version = 1
    if version < 2:
        return list(features or [])
    return expand_features((model or {}).get("sport") or "", features)


def _handicap_value(odds):
    """Линия форы со стороны первой команды (None, если её нет)."""
    try:
        value = (odds or {}).get("handicap")
    except AttributeError:
        return None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_features(match, stats, sport):
    """Собирает вектор признаков по матчу.

    Возвращает (features, meta). meta содержит линию тотала и прочие
    поля, нужные для меток.
    """
    sport = sports.normalize_sport(sport)
    spec, _heads, layout = feature_spec(sport)
    ctx = ctor.Context(match, stats)
    values = []
    available = 0
    for metric_id, args in spec:
        value = ctor.evaluate_metric(ctx, metric_id, dict(args))
        if value is None:
            values.append(0.0)
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            values.append(0.0)
            continue
        available += 1
        values.append(value)

    total = len(spec)
    coverage = available / float(total) if total else 0.0
    features = values + [coverage]
    if layout == "tt":
        features.append(0.0)  # номер партии заполняется при разметке

    odds = (match or {}).get("odds") or {}
    line = odds.get("total_line")
    if line is None:
        line = (stats or {}).get("page_total", {}).get("line")
    if line is None:
        line = sports.default_total(sport)
    try:
        line = float(line)
    except (TypeError, ValueError):
        line = float(sports.default_total(sport))

    meta = {
        "sport": sport,
        "layout": layout,
        "line": line,
        "handicap": _handicap_value(odds),
        "teams": [(match or {}).get("team1", ""), (match or {}).get("team2", "")],
        "date": (match or {}).get("date", ""),
        "coverage": coverage,
    }
    return features, meta


# --------------------------------------------------------------------------
# метки
# --------------------------------------------------------------------------


def tt_sets(score_text):
    """Разбирает счёт настольного тенниса на список сыгранных партий.

    В live-фиде Betcity у завершённого матча ``sc_inter`` содержит счёт
    каждой партии: «9:11, 11:9, 12:10, 5:11, 7:11». Незавершённая партия
    отбрасывается.
    """
    sets = []
    for p1, p2 in sports.score_pairs(score_text):
        if (p1 >= 11 or p2 >= 11) and abs(p1 - p2) >= 2:
            sets.append((int(p1), int(p2)))
    return sets


def tt_line(line=None):
    """Линия тотала одной партии.

    Betcity в главном рынке отдаёт тотал матча (например, 75.5), а не
    партии. Поэтому линию партии берём только из «правдоподобного»
    диапазона, иначе — стандартные 18.5.
    """
    default = float(sports.default_total("table_tennis"))
    try:
        value = float(line)
    except (TypeError, ValueError):
        return default
    if 5.0 <= value <= 40.0:
        return value
    return default


def labels_for_match(sport, score_text, line=None, handicap=None):
    """Размечает финальный счёт.

    Возвращает список словарей: {"y": [...], "m": [...], "set": N}.
    Для командных видов — одна строка на матч, для настольного тенниса —
    по одной строке на каждую сыгранную партию.

    Маска m гасит головы, которых в этом матче нет: ничья без рынка 1X2,
    фора без линии в коэффициентах, «обе забьют» там, где рынка нет.
    """
    sport = sports.normalize_sport(sport)
    _spec, heads, layout = feature_spec(sport)
    profile = sports.profile(sport)
    has_draw = bool(profile["has_draw"])
    bets = profile.get("bets") or []

    if layout == "tt":
        threshold = tt_line(line)
        rows = []
        for index, period in enumerate(tt_sets(score_text), 1):
            p1, p2 = period
            rows.append({
                "y": [1.0 if p1 > p2 else 0.0,
                      1.0 if p2 > p1 else 0.0,
                      1.0 if (p1 + p2) > threshold else 0.0],
                "m": [1.0, 1.0, 1.0],
                "set": index,
                "v": LABEL_VERSION,
            })
        return rows

    parsed = sports.parse_score(sport, score_text)
    if not parsed:
        return []
    match_score = parsed["match"]
    total = parsed.get("total")
    points = parsed.get("points")
    if line is None:
        line = float(sports.default_total(sport))
    line = float(line)
    p1, p2 = int(match_score[0]), int(match_score[1])
    match_known = bool(parsed.get("match_known", True))

    # Фора: в волейболе и теннисе она считается по очкам, а не по
    # выигранным партиям. Если очков нет (пришёл только счёт партий),
    # голову форы гасим маской, а не размечаем наугад.
    handicap_mask = 0.0
    handicap_label = 0.0
    if handicap is not None and "handicap" in bets and points is not None:
        try:
            h = float(handicap)
        except (TypeError, ValueError):
            h = None
        if h is not None:
            margin = int(points[0]) - int(points[1])
            if abs(margin + h) > 1e-9:
                handicap_mask = 1.0
                handicap_label = 1.0 if (margin + h) > 0 else 0.0

    btts_mask = 1.0 if "btts" in bets else 0.0
    btts_label = 1.0 if (p1 > 0 and p2 > 0) else 0.0

    total_mask = 1.0 if total is not None else 0.0
    total_label = 0.0
    if total is not None:
        total_label = 1.0 if total > line else 0.0

    y = [
        1.0 if p1 > p2 else 0.0,
        1.0 if p2 > p1 else 0.0,
        1.0 if (p1 == p2 and match_known) else 0.0,
        total_label,
        handicap_label,
        btts_label,
    ]
    m = [1.0 if match_known else 0.0,
         1.0 if match_known else 0.0,
         1.0 if has_draw else 0.0, total_mask,
         handicap_mask, btts_mask]

    # Согласованность победителя: если итог матча («3:1») не совпадает
    # с числом выигранных партий, доверять нельзя ни тому, ни другому.
    # Гасим головы победителя, но сохраняем строку ради тотала.
    periods = parsed.get("periods") or []
    if profile.get("score_mode") == "sets" and len(periods) >= 2:
        won = (sum(1 for a, b in periods if a > b),
               sum(1 for a, b in periods if b > a))
        if won != (p1, p2):
            m[0] = m[1] = m[2] = 0.0

    # Строка без единой активной головы не нужна обучению: в ней нет
    # ни одного проверенного исхода. Такие строки не создаём.
    if not any(value > 0 for value in m):
        return []
    return [{"y": y, "m": m, "set": 0, "v": LABEL_VERSION}]


# --------------------------------------------------------------------------
# многослойный персептрон
# --------------------------------------------------------------------------


def sigmoid(value):
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_v = math.exp(value)
    return exp_v / (1.0 + exp_v)


class MLP:
    """Простой многослойный персептрон с сигмоидными выходами."""

    ACTIVATIONS = ("tanh", "relu", "sigmoid")

    def __init__(self, sizes, seed=7, activation="tanh"):
        self.sizes = list(sizes)
        self.activation = activation if activation in self.ACTIVATIONS else "tanh"
        rng = random.Random(seed)
        self.weights = []
        self.biases = []
        for index in range(len(self.sizes) - 1):
            n_in = self.sizes[index]
            n_out = self.sizes[index + 1]
            limit = math.sqrt(6.0 / float(n_in + n_out))
            self.weights.append([
                [rng.uniform(-limit, limit) for _ in range(n_in)]
                for _ in range(n_out)
            ])
            self.biases.append([0.0] * n_out)
        self._momentum_w = [[[0.0] * len(row) for row in layer]
                            for layer in self.weights]
        self._momentum_b = [[0.0] * len(row) for row in self.biases]

    # ---------- прямое распространение ----------
    def _hidden_activation(self, value):
        if self.activation == "relu":
            return value if value > 0.0 else 0.0
        if self.activation == "sigmoid":
            return sigmoid(value)
        return math.tanh(value)

    def _hidden_derivative(self, activated):
        """Производная по выходу активации (для обратного прохода)."""
        if self.activation == "relu":
            return 1.0 if activated > 0.0 else 0.0
        if self.activation == "sigmoid":
            return activated * (1.0 - activated)
        return 1.0 - activated * activated

    def forward(self, x):
        acts = [list(x)]
        last = len(self.weights) - 1
        for index, (layer, bias) in enumerate(zip(self.weights, self.biases)):
            prev = acts[-1]
            z = []
            for row, b in zip(layer, bias):
                total = b
                for k, value in enumerate(row):
                    total += value * prev[k]
                z.append(total)
            if index == last:
                acts.append([sigmoid(v) for v in z])
            else:
                acts.append([self._hidden_activation(v) for v in z])
        return acts

    def predict(self, x):
        return self.forward(x)[-1]

    def logits(self, x):
        """Сырые выходы последнего слоя (до сигмоиды).

        Нужны для калибровки температуры: делить на температуру можно
        только логиты, а не уже сжатые вероятности.
        """
        acts = self.forward(x)
        if not self.weights:
            return list(acts[-1])
        prev = acts[-2]
        layer = self.weights[-1]
        bias = self.biases[-1]
        return [b + sum(w * v for w, v in zip(row, prev))
                for row, b in zip(layer, bias)]

    # ---------- обучение ----------
    def train_batch(self, rows, lr=0.05, momentum=0.9, l2=0.0):
        """Один шаг mini-batch. rows: список (x, y, mask) или (x, y, mask, w).

        Вес w (0..1) задаёт доверие к примеру: строки со старой разметкой
        участвуют в обучении слабее, но не выбрасываются.
        l2 — слабая регуляризация весов: на сотнях примеров сеть иначе
        легко заучивает шум и «переобучается» уже к 10-й эпохе.
        """
        if not rows:
            return 0.0
        total_weight = 0.0
        grad_w = [[[0.0] * len(row) for row in layer]
                  for layer in self.weights]
        grad_b = [[0.0] * len(row) for row in self.biases]
        loss = 0.0
        for item in rows:
            if len(item) >= 4:
                x, y, mask = item[0], item[1], item[2]
                try:
                    weight = float(item[3])
                except (TypeError, ValueError):
                    weight = 1.0
            else:
                x, y, mask = item
                weight = 1.0
            weight = max(0.0, min(5.0, weight))
            if weight <= 0.0:
                continue
            total_weight += weight
            acts = self.forward(x)
            out = acts[-1]
            delta = []
            for j, p in enumerate(out):
                if mask[j] <= 0:
                    delta.append(0.0)
                    continue
                target = y[j]
                p = min(max(p, 1e-9), 1.0 - 1e-9)
                loss += weight * (-(target * math.log(p) +
                                    (1.0 - target) * math.log(1.0 - p)))
                delta.append(weight * (p - target) * mask[j])
            for layer_index in range(len(self.weights) - 1, -1, -1):
                layer = self.weights[layer_index]
                prev_act = acts[layer_index]
                for out_index, row in enumerate(layer):
                    d = delta[out_index]
                    if not d:
                        continue
                    grow = grad_w[layer_index][out_index]
                    for k, value in enumerate(row):
                        grow[k] += d * prev_act[k]
                    grad_b[layer_index][out_index] += d
                if layer_index > 0:
                    # Производная tanh берётся от выходов предыдущего слоя —
                    # это acts[layer_index], а не его входы. Раньше здесь
                    # стоял acts[layer_index - 1], из-за чего градиент
                    # скрытого слоя считался неверно и сеть почти не училась.
                    prev_acts = acts[layer_index]
                    prev_delta = [0.0] * len(prev_acts)
                    for out_index, row in enumerate(layer):
                        d = delta[out_index]
                        if not d:
                            continue
                        for k, value in enumerate(row):
                            prev_delta[k] += value * d
                    for k in range(len(prev_delta)):
                        activation = prev_acts[k]
                        prev_delta[k] *= self._hidden_derivative(activation)
                    delta = prev_delta

        if total_weight <= 0.0:
            return 0.0
        scale = lr / total_weight
        for layer_index in range(len(self.weights)):
            layer = self.weights[layer_index]
            bias = self.biases[layer_index]
            for out_index, row in enumerate(layer):
                mom_row = self._momentum_w[layer_index][out_index]
                grad_row = grad_w[layer_index][out_index]
                for k in range(len(row)):
                    gradient = (grad_row[k] + l2 * row[k]) * scale
                    mom_row[k] = momentum * mom_row[k] + gradient
                    row[k] -= mom_row[k]
                mom_b = self._momentum_b[layer_index][out_index]
                mom_b = momentum * mom_b + grad_b[layer_index][out_index] * scale
                self._momentum_b[layer_index][out_index] = mom_b
                bias[out_index] -= mom_b
        return loss / total_weight

    # ---------- сохранение ----------
    def state(self):
        return {"sizes": list(self.sizes),
                "activation": self.activation,
                "weights": [[[float(v) for v in row] for row in layer]
                            for layer in self.weights],
                "biases": [[float(v) for v in row] for row in self.biases]}

    @classmethod
    def load(cls, data):
        model = cls(data.get("sizes") or [2, 1],
                    activation=data.get("activation") or "tanh")
        weights = data.get("weights") or []
        biases = data.get("biases") or []
        for index, layer in enumerate(weights):
            if index >= len(model.weights):
                break
            for row_index, row in enumerate(layer):
                if row_index >= len(model.weights[index]):
                    break
                for k, value in enumerate(row):
                    if k < len(model.weights[index][row_index]):
                        model.weights[index][row_index][k] = float(value)
        for index, row in enumerate(biases):
            if index >= len(model.biases):
                break
            for k, value in enumerate(row):
                if k < len(model.biases[index]):
                    model.biases[index][k] = float(value)
        return model


# --------------------------------------------------------------------------
# стандартизация признаков
# --------------------------------------------------------------------------


class Standardizer:
    """Приводит признаки к нулевому среднему и единичному разбросу."""

    def __init__(self, mean=None, std=None):
        self.mean = list(mean or [])
        self.std = list(std or [])

    def fit(self, rows):
        if not rows:
            return self
        size = len(rows[0])
        mean = []
        std = []
        for k in range(size):
            values = [float(row[k]) for row in rows if k < len(row)]
            if not values:
                mean.append(0.0)
                std.append(1.0)
                continue
            avg = sum(values) / len(values)
            variance = sum((v - avg) ** 2 for v in values) / len(values)
            mean.append(avg)
            std.append(max(math.sqrt(variance), 1e-6))
        self.mean = mean
        self.std = std
        return self

    def transform(self, x):
        if not self.mean:
            return list(x)
        out = []
        for k, value in enumerate(x):
            mean = self.mean[k] if k < len(self.mean) else 0.0
            std = self.std[k] if k < len(self.std) else 1.0
            out.append((float(value) - mean) / (std or 1.0))
        return out

    def state(self):
        return {"mean": [float(v) for v in self.mean],
                "std": [float(v) for v in self.std]}


# --------------------------------------------------------------------------
# обучение модели
# --------------------------------------------------------------------------


def _auc(values, labels):
    """Площадь под ROC-кривой; None, если в выборке один класс."""
    pairs = sorted(zip(values, labels))
    size = len(pairs)
    positives = sum(1 for _value, label in pairs if label >= 0.5)
    negatives = size - positives
    if not positives or not negatives:
        return None
    ranks = [0.0] * size
    index = 0
    while index < size:
        end = index
        while end + 1 < size and pairs[end + 1][0] == pairs[index][0]:
            end += 1
        rank = (index + end) / 2.0 + 1.0
        for position in range(index, end + 1):
            ranks[position] = rank
        index = end + 1
    total = sum(rank for rank, (_value, label) in zip(ranks, pairs)
                if label >= 0.5)
    return (total - positives * (positives + 1) / 2.0) / (
        positives * negatives)


def _logloss(prob, target):
    prob = min(max(float(prob), 1e-9), 1.0 - 1e-9)
    return -(target * math.log(prob) + (1.0 - target) * math.log(1.0 - prob))


def _logloss_logits(logits, targets):
    if not targets:
        return None
    return sum(_logloss(sigmoid(value), target)
               for value, target in zip(logits, targets)) / float(len(targets))


class LinearHead:
    """Логистическая регрессия на нескольких выбранных признаках.

    Многослойная сеть на двух тысячах примеров часто проигрывает простой
    линейной модели: у неё меньше параметров и ей труднее выучить шум.
    Поэтому у каждой головы есть ещё и линейная модель, а на проверке
    выбирается та, что честнее предсказывает вероятность.
    """

    def __init__(self, indices=None, weights=None, bias=0.0):
        self.indices = [int(value) for value in (indices or [])]
        self.weights = [float(value) for value in (weights or [])]
        self.bias = float(bias or 0.0)

    def logit(self, x):
        total = self.bias
        for index, weight in zip(self.indices, self.weights):
            if 0 <= index < len(x):
                total += weight * float(x[index])
        return total

    def state(self):
        return {"indices": list(self.indices),
                "weights": [float(value) for value in self.weights],
                "bias": float(self.bias)}

    @classmethod
    def load(cls, data):
        data = data or {}
        return cls(data.get("indices"), data.get("weights"),
                   data.get("bias") or 0.0)


def _linear_indices(X, y, count):
    """Отбирает признаки с наибольшей одномерной связью с исходом."""
    scored = []
    width = len(X[0]) if X else 0
    for index in range(width):
        value = _auc([row[index] for row in X], y)
        if value is not None:
            scored.append((abs(value - 0.5), index))
    scored.sort(reverse=True)
    return [index for _score, index in scored[:max(1, count)]]


def _fit_linear_head(X, y, weights, Xv, yv):
    """Обучает линейную голову с L2 и ранней остановкой по проверке.

    Возвращает (LinearHead, logloss на проверке). Если сигнала нет вовсе,
    остаётся одна базовая вероятность — это честнее случайных весов.
    """
    if not X or not y:
        return LinearHead(), None
    positives = sum(1 for value in y if value >= 0.5)
    prior = (positives + 1.0) / (len(y) + 2.0)
    prior = min(max(prior, 1e-3), 1.0 - 1e-3)
    count = min(12, max(3, len(X) // 50))
    indices = _linear_indices(X, y, count)
    if not indices:
        return LinearHead([], [], math.log(prior / (1.0 - prior))), None
    rows = [[row[index] for index in indices] for row in X]
    valid = None
    if Xv and yv:
        valid = ([[row[index] for index in indices] for row in Xv], list(yv))
    features = len(indices)
    learn = 0.25
    l2 = 0.02
    epochs = 160 if len(rows) <= 4000 else 100
    weight = [0.0] * features
    bias = math.log(prior / (1.0 - prior))
    best = (None, None)
    samples = [(row, target, max(0.0, float(weight_value)))
               for row, target, weight_value in zip(rows, y, weights)]
    for epoch in range(epochs):
        grad = [0.0] * features
        grad_bias = 0.0
        total = 0.0
        for row, target, row_weight in samples:
            if row_weight <= 0.0:
                continue
            value = bias
            for k in range(features):
                value += weight[k] * row[k]
            delta = row_weight * (sigmoid(value) - target)
            for k in range(features):
                grad[k] += delta * row[k]
            grad_bias += delta
            total += row_weight
        if total <= 0.0:
            break
        bias -= learn * grad_bias / total
        for k in range(features):
            weight[k] -= learn * (grad[k] / total + l2 * weight[k])
        if valid is not None and (epoch % 8 == 7 or epoch == epochs - 1):
            loss = _logloss_logits(
                [bias + sum(weight[k] * row[k] for k in range(features))
                 for row in valid[0]], valid[1])
            if loss is not None and (best[1] is None or loss < best[1]):
                best = (list(weight), loss, bias)
    if best[0] is not None:
        return LinearHead(indices, best[0], best[2]), best[1]
    loss = None
    if valid is not None:
        loss = _logloss_logits(
            [bias + sum(weight[k] * row[k] for k in range(features))
             for row in valid[0]], valid[1])
    return LinearHead(indices, weight, bias), loss


def _head_temperature(model, head):
    """Температура головы: общая, умноженная на её поправку."""
    try:
        base = float((model or {}).get("temperature") or 1.0)
    except (TypeError, ValueError):
        base = 1.0
    if base <= 0.0:
        base = 1.0
    try:
        scale = float(((model or {}).get("head_temperature") or {}).get(head, 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    if scale <= 0.0:
        scale = 1.0
    return base * scale


def _apply_linear(model, z, values):
    """Подменяет логиты голов, для которых выбрана линейная модель."""
    linear = (model or {}).get("head_linear") or {}
    source = (model or {}).get("head_source") or {}
    for head, data in linear.items():
        if source.get(head) != "linear":
            continue
        values[head] = LinearHead.load(data).logit(z)
    return values


def market_specialist(model, head):
    """Отдельная модель рынка для головы, если она готова.

    Победитель сюда не входит: его вероятности считает основная сеть.
    Специалист обучен только на строках своего рынка и включается, лишь
    когда на отложенных матчах доказал перевес над базой.
    """
    for kind, data in ((model or {}).get("market_models") or {}).items():
        if SPECIALIST_HEADS.get(kind) != head:
            continue
        if (data or {}).get("meta", {}).get("ready"):
            return data
    return None


def _apply_specialists(model, z, values):
    """Подменяет логиты рынков их отдельными моделями."""
    for kind, head in SPECIALIST_HEADS.items():
        data = market_specialist(model, head)
        if not data:
            continue
        values[head] = LinearHead.load(data.get("head_state") or {}).logit(z)
    return values


def _market_temperature(model, head):
    """Температура головы: у отдельной модели рынка своя калибровка."""
    data = market_specialist(model, head)
    if data:
        try:
            value = float(data.get("temperature") or 1.0)
        except (TypeError, ValueError):
            value = 1.0
        return value if value > 0.0 else 1.0
    return _head_temperature(model, head)


def _model_logits_rows(model, rows):
    """Логиты всех голов для строк выборки (сеть загружается один раз)."""
    net = MLP.load(model or {})
    standardizer = Standardizer((model or {}).get("standardizer", {}).get("mean"),
                                (model or {}).get("standardizer", {}).get("std"))
    heads = (model or {}).get("heads") or []
    out = []
    for row in rows:
        z = standardizer.transform(model_features(model, row.get("x") or []))
        logits = net.logits(z)
        values = {head: logits[i] for i, head in enumerate(heads)
                  if i < len(logits)}
        values = _apply_linear(model, z, values)
        out.append(_apply_specialists(model, z, values))
    return out


def _metrics_from_probs(samples, heads):
    """Считает точность по головам и по решениям рынков.

    ``samples`` — список (вероятности, метки, маски). Рынок победителя
    считается одним решением (кто вероятнее), а не тремя отдельными
    головами: иначе редкая ничья весит столько же, сколько основной
    исход, и общая точность врёт.
    """
    heads = list(heads or [])
    totals = {head: 0 for head in heads}
    correct = {head: 0 for head in heads}
    base = {head: [0, 0] for head in heads}
    head_loss = {head: 0.0 for head in heads}
    loss_sum = 0.0
    loss_n = 0
    winner_heads = [head for head in heads if head in ("p1", "p2", "draw")]
    winner_total = 0
    winner_correct = 0
    winner_counts = {}
    market_samples = {"winner": 0, "total": 0, "handicap": 0, "btts": 0}
    market_correct = {"winner": 0, "total": 0, "handicap": 0, "btts": 0}
    market_baseline = {"winner": 0, "total": 0, "handicap": 0, "btts": 0}
    for probs, y, mask in samples:
        y = y or []
        mask = mask or []
        for index, head in enumerate(heads):
            if index >= len(y) or index >= len(mask) or mask[index] <= 0:
                continue
            prob = probs.get(head)
            if prob is None:
                continue
            totals[head] += 1
            truth = y[index] >= 0.5
            if (prob >= 0.5) == truth:
                correct[head] += 1
            base[head][0 if truth else 1] += 1
            head_loss[head] += _logloss(prob, float(y[index]))
            loss_sum += _logloss(prob, float(y[index]))
            loss_n += 1
        active = []
        for position, head in enumerate(heads):
            if head not in winner_heads or head not in probs:
                continue
            if position < len(mask) and mask[position] > 0:
                active.append((head, probs[head]))
        if active:
            best_head, _best = max(active, key=lambda item: item[1])
            truth_head = None
            for position, head in enumerate(heads):
                if head not in winner_heads:
                    continue
                if position < len(y) and position < len(mask) \
                        and mask[position] > 0 and y[position] >= 0.5:
                    truth_head = head
                    break
            if truth_head is not None:
                winner_total += 1
                winner_counts[truth_head] = winner_counts.get(truth_head, 0) + 1
                if best_head == truth_head:
                    winner_correct += 1

    head_accuracy = {}
    head_baseline = {}
    parts = []
    for head in heads:
        if not totals[head]:
            continue
        head_accuracy[head] = correct[head] / float(totals[head])
        head_baseline[head] = max(base[head]) / float(totals[head])
        parts.append(head_accuracy[head])
        head_loss[head] /= float(totals[head])
    if winner_total:
        market_samples["winner"] = winner_total
        market_correct["winner"] = winner_correct
        market_baseline["winner"] = max(winner_counts.values())
    for kind, head in (("total", "over"), ("handicap", "handicap"),
                       ("btts", "btts")):
        if totals.get(head):
            market_samples[kind] = totals[head]
            market_correct[kind] = correct[head]
            market_baseline[kind] = max(base[head])
    all_samples = sum(market_samples.values())
    all_correct = sum(market_correct.values())
    all_base = sum(market_baseline.values())
    accuracy = all_correct / float(all_samples) if all_samples else 0.0
    baseline = all_base / float(all_samples) if all_samples else 0.0
    return {
        "accuracy": accuracy,
        "baseline": baseline,
        "lift": accuracy - baseline,
        "macro_accuracy": sum(parts) / len(parts) if parts else 0.0,
        "loss": (loss_sum / loss_n) if loss_n else 0.0,
        "winner_accuracy": (winner_correct / float(winner_total))
        if winner_total else 0.0,
        "winner_baseline": (max(winner_counts.values()) / float(winner_total))
        if winner_total else 0.0,
        "winner_samples": winner_total,
        "over_accuracy": head_accuracy.get("over", 0.0),
        "over_samples": totals.get("over", 0),
        "head_accuracy": head_accuracy,
        "head_baseline": head_baseline,
        "head_samples": totals,
        "head_correct": correct,
        "head_loss": head_loss,
        "market_samples": market_samples,
        "market_correct": market_correct,
        "market_baseline": market_baseline,
    }


def evaluate_model(model, standardizer, rows, heads):
    """Точность сети на отложенной выборке (без линейных голов)."""
    if not rows:
        return _metrics_from_probs([], heads)
    samples = []
    for row in rows:
        probs = model.predict(standardizer.transform(row["x"]))
        values = {head: probs[index] for index, head in enumerate(heads)
                  if index < len(probs)}
        samples.append((values, row.get("y") or [], row.get("m") or []))
    return _metrics_from_probs(samples, heads)


def evaluate_hybrid(model, rows, heads):
    """Точность итоговой модели: сеть, линейные головы и температура."""
    if not rows:
        return _metrics_from_probs([], heads)
    logits_rows = _model_logits_rows(model, rows)
    samples = []
    for row, values in zip(rows, logits_rows):
        probs = {}
        for head, value in values.items():
            temperature = _market_temperature(model, head)
            probs[head] = sigmoid(value / temperature)
        samples.append((probs, row.get("y") or [], row.get("m") or []))
    return _metrics_from_probs(samples, heads)


def _best_temperature(samples, bounds=None, steps=60):
    """Температура, минимизирующая logloss на готовых логитах."""
    if not samples:
        return 1.0, None
    low, high = bounds or TEMPERATURE_RANGE
    low = max(1e-3, float(low))
    high = max(low, float(high))
    steps = max(2, int(steps))
    best_t, best_loss = 1.0, None
    for step in range(steps):
        ratio = step / float(steps - 1)
        temperature = low * ((high / low) ** ratio)
        loss = 0.0
        for target, logit in samples:
            loss += _logloss(sigmoid(logit / temperature), target)
        loss /= float(len(samples))
        if best_loss is None or loss < best_loss:
            best_t, best_loss = temperature, loss
    return best_t, best_loss


def fit_temperature(model, standardizer, rows, heads,
                    bounds=None, steps=60):
    """Подбирает общую температуру по логитам сети.

    Сеть с сигмоидой часто выдаёт 0.9 там, где права в 60% случаев:
    порог уверенности тогда ничего не значит. Температура делит логиты,
    не меняя порядок классов (точность та же), и делает вероятности
    честными. Возвращает (temperature, loss).
    """
    net = model if isinstance(model, MLP) else MLP.load(model or {})
    samples = []
    for row in rows or []:
        y = row.get("y") or []
        mask = row.get("m") or []
        try:
            z = net.logits(standardizer.transform(row["x"]))
        except Exception:
            continue
        for index, logit in enumerate(z):
            if index < len(y) and index < len(mask) and mask[index] > 0:
                samples.append((float(y[index]), float(logit)))
    return _best_temperature(samples, bounds=bounds, steps=steps)


def fit_head_temperatures(model, rows, heads, steps=48):
    """Температура каждой головы на отложенных матчах.

    Возвращает (общая температура, поправки по головам, logloss). Общая
    температура — геометрическое среднее: она задаёт масштаб, а поправки
    голов делают вероятности честными там, где сеть особенно самоуверенна.
    """
    heads = list(heads or [])
    logits_rows = _model_logits_rows(model, rows or [])
    per_head = {}
    losses = {}
    for head in heads:
        samples = []
        for row, values in zip(rows or [], logits_rows):
            if head not in values:
                continue
            y = row.get("y") or []
            mask = row.get("m") or []
            index = (model.get("heads") or []).index(head) \
                if head in (model.get("heads") or []) else -1
            if index < 0 or index >= len(y) or index >= len(mask) \
                    or mask[index] <= 0:
                continue
            samples.append((float(y[index]), float(values[head])))
        temperature, loss = _best_temperature(samples, steps=steps)
        per_head[head] = temperature
        losses[head] = loss
    positive = [value for value in per_head.values() if value > 0.0]
    if positive:
        global_temperature = math.exp(
            sum(math.log(value) for value in positive) / len(positive))
    else:
        global_temperature = 1.0
    scales = {}
    for head, temperature in per_head.items():
        scales[head] = min(4.0, max(0.25, temperature / global_temperature))
    return global_temperature, scales, losses


def _fit_market_specialist(sport, kind, head, train_rows, val_rows,
                           train_x, val_x, heads, legacy_risk):
    """Обучает отдельную модель одного рынка.

    Основная сеть учит все головы сразу, поэтому редкий рынок может
    «потеряться» за сильным победителем. Здесь модель видит только строки
    своего рынка, сама выбирает признаки и включается, только если на
    отложенных матчах обошла базу на требуемый перевес. Победитель в эту
    функцию не попадает.
    """
    if head not in heads:
        return None
    index = heads.index(head)
    train_index = [i for i, row in enumerate(train_rows)
                   if index < len(row.get("m") or [])
                   and float(row["m"][index]) > 0]
    val_index = [i for i, row in enumerate(val_rows)
                 if index < len(row.get("m") or [])
                 and float(row["m"][index]) > 0]
    if len(train_index) < MARKET_MIN_TRAIN_SAMPLES:
        return None
    if len(val_index) < SPECIALIST_MIN_VAL_SAMPLES:
        return None
    Xtr = [train_x[i] for i in train_index]
    ytr = [1.0 if float(train_rows[i]["y"][index]) >= 0.5 else 0.0
           for i in train_index]
    wtr = [_row_weight(sport, _row_version(train_rows[i]))
           for i in train_index]
    Xva = [val_x[i] for i in val_index]
    yva = [1.0 if float(val_rows[i]["y"][index]) >= 0.5 else 0.0
           for i in val_index]
    linear, logloss = _fit_linear_head(Xtr, ytr, wtr, Xva, yva)
    probs = [sigmoid(linear.logit(row)) for row in Xva]
    correct = sum(1 for prob, target in zip(probs, yva)
                  if (prob >= 0.5) == (target >= 0.5))
    accuracy = correct / float(len(yva)) if yva else 0.0
    positives = sum(1 for target in yva if target >= 0.5)
    baseline = max(positives, len(yva) - positives) / float(len(yva)) \
        if yva else 0.0
    temperature, calibration_loss = _best_temperature(
        [(target, linear.logit(row)) for row, target in zip(Xva, yva)])
    required = MARKET_MIN_LIFT + MARKET_LEGACY_LIFT * min(
        1.0, max(0.0, float(legacy_risk or 0.0)))
    if baseline >= MARKET_DEGENERATE_BASELINE:
        ready = accuracy >= baseline - MARKET_MIN_LIFT
    else:
        ready = accuracy >= baseline + required
    return {
        "kind": kind,
        "head": head,
        "source": "linear",
        "head_state": linear.state(),
        "temperature": temperature,
        "meta": {
            "samples": len(train_index),
            "val_samples": len(val_index),
            "accuracy": accuracy,
            "baseline": baseline,
            "lift": accuracy - baseline,
            "required_lift": required,
            "ready": bool(ready),
            "source": "linear",
            "logloss": logloss,
            "calibration_loss": calibration_loss,
            "feature_version": FEATURE_VERSION,
            "label_version": LABEL_VERSION,
        },
    }


def winner_ready(meta):
    """Готов ли рынок победителя как одно совместное решение.

    Отдельная точность голов П1/П2 сравнивается с «всегда самый частый
    исход», а это завышенная планка для несбалансированных исходов.
    Рынок победителя — выбор одного из П1/Ничья/П2, поэтому и проверять
    нужно точность этого выбора, а не каждой головы по отдельности.
    """
    meta = meta or {}
    # Достаточность данных — по обучающей выборке голов П1/П2, как и у
    # остальных рынков. Точность берётся с проверки, но сама проверка на
    # маленьком устройстве может быть короткой: требуем хотя бы 8 исходов.
    coverage = meta.get("head_train_samples") or {}
    train_samples = 0
    if isinstance(coverage, dict):
        values = [int(coverage.get(head) or 0) for head in ("p1", "p2")
                  if head in coverage]
        if values:
            train_samples = min(values)
    if train_samples < MARKET_MIN_TRAIN_SAMPLES:
        try:
            train_samples = int(meta.get("winner_samples") or 0)
        except (TypeError, ValueError):
            train_samples = 0
    if train_samples < MARKET_MIN_TRAIN_SAMPLES:
        return False
    try:
        checked = int(meta.get("winner_samples") or 0)
    except (TypeError, ValueError):
        checked = 0
    if checked and checked < 8:
        return False
    accuracy = meta.get("winner_accuracy")
    baseline = meta.get("winner_baseline")
    if accuracy is None or baseline is None:
        return False
    try:
        accuracy = float(accuracy)
        baseline = float(baseline)
    except (TypeError, ValueError):
        return False
    required = required_lift(meta)
    if baseline >= MARKET_DEGENERATE_BASELINE:
        return accuracy >= baseline - MARKET_MIN_LIFT
    return accuracy >= baseline + required


def ready_markets(meta, sport):
    """Какие рынки вида спорта можно показывать по этой модели.

    Если у рынка есть отдельная модель, её слово главное: она обучена
    только на своих строках и проверена на своих отложенных матчах.
    Старая логика голов остаётся запасным вариантом для моделей без
    специалистов (в том числе уже сохранённых на устройстве).
    """
    meta = meta or {}
    specialists = meta.get("market_models") or {}
    ready = {}
    for kind in market_kinds(sport):
        if kind == "winner":
            ready[kind] = winner_ready(meta)
            continue
        if kind in specialists:
            ready[kind] = bool((specialists.get(kind) or {}).get("ready"))
            continue
        head = SPECIALIST_HEADS.get(kind)
        ready[kind] = bool(head) and head_ready(meta, head)
    return ready


def _market_reason(kind, is_ready, accuracy, baseline, samples,
                   train_samples, required):
    """Короткое объяснение, почему рынок даёт прогноз или молчит."""
    if kind == "winner":
        if is_ready:
            return "точность %.1f%% при базе %.1f%%" % (
                accuracy * 100.0, baseline * 100.0)
        if samples <= 0:
            return "пока нет проверенных матчей"
        return "точность %.1f%% при базе %.1f%% — нужен перевес +%.1f п.п." % (
            accuracy * 100.0, baseline * 100.0, required * 100.0)
    if train_samples < MARKET_MIN_TRAIN_SAMPLES:
        return "мало размеченных матчей: %d из %d" % (
            train_samples, MARKET_MIN_TRAIN_SAMPLES)
    if samples <= 0:
        return "нет проверки на отложенных матчах"
    lift = accuracy - baseline
    if is_ready:
        return "перевес %+.1f п.п. над базой %.1f%%" % (
            lift * 100.0, baseline * 100.0)
    if baseline >= MARKET_DEGENERATE_BASELINE:
        return "исход почти всегда один (база %.1f%%)" % (baseline * 100.0)
    if accuracy < baseline:
        return "точность %.1f%% ниже базы %.1f%%" % (
            accuracy * 100.0, baseline * 100.0)
    return "перевес %+.1f п.п., нужен +%.1f п.п." % (
        lift * 100.0, required * 100.0)


def market_report(meta, sport):
    """Диагностика по каждому рынку вида спорта.

    Возвращает список словарей: точность, база, перевес, требуемый перевес
    и причина, по которой рынок молчит. Нужна и в приложении, и в тестах,
    чтобы «тотал не показывается» было объяснимо, а не загадочно.
    """
    meta = meta or {}
    sport = sports.normalize_sport(sport)
    specialists = meta.get("market_models") or {}
    ready = ready_markets(meta, sport)
    head_train = meta.get("head_train_samples") or {}
    head_accuracy = meta.get("head_accuracy") or {}
    head_baseline = meta.get("head_baseline") or {}
    head_samples = meta.get("head_samples") or {}
    report = []
    for kind in market_kinds(sport):
        head = SPECIALIST_HEADS.get(kind)
        data = specialists.get(kind) or {}
        # В meta модели лежат краткие сведения о специалисте, а не его
        # веса; полная запись (если её передали) завёрнута в "meta".
        info = data.get("meta") if isinstance(data.get("meta"), dict) else data
        if kind == "winner":
            source = "winner"
            accuracy = float(meta.get("winner_accuracy") or 0.0)
            baseline = float(meta.get("winner_baseline") or 0.0)
            samples = int(meta.get("winner_samples") or 0)
            train_samples = int(meta.get("train_samples") or 0)
        elif data:
            source = "specialist"
            accuracy = float(info.get("accuracy") or 0.0)
            baseline = float(info.get("baseline") or 0.0)
            samples = int(info.get("val_samples") or 0)
            train_samples = int(info.get("samples") or 0)
        else:
            source = "head"
            accuracy = float(head_accuracy.get(head) or 0.0)
            baseline = float(head_baseline.get(head) or 0.0)
            samples = int(head_samples.get(head) or 0)
            train_samples = int(head_train.get(head) or 0)
        required = required_lift(meta)
        is_ready = bool(ready.get(kind))
        report.append({
            "kind": kind,
            "label": MARKET_LABELS.get(kind, kind),
            "ready": is_ready,
            "source": source,
            "accuracy": accuracy,
            "baseline": baseline,
            "lift": accuracy - baseline,
            "samples": samples,
            "train_samples": train_samples,
            "required_lift": required,
            "reason": _market_reason(kind, is_ready, accuracy, baseline,
                                     samples, train_samples, required),
        })
    return report


def market_summary(metrics, ready, allow_degenerate=False):
    """Точность по готовым рынкам: (accuracy, baseline, решений).

    Рынки с почти постоянным исходом (база ≥ 90%) не показывают навык:
    «обе забьют — нет» может быть верно всегда, но это не заслуга модели.
    Такие рынки по-прежнему дают прогноз, но в общую точность не входят,
    иначе она выглядит высокой без всякого перевеса.
    """
    metrics = metrics or {}
    correct = 0
    baseline = 0
    total = 0
    for kind, is_ready in (ready or {}).items():
        if not is_ready:
            continue
        samples = int((metrics.get("market_samples") or {}).get(kind) or 0)
        if samples <= 0:
            continue
        kind_baseline = int(
            (metrics.get("market_baseline") or {}).get(kind) or 0) / float(samples)
        if not allow_degenerate and \
                kind_baseline >= MARKET_DEGENERATE_BASELINE:
            continue
        correct += int((metrics.get("market_correct") or {}).get(kind) or 0)
        baseline += int((metrics.get("market_baseline") or {}).get(kind) or 0)
        total += samples
    if not total:
        return 0.0, 0.0, 0
    return correct / float(total), baseline / float(total), total


def split_rows(rows, share=0.2):
    """Делит выборку на обучение и проверку, не разрывая один матч.

    Один матч настольного тенниса даёт до 7 строк (по партии) с почти
    одинаковыми признаками. Если такие строки попадут и в обучение, и в
    проверку, точность на проверке завышается и «переобучение» видно
    поздно. Поэтому группы (матчи) целиком уходят в одну из частей, а
    проверка — самые свежие матчи: так модель проверяется на «будущем».
    """
    rows = list(rows or [])
    if not rows:
        return [], []
    groups = {}
    order = []
    for index, row in enumerate(rows):
        key = row.get("g")
        if key is None:
            key = "row:%d" % index
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(index)
    need = max(1, int(len(rows) * share))
    val_index = set()
    for key in reversed(order):
        if len(val_index) >= need:
            break
        val_index.update(groups[key])
    train_rows = [row for index, row in enumerate(rows)
                  if index not in val_index]
    val_rows = [row for index, row in enumerate(rows) if index in val_index]
    if not train_rows:
        train_rows = rows[:]
    if not val_rows:
        val_rows = rows[-1:]
    return train_rows, val_rows


def _standardizer_for(model, rows):
    """Стандартизация: из модели, иначе по обучающей части."""
    stored = (model or {}).get("standardizer") or {}
    if stored.get("mean"):
        return Standardizer(stored.get("mean"), stored.get("std"))
    return Standardizer().fit([row["x"] for row in rows])


def evaluate_previous(sport, previous, rows, share=0.2):
    """Точность прежней модели на той же проверочной выборке.

    Сравнивать «старую точность» из прошлого обучения с новой нельзя:
    отложенная выборка каждый раз другая, и решение «модель стала хуже»
    принималось по несопоставимым числам. Здесь обе модели проверяются
    на одних и тех же свежих матчах.
    """
    if not previous or not rows:
        return None
    try:
        _spec, heads, _layout = feature_spec(sport)
        ordered = sorted(rows, key=lambda r: r.get("t", ""))
        _train, val_rows = split_rows(ordered, share=share)
        samples = [(predict_probs(previous, row["x"]),
                    row.get("y") or [], row.get("m") or [])
                   for row in val_rows]
        metrics = _metrics_from_probs(samples, heads)
        # Сравнивать модели нужно по одной и той же мере: у новой модели
        # accuracy считается по готовым рынкам, значит и у прежней тоже.
        ready = ready_markets((previous or {}).get("meta") or {}, sport)
        accuracy, baseline, decisions = market_summary(metrics, ready)
        if not decisions:
            accuracy = metrics.get("accuracy") or 0.0
            baseline = metrics.get("baseline") or 0.0
            decisions = sum((metrics.get("market_samples") or {}).values())
        metrics["accuracy_all"] = metrics.get("accuracy")
        metrics["accuracy"] = accuracy
        metrics["baseline"] = baseline
        metrics["lift"] = accuracy - baseline
        metrics["ready_samples"] = decisions
        return metrics
    except Exception:
        return None


def _row_version(row):
    """Версия разметки строки (0 — старая, без метки)."""
    try:
        return int((row or {}).get("v") or 0)
    except (TypeError, ValueError):
        return 0


def _row_weight(sport, version):
    """Вес строки в обучении по версии разметки и виду спорта.

    Старая разметка футбола/тенниса/волейбола могла быть снята со счёта
    периода. Такие строки не выбрасываем — иначе выборка усохнет и
    модели не на чем учиться, — но даём им меньший вес.
    """
    if version >= LABEL_VERSION:
        return 1.0
    if sports.normalize_sport(sport) in LEGACY_RISK_SPORTS:
        return LEGACY_SAMPLE_WEIGHT
    return 1.0


def train_model(sport, rows, previous=None, epochs=12, lr=0.05, hidden=None,
                seed=7, pause=None, l2=0.001, momentum=0.9,
                batch_size=32, validation_share=0.2, hidden_layers=None,
                activation="tanh"):
    """Обучает (или дообучает) модель вида спорта.

    rows — список {"x": [...], "y": [...], "m": [...]}. previous — ранее
    обученная модель (dict), чтобы обучение продолжалось, а не начиналось
    с нуля. Возвращает (model_dict, report).

    Архитектура (hidden_layers), активация и все параметры обучения
    приходят из настроек. Если архитектура или активация изменились,
    старая модель не загружается: веса другой формы бессмысленны, вид
    обучается заново.

    Точность считается по отложенным матчам, а веса берутся с лучшей
    эпохи: сеть не «дообучается» до состояния, где она выучила шум.
    """
    sport = sports.normalize_sport(sport)
    _spec, heads, layout = feature_spec(sport)
    if not rows:
        return previous, {"ok": False, "error": "Нет данных"}

    if hidden_layers is None:
        hidden_layers = [hidden] if hidden else [16]
    clean_layers = []
    for value in hidden_layers:
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 512:
            clean_layers.append(number)
        if len(clean_layers) >= 4:
            break
    hidden_layers = clean_layers or [16]
    activation = activation if activation in MLP.ACTIVATIONS else "tanh"
    try:
        epochs = max(1, min(300, int(epochs)))
    except (TypeError, ValueError):
        epochs = 12
    try:
        batch_size = max(1, min(512, int(batch_size)))
    except (TypeError, ValueError):
        batch_size = 32
    try:
        validation_share = max(0.05, min(0.5, float(validation_share)))
    except (TypeError, ValueError):
        validation_share = 0.2

    rows = sorted(rows, key=lambda r: r.get("t", ""))
    size = len(rows)
    train_rows, val_rows = split_rows(rows, share=validation_share)
    # Признаки версии 2: производные разности считаются один раз, чтобы
    # обучение и проверка сети видели тот же вектор, что и прогноз.
    train_expanded = [expand_features(sport, row.get("x") or [])
                      for row in train_rows]
    val_expanded = [expand_features(sport, row.get("x") or [])
                    for row in val_rows]
    val_rows_for_model = [dict(row, x=x)
                          for row, x in zip(val_rows, val_expanded)]
    standardizer = Standardizer().fit(train_expanded)
    input_size = len(train_expanded[0])
    output_size = len(heads)
    sizes = [input_size] + hidden_layers + [output_size]

    reuse = bool(previous and previous.get("sizes") == sizes and
                 (previous.get("activation") or "tanh") == activation)
    model = MLP.load(previous) if reuse else MLP(
        sizes, seed=seed, activation=activation)

    prepared = []
    legacy_active = 0
    risky_legacy = sports.normalize_sport(sport) in LEGACY_RISK_SPORTS
    for row, vector in zip(train_rows, train_expanded):
        version = _row_version(row)
        weight = _row_weight(sport, version)
        if (risky_legacy and version < LABEL_VERSION and any(
                float(v) > 0 for v in (row.get("m") or []))):
            legacy_active += 1
        prepared.append((standardizer.transform(vector), row["y"],
                         row["m"], weight))
    legacy_risk = (legacy_active / float(len(train_rows))) \
        if train_rows else 0.0
    head_train_samples = {}
    for index, head in enumerate(heads):
        head_train_samples[head] = sum(
            1 for row in train_rows
            if index < len(row.get("m") or [])
            and float(row["m"][index]) > 0)
    rng = random.Random(seed + 3)
    loss = 0.0
    step = 0
    best_state = None
    best_metrics = None
    best_score = (0.0, 0.0, 0.0)
    best_epoch = 0
    for epoch in range(epochs):
        rng.shuffle(prepared)
        for start in range(0, len(prepared), batch_size):
            batch = prepared[start:start + batch_size]
            loss = model.train_batch(batch, lr=lr, momentum=momentum, l2=l2)
            step += 1
            # Периодически отпускаем интерпретатор: на телефоне обучение
            # не должно блокировать остальной движок.
            if pause is not None and step % 8 == 0:
                pause()
        if val_rows and (epoch % 2 == 1 or epoch == epochs - 1):
            metrics = evaluate_model(model, standardizer,
                                     val_rows_for_model, heads)
            # Лучшая эпоха: сначала точность, при равенстве — меньшая
            # потеря (более уверенные и калиброванные вероятности).
            score = (round(float(metrics.get("accuracy") or 0.0), 6),
                     -float(metrics.get("loss") or 0.0),
                     float(metrics.get("winner_accuracy") or 0.0))
            if best_metrics is None or score > best_score:
                best_score = score
                best_metrics = metrics
                best_state = model.state()
                best_epoch = epoch + 1

    if best_state is not None:
        model = MLP.load(best_state)
        metrics = best_metrics
    else:
        metrics = evaluate_model(model, standardizer,
                                     val_rows_for_model, heads)

    # Отдельная линейная модель на каждую голову. На реальных выборках
    # она часто обгоняет многослойную сеть: у неё меньше параметров и ей
    # труднее выучить шум. Сравниваем logloss на отложенных матчах и
    # оставляем лучшую из двух моделей для каждой головы.
    train_x = [standardizer.transform(vector) for vector in train_expanded]
    val_x = [standardizer.transform(vector) for vector in val_expanded]
    val_mlp_logits = [model.logits(x) for x in val_x]
    head_linear = {}
    head_source = {}
    head_auc = {}
    head_logloss = {}
    for index, head in enumerate(heads):
        train_index = [i for i, row in enumerate(train_rows)
                       if index < len(row.get("m") or [])
                       and float(row["m"][index]) > 0]
        val_index = [i for i, row in enumerate(val_rows)
                     if index < len(row.get("m") or [])
                     and float(row["m"][index]) > 0]
        if not train_index:
            continue
        Xtr = [train_x[i] for i in train_index]
        ytr = [1.0 if float(train_rows[i]["y"][index]) >= 0.5 else 0.0
               for i in train_index]
        wtr = [_row_weight(sport, _row_version(train_rows[i]))
               for i in train_index]
        Xva = [val_x[i] for i in val_index]
        yva = [1.0 if float(val_rows[i]["y"][index]) >= 0.5 else 0.0
               for i in val_index]
        linear, linear_loss = _fit_linear_head(Xtr, ytr, wtr, Xva, yva)
        mlp_logits = [val_mlp_logits[i][index] for i in val_index
                      if index < len(val_mlp_logits[i])]
        mlp_loss = _logloss_logits(mlp_logits, yva) \
            if len(mlp_logits) == len(yva) else None
        if linear_loss is not None and (mlp_loss is None or
                                        linear_loss < mlp_loss - 1e-4):
            head_source[head] = "linear"
            head_linear[head] = linear.state()
            head_logloss[head] = linear_loss
            head_probs = [sigmoid(linear.logit(x)) for x in Xva]
        else:
            head_source[head] = "mlp"
            head_logloss[head] = mlp_loss
            head_probs = [sigmoid(value) for value in mlp_logits]
        head_auc[head] = _auc(head_probs, yva) if head_probs else None

    state = model.state()
    state.update({
        "sport": sport,
        "layout": layout,
        "heads": list(heads),
        "standardizer": standardizer.state(),
        "feature_version": FEATURE_VERSION,
        "head_linear": head_linear,
        "head_source": head_source,
        "head_auc": head_auc,
        "head_logloss": head_logloss,
    })
    # Калибровка по отложенным матчам: сеть не должна быть увереннее,
    # чем позволяет её реальная точность. Температура не меняет решение,
    # только масштаб вероятностей.
    temperature, head_temperature, calibration_loss = fit_head_temperatures(
        state, val_rows, heads)
    state["temperature"] = temperature
    state["head_temperature"] = head_temperature
    metrics = evaluate_hybrid(state, val_rows, heads)
    base_meta = {
        "head_train_samples": head_train_samples,
        "head_accuracy": metrics.get("head_accuracy") or {},
        "head_baseline": metrics.get("head_baseline") or {},
        "head_samples": metrics.get("head_samples") or {},
        "legacy_risk": legacy_risk,
        "winner_accuracy": metrics.get("winner_accuracy"),
        "winner_baseline": metrics.get("winner_baseline"),
        "winner_samples": metrics.get("winner_samples"),
    }
    ready = ready_markets(base_meta, sport)
    # Отдельная модель на каждый неготовый рынок. Победитель сюда не
    # входит: его вероятности по-прежнему считает основная сеть, поэтому
    # добавление специалистов не может ухудшить текущую точность исхода.
    market_models = {}
    for kind, head in SPECIALIST_HEADS.items():
        if kind not in market_kinds(sport) or ready.get(kind):
            continue
        specialist = _fit_market_specialist(
            sport, kind, head, train_rows, val_rows, train_x, val_x,
            heads, legacy_risk)
        if specialist:
            market_models[kind] = specialist
    if market_models:
        state["market_models"] = market_models
        # Специалисты изменили вероятности своих рынков: метрики и
        # готовность пересчитываются на той же отложенной выборке.
        metrics = evaluate_hybrid(state, val_rows, heads)
        base_meta["head_accuracy"] = metrics.get("head_accuracy") or {}
        base_meta["head_baseline"] = metrics.get("head_baseline") or {}
        base_meta["head_samples"] = metrics.get("head_samples") or {}
        base_meta["market_models"] = {
            kind: (data.get("meta") or {})
            for kind, data in market_models.items()}
        ready = ready_markets(base_meta, sport)
    accuracy, baseline, decisions = market_summary(metrics, ready)
    accuracy_all, baseline_all, decisions_all = market_summary(
        metrics, {kind: True for kind in market_kinds(sport)})
    if not decisions:
        accuracy, baseline, decisions = accuracy_all, baseline_all, decisions_all
    if not decisions:
        accuracy, baseline, decisions = market_summary(
            metrics, ready, allow_degenerate=True)
    state["meta"] = {
        "samples": size,
        "train_samples": len(train_rows),
        "val_samples": len(val_rows),
        "epochs": epochs,
        "best_epoch": best_epoch or epochs,
        "loss": loss,
        "accuracy": accuracy,
        "baseline": baseline,
        "macro_accuracy": metrics.get("macro_accuracy", 0.0),
        "lift": accuracy - baseline,
        "accuracy_all": accuracy_all,
        "baseline_all": baseline_all,
        "lift_all": accuracy_all - baseline_all,
        "ready_markets": sorted(kind for kind, value in ready.items()
                                if value),
        "market_samples": metrics.get("market_samples") or {},
        "market_correct": metrics.get("market_correct") or {},
        "market_baseline": metrics.get("market_baseline") or {},
        "winner_accuracy": metrics.get("winner_accuracy", 0.0),
        "winner_baseline": metrics.get("winner_baseline", 0.0),
        "winner_samples": metrics.get("winner_samples", 0),
        "over_accuracy": metrics.get("over_accuracy", 0.0),
        "head_accuracy": metrics.get("head_accuracy") or {},
        "head_baseline": metrics.get("head_baseline") or {},
        "head_samples": metrics.get("head_samples") or {},
        "head_train_samples": head_train_samples,
        "head_source": head_source,
        "head_auc": head_auc,
        "head_logloss": head_logloss,
        "training_revision": TRAIN_REVISION,
        "feature_version": FEATURE_VERSION,
        "legacy_risk": round(legacy_risk, 4),
        "legacy_weight": LEGACY_SAMPLE_WEIGHT,
        "temperature": temperature,
        "head_temperature": head_temperature,
        "calibration_loss": calibration_loss,
        "label_version": LABEL_VERSION,
        "architecture": list(hidden_layers),
        "activation": activation,
        "learning_rate": lr,
        "l2": l2,
        "momentum": momentum,
        "batch_size": batch_size,
        "validation_share": validation_share,
        "seed": seed,
        "finetuned": bool(reuse),
        "market_models": {
            kind: (data.get("meta") or {})
            for kind, data in (state.get("market_models") or {}).items()},
    }
    # Диагностика строится по уже собранной meta: так она видит и
    # специалистов, и запасную логику голов.
    state["meta"]["market_report"] = market_report(state["meta"], sport)
    return state, {"ok": True, "metrics": metrics, "epochs": epochs,
                   "best_epoch": best_epoch or epochs,
                   "architecture": list(hidden_layers),
                   "activation": activation, "finetuned": bool(reuse)}


def head_logits(model, features):
    """Сырые логиты голов с учётом выбранных линейных моделей."""
    if not model:
        return {}
    standardizer = Standardizer(
        (model.get("standardizer") or {}).get("mean"),
        (model.get("standardizer") or {}).get("std"))
    z = standardizer.transform(model_features(model, features))
    net = MLP.load(model)
    logits = net.logits(z)
    heads = model.get("heads") or []
    values = {head: logits[i] for i, head in enumerate(heads)
              if i < len(logits)}
    values = _apply_linear(model, z, values)
    return _apply_specialists(model, z, values)


def predict_probs(model, features):
    """Возвращает словарь head -> вероятность для готовой модели."""
    values = head_logits(model, features)
    probs = {}
    for head, value in values.items():
        temperature = _market_temperature(model, head)
        probs[head] = sigmoid(value / temperature)
    return probs

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

# Ревизия обучения: 1.27 добавила веса старых строк и калибровку
# температуры. Модель без этой ревизии переобучается один раз, иначе
# старые веса продолжали бы давать вероятности без проверки.
TRAIN_REVISION = 1

# Минимум обучающих примеров на голову, чтобы рынок давал прогноз.
# Рынок без покрытия или без перевеса над «всегда самый частый класс»
# молчит: редкие и случайные сигналы не должны выглядеть уверенными.
MARKET_MIN_TRAIN_SAMPLES = 20
MARKET_MIN_LIFT = 0.01
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
        risk = float(meta.get("legacy_risk") or 0.0)
        risk = min(1.0, max(0.0, risk))
        required = MARKET_MIN_LIFT + MARKET_LEGACY_LIFT * risk
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


def evaluate_model(model, standardizer, rows, heads):
    """Считает точность на отложенной выборке.

    Возвращает словарь: accuracy (среднее по рынкам), baseline (базовый
    уровень «всегда самый частый класс»), lift, точность по каждой голове
    и точность решения по исходу.
    """
    if not rows:
        return {"accuracy": 0.0, "baseline": 0.0, "lift": 0.0, "heads": {},
                "loss": 0.0}
    winner_heads = [i for i, head in enumerate(heads)
                    if head in ("p1", "p2", "draw")]
    totals = {head: 0 for head in heads}
    correct = {head: 0 for head in heads}
    base = {head: [0, 0] for head in heads}
    correct_winner = 0
    total_winner = 0
    loss_sum = 0.0
    loss_n = 0
    for row in rows:
        x = standardizer.transform(row["x"])
        probs = model.predict(x)
        y = row["y"]
        mask = row["m"]
        for index, head in enumerate(heads):
            if index >= len(y) or index >= len(mask) or mask[index] <= 0:
                continue
            totals[head] += 1
            truth = y[index] >= 0.5
            if (probs[index] >= 0.5) == truth:
                correct[head] += 1
            base[head][0 if truth else 1] += 1
            p = min(max(float(probs[index]), 1e-9), 1.0 - 1e-9)
            loss_sum += -(float(y[index]) * math.log(p) +
                          (1.0 - float(y[index])) * math.log(1.0 - p))
            loss_n += 1
        if winner_heads:
            best = max(winner_heads, key=lambda i: probs[i] if mask[i] > 0
                       else -1.0)
            truth_index = -1
            for i in winner_heads:
                if mask[i] > 0 and y[i] >= 0.5:
                    truth_index = i
                    break
            if truth_index >= 0:
                total_winner += 1
                if best == truth_index:
                    correct_winner += 1

    head_accuracy = {}
    head_baseline = {}
    parts = []
    base_parts = []
    for head in heads:
        if not totals[head]:
            continue
        value = correct[head] / float(totals[head])
        head_accuracy[head] = value
        head_baseline[head] = max(base[head]) / float(totals[head])
        parts.append(value)
        base_parts.append(head_baseline[head])
    # Точность — по всем проверенным решениям, а не среднее по головам:
    # иначе редкая голова (ничья, обе забьют) весит столько же, сколько
    # основной рынок, и общая цифра врёт. Среднее по головам оставляем
    # отдельным полем для диагностики.
    decisions = sum(totals.values())
    accuracy = (sum(correct.values()) / float(decisions)) if decisions else 0.0
    baseline = (sum(max(base[head]) for head in heads) / float(decisions)) \
        if decisions else 0.0
    macro_accuracy = sum(parts) / len(parts) if parts else 0.0
    winner_acc = (correct_winner / total_winner) if total_winner else 0.0
    over_acc = head_accuracy.get("over", 0.0)
    return {
        "accuracy": accuracy,
        "baseline": baseline,
        "macro_accuracy": macro_accuracy,
        "lift": accuracy - baseline,
        "loss": (loss_sum / loss_n) if loss_n else 0.0,
        "winner_accuracy": winner_acc,
        "over_accuracy": over_acc,
        "winner_samples": total_winner,
        "over_samples": totals.get("over", 0),
        "head_accuracy": head_accuracy,
        "head_baseline": head_baseline,
        "head_samples": totals,
    }


def fit_temperature(model, standardizer, rows, heads,
                    bounds=None, steps=60):
    """Подбирает температуру, при которой уверенность не врёт.

    Сеть с сигмоидой часто выдаёт 0.9 там, где права в 60% случаев:
    порог уверенности тогда ничего не значит, а рынки выглядят
    «уверенными» без оснований. Температура делит логиты, не меняя
    порядок классов (точность та же), и делает вероятности честными.

    Возвращает (temperature, loss). При пустой выборке — (1.0, None).
    """
    net = model if isinstance(model, MLP) else MLP.load(model or {})
    heads = list(heads or [])
    samples = []
    for row in rows or []:
        y = row.get("y") or []
        mask = row.get("m") or []
        try:
            z = net.logits(standardizer.transform(row["x"]))
        except Exception:
            continue
        active = [(float(y[i]), float(z[i])) for i in range(len(z))
                  if i < len(y) and i < len(mask) and mask[i] > 0]
        if active:
            samples.append(active)
    if not samples:
        return 1.0, None
    low, high = bounds or TEMPERATURE_RANGE
    low = max(1e-3, float(low))
    high = max(low, float(high))
    steps = max(2, int(steps))
    best_t, best_loss = 1.0, None
    for step in range(steps):
        # Логарифмическая сетка: температуры 0.35..5 важны не линейно.
        ratio = step / float(steps - 1)
        temperature = low * ((high / low) ** ratio)
        loss = 0.0
        count = 0
        for active in samples:
            for target, logit in active:
                p = sigmoid(logit / temperature)
                p = min(max(p, 1e-9), 1.0 - 1e-9)
                loss += -(target * math.log(p) +
                          (1.0 - target) * math.log(1.0 - p))
                count += 1
        if not count:
            continue
        loss /= count
        if best_loss is None or loss < best_loss:
            best_t, best_loss = temperature, loss
    return best_t, best_loss


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
        net = MLP.load(previous)
        standardizer = _standardizer_for(previous, _train)
        return evaluate_model(net, standardizer, val_rows, heads)
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
    standardizer = Standardizer().fit([row["x"] for row in train_rows])
    input_size = len(train_rows[0]["x"])
    output_size = len(heads)
    sizes = [input_size] + hidden_layers + [output_size]

    reuse = bool(previous and previous.get("sizes") == sizes and
                 (previous.get("activation") or "tanh") == activation)
    model = MLP.load(previous) if reuse else MLP(
        sizes, seed=seed, activation=activation)

    prepared = []
    legacy_active = 0
    risky_legacy = sports.normalize_sport(sport) in LEGACY_RISK_SPORTS
    for row in train_rows:
        version = _row_version(row)
        weight = _row_weight(sport, version)
        if (risky_legacy and version < LABEL_VERSION and any(
                float(v) > 0 for v in (row.get("m") or []))):
            legacy_active += 1
        prepared.append((standardizer.transform(row["x"]), row["y"],
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
            metrics = evaluate_model(model, standardizer, val_rows, heads)
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
        metrics = evaluate_model(model, standardizer, val_rows, heads)
    # Калибровка по отложенным матчам: сеть не должна быть увереннее,
    # чем позволяет её реальная точность. Точность при этом не меняется,
    # меняется только масштаб вероятностей.
    temperature, calibration_loss = fit_temperature(
        model, standardizer, val_rows, heads)
    state = model.state()
    state["temperature"] = temperature
    state.update({
        "sport": sport,
        "layout": layout,
        "heads": list(heads),
        "standardizer": standardizer.state(),
        "meta": {
            "samples": size,
            "train_samples": len(train_rows),
            "val_samples": len(val_rows),
            "epochs": epochs,
            "best_epoch": best_epoch or epochs,
            "loss": loss,
            "accuracy": metrics["accuracy"],
            "baseline": metrics["baseline"],
            "macro_accuracy": metrics.get("macro_accuracy", 0.0),
            "lift": metrics["lift"],
            "winner_accuracy": metrics.get("winner_accuracy", 0.0),
            "over_accuracy": metrics.get("over_accuracy", 0.0),
            "head_accuracy": metrics.get("head_accuracy") or {},
            "head_baseline": metrics.get("head_baseline") or {},
            "head_train_samples": head_train_samples,
            "training_revision": TRAIN_REVISION,
            "legacy_risk": round(legacy_risk, 4),
            "legacy_weight": LEGACY_SAMPLE_WEIGHT,
            "temperature": temperature,
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
        },
    })
    return state, {"ok": True, "metrics": metrics, "epochs": epochs,
                   "best_epoch": best_epoch or epochs,
                   "architecture": list(hidden_layers),
                   "activation": activation, "finetuned": bool(reuse)}


def predict_probs(model, features):
    """Возвращает словарь head -> вероятность для готовой модели."""
    if not model:
        return {}
    standardizer = Standardizer(model.get("standardizer", {}).get("mean"),
                                model.get("standardizer", {}).get("std"))
    net = MLP.load(model)
    try:
        temperature = float(model.get("temperature") or 1.0)
    except (TypeError, ValueError):
        temperature = 1.0
    if temperature <= 0.0:
        temperature = 1.0
    logits = net.logits(standardizer.transform(features))
    probs = [sigmoid(value / temperature) for value in logits]
    heads = model.get("heads") or []
    return {head: probs[i] for i, head in enumerate(heads)
            if i < len(probs)}

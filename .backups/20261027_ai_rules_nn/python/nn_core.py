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
            })
        return rows

    parsed = sports.parse_score(sport, score_text)
    if not parsed:
        return []
    match_score = parsed["match"]
    total = parsed.get("total")
    if total is None:
        total = match_score[0] + match_score[1]
    if line is None:
        line = float(sports.default_total(sport))
    line = float(line)
    p1, p2 = int(match_score[0]), int(match_score[1])

    # Фора: первая команда закрывает линию, если разрыв больше её минуса.
    handicap_mask = 0.0
    handicap_label = 0.0
    if handicap is not None and "handicap" in bets:
        try:
            h = float(handicap)
        except (TypeError, ValueError):
            h = None
        if h is not None:
            margin = p1 - p2
            if abs(margin + h) > 1e-9:
                handicap_mask = 1.0
                handicap_label = 1.0 if (margin + h) > 0 else 0.0

    btts_mask = 1.0 if "btts" in bets else 0.0
    btts_label = 1.0 if (p1 > 0 and p2 > 0) else 0.0

    y = [
        1.0 if p1 > p2 else 0.0,
        1.0 if p2 > p1 else 0.0,
        1.0 if p1 == p2 else 0.0,
        1.0 if total > line else 0.0,
        handicap_label,
        btts_label,
    ]
    m = [1.0, 1.0, 1.0 if has_draw else 0.0, 1.0,
         handicap_mask, btts_mask]
    return [{"y": y, "m": m, "set": 0}]


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

    def __init__(self, sizes, seed=7):
        self.sizes = list(sizes)
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
                acts.append([math.tanh(v) for v in z])
        return acts

    def predict(self, x):
        return self.forward(x)[-1]

    # ---------- обучение ----------
    def train_batch(self, rows, lr=0.05, momentum=0.9, l2=0.0):
        """Один шаг mini-batch. rows: список (x, y, mask).

        l2 — слабая регуляризация весов: на сотнях примеров сеть иначе
        легко заучивает шум и «переобучается» уже к 10-й эпохе.
        """
        if not rows:
            return 0.0
        n = len(rows)
        grad_w = [[[0.0] * len(row) for row in layer]
                  for layer in self.weights]
        grad_b = [[0.0] * len(row) for row in self.biases]
        loss = 0.0
        for x, y, mask in rows:
            acts = self.forward(x)
            out = acts[-1]
            delta = []
            for j, p in enumerate(out):
                if mask[j] <= 0:
                    delta.append(0.0)
                    continue
                target = y[j]
                p = min(max(p, 1e-9), 1.0 - 1e-9)
                loss += -(target * math.log(p) + (1.0 - target) * math.log(1.0 - p))
                delta.append((p - target) * mask[j])
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
                        prev_delta[k] *= (1.0 - activation * activation)
                    delta = prev_delta

        scale = lr / float(n)
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
        return loss / float(n)

    # ---------- сохранение ----------
    def state(self):
        return {"sizes": list(self.sizes),
                "weights": [[[float(v) for v in row] for row in layer]
                            for layer in self.weights],
                "biases": [[float(v) for v in row] for row in self.biases]}

    @classmethod
    def load(cls, data):
        model = cls(data.get("sizes") or [2, 1])
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
    parts = []
    base_parts = []
    for head in heads:
        if not totals[head]:
            continue
        value = correct[head] / float(totals[head])
        head_accuracy[head] = value
        parts.append(value)
        base_parts.append(max(base[head]) / float(totals[head]))
    accuracy = sum(parts) / len(parts) if parts else 0.0
    baseline = sum(base_parts) / len(base_parts) if base_parts else 0.0
    winner_acc = (correct_winner / total_winner) if total_winner else 0.0
    over_acc = head_accuracy.get("over", 0.0)
    return {
        "accuracy": accuracy,
        "baseline": baseline,
        "lift": accuracy - baseline,
        "loss": (loss_sum / loss_n) if loss_n else 0.0,
        "winner_accuracy": winner_acc,
        "over_accuracy": over_acc,
        "winner_samples": total_winner,
        "over_samples": totals.get("over", 0),
        "head_accuracy": head_accuracy,
        "head_samples": totals,
    }


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


def evaluate_previous(sport, previous, rows):
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
        _train, val_rows = split_rows(ordered)
        net = MLP.load(previous)
        standardizer = _standardizer_for(previous, _train)
        return evaluate_model(net, standardizer, val_rows, heads)
    except Exception:
        return None


def train_model(sport, rows, previous=None, epochs=12, lr=0.05, hidden=16,
                seed=7, pause=None, l2=0.001):
    """Обучает (или дообучает) модель вида спорта.

    rows — список {"x": [...], "y": [...], "m": [...]}. previous — ранее
    обученная модель (dict), чтобы обучение продолжалось, а не начиналось
    с нуля. Возвращает (model_dict, report).

    Точность считается по отложенным матчам, а веса берутся с лучшей
    эпохи: сеть не «дообучается» до состояния, где она выучила шум.
    """
    sport = sports.normalize_sport(sport)
    _spec, heads, layout = feature_spec(sport)
    if not rows:
        return previous, {"ok": False, "error": "Нет данных"}

    rows = sorted(rows, key=lambda r: r.get("t", ""))
    size = len(rows)
    train_rows, val_rows = split_rows(rows)
    standardizer = Standardizer().fit([row["x"] for row in train_rows])
    input_size = len(train_rows[0]["x"])
    output_size = len(heads)

    model = None
    if previous and previous.get("sizes") == [input_size, hidden, output_size]:
        model = MLP.load(previous)
    if model is None:
        model = MLP([input_size, hidden, output_size], seed=seed)
        epochs = max(epochs, 12)

    prepared = [(standardizer.transform(row["x"]), row["y"], row["m"])
                for row in train_rows]
    rng = random.Random(seed + 3)
    loss = 0.0
    step = 0
    best_state = None
    best_metrics = None
    best_score = (0.0, 0.0, 0.0)
    best_epoch = 0
    for epoch in range(epochs):
        rng.shuffle(prepared)
        batch_size = 32
        for start in range(0, len(prepared), batch_size):
            batch = prepared[start:start + batch_size]
            loss = model.train_batch(batch, lr=lr, l2=l2)
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
    state = model.state()
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
            "lift": metrics["lift"],
            "winner_accuracy": metrics.get("winner_accuracy", 0.0),
            "over_accuracy": metrics.get("over_accuracy", 0.0),
            "head_accuracy": metrics.get("head_accuracy") or {},
        },
    })
    return state, {"ok": True, "metrics": metrics, "epochs": epochs,
                   "best_epoch": best_epoch or epochs}


def predict_probs(model, features):
    """Возвращает словарь head -> вероятность для готовой модели."""
    if not model:
        return {}
    standardizer = Standardizer(model.get("standardizer", {}).get("mean"),
                                model.get("standardizer", {}).get("std"))
    net = MLP.load(model)
    probs = net.predict(standardizer.transform(features))
    heads = model.get("heads") or []
    return {head: probs[i] for i, head in enumerate(heads)
            if i < len(probs)}

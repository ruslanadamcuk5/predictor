# -*- coding: utf-8 -*-
"""Прибыль, ценность ставки и банкролл: общий слой для правил и сервера.

Точность сама по себе не говорит, зарабатывает ли правило. Профессиональный
подход считает **ожидаемую ценность** (EV) относительно коэффициента:

    EV = p * odds - 1

Если модель даёт 55% при коэффициенте 2.00, EV = +10%: на дистанции такая
ставка прибыльна. Если 70% при коэффициенте 1.30, EV = -9%: высокая точность
убыточна. Поэтому правила, рекомендации и кабинет оцениваются по:

* ROI (yield) — прибыль на единицу оборота;
* EV и его нижней границе по Уилсону (осторожная оценка);
* просадке, серии поражений и размеру ставки по дробному Келли;
* out-of-sample проверке: правило должно работать на новых матчах.

Модуль не зависит от других модулей проекта, чтобы его могли использовать
и приложение, и сервер истории.
"""

from __future__ import annotations

import math

# Банкролл по умолчанию и дисциплина ставок.
DEFAULT_BANKROLL = 1000.0
KELLY_FRACTION = 0.25
MAX_STAKE_PCT = 3.0
MIN_STAKE_PCT = 0.25
# Нижняя граница EV, при которой правило считается прибыльным.
MIN_EV_LOWER = 0.005
# Минимум ставок с коэффициентом для денежных выводов.
MIN_ODDS_SAMPLE = 8
# Доля истории для проверки «на будущем».
VALIDATION_SHARE = 0.30
MIN_VALIDATION = 3
Z = 1.96


def _num(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def decimal_odds(value):
    """Коэффициент как положительное число больше 1 или None."""
    number = _num(value)
    if number is None or number <= 1.01 or number > 1000.0:
        return None
    return number


def implied_probability(odds):
    odds = decimal_odds(odds)
    return 1.0 / odds if odds else None


def wilson(wins, total, z=Z):
    """Нижняя и верхняя границы доли по Уилсону (0..1)."""
    total = int(total or 0)
    wins = max(0, min(total, int(wins or 0)))
    if total <= 0:
        return None, None
    p = wins / float(total)
    denominator = 1.0 + z * z / total
    centre = p + z * z / (2.0 * total)
    margin = z * math.sqrt(p * (1.0 - p) / total +
                           z * z / (4.0 * total * total))
    return max(0.0, (centre - margin) / denominator), \
        min(1.0, (centre + margin) / denominator)


def wilson_lower(wins, total, z=Z):
    low, _ = wilson(wins, total, z)
    return low


def kelly(probability, odds):
    """Доля банкролла по полному Келли (может быть отрицательной)."""
    p = _num(probability)
    odds = decimal_odds(odds)
    if p is None or odds is None:
        return 0.0
    value = (p * odds - 1.0) / (odds - 1.0)
    return max(-1.0, min(1.0, value))


def _row_odds(row):
    if isinstance(row, dict):
        return decimal_odds(row.get("odds"))
    if isinstance(row, (list, tuple)):
        return decimal_odds(row[1] if len(row) > 1 else None)
    return None


def _row_success(row):
    if isinstance(row, dict):
        return bool(row.get("success"))
    if isinstance(row, (list, tuple)):
        return bool(row[0])
    return False


def drawdown(profits):
    """Максимальная просадка кривой прибыли (в единицах ставки)."""
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in profits or []:
        equity += float(value or 0.0)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2)


def longest_losses(rows):
    streak = worst = 0
    for row in rows or []:
        if _row_success(row):
            streak = 0
        else:
            streak += 1
            worst = max(worst, streak)
    return worst


def _odds_side_keys(prediction):
    """Ключи коэффициентов для стороны прогноза.

    Возвращает (основные, резервные) списки: сначала рынок партии/матча,
    затем общий матч. Для партий 2–5 Betcity обычно не даёт отдельный
    коэффициент, поэтому используем матчевый как консервативную оценку.
    """
    prediction = prediction or {}
    kind = str(prediction.get("kind") or "").lower()
    target = str(prediction.get("target") or "").lower()
    side = str(prediction.get("expected_side") or "").strip().lower()
    verdict = str(prediction.get("verdict") or "").lower().replace("ё", "е")
    set_no = ""
    if target.startswith("set"):
        set_no = target[3:]
        if not set_no.isdigit():
            set_no = ""

    if kind == "winner":
        if side in ("", "auto"):
            if "п1" in verdict or "p1" in verdict:
                side = "p1"
            elif "п2" in verdict or "p2" in verdict:
                side = "p2"
            elif "ничья" in verdict or verdict.strip() == "x":
                side = "x"
        if side in ("p1", "1", "t1"):
            primary = ["set%s_p1" % set_no] if set_no else []
            return primary + ["match_p1", "set1_p1"], ["match_p1"]
        if side in ("p2", "2", "t2"):
            primary = ["set%s_p2" % set_no] if set_no else []
            return primary + ["match_p2", "set1_p2"], ["match_p2"]
        if side in ("x", "draw"):
            return ["match_draw"], []
    elif kind == "total":
        if side in ("", "auto"):
            if "тм" in verdict or "меньше" in verdict or "under" in verdict:
                side = "under"
            elif "тб" in verdict or "больше" in verdict or "over" in verdict:
                side = "over"
        if side in ("over", "больше", "тб"):
            primary = ["set%s_total_over" % set_no] if set_no else []
            return primary + ["total_over", "set1_total_over"], ["total_over"]
        if side in ("under", "меньше", "тм"):
            primary = ["set%s_total_under" % set_no] if set_no else []
            return primary + ["total_under", "set1_total_under"], ["total_under"]
    elif kind == "handicap":
        if side in ("", "auto"):
            if "ф1" in verdict or "p1" in verdict:
                side = "p1"
            elif "ф2" in verdict or "p2" in verdict:
                side = "p2"
        if side in ("p1", "1"):
            return ["handicap_p1"], []
        if side in ("p2", "2"):
            return ["handicap_p2"], []
    elif kind == "btts":
        if side in ("", "auto"):
            if "нет" in verdict or "no" in verdict:
                side = "no"
            elif "да" in verdict or "yes" in verdict:
                side = "yes"
        if side in ("yes", "да"):
            return ["btts_yes"], []
        if side in ("no", "нет"):
            return ["btts_no"], []
    return [], []


def odds_from_match(prediction, match):
    """Коэффициент на прогноз из снимка матча."""
    odds = (match or {}).get("odds") or {}
    if not isinstance(odds, dict):
        return None
    primary, backup = _odds_side_keys(prediction)
    for key in primary + backup:
        value = decimal_odds(odds.get(key))
        if value is not None:
            return value
    return None


def odds_for_observation(observation):
    """Коэффициент наблюдения: явный, из снимка статистики или None."""
    if not isinstance(observation, dict):
        return None
    explicit = decimal_odds(observation.get("odds"))
    if explicit is not None:
        return explicit
    ctx = observation.get("ctx")
    match = getattr(ctx, "match", None) if ctx is not None else None
    if match is None and isinstance(observation.get("match"), dict):
        match = observation["match"]
    odds = odds_from_match(observation.get("prediction") or {}, match or {})
    if odds is None:
        # Снимок может быть вложен в prediction (старые записи).
        odds = odds_from_match(observation.get("prediction") or {},
                               observation.get("prediction") or {})
    return odds


def rows_for_observations(observations):
    """Компактные строки для расчёта прибыли."""
    result = []
    for item in observations or []:
        if not isinstance(item, dict):
            continue
        odds = odds_for_observation(item)
        result.append({
            "success": bool(item.get("success")),
            "odds": odds,
            "sent_at": str(item.get("sent_at") or ""),
            "sport": str(item.get("sport") or ""),
            "rule_id": str(item.get("rule_id") or ""),
        })
    return result


def summarize(rows, bankroll=DEFAULT_BANKROLL, kelly_fraction=KELLY_FRACTION,
              min_sample=MIN_ODDS_SAMPLE):
    """Полная денежная статистика по списку ставок.

    ``rows`` — элементы с ``success`` и ``odds`` (или пары success, odds).
    Строки без коэффициента не участвуют в деньгах, но входят в точность.
    """
    rows = list(rows or [])
    wins = losses = 0
    odds_rows = []
    for row in rows:
        success = _row_success(row)
        if success:
            wins += 1
        else:
            losses += 1
        odds = _row_odds(row)
        if odds is not None:
            odds_rows.append((success, odds))
    resolved = wins + losses
    odds_n = len(odds_rows)
    wins_odds = sum(1 for success, _ in odds_rows if success)
    avg_odds = (sum(odds for _, odds in odds_rows) / odds_n
                if odds_n else None)
    profits = [(odds - 1.0) if success else -1.0
               for success, odds in odds_rows]
    profit = round(sum(profits), 2)
    roi = round(profit / odds_n * 100.0, 1) if odds_n else None
    hit_rate = round(wins * 100.0 / resolved, 1) if resolved else None
    hit_odds = round(wins_odds * 100.0 / odds_n, 1) if odds_n else None
    ev = None
    ev_lower = None
    if avg_odds:
        p_all = wins / float(resolved) if resolved else 0.0
        p_odds = wins_odds / float(odds_n) if odds_n else 0.0
        ev = round((p_odds * avg_odds - 1.0) * 100.0, 1) if odds_n else None
        low, high = wilson(wins_odds, odds_n)
        if low is not None:
            ev_lower = round((low * avg_odds - 1.0) * 100.0, 1)
            ev_upper = round((high * avg_odds - 1.0) * 100.0, 1)
        else:
            ev_upper = None
        p_used = p_odds
    else:
        p_all = wins / float(resolved) if resolved else 0.0
        p_odds = None
        p_used = p_all
        ev_upper = None
    kelly_value = kelly(p_used, avg_odds) if avg_odds else 0.0
    stake_pct = 0.0
    if avg_odds and ev_lower is not None and ev_lower > 0:
        stake_pct = max(MIN_STAKE_PCT,
                        min(MAX_STAKE_PCT, kelly_value * kelly_fraction * 100.0))
    elif avg_odds and ev is not None and ev > 0 and kelly_value > 0:
        stake_pct = max(MIN_STAKE_PCT,
                        min(MAX_STAKE_PCT, kelly_value * kelly_fraction * 100.0))
    expected_per_bet = (stake_pct / 100.0 * bankroll * (ev or 0) / 100.0
                        if stake_pct and ev is not None else 0.0)
    low, high = wilson(wins, resolved)
    return {
        "resolved": resolved,
        "wins": wins,
        "losses": losses,
        "hit_rate": hit_rate,
        "wilson": round(low * 100.0, 1) if low is not None else None,
        "wilson_high": round(high * 100.0, 1) if high is not None else None,
        "odds_n": odds_n,
        "odds_available": odds_n > 0,
        "odds_covered": round(odds_n * 100.0 / resolved, 1) if resolved else 0.0,
        "avg_odds": round(avg_odds, 2) if avg_odds else None,
        "implied": round(100.0 / avg_odds, 1) if avg_odds else None,
        "hit_rate_odds": hit_odds,
        "profit": profit if odds_n else None,
        "roi": roi,
        "ev": ev,
        "ev_lower": ev_lower,
        "ev_upper": ev_upper,
        "staked": odds_n,
        "turnover": round(odds_n * 1.0, 2) if odds_n else 0.0,
        "drawdown": drawdown(profits) if odds_n else None,
        "longest_loss": longest_losses(odds_rows) if odds_n else None,
        "kelly": round(kelly_value * 100.0, 1) if avg_odds else None,
        "stake_pct": round(stake_pct, 2),
        "expected_per_bet": round(expected_per_bet, 2),
        "expected_per_100": round(expected_per_bet * 100.0, 2),
        "bankroll": bankroll,
        "profitable": bool(ev_lower is not None and ev_lower > 0
                           and roi is not None and roi > 0),
        "value_ready": bool(odds_n >= max(3, int(min_sample or 0))),
        "profit_units": profit if odds_n else None,
    }


def merge_metrics(parts):
    """Складывает деньги нескольких выборок (для портфеля)."""
    parts = [item for item in parts or [] if item]
    if not parts:
        return summarize([])
    rows = []
    for item in parts:
        # Восстанавливаем средние значения: точного ряда уже нет, но для
        # суммарного ROI достаточно прибыли и оборота.
        n = int(item.get("staked") or 0)
        if not n:
            continue
        profit = float(item.get("profit") or 0.0)
        win = float(item.get("hit_rate_odds") or 0.0) / 100.0
        avg = float(item.get("avg_odds") or 1.0)
        wins = int(round(win * n))
        rows.extend([{"success": True, "odds": avg}] * wins)
        rows.extend([{"success": False, "odds": avg}] * (n - wins))
        # Прибыль может отличаться из-за разных коэффициентов; корректируем
        # первую строку, чтобы итог совпал с суммой частей.
        if rows and profit:
            pass
    result = summarize(rows)
    staked = sum(int(item.get("staked") or 0) for item in parts)
    profit = sum(float(item.get("profit") or 0.0) for item in parts)
    if staked:
        result["staked"] = staked
        result["profit"] = round(profit, 2)
        result["profit_units"] = round(profit, 2)
        result["roi"] = round(profit / staked * 100.0, 1)
    return result


def split_validation(rows, share=VALIDATION_SHARE, min_validation=MIN_VALIDATION):
    """Делит историю по времени: обучение → проверка на новых матчах."""
    ordered = sorted(
        (row for row in rows or [] if isinstance(row, dict)),
        key=lambda item: str(item.get("sent_at") or ""))
    if len(ordered) < 2:
        return ordered, []
    cut = int(round(len(ordered) * (1.0 - max(0.1, min(0.5, share)))))
    cut = max(1, min(len(ordered) - 1, cut))
    train, holdout = ordered[:cut], ordered[cut:]
    if len(holdout) < min_validation:
        # Мало данных: проверяем на последних min_validation матчах,
        # не пересекаясь с обучением.
        cut = max(1, len(ordered) - min_validation)
        train, holdout = ordered[:cut], ordered[cut:]
    return train, holdout


def validation(rows, share=VALIDATION_SHARE, min_validation=MIN_VALIDATION):
    """Метрики обучения и проверки + устойчивость прибыли."""
    train, holdout = split_validation(rows, share, min_validation)
    train_m = summarize(train)
    hold_m = summarize(holdout)
    ok = None
    if hold_m.get("odds_available") and hold_m.get("value_ready"):
        ok = bool(hold_m.get("ev_lower") is not None
                  and hold_m["ev_lower"] > 0
                  and (hold_m.get("roi") or 0) > 0)
    return {
        "train": train_m,
        "holdout": hold_m,
        "ok": ok,
        "train_n": len(train),
        "holdout_n": len(holdout),
    }


def odds_condition(prediction, floor):
    """Условие конструктора «коэффициент не ниже floor» для прогноза."""
    kind = str((prediction or {}).get("kind") or "").lower()
    side = str((prediction or {}).get("expected_side") or "").strip().lower()
    verdict = str((prediction or {}).get("verdict") or "").lower().replace("ё", "е")
    metric = ""
    if kind == "winner":
        if side in ("", "auto"):
            side = "p1" if ("п1" in verdict or "p1" in verdict) else (
                "p2" if ("п2" in verdict or "p2" in verdict) else "")
        metric = {"p1": "odds.p1", "p2": "odds.p2"}.get(side, "")
    elif kind == "total":
        if side in ("", "auto"):
            side = "under" if ("тм" in verdict or "under" in verdict) else "over"
        metric = {"over": "odds.total_over",
                  "under": "odds.total_under"}.get(side, "")
    elif kind == "handicap":
        metric = {"p1": "odds.handicap_p1",
                  "p2": "odds.handicap_p2"}.get(side, "")
    elif kind == "btts":
        metric = {"yes": "odds.btts_yes", "no": "odds.btts_no"}.get(side, "")
    if not metric:
        return None
    return {
        "metric": metric,
        "args": {},
        "op": "gte",
        "value": round(float(floor), 2),
    }


def odds_condition_title(floor, kind="total"):
    if kind == "winner":
        return "коэффициент на исход ≥ %.2f" % floor
    if kind == "handicap":
        return "коэффициент на фору ≥ %.2f" % floor
    return "коэффициент ≥ %.2f" % floor


def best_odds_floor(observations, base_metrics, min_keep=3):
    """Ищет порог коэффициента, который повышает ROI правила.

    Возвращает лучший вариант с условием и метриками или None. Порог
    подбирается по фактическим коэффициентам, а не «на глаз».
    """
    rows = rows_for_observations(observations)
    values = sorted({round(row["odds"], 2) for row in rows
                     if row.get("odds") is not None})
    if len(values) < 3:
        return None
    base_roi = base_metrics.get("roi")
    base_ev = base_metrics.get("ev_lower")
    if base_roi is None:
        return None
    candidates = set()
    for position in (0.15, 0.25, 0.35, 0.45, 0.55):
        index = min(len(values) - 1,
                    max(0, int(round(position * (len(values) - 1)))))
        candidates.add(values[index])
    if base_metrics.get("avg_odds"):
        candidates.add(round(float(base_metrics["avg_odds"]), 2))
    best = None
    for floor in sorted(candidates):
        subset = [obs for obs in observations
                  if (odds_for_observation(obs) or 0) >= floor]
        if len(subset) < max(3, int(min_keep or 3)):
            continue
        metrics = summarize(rows_for_observations(subset))
        if not metrics.get("odds_available"):
            continue
        roi = metrics.get("roi")
        ev_lower = metrics.get("ev_lower")
        if roi is None:
            continue
        # Порог должен заметно улучшить ROI и оставить положительный EV.
        if roi < max(base_roi + 2.0, 0.5):
            continue
        if ev_lower is None or ev_lower <= max(0.0, float(base_ev or 0)):
            continue
        score = roi + min(20.0, (ev_lower or 0.0)) * 0.6
        if best is None or score > best["score"]:
            best = {
                "floor": floor,
                "metrics": metrics,
                "matched": len(subset),
                "score": score,
            }
    return best

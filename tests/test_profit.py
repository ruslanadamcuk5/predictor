# -*- coding: utf-8 -*-
"""Тесты денежного слоя: EV, ROI, Уилсон, Келли, порог коэффициента.

Проверяется главное правило проекта: высокая точность не равна прибыли.
Правило должно зарабатывать на дистанции с учётом коэффициентов, а низкий
коэффициент при высокой точности обязан считаться убыточным.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import profit  # noqa: E402

PASSED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
    else:
        raise AssertionError("%s: %s" % (name, detail))


def rows(spec):
    """Строки ставок: spec — список (success, odds)."""
    return [{"success": success, "odds": odds} for success, odds in spec]


def obs(spec, start=1):
    """Наблюдения с датой, результатом и коэффициентом."""
    result = []
    for index, (success, odds) in enumerate(spec):
        result.append({
            "success": bool(success),
            "odds": odds,
            "sent_at": "2026-09-%02dT10:00:00" % (start + index),
            "sport": "football",
            "rule_id": "r1",
        })
    return result


# --------------------------------------------------------------------------
# коэффициенты и вероятности
# --------------------------------------------------------------------------

check("кэф 2.00 принят", profit.decimal_odds(2.0) == 2.0)
check("кэф 1.01 отклонён", profit.decimal_odds(1.01) is None)
check("кэф 1.00 отклонён", profit.decimal_odds(1.0) is None)
check("кэф 0 отклонён", profit.decimal_odds(0) is None)
check("кэф строкой", profit.decimal_odds("2,5") is None,
      "запятая не должна молча превращаться в число")
check("кэф строкой с точкой", profit.decimal_odds("2.5") == 2.5)
check("кэф None", profit.decimal_odds(None) is None)
check("кэф 2000 отклонён", profit.decimal_odds(2000) is None)

check("вероятность из кэфа 2.00",
      abs(profit.implied_probability(2.0) - 0.5) < 1e-9)
check("вероятность из кэфа 4.00",
      abs(profit.implied_probability(4.0) - 0.25) < 1e-9)
check("вероятность без кэфа", profit.implied_probability(None) is None)

low, high = profit.wilson(5, 10)
check("Уилсон: нижняя граница ниже доли", low < 0.5)
check("Уилсон: верхняя граница выше доли", high > 0.5)
check("Уилсон: границы в 0..1", 0.0 <= low <= high <= 1.0)
check("Уилсон: пустая выборка", profit.wilson(0, 0) == (None, None))
low_many, _ = profit.wilson(50, 100)
low_few, _ = profit.wilson(5, 10)
check("Уилсон: больше выборка — уже интервал", low_many > low_few)
check("Уилсон: все победы", profit.wilson(10, 10)[0] < 1.0)

check("Келли: value-ставка положительна",
      profit.kelly(0.55, 2.0) > 0)
check("Келли: убыточная ставка отрицательна",
      profit.kelly(0.40, 2.0) < 0)
check("Келли: ровно fair — ноль",
      abs(profit.kelly(0.50, 2.0)) < 1e-9)
check("Келли: без кэфа ноль", profit.kelly(0.6, None) == 0.0)
check("Келли: не больше 100% банка", profit.kelly(0.99, 2.0) <= 1.0)

check("просадка: пустая кривая", profit.drawdown([]) == 0.0)
check("просадка: только рост", profit.drawdown([1.0, 2.0, 3.0]) == 0.0)
check("просадка: после роста", profit.drawdown([1.0, 2.0, -1.0, -1.0]) == 2.0)
check("просадка: сразу вниз", profit.drawdown([-1.0, -1.0, 2.0]) == 2.0)
check("серия поражений", profit.longest_losses(rows(
    [(True, 2.0), (False, 2.0), (False, 2.0), (True, 2.0),
     (False, 2.0), (False, 2.0), (False, 2.0)])) == 3)
check("серия поражений: без поражений",
      profit.longest_losses(rows([(True, 2.0), (True, 2.0)])) == 0)


# --------------------------------------------------------------------------
# коэффициент прогноза
# --------------------------------------------------------------------------

match = {
    "odds": {
        "match_p1": 2.10, "match_p2": 1.75, "match_draw": 3.40,
        "total_over": 1.90, "total_under": 2.00,
        "handicap_p1": 1.95, "handicap_p2": 1.85,
        "btts_yes": 1.70, "btts_no": 2.05,
        "set2_p1": 2.40,
    }
}

check("кэф на П1", profit.odds_from_match(
    {"kind": "winner", "expected_side": "p1"}, match) == 2.10)
check("кэф на П2", profit.odds_from_match(
    {"kind": "winner", "expected_side": "p2"}, match) == 1.75)
check("кэф на ничью", profit.odds_from_match(
    {"kind": "winner", "expected_side": "x"}, match) == 3.40)
check("кэф на ТБ", profit.odds_from_match(
    {"kind": "total", "expected_side": "over"}, match) == 1.90)
check("кэф на ТМ", profit.odds_from_match(
    {"kind": "total", "expected_side": "under"}, match) == 2.00)
check("кэф на фору П1", profit.odds_from_match(
    {"kind": "handicap", "expected_side": "p1"}, match) == 1.95)
check("кэф на обе забьют", profit.odds_from_match(
    {"kind": "btts", "expected_side": "yes"}, match) == 1.70)
check("кэф на партию", profit.odds_from_match(
    {"kind": "winner", "target": "set2", "expected_side": "p1"},
    match) == 2.40)
check("кэф из вердикта П1", profit.odds_from_match(
    {"kind": "winner", "verdict": "П1"}, match) == 2.10)
check("кэф из вердикта ТМ", profit.odds_from_match(
    {"kind": "total", "verdict": "ТМ 3.5"}, match) == 2.00)
check("кэф: нет рынка", profit.odds_from_match(
    {"kind": "winner", "expected_side": "x"}, {"odds": {}}) is None)
check("кэф: нет снимка", profit.odds_from_match(
    {"kind": "winner", "expected_side": "p1"}, None) is None)
check("кэф наблюдения: явный", profit.odds_for_observation(
    {"odds": 1.88}) == 1.88)
check("кэф наблюдения: из матча", profit.odds_for_observation({
    "prediction": {"kind": "winner", "expected_side": "p1"},
    "match": match,
}) == 2.10)
check("кэф наблюдения: нет данных", profit.odds_for_observation(
    {"prediction": {"kind": "winner"}}) is None)

observation_rows = profit.rows_for_observations([
    {"success": True, "odds": 2.0, "sent_at": "2026-09-01"},
    {"success": False},
    "мусор",
])
check("строки наблюдений: только словари", len(observation_rows) == 2)
check("строки наблюдений: результат сохранён",
      observation_rows[0]["success"] is True)
check("строки наблюдений: кэф сохранён", observation_rows[0]["odds"] == 2.0)
check("строки наблюдений: без кэфа None",
      observation_rows[1]["odds"] is None)


# --------------------------------------------------------------------------
# сводка: прибыль важнее точности
# --------------------------------------------------------------------------

empty = profit.summarize([])
check("пустая сводка: нет ROI", empty["roi"] is None)
check("пустая сводка: нет кэфов", empty["odds_available"] is False)
check("пустая сводка: не прибыльна", empty["profitable"] is False)
check("пустая сводка: ставка 0", empty["stake_pct"] == 0.0)

# 65 из 100 при кэфе 2.00 — прибыльно даже по нижней границе EV.
good = profit.summarize(rows(
    [(True, 2.0)] * 65 + [(False, 2.0)] * 35))
check("прибыль: 65/100 по 2.00", good["profit"] == 30.0)
check("прибыль: ROI 30%", good["roi"] == 30.0)
check("прибыль: EV +30%", good["ev"] == 30.0)
check("прибыль: EV lower положительный", good["ev_lower"] > 0)
check("прибыль: правило прибыльно", good["profitable"] is True)
check("прибыль: ставка положительна", good["stake_pct"] > 0)
check("прибыль: ставка не больше лимита",
      good["stake_pct"] <= profit.MAX_STAKE_PCT)
check("прибыль: точность 65%", good["hit_rate"] == 65.0)
check("прибыль: средний кэф 2.00", good["avg_odds"] == 2.0)
check("прибыль: оборот равен числу ставок", good["turnover"] == 100.0)

# 7 из 10 при кэфе 1.30 — точность высокая, но ставка убыточна.
trap = profit.summarize(rows(
    [(True, 1.30)] * 7 + [(False, 1.30)] * 3))
check("ловушка: точность 70%", trap["hit_rate"] == 70.0)
check("ловушка: ROI отрицательный", trap["roi"] < 0)
check("ловушка: EV отрицательный", trap["ev"] < 0)
check("ловушка: не прибыльно", trap["profitable"] is False)
check("ловушка: ставка 0", trap["stake_pct"] == 0.0)

# 6 из 10 при кэфе 1.50 — всё ещё убыточно.
trap2 = profit.summarize(rows(
    [(True, 1.50)] * 6 + [(False, 1.50)] * 4))
check("почти: точность 60%", trap2["hit_rate"] == 60.0)
check("почти: EV отрицательный", trap2["ev"] < 0)
check("почти: не прибыльно", trap2["profitable"] is False)

# Без коэффициентов денежные метрики не выдумываются.
no_odds = profit.summarize(rows([(True, None)] * 7 + [(False, None)] * 3))
check("без кэфов: точность есть", no_odds["hit_rate"] == 70.0)
check("без кэфов: прибыли нет", no_odds["profit"] is None)
check("без кэфов: ROI нет", no_odds["roi"] is None)
check("без кэфов: value_ready False", no_odds["value_ready"] is False)

partial = profit.summarize(rows(
    [(True, 2.0), (True, 2.0), (False, 2.0), (False, None), (False, None)]))
check("частичные кэфы: в деньгах только 3",
      partial["odds_n"] == 3)
check("частичные кэфы: покрытие 60%", partial["odds_covered"] == 60.0)
check("частичные кэфы: точность по всем 5",
      partial["hit_rate"] == 40.0)

# Ставки кортежами тоже поддерживаются.
tuples = profit.summarize([(True, 2.0), (False, 2.0)])
check("кортежи: ROI 0%", tuples["roi"] == 0.0)
check("кортежи: прибыль 0", tuples["profit"] == 0.0)

small = profit.summarize(rows([(True, 2.0)] * 5 + [(False, 2.0)] * 2))
check("малая выборка: value_ready False", small["value_ready"] is False)
check("малая выборка: не прибыльно", small["profitable"] is False)

enough = profit.summarize(rows([(True, 2.0)] * 17 + [(False, 2.0)] * 3))
check("достаточная выборка: value_ready True",
      enough["value_ready"] is True)
check("достаточная выборка: прибыльно", enough["profitable"] is True)

check("сводка знает банкролл", good["bankroll"] == profit.DEFAULT_BANKROLL)
check("ожидание на ставку положительно", good["expected_per_bet"] > 0)


# --------------------------------------------------------------------------
# объединение выборок и проверка на новых матчах
# --------------------------------------------------------------------------

merged = profit.merge_metrics([good, trap])
check("объединение: ставок 110", merged["staked"] == 110)
check("объединение: прибыль сложена",
      abs(merged["profit"] - (good["profit"] + trap["profit"])) < 1e-6)
check("объединение: ROI пересчитан",
      abs(merged["roi"] - merged["profit"] / 110 * 100.0) < 0.11)
check("объединение: пустой список не падает",
      profit.merge_metrics([])["roi"] is None)

chronology = obs([(True, 2.0)] * 8 + [(False, 2.0)] * 2)
train, holdout = profit.split_validation(chronology)
check("валидация: обе части непустые", bool(train) and bool(holdout))
check("валидация: обучение раньше проверки",
      train[-1]["sent_at"] < holdout[0]["sent_at"])
check("валидация: проверка — последние матчи",
      holdout[-1]["sent_at"] == chronology[-1]["sent_at"])
check("валидация: границы не пересекаются",
      len(train) + len(holdout) == len(chronology))
check("валидация: минимум проверки",
      len(holdout) >= profit.MIN_VALIDATION)

short_train, short_hold = profit.split_validation(obs([(True, 2.0)]))
check("валидация: один матч", len(short_train) == 1 and not short_hold)

val_good = profit.validation(obs(
    ([(True, 2.0)] * 7 + [(False, 2.0)] * 3) * 10))
check("валидация: прибыльное правило подтверждено",
      val_good["ok"] is True)
check("валидация: проверка прибыльна",
      val_good["holdout"]["roi"] is not None)
val_bad = profit.validation(obs(
    ([(True, 1.30)] * 7 + [(False, 1.30)] * 3) * 10))
check("валидация: убыточное правило не подтверждено",
      val_bad["ok"] is False)
val_short = profit.validation(obs([(True, 2.0), (False, 2.0)]))
check("валидация: мало данных — None", val_short["ok"] is None)


# --------------------------------------------------------------------------
# условие «коэффициент не ниже»
# --------------------------------------------------------------------------

cond = profit.odds_condition(
    {"kind": "winner", "expected_side": "p2"}, 1.85)
check("условие кэфа: исход", cond is not None)
check("условие кэфа: метрика", cond["metric"] == "odds.p2")
check("условие кэфа: порог", cond["value"] == 1.85)
check("условие кэфа: оператор", cond["op"] == "gte")
check("условие кэфа: тоталы", profit.odds_condition(
    {"kind": "total", "expected_side": "under"}, 1.9)["metric"]
    == "odds.total_under")
check("условие кэфа: фора", profit.odds_condition(
    {"kind": "handicap", "expected_side": "p1"}, 1.9)["metric"]
    == "odds.handicap_p1")
check("условие кэфа: обе забьют", profit.odds_condition(
    {"kind": "btts", "expected_side": "no"}, 1.9)["metric"]
    == "odds.btts_no")
check("условие кэфа: неизвестный рынок", profit.odds_condition(
    {"kind": "winner"}, 1.9) is None)
check("подпись условия", "1.85" in profit.odds_condition_title(1.85))
check("подпись условия для исхода",
      "исход" in profit.odds_condition_title(1.85, "winner"))

# Порог должен отсекать дешёвые убыточные ставки и повышать ROI.
mixed = obs(
    [(True, 2.10)] * 26 + [(False, 2.15)] * 14 +
    [(True, 1.20)] * 10 + [(False, 1.25)] * 10)
base = profit.summarize(profit.rows_for_observations(mixed))
check("порог: базовая выборка имеет ROI", base["roi"] is not None)
floor = profit.best_odds_floor(mixed, base, min_keep=3)
check("порог найден", floor is not None)
if floor:
    check("порог: выше среднего кэфа", floor["floor"] > 1.5)
    check("порог: ROI вырос", floor["metrics"]["roi"] > base["roi"])
    check("порог: EV lower положительный",
          (floor["metrics"]["ev_lower"] or 0) > 0)
    check("порог: выборка не пустая", floor["matched"] >= 3)
    only_low = obs([(True, 1.2), (False, 1.2), (True, 1.3)])
    check("порог: без разброса не предлагается",
          profit.best_odds_floor(only_low, profit.summarize(
              profit.rows_for_observations(only_low))) is None)
    check("порог: без ROI не предлагается",
          profit.best_odds_floor(mixed, {"roi": None}) is None)


print("OK — проверок: %d" % len(PASSED))

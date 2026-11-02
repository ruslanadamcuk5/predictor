# -*- coding: utf-8 -*-
"""Тесты рекомендаций: мультивыбор видов и жизненный цикл правок.

Проверяется главное для экрана «Анализ»:

* выбранные галочками виды анализируются вместе, а не только активный;
* рекомендация всегда привязана к конкретному правилу и условию;
* после добавления условия рекомендация закрывается и не появляется снова;
* если условие убрать, рекомендация возвращается как новая;
* правило одного вида никогда не подсказывает правку другому виду.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "recommend_home")
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import analysis_service  # noqa: E402
import analyzer  # noqa: E402
import auto_rules  # noqa: E402
import rule_advisor  # noqa: E402

PASSED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  OK   " + name)
    else:
        raise AssertionError("%s: %s" % (name, detail))


# --------------------------------------------------------------------------
# история: одинаковые статистические формы для двух видов спорта
# --------------------------------------------------------------------------

def set_with_total(total):
    first = (total + 1) // 2
    return [first, total - first]


def recent_item(total, day, won):
    return {
        "date": "%02d.10.26" % day,
        "date_text": "%02d.10.26" % day,
        "opponent": "Соперник",
        "league": "Тест",
        "sets": [set_with_total(total) for _ in range(3)],
        "match_score": [2, 1] if won else [1, 2],
    }


def h2h_item(total, day):
    return {
        "date": "%02d.09.26" % day,
        "date_obj": None,
        "player1": "Игрок А",
        "player2": "Игрок Б",
        "sets_parsed": [set_with_total(total) for _ in range(3)],
        "match_score": "3:0",
        "winner": "P1",
    }


def build_stats(p1_total, p2_total, h2h_total):
    return {
        "team1": "Игрок А",
        "team2": "Игрок Б",
        "h2h_matches": [h2h_item(h2h_total, day) for day in range(1, 11)],
        "recent": {
            "team1": [recent_item(p1_total, day, True)
                      for day in range(1, 6)],
            "team2": [recent_item(p2_total, day, False)
                      for day in range(1, 6)],
        },
        "page_total": {
            "line": 75.5, "last5_over": 3, "last5_under": 2,
            "season_over": 128, "season_under": 129,
        },
    }


WINS = [20, 21, 22, 23, 20, 21, 22, 23, 20, 21, 22, 23]
LOSSES = [12, 13, 14, 15, 12, 13, 14, 15, 12, 13, 14, 15]


def build_history(sport, prefix, skip=0, count=None, target="set1",
                  verdict="ТБ 18.5", threshold=18.5):
    """История одного вида: половина удач, половина неудач."""
    history = {}
    index = 0
    for success, totals in ((True, WINS), (False, LOSSES)):
        for total in totals:
            if index < skip:
                index += 1
                continue
            if count is not None and len(history) >= count:
                break
            match = {
                "match_id": "%s%02d" % (prefix, index),
                "team1": "Игрок А", "team2": "Игрок Б",
                "sport": sport, "league": "Тест",
                "date": "19.10 20:30",
                "start_time": "2026-10-19T20:30", "stat_link": "/x",
                "is_started": False, "current_score": "0:0", "odds": {},
            }
            prediction = {
                "target": target, "kind": "total",
                "label": "Тотал", "verdict": verdict,
                "expected_side": "over",
                "threshold": threshold, "confidence_val": 0.6,
            }
            history["%s%02d" % (prefix, index)] = {
                "team1": "Игрок А", "team2": "Игрок Б",
                "date": "%02d.10.26" % (index + 1), "league": "Тест",
                "sent_at": "2026-10-%02dT12:00:00" % (1 + index % 28),
                "predictions": [prediction],
                "set_results": [{
                    "target": target, "kind": "total", "success": success,
                    "score": "11:10" if success else "8:7",
                    "total": total, "label": prediction["label"],
                    "verdict": prediction["verdict"],
                }],
                "stats": analyzer.make_sample(
                    match, build_stats(total, 18, 20)),
                "result_checked": True,
            }
            index += 1
    return history


TT = build_history("table_tennis", "tt")
FB = build_history("football", "fb", target="match",
                   verdict="ТБ 2.5", threshold=2.5)
BOTH = {}
BOTH.update(TT)
BOTH.update(FB)

print("История: настольный теннис %d, футбол %d" % (len(TT), len(FB)))
check("история настольного тенниса", len(TT) == 24, len(TT))
check("история футбола", len(FB) == 24, len(FB))

# --------------------------------------------------------------------------
# 1. Мультивыбор видов спорта
# --------------------------------------------------------------------------
report = analysis_service.build_report(BOTH, {"sports": ["table_tennis"]})
payload = report["payload"]
check("один вид: выбран ровно он",
      payload["sports_selected"] == ["table_tennis"], payload["sports_selected"])
check("один вид: один блок анализа", len(payload["sports"]) == 1)
check("один вид: наблюдения только его",
      payload["observations"]["total"] == len(TT),
      payload["observations"])
check("один вид: нет строк чужого вида",
      all(row.get("sport") == "table_tennis"
          for row in payload["failure"] + payload["success"]),
      payload["failure"][:1] + payload["success"][:1])

report = analysis_service.build_report(BOTH, {
    "sports": ["table_tennis", "football"]})
payload = report["payload"]
check("два вида: оба в списке",
      payload["sports_selected"] == ["table_tennis", "football"],
      payload["sports_selected"])
check("два вида: два блока анализа", len(payload["sports"]) == 2,
      [item.get("sport") for item in payload["sports"]])
check("два вида: наблюдения суммируются",
      payload["observations"]["total"] == len(TT) + len(FB),
      payload["observations"])
check("два вида: подпись содержит оба",
      "Наст. теннис" in payload["sport_name"]
      and "Футбол" in payload["sport_name"], payload["sport_name"])

report = analysis_service.build_report(BOTH, {"sports": ["football"]})
payload = report["payload"]
check("только футбол: выбран он",
      payload["sports_selected"] == ["football"], payload["sports_selected"])
check("только футбол: наблюдения футбола",
      payload["observations"]["total"] == len(FB), payload["observations"])
check("только футбол: нет строк тенниса",
      all(row.get("sport") == "football"
          for row in payload["failure"] + payload["success"]),
      payload["failure"][:1] + payload["success"][:1])

# --------------------------------------------------------------------------
# 2. Рекомендация привязана к правилу и условию
# --------------------------------------------------------------------------
RULE = {
    "id": "rule-tt", "name": "Тотал партии", "enabled": True, "priority": 100,
    "conditions": {"logic": "and", "conditions": []},
    "action": {"type": "total", "targets": [1], "side": "over",
               "threshold": 18.5, "confidence": 0.6},
}
OTHER_RULE = json.loads(json.dumps(RULE))
OTHER_RULE["id"] = "rule-fb"
OTHER_RULE["name"] = "Футбольный тотал"
OTHER_RULE["action"]["targets"] = ["match"]
OTHER_RULE["action"]["threshold"] = 2.5

first = rule_advisor.recommend(
    BOTH, ["table_tennis"], {"table_tennis": [RULE]})
check("рекомендация найдена", len(first["recommendations"]) >= 1,
      first["recommendations"])
rec = first["recommendations"][0]
check("тип — добавить условие", rec["type"] == "add_condition", rec["type"])
check("рекомендация знает вид", rec["sport"] == "table_tennis", rec["sport"])
check("рекомендация знает правило", rec["rule_id"] == "rule-tt", rec["rule_id"])
check("в рекомендации есть условие",
      isinstance(rec.get("condition"), dict)
      and bool(rec.get("condition_text")), rec.get("condition"))
check("в рекомендации есть цифры",
      rec.get("precision_before") is not None
      and rec.get("precision_after") is not None
      and rec.get("matched_before"), rec)
check("рекомендация новая при первом показе", rec["is_new"] is True)
check("рекомендация не закрыта", first["resolved"] == [], first["resolved"])

# Правило другого вида не должно подсказываться в выбранном виде.
mixed = rule_advisor.recommend(
    BOTH, ["table_tennis"],
    {"table_tennis": [RULE], "football": [OTHER_RULE]})
check("чужое правило не попадает в рекомендации",
      all(item["sport"] == "table_tennis" and item["rule_id"] == "rule-tt"
          for item in mixed["recommendations"]),
      mixed["recommendations"])
check("нет рекомендаций по футбольному правилу",
      all(item["rule_id"] != "rule-fb"
          for item in mixed["recommendations"]))

# --------------------------------------------------------------------------
# 2b. Обратный кандидат: текст совпадает со знаком, который предлагаем
# --------------------------------------------------------------------------
# Раньше для условия из неудач брался текст исходной строки, и вместо
# «< 3» рекомендация показывала «≥ 3». Пользователь применял условие,
# противоположное задуманному, и правило замолкало.
failure_row = {
    "condition": {"metric": "p.recent.matches_last_7d", "op": "gte",
                  "value": 3.0, "args": {"side": "p2", "window": 3}},
    "text": "Игр игрока 2 за последние 7 дней ≥ 3",
    "lift": 12.0, "loss_share": 80.0,
}
original_rows = rule_advisor._analysis_rows
try:
    rule_advisor._analysis_rows = lambda sport, group, min_group: {
        "success": [], "failure": [failure_row]}
    pool = rule_advisor._candidate_pool("table_tennis", [], 1)
finally:
    rule_advisor._analysis_rows = original_rows
check("обратный кандидат инвертирует знак",
      pool and pool[0]["condition"]["op"] == "lt",
      pool[0]["condition"] if pool else pool)
check("текст обратного кандидата описывает инвертированный знак",
      pool and pool[0]["text"] == rule_advisor.ce.describe_condition(
          pool[0]["condition"], sport="table_tennis"),
      pool[0]["text"] if pool else pool)
check("текст не повторяет исходное «≥»",
      pool and "≥" not in pool[0]["text"] and "<" in pool[0]["text"],
      pool[0]["text"] if pool else pool)

both = rule_advisor.recommend(
    BOTH, ["table_tennis", "football"],
    {"table_tennis": [RULE], "football": [OTHER_RULE]})
check("мультивыбор: рекомендации по обоим видам",
      {item["sport"] for item in both["recommendations"]}
      == {"table_tennis", "football"},
      [(item["sport"], item["rule_id"])
       for item in both["recommendations"]])
check("мультивыбор: правило совпадает с видом",
      all(item["sport"] == ("table_tennis" if item["rule_id"] == "rule-tt"
                            else "football")
          for item in both["recommendations"]),
      both["recommendations"])

# --------------------------------------------------------------------------
# 3. Жизненный цикл: применили условие — рекомендация закрылась
# --------------------------------------------------------------------------
rec_id = rec["id"]
fixed_rule = json.loads(json.dumps(RULE))
fixed_rule["conditions"] = rec["patch"]["conditions"]

second = rule_advisor.recommend(
    BOTH, ["table_tennis"], {"table_tennis": [fixed_rule]},
    state=first["advisor_state"])
check("после правки рекомендации нет",
      all(item["id"] != rec_id for item in second["recommendations"]),
      second["recommendations"])
check("рекомендация закрыта автоматически",
      any(item["id"] == rec_id for item in second["resolved"]),
      second["resolved"])
check("состояние помнит закрытие",
      rec_id in (second["advisor_state"].get("resolved") or {}),
      second["state"])

# Убрали условие — приложение должно снова увидеть рекомендацию как новую.
third = rule_advisor.recommend(
    BOTH, ["table_tennis"], {"table_tennis": [RULE]},
    state=second["advisor_state"])
again = [item for item in third["recommendations"] if item["id"] == rec_id]
check("после отката рекомендация вернулась", bool(again), third["recommendations"])
check("вернувшаяся рекомендация снова новая",
      bool(again) and again[0]["is_new"] is True,
      again[0] if again else None)

# --------------------------------------------------------------------------
# 4. Скрытие на время и отсутствие повторов
# --------------------------------------------------------------------------
hidden = rule_advisor.dismiss(
    json.loads(json.dumps(third["advisor_state"])), rec_id)
fourth = rule_advisor.recommend(
    BOTH, ["table_tennis"], {"table_tennis": [RULE]}, state=hidden)
check("скрытая рекомендация не показывается",
      all(item["id"] != rec_id for item in fourth["recommendations"]),
      fourth["recommendations"])

# Повторный прогон без правок не должен объявлять рекомендацию новой.
fifth = rule_advisor.recommend(
    BOTH, ["table_tennis"], {"table_tennis": [RULE]},
    state=third["advisor_state"])
repeat = [item for item in fifth["recommendations"] if item["id"] == rec_id]
check("повторный показ не считается новым",
      bool(repeat) and repeat[0]["is_new"] is False,
      repeat[0] if repeat else None)
check("счётчик показов растёт",
      bool(repeat) and repeat[0]["seen_count"] >= 1,
      repeat[0] if repeat else None)

# --------------------------------------------------------------------------
# 5. Полный отчёт: рекомендации внутри анализа
# --------------------------------------------------------------------------
report = analysis_service.build_report(
    BOTH, {"sports": ["table_tennis", "football"]},
    rules_by_sport={"table_tennis": [RULE], "football": [OTHER_RULE]})
advice = report["payload"]["recommendations"]
check("отчёт отдаёт рекомендации", advice.get("ok") is True, advice)
check("отчёт: рекомендации по выбранным видам",
      {item["sport"] for item in advice["recommendations"]}
      <= {"table_tennis", "football"},
      advice["recommendations"])
check("отчёт: состояние сохраняется",
      isinstance(report.get("advisor_state"), dict)
      and "seen" in report["advisor_state"], report.get("advisor_state"))
check("отчёт: портфель присутствует",
      isinstance(report["payload"].get("portfolio"), dict),
      report["payload"].get("portfolio"))
check("отчёт: денежная сводка присутствует",
      isinstance(report["payload"].get("money"), dict),
      report["payload"].get("money"))

# --------------------------------------------------------------------------
# 6. Денежный портфель: только подтверждённые прибылью правила
# --------------------------------------------------------------------------

def portfolio_base(profitable=True, odds=True, stake=6.0, validation_ok=None):
    rows = [{"success": True, "odds": 2.0}] * 20 + \
           [{"success": False, "odds": 2.0}] * 10
    return {
        "kind": "total",
        "target": "match",
        "action": {"type": "total", "side": "over"},
        "condition_group": {"logic": "and", "conditions": []},
        "conditions": [],
        "matched": len(rows),
        "wins": 20,
        "losses": 10,
        "precision": 66.7,
        "base": 50.0,
        "group_size": len(rows),
        "skip": False,
        "money": {
            "odds_available": odds,
            "value_ready": odds,
            "profitable": profitable,
            "roi": 33.3 if profitable else -5.0,
            "ev": 33.3 if profitable else -5.0,
            "ev_lower": 8.0 if profitable else -12.0,
            "profit": 10.0 if profitable else -1.5,
            "drawdown": 2.0,
            "avg_odds": 2.0,
            "odds_n": len(rows) if odds else 0,
            "stake_pct": stake,
            "kelly": 66.7,
        },
        "matched_rows": rows if odds else [],
        "validation": {"ok": validation_ok},
    }


entries = [
    {"sport": "table_tennis", "rule": {"id": "core1", "name": "Ядро 1"},
     "base": portfolio_base()},
    {"sport": "football", "rule": {"id": "core2", "name": "Ядро 2"},
     "base": portfolio_base()},
    {"sport": "football", "rule": {"id": "drop1", "name": "Убыточное"},
     "base": portfolio_base(profitable=False)},
    {"sport": "hockey", "rule": {"id": "no1", "name": "Без кэфов"},
     "base": portfolio_base(odds=False)},
    {"sport": "tennis", "rule": {"id": "frag1", "name": "Хрупкое"},
     "base": portfolio_base(validation_ok=False)},
]
bucket = rule_advisor._portfolio(entries)
check("портфель: ядро только прибыльные",
      {item["rule_id"] for item in bucket["core"]}
      == {"core1", "core2"}, bucket["core"])
check("портфель: убыточное вне ядра", bucket["counts"].get("drop") == 1,
      bucket["counts"])
check("портфель: без кэфов отмечено", bucket["counts"].get("no_odds") == 1,
      bucket["counts"])
check("портфель: хрупкое не в ядре", bucket["counts"].get("fragile") == 1,
      bucket["counts"])
check("портфель: экспозиция в лимите",
      bucket["total_stake_pct"] <= bucket["budget_pct"] + 0.01,
      bucket["total_stake_pct"])
check("портфель: ставки пересчитаны",
      all(num_item["stake_pct"] <= 6.0 for num_item in bucket["core"]),
      bucket["core"])
check("портфель: ожидание положительно", bucket["expected_per_bet"] > 0,
      bucket["expected_per_bet"])
check("портфель: есть подсказка", bool(bucket["hint"]), bucket["hint"])
check("портфель: пустой не падает",
      rule_advisor._portfolio([]).get("core") == [],
      rule_advisor._portfolio([]))

# --------------------------------------------------------------------------
# 7. Рекомендация «поднять коэффициент»: жизненный цикл и применение
# --------------------------------------------------------------------------
floor_condition = {
    "metric": "odds.total_over", "args": {}, "op": "gte", "value": 1.9,
}
floor_rule = json.loads(json.dumps(RULE))
floor_rule["conditions"] = {"logic": "and", "conditions": [floor_condition]}
floor_rec = {"type": "add_odds_floor", "condition": floor_condition}
done, reason = rule_advisor._is_resolved(floor_rec, floor_rule)
check("порог кэфа: условие уже есть — рекомендация закрыта",
      done is True, reason)
open_rule = json.loads(json.dumps(RULE))
done, reason = rule_advisor._is_resolved(floor_rec, open_rule)
check("порог кэфа: без условия — рекомендация открыта", done is False,
      reason)

import engine_api  # noqa: E402
applied, message = engine_api.Engine._apply_rec_to_rule(
    None, open_rule, {
        "type": "add_odds_floor",
        "condition": floor_condition,
        "patch": {"conditions": {"logic": "and",
                                 "conditions": [floor_condition]}},
    })
check("порог кэфа: применяется к правилу", applied is not None, message)
check("порог кэфа: условие добавлено",
      applied and rule_advisor._contains(applied.get("conditions"),
                                         floor_condition),
      applied)
check("порог кэфа: подпись действия",
      rule_advisor.TYPE_TITLES.get("add_odds_floor") == "Поднять коэффициент",
      rule_advisor.TYPE_TITLES)

# --------------------------------------------------------------------------
# 8. «Засуха» правила: слишком жёсткое правило предлагают смягчить
# --------------------------------------------------------------------------
STARVED = {
    "id": "rule-starved", "name": "ТБ 18.5: оба верховые",
    "enabled": True, "priority": 100,
    "conditions": {"logic": "and", "conditions": [
        {"metric": "p.recent.over_rate",
         "args": {"side": "p1", "window": 5, "threshold": 18.5},
         "op": "gte", "value": 60.0},
        {"metric": "p.recent.over_rate",
         "args": {"side": "p2", "window": 5, "threshold": 18.5},
         "op": "gte", "value": 60.0},
    ]},
    "action": {"type": "total", "targets": [1], "side": "over",
               "threshold": 18.5, "confidence": 0.64},
}

starved = rule_advisor.recommend(
    BOTH, ["table_tennis"], {"table_tennis": [STARVED]})
drought = [item for item in starved["recommendations"]
           if item["type"] == "loosen_rule"]
check("засуха: правило без срабатываний получает рекомендацию",
      len(drought) == 1, starved["recommendations"])
if drought:
    drec = drought[0]
    check("засуха: заголовок типа",
          drec["type_title"] == "Смягчить правило", drec.get("type_title"))
    check("засуха: привязана к правилу и условию",
          drec["rule_id"] == "rule-starved" and bool(drec.get("condition"))
          and bool(drec.get("change_text")), drec)
    check("засуха: правка реально расширяет правило",
          drec["patch"]["conditions"] != STARVED["conditions"]
          and drec["matched_after"] >= 6, drec.get("patch"))
    check("засуха: точность после в допустимых пределах",
          drec["precision_after"] >= 57.0, drec.get("precision_after"))
    check("засуха: причина объясняет тишину",
          "молчит" in drec["reason"], drec.get("reason"))
    check("засуха: причина говорит об осторожности",
          "осторожное" in drec["reason"], drec.get("reason"))

    again = rule_advisor.recommend(
        BOTH, ["table_tennis"], {"table_tennis": [STARVED]},
        state=starved["advisor_state"])
    again_rec = [item for item in again["recommendations"]
                 if item["type"] == "loosen_rule"]
    check("засуха: id рекомендации стабилен",
          bool(again_rec) and again_rec[0]["id"] == drec["id"], again_rec)
    check("засуха: повторно не новая",
          bool(again_rec) and again_rec[0]["is_new"] is False,
          again_rec and again_rec[0].get("is_new"))

    applied_rule, message = engine_api.Engine._apply_rec_to_rule(
        None, STARVED, drec)
    check("засуха: правка применяется к правилу",
          applied_rule is not None, message)
    done, reason = rule_advisor._is_resolved(drec, applied_rule)
    check("засуха: после применения рекомендация закрыта",
          done is True, reason)
    after = rule_advisor.recommend(
        BOTH, ["table_tennis"], {"table_tennis": [applied_rule]})
    check("засуха: после применения та же рекомендация не возвращается",
          all(item["type"] != "loosen_rule" or item["id"] != drec["id"]
              for item in after["recommendations"]),
          after["recommendations"])

WIDEN = {
    "id": "rule-widen", "name": "ТБ 18.5: высокий тотал",
    "enabled": True, "priority": 100,
    "conditions": {"logic": "and", "conditions": [
        {"metric": "p.recent.avg_set_total",
         "args": {"side": "p1", "window": 5},
         "op": "gte", "value": 23.5},
    ]},
    "action": {"type": "total", "targets": [1], "side": "over",
               "threshold": 18.5, "confidence": 0.62},
}
widened = rule_advisor.recommend(
    BOTH, ["table_tennis"], {"table_tennis": [WIDEN]})
wrec = [item for item in widened["recommendations"]
        if item["type"] == "loosen_rule"]
check("засуха: единственное условие смягчают, а не убирают",
      len(wrec) == 1 and wrec[0]["change_kind"] == "widen", wrec)
if wrec:
    check("засуха: порог сдвинут в сторону рынка",
          wrec[0]["condition_after"]["value"] < 23.5,
          wrec[0].get("condition_after"))
    check("засуха: после смягчения есть сигналы и точность",
          wrec[0]["matched_after"] >= 6
          and wrec[0]["precision_after"] >= 57.0, wrec[0])
    # При засухе важен не минимальный сдвиг, а возврат покрытия: если
    # несколько порогов держат точность, выбираем самый широкий.
    check("засуха: из безопасных вариантов выбирают самый широкий",
          wrec[0]["matched_after"] == 9, wrec[0].get("matched_after"))

ACTIVE = {
    "id": "rule-active", "name": "ТБ 18.5: форма игрока 1",
    "enabled": True, "priority": 100,
    "conditions": {"logic": "and", "conditions": [
        {"metric": "p.recent.over_rate",
         "args": {"side": "p1", "window": 5, "threshold": 18.5},
         "op": "gte", "value": 60.0},
    ]},
    "action": {"type": "total", "targets": [1], "side": "over",
               "threshold": 18.5, "confidence": 0.6},
}
active = rule_advisor.recommend(
    BOTH, ["table_tennis"], {"table_tennis": [ACTIVE]})
check("засуха: работающее правило не получает ложного смягчения",
      all(item["type"] != "loosen_rule"
          for item in active["recommendations"]),
      active["recommendations"])

# --------------------------------------------------------------------------
# 8b. Засуха по свежести: правило сработало в прошлом, но замолчало
# --------------------------------------------------------------------------

def custom_history(rows, prefix="cx"):
    """История с точным контролем тотала, результата и времени сигнала."""
    history = {}
    for index, (total, success, sent_at) in enumerate(rows):
        match = {
            "match_id": "%s%02d" % (prefix, index),
            "team1": "Игрок А", "team2": "Игрок Б",
            "sport": "table_tennis", "league": "Тест",
            "date": "19.10 20:30", "start_time": "2026-10-19T20:30",
            "stat_link": "/x", "is_started": False,
            "current_score": "0:0", "odds": {},
        }
        prediction = {
            "target": "set1", "kind": "total", "label": "Тотал",
            "verdict": "ТБ 18.5", "expected_side": "over",
            "threshold": 18.5, "confidence_val": 0.6,
        }
        history["%s%02d" % (prefix, index)] = {
            "team1": "Игрок А", "team2": "Игрок Б",
            "date": "19.10.26", "league": "Тест", "sent_at": sent_at,
            "predictions": [prediction],
            "set_results": [{
                "target": "set1", "kind": "total", "success": success,
                "score": "11:10" if success else "8:7",
                "total": total, "label": "Тотал", "verdict": "ТБ 18.5",
            }],
            "stats": analyzer.make_sample(
                match, build_stats(total, 18, 20)),
            "result_checked": True,
        }
    return history


def total_rule(value, rule_id, op="gte"):
    return {
        "id": rule_id, "name": "Средний тотал игрока 1",
        "enabled": True, "priority": 100,
        "conditions": {"logic": "and", "conditions": [
            {"metric": "p.recent.avg_set_total",
             "args": {"side": "p1", "window": 5},
             "op": op, "value": value},
        ]},
        "action": {"type": "total", "targets": [1], "side": "over",
                   "threshold": 18.5, "confidence": 0.6},
    }


def loosen_only(history, rule):
    result = rule_advisor.recommend(
        history, ["table_tennis"], {"table_tennis": [rule]})
    return [item for item in result["recommendations"]
            if item["type"] == "loosen_rule"]


# Шесть старых срабатываний, затем рынок жил ещё шесть матчей без сигналов.
STALE_ROWS = [
    (23, True, "2026-10-01T12:00:00"), (22, True, "2026-10-02T12:00:00"),
    (22, True, "2026-10-03T12:00:00"), (22, True, "2026-10-04T12:00:00"),
    (22, True, "2026-10-05T12:00:00"), (22, False, "2026-10-06T12:00:00"),
    (20, True, "2026-10-07T12:00:00"), (20, True, "2026-10-08T12:00:00"),
    (20, True, "2026-10-09T12:00:00"), (20, False, "2026-10-10T12:00:00"),
    (19, True, "2026-10-11T12:00:00"), (19, False, "2026-10-12T12:00:00"),
]
stale_rule = total_rule(21.5, "rule-stale")
stale_recs = loosen_only(custom_history(STALE_ROWS), stale_rule)
check("свежесть: правило с историей, но давно молчит — рекомендация есть",
      len(stale_recs) == 1, stale_recs)
if stale_recs:
    stale_rec = stale_recs[0]
    check("свежесть: срабатываний до правки достаточно",
          stale_rec["matched_before"] >= 6, stale_rec.get("matched_before"))
    check("свежесть: тишина измерена матчами рынка",
          stale_rec.get("silent_market") >= 6, stale_rec.get("silent_market"))
    check("свежесть: правка возвращает новые срабатывания",
          stale_rec["matched_after"] > stale_rec["matched_before"],
          stale_rec.get("matched_after"))
    check("свежесть: точность после правки не ниже прежней",
          stale_rec["precision_after"] >= 60.0,
          stale_rec.get("precision_after"))
    check("свежесть: застоявшееся правило не отключают",
          stale_rec["type"] == "loosen_rule"
          and stale_rec["change_kind"] == "widen", stale_rec)

# Цель недостижима, но сигналы возвращаются с точностью выше среднего по рынку.
RELAXED_ROWS = [
    (23, True, "2026-10-01T12:00:00"), (23, True, "2026-10-02T12:00:00"),
    (23, True, "2026-10-03T12:00:00"), (20, False, "2026-10-04T12:00:00"),
    (20, False, "2026-10-05T12:00:00"), (20, False, "2026-10-06T12:00:00"),
    (19, True, "2026-10-07T12:00:00"), (19, True, "2026-10-08T12:00:00"),
    (19, False, "2026-10-09T12:00:00"), (19, False, "2026-10-10T12:00:00"),
    (18, False, "2026-10-11T12:00:00"), (18, False, "2026-10-12T12:00:00"),
]
relaxed_rule = total_rule(20, "rule-relaxed")
relaxed_recs = loosen_only(custom_history(RELAXED_ROWS), relaxed_rule)
check("запасное смягчение: рекомендация есть", len(relaxed_recs) == 1,
      relaxed_recs)
if relaxed_recs:
    relaxed_rec = relaxed_recs[0]
    check("запасное смягчение: помечено как relaxed",
          relaxed_rec.get("precision_relaxed") is True, relaxed_rec)
    check("запасное смягчение: вернуло новые срабатывания",
          relaxed_rec["matched_after"] > relaxed_rec["matched_before"],
          relaxed_rec.get("matched_after"))
    check("запасное смягчение: точность выше средней по рынку",
          relaxed_rec["precision_after"] > relaxed_rec["base_precision"],
          (relaxed_rec.get("precision_after"),
           relaxed_rec.get("base_precision")))
    check("запасное смягчение: причина это объясняет",
          "выше средней по рынку" in relaxed_rec["reason"],
          relaxed_rec.get("reason"))

# Смягчение, которое не добавляет ни одного сигнала, не предлагается.
NOOP_HISTORY = custom_history(RELAXED_ROWS, prefix="no")
noop_obs = analyzer.build_observations(NOOP_HISTORY, sport="table_tennis")
noop_groups = auto_rules._groups(noop_obs, "table_tennis")
noop_group = noop_groups[("total", "set1")]
noop_rule = total_rule(100, "rule-noop", op="lte")
noop_base = rule_advisor._evaluate_rule(
    noop_rule, noop_group, "table_tennis")
check("без прироста: правило уже покрывает весь рынок",
      noop_base["matched"] == len(noop_group),
      (noop_base["matched"], len(noop_group)))
check("без прироста: смягчение отклонено",
      rule_advisor._simulate_loosen(
          noop_group, noop_base, "table_tennis", 6, 60.0) is None,
      rule_advisor._simulate_loosen(
          noop_group, noop_base, "table_tennis", 6, 60.0))


print("OK — пройдено проверок: %d" % len(PASSED))

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

print("OK — пройдено проверок: %d" % len(PASSED))

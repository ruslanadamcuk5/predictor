# -*- coding: utf-8 -*-
"""Тесты авто-формирования правил по статистике прогнозов."""

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "auto_rules_home")
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import analyzer  # noqa: E402
import auto_rules  # noqa: E402
import constructor_engine as ce  # noqa: E402
import engine_api as api  # noqa: E402

PASSED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
    else:
        raise AssertionError("%s: %s" % (name, detail))


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
            "team1": [recent_item(p1_total, day, True) for day in range(1, 6)],
            "team2": [recent_item(p2_total, day, False) for day in range(1, 6)],
        },
        "page_total": {
            "line": 75.5, "last5_over": 3, "last5_under": 2,
            "season_over": 128, "season_under": 129,
        },
    }


MATCH = {
    "match_id": "auto1", "team1": "Игрок А", "team2": "Игрок Б",
    "league": "Тест", "date": "19.10 20:30",
    "start_time": "2026-10-19T20:30", "stat_link": "/x",
    "is_started": False, "current_score": "0:0",
    "odds": {"match_p1": 1.85, "match_p2": 1.95},
}

WINS = [20, 21, 22, 23, 20, 21, 22, 23, 20, 21, 22, 23]
LOSSES = [12, 13, 14, 15, 12, 13, 14, 15, 12, 13, 14, 15]

sent = {}
index = 0
for success, totals in ((True, WINS), (False, LOSSES)):
    for total in totals:
        sample = analyzer.make_sample(
            MATCH, build_stats(total, 18, 20))
        pred_id = "auto%02d" % index
        sent[pred_id] = {
            "team1": "Игрок А", "team2": "Игрок Б",
            "date": "%02d.10.26 20:00" % (index + 1),
            "league": "Тест",
            "sent_at": "2026-10-%02dT12:00:00" % (1 + index % 28),
            "predictions": [{
                "target": "set1", "kind": "total",
                "label": "Партия 1 (ТБ18.5/ТМ18.5)",
                "verdict": "ТБ 18.5", "expected_side": "over",
                "threshold": 18.5, "confidence_val": 0.6,
            }],
            "set_results": [{
                "target": "set1", "kind": "total", "success": success,
                "score": "11:10" if success else "8:7",
                "total": total,
                "label": "Партия 1 (ТБ18.5/ТМ18.5)",
                "verdict": "ТБ 18.5",
            }],
            "stats": sample,
            "result_checked": True,
        }
        index += 1

# ---------------------------------------------------------------------
# 1. Генерация
# ---------------------------------------------------------------------
result = auto_rules.generate(sent, "table_tennis", min_precision=60,
                             min_samples=6, max_rules=4)
check("генерация ok", result["ok"] is True, result)
check("наблюдений 24", result["observations"] == 24, result["observations"])
check("правила созданы", bool(result["rules"]), result)
check("есть подпись", bool(result["signature"]))
check("в отчёте есть группа", bool(result["groups"]), result["groups"])

prediction_rules = [rule for rule in result["rules"]
                    if (rule.get("action") or {}).get("type") != "skip"]
check("есть правило-прогноз", bool(prediction_rules), result["rules"])
rule = prediction_rules[0]
check("правило помечено auto", rule.get("auto") is True, rule)
check("у правила есть статистика", isinstance(rule.get("auto_stats"), dict))
check("точность не ниже порога",
      (rule.get("auto_stats") or {}).get("precision", 0) >= 60, rule)
check("есть условия", bool((rule.get("conditions") or {}).get("conditions")))
check("действие тотал", (rule.get("action") or {}).get("type") == "total", rule)
check("сторона over", (rule.get("action") or {}).get("side") == "over", rule)
check("цель set1", (rule.get("action") or {}).get("targets") == [1], rule)
check("имя не пустое", bool(rule.get("name")), rule)
check("id уникальны",
      len({item.get("id") for item in result["rules"]}) == len(result["rules"]))
check("повторная генерация стабильна",
      auto_rules.generate(sent, "table_tennis", min_precision=60,
                          min_samples=6, max_rules=4)["signature"] ==
      result["signature"])

# ---------------------------------------------------------------------
# 2. Сохранение в конструктор сохраняет служебные поля
# ---------------------------------------------------------------------
ctor = ce.ConstructorEngine(path=os.path.join(HOME, "constructor_rules.json"))
manual = {
    "name": "Ручное правило", "enabled": True, "priority": 100,
    "conditions": {"logic": "and", "conditions": [
        {"metric": "h2h.count", "args": {}, "op": "gte", "value": 0}]},
    "action": {"type": "total", "targets": [1], "side": "over",
               "threshold": 18.5, "confidence": 0.6},
}
ok, errors, saved = ctor.save({"rules": [manual] + result["rules"]},
                              "table_tennis")
check("конструктор сохранил", ok, errors)
check("ручное правило на месте",
      any(item.get("name") == "Ручное правило" for item in saved))
check("auto-поля сохранены",
      any(item.get("auto") and item.get("auto_stats") for item in saved),
      saved)

# ---------------------------------------------------------------------
# 2б. Проверка активных правил: отзывы и готовые правки
# ---------------------------------------------------------------------
active = [item for item in saved if item.get("enabled")]
review = auto_rules.review_rules(
    sent, "table_tennis", active, min_samples=6, min_precision=60)
check("проверка правил ok", review.get("ok") is True, review)
check("проверены все активные", review.get("total") == len(active), review)
check("у отзыва есть вердикт",
      all(item.get("verdict") for item in review.get("reviews") or []), review)
check("у отзыва есть точность",
      all("precision" in item for item in review.get("reviews") or []), review)
check("у отзыва есть условия",
      all("conditions_text" in item for item in review.get("reviews") or []),
      review)
empty_review = auto_rules.review_rules(sent, "table_tennis", [])
check("без правил подсказка", empty_review.get("total") == 0 and
      bool(empty_review.get("hint")), empty_review)

# ---------------------------------------------------------------------
# 3. Действие из старого прогноза без expected_side
# ---------------------------------------------------------------------
legacy = auto_rules.action_from_prediction(
    {"target": "set1", "kind": "total", "verdict": "ТМ 18.5"},
    sport="table_tennis")
check("сторона из вердикта", legacy and legacy.get("side") == "under", legacy)
check("линия из вердикта", legacy and legacy.get("threshold") == 18.5, legacy)
team = auto_rules.action_from_prediction(
    {"target": "match", "kind": "winner", "verdict": "П2"},
    sport="football")
check("командный победитель", team and team.get("side") == "p2", team)
check("цель match", team and team.get("targets") == ["match"], team)

# ---------------------------------------------------------------------
# 4. API: включение, обновление, выключение
# ---------------------------------------------------------------------
eng = api.engine()
eng.predictor.telegram.sent_predictions = json.loads(json.dumps(sent))
eng.predictor.constructor.save({"rules": [manual]}, "table_tennis")
eng.settings.update({"active_sport": "table_tennis",
                     "algorithm_mode": "builtin"})
enabled = json.loads(eng.auto_rules(json.dumps({"action": "enable"})))
check("API авто включено", enabled["enabled"] is True, enabled)
check("API режим конструктора", enabled["mode"] == "constructor", enabled)
check("API правила созданы", enabled["generated"] >= 1, enabled)
check("API есть точность", bool(enabled["rules"]), enabled["rules"])
check("API ручное правило сохранено",
      any(item.get("name") == "Ручное правило"
          for item in eng.predictor.constructor.snapshot("table_tennis")))

status = json.loads(eng.auto_rules(json.dumps({"action": "status"})))
check("API статус", status["ok"] is True and status["enabled"] is True, status)
check("API наблюдения", status["observations"] == 24, status)

analysis = json.loads(eng.get_analyzer(json.dumps({"sport": "table_tennis"})))
reviews = analysis.get("rule_reviews") or {}
check("анализ отдаёт проверку правил", reviews.get("ok") is True, reviews)
check("проверка видит активные правила",
      reviews.get("total") == len([
          item for item in eng.predictor.constructor.snapshot("table_tennis")
          if item.get("enabled")]), reviews)
check("анализ отдаёт режим авто-правил",
      analysis.get("auto_rules", {}).get("enabled") is True,
      analysis.get("auto_rules"))
check("в анализе есть название вида",
      bool(analysis.get("sport_name")), analysis.get("sport_name"))

configured = json.loads(eng.auto_rules(json.dumps({
    "action": "configure", "min_precision": 70, "min_samples": 8})))
check("API настройка точности", configured["min_precision"] == 70.0, configured)
check("API настройка наблюдений", configured["min_samples"] == 8, configured)

disabled = json.loads(eng.auto_rules(json.dumps({"action": "disable"})))
check("API авто выключено", disabled["enabled"] is False, disabled)
rules_after = eng.predictor.constructor.snapshot("table_tennis")
check("после выключения авто-правила off",
      all(not item.get("enabled") for item in rules_after if item.get("auto")),
      rules_after)
check("после выключения ручное правило on",
      any(item.get("name") == "Ручное правило" and item.get("enabled")
          for item in rules_after), rules_after)

check("версия движка 1.17.0", api.APP_VERSION == "1.17.0", api.APP_VERSION)

print("OK — пройдено проверок: %d" % len(PASSED))

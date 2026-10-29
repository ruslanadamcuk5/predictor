# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Проверка новых функций: прогноз в очереди + экран результатов с фильтрами."""
import json
import os
import shutil
import sys
import tempfile

BASE = os.path.join(ROOT, "app", "src", "main", "python")
HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "results_home")
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
sys.path.insert(0, BASE)

import predictor_core as core  # noqa: E402
import engine_api as api  # noqa: E402

checks = []


def check(name, ok, detail=""):
    checks.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def seed():
    data = {
        "id1": {
            "team1": "Иванов А.", "team2": "Петров С.", "date": "19.10",
            "league": "Pro League", "message_id": -1,
            "sent_at": "2026-10-19T14:30:00",
            "result_checked": True,
            "result": {"final_score": "11:7 9:11 11:5", "sets": 3},
            "predictions": [
                {"target": "set1", "kind": "winner", "label": "Партия 1 (П1/П2)",
                 "verdict": "П1", "confidence_val": 0.62, "agreement": 0.71,
                 "strong": 4, "models_info": "Модели: streak=T1(71%), window=T1(64%)"},
                {"target": "set1", "kind": "total", "label": "Партия 1 (ТБ18.5/ТМ18.5)",
                 "verdict": "ТБ 18.5", "confidence_val": 0.44, "agreement": 0.55,
                 "strong": 3, "threshold": 18.5,
                 "models_info": "Модели: markov1=TO(52%), base_rate=TO(48%)"},
            ],
            "set_results": [
                {"target": "set1", "kind": "winner", "success": True, "score": "11:7",
                 "total": 18, "label": "Партия 1 (П1/П2)", "verdict": "П1"},
                {"target": "set1", "kind": "total", "success": False, "score": "11:7",
                 "total": 18, "label": "Партия 1 (ТБ18.5/ТМ18.5)", "verdict": "ТБ 18.5"},
            ],
        },
        "id2": {
            "team1": "Сидоров К.", "team2": "Кузнецов Д.", "date": "18.10",
            "league": "TT Cup", "message_id": -2,
            "sent_at": "2026-10-18T09:15:00",
            "result_checked": False,
            "predictions": [
                {"target": "set2", "kind": "winner", "label": "Партия 2 (П1/П2)",
                 "verdict": "П2", "confidence_val": 0.51, "agreement": 0.6,
                 "strong": 3, "models_info": "Модели: window=T2(58%)"},
            ],
            "set_results": [],
        },
        "id3": {
            "team1": "Морозов И.", "team2": "Волков П.", "date": "17.10",
            "league": "Setka Cup", "message_id": -3,
            "sent_at": "2026-10-17T12:00:00",
            "result_checked": True,
            "predictions": [
                {"target": "set1", "kind": "winner", "label": "Партия 1 (П1/П2)",
                 "verdict": "П1", "confidence_val": 0.66, "agreement": 0.8,
                 "strong": 5, "models_info": "Модели: streak=T1(66%)"},
            ],
            "set_results": [
                {"target": "set1", "kind": "winner", "success": True, "score": "11:5",
                 "total": 16, "label": "Партия 1 (П1/П2)", "verdict": "П1"},
            ],
        },
    }
    with open(core.SENT_PREDICTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


seed()
eng = api.Engine()

# --- результаты: всё
res = json.loads(eng.get_results())
check("результаты: 3 игры", res["total"] == 3, res["total"])
check("результаты: сводка прогнозов", res["summary"]["preds"] == 4, res["summary"])
check("результаты: 2 зашло / 1 не зашло", res["summary"]["wins"] == 2 and res["summary"]["losses"] == 1,
      res["summary"])
check("результаты: сортировка по дате", res["items"][0]["id"] == "id1", res["items"][0]["sent_at"])
first = res["items"][0]
check("результат: обоснование сохранено", "streak=T1" in first["rows"][0]["reason"], first["rows"][0]["reason"])
check("результат: уверенность в %", first["rows"][0]["confidence"] == 62.0, first["rows"][0]["confidence"])
check("результат: счёт партии", first["rows"][0]["score"] == "11:7", first["rows"][0]["score"])
check("результат: итоговый счёт", first["final_score"] == "11:7 9:11 11:5", first["final_score"])
check("результат: тотал по партии", first["rows"][1]["total"] == 18, first["rows"][1]["total"])

# --- фильтр по дате
res = json.loads(eng.get_results(start="2026-10-19T00:00"))
check("фильтр с даты: 1 игра", res["total"] == 1, res["total"])
res = json.loads(eng.get_results(end="2026-10-18"))
check("фильтр по дату включительно: 2 игры", res["total"] == 2, res["total"])
res = json.loads(eng.get_results(start="2026-10-19T15:00", end="2026-10-19T23:59"))
check("фильтр по времени: пусто", res["total"] == 0, res["total"])
res = json.loads(eng.get_results(start="2026-10-18T09:00", end="2026-10-19T15:00"))
check("диапазон: 2 игры", res["total"] == 2, res["total"])

# --- фильтр по статусу и поиску
res = json.loads(eng.get_results(status="win"))
check("статус «зашли»: 1 игра без ошибок", res["total"] == 1 and res["items"][0]["id"] == "id3",
      res["total"])
res = json.loads(eng.get_results(status="loss"))
check("статус «не зашли»: 1 игра", res["total"] == 1 and res["items"][0]["id"] == "id1",
      res["total"])
res = json.loads(eng.get_results(status="pending"))
check("статус «ожидают»: 1 игра", res["total"] == 1 and res["items"][0]["id"] == "id2",
      res["total"])
res = json.loads(eng.get_results(search="сидоров"))
check("поиск по команде", res["total"] == 1 and res["items"][0]["id"] == "id2", res["total"])
res = json.loads(eng.get_results(search="pro league"))
check("поиск по лиге", res["total"] == 1, res["total"])
res = json.loads(eng.get_results(search="нет такой"))
check("поиск без совпадений", res["total"] == 0, res["total"])

# --- очередь: прогноз внутри матча
class FakePredictor:
    pass


eng.predictor.get_live_matches = lambda: [
    {"match_id": "m1", "team1": "Иванов А.", "team2": "Петров С.", "league": "Pro League",
     "date": "19.10", "current_score": "1:1", "is_started": True,
     "odds": {"match_p1": 1.7, "match_p2": 2.1}, "stat_link": ""},
    {"match_id": "m2", "team1": "Другой И.", "team2": "Игрок П.", "league": "TT Cup",
     "date": "19.10", "current_score": "0:0", "is_started": False,
     "odds": {"match_p1": 1.9, "match_p2": 1.9}, "stat_link": ""},
]
out = json.loads(eng.refresh_queue())
check("очередь: 2 матча", len(out["items"]) == 2, len(out["items"]))
match = out["items"][0]
check("очередь: сигнал отмечен", match["sent"] is True, match["sent"])
check("очередь: прогноз прикреплён", bool(match.get("prediction")), match.get("prediction"))
check("очередь: 2 прогноза в карточке", len(match["prediction"]["items"]) == 2,
      len(match["prediction"]["items"]))
check("очередь: результат прогноза виден", match["prediction"]["items"][0]["success"] is True,
      match["prediction"]["items"][0])
check("очередь: второй прогноз не зашёл", match["prediction"]["items"][1]["success"] is False,
      match["prediction"]["items"][1])
check("очередь: у матча без прогноза пусто", not out["items"][1].get("prediction"),
      out["items"][1].get("prediction"))
q2 = json.loads(eng.get_queue())
check("get_queue тоже отдаёт прогноз", bool(q2["items"][0].get("prediction")),
      q2["items"][0].get("prediction"))

# --- экспорт CSV результатов
exp = json.loads(eng.export_data("results"))
check("экспорт результатов: ok", exp["ok"] is True, exp.get("error"))
check("экспорт результатов: csv", exp["filename"].endswith(".csv"), exp["filename"])
lines = exp["content"].splitlines()
check("экспорт результатов: заголовок + 4 строки", len(lines) == 5, len(lines))
check("экспорт результатов: обоснование в строке", "streak=T1" in exp["content"], lines[1][:120])

# --- сериализация JSON-строк (как из Kotlin)
check("JSON-строки валидны", isinstance(eng.get_results(), str))

failed = [c for c in checks if not c[1]]
print("\n%d/%d проверок пройдено" % (len(checks) - len(failed), len(checks)))
if failed:
    for name, _, detail in failed:
        print("  FAILED:", name, detail)
    sys.exit(1)
print("ВСЁ ОК")

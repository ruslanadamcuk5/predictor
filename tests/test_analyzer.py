# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Тесты анализатора: снимок статистики, обратный разбор, поиск параметров
удачных и неудачных прогнозов, API и запись снимка в полном цикле."""

import io
import json
import os
import shutil
import sys

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "analyzer_home")
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

from bs4 import BeautifulSoup  # noqa: E402

import predictor_core as core  # noqa: E402
import constructor_engine as ce  # noqa: E402
import analyzer  # noqa: E402
import engine_api as api  # noqa: E402

PASSED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
    else:
        raise AssertionError("%s: %s" % (name, detail))


def close(a, b, tol=1e-6):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return a == b


# =====================================================================
# 1. Снимок и обратный разбор на реальной странице статистики
# =====================================================================
page = io.open(os.path.join(FIXTURES, "stats_page.html"),
               encoding="utf-8").read()


class FakeResponse(object):
    status_code = 200
    text = page


class FakeSession(object):
    def get(self, *args, **kwargs):
        return FakeResponse()


predictor = core.PredictorEnsemble.__new__(core.PredictorEnsemble)
predictor.session = FakeSession()
team1, team2 = "Иван Леднев", "Александр Клавденков"
stats = predictor.get_match_stats("/x", team1, team2)
stats["league"] = "Лига Про"

match = {
    "match_id": "m1", "team1": team1, "team2": team2, "league": "Лига Про",
    "date": "19.10 20:30", "start_time": "2026-10-19T20:30",
    "stat_link": "/x", "is_started": False, "current_score": "0:0",
    "odds": {"match_p1": 1.85, "match_p2": 1.95,
             "first_set_p1": 1.9, "first_set_p2": 1.9},
}
ctx = ce.Context(match, stats)

sample = analyzer.make_sample(match, stats)
check("снимок создан", isinstance(sample, dict) and sample.get("kind") == "context")
check("снимок JSON-совместим", bool(json.dumps(sample, ensure_ascii=False)))
check("снимок без datetime-объектов",
      "__dt__" in json.dumps(sample) or "T00:00:00" in json.dumps(sample))
check("снимок содержит h2h", len(sample["h2h"]) == len(ctx.h2h), len(sample["h2h"]))
check("снимок содержит форму",
      len(sample["recent"]["p1"]) == len(ctx.recent["p1"]))
check("снимок содержит тоталы страницы", sample["page_total"].get("line") == 75.5)

restored = analyzer.context_from_sample(sample)
check("контекст восстановлен", restored is not None)


def arg_variants(metric):
    base = dict(metric.get("args") or {})
    out = [base]
    if "side" in base:
        out = [dict(a, side="p1") for a in out] + [dict(a, side="p2") for a in out]
    if "window" in base:
        out = out + [dict(a, window=3) for a in out]
    if "set" in base:
        out = out + [dict(a, set=2) for a in out]
    return out


mismatch = []
for metric in ce.METRICS:
    for args in arg_variants(metric):
        left = ce.evaluate_metric(ctx, metric["id"], args)
        right = ce.evaluate_metric(restored, metric["id"], args)
        if not close(left, right):
            mismatch.append((metric["id"], args, left, right))
check("все метрики совпадают после снимка", not mismatch, mismatch[:3])

# метка и описание условия из восстановленного контекста
cond = {"metric": "h2h.count", "args": {}, "op": "gte", "value": 1}
matched_a, _ = ce.evaluate_condition(ctx, cond)
matched_b, _ = ce.evaluate_condition(restored, cond)
check("условие совпадает после снимка", matched_a == matched_b == True)


# =====================================================================
# 2. Синтетический сценарий: удачи при высоком тотале партии игрока 1
# =====================================================================
def set_with_total(total):
    first = (total + 1) // 2
    return [first, total - first]


def recent_item(total, day, won):
    sets = [set_with_total(total) for _ in range(3)]
    return {"date": "%02d.10.26" % day, "date_text": "%02d.10.26" % day,
            "opponent": "Соперник", "league": "Тест", "sets": sets,
            "match_score": [2, 1] if won else [1, 2]}


def h2h_item(total, day):
    return {"date": "%02d.09.26" % day, "date_obj": None,
            "player1": "Игрок А", "player2": "Игрок Б",
            "sets_parsed": [set_with_total(total) for _ in range(3)],
            "match_score": "3:0", "winner": "P1"}


def build_stats(p1_total, p2_total, h2h_total):
    return {
        "team1": "Игрок А", "team2": "Игрок Б",
        "h2h_matches": [h2h_item(h2h_total, day) for day in range(1, 11)],
        "recent": {
            "team1": [recent_item(p1_total, day, True) for day in range(1, 6)],
            "team2": [recent_item(p2_total, day, False) for day in range(1, 6)],
        },
        "page_total": {"line": 75.5, "last5_over": 3, "last5_under": 2,
                       "season_over": 128, "season_under": 129},
    }


CASE_MATCH = dict(match)
CASE_MATCH["team1"], CASE_MATCH["team2"] = "Игрок А", "Игрок Б"

WINS_P1 = [19, 20, 21, 22, 20, 21, 19, 22, 20, 21, 19, 21]
LOSSES_P1 = [13, 14, 15, 16, 14, 15, 13, 16, 14, 15, 13, 16]

sent = {}
index = 0
for group, totals in ((True, WINS_P1), (False, LOSSES_P1)):
    for value in totals:
        stats_i = build_stats(value, 18, 20)
        sample_i = analyzer.make_sample(CASE_MATCH, stats_i)
        check("снимок кейса JSON-совместим", bool(json.dumps(sample_i)))
        pred_id = "case%02d" % index
        sent[pred_id] = {
            "team1": "Игрок А", "team2": "Игрок Б",
            "date": "%02d.10.26 20:00" % index,
            "league": "Тест",
            "sent_at": "2026-10-%02dT12:00:00" % (1 + index % 28),
            "predictions": [{
                "target": "set1", "kind": "total",
                "label": "Партия 1 (ТБ18.5/ТМ18.5)", "verdict": "ТБ 18.5",
                "confidence_val": 0.6,
            }],
            "set_results": [{
                "target": "set1", "kind": "total", "success": group,
                "score": "11:10" if group else "8:7",
                "total": value, "label": "Партия 1 (ТБ18.5/ТМ18.5)",
                "verdict": "ТБ 18.5",
            }],
            "stats": sample_i,
            "result_checked": True,
        }
        index += 1

result = analyzer.analyze(sent)
check("наблюдений 24", result["observations"]["total"] == 24, result["observations"])
check("удач 12", result["observations"]["wins"] == 12, result["observations"])
check("неудач 12", result["observations"]["losses"] == 12, result["observations"])
check("со статистикой 24", result["observations"]["with_stats"] == 24)
check("данных достаточно", result["sufficient"] is True)

failures = result["failure"]
successes = result["success"]
check("найдены параметры неудач", len(failures) >= 5, len(failures))
check("найдены параметры удач", len(successes) >= 5, len(successes))

driver_fail = [row for row in failures
               if row["metric"] == "p.recent.avg_set_total"
               and row["args"].get("side") == "p1"]
check("неудачи: тотал партии игрока 1 найден", bool(driver_fail), failures[:3])
check("неудачи: условие «меньше или равно»",
      all(row["op"] == "lte" for row in driver_fail),
      [row["op"] for row in driver_fail])
check("неудачи: доля 100%", all(row["loss_share"] == 100.0 for row in driver_fail),
      [row["loss_share"] for row in driver_fail])
check("неудачи: в удачах 0%", all(row["win_share"] == 0.0 for row in driver_fail))
check("неудачи: перевес отрицательный",
      all(row["lift"] <= -10 for row in failures),
      [row["lift"] for row in failures])

driver_win = [row for row in successes
              if row["metric"] == "p.recent.avg_set_total"
              and row["args"].get("side") == "p1"]
check("удачи: тотал партии игрока 1 найден", bool(driver_win), successes[:3])
check("удачи: условие «больше или равно»",
      all(row["op"] == "gte" for row in driver_win),
      [row["op"] for row in driver_win])
check("удачи: доля 100%", all(row["win_share"] == 100.0 for row in driver_win),
      [row["win_share"] for row in driver_win])
check("удачи: перевес положительный",
      all(row["lift"] >= 10 for row in successes),
      [row["lift"] for row in successes])

check("уникальность условий в списке неудач",
      len({(r["metric"], json.dumps(r["args"], sort_keys=True)) for r in failures})
      == len(failures))
check("условие пригодно для конструктора",
      all(isinstance(r["condition"], dict) and r["condition"].get("metric")
          for r in failures + successes))
check("текст условия не пустой", all(r["text"] for r in failures + successes))
check("примеры приложены",
      all(isinstance(r["examples"], list) and r["examples"]
          for r in failures + successes),
      [r["examples"] for r in failures[:1]])

# проверка, что условие из выдачи реально воспроизводит числа
row = driver_fail[0]
flags = []
for data in sent.values():
    sample_ctx = analyzer.context_from_sample(data["stats"])
    matched, _ = ce.evaluate_condition(sample_ctx, row["condition"])
    flags.append(bool(matched))
hits_loss = sum(1 for f, d in zip(flags, sent.values())
                if f and not d["set_results"][0]["success"])
check("числа условия воспроизводимы", hits_loss == row["loss_hits"],
      (hits_loss, row["loss_hits"]))

check("комбинации неудач", len(result["combos"]["failure"]) >= 1,
      result["combos"]["failure"])
check("комбинации удач", len(result["combos"]["success"]) >= 1,
      result["combos"]["success"])
for combo in result["combos"]["failure"]:
    check("комбинация из двух условий", len(combo["conditions"]) == 2, combo)
    check("комбинация: перевес", combo["lift"] >= 20, combo)

means = result["means"]
check("средние посчитаны", bool(means))
check("средние: сильный признак во главе", means[0]["normalized"] >= 1.5, means[0])
driver_mean = [m for m in means
               if m["metric"] == "p.recent.avg_set_total"
               and m["args"].get("side") == "p1"]
check("средние: тотал партии игрока 1 в списке", bool(driver_mean), means[:3])
check("средние: зашло больше, чем не зашло",
      all(m["delta"] > 0 for m in driver_mean), driver_mean[0])
check("средние: доли игрока 2 не выделяются",
      all(not (m["args"].get("side") == "p2" and m["normalized"] >= 1.0)
          for m in means), [m for m in means if m["args"].get("side") == "p2"][:2])


# =====================================================================
# 3. Фильтры и границы
# =====================================================================
only_winner = analyzer.analyze(sent, kind="winner")
check("фильтр по виду: победитель — пусто",
      only_winner["observations"]["total"] == 0, only_winner["observations"])
check("фильтр по виду: подсказка", bool(only_winner.get("hint")))

only_set2 = analyzer.analyze(sent, target="set2")
check("фильтр по партии: пусто", only_set2["observations"]["total"] == 0)

only_total = analyzer.analyze(sent, kind="total")
check("фильтр по виду: тотал — 24", only_total["observations"]["total"] == 24)

small = {"case00": sent["case00"]}
check("мало данных: insufficient", analyzer.analyze(small)["sufficient"] is False)
check("мало данных: подсказка", bool(analyzer.analyze(small).get("hint")))

legacy = {"old1": {"team1": "А", "team2": "Б", "date": "01.10 12:00",
                   "sent_at": "2026-10-01T12:00:00", "stats": {},
                   "predictions": [{"target": "set1", "kind": "total",
                                    "verdict": "ТБ 18.5"}],
                   "set_results": [{"target": "set1", "kind": "total",
                                    "success": True, "total": 21}]}}
no_data = analyzer.analyze(legacy)
check("без снимка: нет наблюдений", no_data["observations"]["total"] == 0)
check("без снимка: подсказка про статистику",
      "статистик" in (no_data.get("hint") or ""), no_data.get("hint"))
check("без снимка: счётчик with_stats", no_data["observations"]["with_stats"] == 0)

check("порог перевеса настраивается",
      len(analyzer.analyze(sent, min_lift=60)["failure"]) <= len(failures))
check("max_rows ограничивает",
      len(analyzer.analyze(sent, max_rows=2)["failure"]) == 2)
check("pairs отключаются",
      analyzer.analyze(sent, with_pairs=False)["combos"] == {"failure": [], "success": []})
check("limit ограничивает наблюдения",
      analyzer.analyze(sent, limit=10)["observations"]["total"] == 10)


# =====================================================================
# 4. API
# =====================================================================
eng = api.engine()
with eng.predictor.telegram._lock:
    eng.predictor.telegram.sent_predictions = json.loads(json.dumps(sent))

api_result = json.loads(eng.get_analyzer())
check("API анализатор: ok", api_result["ok"] is True)
check("API анализатор: неудачи", bool(api_result["failure"]))
check("API анализатор: удачи", bool(api_result["success"]))
check("API анализатор: комбинации", bool(api_result["combos"]["failure"]))

filtered = json.loads(eng.get_analyzer(json.dumps({"kind": "winner"})))
check("API фильтр по виду", filtered["observations"]["total"] == 0)
filtered = json.loads(eng.get_analyzer(json.dumps(
    {"kind": "total", "min_group": 5, "min_lift": 30})))
check("API фильтр параметров", filtered["ok"] is True
      and filtered["options"]["min_group"] == 5
      and filtered["options"]["min_lift"] == 30.0, filtered["options"])

broken = json.loads(eng.get_analyzer("{это не json"))
check("API кривой JSON не ломает", broken["ok"] is True and "failure" in broken)

exported = json.loads(eng.export_data("analyzer"))
check("API экспорт анализатора", exported["ok"] is True
      and exported["filename"].startswith("analyzer_")
      and "failure" in exported["content"], exported.get("filename"))


# =====================================================================
# 5. Полный цикл записывает снимок статистики
# =====================================================================
live_match = dict(match)
eng.predictor.get_live_matches = lambda: [live_match]
eng.predictor.get_match_stats = lambda link, t1, t2: json.loads(
    json.dumps(stats, ensure_ascii=False, default=str))
engine_ctor = eng.predictor.constructor
engine_ctor.save({"rules": [{
    "name": "Всегда ТБ", "enabled": True, "priority": 100,
    "conditions": {"logic": "and", "conditions": [
        {"metric": "h2h.count", "args": {}, "op": "gte", "value": 0}]},
    "action": {"type": "total", "targets": [1], "side": "over",
               "threshold": 18.5, "confidence": 0.6}}]})
eng.settings.set_algorithm_mode("constructor")
eng.predictor.processed_matches = {}
eng.predictor.telegram.sent_predictions = {}
eng.settings.set_running(True)
summary = eng.predictor.run_cycle()
eng.settings.set_running(False)
check("цикл прошёл", summary.get("error") is None, summary)

stored = list(eng.predictor.telegram.sent_predictions.values())
check("прогноз записан", bool(stored), stored)
snapshot = stored[0].get("stats") if stored else None
check("снимок записан вместе с прогнозом",
      isinstance(snapshot, dict) and snapshot.get("kind") == "context", snapshot)
check("снимок в файле JSON-совместим",
      bool(json.dumps(eng.predictor.telegram.sent_predictions,
                      ensure_ascii=False)))
check("снимок содержит очные встречи",
      isinstance(snapshot, dict) and len(snapshot.get("h2h") or []) == len(ctx.h2h))
check("снимок содержит форму обоих игроков",
      isinstance(snapshot, dict)
      and len((snapshot.get("recent") or {}).get("p1") or []) == 5
      and len((snapshot.get("recent") or {}).get("p2") or []) == 5)

# файл перечитан другим экземпляром
reloaded = core.TelegramBot.__new__(core.TelegramBot)
reloaded.sent_predictions_file = eng.predictor.telegram.sent_predictions_file
loaded = core.TelegramBot.load_sent_predictions(reloaded)
check("снимок сохраняется на диск",
      bool(loaded) and list(loaded.values())[0].get("stats", {}).get("kind") == "context")

# анализатор на данных цикла: результата ещё нет — наблюдений нет, но снимок есть
live = analyzer.build_observations(eng.predictor.telegram.sent_predictions)
check("до результата наблюдений нет", len(live) == 0, len(live))
check("снимок цикла учтён в счётчике",
      analyzer.count_samples(eng.predictor.telegram.sent_predictions) == 1)

pred_key = list(eng.predictor.telegram.sent_predictions.keys())[0]
eng.predictor.telegram.update_set_result(pred_key, "set1", {
    "target": "set1", "kind": "total", "success": True, "score": "11:10",
    "total": 21, "label": "Партия 1 (ТБ18.5/ТМ18.5)", "verdict": "ТБ 18.5"})
live = analyzer.build_observations(eng.predictor.telegram.sent_predictions)
check("после результата наблюдение появилось", len(live) == 1, len(live))
check("наблюдение из цикла имеет контекст", live[0]["ctx"] is not None)
check("наблюдение из цикла помечено успешным", live[0]["success"] is True)
cycle_result = analyzer.analyze(eng.predictor.telegram.sent_predictions)
check("анализатор не падает на одном наблюдении",
      cycle_result["ok"] is True and cycle_result["observations"]["total"] == 1)
check("версия движка", api.APP_VERSION == "1.17.0", api.APP_VERSION)


print("OK — пройдено проверок: %d" % len(PASSED))

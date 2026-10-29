# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
import sys, io, json, os, tempfile, shutil
HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "ctor_home2")
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import predictor_core as core
import constructor_engine as ce
import engine_api as api

assert core.CONSTRUCTOR_RULES_FILE.startswith(HOME), core.CONSTRUCTOR_RULES_FILE

eng = api.engine()
# stop any loop (none started)

res = json.loads(eng.get_constructor())
assert res["ok"] and res["mode"] == "builtin", res["mode"]
assert len(res["catalog"]["metrics"]) > 50, len(res["catalog"]["metrics"])
assert res["presets"], "presets empty"
print("catalog metrics:", len(res["catalog"]["metrics"]), "presets:", len(res["presets"]))

# сохраняем пресеты
rules = [dict(p["rule"], id="r%d" % i, enabled=True, priority=100 - i, stop=False)
         for i, p in enumerate(res["presets"])]
saved = json.loads(eng.save_constructor(json.dumps({"mode": "constructor", "rules": rules})))
assert saved["ok"], saved.get("errors")
assert saved["mode"] == "constructor"
assert len(saved["rules"]) == len(rules)
print("saved rules:", len(saved["rules"]))
for r in saved["rules"]:
    print("  -", r["name"], "|", r["action_text"])
    print("    ", r["summary"][:160])

# неверная метрика -> ошибка
bad = json.loads(eng.save_constructor(json.dumps({"rules": [{"name": "x", "conditions": {"logic": "and", "conditions": [{"metric": "nope.metric", "op": "gt", "value": 1}]}, "action": {"type": "total"}}]})))
assert not bad["ok"] and bad["errors"], bad
print("bad error:", bad["errors"][0])
# после ошибки старые правила остались
again = json.loads(eng.get_constructor())
assert len(again["rules"]) == len(rules), len(again["rules"])
print("rules preserved after error:", len(again["rules"]))

# test_constructor с подменённым получением данных
stats = {
    "team1": "Игрок Один", "team2": "Игрок Два", "league": "Тест",
    "h2h_matches": [
        {"date": "01.10.26", "date_obj": None, "player1": "Игрок Один", "player2": "Игрок Два",
         "match_score": "3:1", "winner": "P1", "sets_parsed": [(11, 9), (9, 11), (11, 7), (11, 8)]},
        {"date": "15.09.26", "date_obj": None, "player1": "Игрок Один", "player2": "Игрок Два",
         "match_score": "3:0", "winner": "P1", "sets_parsed": [(11, 8), (11, 6), (11, 9)]},
        {"date": "01.09.26", "date_obj": None, "player1": "Игрок Один", "player2": "Игрок Два",
         "match_score": "3:2", "winner": "P1", "sets_parsed": [(11, 9), (8, 11), (11, 7), (9, 11), (11, 8)]},
        {"date": "15.08.26", "date_obj": None, "player1": "Игрок Один", "player2": "Игрок Два",
         "match_score": "3:1", "winner": "P1", "sets_parsed": [(11, 7), (9, 11), (11, 8), (11, 6)]},
        {"date": "01.08.26", "date_obj": None, "player1": "Игрок Один", "player2": "Игрок Два",
         "match_score": "1:3", "winner": "P2", "sets_parsed": [(9, 11), (11, 9), (7, 11), (8, 11)]},
        {"date": "15.07.26", "date_obj": None, "player1": "Игрок Один", "player2": "Игрок Два",
         "match_score": "2:3", "winner": "P2", "sets_parsed": [(11, 9), (9, 11), (11, 7), (9, 11), (8, 11)]},
    ],
    "recent": {
        "team1": [
            {"date": "19.10.26", "sets": [(11, 9), (11, 7), (11, 8)], "match_score": (3, 0)},
            {"date": "18.10.26", "sets": [(11, 6), (9, 11), (11, 9), (11, 7)], "match_score": (3, 1)},
            {"date": "17.10.26", "sets": [(11, 5), (11, 8), (11, 6)], "match_score": (3, 0)},
            {"date": "16.10.26", "sets": [(8, 11), (11, 9), (11, 7), (9, 11), (11, 8)], "match_score": (3, 2)},
            {"date": "15.10.26", "sets": [(11, 9), (11, 10), (11, 7)], "match_score": (3, 0)},
        ],
        "team2": [
            {"date": "19.10.26", "sets": [(9, 11), (11, 9), (7, 11), (9, 11)], "match_score": (1, 3)},
            {"date": "18.10.26", "sets": [(5, 11), (8, 11), (6, 11)], "match_score": (0, 3)},
            {"date": "17.10.26", "sets": [(11, 9), (9, 11), (11, 7), (8, 11), (9, 11)], "match_score": (2, 3)},
            {"date": "16.10.26", "sets": [(11, 7), (11, 9), (11, 8)], "match_score": (3, 0)},
            {"date": "15.10.26", "sets": [(9, 11), (11, 9), (7, 11), (11, 9), (8, 11)], "match_score": (2, 3)},
        ],
    },
    "page_total": {"line": 75.5, "last5_under": 3, "last5_over": 2},
}
match = {"match_id": "m1", "team1": "Игрок Один", "team2": "Игрок Два", "league": "Тест",
         "date": "2026-10-19 20:30", "start_time": "2026-10-19T20:30", "stat_link": "x",
         "is_started": False, "current_score": "0:0", "odds": {"match_p1": 1.7, "match_p2": 2.1}}
eng.predictor.get_live_matches = lambda: [match]
eng.predictor.get_match_stats = lambda link, t1, t2: json.loads(json.dumps(stats))
test = json.loads(eng.test_constructor("", 3))
assert test["ok"] and test["checked"] == 1, test
print("test fired:", [f["name"] for f in test["items"][0]["fired"]])
print("test preds:", [p["verdict"] for p in test["items"][0]["predictions"]])

# переключение режима
mode = json.loads(eng.set_algorithm_mode("constructor"))
assert mode["mode"] == "constructor"
assert eng.settings.get_algorithm_mode() == "constructor"
print("mode ok")

# run_cycle в режиме конструктора
eng.settings.set_running(True)
# очистим обработанные
eng.predictor.processed_matches = {}
summary = eng.predictor.run_cycle()
print("run_cycle:", summary)
sent = eng.predictor.telegram.sent_predictions
assert sent, "prediction not sent"
first = list(sent.values())[0]
print("sent predictions:", [(p["verdict"], p["label"]) for p in first["predictions"]])
assert any(p.get("source") == "constructor" for p in first["predictions"])
print("constructor run_cycle OK")
eng.settings.set_running(False)

# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Живая проверка: реальная линия -> статистика матча -> ансамбль."""
import json
import os
import shutil
import sys

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "pred_live")
if os.path.exists(HOME):
    shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME

APP = os.path.join(ROOT, "app", "src", "main", "python")
sys.path.insert(0, APP)

import predictor_core as core

print("=== линия ===")
settings = core.BotSettings()
pred = core.PredictorEnsemble(settings=settings)
matches = pred.get_live_matches()
print("матчей:", len(matches))
if not matches:
    print("НЕТ МАТЧЕЙ — проверка пропущена")
    sys.exit(0)

match = matches[0]
print("матч:", match["team1"], "vs", match["team2"], "| лига:", match["league"])
print("кэфы:", match["odds"].get("match_p1"), "/", match["odds"].get("match_p2"))
print("stat_link:", (match["stat_link"] or "")[:60])

print("=== статистика очных встреч ===")
stats = pred.get_match_stats(match["stat_link"], match["team1"], match["team2"])
h2h = stats.get("h2h_matches", [])
print("очных встреч:", len(h2h))
for row in h2h[:3]:
    print("   ", row["date"], "|", row["teams"], "|", row["score"],
          "| сеты:", row["sets_parsed"][:3], "| победитель:", row["winner"])

print("=== ансамбль по партиям ===")
predictions = pred._analyze_all(stats, match["odds"])
print("прогнозов:", len(predictions))
for p in predictions:
    print("   ", p["label"], "->", p["verdict"],
          "| уверенность %.0f%%" % (p["confidence_val"] * 100),
          "|", p["models_info"][:90])

print("=== проверка счёта ===")
checker = pred.result_checker
for raw in ("11:7, 9:11, 11:5", "8:11 11:9 11:6 11:4", "0:0"):
    sets = checker.parse_score(raw)
    print("  ", raw, "->", [(s["set_number"], s["p1"], s["p2"], s["completed"]) for s in sets])

print()
print("ЖИВАЯ ПРОВЕРКА ЗАВЕРШЕНА")

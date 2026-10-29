# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Полный цикл на реальной линии: анализ -> прогноз -> сохранение -> статистика."""
import json
import os
import shutil
import sys

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "pred_cycle")
if os.path.exists(HOME):
    shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME

APP = os.path.join(ROOT, "app", "src", "main", "python")
sys.path.insert(0, APP)

import predictor_core as core

settings = core.BotSettings()
settings.update({
    "running": True,
    "debug_verbose": True,
    "general_filters": {"min_strong": 1, "min_agreement": 0.0,
                        "min_confidence": 0.0, "min_active": 1,
                        "vote_weight_base": 0.30},
    "model_thresholds": {k: 0.0 for k in core.MODEL_NAMES},
    "odds_check_enabled": False,
    "min_h2h_matches": 1,
})

pred = core.PredictorEnsemble(settings=settings)

print("=== цикл ===")
summary = pred.run_cycle()
print("итог:", json.dumps(summary, ensure_ascii=False))

print("=== сохранённые прогнозы ===")
sent = pred.telegram.sent_predictions
print("прогнозов:", len(sent))
for pid, data in sent.items():
    print("  id:", pid, "| message_id:", data.get("message_id"),
          "|", data["team1"], "vs", data["team2"])
    for p in data.get("predictions", []):
        print("      ", p["label"], "->", p["verdict"])

stats = pred.telegram.stats_payload()
print("=== статистика ===")
print(json.dumps(stats, ensure_ascii=False, indent=2)[:600])

print("=== файлы ===")
for name in ("sent_predictions.json", "processed_matches.json", "predictor.log", "events.jsonl"):
    path = os.path.join(core.DATA_DIR, name)
    size = os.path.getsize(path) if os.path.exists(path) else -1
    print("  %-26s %s" % (name, ("%d B" % size) if size >= 0 else "НЕТ"))

print("=== CSV ===")
rows = pred.bets_logger.read_rows()
print("строк:", len(rows))
for row in rows[:3]:
    print("  ", row.get("teams"), "|", row.get("prediction"))

print()
print("ЦИКЛ ЗАВЕРШЁН")

# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Проверка расчёта результатов: прогноз -> завершённые партии -> статистика."""
import json
import os
import shutil
import sys

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "pred_result")
if os.path.exists(HOME):
    shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME

APP = os.path.join(ROOT, "app", "src", "main", "python")
sys.path.insert(0, APP)

import predictor_core as core

fails = []


def check(name, cond, detail=""):
    if cond:
        print("  OK   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        fails.append(name)


settings = core.BotSettings()
pred = core.PredictorEnsemble(settings=settings)
bot = pred.telegram

# --- создаём прогноз на 2 партии: победитель и тотал ---
predictions = [
    {"target": "set1", "label": "Партия 1 (П1/П2)", "kind": "winner",
     "verdict": "П1", "confidence_val": 0.4, "models_info": "test"},
    {"target": "set1", "label": "Партия 1 (ТБ18.5/ТМ18.5)", "kind": "total",
     "verdict": "ТМ 18.5", "confidence_val": 0.4, "models_info": "test"},
    {"target": "set2", "label": "Партия 2 (П1/П2)", "kind": "winner",
     "verdict": "П1", "confidence_val": 0.4, "models_info": "test"},
]
mid = bot.send_message("test")
pid = bot.mark_prediction_sent("A", "B", "2026-10-19 12:00", predictions, mid, "L", {})

# --- подменяем счёт: П1 выиграл 1-ю партию 11:7 (тотал 18 -> ТМ), 2-ю 9:11 ---
pred.get_live_match_score = lambda t1, t2: "11:7, 9:11"
pred.result_checker.get_live_match_score = pred.get_live_match_score

print("=== прогон проверки ===")
pred.result_checker.check_pending_predictions()

data = bot.sent_predictions[pid]
results = data.get("set_results") or []
print("результатов:", len(results))
for r in results:
    print("   ", r.get("target"), r.get("kind"), "->",
          "зашла" if r.get("success") else "не зашла",
          "| счёт:", r.get("score"), "| тотал:", r.get("total"))

check("сохранены оба вида ставок", len(results) == 3, str(len(results)))
check("есть победитель", any(r.get("kind") == "winner" for r in results))
check("есть тотал", any(r.get("kind") == "total" for r in results))

winner = next((r for r in results if r.get("kind") == "winner"), {})
total = next((r for r in results if r.get("kind") == "total"), {})
check("П1 зашла (11:7)", winner.get("success") is True, str(winner))
check("ТМ 18.5 зашла (11:7=18)", total.get("success") is True, str(total))

payload = bot.stats_payload()
print("=== статистика ===")
print("  всего:", payload["total"], "hit:", payload["hit_rate"])
check("2 победы", payload["total"]["wins"] == 2, str(payload["total"]))
check("1 поражение (П1 в 9:11)", payload["total"]["losses"] == 1, str(payload["total"]))
check("hit rate 66.7", payload["hit_rate"] == 66.7, str(payload["hit_rate"]))

# --- заменяем результат set2 на выигрышный ---
bot.update_set_result(pid, "set2", {
    "target": "set2", "kind": "winner", "success": True,
    "score": "11:9", "total": 20, "label": "Партия 2", "verdict": "П1",
})
payload = bot.stats_payload()
check("3 победы", payload["total"]["wins"] == 3, str(payload["total"]))
check("0 поражений", payload["total"]["losses"] == 0, str(payload["total"]))
check("hit rate 100", payload["hit_rate"] == 100.0, str(payload["hit_rate"]))

# --- стороны матчевых прогнозов: П1 / П2 / Ничья --------------------------
rc = pred.result_checker
parsed_football = core.sports.parse_score("football", "2:1")
check("матч: П1 зашла",
      rc.check_match_prediction_success(
          {"kind": "winner", "expected_side": "П1"}, parsed_football,
          "football").get("success") is True)
check("матч: П2 не зашла",
      rc.check_match_prediction_success(
          {"kind": "winner", "expected_side": "П2"}, parsed_football,
          "football").get("success") is False)
check("матч: Ничья не зашла",
      rc.check_match_prediction_success(
          {"kind": "winner", "expected_side": "Ничья"}, parsed_football,
          "football").get("success") is False)
check("матч: фора П2 +1.5 зашла",
      rc.check_match_prediction_success(
          {"kind": "handicap", "expected_side": "p2", "handicap": 1.5},
          parsed_football, "football").get("success") is True)
check("матч: тотал ТБ 2.5 зашла (3)",
      rc.check_match_prediction_success(
          {"kind": "total", "expected_side": "over", "threshold": 2.5},
          parsed_football, "football").get("success") is True)

# --- мнение ИИ проверяется, даже если обычных прогнозов нет ---------------
score_full = "11:5, 9:11, 11:7, 11:6, 8:11, 11:9"
pred_ai = core.PredictorEnsemble(settings=settings)
bot_ai = pred_ai.telegram
ai_preds = [{"target": "match", "label": "Матч (П1/П2)", "kind": "winner",
             "expected_side": "П1", "verdict": "П1", "confidence_val": 0.6,
             "models_info": "ИИ", "source": "ai"}]
mid = bot_ai.send_message("test")
pid = bot_ai.mark_prediction_sent("ИИ1", "ИИ2", "2026-10-19 12:00", [], mid,
                                  "L", {}, sport="table_tennis",
                                  ai_predictions=ai_preds)
pred_ai.result_checker.get_live_match_score = lambda t1, t2: score_full
pred_ai.result_checker.check_pending_predictions()
data = bot_ai.sent_predictions[pid]
ai_results = data.get("ai_results") or []
check("ИИ-прогноз проверен без обычных", len(ai_results) == 1, ai_results)
check("победа ИИ по матчу засчитана",
      bool(ai_results) and ai_results[0].get("success") is True, ai_results)
check("матч отмечен проверенным", data.get("result_checked") is True, data)

# --- матч ушёл из линии: проверка по последнему счёту ---------------------
from datetime import datetime as _now_dt

pred_cache = core.PredictorEnsemble(settings=settings)
bot_cache = pred_cache.telegram
cached_preds = [{"target": "set1", "label": "Партия 1 (П1/П2)",
                 "kind": "winner", "expected_side": "П1", "verdict": "П1",
                 "confidence_val": 0.6, "models_info": "test"},
                {"target": "set3", "label": "Партия 3 (ТБ/ТМ)",
                 "kind": "total", "expected_side": "under", "verdict": "ТМ 18.5",
                 "threshold": 18.5, "confidence_val": 0.6,
                 "models_info": "test"}]
mid = bot_cache.send_message("test")
pid = bot_cache.mark_prediction_sent("Кэш1", "Кэш2", "2026-10-19 12:00",
                                     cached_preds, mid, "L", {})
pred_cache.result_checker.get_live_match_score = lambda t1, t2: None
pred_cache._scores[pred_cache._score_key("table_tennis", "Кэш1", "Кэш2")] = {
    "sport": "table_tennis", "team1": "Кэш1", "team2": "Кэш2",
    "score": score_full, "finished": False, "complete": True,
    "at": _now_dt.now().isoformat(timespec="seconds"),
}
pred_cache.result_checker.check_pending_predictions()
data = bot_cache.sent_predictions[pid]
results = data.get("set_results") or []
check("матч ушёл из линии — прогнозы проверены", len(results) == 2, results)
check("пометка «по последнему счёту»",
      bool(results) and results[0].get("checked_from") == "cache", results)
check("партия 1 засчитана (11:5)",
      any(r.get("target") == "set1" and r.get("success") is True
          for r in results), results)
check("партия 3 ТМ 18.5 засчитана (11:7=18)",
      any(r.get("target") == "set3" and r.get("success") is True
          for r in results), results)

# --- кэш счётов: завершённый матч запоминается ----------------------------
pred_scores = core.PredictorEnsemble(settings=settings)
tt_id = core.sports.profile("table_tennis")["betcity_id"]
feed = {
    tt_id: {
        "chmps": {
            "1": {
                "evts": {
                    "e1": {
                        "name_ht": "Кэш-А", "name_at": "Кэш-Б",
                        "sc_inter": "11:5, 9:11, 11:7, 11:6, 8:11, 11:9",
                        "sc": "4:2", "date_ev_str": "19.10.2026 12:00",
                        "status_ev": 4, "time_name": "Матч завершён",
                        "time_type_status": -1,
                    }
                }
            }
        }
    }
}
pred_scores._remember_scores(feed, force_save=True)
known = pred_scores.known_score("table_tennis", "Кэш-А", "Кэш-Б")
check("кэш запомнил счёт",
      (known or {}).get("score") == "11:5, 9:11, 11:7, 11:6, 8:11, 11:9", known)
check("кэш отметил завершение", (known or {}).get("finished") is True, known)
check("счёт 4:2 — финальный",
      core.PredictorEnsemble.score_complete(
          "table_tennis", known.get("score") or "") is True, known)
check("счёт 2:1 — не финальный",
      core.PredictorEnsemble.score_complete(
          "table_tennis", "11:5, 9:11, 11:7") is False)
check("матч есть в текущих счётах",
      ("table_tennis", "Кэш-А", "Кэш-Б") in pred_scores.current_scores())
# Свежий фид, чтобы finished_scores не ходил в сеть.
pred_scores._last_feed = {"none": {}}
pred_scores._last_feed_ts = 9e18
finished = pred_scores.finished_scores()
check("матч попадает в finished_scores",
      ("table_tennis", "Кэш-А", "Кэш-Б") in finished, finished)
check("кэш сохраняется на диск", os.path.exists(pred_scores.scores_file))

print()
if fails:
    print("ПРОВАЛЕНО: %s" % ", ".join(fails))
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")

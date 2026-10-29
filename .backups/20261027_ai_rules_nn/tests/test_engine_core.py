# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Проверка ядра без сети: модели, хранилище прогнозов, статистика."""
import json
import os
import shutil
import sys

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "pred_unit")
if os.path.exists(HOME):
    shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME

sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import predictor_core as core

fails = []


def check(name, condition, detail=""):
    if condition:
        print("  OK   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        fails.append(name)


print("=== 1. Ансамбль моделей ===")
settings = core.BotSettings()
seq = ["T1", "T1", "T1", "T1", "T2", "T1", "T1", "T1", "T1", "T1", "T1"]
ens = core.ProbabilityEnsemble(seq, lambda v: {"T1": "T2", "T2": "T1"}.get(v, v))
agg = ens.aggregate()
check("aggregate вернул результат", agg is not None)
check("топ предсказание T1", agg and agg["prediction"] == "T1", str(agg and agg.get("prediction")))
check("strong >= 3", agg and agg["strong"] >= 3, str(agg and agg.get("strong")))
check("agreement в [0,1]", agg and 0 <= agg["agreement"] <= 1)

print("=== 2. Короткая последовательность ===")
short = core.ProbabilityEnsemble(["T1", "T2"], lambda v: v)
check("нет топа на короткой", short.aggregate() is None)

print("=== 3. Локальный режим Telegram ===")
bot = core.TelegramBot("", "", settings)
check("offline=True", bot.offline)
mid = bot.send_message("Тестовый сигнал")
check("локальный id отрицательный", isinstance(mid, int) and mid < 0, str(mid))

preds = [
    {"target": "set1", "label": "Партия 1", "kind": "winner",
     "verdict": "П1", "confidence_val": 0.4, "models_info": "x"},
    {"target": "set1", "label": "Партия 1", "kind": "total",
     "verdict": "ТБ 18.5", "confidence_val": 0.3, "models_info": "y"},
]
pid = bot.mark_prediction_sent("A", "B", "2026-10-19 12:00", preds, mid, "Лига", {})
check("прогноз сохранён", pid in bot.sent_predictions)

bot.update_set_result(pid, "set1", {"target": "set1", "success": True,
                                    "score": "11:7", "total": 18,
                                    "label": "Партия 1", "verdict": "П1"})
payload = bot.stats_payload()
check("один прогноз засчитан", payload["total"]["wins"] == 1, json.dumps(payload["total"]))
check("hit rate 100", payload["hit_rate"] == 100.0, str(payload["hit_rate"]))
check("by_target непустой", len(payload["by_target"]) >= 1)
check("edit_message в offline", bot.edit_message(mid, "text") is True)

print("=== 4. Настройки ===")
check("running по умолчанию False", settings.is_running() is False)
settings.update({"poll_interval_sec": 12, "engine": {"streak_min": 5}})
check("интервал сохранён", settings.get_poll_interval() == 12)
check("streak сохранён", settings.get_engine("streak_min") == 5)
settings.reset_to_defaults()
check("сброс вернул 20 сек", settings.get_poll_interval() == 20)

print("=== 5. CSV ===")
logger = core.BetsLogger()
logger.log_bet({"datetime": "2026-10-19T12:00:00", "teams": "A vs B",
                "league": "L", "prediction": "П1", "rule": "T"})
rows = logger.read_rows()
check("строка записана", len(rows) == 1, str(len(rows)))

print("=== 6. Разбор счёта ===")
check("парсинг счёта", len(bot and core.ResultChecker(bot, logger).parse_score("11:7, 9:11, 11:5")) == 3)

print()
if fails:
    print("ПРОВАЛЕНО: %d -> %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")

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

print("=== 7. Миграция онлайн-адреса ===")
legacy_path = os.path.join(HOME, "legacy_settings.json")
with open(legacy_path, "w", encoding="utf-8") as handle:
    json.dump({
        "online": {"base_url": "https://virusadk.alwaysdata.net/predictor",
                   "enabled": True},
        "updates": {"manifest_url":
                    "https://virusadk.alwaysdata.net/predictor/api/v1/update"},
        "poll_interval_sec": 33,
    }, handle)
legacy = core.BotSettings(legacy_path)
check("старый адрес заменён",
      legacy.data["online"]["base_url"] == "https://predictor.alwaysdata.net",
      legacy.data["online"]["base_url"])
check("старый манифест очищен",
      legacy.data["updates"]["manifest_url"] == "",
      legacy.data["updates"]["manifest_url"])
check("остальные настройки сохранены",
      legacy.data["poll_interval_sec"] == 33
      and legacy.data["online"]["enabled"] is True)
custom_path = os.path.join(HOME, "custom_settings.json")
with open(custom_path, "w", encoding="utf-8") as handle:
    json.dump({"online": {"base_url": "https://example.com/predictor"}}, handle)
custom = core.BotSettings(custom_path)
check("свой адрес не перезаписан",
      custom.data["online"]["base_url"] == "https://example.com/predictor",
      custom.data["online"]["base_url"])

print("=== 8. Согласованность версии и адресов ===")
import re

def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()

js_url = re.search(r"DEFAULT_ONLINE_URL = '([^']+)'", read("app/src/main/assets/www/app.js")).group(1)
core_url = core.BotSettings.DEFAULTS["online"]["base_url"]
client_url = re.search(r'DEFAULT_BASE_URL = "([^"]+)"',
                       read("app/src/main/python/online_client.py")).group(1)
live_url = re.search(r'DEFAULT_BASE = "([^"]+)"',
                     read("tools/check_live.py")).group(1)
check("адрес онлайн-режима совпадает во всех местах",
      len({js_url, core_url, client_url, live_url}) == 1,
      (js_url, core_url, client_url, live_url))
check("адрес не ведёт на запрещённый сайт",
      "virusadk.alwaysdata.net" not in js_url, js_url)

gradle = read("app/build.gradle.kts")
code = int(re.search(r"versionCode = (\d+)", gradle).group(1))
name = re.search(r'versionName = "([^"]+)"', gradle).group(1)
api = read("app/src/main/python/engine_api.py")
server = read("server/online_app.py")
check("versionCode — целое и растёт", code >= 17, code)
check("versionName совпадает с APP_VERSION",
      re.search(r'APP_VERSION = "([^"]+)"', api).group(1) == name + ".0", name)
check("SERVER_VERSION совпадает с APP_VERSION",
      re.search(r'SERVER_VERSION = "([^"]+)"', server).group(1) == name + ".0", name)

print()
if fails:
    print("ПРОВАЛЕНО: %d -> %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")

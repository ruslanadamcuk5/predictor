# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Проверка ядра без сети: модели, хранилище прогнозов, статистика."""
import io
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

print("=== 9. Точность 1.19: калибровка, пороги и лимит прогнозов ===")
filters = core.BotSettings.DEFAULTS["general_filters"]
check("порог сильных моделей поднят", filters["min_strong"] == 2, filters)
check("порог согласия поднят", filters["min_agreement"] == 0.55, filters)
check("порог уверенности поднят", filters["min_confidence"] == 0.56, filters)
check("минимум активных моделей", filters["min_active"] == 2, filters)
check("база веса голоса", filters["vote_weight_base"] == 0.34, filters)
check("минимум очных встреч", core.BotSettings.DEFAULTS["min_h2h_matches"] == 6,
      core.BotSettings.DEFAULTS["min_h2h_matches"])
check("свежая форма весит больше серии",
      core.MODEL_WEIGHTS["recency"] > core.MODEL_WEIGHTS["streak"],
      core.MODEL_WEIGHTS)
check("окно весит больше базовой частоты",
      core.MODEL_WEIGHTS["window"] > core.MODEL_WEIGHTS["base_rate"],
      core.MODEL_WEIGHTS)
check("сжатие вероятности задано", core.PROB_SHRINK == 8.0, core.PROB_SHRINK)

opposite = lambda v: {"T1": "T2", "T2": "T1"}.get(v, v)
short_agg = core.ProbabilityEnsemble(["T1"] * 5, opposite,
                                     vote_weight_base=0.34).aggregate()
long_agg = core.ProbabilityEnsemble(["T1"] * 40, opposite,
                                    vote_weight_base=0.34).aggregate()
check("короткая серия не выглядит сверхуверенной",
      short_agg is not None and 0.5 <= short_agg["confidence"] <= 0.75,
      short_agg and short_agg["confidence"])
check("длинная серия увереннее короткой",
      short_agg and long_agg and long_agg["confidence"] > short_agg["confidence"],
      (short_agg and short_agg["confidence"], long_agg and long_agg["confidence"]))
check("уверенность не превышает 97%",
      long_agg is not None and long_agg["confidence"] <= 0.97,
      long_agg and long_agg["confidence"])

legacy_filters = os.path.join(HOME, "legacy_filters.json")
with open(legacy_filters, "w", encoding="utf-8") as handle:
    json.dump({
        "general_filters": {"min_strong": 1, "min_agreement": 0.20,
                            "min_confidence": 0.10, "min_active": 1,
                            "vote_weight_base": 0.30},
        "min_h2h_matches": 5,
    }, handle)
migrated = core.BotSettings(legacy_filters)
check("мягкие пороги 1.18 мигрируют",
      migrated.data["general_filters"] == filters
      and migrated.data["min_h2h_matches"] == 6,
      migrated.data["general_filters"])
custom_filters = os.path.join(HOME, "custom_filters.json")
with open(custom_filters, "w", encoding="utf-8") as handle:
    json.dump({"general_filters": {"min_strong": 3, "min_agreement": 0.7,
                                   "min_confidence": 0.61, "min_active": 3,
                                   "vote_weight_base": 0.4},
               "min_h2h_matches": 8}, handle)
custom = core.BotSettings(custom_filters)
check("пользовательские пороги не перезаписаны",
      custom.data["general_filters"]["min_strong"] == 3
      and custom.data["general_filters"]["min_confidence"] == 0.61
      and custom.data["min_h2h_matches"] == 8,
      custom.data["general_filters"])

# Реальная страница статистики: очные + последние игры каждого игрока.
from bs4 import BeautifulSoup
engine = core.PredictorEnsemble()
html = io.open(os.path.join(FIXTURES, "stats_page.html"), encoding="utf-8").read()
soup = BeautifulSoup(html, "html.parser")
team1, team2 = "Иван Леднев", "Александр Клавденков"
stats = {"team1": team1, "team2": team2, "sport": "table_tennis",
         "h2h_matches": [], "recent": {"team1": [], "team2": []},
         "page_total": {}}
for candidate in soup.find_all("table"):
    title_cell = candidate.find("td", class_="title")
    title = title_cell.get_text(" ", strip=True) if title_cell else ""
    if "Очные встречи" in title:
        rows = candidate.find_all("tr")
        for index in range(2, len(rows)):
            cells = rows[index].find_all("td")
            if len(cells) < 3:
                continue
            date_text = cells[0].get_text(strip=True)
            teams_text = cells[1].get_text(strip=True)
            score_text = cells[2].get_text(strip=True)
            parts = re.split(r"\s+[-—]\s+", teams_text)
            if len(parts) < 2:
                parts = re.split(r"[-—]", teams_text, maxsplit=1)
            if len(parts) < 2:
                continue
            player1, player2 = parts[0].strip(), parts[1].strip()
            match_score = re.search(r"(\d+):(\d+)", score_text)
            if not match_score:
                continue
            ms1, ms2 = int(match_score.group(1)), int(match_score.group(2))
            all_sets = re.findall(r"(\d+):(\d+)", score_text)
            if len(all_sets) > 1:
                if int(all_sets[0][0]) == ms1 and int(all_sets[0][1]) == ms2:
                    set_scores = all_sets[1:]
                else:
                    set_scores = all_sets
            else:
                set_scores = []
            parsed = [(int(a), int(b)) for a, b in set_scores]
            first = parsed[0] if parsed else None
            stats["h2h_matches"].append({
                "date": date_text, "date_obj": engine._parse_match_date(date_text),
                "teams": teams_text, "score": score_text,
                "match_score": "%d:%d" % (ms1, ms2),
                "sets_parsed": parsed, "num_sets": len(parsed),
                "first_set": first,
                "first_set_total": (first[0] + first[1]) if first else None,
                "winner": "P1" if ms1 > ms2 else "P2",
                "player1": player1, "player2": player2,
            })
    elif title.lower().startswith("последние игры"):
        name = re.split(r"\s*:\s*", title[len("Последние игры"):].strip(" :"),
                        maxsplit=1)[0].strip()
        rec = engine._parse_recent_games(candidate, name)
        if engine._names_match(team1, name):
            stats["recent"]["team1"] = rec
        elif engine._names_match(team2, name):
            stats["recent"]["team2"] = rec
check("очные встречи разобраны", len(stats["h2h_matches"]) == 10,
      len(stats["h2h_matches"]))
check("свежая форма обоих игроков разобрана",
      len(stats["recent"]["team1"]) == 5 and len(stats["recent"]["team2"]) == 5,
      (len(stats["recent"]["team1"]), len(stats["recent"]["team2"])))
sequence_lengths = [len(engine._build_set_sequences(i, stats["h2h_matches"], stats)[0])
                    for i in range(1, 6)]
check("очные и форма объединены в последовательность",
      sequence_lengths == [20, 20, 20, 12, 5], sequence_lengths)
predictions = engine._analyze_all(stats, {})
check("на матч не больше трёх прогнозов", 1 <= len(predictions) <= 3,
      [(p["kind"], p["verdict"]) for p in predictions])
check("прогнозы не дублируют рынок",
      len({(p["target"], p["kind"]) for p in predictions}) == len(predictions),
      [(p["target"], p["kind"]) for p in predictions])
check("уверенность прогнозов выше порога",
      all(p["confidence_val"] >= 0.56 for p in predictions),
      [p["confidence_val"] for p in predictions])

print()
if fails:
    print("ПРОВАЛЕНО: %d -> %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")

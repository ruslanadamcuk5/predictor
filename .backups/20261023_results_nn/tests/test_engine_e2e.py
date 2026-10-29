# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Полный прогон API так, как его вызывает приложение (с вендоренными пакетами)."""
import json
import os
import shutil
import sys

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "pred_e2e")
if os.path.exists(HOME):
    shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
os.environ["PYTHONNOUSERSITE"] = "1"

APP = os.path.join(ROOT, "app", "src", "main", "python")
sys.path.insert(0, APP)

import engine_api as api

fails = []


def check(name, cond, detail=""):
    if cond:
        print("  OK   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        fails.append(name)


def js(raw):
    return json.loads(raw)


print("=== версия/состояние ===")
v = js(api.api_version())
check("версия", v["version"] == "1.12.0", str(v))
check("data_dir создан", os.path.isdir(v["data_dir"]), v["data_dir"])

st = js(api.api_state())
check("state содержит engine_running", "engine_running" in st)
check("state содержит stats", isinstance(st.get("stats"), dict))
check("state содержит version", st.get("version") == "1.12.0")

print("=== настройки ===")
s = js(api.api_settings())
check("settings/defaults", "settings" in s and "defaults" in s)
check("есть telegram", "telegram" in s["settings"])
check("есть engine", "engine" in s["settings"])
check("есть reports", "reports" in s["settings"])
check("есть notifications", "notifications" in s["settings"])

patch = {
    "poll_interval_sec": 30,
    "odds_check_enabled": False,
    "bet_size_percent": 3.5,
    "telegram": {"enabled": False, "token": "", "chat_id": ""},
    "model_thresholds": {"streak": 0.3, "window": 0.2, "markov1": 0.25,
                         "markov2": 0.25, "recency": 0.25, "base_rate": 0.25},
    "required_models": ["streak"],
    "allowed_bets": {"П1": True, "П2": True, "ТБ18.5": True, "ТМ18.5": False},
    "allowed_sets": {"set1": True, "set2": True, "set3": False, "set4": False, "set5": False},
    "general_filters": {"min_strong": 2, "min_agreement": 0.3, "min_confidence": 0.15,
                        "min_active": 2, "vote_weight_base": 0.35},
    "min_h2h_matches": 4,
    "engine": {"streak_min": 4, "window_size": 12, "window_min_hits": 7,
               "markov_min_sample": 6, "recency_decay": 0.9,
               "base_rate_min_n": 12, "prob_threshold": 18.5},
    "reports": {"hourly": False, "daily": True, "daily_hour": 22, "daily_minute": 30},
}
r = js(api.api_save_settings(json.dumps(patch)))
check("сохранение ok", r["ok"], str(r)[:200])
check("интервал", r["settings"]["poll_interval_sec"] == 30)
check("порог streak", abs(r["settings"]["model_thresholds"]["streak"] - 0.3) < 1e-9)
check("запрет ТМ", r["settings"]["allowed_bets"]["ТМ18.5"] is False)
check("партия 3 off", r["settings"]["allowed_sets"]["set3"] is False)
check("engine streak", r["settings"]["engine"]["streak_min"] == 4)
check("reports", r["settings"]["reports"]["daily_hour"] == 22)

# глобальные константы применились
import predictor_core as core
check("константа STREAK_MIN", core.STREAK_MIN == 4, str(core.STREAK_MIN))
check("константа WINDOW_SIZE", core.WINDOW_SIZE == 12, str(core.WINDOW_SIZE))

print("=== настройки сохраняются между перезапусками ===")
path = os.path.join(v["data_dir"], "bot_settings.json")
check("файл настроек", os.path.exists(path), path)
raw = json.load(open(path, encoding="utf-8"))
check("в файле интервал 30", raw.get("poll_interval_sec") == 30, str(raw.get("poll_interval_sec")))

print("=== сеть: линия и очередь ===")
tc = js(api.api_test_connection())
check("Betcity доступен", tc["betcity"] is True, str(tc))
check("матчи получены", tc["matches"] >= 0, str(tc["matches"]))

q = js(api.api_refresh_queue())
check("очередь ok", q.get("ok") is True, str(q)[:200])
check("элементы очереди", isinstance(q.get("items"), list))
if q.get("items"):
    m = q["items"][0]
    check("поля матча", all(k in m for k in ("team1", "team2", "score", "odds", "started")))
q2 = js(api.api_queue())
check("get_queue отдаёт кэш", q2["total"] == len(q.get("items", [])), str(q2["total"]))

print("=== ручной цикл ===")
once = js(api.api_run_once())
check("run_once ok", once.get("ok") is True, str(once)[:200])
check("есть summary", isinstance(once.get("summary"), dict))

print("=== логи ===")
lg = js(api.api_logs(0, 200, "", ""))
check("логи непустые", len(lg["items"]) > 0, str(len(lg["items"])))
check("id растёт", lg["last_id"] > 0, str(lg["last_id"]))
check("поля события", all(k in lg["items"][0] for k in ("id", "ts", "level", "message")))
lg2 = js(api.api_logs(lg["last_id"], 200, "", ""))
check("since работает", all(e["id"] > lg["last_id"] for e in lg2["items"]))
err = js(api.api_errors(50))
check("errors структура", "items" in err)

print("=== прогнозы и статистика ===")
pr = js(api.api_predictions(50))
check("predictions структура", "items" in pr and "total" in pr)
stt = js(api.api_stats())
check("stats total", "total" in stt and "by_target" in stt and "hit_rate" in stt)

print("=== экспорт ===")
for kind, ext in (("report", ".txt"), ("csv", ".csv"), ("predictions", ".json"),
                  ("stats", ".json"), ("logs", ".txt"), ("settings", ".json")):
    ex = js(api.api_export(kind))
    ok = ex.get("ok") and ex["filename"].endswith(ext) and isinstance(ex.get("content"), str)
    check("экспорт %s" % kind, ok, str(ex)[:120])

print("=== очистка ===")
c = js(api.api_clear_data("processed"))
check("clear processed", c.get("ok") is True and "processed" in c["cleared"], str(c))

print("=== сброс настроек ===")
rs = js(api.api_reset_settings())
check("reset ok", rs.get("ok") is True)
check("интервал вернулся 20", rs["settings"]["poll_interval_sec"] == 20, str(rs["settings"]["poll_interval_sec"]))
check("running False", rs["settings"]["running"] is False)

print("=== жизненный цикл движка ===")
st1 = js(api.api_start())
check("start ok", st1.get("ok") is True)
check("движок запущен", js(api.api_state())["engine_running"] is True)
st2 = js(api.api_stop())
check("stop ok", st2.get("ok") is True)
check("движок остановлен", js(api.api_state())["engine_running"] is False)

print()
if fails:
    print("ПРОВАЛЕНО: %d -> %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ (%d)" % 0)

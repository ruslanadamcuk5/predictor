# -*- coding: utf-8 -*-
"""Проверка одновременного анализа всех видов спорта.

Движок без явного вида спорта должен:
- одним запросом получить общий live-фид Betcity;
- собрать матчи всех шести видов;
- показать в сводке количество видов и матчей по каждому виду;
- отдавать в очередь матчи всех видов с правильным sport.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Уникальное хранилище на каждый прогон: тесты не зависят от предыдущих запусков.
HOME = tempfile.mkdtemp(prefix="predictor_all_sports_")
os.environ["HOME"] = HOME
os.makedirs(HOME, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import engine_api as api
import predictor_core as core
import sports

checks = [0, 0]


def check(name, condition, detail=""):
    checks[1] += 1
    if condition:
        checks[0] += 1
        print("PASS %s" % name)
    else:
        print("FAIL %s :: %s" % (name, detail))
        raise SystemExit(1)


def raw_event(team1, team2):
    return {
        "name_ht": team1,
        "name_at": team2,
        "date_ev_str": "22.10.2026 18:00",
        "sc": "0:0",
        "time_name": "",
        "status_ev": 1,
        "time_type_status": 0,
        "stat_link": "/stat/%s/%s" % (team1, team2),
        "main": {
            "Wm": {
                "data": {
                    "0": {
                        "blocks": {
                            "P1": {"kf": "1.90"},
                            "P2": {"kf": "1.90"},
                        }
                    }
                }
            }
        },
    }


def feed_for(sport_ids):
    feed = {}
    for index, sport in enumerate(sport_ids, 1):
        profile = sports.profile(sport)
        feed[profile["betcity_id"]] = {
            "chmps": {
                str(index): {
                    "name_ch": "Лига %s" % profile["short"],
                    "evts": {
                        "1": raw_event("%s A" % profile["short"],
                                       "%s B" % profile["short"]),
                    },
                }
            }
        }
    return feed


# --- 1. Один общий фид -> матчи всех видов --------------------------------
selected = ("table_tennis", "football", "hockey", "basketball",
            "volleyball", "tennis")
predictor = core.PredictorEnsemble.__new__(core.PredictorEnsemble)
predictor._fetch_feed = lambda: feed_for(selected)
matches = predictor.get_live_matches()
check("без аргумента — все виды", len(matches) == len(selected),
      [m.get("sport") for m in matches])
check("виды не потеряны", set(m["sport"] for m in matches) == set(selected),
      [m.get("sport") for m in matches])
check("у каждого матча есть вид", all(m.get("sport") for m in matches))

# --- 2. Явный вид остаётся точечным фильтром ------------------------------
football = predictor.get_live_matches("football")
check("явный вид — только он", len(football) == 1 and
      football[0]["sport"] == "football", football)

# --- 3. Сводка цикла считает все виды ------------------------------------
eng = api.engine()
eng.settings.update({"active_sport": "table_tennis", "running": True,
                     "algorithm_mode": "builtin"})
two_matches = [matches[0], matches[1]]
eng.predictor.get_live_matches = lambda: two_matches
eng.predictor.get_match_stats = lambda *args, **kwargs: {
    "recent": {"team1": [], "team2": []},
    "h2h_matches": [],
    "page_total": {},
    "page_totals": [],
}
summary = eng.predictor.run_cycle()
check("цикл видит оба матча", summary.get("matches") == 2, summary)
check("цикл видит два вида", summary.get("sports") == 2, summary)
check("разбивка по видам", summary.get("by_sport") == {
    "table_tennis": 1, "football": 1}, summary.get("by_sport"))

# --- 3.1. Лимит на вид: лишние матчи ждут следующего цикла -----------------
eng.settings.update({"max_matches_per_sport": 1})


def fresh(base, match_id, team1, team2):
    item = dict(base)
    item["match_id"] = match_id
    item["team1"] = team1
    item["team2"] = team2
    return item


lim_tt1 = fresh(matches[0], "lim-tt-1", "Лимит ТТ 1", "Лимит ТТ 2")
lim_tt2 = fresh(matches[0], "lim-tt-2", "Лимит ТТ 3", "Лимит ТТ 4")
lim_fb1 = fresh(matches[1], "lim-fb-1", "Лимит Ф 1", "Лимит Ф 2")
eng.predictor.get_live_matches = lambda: [lim_tt1, lim_tt2, lim_fb1]
summary = eng.predictor.run_cycle()
check("лимит отложил лишний матч", summary.get("deferred") == 1, summary)
check("первый матч вида обработан",
      eng.predictor.is_processed("lim-tt-1"))
check("отложенный матч не обработан",
      not eng.predictor.is_processed("lim-tt-2"))
check("второй вид не задет лимитом",
      eng.predictor.is_processed("lim-fb-1"))
eng.settings.update({"max_matches_per_sport": 10})

# --- 4. Очередь отдаёт все виды с правильным sport ------------------------
eng.predictor.get_live_matches = lambda: two_matches
queue = json.loads(eng.refresh_queue())
check("очередь ok", queue.get("ok") is True, queue)
items = queue.get("items") or []
check("очередь содержит оба вида",
      set(item.get("sport") for item in items) ==
      {"table_tennis", "football"}, items)
check("в очереди верные подписи",
      all(item.get("sport_name") for item in items), items)

print("\nALL CHECKS PASSED: %d/%d" % (checks[0], checks[1]))

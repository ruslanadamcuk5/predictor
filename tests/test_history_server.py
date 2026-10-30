# -*- coding: utf-8 -*-
"""Тесты веб-кабинета: приём истории, устройства, рекомендации и события.

Проверяется серверная часть: приложение присылает снимок, сервер хранит
его в SQLite, отдаёт список устройств с индикаторами качества и показывает
жизненный цикл рекомендаций (открыта → применена → эффект).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))
HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "history_home")
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
DATA = os.path.join(tempfile.gettempdir(), "predictor-tests", "history_data")
shutil.rmtree(DATA, ignore_errors=True)
os.environ["PREDICTOR_DATA_DIR"] = DATA
os.environ["PREDICTOR_TOKEN"] = "test-token"

import analyzer  # noqa: E402
import online_app  # noqa: E402

PASSED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  OK   " + name)
    else:
        raise AssertionError("%s: %s" % (name, detail))


def request(method, path, payload=None, token="test-token", raw=False):
    body = b""
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    route, _, query = path.partition("?")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": route,
        "QUERY_STRING": query,
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "https",
        "wsgi.input": io.BytesIO(body),
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/json",
    }
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    out = b"".join(online_app.application(environ, start_response))
    try:
        data = json.loads(out.decode("utf-8"))
    except Exception:
        data = {"raw": out.decode("utf-8", "replace")}
    return captured, data


# --------------------------------------------------------------------------
# история: 24 прогноза с результатами, чтобы появилась рекомендация
# --------------------------------------------------------------------------

def set_with_total(total):
    first = (total + 1) // 2
    return [first, total - first]


def recent_item(total, day, won):
    return {
        "date": "%02d.10.26" % day, "date_text": "%02d.10.26" % day,
        "opponent": "Соперник", "league": "Тест",
        "sets": [set_with_total(total) for _ in range(3)],
        "match_score": [2, 1] if won else [1, 2],
    }


def h2h_item(total, day):
    return {
        "date": "%02d.09.26" % day, "date_obj": None,
        "player1": "Игрок А", "player2": "Игрок Б",
        "sets_parsed": [set_with_total(total) for _ in range(3)],
        "match_score": "3:0", "winner": "P1",
    }


def build_stats(p1, p2, h2h):
    return {
        "team1": "Игрок А", "team2": "Игрок Б",
        "h2h_matches": [h2h_item(h2h, day) for day in range(1, 11)],
        "recent": {
            "team1": [recent_item(p1, day, True) for day in range(1, 6)],
            "team2": [recent_item(p2, day, False) for day in range(1, 6)],
        },
        "page_total": {"line": 75.5, "last5_over": 3, "last5_under": 2,
                       "season_over": 128, "season_under": 129},
    }


WINS = [20, 21, 22, 23, 20, 21, 22, 23, 20, 21, 22, 23]
LOSSES = [12, 13, 14, 15, 12, 13, 14, 15, 12, 13, 14, 15]


def build_history(prefix="h"):
    history = {}
    index = 0
    for success, totals in ((True, WINS), (False, LOSSES)):
        for total in totals:
            match = {
                "match_id": "%s%02d" % (prefix, index),
                "team1": "Игрок А", "team2": "Игрок Б",
                "sport": "table_tennis", "league": "Тест",
                "date": "19.10 20:30",
                "start_time": "2026-10-19T20:30", "stat_link": "/x",
                "is_started": False, "current_score": "0:0", "odds": {},
            }
            prediction = {
                "target": "set1", "kind": "total", "label": "Тотал",
                "verdict": "ТБ 18.5", "expected_side": "over",
                "threshold": 18.5, "confidence_val": 0.6,
                "rule_id": "rule-tt", "rule_name": "Тотал партии",
            }
            history["%s%02d" % (prefix, index)] = {
                "team1": "Игрок А", "team2": "Игрок Б",
                "date": "%02d.10.26" % (index + 1), "league": "Тест",
                "sport": "table_tennis",
                "sent_at": "2026-10-%02dT12:00:00" % (1 + index % 28),
                "predictions": [prediction],
                "set_results": [{
                    "target": "set1", "kind": "total", "success": success,
                    "score": "11:10" if success else "8:7", "total": total,
                    "label": prediction["label"],
                    "verdict": prediction["verdict"],
                }],
                "stats": analyzer.make_sample(match, build_stats(total, 18, 20)),
                "result_checked": True,
            }
            index += 1
    return history


RULE = {
    "id": "rule-tt", "name": "Тотал партии", "enabled": True, "priority": 100,
    "conditions": {"logic": "and", "conditions": []},
    "action": {"type": "total", "targets": [1], "side": "over",
               "threshold": 18.5, "confidence": 0.6},
}

SNAPSHOT = {
    "device": {
        "id": "dev_phone_1", "name": "Телефон А", "model": "Pixel 7",
        "platform": "Android 15", "app_version": "1.17.0",
    },
    "settings": {
        "active_sport": "table_tennis",
        "auto_rules": {"enabled": True, "min_samples": 6,
                       "min_precision": 60, "max_rules": 4},
        "online": {"token": "SECRET-TOKEN", "base_url": "https://x"},
        "telegram": {"token": "TG-SECRET", "chat_id": "1"},
    },
    "rules": {"table_tennis": [RULE]},
    "predictions": build_history(),
    "advisor_state": {},
    "meta": {"model": "Pixel 7", "platform": "Android 15"},
}

# --------------------------------------------------------------------------
# 1. Приём снимка
# --------------------------------------------------------------------------
status, data = request("POST", "/api/v1/sync", SNAPSHOT)
check("sync: 200", status["status"] == 200, (status, data))
check("sync: ok", data.get("ok") is True, data)
check("sync: правило создано", data["synced"]["rules"]["created"] == 1, data)
check("sync: прогнозы сохранены", data["synced"]["predictions"] == 24, data)
check("sync: устройство в ответе", data["device"]["id"] == "dev_phone_1", data)
token_leak = "SECRET-TOKEN" in json.dumps(data, ensure_ascii=False)
check("sync: токены не попали в ответ", not token_leak, data)

status, data = request("POST", "/api/v1/sync", SNAPSHOT)
check("повторный sync не создаёт правило заново",
      data["synced"]["rules"]["created"] == 0, data)
check("повторный sync не дублирует прогнозы",
      data["synced"]["predictions"] == 24, data)

# --------------------------------------------------------------------------
# 2. Список устройств и качество
# --------------------------------------------------------------------------
status, data = request("GET", "/api/v1/history/devices")
check("devices: 200", status["status"] == 200, status)
check("devices: одно устройство", len(data.get("devices", [])) == 1, data)
device = data["devices"][0]
check("devices: имя устройства", device["name"] == "Телефон А", device)
check("devices: качество посчитано", isinstance(device["quality"].get("score"), int),
      device["quality"])
check("devices: точность 50%", device["stats"]["hit_rate"] == 50.0,
      device["stats"])
check("devices: есть спарклайн", isinstance(device["stats"].get("spark"), list),
      device["stats"].get("spark"))
check("devices: сводка по всем", data["total"]["devices"] == 1, data["total"])
check("devices: токен не утёк",
      "SECRET-TOKEN" not in json.dumps(data, ensure_ascii=False), data)
check("devices: настройки очищены от секретов",
      "token" not in json.dumps(device.get("settings") or {}).lower(), device)

status, data = request("GET", "/api/v1/history/devices/dev_phone_1/overview")
check("overview: 200", status["status"] == 200, status)
check("overview: спорт в разрезе", data["sports"][0]["sport"] == "table_tennis",
      data.get("sports"))
check("overview: дневной ряд", len(data["device"]["stats"]["daily"]) == 30,
      len(data["device"]["stats"].get("daily") or []))
check("overview: событие создания", data["events"][0]["kind"] == "created",
      data.get("events"))

# --------------------------------------------------------------------------
# 3. Рекомендации и их применение
# --------------------------------------------------------------------------
status, data = request("GET", "/api/v1/history/devices/dev_phone_1/recommendations")
check("recommendations: 200", status["status"] == 200, status)
recs = data.get("items") or []
check("recommendations: найдена хотя бы одна", len(recs) >= 1, data)
rec = recs[0]
check("recommendation: тип — добавить условие", rec["type"] == "add_condition",
      rec["type"])
check("recommendation: привязана к правилу", rec["rule_id"] == "rule-tt", rec)
check("recommendation: есть причина и цифры",
      bool(rec.get("reason")) and rec.get("precision_before") is not None
      and rec.get("precision_after") is not None, rec)
check("recommendation: статус открыта", rec["status"] == "open", rec)

# Применяем рекомендацию на «устройстве»: правило получает условие,
# состояние рекомендаций помечает её применённой.
applied_rule = json.loads(json.dumps(RULE))
applied_rule["conditions"] = {
    "logic": "and", "conditions": [rec["rec"]["condition"]]}
second = json.loads(json.dumps(SNAPSHOT))
second["rules"] = {"table_tennis": [applied_rule]}
second["advisor_state"] = {
    "applied": {rec["rec_id"]: {"at": "2026-10-30T10:00:00",
                                "sport": "table_tennis",
                                "rule_id": "rule-tt"}},
}
status, data = request("POST", "/api/v1/sync", second)
check("sync после применения: правило обновлено",
      data["synced"]["rules"]["updated"] == 1, data)

status, data = request("GET", "/api/v1/history/devices/dev_phone_1/recommendations")
applied = [item for item in data["items"] if item["rec_id"] == rec["rec_id"]]
check("recommendation: статус применена", applied
      and applied[0]["status"] == "applied", applied)
check("recommendation: эффект до/после посчитан",
      applied and isinstance(applied[0].get("outcome"), dict),
      applied[0].get("outcome") if applied else None)
check("recommendation: эффект содержит вердикт",
      applied and (applied[0]["outcome"] or {}).get("verdict"),
      applied[0].get("outcome") if applied else None)

status, data = request("GET", "/api/v1/history/devices/dev_phone_1/events"
                              "?kind=updated")
check("events: изменение правила записано", data["total"] >= 1, data)
updated = data["items"][0]
check("events: изменение связано с рекомендацией",
      updated.get("rec_id") == rec["rec_id"], updated)
check("events: показано добавленное условие",
      any(change.get("field") == "condition_added"
          for change in updated.get("changes") or []), updated.get("changes"))
check("events: у изменения есть эффект",
      isinstance(updated.get("outcome"), dict), updated.get("outcome"))

status, data = request("GET", "/api/v1/history/devices/dev_phone_1/events"
                              "?rule_id=rule-tt")
check("events: фильтр по правилу", data["total"] >= 1, data)
check("events: чужое правило не попадает",
      all(item["rule_id"] == "rule-tt" for item in data["items"]), data)

# --------------------------------------------------------------------------
# 4. Второе устройство: правила и статистика не смешиваются
# --------------------------------------------------------------------------
other = json.loads(json.dumps(SNAPSHOT))
other["device"] = {"id": "dev_phone_2", "name": "Планшет Б",
                   "model": "Galaxy Tab", "platform": "Android 14",
                   "app_version": "1.17.0"}
other["rules"] = {"table_tennis": [{
    "id": "rule-2", "name": "Другое правило", "enabled": True,
    "conditions": {"logic": "and", "conditions": []},
    "action": {"type": "total", "targets": [1], "side": "over",
               "threshold": 20.5, "confidence": 0.5}}]}
other["predictions"] = build_history("o")
status, data = request("POST", "/api/v1/sync", other)
check("второе устройство принято", data.get("ok") is True, data)

status, data = request("GET", "/api/v1/history/devices")
check("devices: теперь два", len(data["devices"]) == 2, data)
check("devices: сводка суммирует прогнозы",
      data["total"]["predictions"] == 48, data["total"])

status, data = request("GET", "/api/v1/history/devices/dev_phone_2/rules")
check("правила второго устройства отдельно",
      [item["rule_id"] for item in data["items"]] == ["rule-2"], data)
check("правила первого устройства не изменились",
      request("GET", "/api/v1/history/devices/dev_phone_1/rules")[1]["items"][0]
      ["rule_id"] == "rule-tt")

status, data = request("GET", "/api/v1/history/devices/dev_phone_2/predictions")
check("прогнозы второго устройства отдельно", data["total"] == 24, data)
check("прогнозы: победы/поражения посчитаны",
      sum(1 for item in data["items"]
          for row in item["rows"] if row["success"] == 1) == 12, data)

# --------------------------------------------------------------------------
# 5. Переименование, авторизация и веб-интерфейс
# --------------------------------------------------------------------------
status, data = request("POST", "/api/v1/history/devices/dev_phone_1/rename",
                       {"name": "Кухонный телефон"})
check("rename: 200", status["status"] == 200, (status, data))
check("rename: имя сохранено", data["device"]["name"] == "Кухонный телефон", data)

status, data = request("GET", "/api/v1/history/devices", token="")
check("история без токена: 401", status["status"] == 401, status)

status, data = request("POST", "/api/v1/sync", SNAPSHOT, token="wrong")
check("sync с чужим токеном: 401", status["status"] == 401, status)

status, data = request("GET", "/")
check("кабинет: 200", status["status"] == 200, status)
html = data.get("raw", "")
check("кабинет: заголовок и поиск устройств",
      "Кабинет истории" in html and "Поиск по названию" in html, html[:200])
check("кабинет: вкладки устройства",
      "Рекомендации" in html and "История изменений" in html, html[:200])
check("кабинет: обращается к API истории",
      "/api/v1" in html and "/history/devices" in html, html[:300])
check("кабинет: ссылка на проверку связи", "/api/v1/ping" in html, html[:400])

status, data = request("GET", "/service")
check("страница состояния сохранена", status["status"] == 200
      and "Онлайн-анализ" in data.get("raw", ""), status)

status, data = request("GET", "/api/v1/history/health")
check("health: база создана", data.get("ok") is True
      and data.get("devices") == 2, data)

print("\nPASSED:", len(PASSED))

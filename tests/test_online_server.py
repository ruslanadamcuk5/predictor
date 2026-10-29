# -*- coding: utf-8 -*-
"""Тесты онлайн-сервиса: ping, авторизация, gzip и расчёт анализа."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "server_home")
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
os.environ["PREDICTOR_TOKEN"] = "test-token"
RELEASES = os.path.join(tempfile.gettempdir(), "predictor-tests",
                        "server_releases")
shutil.rmtree(RELEASES, ignore_errors=True)
os.makedirs(RELEASES, exist_ok=True)
os.environ["PREDICTOR_RELEASES_DIR"] = RELEASES

import online_app  # noqa: E402

PASSED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  OK   " + name)
    else:
        raise AssertionError("%s: %s" % (name, detail))


def request(method, path, payload=None, token="", gzipped=False):
    body = b""
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if gzipped:
            body = gzip.compress(body)
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "https",
        "wsgi.input": io.BytesIO(body),
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/json",
    }
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    if gzipped:
        environ["HTTP_CONTENT_ENCODING"] = "gzip"
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


def raw_request(method, path, headers=None):
    """Запрос без разбора JSON: нужен для APK и HEAD/Range."""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "https",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
    }
    environ.update(headers or {})
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(response_headers)

    body = b"".join(online_app.application(environ, start_response))
    return captured, body


status, data = request("GET", "/api/v1/ping")
check("ping без токена: понятная ошибка",
      data.get("ok") is False and "токен" in data.get("error", ""), data)

status, data = request("GET", "/api/v1/ping", token="test-token")
check("ping с токеном: 200", status["status"] == 200, status)
check("ping: ok и версия", data.get("ok") is True
      and data.get("version") == online_app.SERVER_VERSION, data)
check("ping: авторизация включена", data.get("auth_required") is True, data)

status, data = request("POST", "/api/v1/analyze", {
    "sports": ["table_tennis"],
    "predictions": {},
    "rules": {},
}, token="test-token", gzipped=True)
check("analyze gzip: 200", status["status"] == 200, (status, data))
check("analyze: ok", data.get("ok") is True, data)
check("analyze: выбранный вид", data.get("sports_selected") == ["table_tennis"],
      data.get("sports_selected"))
check("analyze: наблюдения", isinstance(data.get("observations"), dict), data)
check("analyze: рекомендации", isinstance(data.get("recommendations"), dict), data)
check("analyze: состояние рекомендаций",
      isinstance(data.get("advisor_state"), dict), data)
check("analyze: версия сервера",
      data.get("server_version") == online_app.SERVER_VERSION, data)

status, data = request("POST", "/api/v1/analyze", {
    "sports": ["table_tennis"], "predictions": {},
}, token="wrong")
check("analyze с чужим токеном: 401", status["status"] == 401, status)

status, data = request("GET", "/")
check("главная страница: 200", status["status"] == 200, status)
check("главная страница: русский текст", "Онлайн-анализ" in data.get("raw", ""),
      data)

status, data = request("GET", "/api/v1/analyze", token="test-token")
check("неверный метод: 405", status["status"] == 405, status)

status, data = request("GET", "/no-such-page")
check("неизвестный адрес: 404", status["status"] == 404, status)

# =====================================================================
# Обновление APK: манифест, HEAD, Range, защита путей
# =====================================================================
APK_NAME = "predictor-1.15.apk"
APK_BYTES = (b"PK\x03\x04 betcity predictor test apk " +
             bytes(range(256))) * 8
APK_SHA = hashlib.sha256(APK_BYTES).hexdigest()
APK_SIZE = len(APK_BYTES)
with open(os.path.join(RELEASES, APK_NAME), "wb") as handle:
    handle.write(APK_BYTES)
with open(os.path.join(RELEASES, "update.json"), "w",
          encoding="utf-8") as handle:
    json.dump({
        "ok": True,
        "version_code": 16,
        "version_name": "1.15",
        "url": "/releases/" + APK_NAME,
        "size": APK_SIZE,
        "sha256": APK_SHA,
        "notes": "Тестовое обновление",
        "mandatory": False,
        "published_at": "29.10.2026 12:00",
    }, handle, ensure_ascii=False, indent=2)

status, data = request("GET", "/api/v1/update")
check("update без токена: 200", status["status"] == 200, status)
check("update: манифест опубликован",
      data.get("ok") is True and data.get("published") is True, data)
check("update: версия", data.get("version_code") == 16
      and data.get("version_name") == "1.15", data)
check("update: ссылка на APK",
      data.get("url") == "/releases/" + APK_NAME, data.get("url"))
check("update: размер и SHA-256",
      data.get("size") == APK_SIZE and data.get("sha256") == APK_SHA, data)
check("update: заметки", data.get("notes") == "Тестовое обновление", data)

status, body = raw_request("HEAD", "/api/v1/update")
check("update HEAD: 200 без тела", status["status"] == 200 and body == b"",
      (status, body[:20]))
check("update HEAD: Content-Length заголовка",
      int(status["headers"].get("Content-Length") or 0) > 0, status)

status, data = request("POST", "/api/v1/update", {})
check("update POST: 405", status["status"] == 405, status)

status, body = raw_request("GET", "/releases/" + APK_NAME)
check("APK: 200 и полный файл",
      status["status"] == 200 and body == APK_BYTES,
      (status, len(body)))
check("APK: Content-Type",
      status["headers"].get("Content-Type")
      == "application/vnd.android.package-archive", status["headers"])
check("APK: Accept-Ranges", status["headers"].get("Accept-Ranges") == "bytes",
      status["headers"])
check("APK: Content-Length", int(status["headers"].get("Content-Length") or 0)
      == APK_SIZE, status["headers"])
check("APK: имя файла в Content-Disposition",
      APK_NAME in (status["headers"].get("Content-Disposition") or ""),
      status["headers"])

status, body = raw_request("HEAD", "/releases/" + APK_NAME)
check("APK HEAD: 200 без тела",
      status["status"] == 200 and body == b"", (status, body[:20]))
check("APK HEAD: размер файла",
      int(status["headers"].get("Content-Length") or 0) == APK_SIZE,
      status["headers"])

status, body = raw_request("GET", "/releases/" + APK_NAME,
                           {"HTTP_RANGE": "bytes=0-99"})
check("APK Range 0-99: 206 и 100 байт",
      status["status"] == 206 and body == APK_BYTES[:100],
      (status, len(body)))
check("APK Range 0-99: Content-Range",
      status["headers"].get("Content-Range")
      == "bytes 0-99/%d" % APK_SIZE, status["headers"])

status, body = raw_request("GET", "/releases/" + APK_NAME,
                           {"HTTP_RANGE": "bytes=100-"})
check("APK Range 100-: остаток файла",
      status["status"] == 206 and body == APK_BYTES[100:],
      (status, len(body)))

status, body = raw_request("GET", "/releases/" + APK_NAME,
                           {"HTTP_RANGE": "bytes=-16"})
check("APK Range -16: последние байты",
      status["status"] == 206 and body == APK_BYTES[-16:],
      (status, len(body)))

status, body = raw_request("GET", "/releases/" + APK_NAME,
                           {"HTTP_RANGE": "bytes=%d-" % APK_SIZE})
check("APK Range за концом: 416",
      status["status"] == 416 and body == b"", (status, body[:20]))

status, data = request("GET", "/releases/no-such.apk")
check("APK не найден: 404", status["status"] == 404, status)
status, data = request("GET", "/releases/update.json")
check("не-APK из releases не отдаётся: 404", status["status"] == 404, status)
status, data = request("GET", "/releases/../update.json")
check("выход из каталога релизов запрещён: 404", status["status"] == 404,
      status)
status, data = request("GET", "/releases/..%2Fupdate.json")
check("кодированный выход из каталога запрещён: 404",
      status["status"] == 404, status)

# Без update.json сервер сам считает SHA-256 и размер APK.
FALLBACK = os.path.join(tempfile.gettempdir(), "predictor-tests",
                        "server_releases_fallback")
shutil.rmtree(FALLBACK, ignore_errors=True)
os.makedirs(FALLBACK, exist_ok=True)
with open(os.path.join(FALLBACK, "predictor-fallback.apk"), "wb") as handle:
    handle.write(APK_BYTES)
saved_dir = online_app.RELEASES_DIR
try:
    online_app.RELEASES_DIR = FALLBACK
    status, data = request("GET", "/api/v1/update")
    check("update без манифеста: APK найден автоматически",
          status["status"] == 200 and data.get("published") is True, data)
    check("update без манифеста: SHA-256 посчитан",
          data.get("sha256") == APK_SHA, data.get("sha256"))
    check("update без манифеста: размер посчитан",
          data.get("size") == APK_SIZE, data.get("size"))
    check("update без манифеста: ссылка на найденный APK",
          data.get("url", "").endswith("/predictor-fallback.apk"),
          data.get("url"))
finally:
    online_app.RELEASES_DIR = saved_dir

EMPTY = os.path.join(tempfile.gettempdir(), "predictor-tests",
                     "server_releases_empty")
shutil.rmtree(EMPTY, ignore_errors=True)
os.makedirs(EMPTY, exist_ok=True)
try:
    online_app.RELEASES_DIR = EMPTY
    status, data = request("GET", "/api/v1/update")
    check("update без релизов: 200 и published=false",
          status["status"] == 200 and data.get("published") is False, data)
    check("update без релизов: нет версии",
          data.get("version_code") == 0 and data.get("sha256") == "", data)
finally:
    online_app.RELEASES_DIR = saved_dir

# =====================================================================
# Паритет: онлайн считает тем же кодом, что и приложение
# =====================================================================
def set_total(total):
    first = (total + 1) // 2
    return [first, total - first]


def recent(total, day, won):
    return {
        "date": "%02d.10.26" % day, "date_text": "%02d.10.26" % day,
        "opponent": "Соперник", "league": "Тест",
        "sets": [set_total(total) for _ in range(3)],
        "match_score": [2, 1] if won else [1, 2],
    }


def h2h(total, day):
    return {
        "date": "%02d.09.26" % day, "date_obj": None,
        "player1": "Игрок А", "player2": "Игрок Б",
        "sets_parsed": [set_total(total) for _ in range(3)],
        "match_score": "3:0", "winner": "P1",
    }


def stats_for(p1, p2, h2h_total):
    return {
        "team1": "Игрок А", "team2": "Игрок Б",
        "h2h_matches": [h2h(h2h_total, day) for day in range(1, 11)],
        "recent": {
            "team1": [recent(p1, day, True) for day in range(1, 6)],
            "team2": [recent(p2, day, False) for day in range(1, 6)],
        },
        "page_total": {"line": 75.5, "last5_over": 3, "last5_under": 2,
                       "season_over": 128, "season_under": 129},
    }


def parity_history():
    import analyzer
    match = {
        "match_id": "parity", "team1": "Игрок А", "team2": "Игрок Б",
        "sport": "table_tennis", "league": "Тест",
        "date": "19.10 20:30", "start_time": "2026-10-19T20:30",
        "stat_link": "/x", "is_started": False, "current_score": "0:0",
        "odds": {},
    }
    history = {}
    index = 0
    for success, totals in (
            (True, [20, 21, 22, 23, 20, 21, 22, 23, 20, 21, 22, 23]),
            (False, [12, 13, 14, 15, 12, 13, 14, 15, 12, 13, 14, 15])):
        for total in totals:
            history["parity%02d" % index] = {
                "team1": "Игрок А", "team2": "Игрок Б",
                "date": "%02d.10.26" % (index + 1), "league": "Тест",
                "sent_at": "2026-10-%02dT12:00:00" % (1 + index % 28),
                "predictions": [{
                    "target": "set1", "kind": "total",
                    "label": "Партия 1", "verdict": "ТБ 18.5",
                    "expected_side": "over", "threshold": 18.5,
                    "confidence_val": 0.6,
                }],
                "set_results": [{
                    "target": "set1", "kind": "total",
                    "success": success,
                    "score": "11:10" if success else "8:7",
                    "total": total, "label": "Партия 1",
                    "verdict": "ТБ 18.5",
                }],
                "stats": analyzer.make_sample(
                    match, stats_for(total, 18, 20)),
                "result_checked": True,
            }
            index += 1
    return history


VOLATILE = {
    "generated_at", "updated_at", "first_seen", "created_at", "checked_at",
    "resolved_at", "last_run", "server_time", "latency_ms", "online",
    "server_version",
}


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()
                if key not in VOLATILE}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


PARITY = parity_history()
PARITY_PAYLOAD = {
    "sports": ["table_tennis"],
    "predictions": PARITY,
    "rules": {},
    "kind": "all",
    "min_group": 10,
    "min_lift": 5,
    "min_hits": 1,
}
local = online_app.analysis_service.build_report(
    PARITY, PARITY_PAYLOAD, rules_by_sport={}, auto_cfg={})
server = online_app.analyze(PARITY_PAYLOAD)
for key in ("server_version", "server_time", "latency_ms", "online",
            "advisor_state"):
    server.pop(key, None)
local_clean = clean(local["payload"])
server_clean = clean(server)
check("паритет: одинаковые наблюдения",
      local_clean.get("observations") == server_clean.get("observations"),
      (local_clean.get("observations"), server_clean.get("observations")))
check("паритет: одинаковые строки анализа",
      local_clean.get("failure") == server_clean.get("failure")
      and local_clean.get("success") == server_clean.get("success"),
      "строки не совпали")
check("паритет: одинаковые рекомендации",
      local_clean.get("recommendations") == server_clean.get("recommendations"),
      (local_clean.get("recommendations"), server_clean.get("recommendations")))
check("паритет: полный отчёт совпадает", local_clean == server_clean,
      sorted(key for key in set(local_clean) | set(server_clean)
             if local_clean.get(key) != server_clean.get(key)))

# =====================================================================
# Монтирование в подкаталог: /predictor/... (общий сайт alwaysdata)
# =====================================================================
def prefixed_request(method, path):
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "SCRIPT_NAME": "/predictor",
        "QUERY_STRING": "",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
        "HTTP_HOST": "virusadk.alwaysdata.net",
        "HTTP_AUTHORIZATION": "Bearer test-token",
        "wsgi.url_scheme": "https",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
    }
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(response_headers)

    body = b"".join(online_app.application(environ, start_response))
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        data = {"raw": body.decode("utf-8", "replace")}
    return captured, data


status, data = prefixed_request("GET", "/api/v1/update")
check("подкаталог: update 200", status["status"] == 200, status)
check("подкаталог: ссылка APK с префиксом",
      data.get("url") == "/predictor/releases/" + APK_NAME, data.get("url"))

status, data = prefixed_request("GET", "/api/v1/ping")
check("подкаталог: ping работает", data.get("ok") is True, data)

status, body = prefixed_request("GET", "/")
check("подкаталог: страница состояния", status["status"] == 200
      and "/predictor/api/v1/ping" in body.get("raw", ""), status)

# path_trim: снаружи /predictor, внутри WSGI путь уже обрезан
saved_base = online_app.BASE_PATH
try:
    online_app.BASE_PATH = "/predictor"
    status, data = request("GET", "/api/v1/update")
    check("path_trim: ссылка APK с публичным префиксом",
          data.get("url") == "/predictor/releases/" + APK_NAME,
          data.get("url"))
    status, data = request("GET", "/predictor/api/v1/ping",
                           token="test-token")
    check("без path_trim: префикс срезается приложением",
          status["status"] == 200 and data.get("ok") is True, data)
    status, body = raw_request("GET", "/predictor/releases/" + APK_NAME)
    check("без path_trim: APK доступен по префиксу",
          status["status"] == 200 and len(body) == APK_SIZE, status)
finally:
    online_app.BASE_PATH = saved_base

print("OK — пройдено проверок: %d" % len(PASSED))

# -*- coding: utf-8 -*-
"""Тесты онлайн-сервиса: ping, авторизация, gzip и расчёт анализа."""

from __future__ import annotations

import gzip
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "server_home")
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
os.environ["PREDICTOR_TOKEN"] = "test-token"

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


status, data = request("GET", "/api/v1/ping")
check("ping без токена: 401", status["status"] == 401, status)
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

print("OK — пройдено проверок: %d" % len(PASSED))

# -*- coding: utf-8 -*-
"""Онлайн-сервис Betcity Predictor для alwaysdata.com.

Сервис не хранит пользовательские данные: телефон присылает снимок истории
и правил, сервер считает тот же отчёт тем же Python-кодом, что и приложение,
и возвращает результат. Поэтому онлайн и офлайн показывают одинаковые цифры.

Модуль использует только стандартную библиотеку Python и рассчитан на WSGI.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import time
import traceback
from datetime import datetime

SERVER_VERSION = "1.14.0"
MAX_BODY = 12 * 1024 * 1024
MAX_PREDICTIONS = 8000

HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (
    os.path.join(HERE, "python"),
    os.path.join(os.path.dirname(HERE), "app", "src", "main", "python"),
):
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import analysis_service  # noqa: E402

TOKEN = str(os.environ.get("PREDICTOR_TOKEN") or "").strip()
AUTH_REQUIRED = bool(TOKEN)


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _now():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def _json_response(start_response, data, status=200, extra_headers=None):
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("X-Predictor-Server", SERVER_VERSION),
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Headers", "Authorization, Content-Type, Content-Encoding, X-Predictor-Token"),
        ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    start_response("%d %s" % (status, _reason(status)), headers)
    return [body]


def _reason(status):
    return {
        200: "OK", 204: "No Content", 400: "Bad Request",
        401: "Unauthorized", 404: "Not Found", 405: "Method Not Allowed",
        413: "Payload Too Large", 500: "Internal Server Error",
    }.get(status, "OK")


def _html_response(start_response, html, status=200):
    body = (html or "").encode("utf-8")
    start_response("%d %s" % (status, _reason(status)), [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("X-Predictor-Server", SERVER_VERSION),
    ])
    return [body]


def _header(environ, name):
    key = "HTTP_" + name.upper().replace("-", "_")
    return str(environ.get(key) or "")


def _token_from(environ):
    value = _header(environ, "Authorization").strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return _header(environ, "X-Predictor-Token").strip()


def _check_auth(environ):
    if not AUTH_REQUIRED:
        return
    supplied = _token_from(environ)
    if supplied != TOKEN:
        raise HttpError(401, "Неверный или отсутствующий токен доступа.")


def _read_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except Exception:
        length = 0
    if length > MAX_BODY:
        raise HttpError(413, "Слишком большой запрос: максимум %d МБ." %
                        (MAX_BODY // (1024 * 1024)))
    stream = environ.get("wsgi.input")
    raw = stream.read(length) if (stream is not None and length) else b""
    if not raw:
        return {}
    encoding = str(environ.get("HTTP_CONTENT_ENCODING") or "").lower()
    if "gzip" in encoding:
        try:
            raw = gzip.decompress(raw)
        except Exception as exc:
            raise HttpError(400, "Не удалось распаковать gzip: %s" % exc)
        if len(raw) > MAX_BODY:
            raise HttpError(413, "Слишком большой запрос после распаковки.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HttpError(400, "Некорректный JSON: %s" % exc)
    if not isinstance(data, dict):
        raise HttpError(400, "Ожидался JSON-объект.")
    return data


def _trim_predictions(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if not isinstance(item, dict):
            continue
        result[str(key)] = item
        if len(result) >= MAX_PREDICTIONS:
            break
    return result


def _options_from(data):
    return {
        "kind": data.get("kind") or "all",
        "target": data.get("target") or "",
        "sports": data.get("sports"),
        "sport": data.get("sport") or "",
        "min_group": data.get("min_group"),
        "min_lift": data.get("min_lift"),
        "min_hits": data.get("min_hits"),
        "limit": data.get("limit") or 0,
        "pairs": data.get("pairs", True),
    }


def analyze(data):
    started = time.time()
    options = _options_from(data)
    sports = data.get("sports")
    if isinstance(sports, str):
        sports = [part for part in sports.replace(",", " ").split() if part]
    rules_by_sport = data.get("rules") if isinstance(data.get("rules"), dict) else {}
    auto_cfg = data.get("auto_rules") if isinstance(data.get("auto_rules"), dict) else {}
    advisor_state = data.get("advisor_state") if isinstance(
        data.get("advisor_state"), dict) else None
    built = analysis_service.build_report(
        _trim_predictions(data.get("predictions")), options,
        rules_by_sport=rules_by_sport, auto_cfg=auto_cfg,
        advisor_state=advisor_state)
    payload = built.get("payload") or {}
    payload["advisor_state"] = built.get("advisor_state") or {}
    payload["server_version"] = SERVER_VERSION
    payload["server_time"] = _now()
    payload["latency_ms"] = int((time.time() - started) * 1000)
    payload["online"] = True
    return payload


def _dashboard(environ):
    scheme = str(environ.get("wsgi.url_scheme") or "https")
    host = str(environ.get("HTTP_HOST") or "predictor.alwaysdata.net")
    base = "%s://%s" % (scheme, host)
    auth = "включён" if AUTH_REQUIRED else "выключен (открытый доступ)"
    html = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Betcity Predictor — онлайн-сервис</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; padding: 28px 18px; background: #12151d; color: #e8eaf0;
         font: 15px/1.55 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
  main { max-width: 760px; margin: 0 auto; }
  h1 { font-size: 24px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 26px 0 8px; }
  .muted { color: #8e97a8; }
  .card { background: #1a1f2b; border: 1px solid #2a3140; border-radius: 14px;
          padding: 16px 18px; margin-top: 14px; }
  .ok { color: #7ee2b0; }
  code { background: #10141c; border: 1px solid #2a3140; border-radius: 6px;
         padding: 2px 6px; font-size: 13px; }
  pre { background: #10141c; border: 1px solid #2a3140; border-radius: 10px;
        padding: 12px; overflow: auto; font-size: 12.5px; }
  ul { padding-left: 20px; }
</style></head><body><main>
  <h1>Betcity Predictor</h1>
  <div class="muted">Онлайн-анализ истории и рекомендаций по правилам</div>
  <div class="card">
    <div><b>Состояние:</b> <span class="ok">работает</span></div>
    <div><b>Версия:</b> {version}</div>
    <div><b>Время сервера:</b> {time}</div>
    <div><b>Доступ:</b> {auth}</div>
  </div>
  <h2>Подключение в приложении</h2>
  <div class="card">
    <div>Адрес сайта:</div>
    <pre>{base}</pre>
    <div class="muted">Настройки → Онлайн-режим → вставьте адрес. Затем
      включите «Использовать онлайн» на экране «Анализ».</div>
  </div>
  <h2>API</h2>
  <div class="card">
    <ul>
      <li><code>GET /api/v1/ping</code> — проверка связи.</li>
      <li><code>POST /api/v1/analyze</code> — расчёт анализа и рекомендаций.</li>
    </ul>
    <div class="muted">Если задан <code>PREDICTOR_TOKEN</code>, передайте
      заголовок <code>Authorization: Bearer …</code>.</div>
  </div>
</main></body></html>"""
    return (html.replace("{version}", SERVER_VERSION)
            .replace("{time}", _now()).replace("{auth}", auth)
            .replace("{base}", base))


class Application(object):
    """WSGI-приложение. Никаких пользовательских данных не сохраняет."""

    def __call__(self, environ, start_response):
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        path = str(environ.get("PATH_INFO") or "/")
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        try:
            if method == "OPTIONS":
                return _json_response(start_response, {"ok": True})
            if path in ("/api/v1/ping", "/api/v1/health"):
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "Метод не поддерживается.")
                _check_auth(environ)
                return _json_response(start_response, {
                    "ok": True,
                    "service": "betcity-predictor",
                    "version": SERVER_VERSION,
                    "server_time": _now(),
                    "auth_required": AUTH_REQUIRED,
                })
            if path == "/api/v1/analyze":
                if method != "POST":
                    raise HttpError(405, "Метод не поддерживается.")
                _check_auth(environ)
                data = _read_body(environ)
                return _json_response(start_response, analyze(data))
            if path == "/":
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "Метод не поддерживается.")
                return _html_response(start_response, _dashboard(environ))
            raise HttpError(404, "Страница не найдена.")
        except HttpError as exc:
            return _json_response(start_response, {
                "ok": False, "error": exc.message,
                "version": SERVER_VERSION, "server_time": _now(),
            }, status=exc.status)
        except Exception as exc:
            traceback.print_exc()
            return _json_response(start_response, {
                "ok": False,
                "error": "Внутренняя ошибка сервера: %s" % exc,
                "version": SERVER_VERSION, "server_time": _now(),
            }, status=500)


application = Application()


def main():  # pragma: no cover - удобно для локального запуска
    from wsgiref.simple_server import make_server
    port = int(os.environ.get("PORT") or 8080)
    print("Betcity Predictor online: http://127.0.0.1:%d" % port)
    make_server("127.0.0.1", port, application).serve_forever()


if __name__ == "__main__":  # pragma: no cover
    main()

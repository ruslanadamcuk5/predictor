# -*- coding: utf-8 -*-
"""Онлайн-сервис Betcity Predictor для alwaysdata.com.

Сервис не хранит пользовательские данные: телефон присылает снимок истории
и правил, сервер считает тот же отчёт тем же Python-кодом, что и приложение,
и возвращает результат. Поэтому онлайн и офлайн показывают одинаковые цифры.

Модуль использует только стандартную библиотеку Python и рассчитан на WSGI.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from email.utils import formatdate
from urllib.parse import parse_qs, unquote

SERVER_VERSION = "1.18.0"
MAX_BODY = 12 * 1024 * 1024
MAX_PREDICTIONS = 8000
CHUNK_SIZE = 256 * 1024

HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (
    os.path.join(HERE, "python"),
    os.path.join(os.path.dirname(HERE), "app", "src", "main", "python"),
):
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import analysis_service  # noqa: E402
import history_store  # noqa: E402
import history_ui  # noqa: E402

TOKEN = str(os.environ.get("PREDICTOR_TOKEN") or "").strip()
AUTH_REQUIRED = bool(TOKEN)

# Публичный префикс, если сайт alwaysdata настроен с обрезкой пути
# (path_trim). Тогда WSGI видит /api/..., а снаружи адрес /predictor/api/...
BASE_PATH = str(os.environ.get("PREDICTOR_BASE_PATH") or "").rstrip("/")

# Каталог с опубликованными релизами. Можно переопределить переменной окружения
# PREDICTOR_RELEASES_DIR, например /home/<login>/predictor/releases.
RELEASES_DIR = os.path.abspath(
    os.environ.get("PREDICTOR_RELEASES_DIR")
    or os.path.join(HERE, "releases"))
RELEASES_PREFIX = "/releases/"
APK_CONTENT_TYPE = "application/vnd.android.package-archive"
_SHA256_CACHE = {}


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _now():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def _query(environ):
    raw = str(environ.get("QUERY_STRING") or "")
    try:
        return {key: values[-1] for key, values in parse_qs(
            raw, keep_blank_values=True).items()}
    except Exception:
        return {}


def _qint(query, name, default=0, minimum=0, maximum=1000):
    try:
        value = int(query.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _qbool(query, name, default=False):
    value = str(query.get(name) or "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on", "да")


def _read_json_body(environ):
    try:
        data = _read_body(environ)
    except HttpError:
        raise
    return data if isinstance(data, dict) else {}


def _json_response(start_response, data, status=200, extra_headers=None, head=False):
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("X-Predictor-Server", SERVER_VERSION),
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Headers", "Authorization, Content-Type, Content-Encoding, X-Predictor-Token"),
        ("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS"),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    start_response("%d %s" % (status, _reason(status)), headers)
    return [b""] if head else [body]


def _reason(status):
    return {
        200: "OK", 204: "No Content", 206: "Partial Content",
        400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
        405: "Method Not Allowed", 413: "Payload Too Large",
        416: "Requested Range Not Satisfiable",
        500: "Internal Server Error",
    }.get(status, "OK")


def _html_response(start_response, html, status=200, head=False):
    body = (html or "").encode("utf-8")
    start_response("%d %s" % (status, _reason(status)), [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("X-Predictor-Server", SERVER_VERSION),
    ])
    return [b""] if head else [body]


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


def _script_prefix(environ):
    """Префикс монтирования, если сервис живёт не в корне сайта."""
    return str(environ.get("SCRIPT_NAME") or BASE_PATH or "").rstrip("/")


def _base_url(environ):
    scheme = str(environ.get("wsgi.url_scheme") or "https")
    host = str(environ.get("HTTP_HOST") or "predictor.alwaysdata.net")
    return "%s://%s%s" % (scheme, host, _script_prefix(environ))


def _sha256_file(path):
    try:
        stat = os.stat(path)
    except OSError:
        return ""
    key = (path, stat.st_size, int(stat.st_mtime))
    cached = _SHA256_CACHE.get(key)
    if cached:
        return cached
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                digest.update(chunk)
    except OSError:
        return ""
    value = digest.hexdigest()
    _SHA256_CACHE.clear()
    _SHA256_CACHE[key] = value
    return value


def _release_files():
    try:
        names = sorted(os.listdir(RELEASES_DIR))
    except OSError:
        return []
    result = []
    for name in names:
        if not name.lower().endswith(".apk"):
            continue
        path = os.path.join(RELEASES_DIR, name)
        if os.path.isfile(path):
            result.append(path)
    return result


def _read_update_file():
    path = os.path.join(RELEASES_DIR, "update.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        traceback.print_exc()
        return {}
    return data if isinstance(data, dict) else {}


def _release_apk(manifest):
    """Возвращает путь к APK из манифеста или самый свежий файл в releases/."""
    raw = str(manifest.get("url") or manifest.get("apk_url")
              or manifest.get("apkUrl") or "").strip()
    if raw:
        name = os.path.basename(raw.split("?", 1)[0].split("#", 1)[0])
        if name.lower().endswith(".apk"):
            candidate = os.path.join(RELEASES_DIR, name)
            if os.path.isfile(candidate):
                return candidate
    files = _release_files()
    if not files:
        return ""
    return max(files, key=lambda path: os.path.getmtime(path))


def _int_of(data, *keys):
    for key in keys:
        if key in data and data[key] is not None:
            try:
                return int(data[key])
            except (TypeError, ValueError):
                return 0
    return 0


def _str_of(data, *keys):
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def update_manifest(environ):
    """Манифест обновления в формате, который читает Android-клиент."""
    data = _read_update_file()
    apk = _release_apk(data)
    apk_name = os.path.basename(apk) if apk else ""
    url = _str_of(data, "url", "apk_url", "apkUrl")
    if not apk_name:
        return {
            "ok": True,
            "service": "betcity-predictor",
            "published": False,
            "version_code": 0,
            "version_name": "",
            "url": "",
            "size": 0,
            "sha256": "",
            "notes": "Обновления ещё не опубликованы.",
            "server_version": SERVER_VERSION,
            "server_time": _now(),
        }
    if not url:
        url = RELEASES_PREFIX + apk_name
    prefix = _script_prefix(environ)
    if prefix and url.startswith("/") and not url.startswith(prefix + "/"):
        url = prefix + url
    size = os.path.getsize(apk)
    published_at = _str_of(data, "published_at", "date")
    if not published_at:
        published_at = datetime.fromtimestamp(
            os.path.getmtime(apk)).strftime("%d.%m.%Y %H:%M")
    return {
        "ok": True,
        "service": "betcity-predictor",
        "published": True,
        "version_code": _int_of(data, "version_code", "versionCode", "code"),
        "version_name": _str_of(data, "version_name", "versionName", "name"),
        "url": url,
        "size": _int_of(data, "size", "bytes") or size,
        "sha256": (_str_of(data, "sha256", "sha") or _sha256_file(apk)).lower(),
        "notes": _str_of(data, "notes", "changelog"),
        "mandatory": bool(data.get("mandatory", False)),
        "min_sdk": _int_of(data, "min_sdk"),
        "published_at": published_at,
        "apk": apk_name,
        "server_version": SERVER_VERSION,
        "server_time": _now(),
    }


def _file_response(environ, start_response, path):
    """Отдаёт APK с поддержкой HEAD, Range и ETag для докачки."""
    name = os.path.basename(path)
    try:
        size = os.path.getsize(path)
        mtime = int(os.path.getmtime(path))
    except OSError:
        raise HttpError(404, "Файл обновления не найден.")
    etag = '"%x-%x"' % (size, mtime)
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    headers = [
        ("Content-Type", APK_CONTENT_TYPE),
        ("Accept-Ranges", "bytes"),
        ("Cache-Control", "public, max-age=300"),
        ("ETag", etag),
        ("Last-Modified", formatdate(mtime, usegmt=True)),
        ("Content-Disposition", 'attachment; filename="%s"' % name),
        ("X-Predictor-Server", SERVER_VERSION),
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Expose-Headers", "Content-Length, Content-Range, ETag"),
    ]
    start, end, status = 0, size - 1, 200
    range_header = str(environ.get("HTTP_RANGE") or "").strip()
    if range_header.lower().startswith("bytes="):
        spec = range_header[6:].split(",", 1)[0].strip()
        first, _, last = spec.partition("-")
        try:
            if first:
                start = max(0, int(first))
                end = int(last) if last else size - 1
            elif last:
                length = max(0, int(last))
                start = max(0, size - length) if length else 0
                end = size - 1
        except ValueError:
            start, end, status = 0, size - 1, 200
        if status == 200:
            if start >= size:
                headers.append(("Content-Range", "bytes */%d" % size))
                start_response("416 %s" % _reason(416), headers)
                return [b""]
            end = min(end, size - 1)
            if end < start:
                start, end, status = 0, size - 1, 200
            else:
                status = 206
                headers.append(
                    ("Content-Range", "bytes %d-%d/%d" % (start, end, size)))
    length = size if status == 200 else end - start + 1
    headers.append(("Content-Length", str(length)))
    start_response("%d %s" % (status, _reason(status)), headers)
    if method == "HEAD" or length <= 0:
        return [b""]

    def stream():
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return stream()


def _serve_release(environ, start_response, path):
    name = path[len(RELEASES_PREFIX):].strip("/")
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HttpError(404, "Файл обновления не найден.")
    if not name.lower().endswith(".apk"):
        raise HttpError(404, "Файл обновления не найден.")
    full = os.path.join(RELEASES_DIR, name)
    if not os.path.isfile(full):
        raise HttpError(404, "Файл обновления не найден.")
    return _file_response(environ, start_response, full)


def _dashboard(environ):
    base = _base_url(environ)
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
      <li><code>GET {prefix}/api/v1/ping</code> — проверка связи.</li>
      <li><code>POST {prefix}/api/v1/analyze</code> — расчёт анализа и рекомендаций.</li>
      <li><code>POST {prefix}/api/v1/sync</code> — приём истории устройства.</li>
      <li><code>GET {prefix}/api/v1/history/devices</code> — список устройств.</li>
      <li><code>GET {prefix}/api/v1/update</code> — манифест обновления APK.</li>
      <li><code>GET {prefix}/releases/&lt;файл&gt;.apk</code> — файл обновления.</li>
    </ul>
    <div class="muted">Если задан <code>PREDICTOR_TOKEN</code>, передайте
      заголовок <code>Authorization: Bearer …</code>.</div>
  </div>
</main></body></html>"""
    return (html.replace("{version}", SERVER_VERSION)
            .replace("{time}", _now()).replace("{auth}", auth)
            .replace("{base}", base)
            .replace("{prefix}", _script_prefix(environ)))


class Application(object):
    """WSGI-приложение. Никаких пользовательских данных не сохраняет."""

    def __call__(self, environ, start_response):
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        path = str(environ.get("PATH_INFO") or "/")
        if (BASE_PATH and not environ.get("SCRIPT_NAME")
                and (path == BASE_PATH or path.startswith(BASE_PATH + "/"))):
            # Сайт без path_trim: срезаем публичный префикс сами.
            path = path[len(BASE_PATH):] or "/"
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
            if path in ("/api/v1/sync", "/api/v1/history/sync"):
                if method != "POST":
                    raise HttpError(405, "Метод не поддерживается.")
                _check_auth(environ)
                data = _read_json_body(environ)
                return _json_response(start_response, history_store.ingest(data))
            if path in ("/api/v1/history/health", "/api/v1/history/db"):
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "Метод не поддерживается.")
                _check_auth(environ)
                return _json_response(start_response, history_store.health())
            if path in ("/api/v1/history/devices", "/api/v1/devices"):
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "Метод не поддерживается.")
                _check_auth(environ)
                return _json_response(start_response, history_store.list_devices(),
                                      head=(method == "HEAD"))
            match = re.match(
                r"^/api/(?:v1/)?(?:history/)?devices/([^/]+)"
                r"(?:/(overview|rules|recommendations|events|predictions|"
                r"rename|delete))?$", path)
            if match:
                device_id = unquote(match.group(1))
                section = match.group(2) or "overview"
                query = _query(environ)
                _check_auth(environ)
                if section == "rename":
                    if method != "POST":
                        raise HttpError(405, "Метод не поддерживается.")
                    body = _read_json_body(environ)
                    updated = history_store.rename_device(
                        device_id, body.get("name") or "")
                    if updated is None:
                        raise HttpError(404, "Устройство не найдено.")
                    return _json_response(start_response, {
                        "ok": True, "device": updated,
                        "server_time": _now()})
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "Метод не поддерживается.")
                if section == "overview":
                    data = history_store.device_overview(
                        device_id, days=_qint(query, "days", 30, 7, 180))
                elif section == "rules":
                    data = history_store.device_rules(
                        device_id, sport=query.get("sport") or "")
                elif section == "recommendations":
                    data = history_store.device_recommendations(
                        device_id,
                        status=query.get("status") or "",
                        limit=_qint(query, "limit", 200, 1, 1000))
                elif section == "events":
                    data = history_store.device_events(
                        device_id,
                        limit=_qint(query, "limit", 100, 1, 1000),
                        offset=_qint(query, "offset", 0, 0, 1000000),
                        sport=query.get("sport") or "",
                        kind=query.get("kind") or "",
                        rule_id=query.get("rule_id") or "")
                else:
                    data = history_store.device_predictions(
                        device_id,
                        limit=_qint(query, "limit", 100, 1, 500),
                        offset=_qint(query, "offset", 0, 0, 1000000),
                        sport=query.get("sport") or "",
                        rule_id=query.get("rule_id") or "",
                        status=query.get("status") or "all")
                if data is None:
                    raise HttpError(404, "Устройство не найдено.")
                return _json_response(start_response, data,
                                      head=(method == "HEAD"))
            if path == "/api/v1/update":
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "Метод не поддерживается.")
                # Манифест обновления открыт: приложение должно уметь проверить
                # новую версию даже без токена доступа к анализу.
                return _json_response(
                    start_response, update_manifest(environ),
                    head=(method == "HEAD"))
            if path.startswith(RELEASES_PREFIX):
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "Метод не поддерживается.")
                return _serve_release(environ, start_response, path)
            if path in ("/", "/history", "/cabinet"):
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "Метод не поддерживается.")
                prefix = _script_prefix(environ)
                return _html_response(
                    start_response, history_ui.render(prefix),
                    head=(method == "HEAD"))
            if path == "/service":
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "Метод не поддерживается.")
                return _html_response(
                    start_response, _dashboard(environ),
                    head=(method == "HEAD"))
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

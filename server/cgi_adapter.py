#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""CGI-адаптер онлайн-сервиса Predictor для статического сайта alwaysdata.

Сайт, созданный в панели как PHP/static, не умеет запускать WSGI. В этом
случае запросы ``/api/*`` перенаправляются правилом Apache на этот скрипт:
он собирает WSGI-окружение из переменных CGI и вызывает тот же
``online_app.application``, что и при обычном WSGI-развёртывании.

Размещение на аккаунте alwaysdata (пример для логина ``predictor``)::

    /home/predictor/predictor/       — серверный бандл (online_app.py, python/)
    /home/predictor/predictor/.env   — PREDICTOR_BASE_PATH и каталог релизов
    /home/predictor/www/cgi/predictor.py   — этот файл, chmod 755
    /home/predictor/www/.htaccess    — RewriteRule ^api(/.*)?$ /cgi/predictor.py
    /home/predictor/www/releases/    — APK и update.json (раздаёт Apache)

Путь к бандлу можно задать переменной окружения ``PREDICTOR_ROOT``.
"""

import os
import sys
import traceback
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = (
    os.environ.get("PREDICTOR_ROOT"),
    os.path.join(os.path.dirname(HERE), "predictor"),
    os.path.join(os.path.dirname(os.path.dirname(HERE)), "predictor"),
)
ROOT = next(
    (path for path in CANDIDATES
     if path and os.path.isfile(os.path.join(path, "online_app.py"))),
    "/home/predictor/predictor",
)
ROOT = os.path.abspath(ROOT)
PYTHON = os.path.join(ROOT, "python")
for _path in (ROOT, PYTHON):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _load_env(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


_load_env(os.path.join(ROOT, ".env"))


def _request_path():
    uri = os.environ.get("REQUEST_URI") or os.environ.get("REDIRECT_URL") or "/"
    path = uri.split("?", 1)[0]
    return unquote(path) or "/"


def _scheme():
    proto = os.environ.get("HTTP_X_FORWARDED_PROTO") or os.environ.get("HTTPS")
    return "https" if str(proto).lower() in ("https", "on", "1") else "http"


def _environ():
    env = {
        "REQUEST_METHOD": os.environ.get("REQUEST_METHOD", "GET"),
        "SCRIPT_NAME": "",
        "PATH_INFO": _request_path(),
        "QUERY_STRING": os.environ.get("QUERY_STRING", ""),
        "SERVER_NAME": os.environ.get("SERVER_NAME", "predictor.alwaysdata.net"),
        "SERVER_PORT": os.environ.get("SERVER_PORT", "443"),
        "SERVER_PROTOCOL": os.environ.get("SERVER_PROTOCOL", "HTTP/1.1"),
        "REMOTE_ADDR": os.environ.get("REMOTE_ADDR", ""),
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": _scheme(),
        "wsgi.input": sys.stdin.buffer,
        "wsgi.errors": sys.stderr,
        "wsgi.multithread": False,
        "wsgi.multiprocess": True,
        "wsgi.run_once": False,
    }
    for key, value in os.environ.items():
        if key.startswith("HTTP_"):
            env[key] = value
    # mod_rewrite переносит заголовок Authorization в REDIRECT_HTTP_*.
    redirected = os.environ.get("REDIRECT_HTTP_AUTHORIZATION")
    if redirected and "HTTP_AUTHORIZATION" not in env:
        env["HTTP_AUTHORIZATION"] = redirected
    for key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _write(status, headers, app_iter):
    sys.stdout.write("Status: %s\r\n" % status)
    for key, value in headers:
        if key.lower() in ("connection", "transfer-encoding", "keep-alive"):
            continue
        sys.stdout.write("%s: %s\r\n" % (key, value))
    sys.stdout.write("\r\n")
    sys.stdout.flush()
    try:
        for chunk in app_iter:
            if chunk:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
    finally:
        close = getattr(app_iter, "close", None)
        if close:
            close()


def main():
    try:
        import online_app

        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = headers

        result = online_app.application(_environ(), start_response)
        _write(
            captured.get("status", "500 Internal Server Error"),
            captured.get("headers") or [("Content-Type", "text/plain; charset=utf-8")],
            result,
        )
    except Exception:
        traceback.print_exc(file=sys.stderr)
        body = "Internal Server Error".encode("utf-8")
        sys.stdout.write("Status: 500 Internal Server Error\r\n")
        sys.stdout.write("Content-Type: text/plain; charset=utf-8\r\n")
        sys.stdout.write("Content-Length: %d\r\n\r\n" % len(body))
        sys.stdout.flush()
        sys.stdout.buffer.write(body)


if __name__ == "__main__":
    main()

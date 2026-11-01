# -*- coding: utf-8 -*-
"""Тесты проверки живого сервиса (`tools/check_live.py`).

Поднимает локальный HTTP-сервер, который ведёт себя как развёрнутый
онлайн-сервис, и запускает настоящий скрипт проверки. Отдельно
контролируется, что POST-запрос анализа уходит с полным телом: раньше
заголовки ответа на скачивание APK перекрывали заголовки запроса, и сервер
получал `Content-Length` от APK вместо длины JSON.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "check_live.py")

PASSED = []
STATE = {"analyze_calls": 0, "analyze_body": b"", "errors": []}


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  OK   " + name)
    else:
        raise AssertionError("%s: %s" % (name, detail))


def _json(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/v1/ping":
            return _json(self, 200, {
                "ok": True, "service": "betcity-predictor",
                "version": "9.9.0", "auth_required": False})
        if path == "/":
            body = (b"<html><h1>\xd0\x9a\xd0\xb0\xd0\xb1\xd0\xb8\xd0\xbd\xd0\xb5\xd1\x82"
                    b" \xd0\xb8\xd1\x81\xd1\x82\xd0\xbe\xd1\x80\xd0\xb8\xd0\xb8</h1>"
                    b"<code>/api/v1</code></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        if path == "/api/v1/history/devices":
            return _json(self, 200, {"ok": True, "devices": []})
        if path == "/api/v1/update":
            return _json(self, 200, {
                "published": True, "version_code": 99,
                "version_name": "9.9", "url": "/releases/test.apk",
                "size": 1024})
        if path == "/releases/test.apk":
            body = b"PK" + b"\x00" * 1022
            rng = self.headers.get("Range") or ""
            if rng == "bytes=0-1023":
                self.send_response(206)
                self.send_header("Content-Range", "bytes 0-1023/1024")
            else:
                self.send_response(200)
            self.send_header("Content-Type",
                             "application/vnd.android.package-archive")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return None

    def do_POST(self):
        path = self.path.split("?")[0]
        if path != "/api/v1/analyze":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length else b""
        STATE["analyze_calls"] += 1
        STATE["analyze_body"] = body
        if length <= 0 or len(body) != length:
            STATE["errors"].append("пустое или короткое тело анализа")
            return _json(self, 400, {"ok": False})
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception as exc:
            STATE["errors"].append("тело не JSON: %s" % exc)
            return _json(self, 400, {"ok": False})
        if parsed.get("sports") != ["table_tennis"]:
            STATE["errors"].append("виды не дошли: %r" % (parsed.get("sports"),))
            return _json(self, 400, {"ok": False})
        return _json(self, 200, {
            "ok": True, "online": True, "server_version": "9.9.0",
            "recommendations": {"table_tennis": []}})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    try:
        result = subprocess.run(
            [sys.executable, TOOL, "--base", base, "--timeout", "15"],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
    finally:
        server.shutdown()
        server.server_close()

    output = (result.stdout or "") + (result.stderr or "")
    check("проверка сервиса прошла", result.returncode == 0, output[-800:])
    check("итог напечатан", "Все проверки пройдены." in output, output[-400:])
    check("анализ вызван один раз", STATE["analyze_calls"] == 1,
          STATE["analyze_calls"])
    check("тело анализа дошло целиком", not STATE["errors"], STATE["errors"])
    check("в теле есть виды",
          b"table_tennis" in STATE["analyze_body"],
          STATE["analyze_body"][:120])
    check("проверка версии и рекомендаций",
          "версия сервера и манифеста совпадает" in output
          and "онлайн-анализ" in output, output[-400:])

    print("OK — пройдено проверок: %d" % len(PASSED))
    return 0


if __name__ == "__main__":
    sys.exit(main())

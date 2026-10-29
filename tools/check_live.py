# -*- coding: utf-8 -*-
"""Проверка развёрнутого онлайн-сервиса без установки приложения.

Запуск:
    python tools/check_live.py
    python tools/check_live.py --base https://example.com --token SECRET

Скрипт проверяет то, что важно для телефона: ping, манифест обновления,
ссылку на APK и поддержку Range (докачка). Использует только стандартную
библиотеку.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "https://predictor.alwaysdata.net"


def request(url, method="GET", headers=None, timeout=30):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()


def check(name, condition, detail=""):
    print(("  OK   " if condition else "  FAIL ") + name + (
        "" if condition else ": " + str(detail)))
    return bool(condition)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--token", default="")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    base = args.base.rstrip("/")
    headers = {"Accept": "application/json"}
    if args.token:
        headers["Authorization"] = "Bearer " + args.token

    ok = True
    status, _, body = request(base + "/api/v1/ping", headers=headers,
                              timeout=args.timeout)
    try:
        ping = json.loads(body.decode("utf-8"))
    except Exception:
        ping = {}
    ok &= check("ping", status == 200 and ping.get("ok") is True,
                (status, body[:200]))

    status, _, body = request(base + "/api/v1/update",
                              timeout=args.timeout)
    try:
        manifest = json.loads(body.decode("utf-8"))
    except Exception:
        manifest = {}
    ok &= check("манифест обновления", status == 200
                and manifest.get("published") is True
                and int(manifest.get("version_code") or 0) > 0,
                (status, body[:200]))
    apk_url = urllib.parse.urljoin(base + "/", str(manifest.get("url") or ""))
    ok &= check("ссылка на APK", bool(manifest.get("url")), manifest.get("url"))

    if apk_url:
        status, headers, body = request(
            apk_url, headers={"Range": "bytes=0-1023"}, timeout=args.timeout)
        ok &= check("APK и Range", status == 206 and len(body) == 1024,
                    (status, len(body), headers.get("Content-Range")))
        ok &= check("APK начинается с ZIP", len(body) >= 2
                    and body[:2] == b"PK", body[:4])

    print("\n" + ("Все проверки пройдены." if ok else "Есть ошибки."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

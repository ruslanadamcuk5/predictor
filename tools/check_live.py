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


def request(url, method="GET", headers=None, timeout=30, data=None):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return 0, {}, str(exc).encode("utf-8", "replace")


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

    status, _, body = request(base + "/", timeout=args.timeout)
    page = body.decode("utf-8", "replace")
    ok &= check("веб-кабинет", status == 200 and "Кабинет истории" in page
                and "/api/v1" in page, (status, page[:160]))

    status, _, body = request(base + "/api/v1/history/devices",
                              headers=headers, timeout=args.timeout)
    try:
        history = json.loads(body.decode("utf-8"))
    except Exception:
        history = {}
    ok &= check("API истории", status == 200 and history.get("ok") is True
                and isinstance(history.get("devices"), list),
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
        status, resp_headers, body = request(
            apk_url, headers={"Range": "bytes=0-1023"}, timeout=args.timeout)
        ok &= check("APK и Range", status == 206 and len(body) == 1024,
                    (status, len(body), resp_headers.get("Content-Range")))
        ok &= check("APK начинается с ZIP", len(body) >= 2
                    and body[:2] == b"PK", body[:4])

    # Паритет версий: манифест обновления и живой движок должны совпадать.
    live_version = str(ping.get("version") or "")
    manifest_version = str(manifest.get("version_name") or "")
    ok &= check("версия сервера и манифеста совпадает",
                bool(live_version) and live_version == manifest_version + ".0",
                (live_version, manifest_version))

    # Анализ на сервере должен считать тем же движком, что и приложение.
    payload = json.dumps({
        "sports": ["table_tennis"],
        "predictions": [],
        "rules": {},
        "min_samples": 6,
        "min_precision": 0.55,
    }).encode("utf-8")
    analyze_headers = {"Accept": "application/json",
                       "Content-Type": "application/json"}
    if args.token:
        analyze_headers["Authorization"] = "Bearer " + args.token
    status, _, body = request(
        base + "/api/v1/analyze", method="POST", headers=analyze_headers,
        timeout=max(args.timeout, 90), data=payload)
    try:
        report = json.loads(body.decode("utf-8"))
    except Exception:
        report = {}
    recs = report.get("recommendations")
    ok &= check("онлайн-анализ", status == 200 and report.get("ok") is True
                and report.get("online") is True
                and isinstance(recs, (list, dict)),
                (status, body[:200]))
    ok &= check("анализ считает той же версией",
                str(report.get("server_version") or "") == live_version,
                (report.get("server_version"), live_version))

    print("\n" + ("Все проверки пройдены." if ok else "Есть ошибки."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

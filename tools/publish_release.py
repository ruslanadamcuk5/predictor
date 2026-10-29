# -*- coding: utf-8 -*-
"""Публикует собранный APK как обновление для онлайн-сервиса.

Запуск из корня проекта:
    python tools/publish_release.py build/outputs/apk/release/app-release.apk \
        --notes "Что нового в 1.15"

Скрипт:
  1. копирует APK в releases/ под именем predictor-<версия>.apk;
  2. считает SHA-256 и размер;
  3. пишет releases/update.json — манифест для GET /api/v1/update;
  4. удаляет старые APK, оставляя --keep последних.

Версия по умолчанию берётся из app/build.gradle.kts (versionName/versionCode),
поэтому публиковать нужно ровно тот APK, который собран из текущего дерева.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRADLE = os.path.join(ROOT, "app", "build.gradle.kts")
RELEASES = os.path.join(ROOT, "releases")


def gradle_version():
    """Читает versionCode и versionName из app/build.gradle.kts."""
    try:
        with open(GRADLE, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return 0, ""
    code = re.search(r"versionCode\s*=\s*(\d+)", text)
    name = re.search(r'versionName\s*=\s*"([^"]+)"', text)
    return (int(code.group(1)) if code else 0,
            name.group(1) if name else "")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value):
    return re.sub(r"[^0-9A-Za-z._-]", "_", value).strip("._") or "latest"


def parse_args(argv=None):
    code, name = gradle_version()
    parser = argparse.ArgumentParser(
        description="Публикация APK как обновления Betcity Predictor.")
    parser.add_argument("apk", help="путь к собранному APK")
    parser.add_argument("--version-name", default=name,
                        help="версия, например 1.15 (по умолчанию из Gradle)")
    parser.add_argument("--version-code", type=int, default=code,
                        help="versionCode (по умолчанию из Gradle)")
    parser.add_argument("--notes", default="",
                        help="текст «Что нового» для окна обновления")
    parser.add_argument("--mandatory", action="store_true",
                        help="обязательное обновление (нельзя отложить)")
    parser.add_argument("--min-sdk", type=int, default=0,
                        help="минимальный SDK для установки")
    parser.add_argument("--releases", default=RELEASES,
                        help="каталог релизов (по умолчанию ./releases)")
    parser.add_argument("--keep", type=int, default=3,
                        help="сколько последних APK оставить (0 — все)")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать манифест, ничего не записывая")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    source = os.path.abspath(args.apk)
    if not os.path.isfile(source):
        print("APK не найден:", source, file=sys.stderr)
        return 2
    if not source.lower().endswith(".apk"):
        print("Ожидался файл .apk:", source, file=sys.stderr)
        return 2
    version_name = (args.version_name or "").strip()
    version_code = int(args.version_code or 0)
    if not version_name:
        print("Не удалось определить версию: укажите --version-name.",
              file=sys.stderr)
        return 2
    if version_code <= 0:
        print("Не удалось определить versionCode: укажите --version-code.",
              file=sys.stderr)
        return 2

    releases = os.path.abspath(args.releases)
    file_name = "predictor-%s.apk" % safe_name(version_name)
    target = os.path.join(releases, file_name)
    digest = sha256(source)
    size = os.path.getsize(source)
    manifest = {
        "ok": True,
        "service": "betcity-predictor",
        "version_code": version_code,
        "version_name": version_name,
        "url": "/releases/" + file_name,
        "apk": file_name,
        "size": size,
        "sha256": digest,
        "notes": args.notes.strip(),
        "mandatory": bool(args.mandatory),
        "min_sdk": int(args.min_sdk or 0),
        "published_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }
    print("APK:      ", source)
    print("Версия:   ", version_name, "(%d)" % version_code)
    print("Размер:   ", size, "байт")
    print("SHA-256:  ", digest)
    print("На сайте: ", manifest["url"])
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    os.makedirs(releases, exist_ok=True)
    if os.path.abspath(source) != os.path.abspath(target):
        shutil.copyfile(source, target)
    manifest_path = os.path.join(releases, "update.json")
    temp = manifest_path + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp, manifest_path)

    removed = cleanup(releases, args.keep)
    for name in removed:
        print("Удалён старый релиз:", name)
    print("Готово:", manifest_path)
    print("Теперь выполните: python tools/prepare_server.py")
    return 0


def cleanup(releases, keep):
    """Оставляет keep самых свежих APK, остальные удаляет."""
    if keep <= 0:
        return []
    try:
        names = [name for name in os.listdir(releases)
                 if name.lower().endswith(".apk")]
    except OSError:
        return []
    paths = [os.path.join(releases, name) for name in names]
    paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    removed = []
    for path in paths[keep:]:
        try:
            os.remove(path)
            removed.append(os.path.basename(path))
        except OSError:
            pass
    return removed


if __name__ == "__main__":
    sys.exit(main())

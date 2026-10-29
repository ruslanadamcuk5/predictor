# -*- coding: utf-8 -*-
"""Тесты публикации релиза: APK, манифест, SHA-256 и очистка старых версий."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "publish_release.py")
WORK = os.path.join(tempfile.gettempdir(), "predictor-tests", "release_tool")
RELEASES = os.path.join(WORK, "releases")

PASSED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  OK   " + name)
    else:
        raise AssertionError("%s: %s" % (name, detail))


def run(*args):
    return subprocess.run(
        [sys.executable, TOOL] + list(args),
        cwd=ROOT, capture_output=True, text=True)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_apk(name, payload):
    path = os.path.join(WORK, name)
    with open(path, "wb") as handle:
        handle.write(payload)
    return path


shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK, exist_ok=True)
APK_1 = write_apk("app-1.15.apk", b"APK-1.15-" + bytes(range(128)))
APK_2 = write_apk("app-1.16.apk", b"APK-1.16-" + bytes(range(200)))

# ---------------------------------------------------------------------
# 1. Публикация и манифест
# ---------------------------------------------------------------------
result = run(APK_1, "--releases", RELEASES, "--version-name", "1.15",
             "--version-code", "16", "--notes", "Первая публикация")
check("публикация завершилась успешно", result.returncode == 0,
      result.stderr or result.stdout)
manifest_path = os.path.join(RELEASES, "update.json")
check("манифест создан", os.path.isfile(manifest_path))
with open(manifest_path, encoding="utf-8") as handle:
    manifest = json.load(handle)
check("манифест: ok", manifest.get("ok") is True, manifest)
check("манифест: версия", manifest.get("version_code") == 16
      and manifest.get("version_name") == "1.15", manifest)
check("манифест: ссылка", manifest.get("url")
      == "/releases/predictor-1.15.apk", manifest)
published = os.path.join(RELEASES, "predictor-1.15.apk")
check("APK скопирован", os.path.isfile(published))
check("APK совпадает с исходным", sha256(published) == sha256(APK_1))
check("манифест: SHA-256", manifest.get("sha256") == sha256(published), manifest)
check("манифест: размер",
      manifest.get("size") == os.path.getsize(published), manifest)
check("манифест: заметки", manifest.get("notes") == "Первая публикация",
      manifest.get("notes"))
check("манифест: дата публикации", bool(manifest.get("published_at")),
      manifest.get("published_at"))

# ---------------------------------------------------------------------
# 2. Новая версия и очистка старых APK
# ---------------------------------------------------------------------
result = run(APK_2, "--releases", RELEASES, "--version-name", "1.16",
             "--version-code", "17", "--notes", "Вторая публикация",
             "--keep", "1")
check("вторая публикация успешна", result.returncode == 0,
      result.stderr or result.stdout)
with open(manifest_path, encoding="utf-8") as handle:
    manifest = json.load(handle)
check("манифест обновился",
      manifest.get("version_code") == 17
      and manifest.get("version_name") == "1.16", manifest)
check("старый APK удалён по --keep 1",
      not os.path.isfile(os.path.join(RELEASES, "predictor-1.15.apk")))
check("новый APK на месте",
      os.path.isfile(os.path.join(RELEASES, "predictor-1.16.apk")))
check("новый SHA-256",
      manifest.get("sha256")
      == sha256(os.path.join(RELEASES, "predictor-1.16.apk")), manifest)

# ---------------------------------------------------------------------
# 3. Ошибки и dry-run
# ---------------------------------------------------------------------
result = run(os.path.join(WORK, "missing.apk"), "--releases", RELEASES,
             "--version-name", "1.17", "--version-code", "18")
check("отсутствующий APK: ошибка", result.returncode != 0, result.stdout)
with open(manifest_path, encoding="utf-8") as handle:
    unchanged = json.load(handle)
check("ошибка не ломает манифест", unchanged.get("version_code") == 17,
      unchanged)

dry = os.path.join(WORK, "dry-releases")
result = run(APK_2, "--releases", dry, "--version-name", "1.18",
             "--version-code", "19", "--dry-run")
check("dry-run успешен", result.returncode == 0, result.stderr or result.stdout)
check("dry-run ничего не пишет", not os.path.isdir(dry)
      or not os.listdir(dry), os.path.isdir(dry))

print("OK — пройдено проверок: %d" % len(PASSED))

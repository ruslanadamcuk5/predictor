# -*- coding: utf-8 -*-
"""Собирает папку для загрузки онлайн-сервиса на alwaysdata.com.

Запуск из корня проекта:
    python tools/prepare_server.py

Результат: dist/server/
    app.wsgi          — точка входа WSGI
    online_app.py     — само приложение
    cgi_adapter.py    — точка входа для сайта PHP/static (CGI)
    python/           — модули анализатора, конструктора и рекомендаций
    history_store.py  — SQLite-история устройств, правил и рекомендаций
    history_ui.py     — веб-кабинет истории
    index.html        — готовая главная страница (кабинет) для www/
    releases/         — APK и манифест update.json (если опубликованы)
    README.md         — памятка по настройке сайта
"""

from __future__ import annotations

import importlib.util
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_PY = os.path.join(ROOT, "app", "src", "main", "python")
SOURCE_SERVER = os.path.join(ROOT, "server")
SOURCE_RELEASES = os.path.join(ROOT, "releases")
DEST = os.path.join(ROOT, "dist", "server")

MODULES = (
    "analysis_service.py",
    "analyzer.py",
    "auto_rules.py",
    "profit.py",
    "rule_advisor.py",
    "constructor_engine.py",
    "sports.py",
)


def main():
    if os.path.isdir(DEST):
        shutil.rmtree(DEST)
    os.makedirs(os.path.join(DEST, "python"))

    for name in ("app.wsgi", "online_app.py", "lazy_app.py", "cgi_adapter.py",
                 "history_store.py", "history_ui.py", "README.md"):
        shutil.copyfile(os.path.join(SOURCE_SERVER, name),
                        os.path.join(DEST, name))
    for name in MODULES:
        shutil.copyfile(os.path.join(SOURCE_PY, name),
                        os.path.join(DEST, "python", name))

    # Статическая главная страница: Apache на alwaysdata отдаёт "/" как файл,
    # поэтому кабинет должен лежать в www/index.html. Ссылки на API строятся
    # без префикса, запросы уходят через rewrite на CGI.
    spec = importlib.util.spec_from_file_location(
        "history_ui", os.path.join(SOURCE_SERVER, "history_ui.py"))
    history_ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(history_ui)
    with open(os.path.join(DEST, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(history_ui.render(""))

    releases_dest = os.path.join(DEST, "releases")
    os.makedirs(releases_dest, exist_ok=True)
    copied = 0
    if os.path.isdir(SOURCE_RELEASES):
        for name in sorted(os.listdir(SOURCE_RELEASES)):
            if not (name.lower().endswith(".apk") or name == "update.json"):
                continue
            source = os.path.join(SOURCE_RELEASES, name)
            if os.path.isfile(source):
                shutil.copyfile(source, os.path.join(releases_dest, name))
                copied += 1

    print("Готово:", DEST)
    print("Загрузите содержимое dist/server в каталог сайта alwaysdata.")
    print("Точка входа WSGI: app.wsgi")
    print("Точка входа CGI:  cgi_adapter.py (для сайта PHP/static)")
    if copied:
        print("Релизов скопировано: %d (GET /api/v1/update)" % copied)
    else:
        print("Релизы не найдены: сначала выполните tools/publish_release.py.")
    print("Не забудьте задать PREDICTOR_TOKEN в переменных окружения сайта.")


if __name__ == "__main__":
    main()

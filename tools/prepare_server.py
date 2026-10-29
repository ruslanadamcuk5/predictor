# -*- coding: utf-8 -*-
"""Собирает папку для загрузки онлайн-сервиса на alwaysdata.com.

Запуск из корня проекта:
    python tools/prepare_server.py

Результат: dist/server/
    app.wsgi          — точка входа WSGI
    online_app.py     — само приложение
    python/           — модули анализатора и конструктора
    README.md         — памятка по настройке сайта
"""

from __future__ import annotations

import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_PY = os.path.join(ROOT, "app", "src", "main", "python")
SOURCE_SERVER = os.path.join(ROOT, "server")
DEST = os.path.join(ROOT, "dist", "server")

MODULES = (
    "analysis_service.py",
    "analyzer.py",
    "auto_rules.py",
    "rule_advisor.py",
    "constructor_engine.py",
    "sports.py",
)


def main():
    if os.path.isdir(DEST):
        shutil.rmtree(DEST)
    os.makedirs(os.path.join(DEST, "python"))

    for name in ("app.wsgi", "online_app.py", "README.md"):
        shutil.copyfile(os.path.join(SOURCE_SERVER, name),
                        os.path.join(DEST, name))
    for name in MODULES:
        shutil.copyfile(os.path.join(SOURCE_PY, name),
                        os.path.join(DEST, "python", name))

    print("Готово:", DEST)
    print("Загрузите содержимое dist/server в каталог сайта alwaysdata.")
    print("Точка входа WSGI: app.wsgi")
    print("Не забудьте задать PREDICTOR_TOKEN в переменных окружения сайта.")


if __name__ == "__main__":
    main()

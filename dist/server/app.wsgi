# -*- coding: utf-8 -*-
"""Точка входа WSGI для alwaysdata.com.

В панели alwaysdata создайте сайт типа «WSGI» и укажите этот файл:
    <каталог сайта>/app.wsgi
Переменная окружения PREDICTOR_TOKEN задаёт токен доступа. Если она пуста,
сайт отвечает без авторизации — так удобно только для первого запуска.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_env(path):
    """Читает .env рядом с точкой входа (KEY=VALUE, без зависимостей)."""
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


_load_env(os.path.join(HERE, ".env"))
for candidate in (
    os.path.join(HERE, "python"),
    os.path.join(os.path.dirname(HERE), "app", "src", "main", "python"),
):
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)

from online_app import application  # noqa: E402,F401

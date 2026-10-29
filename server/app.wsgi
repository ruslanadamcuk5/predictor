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
for candidate in (
    os.path.join(HERE, "python"),
    os.path.join(os.path.dirname(HERE), "app", "src", "main", "python"),
):
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)

from online_app import application  # noqa: E402,F401

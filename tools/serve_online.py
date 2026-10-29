# -*- coding: utf-8 -*-
"""Локальный запуск онлайн-сервиса для проверки с телефона.

Публичный сайт для онлайн-режима не обязателен: сервис можно поднять на
компьютере в той же Wi-Fi сети и указать его адрес в настройках приложения.
Скрипт использует только стандартную библиотеку, поэтому работает сразу
после распаковки проекта.

Запуск:

    python tools/serve_online.py
    python tools/serve_online.py --host 127.0.0.1 --port 8099
    python tools/serve_online.py --token SECRET

В приложении: «Настройки» → «Онлайн-режим» → адрес вида
``http://192.168.1.10:8099`` (без ``/api``). Телефон и компьютер должны быть
в одной сети. Для доступа извне используйте HTTPS-сайт, а не этот сервер:
локальный запуск предназначен для проверки и разработки.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from wsgiref.simple_server import WSGIRequestHandler, make_server


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(ROOT, "server")
PYTHON_DIR = os.path.join(ROOT, "app", "src", "main", "python")


def local_address():
    """Возвращает адрес машины в локальной сети (без внешних запросов)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # TEST-NET-1, пакеты не уходят
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


def main():
    parser = argparse.ArgumentParser(description="Локальный онлайн-сервис")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, SERVER_DIR)
    if str(PYTHON_DIR) not in sys.path:
        sys.path.insert(0, PYTHON_DIR)
    os.environ["PREDICTOR_TOKEN"] = args.token
    os.environ.setdefault(
        "PREDICTOR_RELEASES_DIR", os.path.join(ROOT, "releases"))

    import online_app  # noqa: E402

    server = make_server(args.host, args.port, online_app.application,
                         handler_class=QuietHandler)
    shown = args.host if args.host not in ("0.0.0.0", "::") else local_address()
    print("Betcity Predictor: онлайн-сервис запущен")
    print("  компьютер: http://127.0.0.1:%d" % args.port)
    print("  телефон:   http://%s:%d" % (shown, args.port))
    print("  токен:     %s" % ("задан" if args.token else "не требуется"))
    print("Остановка: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

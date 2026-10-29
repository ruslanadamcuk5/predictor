# -*- coding: utf-8 -*-
"""Собирает браузерный стенд из реальных assets и mock.js.

Запуск из корня проекта:
    python tools/ui_harness/sync_ui.py

После этого откройте tools/ui_harness/index.html в браузере. Стенд не входит
в APK: он только подменяет window.PyApp заглушкой.
"""

from __future__ import annotations

import io
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "app", "src", "main", "assets", "www")
DST = os.path.dirname(os.path.abspath(__file__))


def main():
    for name in ("index.html", "app.js", "docs.js", "style.css"):
        shutil.copyfile(os.path.join(SRC, name), os.path.join(DST, name))

    index_path = os.path.join(DST, "index.html")
    with io.open(index_path, encoding="utf-8") as handle:
        html = handle.read()

    if "mock.js" not in html:
        html = html.replace(
            '<script src="app.js"></script>',
            '<script src="mock.js"></script>\n<script src="app.js"></script>')
    # Браузер кэширует mock.js, поэтому добавляем метку времени файла:
    # после правок заглушки стенд не требует ручной очистки кэша.
    stamp = str(int(os.path.getmtime(os.path.join(DST, "mock.js"))))
    html = html.replace(
        '<script src="mock.js"></script>',
        '<script src="mock.js?v=%s"></script>' % stamp)
    with io.open(index_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(html)

    print("synced:", DST)


if __name__ == "__main__":
    main()

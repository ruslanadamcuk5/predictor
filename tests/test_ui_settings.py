# -*- coding: utf-8 -*-
"""Проверка сохранения настроек в WebView-интерфейсе.

Запускает `tools/ui_harness/check_settings.js`: он подгружает настоящий
`app.js` с заглушкой документа и проверяет, что AI-карточка не перекрывает
нейросеть/интервал, а фоновый опрос статуса не затирает форму.

Если Node.js не установлен, проверка пропускается: она не должна ломать
офлайн-набор на машине без фронтенд-инструментов.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "tools", "ui_harness", "check_settings.js")

NODE = shutil.which("node") or shutil.which("nodejs")
if not NODE:
    print("SKIP — Node.js не найден, UI-проверка пропущена")
    raise SystemExit(0)

if not os.path.exists(SCRIPT):
    print("FAIL — нет %s" % SCRIPT)
    raise SystemExit(1)

result = subprocess.run([NODE, SCRIPT], cwd=ROOT)
if result.returncode != 0:
    print("FAIL — UI-проверка настроек")
    raise SystemExit(result.returncode)
print("UI SETTINGS PASSED")

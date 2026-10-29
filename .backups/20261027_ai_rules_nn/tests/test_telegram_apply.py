# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Проверка применения настроек Telegram без перезапуска."""
import json
import os
import shutil
import sys

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "pred_tg")
if os.path.exists(HOME):
    shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME

APP = os.path.join(ROOT, "app", "src", "main", "python")
sys.path.insert(0, APP)

import engine_api as api

fails = []


def check(name, cond, detail=""):
    if cond:
        print("  OK   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        fails.append(name)


def js(raw):
    return json.loads(raw)


print("=== старт: локальный режим ===")
st = js(api.api_state())
check("telegram configured=False", st["telegram"]["configured"] is False, str(st["telegram"]))

print("=== включаем Telegram ===")
r = js(api.api_save_settings(json.dumps({
    "telegram": {"enabled": True, "token": "123456:FAKE_TOKEN", "chat_id": "999888"},
})))
check("сохранение ok", r["ok"])
st = js(api.api_state())
check("configured=True", st["telegram"]["configured"] is True, str(st["telegram"]))

eng = api.engine()
check("бот online", eng.predictor.telegram.offline is False)
check("token применён", eng.predictor.telegram.token == "123456:FAKE_TOKEN")
check("chat применён", eng.predictor.telegram.chat_id == "999888")
check("base_url", "123456:FAKE_TOKEN" in eng.predictor.telegram.base_url)

print("=== выключаем Telegram ===")
r = js(api.api_save_settings(json.dumps({
    "telegram": {"enabled": False, "token": "123456:FAKE_TOKEN", "chat_id": "999888"},
})))
check("сохранение ok", r["ok"])
st = js(api.api_state())
check("configured=False", st["telegram"]["configured"] is False, str(st["telegram"]))
check("бот offline", eng.predictor.telegram.offline is True)

print("=== пустые поля ===")
js(api.api_save_settings(json.dumps({
    "telegram": {"enabled": True, "token": "", "chat_id": ""},
})))
check("offline без токена", eng.predictor.telegram.offline is True)

print()
if fails:
    print("ПРОВАЛЕНО: %s" % ", ".join(fails))
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")

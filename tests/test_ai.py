# -*- coding: utf-8 -*-
"""Проверки AI-ассистента: запросы, разбор ответов, кэш, задачи, API."""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="predictor_ai_")
os.environ["HOME"] = HOME
os.makedirs(HOME, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import ai_assistant
import engine_api as api
import predictor_core as core

checks = [0, 0]


def check(name, condition, detail=""):
    checks[1] += 1
    if condition:
        checks[0] += 1
        print("PASS %s" % name)
    else:
        print("FAIL %s :: %s" % (name, detail))
        raise SystemExit(1)


class FakeResponse(object):
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class FakeSession(object):
    """Подмена requests.Session: запоминает запрос и отдаёт заготовку."""

    def __init__(self, answer="ok", status=200):
        self.answer = answer
        self.status = status
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers,
                           "timeout": timeout})
        if self.status != 200:
            return FakeResponse({"error": "boom"}, self.status)
        return FakeResponse({
            "choices": [{"message": {"content": self.answer}}],
        })


def fake_body(assistant):
    """Тело последнего запроса к модели."""
    return (assistant.session.calls[-1] or {}).get("json") if \
        getattr(assistant.session, "calls", None) else {}


# ------------------------------------------------------------------ разбор JSON
check("чистый JSON разбирается",
      ai_assistant._extract_json('{"a": 1}') == {"a": 1})
check("JSON в блоке кода разбирается",
      ai_assistant._extract_json('```json\n{"a": 2}\n```') == {"a": 2})
check("JSON с текстом вокруг разбирается",
      ai_assistant._extract_json('Вот ответ: {"a": 3} — готово') == {"a": 3})
check("мусор не превращается в JSON",
      ai_assistant._extract_json("извините, не знаю") is None)

# ------------------------------------------------------------------ провайдеры
eng = api.engine()
assistant = eng.predictor.ai
eng.settings.update({"ai": {"enabled": True, "provider": "gemini",
                            "api_key": "test-key", "base_url": "",
                            "model": "", "timeout": 15}})
cfg = assistant.config()
check("провайдер по умолчанию — gemini", cfg["provider"] == "gemini", cfg)
check("адрес Gemini подставлен",
      cfg["base_url"] ==
      "https://generativelanguage.googleapis.com/v1beta/openai", cfg)
check("модель Gemini подставлена", cfg["model"] == "gemini-3.8-flash", cfg)
check("ассистент готов", assistant.ready() is True)

fake = FakeSession("ответ модели")
assistant.session = fake
text = assistant.chat([{"role": "user", "content": "привет"}])
check("ответ получен", text == "ответ модели", text)
call = fake.calls[0]
check("адрес запроса правильный",
      call["url"].endswith("/chat/completions"), call["url"])
check("токен передан", call["headers"]["Authorization"] == "Bearer test-key",
      call["headers"])
check("модель в теле запроса",
      call["json"]["model"] == "gemini-3.8-flash", call["json"])

# DeepSeek и свой endpoint
eng.settings.update({"ai": {"provider": "deepseek"}})
cfg = assistant.config()
check("адрес DeepSeek подставлен",
      cfg["base_url"] == "https://api.deepseek.com", cfg)
check("модель DeepSeek подставлена", cfg["model"] == "deepseek-flash", cfg)
eng.settings.update({"ai": {"provider": "custom", "base_url": "http://x/v1",
                            "model": "my-model"}})
cfg = assistant.config()
check("свой endpoint не перетирается",
      cfg["base_url"] == "http://x/v1" and cfg["model"] == "my-model", cfg)

# без ключа запрос не делается (для облачного провайдера)
eng.settings.update({"ai": {"provider": "gemini", "api_key": ""}})
fake2 = FakeSession("не должно быть")
assistant.session = fake2
check("без ключа запрос не отправляется",
      assistant.chat([{"role": "user", "content": "x"}]) == "")
check("сеть не трогалась без ключа", not fake2.calls, fake2.calls)

# ошибка провайдера не роняет приложение
eng.settings.update({"ai": {"api_key": "k"}})
fake3 = FakeSession("err", status=429)
assistant.session = fake3
check("ошибка HTTP не ломает",
      assistant.chat([{"role": "user", "content": "x"}]) == "")

# ------------------------------------------------------------------ контекст
match = {"sport": "football", "team1": "Альфа", "team2": "Бета",
         "league": "РПЛ", "date": "22.10.2026 18:00",
         "odds": {"match_p1": 2.1, "match_p2": 3.4, "match_draw": 3.2,
                  "total_line": 2.5}}
stats = {"recent": {"team1": [{"won": True, "match_total": 3},
                              {"won": True, "match_total": 2}],
                    "team2": [{"won": False, "match_total": 1}]},
         "h2h_matches": [{"score": "2:1 (1:0)"}],
         "page_total": {"line": 2.5}}
context = assistant.match_context(match, stats,
                                  [{"label": "Матч", "verdict": "П1",
                                    "confidence_val": 0.6, "source": "neural"}])
check("в контексте есть команды", "Альфа" in context and "Бета" in context,
      context)
check("в контексте есть коэффициенты", "2.1" in context, context)
check("в контексте есть форма", "Форма" in context, context)
check("в контексте есть очные", "Очные" in context, context)
check("в контексте есть прогноз", "П1" in context, context)

# снимок статистики (как в сохранённом прогнозе)
sample = {"recent": {"p1": [{"won": True, "match_total": 3}],
                    "p2": [{"won": False, "match_total": 1}]},
          "h2h": [{"match_sets": [2, 1]}],
          "page_total": {"line": 2.5}}
context2 = assistant.match_context(match, sample)
check("снимок статистики читается", "Форма" in context2, context2)
check("очные из снимка читаются", "Очные" in context2, context2)

# ------------------------------------------------------------------ ИИ-прогноз
eng.settings.update({"ai": {"provider": "gemini", "api_key": "k",
                            "auto_predict": True, "per_cycle": 1,
                            "per_day": 10, "min_confidence": 0.5}})
fake_assistant = ai_assistant.AIAssistant(core.DATA_DIR, eng.settings, None)
fake_assistant.session = FakeSession(json.dumps({
    "winner": "П1", "winner_confidence": 0.7,
    "total": "over", "total_confidence": 0.6, "line": 2.5,
    "reason": "форма лучше"}))
preds = fake_assistant.predict_to_predictions(
    {"match": match, "stats": stats, "predictions": []}, "football")
check("ИИ вернул прогноз", len(preds) == 2, preds)
kinds = sorted({item["kind"] for item in preds})
check("есть исход и тотал", kinds == ["total", "winner"], kinds)
check("источник ИИ помечен",
      all(item.get("source") == "ai" for item in preds), preds)
check("уверенность перенесена",
      any(abs(item["confidence_val"] - 0.7) < 0.01 for item in preds), preds)
check("тотал с линией", any(item.get("threshold") == 2.5 for item in preds),
      preds)

# выбор видов и рынков ИИ
eng.settings.update({"ai": {"provider": "gemini", "api_key": "k",
                            "auto_predict": True, "per_cycle": 1,
                            "per_day": 10, "min_confidence": 0.5,
                            "sports": ["football"],
                            "markets": {"football": ["total"]}}})
limited = ai_assistant.AIAssistant(core.DATA_DIR, eng.settings, None)
limited.session = FakeSession(json.dumps({
    "winner": "П1", "winner_confidence": 0.9,
    "total": "over", "total_confidence": 0.6, "line": 2.5,
    "reason": "только тотал"}))
preds = limited.predict_to_predictions(
    {"match": match, "stats": stats, "predictions": []}, "football")
check("ИИ фильтрует рынки", [item["kind"] for item in preds] == ["total"],
      preds)
check("ИИ не прогнозирует выключенный вид",
      limited.predict_to_predictions(
          {"match": match, "stats": stats}, "hockey") == [])
check("ИИ помечает встроенное мнение",
      limited.predict_to_predictions(
          {"match": match, "stats": stats, "embed": True}, "football")[0]
      .get("embedded") is True)

# возвращаем выбор по всем видам для следующих проверок
eng.settings.update({"ai": {"sports": [
    "table_tennis", "football", "hockey", "basketball",
    "volleyball", "tennis"], "markets": {}}})

# низкая уверенность — прогноза нет
fake_assistant.session = FakeSession(json.dumps({
    "winner": "П1", "winner_confidence": 0.2, "total": "none",
    "total_confidence": 0, "line": 0, "reason": ""}))
preds = fake_assistant.predict_to_predictions(
    {"match": match, "stats": stats}, "football")
check("при низкой уверенности прогноза нет", preds == [], preds)

# ------------------------------------------------------------------ кэш и квоты
assistant = eng.predictor.ai
assistant.session = FakeSession("кэш-ответ")
key = assistant._key("explain", {"a": 1})
check("ключ кэша стабилен", key == assistant._key("explain", {"a": 1}))
check("ключ кэша разный для разных данных",
      key != assistant._key("explain", {"a": 2}))
assistant._cache_put(key, "кэш-ответ")
check("кэш возвращает значение",
      assistant._cache_get(key) == "кэш-ответ")

before = assistant.usage_today()
assistant._count_usage()
check("счётчик запросов растёт", assistant.usage_today() == before + 1,
      assistant.usage_today())
eng.settings.update({"ai": {"per_day": 2}})
expected = max(0, 2 - assistant.usage_today())
check("остаток лимита считается", assistant.quota_left() == expected,
      (assistant.quota_left(), expected, assistant.usage_today()))
eng.settings.update({"ai": {"per_day": 0}})
check("без лимита остаток не ограничен", assistant.quota_left() > 1000,
      assistant.quota_left())

# ------------------------------------------------------------------ задачи
assistant.session = FakeSession("фоновый ответ")
job = assistant.submit("explain", {"match": match})
check("задача создана", job.get("ok") is True and job.get("job"), job)
job_id = job["job"]
import time as _time
for _ in range(50):
    state = assistant.job(job_id)
    if state.get("status") in ("done", "error"):
        break
    _time.sleep(0.1)
check("задача выполнена", state.get("status") == "done", state)
check("задача вернула текст", "фоновый ответ" in (state.get("text") or ""),
      state)

# ------------------------------------------------------------------ API
res = json.loads(api.api_ai(json.dumps({"action": "status"})))
check("api статус ok", res.get("ok") is True, res)
check("api отдаёт провайдера", res["status"].get("provider") == "gemini", res)
check("api отдаёт список провайдеров",
      len(res["status"].get("providers") or []) >= 4, res["status"])
res = json.loads(api.api_ai(json.dumps({"action": "explain",
                                         "payload": {"team1": "Альфа",
                                                     "team2": "Бета"}})))
check("api принимает задачу", res.get("ok") is True, res)
res = json.loads(api.api_ai(json.dumps({"action": "job", "id": "нет"})))
check("api отвечает по несуществующей задаче", res.get("ok") is False, res)
res = json.loads(api.api_ai(json.dumps({"action": "ерунда"})))
check("api отвергает неизвестное действие", res.get("ok") is False, res)

# ------------------------------------------------------------------ чат
eng.settings.update({"ai": {"provider": "gemini", "api_key": "k",
                            "enabled": True}})
assistant = eng.predictor.ai
assistant.engine = eng
assistant.session = FakeSession("Ответ: проверьте настройки правил")
answer = assistant.answer({"question": "Почему нет прогнозов по хоккею?",
                           "history": [{"role": "user", "text": "привет"}],
                           "docs": [{"title": "Правила",
                                      "text": "включите правила для вида"}]})
check("ответ на вопрос получен", "проверьте" in answer, answer)
last = fake_body(assistant)
check("в запрос попал вопрос",
      "Почему нет прогнозов" in str(last), last)
check("в запрос попала документация",
      "включите правила для вида" in str(last), last)
check("в запрос попала справка о приложении",
      "Predictor" in str(last), last)

passport = assistant.passport(eng)
check("в справке есть режим прогнозов",
      "режим прогнозов" in passport.get("state", {}), passport)
check("в справке есть настройки", "active_sport" in passport.get("settings", {}),
      passport)
check("ключ не попадает в справку",
      "api_key" not in json.dumps(passport, ensure_ascii=False), passport)

assistant.add_message("user", "вопрос из теста")
check("история чата сохраняется",
      any(item["text"] == "вопрос из теста"
          for item in assistant.chat_history()), assistant.chat_history())

# ------------------------------------------------------------------ помощник
import ai_inspector  # noqa: E402

alerts = ai_inspector.inspect(eng, force=True)
check("помощник отвечает списком", isinstance(alerts, list), alerts)
check("у каждого совета есть заголовок",
      all(item.get("title") for item in alerts), alerts[:2])
check("советы отсортированы по важности",
      all(ai_inspector.SEVERITY_ORDER.get(alerts[i].get("severity"), 3) <=
          ai_inspector.SEVERITY_ORDER.get(alerts[i + 1].get("severity"), 3)
          for i in range(len(alerts) - 1)), alerts[:3])

ok, message = ai_inspector.apply_action(eng, {"type": "neural_freeze"})
check("заморозка обучения выполняется", ok, message)
check("заморозка сохранена в настройках",
      eng.settings.snapshot()["neural"].get("freeze") is True,
      eng.settings.snapshot()["neural"])
ok, message = ai_inspector.apply_action(eng, {"type": "neural_sport_off",
                                              "sport": "football"})
check("выключение вида выполняется", ok, message)
check("вид убран из настроек нейросети",
      "football" not in (eng.settings.snapshot()["neural"].get("sports") or []),
      eng.settings.snapshot()["neural"])
ok, message = ai_inspector.apply_action(eng, {"type": "odds_check_on"})
check("включение проверки коэффициентов", ok, message)
check("проверка коэффициентов включена",
      eng.settings.snapshot().get("odds_check_enabled") is True,
      eng.settings.snapshot().get("odds_check_enabled"))
ok, message = ai_inspector.apply_action(eng, {"type": "unknown_action"})
check("неизвестное действие безопасно", ok is False, message)

res = json.loads(api.api_ai(json.dumps({"action": "inspect"})))
check("api отдаёт советы", res.get("ok") is True and "alerts" in res, res)
res = json.loads(api.api_ai(json.dumps({"action": "apply",
                                         "payload": {"action": {"type": "neural_freeze"}}})))
check("api выполняет действие", res.get("ok") is True, res)

# свой endpoint (Ollama/LM Studio) — ключ не нужен
eng.settings.update({"ai": {"provider": "custom", "base_url": "http://192.168.1.10:11434/v1",
                            "model": "qwen2.5:14b", "api_key": ""}})
cfg = assistant.config()
check("свой endpoint без ключа готов", assistant.ready() is True, cfg)
fake_local = FakeSession("локальный ответ")
assistant.session = fake_local
assistant.chat([{"role": "user", "content": "привет"}])
call = fake_local.calls[0]
check("без ключа заголовок не отправляется",
      "Authorization" not in call["headers"], call["headers"])
check("адрес своего endpoint использован",
      call["url"].startswith("http://192.168.1.10:11434/v1/chat/completions"),
      call["url"])
res = json.loads(api.api_ai(json.dumps({"action": "test"})))
check("проверка подключения без ключа проходит", res.get("ok") is True, res)

eng.settings.update({"ai": {"provider": "gemini", "api_key": "k"}})
assistant.session = FakeSession("ответ модели")

# переключение провайдера, когда в полях остались значения другого
eng.settings.update({"ai": {"provider": "deepseek",
                            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                            "model": "gemini-3.8-flash"}})
cfg = assistant.config()
check("адрес от другого провайдера заменён",
      cfg["base_url"] == "https://api.deepseek.com", cfg)
check("модель от другого провайдера заменена",
      cfg["model"] == "deepseek-flash", cfg)
check("провайдер остался deepseek", cfg["provider"] == "deepseek", cfg)
eng.settings.update({"ai": {"provider": "custom",
                            "base_url": "http://192.168.1.5:11434/v1",
                            "model": "qwen2.5:14b"}})
cfg = assistant.config()
check("свой endpoint не перетирается провайдером",
      cfg["base_url"] == "http://192.168.1.5:11434/v1"
      and cfg["model"] == "qwen2.5:14b", cfg)

# ------------------------------------------------------------------ диагностика
# Ошибка провайдера показывается, а не «нет ответа»
class ErrorSession(object):
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return FakeResponse(self.payload, self.status)


eng.settings.update({"ai": {"provider": "deepseek", "api_key": "sk-bad",
                            "base_url": "https://api.deepseek.com",
                            "model": "deepseek-flash", "timeout": 60}})
assistant.session = ErrorSession(401, {"error": {
    "message": "Authentication Fails, Your api key: sk-bad is invalid",
    "type": "authentication_error"}})
res = assistant.test()
check("ошибка ключа распознана", res.get("ok") is False, res)
check("текст ошибки провайдера показан",
      "sk-bad is invalid" in (res.get("error") or ""), res)

assistant.session = ErrorSession(404, {"error": {"message": "model not found"}})
res = assistant.test()
check("ошибка модели распознана", "model not found" in (res.get("error") or ""),
      res)

# таймаут
class TimeoutSession(object):
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        raise Exception("HTTPSConnectionPool(host='api.deepseek.com'): "
                        "Read timed out. (read timeout=60)")


assistant.session = TimeoutSession()
res = assistant.test()
check("таймаут распознан",
      "время ожидания" in (res.get("error") or ""), res)

# размышление выключается полем thinking
assistant.session = FakeSession("ок")
eng.settings.update({"ai": {"thinking": False}})
assistant.chat([{"role": "user", "content": "x"}])
body = fake_body(assistant)
check("размышление выключено полем thinking",
      body.get("thinking") == {"type": "disabled"}, body)
eng.settings.update({"ai": {"thinking": True}})
assistant.chat([{"role": "user", "content": "x"}])
body = fake_body(assistant)
check("размышление включено — поля нет", "thinking" not in body, body)

# таймаут по умолчанию стал 60
eng.settings.update({"ai": {"provider": "gemini", "api_key": "k"}})
check("таймаут по умолчанию 60", assistant.config()["timeout"] == 60,
      assistant.config()["timeout"])

# ------------------------------------------------------------------ версия
check("версия движка 1.17.0", api.APP_VERSION == "1.17.0", api.APP_VERSION)

print("\nALL CHECKS PASSED: %d/%d" % (checks[0], checks[1]))

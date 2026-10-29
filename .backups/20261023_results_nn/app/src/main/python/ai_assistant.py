# -*- coding: utf-8 -*-
"""AI-ассистент Predictor: работа с облачной языковой моделью.

Модуль не влияет на расчёт прогнозов: он умеет объяснять, проверять и
подсказывать. Все провайдеры говорят через один OpenAI-совместимый
endpoint, поэтому переключение — это только base_url, модель и ключ.

Задачи:

1. **explain** — объяснить прогноз по матчу простым текстом.
2. **draft** — собрать черновик правила конструктора из находок анализатора.
3. **digest** — сводка результатов и рекомендации.
4. **review** — ревизия набора правил.
5. **predict** — мнение модели по матчу (отдельный источник «ИИ»).

Ограничения, заложенные в код:
- один одновременный запрос к модели;
- кэш ответов по хэшу запроса (повторный тап не тратит лимит);
- дневной лимит запросов и лимит на цикл движка;
- при отсутствии ключа, сети или лимита приложение работает как обычно.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime

import requests

import sports

CACHE_FILE = "ai_cache.json"
CACHE_LIMIT = 120
MAX_CONTEXT_CHARS = 6000

PROVIDERS = {
    "gemini": {
        "label": "Gemini (бесплатный tier)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.8-flash",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat",
    },
    "custom": {
        "label": "Свой endpoint",
        "base_url": "",
        "model": "",
    },
}

SYSTEM_RU = (
    "Ты — помощник аналитика ставок в приложении Predictor. "
    "Отвечай на русском, кратко и по делу, без воды и без советов "
    "«не играйте». Опирайся только на присланные данные и не выдумывай "
    "факты: если данных мало, так и напиши."
)


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _extract_json(text):
    """Достаёт JSON-объект из ответа модели (даже если она добавила текст)."""
    if not text:
        return None
    raw = str(text).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if fence:
        raw = fence.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _fmt_num(value, digits=2):
    try:
        return ("%." + str(digits) + "f") % float(value)
    except (TypeError, ValueError):
        return str(value)


def _error_text(response):
    """Читает текст ошибки из ответа API (JSON или plain)."""
    try:
        data = response.json()
    except Exception:
        text = str(getattr(response, "text", "") or "")
        return text[:240] or ("HTTP %s" % response.status_code)
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)[:240]
        if error:
            return str(error)[:240]
        if data.get("message"):
            return str(data.get("message"))[:240]
    return str(data)[:240]


def _short_error(exc):
    """Короткое понятное описание сетевой ошибки."""
    name = type(exc).__name__
    text = str(exc)
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "превышено время ожидания (увеличьте таймаут в настройках)"
    if "name or service not known" in text.lower() or "nodename nor servname" in text.lower():
        return "не найден адрес сервера (проверьте адрес API и интернет)"
    if "ssl" in text.lower() or "certificate" in text.lower():
        return "ошибка TLS/сертификата (%s)" % text[:80]
    if "connection" in text.lower() or "refused" in text.lower():
        return "соединение не установлено (%s)" % text[:80]
    return "%s: %s" % (name, text[:120])


class AIAssistant:
    """Обёртка над облачной моделью: запросы, кэш, задачи, квоты."""

    def __init__(self, data_dir, settings, logger=None):
        self.data_dir = data_dir
        self.settings = settings
        self.logger = logger
        self._lock = threading.RLock()
        self._cache = {}
        self._jobs = {}
        self._job_seq = 0
        self._busy = False
        self._messages = []
        self._usage = {"date": "", "count": 0}
        self._last_error = ""
        self.session = requests.Session()
        self._load()

    # ---------------------------------------------------------------- настройки
    def config(self):
        cfg = {"provider": "gemini", "base_url": "", "model": "",
               "api_key": "", "timeout": 90, "enabled": False,
               "auto_predict": False, "per_cycle": 1, "per_day": 40,
               "min_confidence": 0.5, "thinking": True}
        try:
            stored = (self.settings.snapshot() or {}).get("ai") or {}
            if isinstance(stored, dict):
                cfg.update(stored)
        except Exception:
            pass
        provider = str(cfg.get("provider") or "gemini").lower()
        if provider not in PROVIDERS:
            provider = "gemini"
        preset = PROVIDERS[provider]
        cfg["provider"] = provider
        cfg["provider_label"] = preset["label"]
        cfg["base_url"] = self._resolve_endpoint(cfg.get("base_url"), provider,
                                                 "base_url")
        cfg["model"] = self._resolve_endpoint(cfg.get("model"), provider, "model")
        try:
            cfg["timeout"] = max(5, min(300, int(cfg.get("timeout") or 90)))
        except Exception:
            cfg["timeout"] = 90
        try:
            value = int(cfg.get("per_cycle"))
            cfg["per_cycle"] = max(0, min(5, value if value is not None else 0))
        except Exception:
            cfg["per_cycle"] = 0
        try:
            value = int(cfg.get("per_day"))
            cfg["per_day"] = max(0, min(1000, value if value is not None else 40))
        except Exception:
            cfg["per_day"] = 40
        try:
            cfg["min_confidence"] = max(0.3, min(0.95,
                                                  float(cfg.get("min_confidence") or 0.5)))
        except Exception:
            cfg["min_confidence"] = 0.5
        cfg["enabled"] = bool(cfg.get("enabled"))
        cfg["auto_predict"] = bool(cfg.get("auto_predict"))
        cfg["thinking"] = bool(cfg.get("thinking", True))
        cfg["api_key"] = str(cfg.get("api_key") or "").strip()
        return cfg

    @staticmethod
    def _resolve_endpoint(value, provider, field):
        """Адрес и модель берём у выбранного провайдера.

        Если в настройках остались значения другого провайдера (например,
        пользователь переключил чип, но поля не обновились) — подставляем
        пресет текущего. Свой endpoint не трогаем: им управляет пользователь.
        """
        text = str(value or "").strip()
        if provider == "custom":
            return text
        if not text:
            return PROVIDERS[provider][field]
        for key, item in PROVIDERS.items():
            if key == provider:
                continue
            if item.get(field) and text == item[field]:
                return PROVIDERS[provider][field]
        return text

    def ready(self):
        cfg = self.config()
        if not cfg["enabled"] or not cfg["base_url"] or not cfg["model"]:
            return False
        # Для своего endpoint (Ollama, LM Studio, vLLM) ключ не нужен.
        if cfg["provider"] == "custom" and not cfg["api_key"]:
            return True
        return bool(cfg["api_key"])

    # ---------------------------------------------------------------- кэш и квоты
    def _path(self, name):
        return os.path.join(self.data_dir, name)

    def _load(self):
        try:
            path = self._path(CACHE_FILE)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    self._cache = data.get("cache") or {}
                    self._messages = data.get("messages") or []
                    self._usage = data.get("usage") or self._usage
        except Exception as exc:
            self._log("AI: не удалось прочитать кэш: %s" % exc)

    def _save(self):
        try:
            tmp = self._path(CACHE_FILE) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"cache": self._cache, "usage": self._usage,
                           "messages": self._messages},
                          handle, ensure_ascii=False)
            os.replace(tmp, self._path(CACHE_FILE))
        except Exception as exc:
            self._log("AI: не удалось сохранить кэш: %s" % exc)

    @staticmethod
    def _key(action, payload):
        raw = json.dumps({"action": action, "payload": payload},
                         ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key):
        with self._lock:
            item = self._cache.get(key)
        if not item:
            return None
        return item.get("text")

    def _cache_put(self, key, text):
        with self._lock:
            self._cache[key] = {"text": text, "at": _now()}
            if len(self._cache) > CACHE_LIMIT:
                items = sorted(self._cache.items(),
                               key=lambda kv: kv[1].get("at") or "")
                for key_to_drop, _ in items[:-CACHE_LIMIT]:
                    self._cache.pop(key_to_drop, None)
            self._save()

    def usage_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            if self._usage.get("date") != today:
                self._usage = {"date": today, "count": 0}
            return int(self._usage.get("count") or 0)

    def quota_left(self):
        cfg = self.config()
        if not cfg["per_day"]:
            return 999999
        return max(0, cfg["per_day"] - self.usage_today())

    def _count_usage(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            if self._usage.get("date") != today:
                self._usage = {"date": today, "count": 0}
            self._usage["count"] = int(self._usage.get("count") or 0) + 1
            self._save()

    # ---------------------------------------------------------------- запрос
    def _post(self, url, body, headers, timeout):
        try:
            return self.session.post(url, json=body, headers=headers,
                                     timeout=timeout)
        except Exception as exc:
            self._last_error = "Сеть недоступна: %s" % _short_error(exc)
            self._log("AI: сеть недоступна — %s" % _short_error(exc))
            return None

    def chat(self, messages, json_mode=False, thinking=None):
        """Один запрос к модели. Возвращает текст ответа."""
        cfg = self.config()
        if not cfg["api_key"] and cfg["provider"] != "custom":
            return ""
        url = cfg["base_url"].rstrip("/") + "/chat/completions"
        body = {"model": cfg["model"], "messages": messages, "stream": False}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if thinking is None:
            thinking = bool(cfg.get("thinking", True))
        if not thinking:
            # DeepSeek и подобные: короткий ответ без «размышления».
            body["thinking"] = {"type": "disabled"}
        headers = {
            "Content-Type": "application/json",
        }
        if cfg["api_key"]:
            headers["Authorization"] = "Bearer %s" % cfg["api_key"]
        started = time.time()
        resp = self._post(url, body, headers, cfg["timeout"])
        if resp is None:
            return ""
        if resp.status_code == 400 and "thinking" in body:
            # Некоторые провайдеры не знают поле thinking — повторяем без него.
            body.pop("thinking", None)
            resp = self._post(url, body, headers, cfg["timeout"])
            if resp is None:
                return ""
        if resp.status_code != 200:
            detail = _error_text(resp)
            self._last_error = "HTTP %s: %s" % (resp.status_code, detail)
            self._log("AI: HTTP %s — %s" % (resp.status_code, detail))
            return ""
        try:
            data = resp.json()
            message = data["choices"][0]["message"]
            text = message.get("content") or message.get("reasoning_content") or ""
        except Exception:
            try:
                data = resp.json()
                message = data["choices"][0]["message"]
                text = message.get("content") or message.get("reasoning_content") or ""
            except Exception as exc:
                self._last_error = "Не удалось разобрать ответ: %s" % _short_error(exc)
                self._log("AI: не удалось разобрать ответ: %s" % _short_error(exc))
                return ""
        text = str(text or "").strip()
        if not text:
            self._last_error = ("Модель вернула пустой ответ. Проверьте модель "
                                "и режим размышления.")
            self._log("AI: пустой ответ от модели")
            return ""
        self._last_error = ""
        self._count_usage()
        self._log("AI: ответ за %.1f с (%d символов)" % (time.time() - started,
                                                         len(text)))
        return text

    # ---------------------------------------------------------------- контекст
    @staticmethod
    def match_context(match, stats=None, predictions=None, nn_info=None):
        """Компактное текстовое описание матча для модели."""
        match = match or {}
        stats = stats or {}
        lines = []
        sport = match.get("sport") or "table_tennis"
        lines.append("Вид спорта: %s" % sport)
        lines.append("Матч: %s — %s" % (match.get("team1", ""),
                                        match.get("team2", "")))
        if match.get("league"):
            lines.append("Лига: %s" % match["league"])
        if match.get("date"):
            lines.append("Дата: %s" % match["date"])
        odds = match.get("odds") or {}
        if odds:
            parts = []
            for key, title in (("match_p1", "П1"), ("match_draw", "Х"),
                                ("match_p2", "П2"), ("total_line", "тотал"),
                                ("handicap", "фора")):
                value = odds.get(key)
                if value:
                    parts.append("%s=%s" % (title, _fmt_num(value)))
            if parts:
                lines.append("Коэффициенты: " + ", ".join(parts))
        recent = stats.get("recent") or {}
        for side, alt, title in (("team1", "p1", "Игрок/команда 1"),
                                 ("team2", "p2", "Игрок/команда 2")):
            games = recent.get(side) or recent.get(alt) or []
            if not games:
                continue
            wins = sum(1 for game in games if game.get("won"))
            totals = [game.get("match_total") for game in games
                      if isinstance(game.get("match_total"), (int, float))]
            avg = (sum(totals) / len(totals)) if totals else None
            lines.append("Форма %s: %d игр, побед %d, средний тотал %s" % (
                title, len(games), wins,
                _fmt_num(avg) if avg is not None else "—"))
        h2h = stats.get("h2h_matches") or stats.get("h2h") or []
        if h2h:
            scores = []
            for item in h2h[:5]:
                score = item.get("score")
                if not score:
                    parts = item.get("match_sets") or []
                    score = ":".join(str(value) for value in parts) if parts else "?"
                scores.append(str(score))
            lines.append("Очные встречи: %d, последние счета: %s" % (
                len(h2h), ", ".join(scores)))
        page = stats.get("page_total") or {}
        if page.get("line"):
            lines.append("Линия тотала со страницы статистики: %s" %
                         _fmt_num(page.get("line")))
        if predictions:
            lines.append("Прогнозы приложения:")
            for item in predictions:
                lines.append("  • %s: %s (уверенность %s, источник %s)" % (
                    item.get("label", ""), item.get("verdict", ""),
                    item.get("confidence_val", ""),
                    item.get("source", "")))
        if nn_info:
            lines.append("Нейросеть: " + str(nn_info))
        text = "\n".join(lines)
        if len(text) > MAX_CONTEXT_CHARS:
            text = text[:MAX_CONTEXT_CHARS]
        return text

    # ---------------------------------------------------------------- задачи
    def explain(self, payload):
        match = payload.get("match") or {}
        context = payload.get("context") or self.match_context(
            match, payload.get("stats"), payload.get("predictions"),
            payload.get("nn_info"))
        prompt = (
            "Объясни прогноз по этому матчу простыми словами: почему выбран "
            "такой исход, на каких данных он основан, какие риски и что "
            "противоположно. Пиши 3-6 коротких абзацев или пунктов. "
            "Не выдумывай данные, которых нет в описании.\n\n" + context)
        return self.chat([{"role": "system", "content": SYSTEM_RU},
                          {"role": "user", "content": prompt}])

    def draft(self, payload):
        sport = payload.get("sport") or "table_tennis"
        findings = payload.get("findings") or ""
        catalog = payload.get("catalog") or {}
        prompt = (
            "По этим находкам анализатора составь ОДНО правило конструктора "
            "для вида спорта «%s».\n"
            "Ответь строго одним JSON-объектом без пояснений:\n"
            '{"name": "...", "conditions": {"logic": "and", "conditions": '
            '[{"metric": "id-метрики", "op": "gte", "value": 0, "args": {}}]}, '
            '"action": {"type": "winner|total|handicap|btts|skip", "side": ..., '
            '"target": ..., "threshold": ..., "value": ...}, "enabled": true}\n'
            "Доступные метрики: %s\n\nНаходки:\n%s" % (
                sport, json.dumps(catalog, ensure_ascii=False)[:1500], findings))
        text = self.chat([{"role": "system", "content": SYSTEM_RU},
                          {"role": "user", "content": prompt}], json_mode=True)
        data = _extract_json(text)
        if not data:
            return text
        return json.dumps(data, ensure_ascii=False, indent=2)

    def digest(self, payload):
        summary = payload.get("summary") or {}
        recent = payload.get("recent") or []
        prompt = (
            "Сделай краткий разбор работы прогнозов: что зашло и что нет, "
            "по каким рынкам и видам спорта результат лучше, какие 2-3 "
            "конкретных изменения внести в правила или настройки. Пиши "
            "списком, до 10 пунктов.\n\nСводка:\n%s\n\nПоследние матчи:\n%s" % (
                json.dumps(summary, ensure_ascii=False)[:2500],
                json.dumps(recent, ensure_ascii=False)[:2000]))
        return self.chat([{"role": "system", "content": SYSTEM_RU},
                          {"role": "user", "content": prompt}])

    def review(self, payload):
        sport = payload.get("sport") or "table_tennis"
        rules = payload.get("rules") or []
        prompt = (
            "Проверь набор правил вида спорта «%s» и найди проблемы: "
            "противоречия, невозможные условия, рынки, которых нет у вида, "
            "слишком жёсткие пороги, дубли. Ответь списком: сначала critical "
            "(сломает прогнозы), потом прочее. Если всё в порядке — так и "
            "напиши.\n\nПравила:\n%s" % (
                sport, json.dumps(rules, ensure_ascii=False)[:6000]))
        return self.chat([{"role": "system", "content": SYSTEM_RU},
                          {"role": "user", "content": prompt}])

    def predict(self, payload):
        """Мнение модели по матчу. Возвращает текст с JSON внутри."""
        match = payload.get("match") or {}
        sport = sports.normalize_sport(
            payload.get("sport") or match.get("sport") or "table_tennis")
        markets = payload.get("markets") or ["winner", "total"]
        context = payload.get("context") or self.match_context(
            match, payload.get("stats"), payload.get("predictions"),
            payload.get("nn_info"))
        hint = ""
        if sport == "table_tennis":
            hint = ("\nДля настольного тенниса: winner — победитель МАТЧА "
                    "(кто возьмёт больше партий), total и line — тотал "
                    "ПЕРВОЙ партии (обычно 18.5).")
        prompt = (
            "Оцени матч по данным ниже и дай свой прогноз. Ответь строго "
            "одним JSON-объектом без пояснений:\n"
            '{"winner": "П1|П2|Х|none", "winner_confidence": 0.0-1.0, '
            '"total": "over|under|none", "total_confidence": 0.0-1.0, '
            '"line": число, "reason": "одно предложение"}\n'
            "Уверенность — твоя оценка, не вероятность из коэффициентов. "
            "Если данных мало или рынка нет — ставь none." + hint + "\n\n"
            + context)
        text = self.chat([{"role": "system", "content": SYSTEM_RU},
                          {"role": "user", "content": prompt}], json_mode=True)
        data = _extract_json(text)
        if not data:
            return ""
        return json.dumps(data, ensure_ascii=False)

    def predict_to_predictions(self, payload, sport):
        """Превращает ответ модели в прогнозы приложения (source='ai')."""
        payload = dict(payload or {})
        payload["sport"] = sport
        text = self.predict(payload)
        data = _extract_json(text)
        if not data:
            return []
        cfg = self.config()
        min_conf = float(cfg.get("min_confidence") or 0.5)
        has_draw = bool(sports.profile(sport).get("has_draw"))
        predictions = []
        reason = str(data.get("reason") or "")[:240]

        def make(target, label, kind, side, verdict, confidence, threshold=None):
            return {
                "target": target,
                "label": label,
                "kind": kind,
                "expected_side": side,
                "threshold": threshold,
                "verdict": verdict,
                "confidence_val": round(float(confidence), 3),
                "min_model_wilson": round(float(confidence), 3),
                "strong": 1,
                "agreement": round(float(confidence), 3),
                "models_info": "ИИ: %s" % (reason or "мнение модели"),
                "source": "ai",
            }

        winner = str(data.get("winner") or "").strip()
        try:
            winner_conf = float(data.get("winner_confidence") or 0.0)
        except (TypeError, ValueError):
            winner_conf = 0.0
        if winner in ("П1", "П2", "Х") and winner_conf >= min_conf:
            if winner == "Х" and not has_draw:
                winner = ""
            else:
                # Для настольного тенниса ИИ оценивает матч целиком —
                # проверяем по победам в партиях, а не по первой партии.
                target = "match"
                predictions.append(make(
                    target,
                    "Матч (П1/П2)" if sport == "table_tennis" else
                    ("Матч (П1 / Ничья / П2)" if has_draw
                     else "Матч (П1 / П2)"),
                    "winner", winner, winner, winner_conf))
        total = str(data.get("total") or "").strip()
        try:
            total_conf = float(data.get("total_confidence") or 0.0)
        except (TypeError, ValueError):
            total_conf = 0.0
        line = data.get("line")
        try:
            line = float(line)
        except (TypeError, ValueError):
            line = None
        if total in ("over", "under") and total_conf >= min_conf and line:
            if sport == "table_tennis":
                # Линия ИИ может быть тоталом матча — берём только
                # правдоподобную линию партии.
                if not (5.0 <= float(line) <= 40.0):
                    line = float(sports.default_total("table_tennis"))
                target = "set1"
                label = "Партия 1 (ТБ/ТМ)"
            else:
                target = "match"
                label = "Тотал матча (ТБ/ТМ)"
            verdict = ("ТБ %s" if total == "over" else "ТМ %s") % _fmt_num(line)
            predictions.append(make(target, label, "total", total, verdict,
                                    total_conf, threshold=line))
        return predictions

    # ---------------------------------------------------------------- чат
    def passport(self, engine=None):
        """Компактная «справка» о приложении и его текущем состоянии.

        Это то, что модель должна знать, чтобы отвечать на вопросы
        пользователя: что за экран, что настроено, что происходит.
        """
        data = {"app": "Predictor — прогнозы по линии Betcity (Android, offline)"}
        try:
            snapshot = self.settings.snapshot() or {}
        except Exception:
            snapshot = {}
        if engine is not None:
            try:
                neural = engine.predictor.nn.status()
            except Exception:
                neural = {}
            try:
                rules = engine.predictor.constructor.snapshot(
                    self.settings.get_sport())
            except Exception:
                rules = []
            try:
                results = engine.get_results(limit=200)
                if isinstance(results, str):
                    results = json.loads(results)
            except Exception:
                results = {}
            rows = (results or {}).get("items") or []
            wins = sum(1 for row in rows if row.get("success") is True)
            done = sum(1 for row in rows if row.get("success") is not None)
            data["state"] = {
                "активный вид": self.settings.get_sport(),
                "режим прогнозов": self.settings.get_algorithm_mode(),
                "правил включено": sum(1 for rule in rules
                                       if rule.get("enabled")),
                "правил всего": len(rules),
                "примеров нейросети": neural.get("total_samples", 0),
                "готовых видов нейросети": neural.get("ready_sports", 0),
                "точность нейросети": {
                    item.get("short"): round(float(item.get("accuracy") or 0) * 100)
                    for item in (neural.get("sports") or [])
                    if item.get("ready")},
                "закрытых прогнозов": done,
                "hit rate": round(wins / done * 100, 1) if done else None,
                "матчей в линии": getattr(engine.predictor, "_live_matches", 0),
            }
            try:
                data["alerts"] = [
                    {"severity": item.get("severity"),
                     "title": item.get("title")}
                    for item in (engine.advice() or [])][:8]
            except Exception:
                pass
        # Настройки — без секретов.
        safe = {}
        for key, value in (snapshot or {}).items():
            if key in ("telegram", "ai"):
                continue
            if isinstance(value, dict):
                safe[key] = {k: v for k, v in value.items()
                             if k not in ("api_key", "token", "chat_id")}
            else:
                safe[key] = value
        data["settings"] = safe
        return data

    def answer(self, payload, engine=None):
        """Отвечает на вопрос пользователя о приложении."""
        question = str(payload.get("question") or "").strip()
        if not question:
            return ""
        history = payload.get("history") or []
        docs = payload.get("docs") or []
        passport = json.dumps(self.passport(engine), ensure_ascii=False)[:4000]
        doc_text = ""
        for item in docs[:4]:
            title = str(item.get("title") or "")
            text = str(item.get("text") or "")
            if not text:
                continue
            doc_text += "\n### %s\n%s\n" % (title, text[:3000])
        messages = [{
            "role": "system",
            "content": (
                SYSTEM_RU + "\n\nТы — встроенный помощник приложения "
                "Predictor. Отвечай на русском, коротко и по делу, "
                " опираясь ТОЛЬКО на приложенную справку и документацию.\n"
                "Правила ответа:\n"
                "• если в справке есть точные числа (точность, примеры, "
                "правила, настройки) — приводи их и называй источник;\n"
                "• если данных не хватает — прямо скажи, чего не хватает, и "
                "что сделать, чтобы появилось;\n"
                "• давай конкретные шаги интерфейса (вкладки, кнопки, "
                "названия настроек);\n"
                "• не выдумывай функции, которых нет в справке;\n"
                "• ответ 120–400 слов, по делу."
            ),
        }]
        for item in history[-6:]:
            role = str(item.get("role") or "user")
            text = str(item.get("text") or "")[:1200]
            if text:
                messages.append({"role": role, "content": text})
        messages.append({
            "role": "user",
            "content": "СПРАВКА О ПРИЛОЖЕНИИ:\n%s\n\nДОКУМЕНТАЦИЯ:\n%s\n\n"
                       "ВОПРОС: %s" % (passport, doc_text or "(нет)", question),
        })
        return self.chat(messages)

    def chat_history(self):
        with self._lock:
            return list(self._messages)

    def add_message(self, role, text):
        with self._lock:
            self._messages.append({"role": role, "text": str(text)[:2000],
                                    "at": _now()})
            if len(self._messages) > 60:
                self._messages = self._messages[-60:]
            self._save()

    # ---------------------------------------------------------------- задачи (async)
    ACTIONS = ("explain", "draft", "digest", "review", "predict", "chat")

    def submit(self, action, payload):
        """Ставит задачу в фоновый поток, возвращает id."""
        if action not in self.ACTIONS:
            return {"ok": False, "error": "Неизвестное действие: %s" % action}
        with self._lock:
            self._job_seq += 1
            job_id = "ai_%d_%d" % (int(time.time()), self._job_seq)
            self._jobs[job_id] = {"status": "queued", "text": "",
                                  "error": "", "action": action}
        thread = threading.Thread(target=self._run_job, args=(job_id, action,
                                                            payload),
                                  daemon=True, name="ai-job")
        thread.start()
        return {"ok": True, "job": job_id}

    def _run_job(self, job_id, action, payload):
        with self._lock:
            self._jobs[job_id]["status"] = "running"
        try:
            key = self._key(action, payload)
            text = self._cache_get(key)
            if text is None:
                with self._lock:
                    busy = self._busy
                    if not busy:
                        self._busy = True
                if busy:
                    text = ""
                else:
                    try:
                        text = self._dispatch(action, payload)
                    finally:
                        with self._lock:
                            self._busy = False
                    if text:
                        self._cache_put(key, text)
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                if text:
                    job["text"] = text
                    job["status"] = "done"
                    if action == "chat":
                        self.add_message("assistant", text)
                else:
                    job["status"] = "error"
                    job["error"] = (self._last_error or
                                    "Модель не ответила: проверьте ключ, "
                                    "провайдера и лимит запросов")
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job["status"] = "error"
                    job["error"] = str(exc)
            self._log("AI: задача %s не удалась: %s" % (action, exc))

    def _dispatch(self, action, payload):
        if action == "explain":
            return self.explain(payload)
        if action == "draft":
            return self.draft(payload)
        if action == "digest":
            return self.digest(payload)
        if action == "review":
            return self.review(payload)
        if action == "predict":
            return self.predict(payload)
        if action == "chat":
            return self.answer(payload, getattr(self, "engine", None))
        return ""

    def job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"ok": False, "error": "Задача не найдена"}
            return {"ok": True, "job": job_id, "status": job.get("status"),
                    "text": job.get("text", ""), "error": job.get("error", "")}

    # ---------------------------------------------------------------- статус
    def status(self):
        cfg = self.config()
        return {
            "enabled": cfg["enabled"],
            "ready": self.ready(),
            "provider": cfg["provider"],
            "provider_label": cfg["provider_label"],
            "base_url": cfg["base_url"],
            "model": cfg["model"],
            "has_key": bool(cfg["api_key"]),
            "timeout": cfg["timeout"],
            "auto_predict": cfg["auto_predict"],
            "per_cycle": cfg["per_cycle"],
            "per_day": cfg["per_day"],
            "min_confidence": cfg["min_confidence"],
            "used_today": self.usage_today(),
            "quota_left": self.quota_left(),
            "providers": [{"id": key, "label": item["label"],
                           "base_url": item["base_url"],
                           "model": item["model"]}
                          for key, item in PROVIDERS.items()],
        }

    def test(self):
        """Проверка подключения: один короткий запрос."""
        cfg = self.config()
        if not cfg["api_key"] and cfg["provider"] != "custom":
            return {"ok": False, "error": "Не задан ключ API"}
        if not cfg["base_url"] or not cfg["model"]:
            return {"ok": False, "error": "Не указан адрес API или модель"}
        self._last_error = ""
        # Короткая проверка: размышление не нужно, ответ приходит быстро.
        text = self.chat([{"role": "system", "content": SYSTEM_RU},
                          {"role": "user", "content": "Ответь одним словом: работа"}],
                         thinking=False)
        if not text:
            return {"ok": False,
                    "error": self._last_error or "Нет ответа от модели"}
        return {"ok": True, "text": text[:200],
                "provider": cfg["provider"], "model": cfg["model"]}

    def _log(self, message):
        if self.logger:
            try:
                self.logger.info(message)
            except Exception:
                pass
        try:
            import predictor_core as core
            core.events.add("INFO", message)
        except Exception:
            pass

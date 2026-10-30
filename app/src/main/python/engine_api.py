"""API-слой между Android-приложением и движком прогнозирования.

Все функции возвращают JSON-строки (их читает Kotlin/JS).
Потокобезопасность: движок работает в отдельном потоке, состояние
читается через блокировки.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import threading
import time
from datetime import datetime

import predictor_core as core
import analysis_service
import analyzer
import ai_inspector
import auto_rules as auto_rule_engine
import online_client
import rule_advisor
import sports

APP_VERSION = "1.18.0"
# Как часто движок пересобирает авто-правила (секунды).
AUTO_RULES_INTERVAL = 180


class Engine:
    def __init__(self):
        self.settings = core.BotSettings()
        self.predictor = core.PredictorEnsemble(settings=self.settings)
        try:
            self.predictor.ai.engine = self
        except Exception:
            pass
        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self._queue = []
        self._queue_ts = None
        self._queue_error = None
        self._cycles = 0
        self._started_at = None
        self._auto_lock = threading.RLock()
        self._auto_last = {}
        self._auto_signature = {}
        self._auto_report = {}
        self._results_cache = {}
        self._state_cache = {"at": 0.0, "text": ""}
        self._analyzer_cache = {}
        self._advisor_path = core.data_path("advisor_state.json")
        self._advisor_state = rule_advisor.load_state(self._advisor_path)
        self._advisor_recs = {}
        self._advisor_last = {}
        self._advisor_lock = threading.RLock()
        self._online_last = {}
        self._sync_lock = threading.RLock()
        self._sync_last_ts = 0.0
        self._device_cache = None
        self._apply_engine_params()

    # ------------------------------------------------------------------ утилиты
    def _apply_engine_params(self):
        """Переносит «глубокие» параметры из настроек в глобальные константы."""
        engine_cfg = self.settings.snapshot().get("engine", {})
        mapping = {
            "streak_min": "STREAK_MIN",
            "window_size": "WINDOW_SIZE",
            "window_min_hits": "WINDOW_MIN_HITS",
            "markov_min_sample": "MARKOV_MIN_SAMPLE",
            "recency_decay": "RECENCY_DECAY",
            "base_rate_min_n": "BASE_RATE_MIN_N",
            "prob_threshold": "PROB_THRESHOLD",
        }
        for key, constant in mapping.items():
            if key in engine_cfg:
                try:
                    setattr(core, constant, type(getattr(core, constant))(engine_cfg[key]))
                except Exception:
                    pass

    def _json(self, payload):
        return json.dumps(payload, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------ цикл
    def _loop(self):
        while not self._stop.is_set():
            try:
                summary = self.predictor.run_cycle()
                self._cycles += 1
                if summary.get("error"):
                    core.events.add("ERROR", "Ошибка цикла: %s" % summary["error"])
                self._refresh_all_auto_rules()
                try:
                    self._push_history()
                except Exception:
                    pass
            except Exception as exc:  # pragma: no cover
                core.events.add("ERROR", "Критическая ошибка цикла: %s" % exc)
            interval = self.settings.get_poll_interval()
            self._stop.wait(interval)

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self._json({"ok": True, "running": True, "already": True})
            self.settings.set_running(True)
            self._apply_engine_params()
            self._stop.clear()
            self._started_at = datetime.now()
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="predictor-loop")
            self._thread.start()
            self._state_cache["at"] = 0
        core.events.add("INFO", "Движок запущен (интервал %d с)" %
                        self.settings.get_poll_interval())
        return self._json({"ok": True, "running": True})

    def stop(self):
        with self._lock:
            self.settings.set_running(False)
            self._stop.set()
            thread = self._thread
            self._thread = None
            self._state_cache["at"] = 0
        if thread and thread.is_alive():
            thread.join(timeout=5)
        core.events.add("INFO", "Движок остановлен")
        return self._json({"ok": True, "running": False})

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def run_once(self):
        """Ручной прогон одного цикла (даже если движок остановлен)."""
        was_running = self.settings.is_running()
        if not was_running:
            self.settings.set_running(True)
        try:
            summary = self.predictor.run_cycle()
        finally:
            if not was_running:
                self.settings.set_running(False)
        self._cycles += 1
        self._state_cache["at"] = 0
        core.events.add("INFO", "Ручная проверка: матчей %d, видов %d, сигналов %d" % (
            summary.get("matches", 0), summary.get("sports", 0),
            summary.get("signals", 0)))
        self._refresh_all_auto_rules()
        try:
            self._push_history(force=True)
        except Exception:
            pass
        return self._json({"ok": True, "summary": summary})

    # ------------------------------------------------------------------ состояние
    def get_state(self):
        # Панель опрашивает состояние каждые 2.5 с. Лёгкий кэш на 1.5 с
        # убирает повторную сборку статуса нейросети и рекомендаций, но
        # запуск/остановка и смена настроек сбрасывают его явно.
        now = time.time()
        cached = self._state_cache or {}
        if cached.get("text") and now - float(cached.get("at") or 0) < 1.5:
            return cached["text"]
        status = self.predictor.status_payload()
        telegram_cfg = self.settings.get_telegram()
        status.update({
            "engine_running": self.is_running(),
            "cycles": self._cycles,
            "started_at": self._started_at.strftime("%d.%m.%Y %H:%M") if self._started_at else None,
            "telegram": {
                "enabled": bool(telegram_cfg.get("enabled")),
                "configured": bool(
                    telegram_cfg.get("enabled")
                    and telegram_cfg.get("token")
                    and telegram_cfg.get("chat_id")),
            },
            "paths": {
                "data": core.DATA_DIR,
                "log": core.LOG_FILE,
                "csv": core.LOG_CSV_FILE,
            },
            "version": APP_VERSION,
            "advice": self.advice(),
            "online_sync": self._sync_status(),
        })
        text = self._json(status)
        self._state_cache = {"at": now, "text": text}
        return text

    # ------------------------------------------------------------------ настройки
    def get_settings(self):
        return self._json({
            "settings": self.settings.snapshot(),
            "defaults": self.settings.DEFAULTS,
            "sports": sports.public_catalog(),
        })

    def save_settings(self, payload):
        try:
            patch = json.loads(payload) if isinstance(payload, str) else payload
        except Exception as exc:
            return self._json({"ok": False, "error": "Некорректный JSON: %s" % exc})
        if not isinstance(patch, dict):
            return self._json({"ok": False, "error": "Ожидался объект"})
        if "active_sport" in patch:
            patch["active_sport"] = sports.normalize_sport(patch.get("active_sport"))
        ok = self.settings.update(patch)
        self._apply_engine_params()
        self._state_cache["at"] = 0
        self._results_cache.clear()
        if "online" in patch:
            self._analyzer_cache.clear()
        if "neural" in patch:
            try:
                self.predictor.nn.request_train()
            except Exception:
                pass
        # Применяем новые параметры Telegram без перезапуска приложения.
        try:
            self.predictor.telegram.apply_settings()
        except Exception:
            pass
        if "engine" in patch:
            core.events.add("INFO", "Параметры движка обновлены")
        return self._json({"ok": bool(ok), "settings": self.settings.snapshot()})

    def reset_settings(self):
        ok = self.settings.reset_to_defaults(keep_telegram=True)
        self._apply_engine_params()
        core.events.add("WARNING", "Настройки сброшены к значениям по умолчанию")
        return self._json({"ok": bool(ok), "settings": self.settings.snapshot()})

    # ------------------------------------------------------------ авто-правила
    def _auto_cfg(self):
        defaults = dict(self.settings.DEFAULTS.get("auto_rules") or {})
        cfg = self.settings.snapshot().get("auto_rules") or {}
        defaults.update(cfg if isinstance(cfg, dict) else {})
        try:
            defaults["min_precision"] = max(
                50.0, min(95.0, float(defaults.get("min_precision") or 60.0)))
        except Exception:
            defaults["min_precision"] = 60.0
        try:
            defaults["min_samples"] = max(
                3, min(50, int(defaults.get("min_samples") or 6)))
        except Exception:
            defaults["min_samples"] = 6
        try:
            defaults["max_rules"] = max(
                1, min(12, int(defaults.get("max_rules") or 4)))
        except Exception:
            defaults["max_rules"] = 4
        defaults["enabled"] = bool(defaults.get("enabled"))
        return defaults

    def _auto_status(self, sport=None):
        sport = sports.normalize_sport(sport or self.settings.get_sport())
        cfg = self._auto_cfg()
        rules = self.predictor.constructor.snapshot(sport)
        autos = [rule for rule in rules if rule.get("auto")]
        report = dict(self._auto_report.get(sport) or {})
        summary = auto_rule_engine.summarize(autos)
        updated = ""
        for rule in autos:
            value = str((rule.get("auto_stats") or {}).get("updated_at") or "")
            if value > updated:
                updated = value
        if not updated:
            updated = str(report.get("updated_at") or "")
        hint = str(report.get("hint") or "")
        if not cfg["enabled"]:
            hint = "Авто-формирование выключено. Включите его, чтобы правила обновлялись сами."
        elif not autos:
            hint = hint or (
                "Авто включено, но устойчивых закономерностей пока нет. "
                "Нужно больше прогнозов с результатами.")
        elif not self.is_running():
            hint = "Движок остановлен: авто-правила обновятся после запуска или по кнопке «Обновить»."
        return {
            "ok": True,
            "enabled": cfg["enabled"],
            "mode": self.settings.get_algorithm_mode(),
            "engine_running": self.is_running(),
            "sport": sport,
            "sport_name": sports.name(sport),
            "min_precision": cfg["min_precision"],
            "min_samples": cfg["min_samples"],
            "max_rules": cfg["max_rules"],
            "interval_sec": AUTO_RULES_INTERVAL,
            "generated": sum(1 for rule in autos if rule.get("enabled", True)),
            "auto_total": len(autos),
            "observations": int(report.get("observations") or 0),
            "groups": report.get("groups") or [],
            "updated_at": updated,
            "rules": summary,
            "hint": hint,
        }

    def _refresh_auto_rules(self, force=False, sport=None):
        """Пересобирает авто-правила активного вида спорта."""
        cfg = self._auto_cfg()
        sport = sports.normalize_sport(sport or self.settings.get_sport())
        if not cfg["enabled"]:
            return self._auto_status(sport)

        now = time.time()
        with self._auto_lock:
            last = float(self._auto_last.get(sport) or 0)
            if not force and now - last < AUTO_RULES_INTERVAL:
                return self._auto_status(sport)

            raw = self.predictor.telegram.snapshot_predictions()
            constructor = self.predictor.constructor
            existing = constructor.snapshot(sport)
            try:
                result = auto_rule_engine.generate(
                    raw, sport,
                    min_precision=cfg["min_precision"],
                    min_samples=cfg["min_samples"],
                    max_rules=cfg["max_rules"],
                    existing_rules=existing)
            except Exception as exc:
                core.events.add("ERROR", "Авто-правила: %s" % exc)
                self._auto_report[sport] = {
                    "observations": 0, "groups": [],
                    "hint": "Ошибка авто-формирования: %s" % exc,
                    "updated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
                }
                return self._auto_status(sport)

            self._auto_last[sport] = now
            if not result.get("ok"):
                core.events.add(
                    "ERROR", "Авто-правила: %s" % result.get("error"))
                return self._auto_status(sport)

            observations = int(result.get("observations") or 0)
            # Если данных мало, не удаляем уже накопленные авто-правила.
            if observations < cfg["min_samples"]:
                self._auto_report[sport] = {
                    "observations": observations,
                    "groups": result.get("groups") or [],
                    "hint": "Мало данных: нужно минимум %d удачных прогнозов "
                            "с результатами." % cfg["min_samples"],
                    "updated_at": result.get("updated_at") or "",
                }
                return self._auto_status(sport)

            manual = [rule for rule in existing if not rule.get("auto")]
            current_auto = [rule for rule in existing if rule.get("auto")]
            generated = result.get("rules") or []
            new_rules = manual + generated
            same = (result.get("signature") == self._auto_signature.get(sport)
                    and len(current_auto) == len(generated)
                    and all(rule.get("enabled", True) for rule in current_auto))
            if not same:
                ok, errors, saved = constructor.save(
                    {"rules": new_rules, "sport": sport}, sport)
                if not ok:
                    core.events.add(
                        "ERROR", "Авто-правила не сохранены: %s" %
                        "; ".join(errors[:3]))
                    return self._auto_status(sport)
                self._auto_signature[sport] = result.get("signature") or ""
                total_precision = [
                    (rule.get("auto_stats") or {}).get("precision")
                    for rule in saved if rule.get("auto")
                ]
                avg = 0.0
                if total_precision:
                    avg = sum(float(item or 0) for item in total_precision) / \
                        len(total_precision)
                core.events.add(
                    "INFO",
                    "Авто-правила (%s): %d, средняя точность %.1f%%, "
                    "наблюдений %d" % (
                        sports.short_name(sport), len(generated), avg,
                        observations))

            self._auto_report[sport] = {
                "observations": observations,
                "groups": result.get("groups") or [],
                "hint": result.get("hint") or "",
                "updated_at": result.get("updated_at") or "",
            }
            return self._auto_status(sport)

    def _refresh_all_auto_rules(self, force=False):
        """Пересобирает авто-правила по всем видам, которые анализирует движок."""
        if not self._auto_cfg()["enabled"]:
            return
        for sport in sports.SPORT_ORDER:
            try:
                self._refresh_auto_rules(force=force, sport=sport)
            except Exception as exc:
                core.events.add(
                    "ERROR", "Авто-правила (%s): %s" %
                    (sports.short_name(sport), exc))

    def _set_all_auto_rules_enabled(self, enabled):
        """Включает/выключает авто-правила во всех видах, не трогая ручные."""
        for sport in sports.SPORT_ORDER:
            self._set_auto_rules_enabled(sport, enabled)

    def _set_auto_rules_enabled(self, sport, enabled):
        """Включает/выключает авто-правила, не трогая ручные."""
        sport = sports.normalize_sport(sport)
        constructor = self.predictor.constructor
        existing = constructor.snapshot(sport)
        manual = [rule for rule in existing if not rule.get("auto")]
        autos = []
        for rule in existing:
            if not rule.get("auto"):
                continue
            item = json.loads(json.dumps(rule, ensure_ascii=False))
            item["enabled"] = bool(enabled)
            autos.append(item)
        if autos or manual:
            constructor.save({"rules": manual + autos, "sport": sport}, sport)
        self._auto_signature.pop(sport, None)
        self._auto_last.pop(sport, None)

    def auto_rules(self, payload=None):
        """API авто-формирования правил: status/enable/disable/refresh/configure."""
        options = {}
        if payload:
            try:
                data = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(data, dict):
                    options = data
            except Exception:
                options = {}
        action = str(options.get("action") or "status").strip().lower()
        sport = sports.normalize_sport(
            options.get("sport") or self.settings.get_sport())

        if action in ("enable", "on"):
            self.settings.update({
                "auto_rules": {"enabled": True},
                "algorithm_mode": "constructor",
            })
            self._auto_signature.clear()
            self._auto_last.clear()
            self._refresh_all_auto_rules(force=True)
            core.events.add(
                "INFO", "Авто-правила включены для всех видов")
        elif action in ("disable", "off"):
            self.settings.update({"auto_rules": {"enabled": False}})
            self._set_all_auto_rules_enabled(False)
            core.events.add(
                "INFO", "Авто-правила выключены для всех видов")
        elif action in ("configure", "settings"):
            patch = {}
            for key in ("min_precision", "min_samples", "max_rules"):
                if key in options:
                    patch[key] = options.get(key)
            if patch:
                self.settings.update({"auto_rules": patch})
                self._auto_signature.clear()
                self._auto_last.clear()
            if self._auto_cfg()["enabled"]:
                self._refresh_all_auto_rules(force=True)
        elif action in ("refresh", "run", "update"):
            self._refresh_all_auto_rules(force=True)
        else:
            # status
            pass
        return self._json(self._auto_status(sport))

    # ------------------------------------------------------------------ ИИ
    def advice(self, force=False):
        """Рекомендации помощника по текущему состоянию приложения."""
        try:
            return ai_inspector.inspect(self, force=force)
        except Exception as exc:
            core.events.add("ERROR", "Помощник: %s" % exc)
            return []

    def _ai_match_payload(self, body):
        """Собирает контекст матча из сохранённого прогноза."""
        team1 = str(body.get("team1") or "")
        team2 = str(body.get("team2") or "")
        record = None
        try:
            with self.predictor.telegram._lock:
                records = list(self.predictor.telegram.sent_predictions.values())
        except Exception:
            records = []
        for item in records:
            if item.get("team1") == team1 and item.get("team2") == team2:
                record = item
                break
        if record is None:
            return {"match": {"team1": team1, "team2": team2},
                    "stats": {}, "predictions": []}
        sample = record.get("stats") or {}
        match = sample.get("match") or {
            "team1": team1, "team2": team2,
            "sport": record.get("sport"),
            "league": record.get("league"),
            "date": record.get("date"),
        }
        stats = {
            "recent": sample.get("recent") or {},
            "h2h_matches": sample.get("h2h") or [],
            "page_total": sample.get("page_total") or {},
        }
        return {"match": match, "stats": stats,
                "predictions": record.get("predictions") or []}

    def ai(self, payload=None):
        """AI-ассистент: статус, проверка подключения и фоновые задачи."""
        options = {}
        try:
            if isinstance(payload, str) and payload.strip():
                data = json.loads(payload)
                if isinstance(data, dict):
                    options = data
            elif isinstance(payload, dict):
                options = payload
        except Exception as exc:
            return self._json({"ok": False, "error": "Некорректный JSON: %s" % exc})
        action = str(options.get("action") or "status").strip().lower()
        assistant = self.predictor.ai

        if action == "status":
            return self._json({"ok": True, "status": assistant.status()})
        if action == "test":
            result = assistant.test()
            return self._json(result)
        if action == "job":
            return self._json(assistant.job(str(options.get("id") or "")))
        if action == "chat":
            question = str((options.get("payload") or {}).get("question") or "")
            if not question.strip():
                return self._json({"ok": False, "error": "Пустой вопрос"})
            if not assistant.ready():
                return self._json({"ok": False,
                                    "error": "ИИ не настроен: укажите ключ "
                                             "и включите переключатель"})
            assistant.add_message("user", question)
            body = options.get("payload") or {}
            return self._json(assistant.submit("chat", body))
        if action == "messages":
            return self._json({"ok": True, "messages": assistant.chat_history()})
        if action == "inspect":
            return self._json({"ok": True, "alerts": self.advice(force=True)})
        if action == "apply":
            ok, message = ai_inspector.apply_action(
                self, (options.get("payload") or {}).get("action") or {})
            return self._json({"ok": ok, "message": message,
                                "alerts": self.advice(force=True)})
        if action in ("explain", "draft", "digest", "review", "predict"):
            body = options.get("payload") or {}
            if action == "explain":
                body = self._ai_match_payload(body)
            if action == "predict":
                body = dict(body)
                body.setdefault("sport", self.settings.get_sport())
            if action in ("draft", "review"):
                body.setdefault("sport", self.settings.get_sport())
            if not assistant.ready():
                return self._json({"ok": False,
                                    "error": "ИИ не настроен: укажите ключ "
                                             "и включите переключатель"})
            return self._json(assistant.submit(action, body))
        return self._json({"ok": False, "error": "Неизвестное действие"})

    # ------------------------------------------------------------------ нейросеть
    def neural(self, payload=None):
        """Статус, обучение и сброс нейросети."""
        options = {}
        try:
            if isinstance(payload, str) and payload.strip():
                data = json.loads(payload)
                if isinstance(data, dict):
                    options = data
            elif isinstance(payload, dict):
                options = payload
        except Exception as exc:
            return self._json({"ok": False, "error": "Некорректный JSON: %s" % exc})
        action = str(options.get("action") or "status").strip().lower()
        trainer = self.predictor.nn

        if action in ("enable", "on"):
            self.settings.update({"neural": {"enabled": True}})
            trainer.request_train()
            core.events.add("INFO", "Нейросеть: прогнозы по сети включены")
        elif action in ("disable", "off"):
            self.settings.update({"neural": {"enabled": False}})
            core.events.add("INFO", "Нейросеть: прогнозы по сети выключены")
        elif action in ("train", "run", "update"):
            trainer.train_now(force=True)
            core.events.add("INFO", "Нейросеть: обучение запущено в фоне")
        elif action in ("rollback", "restore"):
            sport = options.get("sport")
            done = trainer.rollback(sport)
            core.events.add(
                "INFO", "Нейросеть: откат модели%s" %
                ((" (%s)" % sports.short_name(done[0])) if done else ""))
        elif action in ("reset", "clear"):
            trainer.reset(clear_samples=True)
            core.events.add("WARNING", "Нейросеть: данные обучения сброшены")
        elif action in ("configure", "settings"):
            patch = {}
            for key in ("min_samples", "min_confidence", "sets"):
                if key in options:
                    patch[key] = options.get(key)
            if "sports" in options:
                patch["sports"] = options.get("sports")
            if "markets" in options:
                patch["markets"] = options.get("markets")
            if "auto_train" in options:
                patch["auto_train"] = bool(options.get("auto_train"))
            if "keep_best" in options:
                patch["keep_best"] = bool(options.get("keep_best"))
            if "freeze" in options:
                patch["freeze"] = bool(options.get("freeze"))
            if patch:
                self.settings.update({"neural": patch})
                trainer.request_train()
        status = trainer.status()
        return self._json({"ok": True, "status": status, "action": action})

    def set_sport(self, sport):
        """Переключает активный вид спорта (правила и шаблоны — свои у каждого)."""
        value = sports.normalize_sport(sport)
        self.settings.set_sport(value)
        core.events.add("INFO", "Вид спорта: %s" % sports.name(value))
        return self._json({
            "ok": True,
            "sport": value,
            "name": sports.name(value),
            "constructor": self.predictor.constructor.stats_payload(value),
        })

    # ------------------------------------------------------------------ логи
    def get_logs(self, since_id=0, limit=500, level="", search=""):
        try:
            since_id = int(since_id)
        except Exception:
            since_id = 0
        try:
            limit = max(1, min(2000, int(limit)))
        except Exception:
            limit = 500
        items = core.events.since(since_id, limit=limit)
        if level:
            items = [e for e in items if e.get("level") == level.upper()]
        if search:
            needle = str(search).lower()
            items = [e for e in items if needle in str(e.get("message", "")).lower()]
        last_id = items[-1]["id"] if items else since_id
        return self._json({"items": items, "last_id": last_id})

    def clear_logs(self):
        core.events.clear()
        core.events.add("INFO", "Журнал очищен")
        return self._json({"ok": True})

    def get_errors(self, limit=200):
        items = [e for e in core.events.all(limit=2000) if e.get("level") == "ERROR"]
        return self._json({"items": items[-int(limit):]})

    # ------------------------------------------------------------------ очередь
    def _sent_index(self):
        """Снимок отправленных прогнозов, сгруппированный по матчу."""
        raw = self.predictor.telegram.snapshot_predictions()
        exact, by_teams = {}, {}
        for data in raw.values():
            entry = self._prediction_brief(data)
            key = (data.get("team1"), data.get("team2"), data.get("date"))
            exact[key] = entry
            teams_key = (data.get("team1"), data.get("team2"))
            previous = by_teams.get(teams_key)
            if previous is None or str(entry.get("sent_at", "")) > str(previous.get("sent_at", "")):
                by_teams[teams_key] = entry
        return exact, by_teams

    @staticmethod
    def _prediction_brief(data):
        predictions = data.get("predictions") or []
        results = data.get("set_results") or []
        items = []
        for pred in predictions:
            result = None
            for res in results:
                if res.get("target") != pred.get("target"):
                    continue
                if res.get("kind") and pred.get("kind") and \
                        res.get("kind") != pred.get("kind"):
                    continue
                result = res
                break
            items.append({
                "target": pred.get("target", ""),
                "kind": pred.get("kind", ""),
                "label": pred.get("label", pred.get("target", "")),
                "verdict": pred.get("verdict", ""),
                "success": result.get("success") if result else None,
                "score": (result or {}).get("score", ""),
                "total": (result or {}).get("total"),
            })
        wins = sum(1 for r in results if r.get("success"))
        losses = sum(1 for r in results if not r.get("success"))
        return {
            "sent_at": data.get("sent_at", ""),
            "sport": sports.normalize_sport(data.get("sport") or "table_tennis"),
            "sport_name": sports.short_name(data.get("sport") or "table_tennis"),
            "team1": data.get("team1", ""),
            "team2": data.get("team2", ""),
            "league": data.get("league", ""),
            "date": data.get("date", ""),
            "items": items,
            "wins": wins,
            "losses": losses,
            "pending": max(0, len(predictions) - len(results)),
        }

    def _attach_predictions(self, items):
        """Добавляет к матчам очереди их прогноз (для фильтра «Отправлены»)."""
        if not items:
            return items
        try:
            exact, by_teams = self._sent_index()
        except Exception as exc:
            core.events.add("ERROR", "Очередь: %s" % exc)
            return items
        for match in items:
            brief = exact.get((match.get("team1"), match.get("team2"), match.get("date")))
            if brief is None:
                brief = by_teams.get((match.get("team1"), match.get("team2")))
            if brief is not None:
                match["sent"] = True
                match["prediction"] = brief
        return items

    def refresh_queue(self):
        try:
            try:
                matches = self.predictor.get_live_matches()
            except TypeError:
                matches = self.predictor.get_live_matches(
                    self.settings.get_sport())
            items = []
            for match in matches:
                item_sport = sports.normalize_sport(
                    match.get("sport") or self.settings.get_sport())
                items.append({
                    "match_id": match["match_id"],
                    "sport": item_sport,
                    "sport_name": sports.short_name(item_sport),
                    "team1": match["team1"],
                    "team2": match["team2"],
                    "league": match["league"],
                    "date": match["date"],
                    "score": match["current_score"],
                    "started": match["is_started"],
                    "processed": self.predictor.is_processed(match["match_id"]),
                    "sent": self.predictor.telegram.is_prediction_sent(
                        match["team1"], match["team2"], match["date"],
                        item_sport),
                    "odds": {
                        "p1": match["odds"].get("match_p1"),
                        "p2": match["odds"].get("match_p2"),
                        "draw": match["odds"].get("match_draw"),
                        "total_line": match["odds"].get("total_line"),
                    },
                })
            self._attach_predictions(items)
            with self._lock:
                self._queue = items
                self._queue_ts = datetime.now().strftime("%H:%M:%S")
                self._queue_error = None
            core.events.add("INFO", "Очередь обновлена: %d матчей" % len(items))
            return self._json({"ok": True, "items": items, "ts": self._queue_ts})
        except Exception as exc:
            with self._lock:
                self._queue_error = str(exc)
            core.events.add("ERROR", "Очередь: %s" % exc)
            return self._json({"ok": False, "error": str(exc),
                               "items": self._attach_predictions(list(self._queue)),
                               "ts": self._queue_ts})

    def get_queue(self, sport=""):
        with self._lock:
            items = self._attach_predictions([dict(m) for m in self._queue])
            if sport:
                wanted = sports.normalize_sport(sport)
                items = [m for m in items if m.get("sport") == wanted]
            return self._json({
                "items": items,
                "ts": self._queue_ts,
                "error": self._queue_error,
                "total": len(items),
                "sport": self.settings.get_sport(),
                "upcoming": len([m for m in items if not m["started"]]),
            })

    def clear_processed(self):
        self.predictor.processed_matches = {}
        self.predictor.save_processed()
        core.events.add("WARNING", "История обработанных матчей очищена")
        return self._json({"ok": True})

    # ------------------------------------------------------------------ прогнозы/статистика
    def get_predictions(self, limit=200, sport=""):
        raw = self.predictor.telegram.snapshot_predictions()
        wanted = sports.normalize_sport(sport) if sport else ""
        items = []
        for pred_id, data in raw.items():
            item_sport = sports.normalize_sport(data.get("sport") or "table_tennis")
            if wanted and item_sport != wanted:
                continue
            results = data.get("set_results") or []
            predictions = data.get("predictions") or []
            wins = sum(1 for r in results if r.get("success"))
            losses = sum(1 for r in results if not r.get("success"))
            items.append({
                "id": pred_id,
                "sport": item_sport,
                "sport_name": sports.short_name(item_sport),
                "team1": data.get("team1"),
                "team2": data.get("team2"),
                "league": data.get("league", ""),
                "date": data.get("date", ""),
                "sent_at": data.get("sent_at", ""),
                "predictions": predictions,
                "results": results,
                "wins": wins,
                "losses": losses,
                "pending": max(0, len(predictions) - len(results)),
                "checked": bool(data.get("result_checked")),
                "message": data.get("message_text", ""),
            })
        items.sort(key=lambda x: str(x.get("sent_at", "")), reverse=True)
        return self._json({"items": items[:int(limit)], "total": len(items)})

    @staticmethod
    def _parse_stamp(value):
        """Разбирает дату из фильтра: 'YYYY-MM-DDTHH:MM' или 'YYYY-MM-DD'."""
        value = str(value or "").strip()
        if not value:
            return None
        formats = (
            ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%dT%H:%M", 16),
            ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16),
            ("%Y-%m-%d", 10), ("%d.%m.%Y %H:%M", 16), ("%d.%m.%Y", 10),
        )
        for fmt, size in formats:
            try:
                return datetime.strptime(value[:size], fmt)
            except Exception:
                continue
        return None

    def get_results(self, start="", end="", search="", status="all", limit=500,
                    sport=""):
        """История игр: прогноз, обоснование и результат. Фильтр по дате/времени."""
        start_dt = self._parse_stamp(start)
        end_dt = self._parse_stamp(end)
        if end_dt is not None and len(str(end).strip()) <= 10:
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        needle = str(search or "").strip().lower()
        status = (status or "all").lower()
        wanted = sports.normalize_sport(sport) if sport else ""
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 500
        rev = self.predictor.telegram.revision()
        cache_key = (rev, str(start or ""), str(end or ""), needle, status,
                     limit, wanted)
        cached = self._results_cache.get(cache_key)
        if cached is not None:
            return cached
        raw = self.predictor.telegram.snapshot_predictions()

        games = []
        for pred_id, data in raw.items():
            item_sport = sports.normalize_sport(data.get("sport") or "table_tennis")
            if wanted and item_sport != wanted:
                continue
            sent_dt = self._parse_stamp(data.get("sent_at", ""))
            if start_dt and (sent_dt is None or sent_dt < start_dt):
                continue
            if end_dt and (sent_dt is None or sent_dt > end_dt):
                continue

            team1, team2 = data.get("team1", ""), data.get("team2", "")
            if needle and needle not in ("%s %s" % (team1, team2)).lower() \
                    and needle not in str(data.get("league", "")).lower():
                continue

            results = data.get("set_results") or []
            rows = []
            for pred in data.get("predictions") or []:
                result = None
                for res in results:
                    if res.get("target") != pred.get("target"):
                        continue
                    if res.get("kind") and pred.get("kind") and \
                            res.get("kind") != pred.get("kind"):
                        continue
                    result = res
                    break
                confidence = pred.get("confidence_val")
                rows.append({
                    "target": pred.get("target", ""),
                    "kind": pred.get("kind", ""),
                    "label": pred.get("label", pred.get("target", "")),
                    "verdict": pred.get("verdict", ""),
                    "reason": pred.get("models_info", ""),
                    "confidence": round(float(confidence) * 100, 1)
                    if confidence is not None else None,
                    "agreement": round(float(pred.get("agreement", 0)) * 100, 1)
                    if pred.get("agreement") is not None else None,
                    "strong": pred.get("strong"),
                    "threshold": pred.get("threshold"),
                    "success": result.get("success") if result else None,
                    "score": (result or {}).get("score", ""),
                    "total": (result or {}).get("total"),
                    "checked_from": (result or {}).get("checked_from"),
                })

            # Мнение ИИ — отдельные строки, чтобы можно было честно
            # сравнить его с прогнозами правил и нейросети.
            ai_results = data.get("ai_results") or []
            for pred in data.get("ai_predictions") or []:
                result = None
                for res in ai_results:
                    if res.get("target") != pred.get("target"):
                        continue
                    if res.get("kind") and pred.get("kind") and \
                            res.get("kind") != pred.get("kind"):
                        continue
                    result = res
                    break
                confidence = pred.get("confidence_val")
                rows.append({
                    "target": pred.get("target", ""),
                    "kind": pred.get("kind", ""),
                    "label": "🤖 " + pred.get("label", pred.get("target", "")),
                    "verdict": pred.get("verdict", ""),
                    "reason": pred.get("models_info", ""),
                    "confidence": round(float(confidence) * 100, 1)
                    if confidence is not None else None,
                    "agreement": None,
                    "strong": None,
                    "threshold": pred.get("threshold"),
                    "success": result.get("success") if result else None,
                    "score": (result or {}).get("score", ""),
                    "total": (result or {}).get("total"),
                    "checked_from": (result or {}).get("checked_from"),
                    "source": "ai",
                })

            wins = sum(1 for r in rows if r["success"] is True)
            losses = sum(1 for r in rows if r["success"] is False)
            pending = len(rows) - wins - losses
            if status == "win" and not (wins > 0 and losses == 0):
                continue
            if status == "loss" and losses == 0:
                continue
            if status == "pending" and pending == 0:
                continue

            games.append({
                "id": pred_id,
                "sport": item_sport,
                "sport_name": sports.short_name(item_sport),
                "team1": team1,
                "team2": team2,
                "league": data.get("league", ""),
                "date": data.get("date", ""),
                "sent_at": data.get("sent_at", ""),
                "rows": rows,
                "wins": wins,
                "losses": losses,
                "pending": pending,
                "checked": bool(data.get("result_checked")),
                "from_cache": any(r.get("checked_from") == "cache"
                                  for r in rows),
                "final_score": (data.get("result") or {}).get("final_score", ""),
            })

        games.sort(key=lambda g: str(g.get("sent_at", "")), reverse=True)
        total_preds = sum(len(g["rows"]) for g in games)
        wins = sum(g["wins"] for g in games)
        losses = sum(g["losses"] for g in games)
        pending = sum(g["pending"] for g in games)
        finished = wins + losses
        ai_rows = [r for g in games for r in g["rows"]
                   if r.get("source") == "ai"]
        ai_wins = sum(1 for r in ai_rows if r.get("success") is True)
        ai_losses = sum(1 for r in ai_rows if r.get("success") is False)
        text = self._json({
            "items": games[:limit],
            "total": len(games),
            "summary": {
                "games": len(games),
                "preds": total_preds,
                "wins": wins,
                "losses": losses,
                "pending": pending,
                "hit_rate": round(wins / finished * 100, 1) if finished else 0.0,
                "ai_preds": len(ai_rows),
                "ai_wins": ai_wins,
                "ai_losses": ai_losses,
                "ai_pending": len(ai_rows) - ai_wins - ai_losses,
                "from_cache": sum(1 for g in games if g.get("from_cache")),
            },
        })
        # Держим только последние несколько вариантов фильтра.
        if len(self._results_cache) > 8:
            self._results_cache.clear()
        self._results_cache[cache_key] = text
        return text

    # ------------------------------------------------------------------ конструктор
    def get_constructor(self, sport=None):
        engine_ctor = self.predictor.constructor
        sport = sports.normalize_sport(sport or self.settings.get_sport())
        return self._json({
            "ok": True,
            "sport": sport,
            "sport_name": sports.name(sport),
            "mode": self.settings.get_algorithm_mode(),
            "rules": engine_ctor.snapshot(sport),
            "catalog": engine_ctor.catalog_payload(sport),
            "presets": engine_ctor.presets(sport),
            "stats": engine_ctor.stats_payload(sport),
            "file": engine_ctor._path_for(sport),
        })

    def save_constructor(self, payload, sport=None):
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
        except Exception as exc:
            return self._json({"ok": False, "errors": ["Некорректный JSON: %s" % exc]})
        if not isinstance(data, dict) and not isinstance(data, list):
            return self._json({"ok": False, "errors": ["Ожидался объект или список"]})

        if isinstance(data, dict) and data.get("mode") is not None:
            self.settings.set_algorithm_mode(data.get("mode"))
        payload_sport = data.get("sport") if isinstance(data, dict) else None
        sport = sports.normalize_sport(
            sport or payload_sport or self.settings.get_sport())

        engine_ctor = self.predictor.constructor
        try:
            ok, errors, rules = engine_ctor.save(data, sport)
        except Exception as exc:
            return self._json({"ok": False, "errors": [str(exc)]})
        if ok:
            core.events.add("INFO", "Конструктор (%s): сохранено правил — %d" % (
                sports.short_name(sport), len(rules)))
        else:
            core.events.add("ERROR", "Конструктор: %s" % "; ".join(errors[:3]))
        return self._json({
            "ok": bool(ok),
            "sport": sport,
            "errors": errors,
            "rules": rules,
            "mode": self.settings.get_algorithm_mode(),
            "stats": engine_ctor.stats_payload(sport),
        })

    def set_algorithm_mode(self, mode):
        value = "constructor" if str(mode).lower() == "constructor" else "builtin"
        self.settings.set_algorithm_mode(value)
        core.events.add("INFO", "Источник прогнозов: %s" % (
            "конструктор" if value == "constructor" else "встроенный алгоритм"))
        return self._json({"ok": True, "mode": value})

    def test_constructor(self, payload=None, limit=6, sport=None):
        """Прогоняет правила по текущей линии, ничего не отправляя."""
        sport = sports.normalize_sport(sport or self.settings.get_sport())
        rules = None
        if payload:
            try:
                data = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(data, dict):
                    rules = data.get("rules")
                    if data.get("sport"):
                        sport = sports.normalize_sport(data.get("sport"))
                elif isinstance(data, list):
                    rules = data
            except Exception:
                rules = None
        try:
            limit = max(1, min(12, int(limit)))
        except Exception:
            limit = 6

        engine_ctor = self.predictor.constructor
        try:
            try:
                matches = self.predictor.get_live_matches(sport)
            except TypeError:
                matches = self.predictor.get_live_matches()
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc), "items": []})

        upcoming = [m for m in matches
                    if not m.get("is_started") and m.get("stat_link")][:limit]
        items = []
        for match in upcoming:
            try:
                try:
                    stats = self.predictor.get_match_stats(
                        match["stat_link"], match["team1"], match["team2"], sport)
                except TypeError:
                    stats = self.predictor.get_match_stats(
                        match["stat_link"], match["team1"], match["team2"])
            except Exception:
                stats = {}
            stats["league"] = match.get("league", "")
            stats["sport"] = sport
            predictions, fired, skip = engine_ctor.evaluate(match, stats, rules=rules)
            items.append({
                "team1": match["team1"],
                "team2": match["team2"],
                "league": match.get("league", ""),
                "date": match.get("date", ""),
                "start_time": match.get("start_time", ""),
                "h2h": len(stats.get("h2h_matches") or []),
                "recent1": len((stats.get("recent") or {}).get("team1") or []),
                "recent2": len((stats.get("recent") or {}).get("team2") or []),
                "fired": fired,
                "skip": skip,
                "predictions": [{
                    "label": p["label"],
                    "verdict": p["verdict"],
                    "confidence": round(p["confidence_val"] * 100, 1),
                    "reason": p["models_info"],
                } for p in predictions],
            })
        core.events.add("INFO", "Тест конструктора: проверено матчей — %d" % len(items))
        return self._json({"ok": True, "checked": len(items), "items": items})

    # ------------------------------------------------------------------ анализатор
    def _rules_for_sports(self, selected):
        result = {}
        for sport in selected:
            try:
                result[sport] = self.predictor.constructor.snapshot(sport)
            except Exception:
                result[sport] = []
        return result

    @staticmethod
    def _rules_signature(rules_by_sport):
        payload = {}
        for sport, rules in (rules_by_sport or {}).items():
            items = []
            for rule in rules or []:
                items.append([
                    rule.get("id"), bool(rule.get("enabled", True)),
                    rule.get("priority"), rule.get("conditions"),
                    rule.get("action"), rule.get("auto_kind"),
                    rule.get("auto_target"), bool(rule.get("auto")),
                ])
            payload[sport] = items
        try:
            raw = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                             default=str).encode("utf-8")
            return hashlib.sha1(raw).hexdigest()
        except Exception:
            return str(len(payload))

    def _save_advisor_state(self):
        try:
            rule_advisor.save_state(self._advisor_path, self._advisor_state)
        except Exception:
            pass

    def _remember_recommendations(self, payload):
        """Запоминает открытые рекомендации для применения одной кнопкой."""
        info = (payload or {}).get("recommendations") or {}
        records = {}
        for rec in info.get("recommendations") or []:
            if isinstance(rec, dict) and rec.get("id"):
                records[str(rec["id"])] = json.loads(
                    json.dumps(rec, ensure_ascii=False, default=str))
        with self._advisor_lock:
            self._advisor_recs = records
            self._advisor_last = {
                "options": (payload or {}).get("options") or {},
                "counts": info.get("counts") or {},
                "total": info.get("total") or 0,
                "new_count": info.get("new_count") or 0,
                "hint": info.get("hint") or "",
                "updated_at": info.get("updated_at") or "",
                "resolved": info.get("resolved") or [],
            }

    def _cached_payload(self, cached):
        """Копия кэша с актуальными пометками «новое»."""
        payload = json.loads(json.dumps(cached, ensure_ascii=False, default=str))
        info = payload.get("recommendations") or {}
        seen = (self._advisor_state or {}).get("seen") or {}
        new_count = 0
        for rec in info.get("recommendations") or []:
            # Первый расчёт уже записал рекомендации в seen. Поэтому при
            # повторной выдаче из кэша они не считаются новыми.
            rec["is_new"] = False
        info["new_count"] = new_count
        info["resolved"] = []
        info["state"] = {
            "seen": len(seen),
            "applied": len((self._advisor_state or {}).get("applied") or {}),
            "resolved": len((self._advisor_state or {}).get("resolved") or {}),
            "dismissed": len((self._advisor_state or {}).get("dismissed") or {}),
        }
        return payload

    @staticmethod
    def _analyzer_error(error, online=False):
        return {
            "ok": False, "error": str(error), "failure": [], "success": [],
            "combos": {"failure": [], "success": []}, "means": [],
            "observations": {"total": 0, "wins": 0, "losses": 0,
                             "with_stats": 0},
            "rule_reviews": {"ok": False, "reviews": [], "total": 0},
            "recommendations": {
                "ok": False, "error": str(error), "recommendations": [],
                "resolved": [], "counts": {}, "total": 0, "new_count": 0,
                "hint": "", "state": {},
            },
            "online": bool(online),
        }

    def get_analyzer(self, payload=None):
        """Анализ истории по выбранным видам + рекомендации по правилам.

        Фильтр ``sports`` (список) — новый формат; ``sport`` (строка)
        поддержан для старых клиентов и тестов. Пустой список означает
        активный вид, ``all`` — все виды.
        """
        options = {}
        if payload:
            try:
                data = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(data, dict):
                    options = data
            except Exception:
                options = {}
        active_sport = self.settings.get_sport()
        filters = analysis_service.parse_options(options, active_sport)
        selected = filters["sports"]
        rules_by_sport = self._rules_for_sports(selected)
        cfg = self._auto_cfg()
        online_cfg = online_client.config(self.settings.snapshot())
        online_error = ""

        # Онлайн-режим: тот же расчёт, но на сайте. При ошибке — локальный
        # fallback, чтобы экран анализа не оставался пустым без сети.
        if online_client.enabled(self.settings.snapshot()):
            try:
                raw = self.predictor.telegram.snapshot_predictions()
                remote = online_client.analyze(
                    self.settings.snapshot(), filters, raw, rules_by_sport,
                    auto_cfg=cfg, advisor_state=self._advisor_state)
                state = remote.pop("advisor_state", None)
                if isinstance(state, dict):
                    with self._advisor_lock:
                        self._advisor_state = rule_advisor.normalize_state(state)
                    self._save_advisor_state()
                remote["online"] = True
                remote["server_version"] = remote.get(
                    "server_version") or remote.get("version") or ""
                remote.setdefault("auto_rules", {
                    "enabled": bool(cfg.get("enabled")),
                    "min_precision": cfg.get("min_precision"),
                    "min_samples": cfg.get("min_samples")})
                remote["revision"] = self.predictor.analysis_revision()
                self._online_last = {
                    "at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                    "ok": True,
                    "latency_ms": remote.get("latency_ms") or 0,
                    "url": online_cfg.get("base_url") or "",
                    "error": "",
                }
                self._remember_recommendations(remote)
                return self._json(remote)
            except Exception as exc:
                online_error = str(exc)
                self._online_last = {
                    "at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                    "ok": False,
                    "latency_ms": 0,
                    "url": online_cfg.get("base_url") or "",
                    "error": online_error,
                }
                core.events.add("WARNING", "Онлайн-анализ: %s" % online_error)
                if not online_cfg.get("fallback_local", True):
                    result = self._analyzer_error(online_error, online=True)
                    result["online_error"] = online_error
                    return self._json(result)

        raw = self.predictor.telegram.snapshot_predictions()
        try:
            revision = self.predictor.telegram.revision()
        except Exception:
            revision = len(raw)
        key = (
            revision, tuple(selected), filters["kind"], filters["target"],
            filters["min_group"], filters["min_lift"], filters["min_hits"],
            filters["limit"], bool(filters["pairs"]),
            self._rules_signature(rules_by_sport),
        )
        cached = self._analyzer_cache.get(key)
        if cached is not None:
            payload = self._cached_payload(cached)
            payload["online"] = False
            payload["revision"] = self.predictor.analysis_revision()
            if online_error:
                payload["online_error"] = online_error
            self._remember_recommendations(payload)
            return self._json(payload)

        try:
            built = analysis_service.build_report(
                raw, filters, rules_by_sport=rules_by_sport, auto_cfg=cfg,
                advisor_state=self._advisor_state, active_sport=active_sport)
            state = built.get("advisor_state")
            if isinstance(state, dict):
                with self._advisor_lock:
                    self._advisor_state = state
                self._save_advisor_state()
            result = built.get("payload") or {}
            result["online"] = False
            result["version"] = APP_VERSION
            result["revision"] = self.predictor.analysis_revision()
            if online_error:
                result["online_error"] = online_error
            self._remember_recommendations(result)
            self._analyzer_cache[key] = json.loads(
                json.dumps(result, ensure_ascii=False, default=str))
            # Кэш не должен расти: храним последние четыре варианта фильтра.
            while len(self._analyzer_cache) > 4:
                self._analyzer_cache.pop(next(iter(self._analyzer_cache)))
            return self._json(result)
        except Exception as exc:
            core.events.add("ERROR", "Анализ истории: %s" % exc)
            result = self._analyzer_error(exc)
            result["version"] = APP_VERSION
            result["online"] = False
            result["revision"] = self.predictor.analysis_revision()
            if online_error:
                result["online_error"] = online_error
            return self._json(result)

    # ---------------------------------------------------------- рекомендации
    def _current_rule(self, sport, rule_id):
        try:
            for rule in self.predictor.constructor.snapshot(sport):
                if str(rule.get("id") or "") == str(rule_id or ""):
                    return rule
        except Exception:
            pass
        return None

    def _apply_rec_to_rule(self, rule, rec):
        """Применяет patch рекомендации к актуальной версии правила."""
        rec_type = str(rec.get("type") or "")
        next_rule = json.loads(json.dumps(rule, ensure_ascii=False,
                                          default=str))
        group = next_rule.get("conditions")
        if not isinstance(group, dict) or "metric" in group:
            group = {"logic": "and", "conditions": []}
        conditions = group.get("conditions")
        if not isinstance(conditions, list):
            conditions = []
        group["conditions"] = conditions
        next_rule["conditions"] = group

        if rec_type in ("add_condition", "add_odds_floor"):
            condition = rec.get("condition")
            if not isinstance(condition, dict):
                return None, "В рекомендации нет условия."
            if str(group.get("logic") or "and").lower() != "and":
                return None, ("Правило использует логику «ИЛИ»: добавление "
                              "условия расширит его. Измените правило вручную.")
            if rule_advisor._contains(group, condition):
                return rule, "Условие уже есть"
            conditions.append(json.loads(json.dumps(condition,
                                                     ensure_ascii=False)))
        elif rec_type == "remove_condition":
            condition = rec.get("condition")
            key = rule_advisor.condition_key(condition)
            conditions[:] = [item for item in conditions
                             if rule_advisor.condition_key(item) != key]
            group["conditions"] = conditions
        elif rec_type == "disable_rule":
            next_rule["enabled"] = False
        elif rec_type == "adjust_confidence":
            patch = rec.get("patch") or {}
            action = patch.get("action")
            if not isinstance(action, dict):
                return None, "В рекомендации нет нового действия."
            next_rule["action"] = action
        else:
            # Универсальный путь: принимаем готовую группу условий.
            patch = rec.get("patch") or {}
            if isinstance(patch.get("conditions"), dict):
                next_rule["conditions"] = patch["conditions"]
            elif patch.get("enabled") is not None:
                next_rule["enabled"] = bool(patch.get("enabled"))
            else:
                return None, "Неизвестный тип рекомендации."
        return next_rule, ""

    def advisor(self, payload=None):
        """API рекомендаций: status / apply / dismiss / reset / refresh."""
        options = {}
        try:
            if isinstance(payload, str) and payload.strip():
                data = json.loads(payload)
                if isinstance(data, dict):
                    options = data
            elif isinstance(payload, dict):
                options = payload
        except Exception as exc:
            return self._json({"ok": False,
                               "error": "Некорректный JSON: %s" % exc})
        action = str(options.get("action") or "status").strip().lower()
        rec_id = str(options.get("id") or options.get("rec_id") or "")

        with self._advisor_lock:
            rec = json.loads(json.dumps(
                self._advisor_recs.get(rec_id) or {}, ensure_ascii=False))
        if action in ("apply", "accept", "add"):
            if not rec:
                return self._json({
                    "ok": False, "error": "Рекомендация устарела — "
                                          "обновите анализ.",
                    "code": "stale"})
            sport = str(rec.get("sport") or "")
            rule = self._current_rule(sport, rec.get("rule_id"))
            if rule is None:
                return self._json({"ok": False, "code": "rule_missing",
                                   "error": "Правило не найдено — возможно, "
                                            "оно удалено."})
            done, reason = rule_advisor._is_resolved(rec, rule)
            if done:
                with self._advisor_lock:
                    self._advisor_state = rule_advisor.mark_applied(
                        self._advisor_state, rec, reason)
                self._save_advisor_state()
                self._analyzer_cache.clear()
                return self._json({"ok": True, "already": True,
                                   "message": reason, "id": rec_id})
            next_rule, error = self._apply_rec_to_rule(rule, rec)
            if next_rule is None:
                return self._json({"ok": False, "error": error,
                                   "code": "patch_failed"})
            rules = self.predictor.constructor.snapshot(sport)
            updated = []
            for item in rules:
                if str(item.get("id") or "") == str(rec.get("rule_id") or ""):
                    updated.append(next_rule)
                else:
                    updated.append(item)
            ok, errors, saved = self.predictor.constructor.save(
                {"rules": updated, "sport": sport}, sport)
            if not ok:
                return self._json({
                    "ok": False, "error": (errors[0] if errors else
                                           "Не удалось сохранить правило"),
                    "errors": errors})
            with self._advisor_lock:
                self._advisor_state = rule_advisor.mark_applied(
                    self._advisor_state, rec, "Применено в приложении")
            self._save_advisor_state()
            self._analyzer_cache.clear()
            self._auto_signature.pop(sport, None)
            message = "Рекомендация применена: правило «%s» обновлено." % \
                (rec.get("rule_name") or "")
            core.events.add("INFO", "Анализ: %s" % message)
            return self._json({
                "ok": True, "applied": True, "id": rec_id,
                "sport": sport, "rule_id": rec.get("rule_id"),
                "message": message, "rules": saved,
            })

        if action in ("dismiss", "hide", "skip"):
            if not rec_id:
                return self._json({"ok": False, "error": "Не указан id."})
            with self._advisor_lock:
                self._advisor_state = rule_advisor.dismiss(
                    self._advisor_state, rec_id)
            self._save_advisor_state()
            self._analyzer_cache.clear()
            return self._json({"ok": True, "dismissed": True, "id": rec_id,
                               "message": "Рекомендация скрыта на 7 дней."})

        if action in ("reset", "clear"):
            with self._advisor_lock:
                self._advisor_state = rule_advisor.empty_state()
            self._save_advisor_state()
            self._analyzer_cache.clear()
            return self._json({"ok": True, "message": "Состояние рекомендаций "
                                                     "сброшено."})

        if action in ("refresh", "run"):
            # Пересчитать с текущими фильтрами. UI обычно просто вызывает
            # analyzer, но отдельный action удобен для тестов и автоматики.
            return self.get_analyzer(options.get("filter") or options)

        with self._advisor_lock:
            last = dict(self._advisor_last)
            records = [json.loads(json.dumps(item, ensure_ascii=False))
                       for item in self._advisor_recs.values()]
        return self._json({
            "ok": True,
            "recommendations": records,
            "total": len(records),
            "counts": last.get("counts") or {},
            "new_count": last.get("new_count") or 0,
            "hint": last.get("hint") or "",
            "updated_at": last.get("updated_at") or "",
            "state": {
                "seen": len((self._advisor_state or {}).get("seen") or {}),
                "applied": len((self._advisor_state or {}).get("applied") or {}),
                "resolved": len((self._advisor_state or {}).get("resolved") or {}),
                "dismissed": len((self._advisor_state or {}).get("dismissed") or {}),
            },
        })

    # ------------------------------------------- синхронизация с веб-кабинетом
    def _sync_status(self):
        current = self.settings.snapshot().get("online") or {}
        cfg = online_client.config(self.settings.snapshot())
        try:
            interval = max(5, min(720, int(
                current.get("sync_interval_min") or 15)))
        except (TypeError, ValueError):
            interval = 15
        device = self._device_info()
        return {
            "enabled": bool(current.get("sync_enabled", True)),
            "interval_min": interval,
            "base_url": cfg.get("base_url") or "",
            "last_sync": current.get("last_sync") or "",
            "last_error": current.get("last_sync_error") or "",
            "last_summary": current.get("last_sync_summary") or "",
            "device_id": device.get("id") or "",
            "device_name": device.get("name") or "",
        }

    def _device_info(self):
        """Идентификатор и имя устройства; создаётся один раз."""
        snapshot = self.settings.snapshot()
        info = online_client.device_info(snapshot, APP_VERSION)
        if self._device_cache and self._device_cache.get("id"):
            info["id"] = self._device_cache["id"]
            info["name"] = self._device_cache.get("name") or info["name"]
        stored = snapshot.get("device") if isinstance(
            snapshot.get("device"), dict) else {}
        patch = {}
        if info.get("id") and str(stored.get("id") or "") != info["id"]:
            patch["id"] = info["id"]
        if info.get("name") and str(stored.get("name") or "") != info["name"]:
            patch["name"] = info["name"]
        if patch:
            try:
                self.settings.update({"device": patch})
            except Exception:
                pass
        self._device_cache = dict(info)
        return info

    def _sync_due(self):
        current = self.settings.snapshot().get("online") or {}
        if not bool(current.get("sync_enabled", True)):
            return False
        try:
            interval = max(5, min(720, int(
                current.get("sync_interval_min") or 15)))
        except (TypeError, ValueError):
            interval = 15
        return (time.time() - float(self._sync_last_ts or 0)) >= interval * 60

    def _push_history(self, force=False):
        """Отправляет снимок истории и правил в веб-кабинет."""
        snapshot = self.settings.snapshot()
        current = snapshot.get("online") or {}
        if not force and not bool(current.get("sync_enabled", True)):
            return {"ok": True, "skipped": "синхронизация выключена"}
        if not force and not self._sync_due():
            return {"ok": True, "skipped": "ещё не время"}
        with self._sync_lock:
            if not force and not self._sync_due():
                return {"ok": True, "skipped": "ещё не время"}
            try:
                raw = self.predictor.telegram.snapshot_predictions()
                rules = self._rules_for_sports(list(sports.SPORT_ORDER))
                device = self._device_info()
                result = online_client.sync(
                    snapshot, raw, rules,
                    advisor_state=self._advisor_state,
                    device=device, app_version=APP_VERSION,
                    meta={"model": device.get("model") or "",
                          "platform": device.get("platform") or ""})
                synced = result.get("synced") or {}
                rules_info = synced.get("rules") or {}
                parts = []
                if synced.get("predictions"):
                    parts.append("прогнозов: %d" % int(synced["predictions"]))
                if rules_info.get("created"):
                    parts.append("новых правил: %d" % rules_info["created"])
                if rules_info.get("updated"):
                    parts.append("изменено правил: %d" % rules_info["updated"])
                if rules_info.get("deleted"):
                    parts.append("удалено правил: %d" % rules_info["deleted"])
                summary = ", ".join(parts) or "без изменений"
                stamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                self.settings.update({"online": {
                    "last_sync": stamp,
                    "last_sync_error": "",
                    "last_sync_summary": summary,
                }})
                self._sync_last_ts = time.time()
                core.events.add("INFO", "История отправлена на сайт: %s" % summary)
                return {
                    "ok": True,
                    "device": result.get("device") or device,
                    "synced": synced,
                    "message": summary,
                    "server_version": result.get("server_version") or "",
                    "server_time": result.get("server_time") or "",
                }
            except Exception as exc:
                message = str(exc)
                # Не повторяем попытку каждый цикл: иначе при недоступном
                # сайте движок будет ждать таймаут бесконечно часто.
                self._sync_last_ts = time.time()
                self.settings.update({"online": {"last_sync_error": message}})
                core.events.add("WARNING", "Отправка истории: %s" % message)
                return {"ok": False, "error": message}

    def sync_history(self, payload=None):
        """API синхронизации: status / now / configure."""
        options = {}
        try:
            if isinstance(payload, str) and payload.strip():
                data = json.loads(payload)
                if isinstance(data, dict):
                    options = data
            elif isinstance(payload, dict):
                options = payload
        except Exception as exc:
            return self._json({"ok": False,
                               "error": "Некорректный JSON: %s" % exc})
        action = str(options.get("action") or "status").strip().lower()
        if action in ("configure", "save"):
            patch = {}
            for key in ("sync_enabled", "sync_interval_min"):
                if key in options:
                    patch[key] = options.get(key)
            if "sync_interval_min" in patch:
                try:
                    patch["sync_interval_min"] = max(
                        5, min(720, int(patch["sync_interval_min"])))
                except (TypeError, ValueError):
                    patch["sync_interval_min"] = 15
            if patch:
                self.settings.update({"online": patch})
                if patch.get("sync_enabled"):
                    self._sync_last_ts = 0.0
            return self._json({"ok": True, "sync": self._sync_status()})
        if action in ("now", "run", "push", "sync"):
            result = self._push_history(force=True)
            status = self._sync_status()
            result["sync"] = status
            return self._json(result)
        status = self._sync_status()
        status.update({"ok": True})
        return self._json(status)

    # --------------------------------------------------------------- онлайн
    def online(self, payload=None):
        """API онлайн-режима: status / test / configure."""
        options = {}
        try:
            if isinstance(payload, str) and payload.strip():
                data = json.loads(payload)
                if isinstance(data, dict):
                    options = data
            elif isinstance(payload, dict):
                options = payload
        except Exception as exc:
            return self._json({"ok": False,
                               "error": "Некорректный JSON: %s" % exc})
        action = str(options.get("action") or "status").strip().lower()
        snapshot = self.settings.snapshot()
        cfg = online_client.config(snapshot, options)

        if action in ("test", "ping", "check"):
            result = online_client.ping(snapshot, options)
            patch = {"last_ok": "", "last_error": ""}
            if result.get("ok"):
                patch["last_ok"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            else:
                patch["last_error"] = str(result.get("error") or "")
            self.settings.update({"online": patch})
            if result.get("ok"):
                core.events.add("INFO", "Онлайн-сайт доступен: %s" % cfg.get(
                    "base_url"))
            else:
                core.events.add("WARNING", "Онлайн-сайт: %s" %
                                result.get("error"))
            return self._json(result)

        if action in ("configure", "save"):
            patch = {}
            for key in ("enabled", "base_url", "token", "timeout",
                        "fallback_local", "verify_ssl"):
                if key in options:
                    patch[key] = options.get(key)
            if patch:
                self.settings.update({"online": patch})
                self._analyzer_cache.clear()
            return self._json({"ok": True,
                               "online": self.settings.snapshot().get("online")})

        # status
        current = self.settings.snapshot().get("online") or {}
        return self._json({
            "ok": True,
            "enabled": bool(current.get("enabled")),
            "configured": bool(str(current.get("base_url") or "").strip()),
            "base_url": current.get("base_url") or "",
            "token_set": bool(current.get("token")),
            "timeout": current.get("timeout") or 25,
            "fallback_local": current.get("fallback_local", True) is not False,
            "verify_ssl": current.get("verify_ssl", True) is not False,
            "last_ok": current.get("last_ok") or "",
            "last_error": current.get("last_error") or "",
            "last_remote": dict(self._online_last),
            "sync": self._sync_status(),
        })

    def get_stats(self):
        return self._json(self.predictor.telegram.stats_payload())

    def reset_stats(self):
        self.predictor.reset_stats()
        core.events.add("WARNING", "Счётчики сессии сброшены")
        return self._json({"ok": True})

    # ------------------------------------------------------------------ сервис
    def test_connection(self):
        result = {"betcity": False, "telegram": None, "matches": 0, "error": None}
        try:
            matches = self.predictor.get_live_matches()
            result["betcity"] = True
            result["matches"] = len(matches)
        except Exception as exc:
            result["error"] = str(exc)

        cfg = self.settings.get_telegram()
        if cfg.get("token") and cfg.get("chat_id"):
            try:
                import requests as _requests
                url = "https://api.telegram.org/bot%s/getMe" % cfg["token"]
                resp = _requests.get(url, timeout=10)
                result["telegram"] = resp.status_code == 200
            except Exception:
                result["telegram"] = False
        else:
            result["telegram"] = None

        core.events.add("INFO", "Проверка связи: Betcity=%s, матчей=%d, Telegram=%s" % (
            result["betcity"], result["matches"], result["telegram"]))
        return self._json(result)

    # ------------------------------------------------------------------ экспорт
    def export_data(self, kind="stats"):
        """Возвращает {filename, mime, content} для сохранения/отправки."""
        kind = (kind or "stats").lower()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if kind == "csv":
            content = ""
            try:
                if os.path.exists(core.LOG_CSV_FILE):
                    with open(core.LOG_CSV_FILE, "r", encoding="utf-8") as f:
                        content = f.read()
            except Exception as exc:
                return self._json({"ok": False, "error": str(exc)})
            return self._json({"ok": True, "filename": "bets_%s.csv" % stamp,
                               "mime": "text/csv", "content": content})

        if kind == "predictions":
            with self.predictor.telegram._lock:
                content = json.dumps(self.predictor.telegram.sent_predictions,
                                     ensure_ascii=False, indent=2)
            return self._json({"ok": True, "filename": "predictions_%s.json" % stamp,
                               "mime": "application/json", "content": content})

        if kind == "logs":
            items = core.events.all(limit=5000)
            content = "\n".join("%s %-7s %s" % (e.get("ts_full"), e.get("level"),
                                                e.get("message")) for e in items)
            return self._json({"ok": True, "filename": "logs_%s.txt" % stamp,
                               "mime": "text/plain", "content": content})

        if kind == "settings":
            content = json.dumps(self.settings.snapshot(), ensure_ascii=False, indent=2)
            return self._json({"ok": True, "filename": "settings_%s.json" % stamp,
                               "mime": "application/json", "content": content})

        if kind == "constructor":
            sport = self.settings.get_sport()
            rules = self.predictor.constructor.snapshot(sport)
            for rule in rules:
                rule.pop("summary", None)
                rule.pop("conditions_text", None)
                rule.pop("action_text", None)
                rule.pop("index", None)
            content = json.dumps({"version": 2, "sport": sport, "rules": rules},
                                 ensure_ascii=False, indent=2)
            return self._json({"ok": True,
                               "filename": "constructor_%s_%s.json" % (sport, stamp),
                               "mime": "application/json", "content": content})

        if kind == "analyzer":
            data = json.loads(self.get_analyzer())
            content = json.dumps(data, ensure_ascii=False, indent=2)
            return self._json({"ok": True, "filename": "analyzer_%s.json" % stamp,
                               "mime": "application/json", "content": content})

        if kind == "results":
            data = json.loads(self.get_results(limit=100000))
            lines = ["дата;матч;лига;партия;прогноз;уверенность;обоснование;результат;счёт;тотал"]
            for game in data.get("items", []):
                sent_stamp = str(game.get("sent_at", "")).replace("T", " ")[:16]
                for row in game.get("rows", []):
                    if row.get("success") is True:
                        outcome = "зашла"
                    elif row.get("success") is False:
                        outcome = "не зашла"
                    else:
                        outcome = "ожидает"
                    lines.append(";".join(str(v).replace(";", ",") for v in (
                        sent_stamp,
                        "%s - %s" % (game.get("team1", ""), game.get("team2", "")),
                        game.get("league", ""),
                        row.get("label", ""),
                        row.get("verdict", ""),
                        "" if row.get("confidence") is None else row["confidence"],
                        row.get("reason", ""),
                        outcome,
                        row.get("score", ""),
                        "" if row.get("total") is None else row["total"],
                    )))
            return self._json({"ok": True, "filename": "results_%s.csv" % stamp,
                               "mime": "text/csv", "content": "\r\n".join(lines)})

        if kind == "report":
            payload = self.predictor.telegram.stats_payload()
            lines = ["ОТЧЁТ %s" % datetime.now().strftime("%d.%m.%Y %H:%M"), ""]
            totals = payload["total"]
            lines.append("Всего прогнозов: %d" % totals["preds"])
            lines.append("Успешных: %d" % totals["wins"])
            lines.append("Неудачных: %d" % totals["losses"])
            lines.append("Ожидают: %d" % totals["pending"])
            lines.append("Hit rate: %.1f%%" % payload["hit_rate"])
            lines.append("")
            lines.append("Сегодня: %d прогнозов" % payload["today"]["preds"])
            lines.append("  ✅ %d  ❌ %d  ⏳ %d" % (
                payload["today"]["wins"], payload["today"]["losses"],
                payload["today"]["pending"]))
            lines.append("")
            lines.append("По видам ставок:")
            for row in payload["by_target"]:
                lines.append("  %-16s %3d  ✅%d ❌%d  %.0f%%" % (
                    row["key"], row["total"], row["wins"],
                    row["losses"], row["hit_rate"]))
            content = "\n".join(lines)
            return self._json({"ok": True, "filename": "report_%s.txt" % stamp,
                               "mime": "text/plain", "content": content})

        # stats — сводный JSON
        content = json.dumps({
            "generated_at": datetime.now().isoformat(),
            "stats": self.predictor.telegram.stats_payload(),
            "session": self.predictor.stats,
            "queue": self._queue,
        }, ensure_ascii=False, indent=2)
        return self._json({"ok": True, "filename": "stats_%s.json" % stamp,
                           "mime": "application/json", "content": content})

    # ------------------------------------------------------------------ очистка
    def clear_data(self, what="all"):
        what = (what or "all").lower()
        done = []
        try:
            if what in ("all", "logs"):
                core.events.clear()
                done.append("logs")
            if what in ("all", "csv"):
                self.predictor.bets_logger.clear()
                done.append("csv")
            if what in ("all", "predictions"):
                with self.predictor.telegram._lock:
                    self.predictor.telegram.sent_predictions = {}
                self.predictor.telegram.save_sent_predictions()
                done.append("predictions")
            if what in ("all", "processed"):
                self.predictor.processed_matches = {}
                self.predictor.save_processed()
                done.append("processed")
            if what in ("all", "constructor"):
                self.predictor.constructor.save({"rules": []})
                done.append("constructor")
            if what in ("all", "neural"):
                self.predictor.nn.reset(clear_samples=True)
                done.append("neural")
            core.events.add("WARNING", "Очищено: %s" % ", ".join(done))
            return self._json({"ok": True, "cleared": done})
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)})


_engine = None
_engine_lock = threading.Lock()


def engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = Engine()
        return _engine


# ---------------------------------------------------------------- публичное API
# Kotlin вызывает эти функции через Chaquopy. Возвращают JSON-строки.

def api_state():
    return engine().get_state()


def api_start():
    return engine().start()


def api_stop():
    return engine().stop()


def api_run_once():
    return engine().run_once()


def api_settings():
    return engine().get_settings()


def api_save_settings(payload):
    return engine().save_settings(payload)


def api_reset_settings():
    return engine().reset_settings()


def api_set_sport(sport):
    return engine().set_sport(sport)


def api_logs(since_id=0, limit=500, level="", search=""):
    return engine().get_logs(since_id, limit, level, search)


def api_clear_logs():
    return engine().clear_logs()


def api_errors(limit=200):
    return engine().get_errors(limit)


def api_queue():
    return engine().get_queue()


def api_refresh_queue():
    return engine().refresh_queue()


def api_predictions(limit=200, sport=""):
    return engine().get_predictions(limit, sport)


def api_results(start="", end="", search="", status="all", limit=500,
                sport=""):
    return engine().get_results(start, end, search, status, limit, sport)


def api_constructor(sport=None):
    return engine().get_constructor(sport)


def api_save_constructor(payload):
    return engine().save_constructor(payload)


def api_set_algorithm_mode(mode):
    return engine().set_algorithm_mode(mode)


def api_test_constructor(payload=None, limit=6, sport=None):
    return engine().test_constructor(payload, limit, sport)


def api_analyzer(payload=None):
    return engine().get_analyzer(payload)


def api_auto_rules(payload=None):
    return engine().auto_rules(payload)


def api_advisor(payload=None):
    return engine().advisor(payload)


def api_online(payload=None):
    return engine().online(payload)


def api_sync_history(payload=None):
    return engine().sync_history(payload)


def api_neural(payload=None):
    return engine().neural(payload)


def api_ai(payload=None):
    return engine().ai(payload)


def api_stats():
    return engine().get_stats()


def api_reset_stats():
    return engine().reset_stats()


def api_clear_processed():
    return engine().clear_processed()


def api_test_connection():
    return engine().test_connection()


def api_export(kind="stats"):
    return engine().export_data(kind)


def api_clear_data(what="all"):
    return engine().clear_data(what)


def api_version():
    return json.dumps({
        "version": APP_VERSION,
        "data_dir": core.DATA_DIR,
        "python": "ok",
    }, ensure_ascii=False)


def api_autostart():
    """Поднимает движок после перезапуска сервиса, если он был запущен."""
    eng = engine()
    try:
        if eng.settings.is_running() and not eng.is_running():
            eng.start()
        return eng.get_state()
    except Exception as exc:
        core.events.add("ERROR", "Автозапуск: %s" % exc)
        return eng.get_state()

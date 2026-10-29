"""API-слой между Android-приложением и движком прогнозирования.

Все функции возвращают JSON-строки (их читает Kotlin/JS).
Потокобезопасность: движок работает в отдельном потоке, состояние
читается через блокировки.
"""

from __future__ import annotations

import csv
import io
import json
import os
import threading
import time
from datetime import datetime

import predictor_core as core
import analyzer

APP_VERSION = "1.4.0"


class Engine:
    def __init__(self):
        self.settings = core.BotSettings()
        self.predictor = core.PredictorEnsemble(settings=self.settings)
        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self._queue = []
        self._queue_ts = None
        self._queue_error = None
        self._cycles = 0
        self._started_at = None
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
        core.events.add("INFO", "Движок запущен (интервал %d с)" %
                        self.settings.get_poll_interval())
        return self._json({"ok": True, "running": True})

    def stop(self):
        with self._lock:
            self.settings.set_running(False)
            self._stop.set()
            thread = self._thread
            self._thread = None
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
        core.events.add("INFO", "Ручная проверка: матчей %d, сигналов %d" % (
            summary.get("matches", 0), summary.get("signals", 0)))
        return self._json({"ok": True, "summary": summary})

    # ------------------------------------------------------------------ состояние
    def get_state(self):
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
        })
        return self._json(status)

    # ------------------------------------------------------------------ настройки
    def get_settings(self):
        return self._json({
            "settings": self.settings.snapshot(),
            "defaults": self.settings.DEFAULTS,
        })

    def save_settings(self, payload):
        try:
            patch = json.loads(payload) if isinstance(payload, str) else payload
        except Exception as exc:
            return self._json({"ok": False, "error": "Некорректный JSON: %s" % exc})
        if not isinstance(patch, dict):
            return self._json({"ok": False, "error": "Ожидался объект"})
        ok = self.settings.update(patch)
        self._apply_engine_params()
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
        with self.predictor.telegram._lock:
            raw = json.loads(json.dumps(self.predictor.telegram.sent_predictions))
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
            matches = self.predictor.get_live_matches()
            items = []
            for match in matches:
                items.append({
                    "match_id": match["match_id"],
                    "team1": match["team1"],
                    "team2": match["team2"],
                    "league": match["league"],
                    "date": match["date"],
                    "score": match["current_score"],
                    "started": match["is_started"],
                    "processed": self.predictor.is_processed(match["match_id"]),
                    "sent": self.predictor.telegram.is_prediction_sent(
                        match["team1"], match["team2"], match["date"]),
                    "odds": {
                        "p1": match["odds"].get("match_p1"),
                        "p2": match["odds"].get("match_p2"),
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

    def get_queue(self):
        with self._lock:
            items = self._attach_predictions([dict(m) for m in self._queue])
            return self._json({
                "items": items,
                "ts": self._queue_ts,
                "error": self._queue_error,
                "total": len(items),
                "upcoming": len([m for m in items if not m["started"]]),
            })

    def clear_processed(self):
        self.predictor.processed_matches = {}
        self.predictor.save_processed()
        core.events.add("WARNING", "История обработанных матчей очищена")
        return self._json({"ok": True})

    # ------------------------------------------------------------------ прогнозы/статистика
    def get_predictions(self, limit=200):
        with self.predictor.telegram._lock:
            raw = json.loads(json.dumps(self.predictor.telegram.sent_predictions))
        items = []
        for pred_id, data in raw.items():
            results = data.get("set_results") or []
            predictions = data.get("predictions") or []
            wins = sum(1 for r in results if r.get("success"))
            losses = sum(1 for r in results if not r.get("success"))
            items.append({
                "id": pred_id,
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

    def get_results(self, start="", end="", search="", status="all", limit=500):
        """История игр: прогноз, обоснование и результат. Фильтр по дате/времени."""
        start_dt = self._parse_stamp(start)
        end_dt = self._parse_stamp(end)
        if end_dt is not None and len(str(end).strip()) <= 10:
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        needle = str(search or "").strip().lower()
        status = (status or "all").lower()

        with self.predictor.telegram._lock:
            raw = json.loads(json.dumps(self.predictor.telegram.sent_predictions))

        games = []
        for pred_id, data in raw.items():
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
                "final_score": (data.get("result") or {}).get("final_score", ""),
            })

        games.sort(key=lambda g: str(g.get("sent_at", "")), reverse=True)
        total_preds = sum(len(g["rows"]) for g in games)
        wins = sum(g["wins"] for g in games)
        losses = sum(g["losses"] for g in games)
        pending = sum(g["pending"] for g in games)
        finished = wins + losses
        return self._json({
            "items": games[:int(limit)],
            "total": len(games),
            "summary": {
                "games": len(games),
                "preds": total_preds,
                "wins": wins,
                "losses": losses,
                "pending": pending,
                "hit_rate": round(wins / finished * 100, 1) if finished else 0.0,
            },
        })

    # ------------------------------------------------------------------ конструктор
    def get_constructor(self):
        engine_ctor = self.predictor.constructor
        return self._json({
            "ok": True,
            "mode": self.settings.get_algorithm_mode(),
            "rules": engine_ctor.snapshot(),
            "catalog": engine_ctor.catalog_payload(),
            "presets": engine_ctor.presets(),
            "stats": engine_ctor.stats_payload(),
            "file": engine_ctor.path,
        })

    def save_constructor(self, payload):
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
        except Exception as exc:
            return self._json({"ok": False, "errors": ["Некорректный JSON: %s" % exc]})
        if not isinstance(data, dict) and not isinstance(data, list):
            return self._json({"ok": False, "errors": ["Ожидался объект или список"]})

        if isinstance(data, dict) and data.get("mode") is not None:
            self.settings.set_algorithm_mode(data.get("mode"))

        engine_ctor = self.predictor.constructor
        try:
            ok, errors, rules = engine_ctor.save(data)
        except Exception as exc:
            return self._json({"ok": False, "errors": [str(exc)]})
        if ok:
            core.events.add("INFO", "Конструктор: сохранено правил — %d" % len(rules))
        else:
            core.events.add("ERROR", "Конструктор: %s" % "; ".join(errors[:3]))
        return self._json({
            "ok": bool(ok),
            "errors": errors,
            "rules": rules,
            "mode": self.settings.get_algorithm_mode(),
            "stats": engine_ctor.stats_payload(),
        })

    def set_algorithm_mode(self, mode):
        value = "constructor" if str(mode).lower() == "constructor" else "builtin"
        self.settings.set_algorithm_mode(value)
        core.events.add("INFO", "Источник прогнозов: %s" % (
            "конструктор" if value == "constructor" else "встроенный алгоритм"))
        return self._json({"ok": True, "mode": value})

    def test_constructor(self, payload=None, limit=6):
        """Прогоняет правила по текущей линии, ничего не отправляя."""
        rules = None
        if payload:
            try:
                data = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(data, dict):
                    rules = data.get("rules")
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
            matches = self.predictor.get_live_matches()
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc), "items": []})

        upcoming = [m for m in matches
                    if not m.get("is_started") and m.get("stat_link")][:limit]
        items = []
        for match in upcoming:
            try:
                stats = self.predictor.get_match_stats(
                    match["stat_link"], match["team1"], match["team2"])
            except Exception:
                stats = {}
            stats["league"] = match.get("league", "")
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
    def get_analyzer(self, payload=None):
        """Ищет параметры статистики, характерные для удачных и неудачных прогнозов."""
        options = {}
        if payload:
            try:
                data = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(data, dict):
                    options = data
            except Exception:
                options = {}
        kind = str(options.get("kind") or "all").lower()
        if kind not in ("all", "winner", "total"):
            kind = "all"
        target = str(options.get("target") or "").strip()
        try:
            min_group = max(2, min(20, int(options.get("min_group") or
                                           analyzer.MIN_GROUP)))
        except Exception:
            min_group = analyzer.MIN_GROUP
        try:
            min_lift = max(0.0, min(100.0, float(options.get("min_lift")
                                                 or analyzer.MIN_LIFT)))
        except Exception:
            min_lift = analyzer.MIN_LIFT
        try:
            min_hits = max(1, int(options.get("min_hits") or analyzer.MIN_HITS))
        except Exception:
            min_hits = analyzer.MIN_HITS
        try:
            limit = max(0, int(options.get("limit") or 0))
        except Exception:
            limit = 0

        with self.predictor.telegram._lock:
            raw = json.loads(json.dumps(self.predictor.telegram.sent_predictions))
        try:
            result = analyzer.analyze(
                raw, kind=kind, target=target, min_group=min_group,
                min_lift=min_lift, min_hits=min_hits, limit=limit,
                with_pairs=bool(options.get("pairs", True)))
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc),
                               "failure": [], "success": [],
                               "combos": {"failure": [], "success": []},
                               "means": [], "observations": {}})
        result["ok"] = True
        return self._json(result)

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
            rules = self.predictor.constructor.snapshot()
            for rule in rules:
                rule.pop("summary", None)
                rule.pop("conditions_text", None)
                rule.pop("action_text", None)
                rule.pop("index", None)
            content = json.dumps({"version": 1, "rules": rules},
                                 ensure_ascii=False, indent=2)
            return self._json({"ok": True, "filename": "constructor_%s.json" % stamp,
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


def api_predictions(limit=200):
    return engine().get_predictions(limit)


def api_results(start="", end="", search="", status="all", limit=500):
    return engine().get_results(start, end, search, status, limit)


def api_constructor():
    return engine().get_constructor()


def api_save_constructor(payload):
    return engine().save_constructor(payload)


def api_set_algorithm_mode(mode):
    return engine().set_algorithm_mode(mode)


def api_test_constructor(payload=None, limit=6):
    return engine().test_constructor(payload, limit)


def api_analyzer(payload=None):
    return engine().get_analyzer(payload)


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

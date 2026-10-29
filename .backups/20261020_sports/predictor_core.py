"""
Betcity Predictor — мобильное ядро.

Адаптация 17allsets.py для запуска внутри Android-приложения (Chaquopy).
Логика прогнозирования сохранена без изменений; добавлены:
  * работа с файлами в приватной папке приложения (os.environ["HOME"]);
  * потокобезопасный доступ к настройкам и состоянию;
  * журнал событий в памяти + файл (для экрана «Логи»);
  * API-слой (engine_api.py) для Kotlin/JS.

Внешние зависимости: requests, beautifulsoup4.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta

import warnings

import requests
from bs4 import BeautifulSoup

import analyzer
import constructor_engine

# requests 2.31 ругается на более новый urllib3 — на работу это не влияет.
warnings.filterwarnings(
    "ignore", message=".*doesn't match a supported version.*")

# ============================================================================
# Пути и файлы
# ============================================================================

def _is_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def _resolve_base_dir() -> str:
    """Определяет доступную для записи папку.

    На Android os.environ["HOME"] обычно не задан, поэтому берём
    приватный каталог приложения через Java API Chaquopy.
    """
    candidates = []
    env_home = os.environ.get("PREDICTOR_HOME") or os.environ.get("HOME")
    if env_home:
        candidates.append(env_home)

    try:
        from java import jclass  # доступно только внутри Chaquopy
        python_cls = jclass("com.chaquo.python.Python")
        application = python_cls.getPlatform().getApplication()
        candidates.append(str(application.getFilesDir().getAbsolutePath()))
    except Exception:
        pass

    candidates.append(os.path.join(os.path.expanduser("~"), "predictor"))
    candidates.append(os.path.join(os.getcwd(), "predictor_data"))

    for candidate in candidates:
        if candidate and _is_writable(candidate):
            return candidate
    return os.getcwd()


BASE_DIR = _resolve_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "predictor_data")
os.makedirs(DATA_DIR, exist_ok=True)


def data_path(name: str) -> str:
    return os.path.join(DATA_DIR, name)


SETTINGS_FILE = data_path("bot_settings.json")
SENT_PREDICTIONS_FILE = data_path("sent_predictions.json")
PROCESSED_MATCHES_FILE = data_path("processed_matches.json")
REPORT_STATE_FILE = data_path("report_state.json")
LOG_CSV_FILE = data_path("bets_log.csv")
LOG_FILE = data_path("predictor.log")
EVENTS_FILE = data_path("events.jsonl")
CONSTRUCTOR_RULES_FILE = data_path("constructor_rules.json")

# ============================================================================
# Константы движка (значения по умолчанию; часть переопределяется настройками)
# ============================================================================

PROB_THRESHOLD = 18.5
PROB_Z = 1.96
MIN_H2H_MATCHES = 5

STREAK_MIN = 3
WINDOW_SIZE = 10
WINDOW_MIN_HITS = 6
MARKOV_MIN_SAMPLE = 5
RECENCY_DECAY = 0.85
BASE_RATE_MIN_N = 10

MAX_SETS_TRACKED = 7

HOURLY_REPORT_ENABLED = True
HOURLY_REPORT_INTERVAL_SEC = 3600
DAILY_REPORT_ENABLED = True
DAILY_REPORT_HOUR = 23
DAILY_REPORT_MINUTE = 55

BETCITY_API = "https://d.betcity.by/api/v1/live/bets"
BETCITY_STATS = "https://betcity.by/ru/mstat/"
BETCITY_PARAMS = {"rev": "8", "add": "dep_event", "ver": "479", "csn": "lsmif5"}
BETCITY_COOKIES = {
    "cud": "rBMAD2eYfIozNtNBBNsOAg==",
    "xq_icm": "13000",
    "acceptCookies": "true",
}
BETCITY_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "user-agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
}

MODEL_NAMES = ("streak", "window", "markov1", "markov2", "recency", "base_rate")

# ============================================================================
# Журнал событий (для экрана «Логи»)
# ============================================================================


class EventLog:
    """Кольцевой буфер событий + запись в файл.

    Уровни: DEBUG / INFO / WARNING / ERROR / SUCCESS.
    """

    MAX_EVENTS = 2000

    def __init__(self):
        self._lock = threading.Lock()
        self._events = deque(maxlen=self.MAX_EVENTS)
        self._seq = 0
        self._subscribers = []

    def add(self, level, message, **extra):
        with self._lock:
            self._seq += 1
            event = {
                "id": self._seq,
                "ts": datetime.now().strftime("%H:%M:%S"),
                "ts_full": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": (level or "INFO").upper(),
                "message": str(message),
            }
            if extra:
                event["extra"] = extra
            self._events.append(event)
            subs = list(self._subscribers)

        # файл (не критично при ошибке)
        try:
            with open(EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass

        for cb in subs:
            try:
                cb(event)
            except Exception:
                pass
        return event

    def subscribe(self, callback):
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback):
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def since(self, last_id=0, limit=500):
        with self._lock:
            items = [e for e in self._events if e["id"] > last_id]
        return items[-limit:]

    def all(self, limit=1000):
        with self._lock:
            items = list(self._events)
        return items[-limit:]

    def clear(self):
        with self._lock:
            self._events.clear()
        try:
            if os.path.exists(EVENTS_FILE):
                os.remove(EVENTS_FILE)
        except Exception:
            pass

    def load_from_file(self, limit=500):
        """Подхватывает историю после перезапуска приложения."""
        try:
            if not os.path.exists(EVENTS_FILE):
                return
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()[-limit:]
            with self._lock:
                for line in lines:
                    try:
                        ev = json.loads(line)
                        self._seq = max(self._seq, int(ev.get("id", 0)))
                        self._events.append(ev)
                    except Exception:
                        continue
        except Exception:
            pass


events = EventLog()


class _LogHandler(logging.Handler):
    def emit(self, record):
        try:
            level = record.levelname
            if level == "CRITICAL":
                level = "ERROR"
            events.add(level, record.getMessage())
        except Exception:
            pass


def setup_logging():
    root = logging.getLogger("predictor")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass

    eh = _LogHandler()
    eh.setFormatter(fmt)
    root.addHandler(eh)
    return root


logger = setup_logging()
events.load_from_file()


# ============================================================================
# Системные уведомления Android
# ============================================================================

def notify_android(title, text):
    """Показывает уведомление в шторке Android (если доступно).

    Вне Android (например, при отладке на компьютере) тихо ничего не делает.
    """
    try:
        from java import jclass
        python_cls = jclass("com.chaquo.python.Python")
        application = python_cls.getPlatform().getApplication()
        service = jclass("by.betcity.predictor.EngineService")
        service.notify(application, str(title), str(text))
        return True
    except Exception:
        return False

# ============================================================================
# Настройки
# ============================================================================


class BotSettings:
    DEFAULTS = {
        "running": False,
        "model_thresholds": {
            "streak": 0.25,
            "window": 0.25,
            "markov1": 0.25,
            "markov2": 0.25,
            "recency": 0.25,
            "base_rate": 0.25,
        },
        "required_models": [],
        "allowed_bets": {
            "П1": True, "П2": True, "ТБ18.5": True, "ТМ18.5": True,
        },
        "allowed_sets": {
            "set1": True, "set2": True, "set3": True,
            "set4": True, "set5": True,
        },
        "general_filters": {
            "min_strong": 1,
            "min_agreement": 0.20,
            "min_confidence": 0.10,
            "min_active": 1,
            "vote_weight_base": 0.30,
        },
        "min_h2h_matches": 5,
        "debug_verbose": False,
        # --- параметры, добавленные для приложения ---
        "telegram": {
            "enabled": True,
            "token": "",
            "chat_id": "",
        },
        "poll_interval_sec": 20,
        "odds_check_enabled": True,
        "bet_size_percent": 2.0,
        # builtin — встроенный ансамбль; constructor — правила конструктора
        "algorithm_mode": "builtin",
        "reports": {
            "hourly": True,
            "daily": True,
            "daily_hour": 23,
            "daily_minute": 55,
        },
        "notifications": {
            "on_signal": True,
            "on_error": True,
            "on_result": True,
        },
        "engine": {
            "streak_min": 3,
            "window_size": 10,
            "window_min_hits": 6,
            "markov_min_sample": 5,
            "recency_decay": 0.85,
            "base_rate_min_n": 10,
            "prob_threshold": 18.5,
        },
    }

    NESTED = ("model_thresholds", "allowed_bets", "allowed_sets",
              "general_filters", "telegram", "reports", "notifications",
              "engine")

    def __init__(self, path=SETTINGS_FILE):
        self.path = path
        self._lock = threading.RLock()
        self.data = self._load()

    # ---------- сериализация ----------
    def _deep_defaults(self):
        return json.loads(json.dumps(self.DEFAULTS))

    def _load(self):
        data = self._deep_defaults()
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                if isinstance(stored, dict):
                    for key, default in self.DEFAULTS.items():
                        if key not in stored:
                            continue
                        if isinstance(default, dict):
                            if isinstance(stored[key], dict):
                                merged = dict(default)
                                merged.update(stored[key])
                                data[key] = merged
                        else:
                            data[key] = stored[key]
        except Exception as exc:
            logger.error("Не удалось загрузить настройки: %s", exc)
        return data

    def save(self):
        with self._lock:
            try:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
                return True
            except Exception as exc:
                logger.error("Не удалось сохранить настройки: %s", exc)
                return False

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self.data))

    def update(self, patch):
        """Частичное обновление (вложенные словари мержатся)."""
        if not isinstance(patch, dict):
            return False
        with self._lock:
            for key, value in patch.items():
                if key not in self.DEFAULTS:
                    continue
                if isinstance(self.DEFAULTS[key], dict) and isinstance(value, dict):
                    self.data[key].update(value)
                else:
                    self.data[key] = value
        return self.save()

    def reset_to_defaults(self, keep_telegram=True):
        with self._lock:
            telegram = dict(self.data.get("telegram") or {})
            self.data = self._deep_defaults()
            if keep_telegram:
                self.data["telegram"] = telegram
        return self.save()

    # ---------- доступ ----------
    def is_running(self):
        with self._lock:
            return bool(self.data.get("running", False))

    def set_running(self, value):
        with self._lock:
            self.data["running"] = bool(value)
        return self.save()

    def get_model_threshold(self, name):
        with self._lock:
            return float(self.data["model_thresholds"].get(name, 0.25))

    def get_required_models(self):
        with self._lock:
            return set(self.data.get("required_models", []))

    def is_bet_allowed(self, code):
        with self._lock:
            return bool(self.data["allowed_bets"].get(code, True))

    def is_set_allowed(self, set_target):
        with self._lock:
            return bool(self.data["allowed_sets"].get(set_target, True))

    def get_filter(self, name):
        with self._lock:
            return self.data["general_filters"].get(
                name, self.DEFAULTS["general_filters"][name])

    def get_min_h2h(self):
        with self._lock:
            return int(self.data.get("min_h2h_matches", MIN_H2H_MATCHES))

    def get_algorithm_mode(self):
        with self._lock:
            mode = str(self.data.get("algorithm_mode") or "builtin").lower()
        return "constructor" if mode == "constructor" else "builtin"

    def set_algorithm_mode(self, mode):
        value = "constructor" if str(mode).lower() == "constructor" else "builtin"
        with self._lock:
            self.data["algorithm_mode"] = value
        return self.save()

    def is_verbose(self):
        with self._lock:
            return bool(self.data.get("debug_verbose", False))

    def get_vote_weight_base(self):
        with self._lock:
            return float(self.data["general_filters"].get(
                "vote_weight_base", 0.30))

    def get_engine(self, name):
        with self._lock:
            default = self.DEFAULTS["engine"].get(name)
            value = self.data.get("engine", {}).get(name, default)
        try:
            return type(default)(value)
        except Exception:
            return default

    def get_telegram(self):
        with self._lock:
            cfg = dict(self.data.get("telegram") or {})
        cfg.setdefault("enabled", True)
        cfg.setdefault("token", "")
        cfg.setdefault("chat_id", "")
        return cfg

    def get_poll_interval(self):
        with self._lock:
            try:
                return max(5, int(self.data.get("poll_interval_sec", 20)))
            except Exception:
                return 20

    def get_reports(self):
        with self._lock:
            cfg = dict(self.DEFAULTS["reports"])
            cfg.update(self.data.get("reports") or {})
        return cfg

    def get_notifications(self):
        with self._lock:
            cfg = dict(self.DEFAULTS["notifications"])
            cfg.update(self.data.get("notifications") or {})
        return cfg


# ============================================================================
# Telegram
# ============================================================================


class TelegramBot:
    """Хранилище прогнозов + необязательная отправка в Telegram.

    Если token/chat_id не заданы, объект работает в локальном режиме:
    прогнозы сохраняются, результаты отслеживаются, отчёты пишутся в журнал.
    """

    def __init__(self, token, chat_id, settings):
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.settings = settings
        self.offline = not (self.token and self.chat_id)
        self.base_url = ("https://api.telegram.org/bot" + self.token) if self.token else ""
        self.sent_predictions_file = SENT_PREDICTIONS_FILE
        self.sent_predictions = self.load_sent_predictions()
        self.predictor = None
        self._lock = threading.RLock()
        self._local_id = -1

    def _local_message_id(self):
        with self._lock:
            self._local_id -= 1
            return self._local_id

    def apply_settings(self):
        """Подхватывает токен/chat_id после изменения настроек в приложении."""
        cfg = self.settings.get_telegram()
        token = (cfg.get("token") or "").strip()
        chat_id = (cfg.get("chat_id") or "").strip()
        enabled = bool(cfg.get("enabled", True))
        with self._lock:
            if not enabled:
                token, chat_id = "", ""
            changed = (token != self.token) or (chat_id != self.chat_id)
            self.token = token
            self.chat_id = chat_id
            self.offline = not (token and chat_id)
            self.base_url = ("https://api.telegram.org/bot" + token) if token else ""
        if changed:
            if self.offline:
                logger.info("Telegram: локальный режим (сигналы только в приложении)")
            else:
                logger.info("Telegram: подключён чат %s", chat_id)
        return not self.offline

    # ---------- хранилище прогнозов ----------
    def load_sent_predictions(self):
        try:
            if os.path.exists(self.sent_predictions_file):
                with open(self.sent_predictions_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as exc:
            logger.error("Загрузка прогнозов: %s", exc)
        return {}

    def save_sent_predictions(self):
        with self._lock:
            try:
                tmp = self.sent_predictions_file + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.sent_predictions, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.sent_predictions_file)
            except Exception as exc:
                logger.error("Сохранение прогнозов: %s", exc)

    def generate_prediction_id(self, team1, team2, date):
        raw = "%s_%s_%s" % (team1, team2, date)
        return hashlib.md5(raw.encode()).hexdigest()

    def is_prediction_sent(self, team1, team2, date):
        with self._lock:
            return self.generate_prediction_id(team1, team2, date) in self.sent_predictions

    def mark_prediction_sent(self, team1, team2, date, predictions_list,
                             message_id, league="", stats=None, message_text=None):
        pred_id = self.generate_prediction_id(team1, team2, date)
        with self._lock:
            self.sent_predictions[pred_id] = {
                "team1": team1, "team2": team2, "date": date, "league": league,
                "message_id": message_id,
                "predictions": predictions_list,
                "stats": stats,
                "message_text": message_text,
                "sent_at": datetime.now().isoformat(),
                "result_checked": False,
                "set_results": [],
                "sets_completed": 0,
                "original_message": None,
            }
        self.save_sent_predictions()
        return pred_id

    def update_set_result(self, pred_id, target, result):
        with self._lock:
            pred = self.sent_predictions.get(pred_id)
            if not pred:
                return False
            results = pred.setdefault("set_results", [])
            kind = result.get("kind", "")
            for idx, existing in enumerate(results):
                if existing.get("target") != target:
                    continue
                # Победитель и тотал одной партии — разные прогнозы,
                # поэтому сравниваем ещё и вид ставки.
                if kind and existing.get("kind") and existing.get("kind") != kind:
                    continue
                results[idx] = result
                break
            else:
                results.append(result)
        self.save_sent_predictions()
        return True

    def update_prediction_result(self, pred_id, result_data, updated_message):
        with self._lock:
            pred = self.sent_predictions.get(pred_id)
            if not pred:
                return False
            pred["result_checked"] = True
            pred["result"] = result_data
            pred["checked_at"] = datetime.now().isoformat()
            pred["original_message"] = updated_message
        self.save_sent_predictions()
        return True

    # ---------- HTTP ----------
    def send_message(self, text, reply_markup=None):
        if self.offline:
            logger.info("Сигнал (локально): %s", text.splitlines()[0] if text else "")
            return self._local_message_id()
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_markup:
                payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
            resp = requests.post(self.base_url + "/sendMessage", json=payload, timeout=10)
            if resp.status_code == 200:
                return resp.json().get("result", {}).get("message_id")
            logger.error("Telegram API: %s %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.error("Ошибка отправки в Telegram: %s", exc)
        return None

    def edit_message(self, message_id, text, reply_markup=None):
        if self.offline or (isinstance(message_id, int) and message_id < 0):
            return True
        try:
            payload = {
                "chat_id": self.chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_markup is not None:
                payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
            resp = requests.post(self.base_url + "/editMessageText", json=payload, timeout=10)
            if resp.status_code == 200:
                return True
            if "message is not modified" in resp.text:
                return True
            return False
        except Exception as exc:
            logger.error("Ошибка редактирования сообщения: %s", exc)
            return False

    # ---------- отчёты ----------
    def _collect_common(self):
        with self._lock:
            sent = dict(self.sent_predictions)
        now = datetime.now()
        today_iso = now.date().isoformat()

        totals = {"preds": 0, "wins": 0, "losses": 0, "pending": 0}
        today = {"preds": 0, "wins": 0, "losses": 0, "pending": 0}
        by_target = {}

        for pred in sent.values():
            predictions = pred.get("predictions") or []
            results = pred.get("set_results") or []
            n_preds = len(predictions)
            wins = sum(1 for r in results if r.get("success"))
            losses = sum(1 for r in results if not r.get("success"))
            pending = max(0, n_preds - len(results))

            totals["preds"] += n_preds
            totals["wins"] += wins
            totals["losses"] += losses
            totals["pending"] += pending

            if str(pred.get("sent_at", "")).startswith(today_iso):
                today["preds"] += n_preds
                today["wins"] += wins
                today["losses"] += losses
                today["pending"] += pending

            for item in predictions:
                key = "%s:%s" % (item.get("target"), item.get("kind"))
                by_target.setdefault(key, {"n": 0, "w": 0, "l": 0})["n"] += 1

            for result in results:
                target = result.get("target", "")
                kind = next((p.get("kind") for p in predictions
                             if p.get("target") == target), None)
                key = "%s:%s" % (target, kind)
                if key in by_target:
                    if result.get("success"):
                        by_target[key]["w"] += 1
                    else:
                        by_target[key]["l"] += 1

        return {
            "matches": len(sent),
            "total": totals,
            "today": today,
            "by_target": by_target,
        }

    def stats_payload(self):
        """Готовые цифры для приложения."""
        data = self._collect_common()
        totals = data["total"]
        finished = totals["wins"] + totals["losses"]
        hit_rate = (totals["wins"] / finished * 100) if finished else 0.0

        today = data["today"]
        today_finished = today["wins"] + today["losses"]
        today_rate = (today["wins"] / today_finished * 100) if today_finished else 0.0

        by_target = []
        for key, val in sorted(data["by_target"].items()):
            finished_t = val["w"] + val["l"]
            by_target.append({
                "key": key,
                "total": val["n"],
                "wins": val["w"],
                "losses": val["l"],
                "hit_rate": round(val["w"] / finished_t * 100, 1) if finished_t else 0.0,
            })

        return {
            "matches": data["matches"],
            "total": totals,
            "today": today,
            "hit_rate": round(hit_rate, 1),
            "today_hit_rate": round(today_rate, 1),
            "by_target": by_target,
        }

    def send_hourly_report(self):
        payload = self.stats_payload()
        totals = payload["total"]
        lines = [
            "⏰ <b>Ежечасный отчёт</b>",
            "─────────────────────────",
            "📊 Прогнозов: %d" % totals["preds"],
            "✅ %d | ❌ %d | ⏳ %d" % (totals["wins"], totals["losses"], totals["pending"]),
        ]
        if payload["hit_rate"]:
            lines.append("🎯 Hit rate: %.1f%%" % payload["hit_rate"])
        lines.append("")
        lines.append("📅 Сегодня: %d прогнозов" % payload["today"]["preds"])
        lines.append("✅ %d | ❌ %d" % (payload["today"]["wins"], payload["today"]["losses"]))
        self.send_message("\n".join(lines))

    def send_daily_report(self):
        payload = self.stats_payload()
        totals, today = payload["total"], payload["today"]
        lines = [
            "📆 <b>Дневной отчёт</b> — %s" % datetime.now().date().isoformat(),
            "═════════════════════════",
            "📅 Сегодня: %d прогнозов" % today["preds"],
            "✅ %d | ❌ %d | ⏳ %d" % (today["wins"], today["losses"], today["pending"]),
            "🎯 Hit rate: %.1f%%" % payload["today_hit_rate"],
            "",
            "📈 За весь период:",
            "Всего прогнозов: %d" % totals["preds"],
            "✅ %d | ❌ %d | ⏳ %d" % (totals["wins"], totals["losses"], totals["pending"]),
            "🎯 Hit rate: %.1f%%" % payload["hit_rate"],
            "═════════════════════════",
        ]
        self.send_message("\n".join(lines))

    def send_full_report(self):
        payload = self.stats_payload()
        totals = payload["total"]
        lines = [
            "📈 <b>Полный отчёт</b>",
            "═════════════════════════",
            "Всего прогнозов: %d" % totals["preds"],
            "✅ %d | ❌ %d | ⏳ %d" % (totals["wins"], totals["losses"], totals["pending"]),
            "🎯 Hit rate: %.1f%%" % payload["hit_rate"],
        ]
        if payload["by_target"]:
            lines.append("")
            lines.append("🎯 По видам ставок:")
            for row in payload["by_target"]:
                lines.append("   %s: %d (✅%d/❌%d = %.0f%%)" % (
                    row["key"], row["total"], row["wins"],
                    row["losses"], row["hit_rate"]))
        self.send_message("\n".join(lines))


# ============================================================================
# Отчёты по расписанию
# ============================================================================


class ReportManager:
    def __init__(self, telegram_bot, settings):
        self.telegram = telegram_bot
        self.settings = settings
        self.state = self._load_state()

    def _load_state(self):
        try:
            if os.path.exists(REPORT_STATE_FILE):
                with open(REPORT_STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"last_hourly_ts": 0, "last_daily_date": ""}

    def _save_state(self):
        try:
            with open(REPORT_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("ReportManager: %s", exc)

    def check_and_send(self):
        cfg = self.settings.get_reports()
        now = time.time()

        if cfg.get("hourly"):
            if now - self.state.get("last_hourly_ts", 0) >= HOURLY_REPORT_INTERVAL_SEC:
                try:
                    self.telegram.send_hourly_report()
                    self.state["last_hourly_ts"] = now
                    self._save_state()
                except Exception as exc:
                    logger.error("Ежечасный отчёт: %s", exc)

        if cfg.get("daily"):
            local_now = datetime.now()
            today = local_now.date().isoformat()
            target = local_now.replace(
                hour=int(cfg.get("daily_hour", 23)),
                minute=int(cfg.get("daily_minute", 55)),
                second=0, microsecond=0)
            if local_now >= target and self.state.get("last_daily_date", "") != today:
                try:
                    self.telegram.send_daily_report()
                    self.state["last_daily_date"] = today
                    self._save_state()
                except Exception as exc:
                    logger.error("Дневной отчёт: %s", exc)


# ============================================================================
# CSV-журнал ставок
# ============================================================================


class BetsLogger:
    FIELDS = ["datetime", "teams", "league", "rule", "prediction",
              "confidence_claimed", "ensemble_details", "odds_info",
              "set1_result", "set1_score", "set1_total",
              "set2_result", "set2_score", "set2_total",
              "set3_result", "set3_score", "set3_total",
              "set4_result", "set4_score", "set4_total",
              "set5_result", "set5_score", "set5_total",
              "set6_result", "set6_score", "set6_total",
              "set7_result", "set7_score", "set7_total",
              "first_set_only", "total_sets_played"]

    def __init__(self, path=LOG_CSV_FILE):
        self.path = path
        if not os.path.exists(self.path):
            self._write_header()
        else:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    header = f.readline().strip()
                if "set7_result" not in header:
                    backup = self.path + ".old_" + datetime.now().strftime("%Y%m%d_%H%M%S")
                    os.rename(self.path, backup)
                    self._write_header()
            except Exception:
                pass

    def _write_header(self):
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(self.FIELDS)

    def log_bet(self, row):
        try:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([row.get(k, "") for k in self.FIELDS])
        except Exception as exc:
            logger.error("CSV: %s", exc)

    def update_bet_results(self, teams, datetime_prefix, set_results):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            updated = False
            for row in rows:
                if row.get("teams") != teams:
                    continue
                if not str(row.get("datetime", "")).startswith(datetime_prefix):
                    continue
                for result in set_results:
                    target = result.get("target", "")
                    match = re.match(r"set(\d)", target)
                    if not match:
                        continue
                    number = int(match.group(1))
                    if 1 <= number <= MAX_SETS_TRACKED:
                        row["set%d_result" % number] = "win" if result.get("success") else "loss"
                        row["set%d_score" % number] = result.get("score", "")
                        row["set%d_total" % number] = result.get("total", "")
                first = next((r for r in set_results if r.get("target") == "set1"), None)
                if first:
                    row["first_set_only"] = "win" if first.get("success") else "loss"
                row["total_sets_played"] = len(
                    [r for r in set_results if str(r.get("target", "")).startswith("set")])
                updated = True
                break
            if updated:
                with open(self.path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=self.FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
        except Exception as exc:
            logger.error("CSV update: %s", exc)

    def read_rows(self, limit=500):
        rows = []
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
        except Exception as exc:
            logger.error("CSV read: %s", exc)
        return rows[-limit:]

    def clear(self):
        try:
            self._write_header()
            return True
        except Exception:
            return False


# ============================================================================
# Проверка результатов
# ============================================================================


class ResultChecker:
    def __init__(self, telegram_bot, bets_logger):
        self.telegram = telegram_bot
        self.bets_logger = bets_logger
        self.session = requests.Session()
        self.running = True
        self.csv_updated = set()

    @staticmethod
    def is_set_completed(p1, p2):
        if (p1 >= 11 or p2 >= 11) and abs(p1 - p2) >= 2:
            return True
        if p1 >= 10 and p2 >= 10 and abs(p1 - p2) >= 2:
            return True
        return False

    def check_prediction_success(self, prediction, set_data):
        if not set_data:
            return None
        p1, p2 = set_data["p1"], set_data["p2"]
        total = p1 + p2
        kind = prediction.get("kind", "")
        side = prediction.get("expected_side", "")

        # Старые сохранённые прогнозы могут не содержать expected_side,
        # поэтому определяем сторону по тексту вердикта.
        verdict = str(prediction.get("verdict", ""))
        if not side:
            if "П1" in verdict:
                side = "П1"
            elif "П2" in verdict:
                side = "П2"
            elif "ТБ" in verdict:
                side = "over"
            elif "ТМ" in verdict:
                side = "under"

        if kind == "winner":
            if side not in ("П1", "П2"):
                side = "П1" if p1 > p2 else "П2"
            success = (p1 > p2) if side == "П1" else (p2 > p1)
        elif kind == "total":
            threshold = prediction.get("threshold", 18.5)
            success = (total > threshold) if side == "over" else (total < threshold)
        else:
            return None
        return {"success": success, "score": "%d:%d" % (p1, p2), "total": total}

    def get_live_match_score(self, team1, team2):
        try:
            resp = self.session.get(BETCITY_API, params=BETCITY_PARAMS,
                                    cookies=BETCITY_COOKIES,
                                    headers=BETCITY_HEADERS, timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()
            sports = (data.get("reply") or {}).get("sports") or {}
            tennis = sports.get("46") or {}
            for champ in (tennis.get("chmps") or {}).values():
                for match in (champ.get("evts") or {}).values():
                    try:
                        if match["name_ht"] == team1 and match["name_at"] == team2:
                            return match.get("sc_inter", "0:0")
                    except Exception:
                        continue
        except Exception:
            return None
        return None

    def parse_score(self, score_str):
        sets = []
        if not score_str or score_str == "0:0":
            return sets
        # Betcity отдаёт счёт либо через запятую, либо через пробел.
        parts = re.split(r"[,\s]+", str(score_str).strip())
        for part in parts:
            part = part.strip()
            if ":" not in part:
                continue
            try:
                p1, p2 = map(int, part.split(":")[:2])
            except Exception:
                continue
            sets.append({
                "set_number": len(sets) + 1,
                "p1": p1, "p2": p2,
                "completed": self.is_set_completed(p1, p2),
                "display": "%d:%d" % (p1, p2),
            })
        return sets

    def build_original_message(self, pred_data):
        team1, team2 = pred_data["team1"], pred_data["team2"]
        predictions = pred_data.get("predictions") or []
        lines = [
            "🔴 <b>LIVE: %s vs %s</b>" % (team1, team2),
            "⏰ Начало: %s" % str(pred_data.get("sent_at", ""))[:16].replace("T", " "),
        ]
        if pred_data.get("league"):
            lines.append("🏆 Лига: %s" % pred_data["league"])
        lines.append("")
        lines.append("📊 <b>ПРОГНОЗЫ:</b>")
        for pred in predictions:
            lines.append("   • <b>%s:</b> %s" % (pred.get("label"), pred.get("verdict")))
            lines.append("     %s" % pred.get("models_info", ""))
        if predictions:
            per = round(2.0 / len(predictions), 2)
            lines.append("")
            lines.append("💰 <b>Ставка: 2.0%%</b> (по %s%% на каждый)" % per)
        lines.append("")
        lines.append("🔄 Отслеживание по всем партиям")
        lines.append("─" * 40)
        return "\n".join(lines)

    def format_result_message(self, original_message, set_results, final_score):
        separator = "─" * 40
        marker = "📊 <b>РЕЗУЛЬТАТЫ</b>"
        if marker in original_message:
            base = original_message.split(marker)[0]
        elif separator in original_message:
            base = original_message.split(separator)[0]
        else:
            base = original_message

        lines = ["", "", marker, "🎾 Счет: %s" % final_score, ""]
        for result in sorted(set_results, key=lambda r: str(r.get("target"))):
            emoji = "✅" if result.get("success") else "❌"
            label = result.get("label", result.get("target", ""))
            lines.append("<b>%s:</b> %s (тотал %s)" % (
                label, result.get("score", ""), result.get("total", "")))
            lines.append("   %s %s" % (emoji, result.get("verdict", "")))

        set_results_only = [r for r in set_results
                            if str(r.get("target", "")).startswith("set")]
        wins = sum(1 for r in set_results_only if r.get("success"))
        if set_results_only:
            lines.append("")
            lines.append("📈 Итого: %d/%d (%.0f%%)" % (
                wins, len(set_results_only), wins / len(set_results_only) * 100))
        return base.strip() + "\n".join(lines) + "\n" + separator

    def check_pending_predictions(self):
        snapshot = list(self.telegram.sent_predictions.items())
        for pred_id, pred_data in snapshot:
            team1, team2 = pred_data.get("team1"), pred_data.get("team2")
            message_id = pred_data.get("message_id")
            predictions = pred_data.get("predictions") or []
            if not message_id or not predictions:
                continue

            score_str = self.get_live_match_score(team1, team2)
            if not score_str:
                continue
            sets = self.parse_score(score_str)
            completed = [s for s in sets if s.get("completed")][:MAX_SETS_TRACKED]
            if not completed:
                continue

            current = len(completed)
            previous = pred_data.get("sets_completed", 0)

            for pred in predictions:
                target = pred.get("target", "")
                if not target.startswith("set"):
                    continue
                try:
                    number = int(target.replace("set", ""))
                except Exception:
                    continue
                set_data = next((s for s in completed if s["set_number"] == number), None)
                if not set_data:
                    continue
                result = self.check_prediction_success(pred, set_data)
                if result:
                    result["target"] = target
                    result["kind"] = pred.get("kind", "")
                    result["label"] = pred.get("label", "Партия %d" % number)
                    result["verdict"] = pred.get("verdict", "")
                    self.telegram.update_set_result(pred_id, target, result)

            if current > previous or not pred_data.get("original_message"):
                all_results = sorted(pred_data.get("set_results", []),
                                     key=lambda r: str(r.get("target")))
                new_message = self.format_result_message(
                    self.build_original_message(pred_data), all_results, score_str)
                if self.telegram.edit_message(message_id, new_message):
                    pred_data["original_message"] = new_message
                    self.telegram.save_sent_predictions()
                if pred_id not in self.csv_updated or current > previous:
                    self._update_csv(pred_data, all_results)
                    self.csv_updated.add(pred_id)

            p1 = sum(1 for s in completed if s["p1"] > s["p2"])
            p2 = sum(1 for s in completed if s["p2"] > s["p1"])
            if p1 >= 4 or p2 >= 4:
                if not pred_data.get("result_checked"):
                    self.telegram.update_prediction_result(
                        pred_id,
                        {"final_score": score_str, "sets": current},
                        pred_data.get("original_message", ""))
                    self._notify_result(pred_data, score_str)
            elif (p1 >= 3 or p2 >= 3) and current >= 3:
                last = pred_data.get("last_match_score")
                if last == score_str:
                    if not pred_data.get("result_checked"):
                        self.telegram.update_prediction_result(
                            pred_id,
                            {"final_score": score_str, "sets": current},
                            pred_data.get("original_message", ""))
                        self._notify_result(pred_data, score_str)
                else:
                    pred_data["last_match_score"] = score_str
                    self.telegram.save_sent_predictions()

    def _notify_result(self, pred_data, score_str):
        try:
            if not self.telegram.settings.get_notifications().get("on_result", True):
                return
            results = pred_data.get("set_results") or []
            wins = sum(1 for r in results if r.get("success"))
            losses = sum(1 for r in results if not r.get("success"))
            notify_android(
                "Матч завершён: %s — %s" % (pred_data.get("team1"), pred_data.get("team2")),
                "Счёт %s · прогнозы: %d/%d" % (score_str, wins, wins + losses))
        except Exception:
            pass

    def _update_csv(self, pred_data, all_results):
        try:
            prefix = str(pred_data.get("sent_at", ""))[:16]
            teams = "%s vs %s" % (pred_data["team1"], pred_data["team2"])
            self.bets_logger.update_bet_results(teams, prefix, all_results)
        except Exception as exc:
            logger.error("CSV outer: %s", exc)

    def run(self):
        while self.running:
            try:
                self.check_pending_predictions()
            except Exception as exc:
                logger.error("ResultChecker: %s", exc)
            time.sleep(30)

    def stop(self):
        self.running = False


# ============================================================================
# Ансамбль вероятностей
# ============================================================================


class ProbabilityEnsemble:
    def __init__(self, seq, opposite_fn, vote_weight_base=0.30):
        self.seq = list(seq)
        self.opposite_fn = opposite_fn
        self.vote_weight_base = vote_weight_base

    @staticmethod
    def _wilson(wins, n, z=PROB_Z):
        if n == 0:
            return 0.0
        phat = wins / n
        denom = 1 + z * z / n
        center = phat + z * z / (2 * n)
        margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
        return max(0.0, (center - margin) / denom)

    def m_streak(self):
        if not self.seq:
            return {"name": "streak", "prediction": None, "wilson_lower": 0.0}
        current = self.seq[-1]
        run = 0
        for value in reversed(self.seq):
            if value == current:
                run += 1
            else:
                break
        if run < STREAK_MIN:
            return {"name": "streak", "prediction": None, "wilson_lower": 0.0}
        wins = sum(1 for v in self.seq if v == current)
        return {
            "name": "streak",
            "prediction": current,
            "wilson_lower": self._wilson(wins, len(self.seq)),
            "detail": "run=%d" % run,
        }

    def m_window(self):
        if len(self.seq) < WINDOW_SIZE:
            return {"name": "window", "prediction": None, "wilson_lower": 0.0}
        window = self.seq[-WINDOW_SIZE:]
        counts = {}
        for value in window:
            counts[value] = counts.get(value, 0) + 1
        top, hits = max(counts.items(), key=lambda kv: kv[1])
        if hits < WINDOW_MIN_HITS:
            return {"name": "window", "prediction": None, "wilson_lower": 0.0}
        return {
            "name": "window",
            "prediction": top,
            "wilson_lower": self._wilson(hits, len(window)),
            "detail": "hits=%d/%d" % (hits, len(window)),
        }

    def _markov(self, order, name):
        if len(self.seq) <= order:
            return {"name": name, "prediction": None, "wilson_lower": 0.0}
        context = tuple(self.seq[-order:])
        transitions = {}
        for idx in range(len(self.seq) - order):
            if tuple(self.seq[idx:idx + order]) == context:
                nxt = self.seq[idx + order]
                transitions[nxt] = transitions.get(nxt, 0) + 1
        total = sum(transitions.values())
        if total < MARKOV_MIN_SAMPLE:
            return {"name": name, "prediction": None, "wilson_lower": 0.0}
        top, hits = max(transitions.items(), key=lambda kv: kv[1])
        return {
            "name": name,
            "prediction": top,
            "wilson_lower": self._wilson(hits, total),
            "detail": "%d/%d" % (hits, total),
        }

    def m_markov1(self):
        return self._markov(1, "markov1")

    def m_markov2(self):
        return self._markov(2, "markov2")

    def m_recency(self):
        if not self.seq:
            return {"name": "recency", "prediction": None, "wilson_lower": 0.0}
        weights = {}
        total_weight = 0.0
        for idx, value in enumerate(reversed(self.seq)):
            weight = RECENCY_DECAY ** idx
            weights[value] = weights.get(value, 0.0) + weight
            total_weight += weight
        if total_weight <= 0:
            return {"name": "recency", "prediction": None, "wilson_lower": 0.0}
        top = max(weights.items(), key=lambda kv: kv[1])
        share = top[1] / total_weight
        wins = sum(1 for v in self.seq if v == top[0])
        return {
            "name": "recency",
            "prediction": top[0],
            "wilson_lower": self._wilson(wins, len(self.seq)) * share,
            "detail": "share=%.2f" % share,
        }

    def m_base(self):
        if len(self.seq) < BASE_RATE_MIN_N:
            return {"name": "base_rate", "prediction": None, "wilson_lower": 0.0}
        counts = {}
        for value in self.seq:
            counts[value] = counts.get(value, 0) + 1
        top, hits = max(counts.items(), key=lambda kv: kv[1])
        return {
            "name": "base_rate",
            "prediction": top,
            "wilson_lower": self._wilson(hits, len(self.seq)),
            "detail": "%d/%d" % (hits, len(self.seq)),
        }

    def aggregate(self):
        models = [self.m_streak(), self.m_window(), self.m_markov1(),
                  self.m_markov2(), self.m_recency(), self.m_base()]
        votes = {}
        active = []
        for model in models:
            prediction = model.get("prediction")
            if prediction is None:
                continue
            active.append(model)
            weight = max(0.0, model["wilson_lower"] - self.vote_weight_base)
            if weight <= 0:
                continue
            votes[prediction] = votes.get(prediction, 0.0) + weight

        if not votes:
            return None

        total_weight = sum(votes.values())
        top, top_weight = max(votes.items(), key=lambda kv: kv[1])
        agreement = top_weight / total_weight if total_weight else 0.0

        agreeing = [m for m in active if m["prediction"] == top]
        confidence = (sum(m["wilson_lower"] for m in agreeing) / len(agreeing)
                      if agreeing else 0.0)

        return {
            "prediction": top,
            "models": models,
            "strong": len(agreeing),
            "agreement": agreement,
            "confidence": confidence,
            "votes": votes,
        }


# ============================================================================
# Предиктор
# ============================================================================


class PredictorEnsemble:
    def __init__(self, telegram_token=None, telegram_chat_id=None, settings=None):
        self.session = requests.Session()
        self.settings = settings or BotSettings()

        # Хранилище прогнозов нужно всегда: без него не работают
        # ни статистика, ни отслеживание результатов.
        self.telegram = TelegramBot(telegram_token, telegram_chat_id, self.settings)
        self.telegram.predictor = self
        if telegram_token is None and telegram_chat_id is None:
            self.telegram.apply_settings()

        self.bets_logger = BetsLogger()
        self.result_checker = ResultChecker(self.telegram, self.bets_logger)
        self.checker_thread = None

        self.processed_file = PROCESSED_MATCHES_FILE
        self.processed_matches = self.load_processed()
        self.stats = {
            "checked": 0, "sent": 0, "skipped": 0,
            "blocked_odds": 0, "blocked_settings": 0, "blocked_general": 0,
            "no_h2h": 0, "short_seq": 0, "no_top": 0,
            "by_target": {},
        }
        self.report_manager = ReportManager(self.telegram, self.settings)
        self.constructor = constructor_engine.ConstructorEngine(
            CONSTRUCTOR_RULES_FILE, self.settings, logger)

        self._lock = threading.RLock()
        self._last_cycle = None
        self._last_error = None
        self._live_matches = 0

    # ---------- обработанные матчи ----------
    def load_processed(self):
        try:
            if os.path.exists(self.processed_file):
                with open(self.processed_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_processed(self):
        try:
            tmp = self.processed_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.processed_matches, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.processed_file)
        except Exception:
            pass

    def is_processed(self, match_id):
        return match_id in self.processed_matches

    def mark_processed(self, match_id):
        self.processed_matches[match_id] = {"processed_at": datetime.now().isoformat()}
        self.save_processed()

    # ---------- парсинг дат ----------
    @staticmethod
    def _parse_date(value):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M",
                    "%Y/%m/%d %H:%M:%S", "%d.%m.%y"):
            try:
                return datetime.strptime(value, fmt)
            except Exception:
                continue
        return None

    @staticmethod
    def _parse_match_date(value):
        for fmt in ("%d.%m.%y", "%d.%m.%Y"):
            try:
                return datetime.strptime(value, fmt)
            except Exception:
                continue
        return None

    # ---------- нормализация имён ----------
    @staticmethod
    def _clean_name(value):
        return re.sub(r"[^\w\s]", "", (value or "")).lower().strip()

    def _names_match(self, a, b):
        a, b = self._clean_name(a), self._clean_name(b)
        if not a or not b:
            return False
        if a == b or a in b or b in a:
            return True
        words_a, words_b = a.split(), b.split()
        if words_a and words_b and words_a[-1] == words_b[-1]:
            return True
        return False

    @staticmethod
    def _opposite(value):
        return {"T1": "T2", "T2": "T1", "TO": "TM", "TM": "TO"}.get(value, value)

    # ---------- кэфы ----------
    @staticmethod
    def _extract_match_odds(match):
        try:
            for key in (match.get("main") or {}):
                item = match["main"][key]
                if item.get("name") == "Исходы по партиям" or \
                        "Фактический исход" in item.get("name", ""):
                    data = item.get("data", {})
                    for data_key in data:
                        blocks = data[data_key].get("blocks", {})
                        if "W" in blocks:
                            win = blocks["W"]
                            if "P1" in win and "P2" in win:
                                return float(win["P1"]["kf"]), float(win["P2"]["kf"])

            for key in (match.get("ext") or {}):
                item = match["ext"][key]
                if item.get("name") == "Исходы по партиям":
                    rows = item.get("rows", {})
                    for row_key in rows:
                        row = rows[row_key]
                        if row.get("name") == "1-я партия":
                            data = row.get("data", {})
                            for data_key in data:
                                blocks = data[data_key].get("blocks", {})
                                if "W" in blocks:
                                    win = blocks["W"]
                                    if "P1" in win and "P2" in win:
                                        return float(win["P1"]["kf"]), float(win["P2"]["kf"])
            return None, None
        except Exception:
            return None, None

    # ---------- статистика: последние игры и тоталы ----------
    def _parse_recent_games(self, table, player):
        """5 последних игр игрока со страницы статистики.

        Возвращает записи, уже ориентированные на игрока:
        sets = [(очки игрока, очки соперника), ...].
        """
        games = []
        date_text = ""
        league = ""
        for row in table.find_all("tr"):
            date_cell = row.find("td", class_="ev-mstat-dt")
            if date_cell is not None:
                date_text = date_cell.get_text(" ", strip=True)
                league_cell = row.find("td", class_="ev-mstat-ch")
                league = league_cell.get_text(" ", strip=True) if league_cell else ""
                continue

            teams_cell = row.find("td", class_="ev-mstat-ev")
            if teams_cell is None:
                continue
            teams_text = teams_cell.get_text(" ", strip=True)
            score_cell = row.find("td", class_="ev-mstat-sc")
            score_text = score_cell.get_text(" ", strip=True) if score_cell else ""

            parts = re.split(r"\s+[-—]\s+", teams_text)
            if len(parts) < 2:
                parts = re.split(r"[-—]", teams_text, maxsplit=1)
            if len(parts) < 2:
                continue
            left, right = parts[0].strip(), parts[1].strip()

            pairs = [(int(a), int(b)) for a, b in
                     re.findall(r"(\d+)\s*:\s*(\d+)", score_text)]
            if not pairs:
                continue
            match_score = pairs[0]
            set_scores = pairs[1:] if len(pairs) > 1 else []

            if self._names_match(player, left) and not self._names_match(player, right):
                side = 1
            elif self._names_match(player, right) and not self._names_match(player, left):
                side = 2
            else:
                side = 1

            if side == 1:
                own_sets = [(a, b) for a, b in set_scores]
                own_score = (match_score[0], match_score[1])
                opponent = right
            else:
                own_sets = [(b, a) for a, b in set_scores]
                own_score = (match_score[1], match_score[0])
                opponent = left

            games.append({
                "date": date_text,
                "date_obj": self._parse_match_date(date_text),
                "date_text": date_text,
                "league": league,
                "teams": teams_text,
                "opponent": opponent,
                "score": score_text,
                "match_score": own_score,
                "sets": own_sets,
                "num_sets": len(own_sets),
                "set_totals": [a + b for a, b in own_sets],
                "match_total": sum(a + b for a, b in own_sets),
                "won": own_score[0] > own_score[1],
            })
        games.sort(key=lambda g: g["date_obj"] or datetime.min, reverse=True)
        return games[:10]

    @staticmethod
    def _parse_page_total(table):
        page = {}
        rows = table.find_all("tr")
        if not rows:
            return page
        header_cells = [cell.get_text(" ", strip=True)
                        for cell in rows[0].find_all(["td", "th"])]
        if header_cells:
            match = re.search(r"(\d+(?:[.,]\d+)?)", header_cells[0])
            if match:
                try:
                    page["line"] = float(match.group(1).replace(",", "."))
                except Exception:
                    pass
        for row in rows[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if len(cells) < 3:
                continue
            label = cells[0].lower()
            try:
                under = int(re.sub(r"\D", "", cells[1]) or 0)
                over = int(re.sub(r"\D", "", cells[2]) or 0)
            except Exception:
                continue
            if "последн" in label:
                page["last5_under"] = under
                page["last5_over"] = over
            elif "чемпионат" in label:
                page["season_under"] = under
                page["season_over"] = over
        return page

    # ---------- live-матчи ----------
    def get_live_matches(self):
        try:
            resp = self.session.get(BETCITY_API, params=BETCITY_PARAMS,
                                    cookies=BETCITY_COOKIES,
                                    headers=BETCITY_HEADERS, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            sports = (data.get("reply") or {}).get("sports") or {}
            tennis = sports.get("46") or {}
            matches = []

            for champ in (tennis.get("chmps") or {}).values():
                league = champ.get("name_ch", "")
                for raw in (champ.get("evts") or {}).values():
                    try:
                        team1, team2 = raw["name_ht"], raw["name_at"]
                        date_str = raw["date_ev_str"]
                        score = raw.get("sc_inter", "0:0")
                        stat_link = raw.get("stat_link", "")
                        o1, o2 = self._extract_match_odds(raw)
                        if not o1 or not o2:
                            continue
                        odds = {
                            "match_p1": o1, "match_p2": o2,
                            "set1_p1": o1, "set1_p2": o2,
                            "set1_total_over": None, "set1_total_under": None,
                        }
                        parsed = self._parse_date(date_str)
                        match_id = ("%s_%s_%s" % (team1, team2, date_str)) \
                            .replace(" ", "_").replace(":", "-").replace(".", "-")
                        matches.append({
                            "match_id": match_id,
                            "team1": team1, "team2": team2,
                            "league": league, "date": date_str,
                            "current_score": score,
                            "stat_link": stat_link,
                            "odds": odds,
                            "is_started": score != "0:0",
                            "start_time": parsed.isoformat() if parsed
                            else datetime.now().isoformat(),
                        })
                    except Exception:
                        continue
            return matches
        except Exception as exc:
            logger.error("Получение матчей: %s", exc)
            return []

    # ---------- статистика матча ----------
    def get_match_stats(self, stat_link, team1, team2):
        stats = {
            "team1": team1,
            "team2": team2,
            "h2h_matches": [],
            "recent": {"team1": [], "team2": []},
            "page_total": {},
        }
        if not stat_link:
            return stats
        try:
            resp = self.session.get(BETCITY_STATS + stat_link, timeout=15)
            if resp.status_code != 200:
                return stats
            soup = BeautifulSoup(resp.text, "html.parser")

            h2h_table = None
            recent_tables = []
            for candidate in soup.find_all("table"):
                title_cell = candidate.find("td", class_="title")
                title = title_cell.get_text(" ", strip=True) if title_cell else ""
                if "Очные встречи" in title:
                    if h2h_table is None:
                        h2h_table = candidate
                elif title.lower().startswith("последние игры"):
                    recent_tables.append((title, candidate))
                elif not title:
                    first_row = candidate.find("tr")
                    first_cells = first_row.find_all(["td", "th"]) if first_row else []
                    first_text = first_cells[0].get_text(" ", strip=True) if first_cells else ""
                    if first_text.lower().startswith("тотал"):
                        stats["page_total"] = self._parse_page_total(candidate)

            # последние игры каждого игрока
            for title, table in recent_tables:
                name = title[len("Последние игры"):].strip(" :")
                first_is_team1 = self._names_match(team1, name)
                second_is_team2 = self._names_match(team2, name)
                if first_is_team1 and not second_is_team2:
                    stats["recent"]["team1"] = self._parse_recent_games(table, team1)
                elif second_is_team2 and not first_is_team1:
                    stats["recent"]["team2"] = self._parse_recent_games(table, team2)
                elif first_is_team1:
                    stats["recent"]["team1"] = self._parse_recent_games(table, team1)
                elif second_is_team2:
                    stats["recent"]["team2"] = self._parse_recent_games(table, team2)

            if h2h_table is None:
                return stats

            rows = h2h_table.find_all("tr")
            for index in range(2, len(rows)):
                cells = rows[index].find_all("td")
                if len(cells) < 3:
                    continue
                date_text = cells[0].get_text(strip=True)
                teams_text = cells[1].get_text(strip=True)
                score_text = cells[2].get_text(strip=True)
                parts = re.split(r"[-—]", teams_text)
                if len(parts) < 2:
                    continue
                player1, player2 = parts[0].strip(), parts[1].strip()
                match_score = re.search(r"(\d+):(\d+)", score_text)
                if not match_score:
                    continue
                ms1, ms2 = int(match_score.group(1)), int(match_score.group(2))
                all_sets = re.findall(r"(\d+):(\d+)", score_text)
                if len(all_sets) > 1:
                    if int(all_sets[0][0]) == ms1 and int(all_sets[0][1]) == ms2:
                        set_scores = all_sets[1:]
                    else:
                        set_scores = all_sets
                else:
                    set_scores = []
                parsed_sets = []
                for pair in set_scores:
                    try:
                        parsed_sets.append((int(pair[0]), int(pair[1])))
                    except Exception:
                        continue
                first_set = parsed_sets[0] if parsed_sets else None
                first_total = (first_set[0] + first_set[1]) if first_set else None
                stats["h2h_matches"].append({
                    "date": date_text,
                    "date_obj": self._parse_match_date(date_text),
                    "teams": teams_text,
                    "score": score_text,
                    "match_score": "%d:%d" % (ms1, ms2),
                    "sets_parsed": parsed_sets,
                    "num_sets": len(parsed_sets),
                    "first_set": first_set,
                    "first_set_total": first_total,
                    "winner": "P1" if ms1 > ms2 else "P2",
                    "player1": player1,
                    "player2": player2,
                })
            stats["h2h_matches"] = sorted(
                stats["h2h_matches"],
                key=lambda x: x["date_obj"] if x["date_obj"] else datetime.min,
                reverse=True,
            )[:20]
        except Exception as exc:
            logger.error("parse: %s", exc)
        return stats

    # ---------- последовательности ----------
    def _build_set_sequences(self, set_index, h2h, stats):
        winner_seq, total_seq = [], []
        for match in reversed(h2h):
            sets = match.get("sets_parsed") or []
            if len(sets) < set_index:
                continue
            player1 = match.get("player1", "")
            a, b = sets[set_index - 1]
            total_seq.append("TM" if (a + b) < PROB_THRESHOLD else "TO")
            if self._names_match(stats["team1"], player1):
                winner_seq.append("T1" if a > b else "T2")
            elif self._names_match(stats["team2"], player1):
                winner_seq.append("T2" if a > b else "T1")
        return winner_seq, total_seq

    # ---------- фильтры ----------
    def _check_general_filters(self, agg, label=""):
        filters = self.settings.snapshot()["general_filters"]
        if agg.get("prediction") is None:
            return False, "нет топа"
        if agg["strong"] < int(filters.get("min_strong", 1)):
            return False, "strong %d < %d" % (agg["strong"], int(filters["min_strong"]))
        if agg["agreement"] < float(filters.get("min_agreement", 0.20)):
            return False, "agreement %.1f%% < %d%%" % (
                agg["agreement"] * 100, int(filters["min_agreement"] * 100))
        if agg["confidence"] < float(filters.get("min_confidence", 0.10)):
            return False, "confidence %.1f%% < %d%%" % (
                agg["confidence"] * 100, int(filters["min_confidence"] * 100))
        active = [m for m in agg["models"] if m.get("prediction") is not None]
        if len(active) < int(filters.get("min_active", 1)):
            return False, "активных %d < %d" % (len(active), int(filters["min_active"]))
        return True, ""

    def _check_settings_filters(self, agg, label=""):
        active = [m for m in agg["models"] if m.get("prediction") is not None]
        names = [m["name"] for m in active]
        missing = [r for r in self.settings.get_required_models() if r not in names]
        if missing:
            return False, "нет обязательных: %s" % ", ".join(missing)
        for model in active:
            threshold = self.settings.get_model_threshold(model["name"])
            # Порог 0 = проверка отключена для этой модели
            if threshold > 0 and model["wilson_lower"] < threshold:
                return False, "%s: %.1f%% < %d%%" % (
                    model["name"], model["wilson_lower"] * 100, int(threshold * 100))
        return True, ""

    def _is_bet_allowed(self, kind, verdict, threshold=None):
        if kind == "winner":
            return self.settings.is_bet_allowed("П1" if verdict == "П1" else "П2")
        if kind == "total" and threshold == 18.5:
            if "ТБ" in verdict:
                return self.settings.is_bet_allowed("ТБ18.5")
            if "ТМ" in verdict:
                return self.settings.is_bet_allowed("ТМ18.5")
        return False

    # ---------- анализ ----------
    def _analyze_one(self, seq, kind, target, label, odds=None):
        if not seq:
            return None
        if len(seq) < STREAK_MIN + 1:
            self.stats["short_seq"] += 1
            return None

        vote_base = self.settings.get_vote_weight_base()
        ensemble = ProbabilityEnsemble(seq, self._opposite, vote_weight_base=vote_base)
        agg = ensemble.aggregate()
        if not agg:
            self.stats["no_top"] += 1
            return None

        if self.settings.is_verbose():
            parts = [
                "%s=%s(%.0f%%)" % (m["name"], m["prediction"], m["wilson_lower"] * 100)
                if m.get("prediction") else "%s=None" % m["name"]
                for m in agg["models"]
            ]
            logger.info("      🔍 %s: models=[%s] top=%s strong=%s agree=%.0f%% conf=%.1f%% vote_base=%.2f",
                        label, ", ".join(parts), agg.get("prediction"),
                        agg.get("strong"), agg.get("agreement", 0) * 100,
                        agg.get("confidence", 0) * 100, vote_base)

        ok, reason = self._check_general_filters(agg, label)
        if not ok:
            logger.info("      ❌ %s: %s", label, reason)
            if reason == "нет топа":
                self.stats["no_top"] += 1
            else:
                self.stats["blocked_general"] += 1
            return None

        ok, reason = self._check_settings_filters(agg, label)
        if not ok:
            logger.info("      ⛔ %s: %s", label, reason)
            self.stats["blocked_settings"] += 1
            return None

        raw = agg["prediction"]
        if kind == "total":
            verdict = "ТМ 18.5" if raw == "TM" else "ТБ 18.5"
            expected_side = "under" if raw == "TM" else "over"
            threshold = 18.5
        else:
            verdict = "П1" if raw == "T1" else "П2"
            expected_side = verdict
            threshold = None

        if not self._is_bet_allowed(kind, verdict, threshold):
            self.stats["blocked_settings"] += 1
            return None
        if target.startswith("set") and not self.settings.is_set_allowed(target):
            self.stats["blocked_settings"] += 1
            return None

        odds_enabled = bool(self.settings.snapshot().get("odds_check_enabled", True))
        if odds_enabled and odds and target == "set1":
            if kind == "total":
                over = odds.get("set1_total_over")
                under = odds.get("set1_total_under")
                if over is not None and under is not None:
                    if expected_side == "under" and over < under:
                        self.stats["blocked_odds"] += 1
                        return None
                    if expected_side == "over" and under < over:
                        self.stats["blocked_odds"] += 1
                        return None
            else:
                p1_odds, p2_odds = odds.get("set1_p1"), odds.get("set1_p2")
                if p1_odds is not None and p2_odds is not None:
                    ours = p1_odds if expected_side == "П1" else p2_odds
                    theirs = p2_odds if expected_side == "П1" else p1_odds
                    if ours > theirs:
                        self.stats["blocked_odds"] += 1
                        return None

        ordered = sorted(agg["models"],
                         key=lambda m: (m["name"] == "streak", -m["wilson_lower"]))
        parts = ["%s=%s(%.0f%%)" % (m["name"], m["prediction"], m["wilson_lower"] * 100)
                 for m in ordered if m.get("prediction")]
        models_info = "Модели: " + ", ".join(parts)
        logger.info("      ✅ %s: %s | %s", label, verdict, models_info)

        non_streak = [m for m in agg["models"] if m["name"] != "streak"]
        min_wilson = min((m["wilson_lower"] for m in non_streak), default=0.0)

        return {
            "target": target, "label": label, "kind": kind,
            "expected_side": expected_side, "threshold": threshold,
            "verdict": verdict,
            "confidence_val": agg["confidence"],
            "min_model_wilson": min_wilson,
            "strong": agg["strong"],
            "agreement": agg["agreement"],
            "models_info": models_info,
        }

    def _analyze_all(self, stats, odds):
        h2h = stats.get("h2h_matches") or []
        if len(h2h) < self.settings.get_min_h2h():
            self.stats["no_h2h"] += 1
            return []

        predictions = []
        for set_index in range(1, 6):
            winner_seq, total_seq = self._build_set_sequences(set_index, h2h, stats)
            if winner_seq:
                result = self._analyze_one(
                    winner_seq, "winner", "set%d" % set_index,
                    "Партия %d (П1/П2)" % set_index, odds)
                if result:
                    predictions.append(result)
            if total_seq:
                result = self._analyze_one(
                    total_seq, "total", "set%d" % set_index,
                    "Партия %d (ТБ18.5/ТМ18.5)" % set_index, odds)
                if result:
                    predictions.append(result)

        best = {}
        for prediction in predictions:
            key = (prediction["target"], prediction["kind"])
            if key not in best or \
                    prediction["confidence_val"] > best[key]["confidence_val"]:
                best[key] = prediction
        return list(best.values())

    # ---------- сообщение ----------
    def format_prediction_message(self, match, predictions):
        bet_size = float(self.settings.snapshot().get("bet_size_percent", 2.0))
        lines = ["🔴 <b>LIVE: %s vs %s</b>" % (match["team1"], match["team2"])]
        if match.get("start_time"):
            lines.append("⏰ Начало: %s" % match["start_time"][:16].replace("T", " "))
        if match.get("league"):
            lines.append("🏆 Лига: %s" % match["league"])
        lines.append("")
        lines.append("📊 <b>ПРОГНОЗЫ:</b>")
        for pred in predictions:
            lines.append("   • <b>%s:</b> %s" % (pred["label"], pred["verdict"]))
            lines.append("     %s" % pred["models_info"])
        if predictions:
            per = round(bet_size / len(predictions), 2)
            lines.append("")
            lines.append("💰 <b>Ставка: %s%%</b> (по %s%% на каждый)" % (bet_size, per))
        lines.append("")
        lines.append("🔄 Отслеживание по всем партиям")
        lines.append("─" * 40)
        return "\n".join(lines)

    # ---------- один цикл ----------
    def run_cycle(self):
        """Один цикл анализа. Возвращает краткую статистику."""
        summary = {"matches": 0, "upcoming": 0, "signals": 0, "error": None}
        try:
            if self.result_checker and not self.checker_thread:
                self.checker_thread = threading.Thread(
                    target=self.result_checker.run, daemon=True)
                self.checker_thread.daemon = True
                self.checker_thread.start()

            # Отчёты по расписанию имеют смысл только при подключённом Telegram.
            if self.report_manager and not self.telegram.offline:
                try:
                    self.report_manager.check_and_send()
                except Exception as exc:
                    logger.error("Отчёты: %s", exc)

            if not self.settings.is_running():
                return summary

            matches = self.get_live_matches()
            summary["matches"] = len(matches)
            self._live_matches = len(matches)
            if not matches:
                self._last_cycle = datetime.now()
                return summary

            upcoming = [m for m in matches if not m["is_started"]]
            summary["upcoming"] = len(upcoming)
            logger.info("📊 Всего матчей: %d, скоро: %d", len(matches), len(upcoming))

            for match in upcoming:
                self.stats["checked"] += 1
                if self.telegram.is_prediction_sent(
                        match["team1"], match["team2"], match["date"]):
                    continue
                if self.is_processed(match["match_id"]):
                    continue

                logger.info("Анализ: %s vs %s", match["team1"], match["team2"])
                stats = self.get_match_stats(
                    match["stat_link"], match["team1"], match["team2"])
                stats["league"] = match["league"]

                mode = self.settings.get_algorithm_mode()
                fired = []
                skip_info = None
                if mode == "constructor":
                    predictions, fired, skip_info = self.constructor.evaluate(
                        match, stats)
                    if skip_info:
                        logger.info("⏭ Конструктор: %s vs %s — правило «%s»",
                                    match["team1"], match["team2"],
                                    skip_info.get("rule", ""))
                        self.stats["skipped"] += 1
                        self.mark_processed(match["match_id"])
                        time.sleep(0.5)
                        continue
                    if fired:
                        logger.info("🧩 Конструктор: %s vs %s — правил %d, прогнозов %d",
                                    match["team1"], match["team2"],
                                    len(fired), len(predictions))
                else:
                    predictions = self._analyze_all(stats, match["odds"])

                if not predictions:
                    self.stats["skipped"] += 1
                    self.mark_processed(match["match_id"])
                    time.sleep(0.5)
                    continue

                logger.info("✅ Сигналов: %d (%s vs %s)",
                            len(predictions), match["team1"], match["team2"])
                message = self.format_prediction_message(match, predictions)
                message_id = self.telegram.send_message(message)
                if message_id:
                    pred_id = self.telegram.mark_prediction_sent(
                        match["team1"], match["team2"], match["date"],
                        predictions, message_id, match.get("league", ""),
                        analyzer.make_sample(match, stats), message_text=message)
                    first = predictions[0]
                    rule_name = "ENSEMBLE_MULTI"
                    if first.get("source") == "constructor":
                        rule_name = "CONSTRUCTOR:%s" % first.get("rule_name", "")
                    row = {
                        "datetime": self.telegram.sent_predictions[pred_id].get("sent_at", ""),
                        "teams": "%s vs %s" % (match["team1"], match["team2"]),
                        "league": match.get("league", ""),
                        "rule": rule_name,
                        "prediction": first.get("verdict", ""),
                        "confidence_claimed": "%.1f%%" % (first.get("confidence_val", 0) * 100),
                        "ensemble_details": first.get("models_info", ""),
                        "odds_info": "",
                    }
                    try:
                        self.bets_logger.log_bet(row)
                    except Exception:
                        pass
                    self.stats["sent"] += 1
                    summary["signals"] += 1
                    for pred in predictions:
                        key = "%s:%s" % (pred["target"], pred["kind"])
                        self.stats["by_target"][key] = \
                            self.stats["by_target"].get(key, 0) + 1

                    if self.settings.get_notifications().get("on_signal", True):
                        notify_android(
                            "Сигнал: %s — %s" % (match["team1"], match["team2"]),
                            ", ".join("%s: %s" % (p["label"], p["verdict"])
                                      for p in predictions[:3]))
                self.mark_processed(match["match_id"])
                time.sleep(0.5)

            self._last_cycle = datetime.now()
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            summary["error"] = str(exc)
            logger.error("Цикл: %s", exc)
            logger.debug(traceback.format_exc())
            if self.settings.get_notifications().get("on_error", True):
                notify_android("Ошибка движка", str(exc)[:180])
        return summary

    # ---------- статус ----------
    def status_payload(self):
        with self._lock:
            stats = json.loads(json.dumps(self.stats))
        return {
            "running": self.settings.is_running(),
            "stats": stats,
            "last_cycle": self._last_cycle.strftime("%H:%M:%S") if self._last_cycle else None,
            "last_error": self._last_error,
            "live_matches": self._live_matches,
            "processed": len(self.processed_matches),
            "algorithm_mode": self.settings.get_algorithm_mode(),
            "constructor": self.constructor.stats_payload(),
            "telegram_configured": bool(
                self.settings.get_telegram().get("token") and
                self.settings.get_telegram().get("chat_id")),
        }

    def reset_stats(self):
        with self._lock:
            for key in ("checked", "sent", "skipped", "blocked_odds",
                        "blocked_settings", "blocked_general",
                        "no_h2h", "short_seq", "no_top"):
                self.stats[key] = 0
            self.stats["by_target"] = {}

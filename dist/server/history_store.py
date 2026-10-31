# -*- coding: utf-8 -*-
"""Хранилище истории устройств, правил и рекомендаций.

Модуль работает на стандартной библиотеке: SQLite лежит рядом с серверным
бандлом (каталог можно переопределить переменной ``PREDICTOR_DATA_DIR``).
Приложение периодически присылает снимок истории и правил, а сервер:

* обновляет текущие правила и фиксирует каждое изменение (diff before/after);
* складывает прогнозы и результаты, чтобы считать точность по правилам;
* пересчитывает рекомендации тем же ``rule_advisor``, что и приложение;
* отслеживает жизненный цикл рекомендации: открыта → применена/скрыта/закрыта;
* считает «до/после» по фактическим результатам правила.

Никаких персональных данных, кроме названия устройства и спортивной истории,
не сохраняется.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (
    os.path.join(HERE, "python"),
    os.path.join(os.path.dirname(HERE), "app", "src", "main", "python"),
):
    if os.path.isdir(_candidate):
        import sys
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)

import constructor_engine as ce  # noqa: E402
import profit  # noqa: E402
import rule_advisor  # noqa: E402
import sports as sport_catalog  # noqa: E402

SERVER_VERSION = "1.19.0"
SCHEMA_VERSION = 1
MAX_DEVICE_ROWS = 40000
RETENTION_DAYS = 400
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(HERE), "data")
DATA_DIR = os.path.abspath(
    os.environ.get("PREDICTOR_DATA_DIR") or DEFAULT_DATA_DIR)
DB_PATH = os.path.join(DATA_DIR, "predictor.sqlite3")

_INIT_LOCK = threading.Lock()
_INITIALIZED = False


# --------------------------------------------------------------------------
# утилиты
# --------------------------------------------------------------------------

def _now_dt():
    return datetime.now().replace(microsecond=0)


def _now_iso():
    return _now_dt().isoformat()


def _clean(value, limit=2000):
    text = str(value if value is not None else "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for candidate in (text, text[:19], text[:16], text[:10]):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:len(fmt) + 2], fmt)
        except ValueError:
            continue
    return None


def _iso(value):
    parsed = _parse_dt(value)
    return parsed.isoformat() if parsed else _clean(value, 40)


def _json(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      default=str, separators=(",", ":"))


def _sha(value):
    return hashlib.sha1(_dump(value).encode("utf-8")).hexdigest()


_SECRET_MARKERS = ("token", "secret", "password", "passwd", "api_key",
                   "apikey", "access_key", "private")


def _safe_settings(value, depth=0):
    """Убирает из настроек всё, что похоже на секрет.

    Приложение и так отправляет только параметры анализа, но старые
    версии могли прислать весь снимок настроек. Токены не должны попадать
    в базу и тем более в веб-кабинет.
    """
    if depth > 6:
        return ""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            name = str(key or "").lower()
            if any(marker in name for marker in _SECRET_MARKERS):
                continue
            if name in ("telegram", "proxy"):
                continue
            result[str(key)] = _safe_settings(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_settings(item, depth + 1) for item in value[:200]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)[:400]


def _connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=25)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=25000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        os.makedirs(DATA_DIR, exist_ok=True)
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    name TEXT DEFAULT '',
                    alias TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    platform TEXT DEFAULT '',
                    app_version TEXT DEFAULT '',
                    first_seen TEXT,
                    last_seen TEXT,
                    sync_count INTEGER DEFAULT 0,
                    settings_json TEXT DEFAULT '{}',
                    meta_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS prediction_rows (
                    device_id TEXT NOT NULL,
                    pred_id TEXT NOT NULL,
                    row_key TEXT NOT NULL,
                    sport TEXT DEFAULT '',
                    rule_id TEXT DEFAULT '',
                    rule_name TEXT DEFAULT '',
                    team1 TEXT DEFAULT '',
                    team2 TEXT DEFAULT '',
                    league TEXT DEFAULT '',
                    sent_at TEXT,
                    target TEXT DEFAULT '',
                    kind TEXT DEFAULT '',
                    label TEXT DEFAULT '',
                    verdict TEXT DEFAULT '',
                    confidence REAL,
                    odds REAL,
                    success INTEGER,
                    score TEXT DEFAULT '',
                    total REAL,
                    checked_from TEXT DEFAULT '',
                    source TEXT DEFAULT 'rule',
                    updated_at TEXT,
                    PRIMARY KEY (device_id, pred_id, row_key)
                );
                CREATE INDEX IF NOT EXISTS idx_pred_sent
                    ON prediction_rows(device_id, sent_at);
                CREATE INDEX IF NOT EXISTS idx_pred_rule
                    ON prediction_rows(device_id, sport, rule_id, sent_at);
                CREATE INDEX IF NOT EXISTS idx_pred_checked
                    ON prediction_rows(device_id, success, sent_at);

                CREATE TABLE IF NOT EXISTS rules (
                    device_id TEXT NOT NULL,
                    sport TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    enabled INTEGER DEFAULT 1,
                    priority INTEGER DEFAULT 100,
                    fingerprint TEXT DEFAULT '',
                    conditions_json TEXT DEFAULT '{}',
                    action_json TEXT DEFAULT '{}',
                    conditions_text TEXT DEFAULT '',
                    action_text TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    auto INTEGER DEFAULT 0,
                    stop INTEGER DEFAULT 0,
                    auto_kind TEXT DEFAULT '',
                    auto_target TEXT DEFAULT '',
                    first_seen TEXT,
                    last_seen TEXT,
                    last_change_at TEXT,
                    change_count INTEGER DEFAULT 0,
                    deleted_at TEXT,
                    PRIMARY KEY (device_id, sport, rule_id)
                );
                CREATE INDEX IF NOT EXISTS idx_rules_device
                    ON rules(device_id, sport, deleted_at);

                CREATE TABLE IF NOT EXISTS rule_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    sport TEXT DEFAULT '',
                    rule_id TEXT DEFAULT '',
                    rule_name TEXT DEFAULT '',
                    at TEXT NOT NULL,
                    kind TEXT DEFAULT 'updated',
                    source TEXT DEFAULT 'sync',
                    rec_id TEXT DEFAULT '',
                    before_json TEXT,
                    after_json TEXT,
                    changes_json TEXT DEFAULT '[]',
                    summary TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_events_device
                    ON rule_events(device_id, at);
                CREATE INDEX IF NOT EXISTS idx_events_rule
                    ON rule_events(device_id, sport, rule_id, at);

                CREATE TABLE IF NOT EXISTS recommendations (
                    device_id TEXT NOT NULL,
                    rec_id TEXT NOT NULL,
                    sport TEXT DEFAULT '',
                    rule_id TEXT DEFAULT '',
                    rule_name TEXT DEFAULT '',
                    type TEXT DEFAULT '',
                    type_title TEXT DEFAULT '',
                    severity TEXT DEFAULT 'info',
                    reason TEXT DEFAULT '',
                    condition_text TEXT DEFAULT '',
                    target_rule_json TEXT DEFAULT '{}',
                    rec_json TEXT DEFAULT '{}',
                    precision_before REAL,
                    precision_after REAL,
                    gain REAL,
                    first_seen TEXT,
                    last_seen TEXT,
                    seen_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'open',
                    status_reason TEXT DEFAULT '',
                    applied_at TEXT,
                    resolved_at TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (device_id, rec_id)
                );
                CREATE INDEX IF NOT EXISTS idx_rec_device
                    ON recommendations(device_id, status, first_seen);

                CREATE TABLE IF NOT EXISTS advisor_state (
                    device_id TEXT PRIMARY KEY,
                    state_json TEXT DEFAULT '{}',
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    at TEXT NOT NULL,
                    app_version TEXT DEFAULT '',
                    summary_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_sync_device
                    ON sync_log(device_id, at);

                PRAGMA user_version=1;
                """
            )
            _migrate(conn)
            conn.commit()
        finally:
            conn.close()
        _INITIALIZED = True


def _migrate(conn):
    """Добавляет новые колонки к уже созданной базе без потери истории."""
    columns = {row["name"] for row in conn.execute(
        "PRAGMA table_info(prediction_rows)")}
    if "odds" not in columns:
        conn.execute("ALTER TABLE prediction_rows ADD COLUMN odds REAL")


def _row_get(row, key, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


# --------------------------------------------------------------------------
# нормализация входящего снимка
# --------------------------------------------------------------------------

def _rule_payload(rule, sport):
    if not isinstance(rule, dict):
        return None
    clean = {
        "id": str(rule.get("id") or ("r_" + uuid.uuid4().hex[:10])),
        "name": _clean(rule.get("name") or "Правило", 200),
        "sport": sport,
        "enabled": bool(rule.get("enabled", True)),
        "priority": _int(rule.get("priority", 100), 100),
        "stop": bool(rule.get("stop", False)),
        "conditions": rule.get("conditions") if isinstance(
            rule.get("conditions"), dict) else {"logic": "and", "conditions": []},
        "action": rule.get("action") if isinstance(rule.get("action"), dict) else {},
        "auto": bool(rule.get("auto")),
        "auto_kind": _clean(rule.get("auto_kind"), 40),
        "auto_target": _clean(rule.get("auto_target"), 60),
    }
    if rule.get("auto_created_at"):
        clean["auto_created_at"] = _clean(rule.get("auto_created_at"), 40)
    return clean


def _rule_fingerprint(rule):
    return _sha({
        "name": rule.get("name"),
        "enabled": bool(rule.get("enabled", True)),
        "priority": rule.get("priority"),
        "stop": bool(rule.get("stop", False)),
        "conditions": rule.get("conditions"),
        "action": rule.get("action"),
    })


def _rule_texts(rule, sport):
    try:
        conditions_text = ce.describe_group(
            rule.get("conditions") or {}, sport=sport)
    except Exception:
        conditions_text = ""
    try:
        action_text = ce.describe_action(rule.get("action") or {}, sport=sport)
    except Exception:
        action_text = ""
    try:
        summary = ce.describe_rule(rule, sport)
    except Exception:
        summary = " ".join(item for item in (conditions_text, action_text) if item)
    return conditions_text, action_text, summary


def _condition_text(condition, sport):
    try:
        return ce.describe_condition(condition, sport=sport)
    except Exception:
        return _clean(_dump(condition), 300)


def _diff_rules(old, new, sport):
    """Возвращает (changes, summary) для человекочитаемой истории."""
    if old is None:
        texts = [_condition_text(item, sport)
                 for item in rule_advisor._flatten((new or {}).get("conditions"))]
        action = _clean((new or {}).get("action_text") or "", 300)
        if not action:
            try:
                action = ce.describe_action((new or {}).get("action") or {},
                                            sport=sport)
            except Exception:
                action = ""
        parts = texts[:6]
        summary = "Правило создано"
        if parts:
            summary += " · " + "; ".join(parts)
        if action:
            summary += " → " + action
        return [], summary[:900]

    changes = []

    def add(field, label, before, after):
        changes.append({
            "field": field, "label": label,
            "before": before, "after": after,
        })

    if old.get("name") != new.get("name"):
        add("name", "Название", old.get("name") or "", new.get("name") or "")
    if bool(old.get("enabled", True)) != bool(new.get("enabled", True)):
        add("enabled", "Состояние",
            "включено" if old.get("enabled", True) else "выключено",
            "включено" if new.get("enabled", True) else "выключено")
    if _int(old.get("priority")) != _int(new.get("priority")):
        add("priority", "Приоритет", _int(old.get("priority")),
            _int(new.get("priority")))
    if bool(old.get("stop")) != bool(new.get("stop")):
        add("stop", "Останавливать проверку",
            "да" if old.get("stop") else "нет",
            "да" if new.get("stop") else "нет")

    old_group = old.get("conditions") or {}
    new_group = new.get("conditions") or {}
    old_logic = str(old_group.get("logic") or "and").lower()
    new_logic = str(new_group.get("logic") or "and").lower()
    if old_logic != new_logic:
        add("logic", "Логика группы", old_logic.upper(), new_logic.upper())

    old_flat = rule_advisor._flatten(old_group)
    new_flat = rule_advisor._flatten(new_group)
    old_keys = {rule_advisor.condition_key(item): item for item in old_flat}
    new_keys = {rule_advisor.condition_key(item): item for item in new_flat}
    for key, item in new_keys.items():
        if key in old_keys:
            continue
        changes.append({
            "field": "condition_added",
            "label": "Добавлено условие",
            "before": "",
            "after": _condition_text(item, sport),
        })
    for key, item in old_keys.items():
        if key in new_keys:
            continue
        changes.append({
            "field": "condition_removed",
            "label": "Удалено условие",
            "before": _condition_text(item, sport),
            "after": "",
        })

    old_action = old.get("action") or {}
    new_action = new.get("action") or {}
    action_fields = (
        ("type", "Тип ставки"), ("targets", "Партии"), ("side", "Сторона"),
        ("threshold", "Порог"), ("value", "Фора"), ("confidence", "Уверенность"),
        ("scope", "Охват"),
    )
    for field, label in action_fields:
        before = old_action.get(field)
        after = new_action.get(field)
        if field == "confidence":
            before = round(_num(before, 0) * 100, 1)
            after = round(_num(after, 0) * 100, 1)
            label = "Уверенность, %"
        if field == "threshold":
            before = _num(before)
            after = _num(after)
        if before == after:
            continue
        add("action." + field, label, before, after)

    if not changes:
        if _sha(old) != _sha(new):
            add("other", "Служебные поля", "было", "стало")
        else:
            return [], ""

    parts = []
    for item in changes[:6]:
        label = item["label"]
        before, after = item["before"], item["after"]
        if item["field"] == "condition_added":
            parts.append("Добавлено условие: %s" % after)
        elif item["field"] == "condition_removed":
            parts.append("Удалено условие: %s" % before)
        elif before in ("", None) and after not in ("", None):
            parts.append("%s: %s" % (label, after))
        elif after in ("", None) and before not in ("", None):
            parts.append("%s: убрано (%s)" % (label, before))
        else:
            parts.append("%s: %s → %s" % (label, before, after))
    return changes, "; ".join(parts)[:900]


def _normalize_rules(value):
    """Приводит rules к словарю sport → [rule, ...]."""
    result = {}
    if isinstance(value, dict):
        for sport, items in value.items():
            sport_id = sport_catalog.normalize_sport(sport or "table_tennis")
            if not isinstance(items, list):
                continue
            cleaned = [_rule_payload(item, sport_id) for item in items
                       if isinstance(item, dict)]
            result[sport_id] = [item for item in cleaned if item]
    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            sport_id = sport_catalog.normalize_sport(
                item.get("sport") or "table_tennis")
            payload = _rule_payload(item, sport_id)
            if payload:
                result.setdefault(sport_id, []).append(payload)
    return result


def _result_for(pred, target, kind):
    for result in pred.get("set_results") or []:
        if not isinstance(result, dict):
            continue
        if str(result.get("target")) != str(target):
            continue
        result_kind = str(result.get("kind") or "")
        if result_kind and kind and result_kind != str(kind):
            continue
        return result
    return {}


def _prediction_rows(pred_id, pred, source="rule"):
    if not isinstance(pred, dict):
        return []
    sport = sport_catalog.normalize_sport(pred.get("sport") or "table_tennis")
    sent_at = _iso(pred.get("sent_at") or pred.get("date") or "")
    team1 = _clean(pred.get("team1"), 160)
    team2 = _clean(pred.get("team2"), 160)
    league = _clean(pred.get("league"), 160)
    items = pred.get("predictions") if source == "rule" else pred.get("ai_predictions")
    if not isinstance(items, list):
        items = []
    match = ((pred.get("stats") or {}).get("match") or {})
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target") or "")
        kind = str(item.get("kind") or "")
        label = _clean(item.get("label") or target, 120)
        result = _result_for(pred, target, kind)
        success = result.get("success")
        if success is not None:
            success = 1 if success else 0
        confidence = item.get("confidence_val")
        try:
            confidence = round(float(confidence), 4) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        total = result.get("total")
        try:
            total = float(total) if total is not None else None
        except (TypeError, ValueError):
            total = None
        odds = profit.odds_from_match(item, match)
        rows.append({
            "device_id": "",
            "pred_id": str(pred_id),
            "row_key": "%s|%s|%s|%s" % (source, target, kind, label),
            "sport": sport,
            "rule_id": str(item.get("rule_id") or "") if source == "rule" else "",
            "rule_name": _clean(item.get("rule_name"), 160) if source == "rule" else "",
            "team1": team1, "team2": team2, "league": league,
            "sent_at": sent_at,
            "target": target, "kind": kind, "label": label,
            "verdict": _clean(item.get("verdict"), 160),
            "confidence": confidence,
            "odds": odds,
            "success": success,
            "score": _clean(result.get("score"), 60),
            "total": total,
            "checked_from": _clean(result.get("checked_from"), 40),
            "source": source,
            "updated_at": _now_iso(),
        })
    if not rows and source == "rule":
        # Матч без прогнозов всё равно полезен для счётчиков.
        rows.append({
            "device_id": "", "pred_id": str(pred_id),
            "row_key": "match|none||", "sport": sport,
            "rule_id": "", "rule_name": "",
            "team1": team1, "team2": team2, "league": league,
            "sent_at": sent_at, "target": "", "kind": "",
            "label": "Без прогноза", "verdict": "", "confidence": None,
            "odds": None, "success": None, "score": "", "total": None,
            "checked_from": "", "source": source,
            "updated_at": _now_iso(),
        })
    return rows


# --------------------------------------------------------------------------
# рекомендации и состояние
# --------------------------------------------------------------------------

def _merge_states(server_state, app_state):
    merged = rule_advisor.normalize_state(server_state)
    app = rule_advisor.normalize_state(app_state)
    for bucket in ("seen", "applied", "resolved", "dismissed"):
        for key, value in (app.get(bucket) or {}).items():
            if not isinstance(value, dict):
                continue
            merged.setdefault(bucket, {})[str(key)] = dict(value)
    for key, value in (app.get("seen") or {}).items():
        if not isinstance(value, dict):
            continue
        current = merged.setdefault("seen", {}).get(str(key)) or {}
        first = min(filter(None, [current.get("first_seen"),
                                  value.get("first_seen")]))
        merged["seen"][str(key)] = {
            "first_seen": first or value.get("first_seen") or "",
            "last_seen": max(filter(None, [current.get("last_seen"),
                                           value.get("last_seen")]) or [""]),
            "count": max(_int(current.get("count")), _int(value.get("count"))),
            "type": value.get("type") or current.get("type") or "",
            "sport": value.get("sport") or current.get("sport") or "",
            "rule_id": value.get("rule_id") or current.get("rule_id") or "",
        }
    if app.get("last_run"):
        merged["last_run"] = app.get("last_run")
    if app.get("last_sports"):
        merged["last_sports"] = app.get("last_sports")
    return merged


def _rec_status_from_state(rec_id, rec, app_state, now_iso):
    state = app_state or {}
    applied = (state.get("applied") or {}).get(rec_id)
    if isinstance(applied, dict):
        return "applied", "Применено на устройстве", applied.get("at") or now_iso, ""
    resolved = (state.get("resolved") or {}).get(rec_id)
    if isinstance(resolved, dict):
        return "resolved", _clean(resolved.get("reason") or "Закрыта",
                                  300), "", resolved.get("at") or now_iso
    dismissed = (state.get("dismissed") or {}).get(rec_id)
    if isinstance(dismissed, dict):
        until = str(dismissed.get("until") or "")
        if not until or until >= now_iso:
            return "dismissed", "Скрыта на устройстве", "", ""
    return "", "", "", ""


def _rec_actual_outcome(conn, device_id, rec):
    applied_at = rec.get("applied_at") or rec.get("first_seen")
    if not applied_at:
        return None
    before = _rule_performance(conn, device_id, rec.get("rule_id"),
                               sport=rec.get("sport"), until=applied_at,
                               days=120)
    after = _rule_performance(conn, device_id, rec.get("rule_id"),
                              sport=rec.get("sport"), since=applied_at,
                              days=120)
    if before["resolved"] == 0 and after["resolved"] == 0:
        # Старые версии приложения не всегда сохраняли id правила в
        # прогнозе: тогда эффект считаем по всему виду спорта.
        before = _sport_performance(conn, device_id, rec.get("sport"),
                                    until=applied_at, days=120)
        after = _sport_performance(conn, device_id, rec.get("sport"),
                                   since=applied_at, days=120)
    if before["resolved"] == 0 and after["resolved"] == 0:
        return None
    delta = None
    if before["hit_rate"] is not None and after["hit_rate"] is not None:
        delta = round(after["hit_rate"] - before["hit_rate"], 1)
    delta_roi = None
    if before.get("roi") is not None and after.get("roi") is not None:
        delta_roi = round(after["roi"] - before["roi"], 1)
    delta_ev = None
    if before.get("ev") is not None and after.get("ev") is not None:
        delta_ev = round(after["ev"] - before["ev"], 1)
    money_ready = bool(after.get("value_ready"))
    verdict = "наблюдаем"
    if after["resolved"] < 3:
        verdict = "мало данных после изменения"
    elif money_ready:
        if (delta_roi is not None and delta_roi >= 2.0) or \
                (after.get("ev_lower") or -1) > 0:
            verdict = "лучше"
        elif (delta_roi is not None and delta_roi <= -2.0) or \
                (after.get("ev_lower") is not None and
                 after["ev_lower"] <= -1.0):
            verdict = "хуже"
        else:
            verdict = "без изменений"
    elif delta is not None and delta >= 3:
        verdict = "лучше"
    elif delta is not None and delta <= -3:
        verdict = "хуже"
    else:
        verdict = "без изменений"
    return {
        "before": before, "after": after, "delta": delta,
        "delta_roi": delta_roi, "delta_ev": delta_ev,
        "money_ready": money_ready, "verdict": verdict,
    }


# --------------------------------------------------------------------------
# агрегаты
# --------------------------------------------------------------------------

def _wilson(wins, total, z=1.96):
    if total <= 0:
        return None
    p = wins / float(total)
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5)
    return round((centre - margin) / denominator * 100, 1)


def _row_stats(rows):
    wins = losses = pending = 0
    money_rows = []
    for row in rows:
        success = _row_get(row, "success")
        if success is None:
            pending += 1
        elif success:
            wins += 1
        else:
            losses += 1
        if success is not None:
            money_rows.append({
                "success": bool(success),
                "odds": _row_get(row, "odds"),
            })
    resolved = wins + losses
    money = profit.summarize(money_rows)
    return {
        "wins": wins, "losses": losses, "pending": pending,
        "resolved": resolved, "total": resolved + pending,
        "hit_rate": round(wins * 100.0 / resolved, 1) if resolved else None,
        "wilson": _wilson(wins, resolved),
        "roi": money.get("roi"),
        "ev": money.get("ev"),
        "ev_lower": money.get("ev_lower"),
        "avg_odds": money.get("avg_odds"),
        "odds_n": money.get("odds_n") or 0,
        "profit": money.get("profit"),
        "drawdown": money.get("drawdown"),
        "stake_pct": money.get("stake_pct"),
        "profitable": money.get("profitable"),
        "value_ready": money.get("value_ready"),
    }


def _rule_performance(conn, device_id, rule_id, sport=None, since=None,
                      until=None, days=None):
    clauses = ["device_id = ?", "rule_id = ?", "source = 'rule'"]
    params = [device_id, rule_id]
    if sport:
        clauses.append("sport = ?")
        params.append(sport)
    if since:
        clauses.append("sent_at >= ?")
        params.append(since)
    if until:
        clauses.append("sent_at < ?")
        params.append(until)
    if days:
        clauses.append("sent_at >= ?")
        params.append((_now_dt() - timedelta(days=days)).isoformat())
    sql = ("SELECT success, odds FROM prediction_rows WHERE " +
           " AND ".join(clauses))
    rows = list(conn.execute(sql, params))
    result = _row_stats(rows)
    result["since"] = since or ""
    result["until"] = until or ""
    return result


def _sport_performance(conn, device_id, sport, since=None, until=None,
                       days=None):
    clauses = ["device_id = ?", "source = 'rule'"]
    params = [device_id]
    if sport:
        clauses.append("sport = ?")
        params.append(sport)
    if since:
        clauses.append("sent_at >= ?")
        params.append(since)
    if until:
        clauses.append("sent_at < ?")
        params.append(until)
    if days:
        clauses.append("sent_at >= ?")
        params.append((_now_dt() - timedelta(days=days)).isoformat())
    rows = list(conn.execute(
        "SELECT success, odds FROM prediction_rows WHERE " +
        " AND ".join(clauses), params))
    result = _row_stats(rows)
    result["since"] = since or ""
    result["until"] = until or ""
    return result


def _day_key(value):
    parsed = _parse_dt(value)
    return parsed.strftime("%Y-%m-%d") if parsed else ""


def _daily_series(conn, device_id, days=30):
    since = (_now_dt() - timedelta(days=max(1, days) - 1)).date().isoformat()
    rows = conn.execute(
        "SELECT sent_at, success, odds FROM prediction_rows "
        "WHERE device_id = ? AND source = 'rule' AND sent_at >= ?",
        (device_id, since)).fetchall()
    buckets = {}
    for offset in range(days):
        key = (_now_dt() - timedelta(days=days - 1 - offset)).date().isoformat()
        buckets[key] = {"date": key, "wins": 0, "losses": 0,
                        "pending": 0, "hit_rate": None,
                        "_rows": []}
    for row in rows:
        key = _day_key(row["sent_at"])
        bucket = buckets.get(key)
        if bucket is None:
            continue
        if row["success"] is None:
            bucket["pending"] += 1
        elif row["success"]:
            bucket["wins"] += 1
        else:
            bucket["losses"] += 1
        if row["success"] is not None:
            bucket["_rows"].append({
                "success": bool(row["success"]), "odds": row["odds"]})
    for bucket in buckets.values():
        resolved = bucket["wins"] + bucket["losses"]
        bucket["hit_rate"] = (round(bucket["wins"] * 100.0 / resolved, 1)
                              if resolved else None)
        money = profit.summarize(bucket.pop("_rows"))
        bucket["roi"] = money.get("roi")
        bucket["profit"] = money.get("profit")
        bucket["ev"] = money.get("ev")
        bucket["odds_n"] = money.get("odds_n") or 0
    return list(buckets.values())


def _window_stats(conn, device_id, start, end):
    rows = conn.execute(
        "SELECT success, odds FROM prediction_rows WHERE device_id = ? "
        "AND source = 'rule' AND sent_at >= ? AND sent_at < ?",
        (device_id, start, end)).fetchall()
    return _row_stats(rows)


def _quality(stats, last_seen, rules_count, recs):
    score = 0.0
    reasons = []
    wilson = stats.get("wilson")
    if wilson is not None:
        score += min(55.0, wilson * 0.55)
        reasons.append("точность (Wilson): %.0f%%" % wilson)
    resolved = stats.get("resolved") or 0
    volume = min(20.0, resolved / 100.0 * 20.0)
    score += volume
    if resolved < 10:
        reasons.append("мало проверенных прогнозов")
    elif resolved >= 100:
        reasons.append("хорошая выборка: %d" % resolved)
    checked = stats.get("checked_share")
    if checked is not None:
        score += min(10.0, checked / 100.0 * 10.0)
        if checked < 60:
            reasons.append("низкая доля проверенных")
    minutes = _minutes_since(last_seen)
    if minutes is None:
        score += 0
        reasons.append("нет связи")
    elif minutes <= 30:
        score += 10
        reasons.append("свежие данные")
    elif minutes <= 180:
        score += 6
        reasons.append("данные за последние часы")
    elif minutes <= 1440:
        score += 2
        reasons.append("данные старше 3 часов")
    else:
        reasons.append("устройство давно не выходило на связь")
    if rules_count:
        score += 5
    if (recs or {}).get("applied"):
        score += min(5.0, (recs.get("applied") or 0) * 0.5)
    score = int(round(min(100.0, max(0.0, score))))
    if resolved < 5:
        label = "Мало данных"
    elif score >= 78:
        label = "Надёжно"
    elif score >= 58:
        label = "Стабильно"
    elif score >= 38:
        label = "Средне"
    else:
        label = "Слабо"
    return {"score": score, "label": label, "reasons": reasons[:4]}


def _minutes_since(value):
    parsed = _parse_dt(value)
    if not parsed:
        return None
    return max(0, int((_now_dt() - parsed).total_seconds() // 60))


def _device_stats(conn, device_id):
    rows = conn.execute(
        "SELECT success, odds FROM prediction_rows WHERE device_id = ? "
        "AND source = 'rule'", (device_id,)).fetchall()
    stats = _row_stats(rows)
    resolved = stats["resolved"]
    stats["checked_share"] = (round(resolved * 100.0 /
                                    max(1, stats["total"]), 1)
                              if stats["total"] else None)
    now = _now_dt()
    last7_start = (now - timedelta(days=7)).isoformat()
    prev7_start = (now - timedelta(days=14)).isoformat()
    last7 = _window_stats(conn, device_id, last7_start, now.isoformat() + "~")
    prev7 = _window_stats(conn, device_id, prev7_start, last7_start)
    stats["last7"] = last7
    stats["prev7"] = prev7
    stats["trend"] = (round(last7["hit_rate"] - prev7["hit_rate"], 1)
                      if last7["hit_rate"] is not None
                      and prev7["hit_rate"] is not None else None)
    row = conn.execute(
        "SELECT MAX(sent_at) AS last_result FROM prediction_rows "
        "WHERE device_id = ? AND success IS NOT NULL", (device_id,)).fetchone()
    stats["last_result_at"] = row["last_result"] if row else ""
    active = conn.execute(
        "SELECT COUNT(DISTINCT substr(sent_at, 1, 10)) AS days "
        "FROM prediction_rows WHERE device_id = ?", (device_id,)).fetchone()
    stats["days_active"] = _int(active["days"]) if active else 0
    return stats


def _device_row(conn, row):
    device_id = row["id"]
    stats = _device_stats(conn, device_id)
    rule_counts = conn.execute(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) "
        "AS enabled FROM rules WHERE device_id = ? AND deleted_at IS NULL",
        (device_id,)).fetchone()
    rec_counts = {}
    for item in conn.execute(
            "SELECT status, COUNT(*) AS count FROM recommendations "
            "WHERE device_id = ? GROUP BY status", (device_id,)):
        rec_counts[item["status"]] = _int(item["count"])
    quality = _quality(stats, row["last_seen"],
                       _int(rule_counts["total"]) if rule_counts else 0,
                       rec_counts)
    return {
        "id": device_id,
        "name": row["alias"] or row["name"] or row["model"] or "Устройство",
        "alias": row["alias"] or "",
        "reported_name": row["name"] or "",
        "model": row["model"] or "",
        "platform": row["platform"] or "",
        "app_version": row["app_version"] or "",
        "first_seen": row["first_seen"] or "",
        "last_seen": row["last_seen"] or "",
        "stale_minutes": _minutes_since(row["last_seen"]),
        "sync_count": _int(row["sync_count"]),
        "settings": _json(row["settings_json"], {}),
        "stats": stats,
        "rules": {
            "total": _int(rule_counts["total"]) if rule_counts else 0,
            "enabled": _int(rule_counts["enabled"]) if rule_counts else 0,
        },
        "recs": {
            "open": rec_counts.get("open", 0),
            "applied": rec_counts.get("applied", 0),
            "dismissed": rec_counts.get("dismissed", 0),
            "resolved": rec_counts.get("resolved", 0),
        },
        "quality": quality,
    }


def list_devices():
    init_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM devices ORDER BY last_seen DESC").fetchall()
        devices = []
        for row in rows:
            item = _device_row(conn, row)
            daily = _daily_series(conn, item["id"], days=14)
            item["stats"]["spark"] = [bucket["hit_rate"] for bucket in daily]
            item["stats"]["daily14"] = [
                {"date": bucket["date"], "hit_rate": bucket["hit_rate"],
                 "wins": bucket["wins"], "losses": bucket["losses"],
                 "pending": bucket["pending"]}
                for bucket in daily
            ]
            devices.append(item)
        total = {
            "devices": len(devices),
            "online": sum(1 for item in devices
                          if (item["stale_minutes"] or 99999) <= 30),
            "predictions": sum(item["stats"]["total"] for item in devices),
            "resolved": sum(item["stats"]["resolved"] for item in devices),
            "wins": sum(item["stats"]["wins"] for item in devices),
            "losses": sum(item["stats"]["losses"] for item in devices),
            "open_recs": sum(item["recs"]["open"] for item in devices),
            "applied_recs": sum(item["recs"]["applied"] for item in devices),
            "odds_n": sum(item["stats"].get("odds_n") or 0
                          for item in devices),
            "profit": round(sum(item["stats"].get("profit") or 0.0
                                for item in devices), 2),
            "drawdown": round(max([item["stats"].get("drawdown") or 0.0
                                   for item in devices] or [0.0]), 2),
            "profitable_devices": sum(
                1 for item in devices
                if (item["stats"].get("ev_lower") or -1) > 0),
        }
        resolved = total["resolved"]
        total["hit_rate"] = (round(total["wins"] * 100.0 / resolved, 1)
                             if resolved else None)
        total["roi"] = (round(total["profit"] / total["odds_n"] * 100.0, 1)
                        if total["odds_n"] else None)
        total["avg_odds"] = (
            round(sum((item["stats"].get("avg_odds") or 0.0) *
                      (item["stats"].get("odds_n") or 0)
                      for item in devices) / total["odds_n"], 2)
            if total["odds_n"] else None)
        total["ev"] = (
            round(sum((item["stats"].get("ev") or 0.0) *
                      (item["stats"].get("odds_n") or 0)
                      for item in devices) / total["odds_n"], 1)
            if total["odds_n"] else None)
        return {"ok": True, "devices": devices, "total": total,
                "server_version": SERVER_VERSION, "server_time": _now()}
    finally:
        conn.close()


def _now():
    return _now_dt().strftime("%d.%m.%Y %H:%M:%S")


# --------------------------------------------------------------------------
# приём снимка
# --------------------------------------------------------------------------

def ingest(data):
    """Принимает снимок устройства и возвращает сводку изменений."""
    init_db()
    device = data.get("device") if isinstance(data.get("device"), dict) else {}
    device_id = _clean(device.get("id") or data.get("device_id"), 80)
    if not device_id:
        device_id = "dev_" + hashlib.sha1(
            (_clean(device.get("model"), 80) or "unknown").encode()).hexdigest()[:16]
    now_iso = _now_iso()
    rules_by_sport = _normalize_rules(data.get("rules"))
    predictions = data.get("predictions") if isinstance(
        data.get("predictions"), dict) else {}
    settings = _safe_settings(
        data.get("settings") if isinstance(data.get("settings"), dict) else {})
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    app_version = _clean(device.get("app_version") or meta.get("app_version"), 40)
    name = _clean(device.get("name") or settings.get("device_name"), 120)
    model = _clean(device.get("model") or meta.get("model"), 120)
    platform = _clean(device.get("platform") or meta.get("platform"), 120)

    conn = _connect()
    summary = {"rules": {"created": 0, "updated": 0, "deleted": 0},
               "predictions": 0, "recommendations": {"new": 0, "open": 0,
                                                     "applied": 0, "resolved": 0}}
    try:
        existing = conn.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO devices (id, name, model, platform, app_version, "
                "first_seen, last_seen, sync_count, settings_json, meta_json) "
                "VALUES (?,?,?,?,?,?,?,1,?,?)",
                (device_id, name, model, platform, app_version, now_iso,
                 now_iso, _dump(settings), _dump(meta)))
        else:
            conn.execute(
                "UPDATE devices SET name=COALESCE(NULLIF(?,''), name), "
                "model=COALESCE(NULLIF(?,''), model), "
                "platform=COALESCE(NULLIF(?,''), platform), "
                "app_version=COALESCE(NULLIF(?,''), app_version), "
                "last_seen=?, sync_count=sync_count+1, settings_json=?, "
                "meta_json=? WHERE id=?",
                (name, model, platform, app_version, now_iso, _dump(settings),
                 _dump(meta), device_id))

        # ---------- правила: diff и события ----------
        for sport, incoming in rules_by_sport.items():
            current_rows = conn.execute(
                "SELECT * FROM rules WHERE device_id=? AND sport=? "
                "AND deleted_at IS NULL", (device_id, sport)).fetchall()
            current = {row["rule_id"]: row for row in current_rows}
            seen_ids = set()
            for rule in incoming:
                rule_id = rule["id"]
                seen_ids.add(rule_id)
                fingerprint = _rule_fingerprint(rule)
                conditions_text, action_text, summary_text = _rule_texts(rule, sport)
                previous = current.get(rule_id)
                old_payload = None
                old_fingerprint = None
                if previous is not None:
                    old_payload = {
                        "id": previous["rule_id"],
                        "name": previous["name"],
                        "sport": sport,
                        "enabled": bool(previous["enabled"]),
                        "priority": previous["priority"],
                        "stop": bool(previous["stop"] if "stop" in previous.keys() else False),
                        "conditions": _json(previous["conditions_json"], {}),
                        "action": _json(previous["action_json"], {}),
                        "auto": bool(previous["auto"]),
                    }
                    old_fingerprint = previous["fingerprint"]
                if previous is None:
                    changes, change_summary = _diff_rules(None, rule, sport)
                    kind = "created"
                    summary["rules"]["created"] += 1
                elif old_fingerprint != fingerprint:
                    changes, change_summary = _diff_rules(old_payload, rule, sport)
                    kind = "updated"
                    summary["rules"]["updated"] += 1
                else:
                    changes, change_summary, kind = [], "", ""
                if kind:
                    conn.execute(
                        "INSERT INTO rule_events (device_id, sport, rule_id, "
                        "rule_name, at, kind, source, rec_id, before_json, "
                        "after_json, changes_json, summary) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (device_id, sport, rule_id, rule["name"], now_iso, kind,
                         "sync", "", _dump(old_payload) if old_payload else None,
                         _dump(rule), _dump(changes), change_summary))
                if previous is None:
                    conn.execute(
                        "INSERT INTO rules (device_id, sport, rule_id, name, "
                        "enabled, priority, fingerprint, conditions_json, "
                        "action_json, conditions_text, action_text, summary, "
                        "auto, stop, auto_kind, auto_target, first_seen, "
                        "last_seen, last_change_at, change_count, deleted_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                        (device_id, sport, rule_id, rule["name"],
                         1 if rule["enabled"] else 0, rule["priority"],
                         fingerprint, _dump(rule["conditions"]),
                         _dump(rule["action"]), conditions_text, action_text,
                         summary_text, 1 if rule.get("auto") else 0,
                         1 if rule.get("stop") else 0,
                         rule.get("auto_kind") or "",
                         rule.get("auto_target") or "",
                         now_iso, now_iso, now_iso, 0))
                else:
                    conn.execute(
                        "UPDATE rules SET name=?, enabled=?, priority=?, "
                        "fingerprint=?, conditions_json=?, action_json=?, "
                        "conditions_text=?, action_text=?, summary=?, auto=?, "
                        "stop=?, auto_kind=?, auto_target=?, "
                        "last_seen=?, last_change_at=?, change_count=?, "
                        "deleted_at=NULL WHERE device_id=? AND sport=? "
                        "AND rule_id=?",
                        (rule["name"], 1 if rule["enabled"] else 0,
                         rule["priority"], fingerprint,
                         _dump(rule["conditions"]), _dump(rule["action"]),
                         conditions_text, action_text, summary_text,
                         1 if rule.get("auto") else 0,
                         1 if rule.get("stop") else 0,
                         rule.get("auto_kind") or "",
                         rule.get("auto_target") or "",
                         now_iso,
                         now_iso if kind else previous["last_change_at"],
                         _int(previous["change_count"]) + (1 if kind else 0),
                         device_id, sport, rule_id))
            # правила, которых больше нет в снимке этого вида
            for rule_id, previous in current.items():
                if rule_id in seen_ids:
                    continue
                conn.execute(
                    "UPDATE rules SET deleted_at=?, last_seen=?, "
                    "last_change_at=?, change_count=change_count+1 "
                    "WHERE device_id=? AND sport=? AND rule_id=?",
                    (now_iso, now_iso, now_iso, device_id, sport, rule_id))
                conn.execute(
                    "INSERT INTO rule_events (device_id, sport, rule_id, "
                    "rule_name, at, kind, source, rec_id, before_json, "
                    "after_json, changes_json, summary) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (device_id, sport, rule_id, previous["name"], now_iso,
                     "deleted", "sync", "", _dump({
                         "id": rule_id, "name": previous["name"],
                         "conditions": _json(previous["conditions_json"], {}),
                         "action": _json(previous["action_json"], {}),
                     }), None, _dump([{
                         "field": "deleted", "label": "Правило удалено",
                         "before": previous["name"], "after": "",
                     }]), "Правило удалено из конструктора"))
                summary["rules"]["deleted"] += 1

        # ---------- прогнозы и результаты ----------
        for pred_id, pred in list(predictions.items()):
            if not isinstance(pred, dict):
                continue
            rows = _prediction_rows(pred_id, pred, "rule")
            rows += _prediction_rows(pred_id, pred, "ai")
            keep = {row["row_key"] for row in rows}
            old = conn.execute(
                "SELECT row_key FROM prediction_rows WHERE device_id=? AND "
                "pred_id=?", (device_id, str(pred_id))).fetchall()
            for item in old:
                if item["row_key"] not in keep:
                    conn.execute(
                        "DELETE FROM prediction_rows WHERE device_id=? AND "
                        "pred_id=? AND row_key=?",
                        (device_id, str(pred_id), item["row_key"]))
            for row in rows:
                row["device_id"] = device_id
                conn.execute(
                    "INSERT INTO prediction_rows (device_id, pred_id, row_key, "
                    "sport, rule_id, rule_name, team1, team2, league, sent_at, "
                    "target, kind, label, verdict, confidence, odds, success, "
                    "score, total, checked_from, source, updated_at) "
                    "VALUES (:device_id,:pred_id,:row_key,:sport,:rule_id,"
                    ":rule_name,:team1,:team2,:league,:sent_at,:target,:kind,"
                    ":label,:verdict,:confidence,:odds,:success,:score,:total,"
                    ":checked_from,:source,:updated_at) "
                    "ON CONFLICT(device_id,pred_id,row_key) DO UPDATE SET "
                    "sport=excluded.sport, rule_id=excluded.rule_id, "
                    "rule_name=excluded.rule_name, team1=excluded.team1, "
                    "team2=excluded.team2, league=excluded.league, "
                    "sent_at=excluded.sent_at, target=excluded.target, "
                    "kind=excluded.kind, label=excluded.label, "
                    "verdict=excluded.verdict, confidence=excluded.confidence, "
                    "odds=excluded.odds, success=excluded.success, "
                    "score=excluded.score, "
                    "total=excluded.total, checked_from=excluded.checked_from, "
                    "source=excluded.source, updated_at=excluded.updated_at",
                    row)
                summary["predictions"] += 1

        # ---------- состояние рекомендаций ----------
        app_state = rule_advisor.normalize_state(
            data.get("advisor_state") if isinstance(
                data.get("advisor_state"), dict) else {})
        state_row = conn.execute(
            "SELECT state_json FROM advisor_state WHERE device_id=?",
            (device_id,)).fetchone()
        server_state = _json(state_row["state_json"], {}) if state_row else {}
        merged_state = _merge_states(server_state, app_state)

        auto_cfg = settings.get("auto_rules") if isinstance(
            settings.get("auto_rules"), dict) else {}
        try:
            min_samples = max(3, min(50, _int(
                auto_cfg.get("min_samples"), 6)))
        except Exception:
            min_samples = 6
        try:
            min_precision = max(50.0, min(95.0, _num(
                auto_cfg.get("min_precision"), 60.0)))
        except Exception:
            min_precision = 60.0
        active_sport = sport_catalog.normalize_sport(
            settings.get("active_sport") or "table_tennis")
        selected = [sport for sport in sport_catalog.SPORT_ORDER
                    if rules_by_sport.get(sport)]
        if not selected:
            selected = [active_sport]

        advisor_info = {"recommendations": [], "resolved": [], "advisor_state": merged_state}
        try:
            raw_predictions = data.get("predictions") if isinstance(
                data.get("predictions"), dict) else {}
            advisor_info = rule_advisor.recommend(
                raw_predictions, sports=selected,
                rules_by_sport={sport: [
                    dict(rule, conditions=rule["conditions"],
                         action=rule["action"]) for rule in rules_by_sport[sport]
                ] for sport in selected},
                min_samples=min_samples, min_precision=min_precision,
                state=merged_state, active_sport=active_sport)
        except Exception:
            advisor_info["advisor_state"] = merged_state

        new_state = rule_advisor.normalize_state(
            advisor_info.get("advisor_state") or merged_state)
        if state_row is None:
            conn.execute(
                "INSERT INTO advisor_state (device_id, state_json, updated_at) "
                "VALUES (?,?,?)", (device_id, _dump(new_state), now_iso))
        else:
            conn.execute(
                "UPDATE advisor_state SET state_json=?, updated_at=? "
                "WHERE device_id=?", (_dump(new_state), now_iso, device_id))

        current_recs = {str(item.get("id")): item
                        for item in advisor_info.get("recommendations") or []
                        if isinstance(item, dict)}
        previously_open = conn.execute(
            "SELECT rec_id FROM recommendations WHERE device_id=? AND "
            "status='open'", (device_id,)).fetchall()
        previously_open = {item["rec_id"] for item in previously_open}

        for rec_id, rec in current_recs.items():
            exists = conn.execute(
                "SELECT * FROM recommendations WHERE device_id=? AND rec_id=?",
                (device_id, rec_id)).fetchone()
            status, reason, applied_at, resolved_at = _rec_status_from_state(
                rec_id, rec, app_state, now_iso)
            if not status:
                status, reason = "open", ""
            if exists is None:
                conn.execute(
                    "INSERT INTO recommendations (device_id, rec_id, sport, "
                    "rule_id, rule_name, type, type_title, severity, reason, "
                    "condition_text, target_rule_json, rec_json, "
                    "precision_before, precision_after, gain, first_seen, "
                    "last_seen, seen_count, status, status_reason, applied_at, "
                    "resolved_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (device_id, rec_id, rec.get("sport") or "",
                     rec.get("rule_id") or "", rec.get("rule_name") or "",
                     rec.get("type") or "", rec.get("type_title") or "",
                     rec.get("severity") or "info", rec.get("reason") or "",
                     rec.get("condition_text") or "",
                     _dump(rec.get("target_rule") or {}), _dump(rec),
                     _num(rec.get("precision_before"), 0) or None,
                     _num(rec.get("precision_after"), 0) or None,
                     _num(rec.get("gain"), 0), now_iso, now_iso, 1, status,
                     reason, applied_at or "", resolved_at or "", now_iso))
                summary["recommendations"]["new"] += 1
            else:
                seen_count = _int(exists["seen_count"]) + 1
                first_seen = exists["first_seen"] or now_iso
                applied = exists["applied_at"]
                resolved = exists["resolved_at"]
                final_status = status
                # применённая рекомендация не должна «открываться» снова
                if exists["status"] == "applied":
                    final_status = "applied"
                if applied_at:
                    applied = applied_at
                if resolved_at:
                    resolved = resolved_at
                conn.execute(
                    "UPDATE recommendations SET sport=?, rule_id=?, "
                    "rule_name=?, type=?, type_title=?, severity=?, reason=?, "
                    "condition_text=?, target_rule_json=?, rec_json=?, "
                    "precision_before=?, precision_after=?, gain=?, "
                    "last_seen=?, seen_count=?, status=?, status_reason=?, "
                    "applied_at=?, resolved_at=?, updated_at=? "
                    "WHERE device_id=? AND rec_id=?",
                    (rec.get("sport") or "", rec.get("rule_id") or "",
                     rec.get("rule_name") or "", rec.get("type") or "",
                     rec.get("type_title") or "", rec.get("severity") or "info",
                     rec.get("reason") or "", rec.get("condition_text") or "",
                     _dump(rec.get("target_rule") or {}), _dump(rec),
                     _num(rec.get("precision_before"), 0) or None,
                     _num(rec.get("precision_after"), 0) or None,
                     _num(rec.get("gain"), 0), now_iso, seen_count,
                     final_status, reason or exists["status_reason"] or "",
                     applied or "", resolved or "", now_iso,
                     device_id, rec_id))
            if status == "applied":
                summary["recommendations"]["applied"] += 1

        # ---------- закрытие рекомендаций по фактическим правкам правил ----------
        rules_index = {}
        for sport, items in rules_by_sport.items():
            for rule in items:
                rules_index[(sport, rule["id"])] = rule

        # Открытые рекомендации, которые перестали появляться. Сначала
        # проверяем, не применили ли их на устройстве или вручную: правка
        # важнее, чем простое исчезновение из выдачи.
        current_ids = set(current_recs)
        for item in previously_open:
            if item in current_ids:
                continue
            row = conn.execute(
                "SELECT * FROM recommendations WHERE device_id=? AND rec_id=?",
                (device_id, item)).fetchone()
            if row is None:
                continue
            rec = _json(row["rec_json"], {}) or {}
            rule = rules_index.get((row["sport"], row["rule_id"]))
            status, reason, applied_at, resolved_at = _rec_status_from_state(
                item, rec, app_state, now_iso)
            final = "resolved"
            event_reason = "Устарела: условия или история изменились"
            if status == "applied":
                final = "applied"
                event_reason = reason or "Применено на устройстве"
            elif rule is not None:
                done, why = rule_advisor._is_resolved(rec, rule)
                if done and why not in ("Правило удалено", "Правило выключено"):
                    final = "applied"
                    event_reason = why
                elif done:
                    event_reason = why
            conn.execute(
                "UPDATE recommendations SET status=?, status_reason=?, "
                "applied_at=CASE WHEN ?='applied' THEN ? ELSE applied_at END, "
                "resolved_at=CASE WHEN ?='resolved' THEN ? ELSE resolved_at END, "
                "updated_at=? WHERE device_id=? AND rec_id=?",
                (final, event_reason, final, applied_at or now_iso,
                 final, resolved_at or now_iso, now_iso, device_id, item))
            if final == "applied":
                summary["recommendations"]["applied"] += 1
                conn.execute(
                    "UPDATE rule_events SET rec_id=?, source='recommendation' "
                    "WHERE id = (SELECT id FROM rule_events WHERE device_id=? "
                    "AND sport=? AND rule_id=? ORDER BY id DESC LIMIT 1)",
                    (item, device_id, row["sport"], row["rule_id"]))

        open_rows = conn.execute(
            "SELECT * FROM recommendations WHERE device_id=? AND "
            "status IN ('open','dismissed')", (device_id,)).fetchall()
        for row in open_rows:
            rec = _json(row["rec_json"], {}) or {}
            rule = rules_index.get((row["sport"], row["rule_id"]))
            if rule is None:
                continue
            done, why = rule_advisor._is_resolved(rec, rule)
            if not done:
                continue
            final = "resolved"
            if row["status"] == "applied":
                final = "applied"
            elif rec.get("type") == "disable_rule" and not rule.get("enabled", True):
                final = "applied"
            elif why not in ("Правило удалено", "Правило выключено"):
                final = "applied"
            conn.execute(
                "UPDATE recommendations SET status=?, status_reason=?, "
                "applied_at=CASE WHEN ?='applied' THEN ? ELSE applied_at END, "
                "resolved_at=CASE WHEN ?='resolved' THEN ? ELSE resolved_at END, "
                "updated_at=? WHERE device_id=? AND rec_id=?",
                (final, why, final, now_iso, final, now_iso, now_iso,
                 device_id, row["rec_id"]))
            if final == "applied":
                summary["recommendations"]["applied"] += 1
                # связываем событие изменения правила с рекомендацией
                conn.execute(
                    "UPDATE rule_events SET rec_id=?, source='recommendation' "
                    "WHERE id = (SELECT id FROM rule_events WHERE device_id=? "
                    "AND sport=? AND rule_id=? ORDER BY id DESC LIMIT 1)",
                    (row["rec_id"], device_id, row["sport"], row["rule_id"]))

        summary["recommendations"]["open"] = len(current_ids)
        conn.execute(
            "INSERT INTO sync_log (device_id, at, app_version, summary_json) "
            "VALUES (?,?,?,?)",
            (device_id, now_iso, app_version, _dump(summary)))

        # ---------- аккуратная уборка ----------
        cutoff = (_now_dt() - timedelta(days=RETENTION_DAYS)).isoformat()
        conn.execute(
            "DELETE FROM prediction_rows WHERE device_id=? AND sent_at < ?",
            (device_id, cutoff))
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM prediction_rows WHERE device_id=?",
            (device_id,)).fetchone()
        if count and _int(count["c"]) > MAX_DEVICE_ROWS:
            conn.execute(
                "DELETE FROM prediction_rows WHERE rowid IN ("
                "SELECT rowid FROM prediction_rows WHERE device_id=? "
                "ORDER BY sent_at ASC LIMIT ?)",
                (device_id, _int(count["c"]) - MAX_DEVICE_ROWS))
        conn.execute(
            "DELETE FROM sync_log WHERE device_id=? AND id NOT IN ("
            "SELECT id FROM sync_log WHERE device_id=? ORDER BY id DESC LIMIT 500)",
            (device_id, device_id))
        conn.commit()
        device_snapshot = _device_row(conn, conn.execute(
            "SELECT * FROM devices WHERE id=?", (device_id,)).fetchone())
        return {
            "ok": True,
            "device": device_snapshot,
            "synced": summary,
            "server_version": SERVER_VERSION,
            "server_time": _now(),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------
# чтение для веба
# --------------------------------------------------------------------------

def get_device(device_id):
    init_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM devices WHERE id=?",
                           (device_id,)).fetchone()
        if row is None:
            return None
        return _device_row(conn, row)
    finally:
        conn.close()


def device_overview(device_id, days=30):
    init_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM devices WHERE id=?",
                           (device_id,)).fetchone()
        if row is None:
            return None
        device = _device_row(conn, row)
        stats = device["stats"]
        stats["daily"] = _daily_series(conn, device_id, days=days)
        sports_rows = conn.execute(
            "SELECT sport, COUNT(*) AS total, "
            "SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS wins, "
            "SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS losses, "
            "SUM(CASE WHEN success IS NULL THEN 1 ELSE 0 END) AS pending "
            "FROM prediction_rows WHERE device_id=? AND source='rule' "
            "GROUP BY sport ORDER BY total DESC", (device_id,)).fetchall()
        sports = []
        for item in sports_rows:
            resolved = _int(item["wins"]) + _int(item["losses"])
            money = _row_stats(conn.execute(
                "SELECT success, odds FROM prediction_rows WHERE "
                "device_id=? AND source='rule' AND sport=?",
                (device_id, item["sport"])).fetchall())
            sports.append({
                "sport": item["sport"],
                "name": sport_catalog.name(item["sport"]),
                "short_name": sport_catalog.short_name(item["sport"]),
                "total": _int(item["total"]), "wins": _int(item["wins"]),
                "losses": _int(item["losses"]),
                "pending": _int(item["pending"]),
                "hit_rate": (round(_int(item["wins"]) * 100.0 / resolved, 1)
                             if resolved else None),
                "roi": money.get("roi"), "ev": money.get("ev"),
                "profit": money.get("profit"),
                "avg_odds": money.get("avg_odds"),
                "odds_n": money.get("odds_n") or 0,
                "drawdown": money.get("drawdown"),
                "profitable": money.get("profitable"),
            })
        targets_rows = conn.execute(
            "SELECT kind, COUNT(*) AS total, "
            "SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS wins, "
            "SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS losses "
            "FROM prediction_rows WHERE device_id=? AND source='rule' "
            "GROUP BY kind ORDER BY total DESC", (device_id,)).fetchall()
        targets = []
        for item in targets_rows:
            resolved = _int(item["wins"]) + _int(item["losses"])
            money = _row_stats(conn.execute(
                "SELECT success, odds FROM prediction_rows WHERE "
                "device_id=? AND source='rule' AND kind=?",
                (device_id, item["kind"])).fetchall())
            targets.append({
                "kind": item["kind"] or "—", "total": _int(item["total"]),
                "wins": _int(item["wins"]), "losses": _int(item["losses"]),
                "hit_rate": (round(_int(item["wins"]) * 100.0 / resolved, 1)
                             if resolved else None),
                "roi": money.get("roi"), "ev": money.get("ev"),
                "profit": money.get("profit"),
                "avg_odds": money.get("avg_odds"),
                "odds_n": money.get("odds_n") or 0,
            })
        events = _events(conn, device_id, limit=8, offset=0)
        return {
            "ok": True, "device": device, "sports": sports,
            "targets": targets, "events": events["items"],
            "server_version": SERVER_VERSION, "server_time": _now(),
        }
    finally:
        conn.close()


def device_rules(device_id, sport=""):
    init_db()
    conn = _connect()
    try:
        clauses = ["device_id=?", "deleted_at IS NULL"]
        params = [device_id]
        if sport:
            clauses.append("sport=?")
            params.append(sport_catalog.normalize_sport(sport))
        rows = conn.execute(
            "SELECT * FROM rules WHERE " + " AND ".join(clauses) +
            " ORDER BY sport, priority, name", params).fetchall()
        items = []
        for row in rows:
            perf = _rule_performance(conn, device_id, row["rule_id"],
                                     sport=row["sport"], days=90)
            since_perf = _rule_performance(
                conn, device_id, row["rule_id"], sport=row["sport"],
                since=row["last_change_at"])
            last_event = conn.execute(
                "SELECT id, at, kind, summary FROM rule_events WHERE "
                "device_id=? AND sport=? AND rule_id=? ORDER BY id DESC LIMIT 1",
                (device_id, row["sport"], row["rule_id"])).fetchone()
            items.append({
                "sport": row["sport"],
                "sport_name": sport_catalog.name(row["sport"]),
                "rule_id": row["rule_id"],
                "name": row["name"],
                "enabled": bool(row["enabled"]),
                "priority": _int(row["priority"]),
                "auto": bool(row["auto"]),
                "stop": bool(row["stop"]) if "stop" in row.keys() else False,
                "auto_kind": row["auto_kind"] if "auto_kind" in row.keys() else "",
                "auto_target": row["auto_target"] if "auto_target" in row.keys() else "",
                "conditions_text": row["conditions_text"],
                "action_text": row["action_text"],
                "summary": row["summary"],
                "conditions": _json(row["conditions_json"], {}),
                "action": _json(row["action_json"], {}),
                "first_seen": row["first_seen"],
                "last_change_at": row["last_change_at"],
                "change_count": _int(row["change_count"]),
                "performance": perf,
                "since_change": since_perf,
                "last_event": dict(last_event) if last_event else None,
            })
        return {"ok": True, "items": items, "server_time": _now()}
    finally:
        conn.close()


def device_recommendations(device_id, status="", limit=200):
    init_db()
    conn = _connect()
    try:
        clauses = ["device_id=?"]
        params = [device_id]
        if status and status != "all":
            clauses.append("status=?")
            params.append(status)
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE " + " AND ".join(clauses) +
            " ORDER BY COALESCE(applied_at, first_seen) DESC LIMIT ?",
            params + [max(1, min(1000, _int(limit, 200)))]).fetchall()
        items = []
        for row in rows:
            rec = {
                "device_id": row["device_id"], "rec_id": row["rec_id"],
                "sport": row["sport"], "sport_name": sport_catalog.name(
                    row["sport"]),
                "rule_id": row["rule_id"], "rule_name": row["rule_name"],
                "type": row["type"], "type_title": row["type_title"],
                "severity": row["severity"], "reason": row["reason"],
                "condition_text": row["condition_text"],
                "precision_before": row["precision_before"],
                "precision_after": row["precision_after"],
                "gain": row["gain"], "first_seen": row["first_seen"],
                "last_seen": row["last_seen"], "seen_count": row["seen_count"],
                "status": row["status"], "status_reason": row["status_reason"],
                "applied_at": row["applied_at"],
                "resolved_at": row["resolved_at"],
                "target_rule": _json(row["target_rule_json"], {}),
                "rec": _json(row["rec_json"], {}),
            }
            rec["outcome"] = _rec_actual_outcome(conn, device_id, rec)
            event = conn.execute(
                "SELECT id FROM rule_events WHERE device_id=? AND rec_id=? "
                "ORDER BY id LIMIT 1", (device_id, row["rec_id"])).fetchone()
            rec["event_id"] = event["id"] if event else None
            items.append(rec)
        counts = {}
        for item in conn.execute(
                "SELECT status, COUNT(*) AS c FROM recommendations "
                "WHERE device_id=? GROUP BY status", (device_id,)):
            counts[item["status"]] = _int(item["c"])
        return {"ok": True, "items": items, "counts": counts,
                "server_time": _now()}
    finally:
        conn.close()


def _events(conn, device_id, limit=100, offset=0, sport="", kind="",
            rule_id=""):
    clauses = ["device_id=?"]
    params = [device_id]
    if sport:
        clauses.append("sport=?")
        params.append(sport_catalog.normalize_sport(sport))
    if kind and kind != "all":
        clauses.append("kind=?")
        params.append(kind)
    if rule_id:
        clauses.append("rule_id=?")
        params.append(str(rule_id))
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM rule_events WHERE " +
        " AND ".join(clauses), params).fetchone()
    rows = conn.execute(
        "SELECT * FROM rule_events WHERE " + " AND ".join(clauses) +
        " ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [max(1, min(1000, _int(limit, 100))),
                  max(0, _int(offset))]).fetchall()
    items = []
    for row in rows:
        after = _json(row["after_json"], {}) or {}
        item = {
            "id": row["id"], "at": row["at"], "kind": row["kind"],
            "source": row["source"], "rec_id": row["rec_id"] or "",
            "sport": row["sport"],
            "sport_name": sport_catalog.name(row["sport"]),
            "rule_id": row["rule_id"], "rule_name": row["rule_name"],
            "summary": row["summary"],
            "changes": _json(row["changes_json"], []) or [],
            "before": _json(row["before_json"], None),
            "after": after,
        }
        if item["kind"] == "updated" and (row["sport"], row["rule_id"]):
            before = _rule_performance(conn, device_id, row["rule_id"],
                                       sport=row["sport"], until=row["at"])
            after_perf = _rule_performance(conn, device_id, row["rule_id"],
                                           sport=row["sport"], since=row["at"])
            delta = None
            if before["hit_rate"] is not None and after_perf["hit_rate"] is not None:
                delta = round(after_perf["hit_rate"] - before["hit_rate"], 1)
            delta_roi = None
            if before.get("roi") is not None and after_perf.get("roi") is not None:
                delta_roi = round(after_perf["roi"] - before["roi"], 1)
            verdict = "наблюдаем"
            if after_perf["resolved"] < 3:
                verdict = "мало данных после изменения"
            elif after_perf.get("value_ready"):
                if (delta_roi is not None and delta_roi >= 2.0) or \
                        (after_perf.get("ev_lower") or -1) > 0:
                    verdict = "лучше"
                elif (delta_roi is not None and delta_roi <= -2.0) or \
                        (after_perf.get("ev_lower") is not None and
                         after_perf["ev_lower"] <= -1.0):
                    verdict = "хуже"
                else:
                    verdict = "без изменений"
            elif delta is not None and delta >= 3:
                verdict = "лучше"
            elif delta is not None and delta <= -3:
                verdict = "хуже"
            elif delta is not None:
                verdict = "без изменений"
            item["outcome"] = {"before": before, "after": after_perf,
                               "delta": delta, "delta_roi": delta_roi,
                               "verdict": verdict}
        if item["rec_id"]:
            rec = conn.execute(
                "SELECT status, type_title, reason FROM recommendations "
                "WHERE device_id=? AND rec_id=?",
                (device_id, item["rec_id"])).fetchone()
            if rec:
                item["recommendation"] = dict(rec)
        items.append(item)
    return {"ok": True, "items": items, "total": _int(total["c"]),
            "limit": limit, "offset": offset}


def device_events(device_id, limit=100, offset=0, sport="", kind="",
                  rule_id=""):
    init_db()
    conn = _connect()
    try:
        result = _events(conn, device_id, limit=limit, offset=offset,
                         sport=sport, kind=kind, rule_id=rule_id)
        result["server_time"] = _now()
        return result
    finally:
        conn.close()


def device_predictions(device_id, limit=100, offset=0, sport="", rule_id="",
                       status="all"):
    init_db()
    conn = _connect()
    try:
        clauses = ["device_id=?"]
        params = [device_id]
        if sport:
            clauses.append("sport=?")
            params.append(sport_catalog.normalize_sport(sport))
        if rule_id:
            clauses.append("rule_id=?")
            params.append(rule_id)
        if status == "win":
            clauses.append("success=1")
        elif status == "loss":
            clauses.append("success=0")
        elif status == "pending":
            clauses.append("success IS NULL")
        where = " AND ".join(clauses)
        total = conn.execute(
            "SELECT COUNT(DISTINCT pred_id) AS c FROM prediction_rows WHERE " +
            where, params).fetchone()
        rows = conn.execute(
            "SELECT * FROM prediction_rows WHERE " + where +
            " ORDER BY sent_at DESC, pred_id LIMIT ? OFFSET ?",
            params + [max(1, min(500, _int(limit, 100))),
                      max(0, _int(offset))]).fetchall()
        games = {}
        order = []
        for row in rows:
            key = row["pred_id"]
            if key not in games:
                games[key] = {
                    "pred_id": key, "sport": row["sport"],
                    "sport_name": sport_catalog.name(row["sport"]),
                    "team1": row["team1"], "team2": row["team2"],
                    "league": row["league"], "sent_at": row["sent_at"],
                    "rows": [],
                }
                order.append(key)
            games[key]["rows"].append({
                "label": row["label"], "verdict": row["verdict"],
                "rule_id": row["rule_id"], "rule_name": row["rule_name"],
                "confidence": row["confidence"], "success": row["success"],
                "score": row["score"], "total": row["total"],
                "source": row["source"], "kind": row["kind"],
                "target": row["target"], "odds": row["odds"],
            })
        for game in games.values():
            game["money"] = _row_stats([
                {"success": item["success"], "odds": item["odds"]}
                for item in game["rows"] if item["success"] is not None])
        return {"ok": True, "items": [games[key] for key in order],
                "total": _int(total["c"]), "limit": limit, "offset": offset,
                "server_time": _now()}
    finally:
        conn.close()


def rename_device(device_id, name):
    init_db()
    clean = _clean(name, 80)
    conn = _connect()
    try:
        cur = conn.execute("UPDATE devices SET alias=? WHERE id=?",
                           (clean, device_id))
        conn.commit()
        if not cur.rowcount:
            return None
        return get_device(device_id)
    finally:
        conn.close()


def health():
    init_db()
    conn = _connect()
    try:
        devices = conn.execute(
            "SELECT COUNT(*) AS c FROM devices").fetchone()
        rows = conn.execute(
            "SELECT COUNT(*) AS c FROM prediction_rows").fetchone()
        recs = conn.execute(
            "SELECT COUNT(*) AS c FROM recommendations").fetchone()
        return {
            "ok": True, "db": DB_PATH, "devices": _int(devices["c"]),
            "predictions": _int(rows["c"]), "recommendations": _int(recs["c"]),
        }
    finally:
        conn.close()

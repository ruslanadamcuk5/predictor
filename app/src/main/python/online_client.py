# -*- coding: utf-8 -*-
"""Клиент онлайн-режима: отправляет историю и правила на сайт.

Приложение остаётся полностью работоспособным без сети. Онлайн-режим — это
необязательный ускоритель и общий экран анализа: телефон отправляет снимок
истории, сервер считает те же метрики тем же Python-кодом и возвращает
готовый отчёт вместе с рекомендациями по правилам.

Все сетевые ошибки возвращаются вызывающей стороне; движок сам решает,
переключиться на локальный расчёт или показать ошибку.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time

import requests

DEFAULT_TIMEOUT = 25
MAX_HISTORY = 8000
# Для периодической синхронизации достаточно последних матчей: сервер
# пересчитывает рекомендации по той же истории, но не получает мегабайты
# при каждом обновлении.
MAX_SYNC_HISTORY = 3000
# Адрес онлайн-сервиса, если пользователь не указал свой.
DEFAULT_BASE_URL = "https://predictor.alwaysdata.net"
# Адреса из версии 1.15: их нужно игнорировать, чтобы старые настройки
# не уводили приложение на чужой/отключённый сайт.
LEGACY_BASE_PREFIX = "https://virusadk.alwaysdata.net"

# Поля истории, без которых анализатору нечего считать. Остальное
# (текст сообщения, id Telegram, старые ИИ-прогнозы) не отправляем: так
# запрос в разы меньше и не содержит лишних данных.
KEEP_RECORD = (
    "team1", "team2", "league", "date", "sport", "sent_at", "stats",
    "predictions", "set_results", "sets_completed", "result_checked",
)


class OnlineError(Exception):
    pass


def config(settings_snapshot, overrides=None):
    cfg = dict((settings_snapshot or {}).get("online") or {})
    if isinstance(overrides, dict):
        for key in ("base_url", "token", "timeout", "enabled",
                    "fallback_local", "verify_ssl"):
            if key in overrides and overrides[key] not in (None, ""):
                cfg[key] = overrides[key]
    base = str(cfg.get("base_url") or "").strip().rstrip("/")
    if base.startswith(LEGACY_BASE_PREFIX):
        base = ""
    cfg["base_url"] = base or DEFAULT_BASE_URL
    cfg["token"] = str(cfg.get("token") or "").strip()
    try:
        cfg["timeout"] = max(5, min(120, int(cfg.get("timeout") or
                                            DEFAULT_TIMEOUT)))
    except Exception:
        cfg["timeout"] = DEFAULT_TIMEOUT
    cfg["verify_ssl"] = cfg.get("verify_ssl", True) is not False
    return cfg


def enabled(settings_snapshot):
    cfg = config(settings_snapshot)
    return bool(cfg.get("enabled")) and bool(cfg.get("base_url"))


def _headers(cfg, compressed=False):
    headers = {
        "Accept": "application/json",
        "X-Predictor-Client": "android",
    }
    if cfg.get("token"):
        headers["Authorization"] = "Bearer " + cfg["token"]
    if compressed:
        headers["Content-Encoding"] = "gzip"
    return headers


def _request(method, cfg, path, payload=None, timeout=None):
    url = cfg["base_url"] + path
    body = None
    compressed = False
    if payload is not None:
        raw = json.dumps(payload, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
        if len(raw) > 2048:
            body = gzip.compress(raw, compresslevel=6)
            compressed = True
        else:
            body = raw
    started = time.time()
    try:
        response = requests.request(
            method, url, data=body,
            headers=_headers(cfg, compressed=compressed),
            timeout=timeout or cfg.get("timeout") or DEFAULT_TIMEOUT,
            verify=cfg.get("verify_ssl", True))
    except Exception as exc:
        raise OnlineError("Сайт недоступен: %s" % exc)
    elapsed = int((time.time() - started) * 1000)
    text = response.text or ""
    try:
        data = response.json()
    except Exception:
        data = None
    if response.status_code == 401:
        raise OnlineError("Сайт отклонил токен доступа (401).")
    if response.status_code == 413:
        raise OnlineError("История слишком большая для сайта (413).")
    if response.status_code >= 400:
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("error") or "")
        raise OnlineError("Сайт вернул %d%s" % (
            response.status_code, (": " + detail) if detail else ""))
    if not isinstance(data, dict):
        raise OnlineError("Сайт вернул не JSON: %s" % text[:120])
    data.setdefault("ok", True)
    data["latency_ms"] = elapsed
    data["online"] = True
    return data


def ping(settings_snapshot, overrides=None):
    cfg = config(settings_snapshot, overrides)
    if not cfg.get("base_url"):
        return {"ok": False, "error": "Не указан адрес сайта."}
    try:
        data = _request("GET", cfg, "/api/v1/ping")
        return {
            "ok": bool(data.get("ok")),
            "url": cfg["base_url"],
            "latency_ms": data.get("latency_ms"),
            "version": data.get("version"),
            "server_time": data.get("server_time"),
            "auth": bool(cfg.get("token")),
            "message": "Связь с сайтом установлена.",
        }
    except OnlineError as exc:
        return {"ok": False, "url": cfg["base_url"], "error": str(exc)}


def _trim_predictions(sent_predictions, selected):
    """Оставляет только нужные виды и поля, чтобы запрос был компактным."""
    selected = set(selected or [])
    result = {}
    for pred_id, record in (sent_predictions or {}).items():
        if not isinstance(record, dict):
            continue
        sport = str(record.get("sport") or "").strip()
        if not sport:
            sample = record.get("stats") or {}
            sport = str((sample or {}).get("sport") or "")
        if selected and sport and sport not in selected:
            continue
        if selected and not sport:
            # Старые записи без вида: оставляем, если выбран настольный
            # теннис (исторически это был вид по умолчанию).
            if "table_tennis" not in selected:
                continue
        item = {}
        for key in KEEP_RECORD:
            if key in record:
                item[key] = record[key]
        item["sport"] = sport or "table_tennis"
        result[pred_id] = item
        if len(result) >= MAX_HISTORY:
            break
    return result


def _trim_rules(rules_by_sport):
    result = {}
    for sport, rules in (rules_by_sport or {}).items():
        items = []
        for rule in rules or []:
            if not isinstance(rule, dict):
                continue
            item = {
                "id": rule.get("id"),
                "name": rule.get("name"),
                "sport": rule.get("sport") or sport,
                "enabled": bool(rule.get("enabled", True)),
                "priority": rule.get("priority"),
                "stop": bool(rule.get("stop")),
                "conditions": rule.get("conditions") or {},
                "action": rule.get("action") or {},
                "auto": bool(rule.get("auto")),
                "auto_kind": rule.get("auto_kind"),
                "auto_target": rule.get("auto_target"),
                "auto_stats": rule.get("auto_stats"),
                "conditions_text": rule.get("conditions_text"),
                "action_text": rule.get("action_text"),
            }
            items.append(item)
        result[sport] = items
    return result


def analyze(settings_snapshot, options, sent_predictions, rules_by_sport,
            auto_cfg=None, advisor_state=None, overrides=None):
    """Отправляет снимок на сайт и возвращает готовый отчёт анализа."""
    cfg = config(settings_snapshot, overrides)
    if not cfg.get("base_url"):
        raise OnlineError("Не указан адрес сайта.")
    selected = list(options.get("sports") or [])
    payload = {
        "kind": options.get("kind") or "all",
        "target": options.get("target") or "",
        "sports": selected,
        "min_group": options.get("min_group"),
        "min_lift": options.get("min_lift"),
        "min_hits": options.get("min_hits"),
        "limit": options.get("limit") or 0,
        "pairs": bool(options.get("pairs", True)),
        "predictions": _trim_predictions(sent_predictions, selected),
        "rules": _trim_rules(rules_by_sport),
        "auto_rules": dict(auto_cfg or {}),
        "advisor_state": advisor_state or {},
    }
    data = _request("POST", cfg, "/api/v1/analyze", payload)
    if not data.get("ok"):
        raise OnlineError(str(data.get("error") or "Сайт не смог посчитать анализ."))
    data["online"] = True
    data["online_url"] = cfg["base_url"]
    return data


# --------------------------------------------------------------------------
# Синхронизация истории для веб-кабинета
# --------------------------------------------------------------------------

SYNC_SETTING_KEYS = (
    "active_sport", "auto_rules", "algorithm_mode", "model_thresholds",
    "required_models", "allowed_bets", "allowed_sets", "general_filters",
    "min_h2h_matches", "poll_interval_sec", "odds_check_enabled",
    "bet_size_percent", "reports", "engine",
)


def _android_info():
    """Модель и платформа устройства. Вне Android возвращает пустые поля."""
    result = {"model": "", "platform": "", "android_id": ""}
    try:
        from java import jclass
        build = jclass("android.os.Build")
        model = str(build.MODEL or "").strip()
        manufacturer = str(build.MANUFACTURER or "").strip()
        if manufacturer and manufacturer.lower() not in model.lower():
            model = manufacturer + " " + model
        release = str(build.VERSION.RELEASE or "").strip()
        sdk = str(build.VERSION.SDK_INT or "").strip()
        result["model"] = model[:120]
        result["platform"] = ("Android %s (SDK %s)" % (release, sdk)).strip()
        try:
            python_cls = jclass("com.chaquo.python.Python")
            context = python_cls.getPlatform().getApplication()
            secure = jclass("android.provider.Settings$Secure")
            value = secure.getString(context.getContentResolver(), "android_id")
            if value:
                result["android_id"] = str(value)[:80]
        except Exception:
            pass
    except Exception:
        pass
    if not result["model"] and os.environ.get("PREDICTOR_DEVICE_MODEL"):
        result["model"] = os.environ["PREDICTOR_DEVICE_MODEL"][:120]
    if not result["platform"]:
        result["platform"] = os.environ.get("PREDICTOR_DEVICE_PLATFORM", "")[:120]
    if not result["android_id"]:
        result["android_id"] = os.environ.get("PREDICTOR_DEVICE_ID", "")
    return result


def make_device_id(seed=""):
    raw = str(seed or "").strip()
    if not raw:
        raw = "predictor-%s-%s" % (os.uname().nodename if hasattr(os, "uname")
                                   else "device", time.time())
    return "dev_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def device_info(settings_snapshot, app_version=""):
    """Стабильные данные устройства для списка в веб-кабинете."""
    snapshot = settings_snapshot or {}
    stored = snapshot.get("device") if isinstance(snapshot.get("device"),
                                                  dict) else {}
    platform_info = _android_info()
    seed = platform_info.get("android_id") or ""
    if not seed:
        seed = "%s|%s" % (platform_info.get("model") or "",
                          platform_info.get("platform") or "")
    device_id = str(stored.get("id") or "").strip()
    if not device_id:
        if seed.strip("|"):
            device_id = make_device_id(seed)
    name = str(stored.get("name") or "").strip()
    if not name:
        name = platform_info.get("model") or "Устройство Predictor"
    return {
        "id": device_id,
        "name": name[:120],
        "model": platform_info.get("model") or "",
        "platform": platform_info.get("platform") or "",
        "app_version": str(app_version or ""),
    }


def _sync_settings(settings_snapshot):
    """Только параметры анализа: без токенов, ключей и Telegram."""
    snapshot = settings_snapshot or {}
    result = {}
    for key in SYNC_SETTING_KEYS:
        if key in snapshot:
            result[key] = snapshot[key]
    return result


def sync(settings_snapshot, sent_predictions, rules_by_sport,
         advisor_state=None, device=None, app_version="",
         meta=None, overrides=None):
    """Отправляет снимок истории и правил в веб-кабинет."""
    cfg = config(settings_snapshot, overrides)
    if not cfg.get("base_url"):
        raise OnlineError("Не указан адрес сайта.")
    predictions = _trim_predictions(sent_predictions, None)
    if len(predictions) > MAX_SYNC_HISTORY:
        items = list(predictions.items())
        items.sort(key=lambda pair: str((pair[1] or {}).get("sent_at") or ""),
                   reverse=True)
        predictions = dict(items[:MAX_SYNC_HISTORY])
    info = device if isinstance(device, dict) else device_info(
        settings_snapshot, app_version)
    payload = {
        "device": info,
        "settings": _sync_settings(settings_snapshot),
        "rules": _trim_rules(rules_by_sport),
        "predictions": predictions,
        "advisor_state": advisor_state or {},
        "meta": dict(meta or {}, app_version=str(app_version or ""),
                     client="android"),
    }
    data = _request("POST", cfg, "/api/v1/sync", payload,
                    timeout=max(45, cfg.get("timeout") or DEFAULT_TIMEOUT))
    if not data.get("ok"):
        raise OnlineError(str(data.get("error") or "Сайт не принял историю."))
    return data

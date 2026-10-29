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
import json
import time

import requests

DEFAULT_TIMEOUT = 25
MAX_HISTORY = 8000

# Поля истории, без которых анализатору нечего считать. Остальное
# (текст сообщения, id Telegram, старые ИИ-прогнозы) не отправляем: так
# запрос в разы меньше и не содержит лишних данных.
KEEP_RECORD = (
    "team1", "team2", "league", "date", "sport", "sent_at", "stats",
    "predictions", "set_results", "sets_completed",
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
    cfg["base_url"] = str(cfg.get("base_url") or "").strip().rstrip("/")
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

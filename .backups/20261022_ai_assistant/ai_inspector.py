# -*- coding: utf-8 -*-
"""Помощник Predictor: автономный контроль состояния приложения.

Модуль раз в минуту смотрит на живые данные движка и формирует
конкретные рекомендации: что переобучается, какое правило чаще всего
проигрывает, где не хватает правил, почему нет сигналов. Проверки
локальные и бесплатные — модель для них не нужна.

Каждая рекомендация может содержать действие (`action`), которое
приложение умеет выполнить одной кнопкой.
"""

from __future__ import annotations

import time

import sports

# Кэш проверок, чтобы не считать анализ заново на каждом опросе панели.
_CACHE = {"at": 0.0, "alerts": []}
CACHE_TTL = 60.0
ANALYZER_TTL = 300.0
_ANALYZER = {"at": 0.0, "data": {}}

SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2}


def _alert(alert_id, severity, title, text, action=None, sport=None):
    return {
        "id": alert_id,
        "severity": severity,
        "title": title,
        "text": text,
        "action": action or {},
        "sport": sport or "",
    }


def _rule_conditions(rule):
    """Собирает список (metric, args) из условий правила (с группами)."""
    result = []
    stack = [(rule or {}).get("conditions") or {}]
    while stack:
        node = stack.pop()
        for item in node.get("conditions") or []:
            if not isinstance(item, dict):
                continue
            if item.get("metric"):
                result.append((str(item.get("metric")),
                               json_args(item.get("args"))))
            inner = item.get("conditions")
            if isinstance(inner, dict):
                stack.append(inner)
    return result


def json_args(args):
    try:
        return {str(key): str(value) for key, value in (args or {}).items()}
    except Exception:
        return {}


def _same_args(left, right):
    keys = set(left) | set(right)
    for key in keys:
        if str(left.get(key, "")) != str(right.get(key, "")):
            return False
    return True


def _analyzer_data(engine, sport):
    key = sport or "all"
    now = time.time()
    item = _ANALYZER.get(key)
    if item and now - item.get("at", 0) < ANALYZER_TTL:
        return item.get("data") or {}
    try:
        data = engine.get_analyzer({"sport": key, "min_group": 3,
                                    "min_lift": 20})
    except Exception:
        data = {}
    _ANALYZER[key] = {"at": now, "data": data}
    return data


def inspect(engine, force=False):
    """Возвращает список рекомендаций по состоянию приложения."""
    now = time.time()
    if not force and now - _CACHE.get("at", 0) < CACHE_TTL:
        return _CACHE.get("alerts") or []
    alerts = []
    try:
        alerts = _collect(engine)
    except Exception:
        alerts = []
    alerts.sort(key=lambda item: SEVERITY_ORDER.get(item.get("severity"), 3))
    _CACHE["at"] = now
    _CACHE["alerts"] = alerts
    return alerts


def _collect(engine):
    alerts = []
    predictor = engine.predictor
    settings = engine.settings
    neural = predictor.nn.status()

    # ---- нейросеть: переобучение, плато, бесполезность ------------------
    for item in neural.get("sports") or []:
        sport = item.get("sport")
        name = item.get("short") or sport
        history = item.get("history") or []
        rejected = [row for row in history if row.get("rejected")]
        accuracy = float(item.get("accuracy") or 0.0)
        baseline = float(item.get("baseline") or 0.0)
        lift = float(item.get("lift") or 0.0)
        if item.get("ready") and lift <= 0 and item.get("selected"):
            alerts.append(_alert(
                "nn_weak_%s" % sport, "critical",
                "Нейросеть по виду «%s» не лучше базы" % name,
                "Точность %.0f%% против базового уровня %.0f%% — модель "
                "угадывает не лучше, чем «всегда самый частый исход». "
                "Отключите её для этого вида или переобучите с нуля." % (
                    accuracy * 100, baseline * 100),
                {"type": "neural_sport_off", "label": "Выключить сеть",
                 "sport": sport}, sport))
            continue
        if len(rejected) >= 2 or (item.get("trend") == "down" and rejected):
            alerts.append(_alert(
                "nn_overfit_%s" % sport, "critical",
                "Нейросеть по виду «%s» переобучается" % name,
                "Из последних %d обучений %d новых моделей хуже прежних "
                "(точность падает). Остановите автоматическое обучение: "
                "иначе сеть начнёт запоминать, а не обобщать." % (
                    len(history), len(rejected)),
                {"type": "neural_freeze", "label": "Заморозить обучение"},
                sport))
        if item.get("plateau"):
            alerts.append(_alert(
                "nn_plateau_%s" % sport, "warn",
                "Обучение по виду «%s» остановилось: точность не растёт" % name,
                "Три раунда подряд без улучшения. Либо данных мало, либо "
                "модель выучила шум. Попробуйте обучить вручную с новыми "
                "примерами или отключите сеть для этого вида.",
                {"type": "neural_train", "label": "Обучить сейчас",
                 "sport": sport}, sport))
        if item.get("pending", 0) >= 150:
            alerts.append(_alert(
                "nn_pending_%s" % sport, "warn",
                "Много примеров ждут результата по виду «%s»" % name,
                "%d матчей проверены, но их исходы не подтянулись. Проверьте "
                "логи: возможно, страницы статистики или линии временно "
                "не отдают финальный счёт." % item.get("pending"),
                {"type": "open_logs", "label": "Открыть логи"}, sport))

    # ---- конструктор: нет правил, плохое правило -------------------------
    active_sport = settings.get_sport()
    rules = predictor.constructor.snapshot(active_sport)
    enabled = [rule for rule in rules if rule.get("enabled")]
    if not enabled:
        alerts.append(_alert(
            "ctor_empty", "warn",
            "У вида «%s» нет включённых правил" % (
                sports.short_name(active_sport)),
            "В режиме конструктора по этому виду не будет ни одного "
            "прогноза. Откройте «Правила» и добавьте шаблоны или включите "
            "нужные правила.",
            {"type": "open_constructor", "label": "Открыть правила",
             "sport": active_sport}, active_sport))

    data = _analyzer_data(engine, active_sport)
    failures = data.get("failure") or []
    if failures:
        worst = failures[0]
        target_metric = str(worst.get("metric") or "")
        target_args = json_args(worst.get("args"))
        for rule in enabled:
            for metric, args in _rule_conditions(rule):
                if metric != target_metric:
                    continue
                if not _same_args(args, target_args):
                    continue
                alerts.append(_alert(
                    "rule_bad_%s" % rule.get("id"), "warn",
                    "Правило «%s» чаще проигрывает" % (rule.get("name") or ""),
                    "Условие «%s» встречается в %d%% неудачных прогнозов и "
                    "почти не встречается в удачных. Это кандидат на "
                    "исключение — выключите правило и сравните результат." % (
                        worst.get("text") or metric, worst.get("loss_share") or 0),
                    {"type": "rule_disable", "label": "Выключить правило",
                     "sport": active_sport, "rule_id": rule.get("id")},
                    active_sport))
                break
            else:
                continue
            break

    # ---- авто-правила ----------------------------------------------------
    auto = engine._auto_status(active_sport)
    if auto.get("enabled") and not (auto.get("rules") or []):
        alerts.append(_alert(
            "auto_empty", "info",
            "Авто-правила включены, но ещё не созданы",
            "Нужно минимум %d размеченных прогнозов. Пока данных мало, "
            "подождите — авто-правила появятся сами." % (
                auto.get("min_samples") or 6),
            {"type": "open_analyzer", "label": "Открыть анализ"},
            active_sport))

    # ---- логи и ошибки ----------------------------------------------------
    errors = [item for item in events if item.get("level") == "ERROR"]
    if len(errors) >= 5:
        alerts.append(_alert(
            "many_errors", "warn",
            "В логе %d ошибок" % len(errors),
            "Последние ошибки: %s. Проверьте правила и настройки — чаще всего "
            "это недоступная страница статистики или конфликт условий." % (
                "; ".join(str(item.get("message"))[:60] for item in errors[:2])),
            {"type": "open_logs", "label": "Открыть логи"}))

    # ---- результаты: сравнение ИИ и правил --------------------------------
    try:
        import predictor_core as core
        events = core.events.all(limit=200)
    except Exception:
        events = []
    try:
        results = engine.get_results(limit=200)
    except Exception:
        results = {}
    rows = results.get("items") or []
    ai_rows = [row for row in rows if row.get("source") == "ai"]
    rule_rows = [row for row in rows if row.get("source") != "ai"]
    ai_hit = _hit_rate(ai_rows)
    rule_hit = _hit_rate(rule_rows)
    if ai_rows and rule_rows and ai_hit[0] >= 5 and ai_hit[1] > rule_hit[1]:
        alerts.append(_alert(
            "ai_better", "info",
            "Мнение ИИ заходит чаще правил",
            "По закрытым прогнозам: ИИ — %d из %d (%.0f%%), правила — %d из "
            "%d (%.0f%%). Можно поднять статус ИИ: включить «ИИ-прогнозы по "
            "линии»." % (ai_hit[0], ai_hit[1], ai_hit[2], rule_hit[0],
                         rule_hit[1], rule_hit[2]),
            {"type": "ai_auto_predict_on", "label": "Включить ИИ-прогнозы"}))

    # ---- настройки -------------------------------------------------------
    snapshot = settings.snapshot() or {}
    try:
        interval = int(snapshot.get("poll_interval_sec") or 20)
    except Exception:
        interval = 20
    if interval < 15:
        alerts.append(_alert(
            "poll_fast", "info",
            "Слишком частый опрос линии",
            "Интервал %d с при шести видах спорта — это лишний трафик и "
            "батарея. 20–30 с обычно достаточно." % interval,
            {"type": "interval_up", "label": "Поставить 30 с"}))
    if not snapshot.get("odds_check_enabled", True):
        alerts.append(_alert(
            "odds_off", "info",
            "Проверка коэффициентов выключена",
            "Часть сигналов может быть по невыгодной цене. Если hit rate ниже "
            "обычного — включите проверку коэффициентов.",
            {"type": "odds_check_on", "label": "Включить проверку"}))

    return alerts


def _hit_rate(rows):
    wins = sum(1 for row in rows if row.get("success") is True)
    total = sum(1 for row in rows if row.get("success") is not None)
    share = (wins / total * 100.0) if total else 0.0
    return wins, total, share


def apply_action(engine, action):
    """Выполняет рекомендацию. Возвращает (ok, message)."""
    if not isinstance(action, dict):
        return False, "Пустое действие"
    kind = str(action.get("type") or "")
    settings = engine.settings
    predictor = engine.predictor
    try:
        if kind == "neural_freeze":
            settings.update({"neural": {"freeze": True}})
            return True, "Обучение нейросети заморожено"
        if kind == "neural_train":
            predictor.nn.train_now(force=True)
            return True, "Обучение запущено"
        if kind == "neural_sport_off":
            sport = sports.normalize_sport(action.get("sport"))
            current = list(predictor.nn.config().get("sports") or [])
            if sport in current:
                current.remove(sport)
            settings.update({"neural": {"sports": current}})
            return True, "Нейросеть выключена для вида «%s»" % (
                sports.short_name(sport))
        if kind == "auto_rules_off":
            settings.update({"auto_rules": {"enabled": False}})
            return True, "Авто-правила выключены"
        if kind == "auto_rules_on":
            settings.update({"auto_rules": {"enabled": True}})
            engine._refresh_all_auto_rules(force=True)
            return True, "Авто-правила включены"
        if kind == "rule_disable":
            sport = sports.normalize_sport(action.get("sport") or
                                           settings.get_sport())
            rule_id = str(action.get("rule_id") or "")
            rules = predictor.constructor.snapshot(sport)
            changed = False
            for rule in rules:
                if str(rule.get("id")) == rule_id and rule.get("enabled"):
                    rule["enabled"] = False
                    changed = True
            if changed:
                predictor.constructor.save({"rules": rules}, sport)
            return True, "Правило выключено" if changed else (
                "Правило уже выключено")
        if kind == "odds_check_on":
            settings.update({"odds_check_enabled": True})
            return True, "Проверка коэффициентов включена"
        if kind == "interval_up":
            try:
                current = int(settings.snapshot().get("poll_interval_sec") or 20)
            except Exception:
                current = 20
            settings.update({"poll_interval_sec": max(30, current)})
            return True, "Интервал опроса увеличен"
        if kind == "ai_auto_predict_on":
            settings.update({"ai": {"auto_predict": True}})
            return True, "ИИ-прогнозы по линии включены"
    except Exception as exc:
        return False, "Не удалось выполнить: %s" % exc
    return False, "Неизвестное действие: %s" % kind

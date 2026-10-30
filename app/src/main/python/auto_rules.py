# -*- coding: utf-8 -*-
"""Автоматическое формирование и доработка правил конструктора.

Модуль берёт историю отправленных прогнозов (со снимками статистики и
результатами), находит устойчивые признаки удач и неудач и собирает из них
готовые правила конструктора.

Правила помечаются ``auto: true``. Это позволяет движку обновлять только
автоматические правила и никогда не трогать правила, созданные вручную.
Каждое обновление пересчитывает точность на всей доступной истории, поэтому
правила постепенно уточняются по мере накопления статистики.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re

import analyzer
import constructor_engine as ce
import profit
import sports as sport_catalog

# Сколько условий максимум объединять в одном автоматическом правиле.
MAX_CONDITIONS = 2
# Минимальная доля одного действия среди удачных срабатываний правила.
MIN_ACTION_SHARE = 0.60
# Насколько правило должно быть лучше средней точности группы (п.п.).
MIN_IMPROVEMENT = 5.0
# Порог для автоматического правила-пропуска.
SKIP_LOSS_SHARE = 75.0
# Сколько правил одного вида/цели строить.
MAX_PER_GROUP = 1
# Сколько правил-пропусков строить.
MAX_SKIP_RULES = 1

INVERSE_OPS = {
    "gt": "lte", "gte": "lt", "lt": "gte", "lte": "gt",
    "eq": "neq", "neq": "eq", "is": "neq", "is_not": "eq",
    "contains": "not_contains", "not_contains": "contains",
    "in": "not_in", "not_in": "in",
    "exists": "not_exists", "not_exists": "exists",
}

SIDE_ALIASES = {
    "п1": "p1", "п2": "p2", "p1": "p1", "p2": "p2",
    "x": "x", "ничья": "x", "draw": "x",
    "over": "over", "больше": "over", "тб": "over",
    "under": "under", "меньше": "under", "тм": "under",
    "yes": "yes", "да": "yes", "no": "no", "нет": "no",
    "auto": "auto", "": "auto",
}

NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _now():
    return datetime.datetime.now().strftime("%d.%m.%Y %H:%M")


def _number(value):
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def _num(value, default=0.0):
    number = _number(value)
    return default if number is None else number


def _parse_verdict(prediction):
    """Достаёт сторону и линию из старого/нового прогноза."""
    verdict = str(prediction.get("verdict") or "").strip()
    kind = str(prediction.get("kind") or "").lower()
    text = verdict.lower().replace("ё", "е")
    side = SIDE_ALIASES.get(
        str(prediction.get("expected_side") or "").strip().lower(), "auto")
    threshold = _number(prediction.get("threshold"))
    handicap = _number(prediction.get("handicap"))

    if kind == "total":
        if side == "auto":
            if "тм" in text or "меньше" in text or "under" in text:
                side = "under"
            elif "тб" in text or "больше" in text or "over" in text:
                side = "over"
        if threshold is None:
            found = NUMBER_RE.search(verdict)
            threshold = _number(found.group(0)) if found else None
    elif kind == "winner":
        if side == "auto":
            if "п1" in text or "p1" in text:
                side = "p1"
            elif "п2" in text or "p2" in text:
                side = "p2"
            elif "ничья" in text or "x" == text:
                side = "x"
    elif kind == "handicap":
        if side == "auto":
            if "ф1" in text or "p1" in text:
                side = "p1"
            elif "ф2" in text or "p2" in text:
                side = "p2"
        if handicap is None:
            found = NUMBER_RE.search(verdict)
            handicap = _number(found.group(0)) if found else None
    elif kind == "btts":
        if side == "auto":
            if "нет" in text or "no" in text:
                side = "no"
            elif "да" in text or "yes" in text:
                side = "yes"
    return kind, side, threshold, handicap


def action_from_prediction(prediction, confidence=0.6, sport="table_tennis"):
    """Превращает прогноз в действие конструктора."""
    prediction = prediction or {}
    sport = sport_catalog.normalize_sport(sport)
    kind, side, threshold, handicap = _parse_verdict(prediction)
    if kind not in ("winner", "total", "handicap", "btts"):
        return None
    if sport == "table_tennis" and kind not in ("winner", "total"):
        return None

    target = str(prediction.get("target") or "").strip().lower()
    if sport == "table_tennis":
        if not target.startswith("set"):
            return None
        try:
            set_no = int(target.replace("set", ""))
        except Exception:
            return None
        if not 1 <= set_no <= 5:
            return None
        targets = [set_no]
    else:
        targets = ["match"]

    if kind == "winner":
        side = side if side in ("p1", "p2", "x") else "auto"
    elif kind == "total":
        side = side if side in ("over", "under") else "auto"
    elif kind == "handicap":
        side = side if side in ("p1", "p2") else "auto"
    elif kind == "btts":
        side = side if side in ("yes", "no") else "auto"

    default_total = sport_catalog.default_total(sport)
    action = {
        "type": kind,
        "targets": targets,
        "side": side,
        "confidence": round(float(confidence or 0.6), 2),
    }
    if kind == "total":
        action["threshold"] = threshold if threshold is not None else default_total
    if kind == "handicap":
        action["value"] = handicap if handicap is not None else 0
    return action


def _action_key(action, target):
    if not action:
        return ""
    return json.dumps({
        "type": action.get("type"),
        "target": target,
        "side": action.get("side"),
        "threshold": action.get("threshold"),
        "value": action.get("value"),
    }, sort_keys=True, ensure_ascii=False)


def _conditions_key(conditions):
    return json.dumps(conditions or [], sort_keys=True, ensure_ascii=False)


def _invert(condition):
    if not isinstance(condition, dict):
        return None
    op = str(condition.get("op") or "").lower()
    inverse = INVERSE_OPS.get(op)
    if not inverse or condition.get("value_metric"):
        return None
    result = json.loads(json.dumps(condition, ensure_ascii=False))
    result["op"] = inverse
    return result


def _metric_key(condition):
    return "%s|%s" % (
        condition.get("metric", ""),
        json.dumps(condition.get("args") or {}, sort_keys=True,
                   ensure_ascii=False),
    )


def _matched(observations, conditions):
    if not conditions:
        return []
    group = {"logic": "and", "conditions": conditions}
    result = []
    for observation in observations:
        try:
            matched, _ = ce.evaluate_group(observation.get("ctx"), group)
        except Exception:
            matched = False
        if matched:
            result.append(observation)
    return result


def _group_of(observation):
    return (
        str(observation.get("kind") or "").lower(),
        str(observation.get("target") or "").strip().lower(),
    )


def _groups(observations, sport):
    """Группирует наблюдения по рынку и цели (партия/матч)."""
    result = {}
    for observation in observations:
        kind, target = _group_of(observation)
        if kind not in ("winner", "total", "handicap", "btts"):
            continue
        if sport == "table_tennis":
            if not target.startswith("set"):
                continue
        elif target != "match":
            continue
        result.setdefault((kind, target), []).append(observation)
    return result


def _fmt_pct(value):
    return "—" if value is None else ("%.1f" % _num(value))


def _fmt_num(value):
    return "—" if value is None else ("%.1f" % _num(value))


def _fmt_signed(value):
    return "—" if value is None else ("%+.1f" % _num(value))


def _money(observations):
    """Денежная статистика выборки: ROI, EV, просадка, размер ставки."""
    return profit.summarize(profit.rows_for_observations(observations))


def _money_stats(money):
    """Поля денежной статистики для auto_stats и отчётов."""
    money = money or {}
    return {
        "odds_n": money.get("odds_n") or 0,
        "odds_cover": money.get("odds_covered"),
        "avg_odds": money.get("avg_odds"),
        "roi": money.get("roi"),
        "ev": money.get("ev"),
        "ev_lower": money.get("ev_lower"),
        "profit": money.get("profit"),
        "drawdown": money.get("drawdown"),
        "stake_pct": money.get("stake_pct"),
        "profitable": money.get("profitable"),
        "value_ready": money.get("value_ready"),
    }


def _value_ready(money):
    return bool((money or {}).get("odds_available")
                and (money or {}).get("value_ready"))


def _action_from_wins(observations, sport):
    """Самое частое действие среди удачных наблюдений."""
    counts = {}
    examples = {}
    for observation in observations:
        if not observation.get("success"):
            continue
        action = action_from_prediction(
            observation.get("prediction") or {},
            confidence=0.6, sport=sport)
        if not action:
            continue
        key = _action_key(action, observation.get("target"))
        counts[key] = counts.get(key, 0) + 1
        examples.setdefault(key, action)
    if not counts:
        return None, 0, 0
    key = max(counts, key=lambda item: counts[item])
    wins = sum(1 for item in observations if item.get("success"))
    share = counts[key] / wins if wins else 0.0
    return examples[key], counts[key], share


def _candidate_sets(success_rows, failure_rows):
    """Готовые наборы условий: удачи, обратные неудачи и их смесь."""
    sets = []
    seen = set()

    def add(conditions, source):
        if not conditions or len(conditions) > MAX_CONDITIONS:
            return
        key = _conditions_key(conditions)
        if key in seen:
            return
        seen.add(key)
        sets.append((conditions, source))

    success = [row.get("condition") for row in (success_rows or [])
               if isinstance(row.get("condition"), dict)]
    failure = []
    for row in failure_rows or []:
        inverted = _invert(row.get("condition"))
        if inverted:
            failure.append(inverted)

    for condition in success[:3]:
        add([condition], "success")
    if len(success) >= 2:
        for index in range(min(3, len(success) - 1)):
            left, right = success[index], success[index + 1]
            if _metric_key(left) != _metric_key(right):
                add([left, right], "success")

    for condition in failure[:3]:
        add([condition], "failure")
    if len(failure) >= 2:
        for index in range(min(3, len(failure) - 1)):
            left, right = failure[index], failure[index + 1]
            if _metric_key(left) != _metric_key(right):
                add([left, right], "failure")

    if success and failure:
        left = success[0]
        for right in failure[:3]:
            if _metric_key(left) != _metric_key(right):
                add([left, right], "mixed")
                break
    return sets


def _candidate(conditions, observations, sport, min_samples, min_precision,
               source):
    """Кандидат в авто-правило: сначала прибыль, потом точность.

    Если в истории есть коэффициенты, правило должно не просто угадывать
    чаще, а давать положительный ROI и EV. Высокая точность при низком
    коэффициенте отклоняется: такие ставки убыточны на дистанции.
    Без коэффициентов остаётся прежний порог точности.
    """
    matched = _matched(observations, conditions)
    total = len(matched)
    if total < min_samples:
        return None
    wins = sum(1 for item in matched if item.get("success"))
    if wins < 2:
        return None
    precision = wins / total * 100.0
    base = sum(1 for item in observations if item.get("success"))
    base = base / len(observations) * 100.0 if observations else 0.0
    money = _money(matched)
    base_money = _money(observations)
    value_mode = _value_ready(money)
    validation = profit.validation(profit.rows_for_observations(matched))
    if value_mode:
        roi = _num(money.get("roi"), -999.0)
        ev = _num(money.get("ev"), -999.0)
        ev_lower = _num(money.get("ev_lower"), -999.0)
        base_roi = _num(base_money.get("roi"), 0.0)
        # Убыточное правило не создаём, даже если точность высокая.
        if roi <= 0 or ev <= 0:
            return None
        if validation.get("ok") is False:
            return None
        if precision < 35.0:
            return None
        if roi < max(1.0, base_roi + MIN_IMPROVEMENT * 0.4) and \
                precision < min_precision:
            return None
    else:
        if precision < max(min_precision, base + MIN_IMPROVEMENT):
            return None

    action, action_wins, action_share = _action_from_wins(matched, sport)
    if not action or action_share < MIN_ACTION_SHARE:
        return None
    action["confidence"] = round(min(0.90, max(0.55, precision / 100.0)), 2)
    target = str(matched[0].get("target") or "")
    key = _action_key(action, target) + "|" + _conditions_key(conditions)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    stats = {
        "precision": round(precision, 1),
        "coverage": round(total / len(observations) * 100.0, 1),
        "matched": total,
        "wins": wins,
        "losses": total - wins,
        "base_precision": round(base, 1),
        "action_wins": action_wins,
        "updated_at": _now(),
    }
    stats.update(_money_stats(money))
    stats["validation_roi"] = (validation.get("holdout") or {}).get("roi")
    stats["validation_n"] = (validation.get("holdout") or {}).get("staked")
    stats["validation_ok"] = validation.get("ok")
    score = _candidate_score(precision, total, money, min_samples)
    priority = 130 if precision >= 70 else (120 if precision >= 62 else 110)
    if value_mode:
        priority = 140 if money.get("profitable") else priority
    return {
        "id": "auto_" + digest,
        "name": "",
        "sport": sport,
        "enabled": True,
        "priority": priority,
        "stop": False,
        "conditions": {"logic": "and", "conditions": conditions},
        "action": action,
        "auto": True,
        "auto_key": digest,
        "auto_kind": str(matched[0].get("kind") or ""),
        "auto_target": target,
        "auto_source": source,
        "auto_stats": stats,
        "_score": score,
    }


def _candidate_score(precision, total, money, min_samples):
    """Оценка кандидата: прибыль важнее точности."""
    coverage = min(1.0, total / max(1.0, float(min_samples or 6) * 2.0))
    if _value_ready(money):
        roi = _num(money.get("roi"), 0.0)
        ev_lower = _num(money.get("ev_lower"), 0.0)
        score = 50.0 + roi * 1.6 + max(-5.0, ev_lower) * 1.2
        score += coverage * 6.0
        return round(score, 3)
    return round(precision * coverage, 3)


def _skip_candidate(group, failure_rows, min_samples):
    """Правило-пропуск: условие, которое почти всегда приводит к неудаче."""
    if not failure_rows or not group:
        return None
    total = len(group)
    kind, target = _group_of(group[0])
    for row in failure_rows[:4]:
        condition = row.get("condition")
        matched = _matched(group, [condition] if condition else [])
        if len(matched) < max(3, min_samples // 2):
            continue
        losses = sum(1 for item in matched if not item.get("success"))
        loss_share = losses / len(matched) * 100.0
        if loss_share < SKIP_LOSS_SHARE:
            continue
        # Не блокируем больше половины группы: иначе правило бесполезно.
        if total and len(matched) > total * 0.5:
            continue
        key = "skip|%s|%s|%s" % (kind, target, _conditions_key([condition]))
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        return {
            "id": "auto_" + digest,
            "name": "",
            "sport": "",
            "enabled": True,
            "priority": 100,
            "stop": False,
            "conditions": {"logic": "and", "conditions": [condition]},
            "action": {
                "type": "skip", "targets": ["match"], "side": "auto",
                "confidence": 0.6,
            },
            "auto": True,
            "auto_key": digest,
            "auto_kind": kind,
            "auto_target": target,
            "auto_source": "failure",
            "auto_stats": {
                "precision": round(loss_share, 1),
                "coverage": round(len(matched) / total * 100.0, 1) if total else 0.0,
                "matched": len(matched),
                "wins": len(matched) - losses,
                "losses": losses,
                "base_precision": round(
                    sum(1 for item in group if not item.get("success"))
                    / total * 100.0, 1) if total else 0.0,
                "updated_at": _now(),
            },
            "_score": loss_share,
        }
    return None


def _existing_candidates(existing_rules, observations, sport, min_samples,
                         min_precision):
    """Перепроверяет уже созданные авто-правила на свежих данных.

    В режиме коэффициентов правило остаётся в наборе только если оно не
    убыточно и хотя бы на части новых матчей подтверждает прибыль. Высокая
    точность без положительного EV больше не считается успехом.
    """
    result = []
    for rule in existing_rules or []:
        if not rule.get("auto"):
            continue
        kind = str(rule.get("auto_kind") or "").lower()
        target = str(rule.get("auto_target") or "").lower()
        if not target:
            continue
        group = [item for item in observations if _group_of(item) == (kind, target)]
        if not group:
            continue
        conditions = ((rule.get("conditions") or {}).get("conditions") or [])
        matched = _matched(group, conditions)
        is_skip = (rule.get("action") or {}).get("type") == "skip"
        need = max(3, min_samples // 2) if is_skip else min_samples
        if len(matched) < need:
            continue
        money = _money(matched)
        validation = profit.validation(profit.rows_for_observations(matched))
        value_mode = _value_ready(money)
        if is_skip:
            losses = sum(1 for item in matched if not item.get("success"))
            precision = losses / len(matched) * 100.0
            # Фильтр полезен, если отсекает убыточные ставки, а не просто
            # повышает точность.
            if value_mode:
                if _num(money.get("profit"), 0.0) >= 0 and \
                        precision < SKIP_LOSS_SHARE:
                    continue
            elif precision < SKIP_LOSS_SHARE:
                continue
        else:
            wins = sum(1 for item in matched if item.get("success"))
            precision = wins / len(matched) * 100.0
            if value_mode:
                roi = _num(money.get("roi"), -999.0)
                ev = _num(money.get("ev"), -999.0)
                if validation.get("ok") is False:
                    continue
                if roi < -2.0 and ev < 0:
                    continue
                if roi <= 0 and precision < min_precision:
                    continue
            elif precision < min_precision:
                continue
        item = json.loads(json.dumps(rule, ensure_ascii=False))
        stats = item.setdefault("auto_stats", {})
        stats.update({
            "precision": round(precision, 1),
            "coverage": round(len(matched) / len(group) * 100.0, 1),
            "matched": len(matched),
            "updated_at": _now(),
        })
        stats.update(_money_stats(money))
        stats["validation_ok"] = validation.get("ok")
        stats["validation_roi"] = (validation.get("holdout") or {}).get("roi")
        action = item.get("action") or {}
        if action.get("type") != "skip":
            action["confidence"] = round(
                min(0.90, max(0.55, precision / 100.0)), 2)
        item["_score"] = _candidate_score(
            precision, len(matched), money, min_samples)
        result.append(item)
    return result


def _rule_name(rule, sport):
    action = rule.get("action") or {}
    text = ce.describe_action(action, sport)
    stats = rule.get("auto_stats") or {}
    precision = stats.get("precision")
    matched = stats.get("matched")
    if action.get("type") == "skip":
        return "Авто-фильтр · %s (n=%s)" % (text, matched or 0)
    suffix = ""
    if precision is not None:
        suffix = " · %s%%" % precision
    if matched:
        suffix += " (n=%s)" % matched
    return "Авто · %s%s" % (text, suffix)


MARKET_TITLES = {
    "winner": "Победитель",
    "total": "Тотал",
    "handicap": "Фора",
    "btts": "Обе забьют",
    "skip": "Фильтр",
}

VERDICT_LEVEL = {
    "disable": 0, "tighten": 1, "loosen": 2, "confidence": 3,
    "collect": 4, "no_data": 5, "keep": 6,
}


def _rule_market(rule, sport):
    """Рынок и цель правила: (kind, target) или ("", "")."""
    action = rule.get("action") or {}
    is_skip = str(action.get("type") or "").lower() == "skip"
    kind = str(rule.get("auto_kind") or action.get("type") or "").lower()
    if is_skip:
        kind = str(rule.get("auto_kind") or "").lower()
    target = str(rule.get("auto_target") or "").strip().lower()
    if not target:
        targets = action.get("targets") or []
        if sport == "table_tennis":
            for value in targets:
                text = str(value).strip().lower()
                if text.startswith("set"):
                    target = text
                elif text.isdigit():
                    target = "set%s" % text
                if target:
                    break
        else:
            target = "match"
    if kind not in ("winner", "total", "handicap", "btts"):
        return "", ""
    if sport == "table_tennis":
        if not target.startswith("set"):
            return "", ""
    elif target != "match":
        return "", ""
    return kind, target


def _rule_conditions(rule):
    group = rule.get("conditions")
    if not isinstance(group, dict):
        return {"logic": "and", "conditions": []}
    if "metric" in group:
        return {"logic": "and", "conditions": [group]}
    conditions = group.get("conditions")
    if not isinstance(conditions, list):
        conditions = []
    return {
        "logic": "or" if str(group.get("logic", "and")).lower() == "or"
                 else "and",
        "conditions": conditions,
    }


def _matched_group(observations, group):
    result = []
    for observation in observations:
        try:
            matched, _ = ce.evaluate_group(observation.get("ctx"), group)
        except Exception:
            matched = False
        if matched:
            result.append(observation)
    return result


def _target_title(target, sport):
    if sport == "table_tennis" and target.startswith("set"):
        return "партия %s" % target.replace("set", "")
    return "матч"


def review_rules(sent_predictions, sport, rules=None, observations=None,
                 min_samples=6, min_precision=60.0):
    """Проверяет включённые правила на истории и предлагает правки.

    Возвращает список отзывов: точность, покрытие и готовый ``patch``,
    который интерфейс может применить одной кнопкой (отключить, ужесточить,
    расширить, поправить уверенность).
    """
    sport = sport_catalog.normalize_sport(sport)
    try:
        min_samples = max(3, min(50, int(min_samples or 6)))
    except Exception:
        min_samples = 6
    try:
        min_precision = max(50.0, min(95.0, float(min_precision or 60.0)))
    except Exception:
        min_precision = 60.0

    if observations is None:
        try:
            observations = analyzer.build_observations(
                sent_predictions, sport=sport)
        except Exception as exc:
            return {
                "ok": False, "error": str(exc), "sport": sport,
                "reviews": [], "total": 0, "active": 0, "disabled": 0,
                "counts": {}, "hint": "Не удалось разобрать историю.",
            }

    groups = _groups(observations, sport)
    reviews = []
    disabled = 0
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        if not rule.get("enabled", True):
            disabled += 1
            continue
        action = rule.get("action") or {}
        is_skip = str(action.get("type") or "").lower() == "skip"
        kind, target = _rule_market(rule, sport)
        if not kind:
            continue
        group = groups.get((kind, target)) or []
        condition_group = _rule_conditions(rule)
        conditions = condition_group.get("conditions") or []
        if conditions:
            matched = _matched_group(group, condition_group)
        else:
            matched = list(group)
        total = len(matched)
        wins = sum(1 for item in matched if item.get("success"))
        losses = total - wins
        group_wins = sum(1 for item in group if item.get("success"))
        base = (group_wins / len(group) * 100.0) if group else 0.0
        if is_skip:
            base = ((len(group) - group_wins) / len(group) * 100.0) \
                if group else 0.0
            precision = (losses / total * 100.0) if total else 0.0
        else:
            precision = (wins / total * 100.0) if total else 0.0
        money = _money(matched)
        validation = profit.validation(profit.rows_for_observations(matched))
        value_mode = _value_ready(money) and not is_skip
        value_bad = bool(value_mode and (
            _num(money.get("ev_lower"), 0.0) <= -1.0 or
            _num(money.get("roi"), 0.0) <= -2.0))

        name = str(rule.get("name") or "").strip()
        if not name:
            name = str(rule.get("action_text") or "").strip() or \
                ce.describe_action(action, sport)
        title = "%s · %s (%s)" % (
            name, MARKET_TITLES.get(kind, kind), _target_title(target, sport))

        review = {
            "id": rule.get("id", ""),
            "name": name,
            "title": title,
            "auto": bool(rule.get("auto")),
            "skip": is_skip,
            "kind": kind,
            "target": target,
            "market": MARKET_TITLES.get(kind, kind),
            "target_title": _target_title(target, sport),
            "action_text": rule.get("action_text") or ce.describe_action(
                action, sport),
            "conditions_text": rule.get("conditions_text") or ce.describe_group(
                condition_group, sport=sport),
            "matched": total,
            "wins": wins,
            "losses": losses,
            "precision": round(precision, 1),
            "base_precision": round(base, 1),
            "lift": round(precision - base, 1),
            "group_size": len(group),
            "confidence": float(action.get("confidence") or 0.0),
            "value_mode": value_mode,
            "roi": money.get("roi"),
            "ev": money.get("ev"),
            "ev_lower": money.get("ev_lower"),
            "avg_odds": money.get("avg_odds"),
            "odds_n": money.get("odds_n") or 0,
            "profit": money.get("profit"),
            "drawdown": money.get("drawdown"),
            "stake_pct": money.get("stake_pct"),
            "profitable": money.get("profitable"),
            "validation_roi": (validation.get("holdout") or {}).get("roi"),
            "validation_ok": validation.get("ok"),
            "verdict": "collect",
            "label": "",
            "suggestion": "",
            "patch": None,
        }

        if not group:
            review["verdict"] = "no_data"
            review["suggestion"] = (
                "Нет прогнозов по рынку «%s» (%s) с результатами — "
                "проверять нечего." % (
                    MARKET_TITLES.get(kind, kind),
                    _target_title(target, sport)))
            reviews.append(review)
            continue
        if total == 0:
            review["verdict"] = "no_data"
            review["suggestion"] = (
                "Условия правила ни разу не совпали с историей. Проверьте "
                "пороги или дождитесь матчей с такими данными.")
            reviews.append(review)
            continue
        if total < min_samples:
            review["verdict"] = "collect"
            review["suggestion"] = (
                "Сработало %d раз, нужно минимум %d. Пока рано менять "
                "правило — данных мало." % (total, min_samples))
            reviews.append(review)
            continue

        if is_skip:
            saved = -_num(money.get("profit"), 0.0) if money.get("odds_available") \
                else 0.0
            useful_by_money = bool(money.get("odds_available")
                                   and _num(money.get("profit"), 0.0) < 0)
            if precision >= SKIP_LOSS_SHARE or useful_by_money:
                review["verdict"] = "keep"
                if useful_by_money:
                    review["suggestion"] = (
                        "Оставить: без фильтра эти матчи дали бы %+.1f ед. "
                        "прибыли (ROI %s%%), фильтр экономит %.1f ед. и "
                        "отсекает %.0f%% неудач." % (
                            _num(money.get("profit"), 0.0),
                            _fmt_pct(money.get("roi")), saved, precision))
                else:
                    review["suggestion"] = (
                        "Оставить: фильтр отсекает %.0f%% неудачных "
                        "прогнозов при пороге %.0f%%." % (
                            precision, SKIP_LOSS_SHARE))
            else:
                review["verdict"] = "disable"
                review["label"] = "Отключить"
                if money.get("odds_available"):
                    review["suggestion"] = (
                        "Отключить: ставки, которые фильтр отсекает, дают "
                        "%+.1f ед. (ROI %s%%), то есть фильтр не спасает "
                        "деньги, а только режет выборку." % (
                            _num(money.get("profit"), 0.0),
                            _fmt_pct(money.get("roi"))))
                else:
                    review["suggestion"] = (
                        "Отключить: фильтр отсекает только %.0f%% неудач, "
                        "нужно ≥ %.0f%%." % (precision, SKIP_LOSS_SHARE))
                review["patch"] = {"enabled": False}
            reviews.append(review)
            continue

        if precision < min_precision or value_bad:
            candidate = _tighten_rule(
                sent_predictions, matched, condition_group, sport,
                min_precision, min_samples)
            if candidate:
                review["verdict"] = "tighten"
                review["label"] = "Ужесточить"
                if candidate.get("value_mode"):
                    review["suggestion"] = (
                        "Добавить «%s»: останется %d ставок, ROI %s%% → "
                        "%s%%, EV %s%% → %s%%. Правило станет прибыльнее, "
                        "даже если точность изменится." % (
                            candidate["text"], candidate["matched"],
                            _fmt_pct(money.get("roi")),
                            _fmt_pct(candidate.get("roi")),
                            _fmt_signed(money.get("ev")),
                            _fmt_signed(candidate.get("ev"))))
                else:
                    review["suggestion"] = (
                        "Добавить «%s»: останется %d срабатываний с "
                        "точностью %.0f%% вместо %.0f%%." % (
                            candidate["text"], candidate["matched"],
                            candidate["precision"], precision))
                review["patch"] = candidate["patch"]
            elif value_bad:
                review["verdict"] = "disable"
                review["label"] = "Отключить"
                review["suggestion"] = (
                    "Отключить: правило убыточно — ROI %s%%, EV %s%% при "
                    "среднем коэффициенте %s. Высокая точность не спасает, "
                    "если коэффициент ниже справедливого. Условия, которое "
                    "выводит правило в плюс, не нашлось." % (
                        _fmt_pct(money.get("roi")),
                        _fmt_signed(money.get("ev")),
                        _fmt_num(money.get("avg_odds"))))
                review["patch"] = {"enabled": False}
            elif precision < 50.0 or precision + 5.0 < base:
                review["verdict"] = "disable"
                review["label"] = "Отключить"
                review["suggestion"] = (
                    "Отключить: точность %.0f%% ниже цели %.0f%% и ниже "
                    "средней по рынку %.0f%%. Надёжного условия для "
                    "ужесточения не нашлось." % (
                        precision, min_precision, base))
                review["patch"] = {"enabled": False}
            else:
                review["verdict"] = "disable"
                review["label"] = "Отключить"
                review["suggestion"] = (
                    "Точность %.0f%% ниже цели %.0f%%, а добавить условие "
                    "без потери данных не удалось. Отключите правило или "
                    "пересоберите его в конструкторе." % (
                        precision, min_precision))
                review["patch"] = {"enabled": False}
            reviews.append(review)
            continue

        loose = _loosen_rule(
            group, condition_group, sport, min_precision, precision, total)
        if loose:
            review["verdict"] = "loosen"
            review["label"] = "Расширить"
            if loose.get("value_mode"):
                review["suggestion"] = (
                    "Снять «%s»: ставок станет %d вместо %d, ROI %s%%, "
                    "EV %s%% — прибыль не падает, а выборка растёт." % (
                        loose["text"], loose["matched"], total,
                        _fmt_pct(loose.get("roi")),
                        _fmt_signed(loose.get("ev"))))
            else:
                review["suggestion"] = (
                    "Снять «%s»: правило начнёт срабатывать %d раз вместо "
                    "%d, точность %.0f%%." % (
                        loose["text"], loose["matched"], total,
                        loose["precision"]))
            review["patch"] = loose["patch"]
            reviews.append(review)
            continue

        confidence = float(action.get("confidence") or 0.0)
        if abs(confidence * 100.0 - precision) >= 12.0:
            target_conf = round(min(0.90, max(0.55, precision / 100.0)), 2)
            updated = json.loads(json.dumps(action, ensure_ascii=False))
            updated["confidence"] = target_conf
            review["verdict"] = "confidence"
            review["label"] = "Поправить уверенность"
            review["suggestion"] = (
                "Точность %.0f%%, а в действии уверенность %.0f%%. "
                "Поставить %.0f%% — прогноз будет честнее." % (
                    precision, confidence * 100.0, target_conf * 100.0))
            review["patch"] = {"action": updated}
            reviews.append(review)
            continue

        review["verdict"] = "keep"
        if value_mode and money.get("odds_available"):
            review["suggestion"] = (
                "Оставить: правило прибыльно — ROI %s%%, EV %s%% на %d "
                "ставках, просадка %s ед. Точность %.0f%% при цели %.0f%%. "
                "Проверка на новых матчах: ROI %s%%." % (
                    _fmt_pct(money.get("roi")),
                    _fmt_signed(money.get("ev")),
                    money.get("odds_n") or 0,
                    _fmt_num(money.get("drawdown")), precision,
                    min_precision,
                    _fmt_pct((validation.get("holdout") or {}).get("roi"))))
        else:
            review["suggestion"] = (
                "Оставить: точность %.0f%% при цели %.0f%% и %d "
                "срабатываниях." % (precision, min_precision, total))
        reviews.append(review)

    reviews.sort(key=lambda item: (
        VERDICT_LEVEL.get(item.get("verdict"), 9),
        -float(item.get("matched") or 0)))
    counts = {}
    for item in reviews:
        verdict = item.get("verdict") or "keep"
        counts[verdict] = counts.get(verdict, 0) + 1
    hint = ""
    if not reviews:
        hint = ("Нет включённых правил для проверки. Включите правила в "
                "конструкторе или дождитесь, пока авто-правила соберутся.")
    elif not any(item.get("verdict") in ("disable", "tighten", "loosen",
                                        "confidence")
                 for item in reviews):
        hint = ("Активные правила выглядят устойчиво: правок не требуется. "
                "Проверка обновится по мере накопления результатов.")
    return {
        "ok": True,
        "sport": sport,
        "reviews": reviews,
        "total": len(reviews),
        "active": len(reviews),
        "disabled": disabled,
        "counts": counts,
        "hint": hint,
        "updated_at": _now(),
    }


def _tighten_rule(sent_predictions, matched, condition_group, sport,
                  min_precision, min_samples):
    """Ищет правку, которая повышает прибыль правила, а не только точность.

    Сначала проверяется добавление признака из неудач, затем — минимальный
    коэффициент. В режиме коэффициентов побеждает вариант с лучшим ROI и
    подтверждением на новых матчах; без коэффициентов — по точности.
    """
    if not matched:
        return None
    # Добавлять условие можно только к логике «И». Для «ИЛИ» новое условие
    # наоборот расширило бы правило и повысило бы охват неудач.
    if str(condition_group.get("logic") or "and").lower() != "and":
        return None
    old_wins = sum(1 for item in matched if item.get("success"))
    old_precision = old_wins / len(matched) * 100.0
    old_money = _money(matched)
    old_value = _value_ready(old_money)
    old_roi = _num(old_money.get("roi"), 0.0)
    old_ev_lower = _num(old_money.get("ev_lower"), 0.0)
    best = None

    def consider(condition, text, kept, floor=None):
        nonlocal best
        if len(kept) < max(3, int(min_samples or 6) // 2):
            return
        wins = sum(1 for item in kept if item.get("success"))
        precision = wins / len(kept) * 100.0
        money = _money(kept)
        validation = profit.validation(profit.rows_for_observations(kept))
        value_mode = bool(old_value and _value_ready(money))
        if value_mode:
            roi = _num(money.get("roi"), -999.0)
            ev_lower = _num(money.get("ev_lower"), -999.0)
            if roi < max(0.5, old_roi + 2.0):
                return
            if ev_lower <= old_ev_lower:
                return
            if validation.get("ok") is False:
                return
            score = roi * 1.4 + max(0.0, ev_lower) * 1.2
        else:
            if precision < max(min_precision, old_precision + 5.0):
                return
            removed = len(matched) - len(kept)
            if removed < 1:
                return
            score = precision + min(removed, 5) * 0.5
        patch_group = json.loads(json.dumps(condition_group,
                                            ensure_ascii=False))
        patch_group["conditions"] = list(
            patch_group.get("conditions") or []) + [condition]
        candidate = {
            "text": text,
            "matched": len(kept),
            "precision": precision,
            "score": score,
            "patch": {"conditions": patch_group},
            "roi": money.get("roi"),
            "ev": money.get("ev"),
            "ev_lower": money.get("ev_lower"),
            "profit": money.get("profit"),
            "value_mode": value_mode,
            "validation_ok": validation.get("ok"),
        }
        if floor is not None:
            candidate["floor"] = floor
            candidate["condition"] = condition
        if best is None or score > best["score"]:
            best = candidate

    # 1. Признак из неудач.
    try:
        payload = analyzer.analyze(
            sent_predictions, observations=matched, min_group=2,
            min_lift=5.0, min_hits=1, max_rows=10, with_pairs=False,
            with_means=False, sport=sport)
    except Exception:
        payload = {}
    for row in payload.get("failure") or []:
        inverse = _invert(row.get("condition"))
        if not inverse:
            continue
        kept = _matched(matched, [inverse])
        consider(inverse, ce.describe_condition(inverse, sport=sport), kept)

    # 2. Минимальный коэффициент: отсекает дешёвые ставки с отрицательным EV.
    if old_value:
        floor = profit.best_odds_floor(matched, old_money, max(3, min_samples // 2))
        if floor:
            prediction = dict((matched[0].get("prediction") or {}))
            prediction["kind"] = matched[0].get("kind")
            condition = profit.odds_condition(prediction, floor["floor"])
            if condition:
                kept = [item for item in matched
                        if (profit.odds_for_observation(item) or 0)
                        >= floor["floor"]]
                consider(condition, "коэффициент ≥ %.2f" % floor["floor"],
                         kept, floor=floor["floor"])

    if not best:
        return None
    best.pop("score", None)
    return best


def _loosen_rule(group, condition_group, sport, min_precision, precision,
                 total):
    """Ищет условие, которое можно снять без потери прибыли."""
    conditions = list(condition_group.get("conditions") or [])
    if len(conditions) < 2 or condition_group.get("logic") != "and":
        return None
    old_money = _money(_matched_group(group, condition_group))
    old_value = _value_ready(old_money)
    old_roi = _num(old_money.get("roi"), 0.0)
    old_ev_lower = _num(old_money.get("ev_lower"), 0.0)
    best = None
    for index, condition in enumerate(conditions):
        rest = conditions[:index] + conditions[index + 1:]
        candidate_group = {"logic": "and", "conditions": rest}
        matched = _matched_group(group, candidate_group)
        if len(matched) < total + 2:
            continue
        wins = sum(1 for item in matched if item.get("success"))
        new_precision = wins / len(matched) * 100.0
        money = _money(matched)
        validation = profit.validation(profit.rows_for_observations(matched))
        value_mode = bool(old_value and _value_ready(money))
        if value_mode:
            roi = _num(money.get("roi"), -999.0)
            ev_lower = _num(money.get("ev_lower"), -999.0)
            if roi < old_roi - 1.0 or ev_lower < old_ev_lower - 0.5:
                continue
            if validation.get("ok") is False:
                continue
            score = (len(matched) - total) * 0.2 + roi * 0.5 + \
                new_precision * 0.1
        else:
            if new_precision < max(min_precision - 2.0, precision - 5.0):
                continue
            score = len(matched) * 0.1 + new_precision
        if best is None or score > best["score"]:
            best = {
                "text": ce.describe_condition(condition, sport=sport),
                "matched": len(matched),
                "precision": new_precision,
                "score": score,
                "patch": {"conditions": candidate_group},
                "roi": money.get("roi"),
                "ev": money.get("ev"),
                "ev_lower": money.get("ev_lower"),
                "value_mode": value_mode,
            }
    if not best:
        return None
    best.pop("score", None)
    return best


def generate(sent_predictions, sport, min_precision=60.0, min_samples=6,
             max_rules=4, existing_rules=None):
    """Строит новые авто-правила и перепроверяет старые.

    Возвращает словарь с правилами, отчётом и сигнатурой для движка.
    """
    sport = sport_catalog.normalize_sport(sport)
    min_precision = max(50.0, min(95.0, float(min_precision or 60.0)))
    min_samples = max(3, min(50, int(min_samples or 6)))
    max_rules = max(1, min(12, int(max_rules or 4)))

    try:
        observations = analyzer.build_observations(sent_predictions, sport=sport)
    except Exception as exc:
        return {
            "ok": False, "error": str(exc), "rules": [], "generated": 0,
            "signature": "", "observations": 0, "groups": [],
        }

    if not observations:
        return {
            "ok": True, "rules": [], "generated": 0,
            "signature": "empty|%s" % sport, "observations": 0,
            "groups": [], "hint": "Нет прогнозов с результатами и статистикой.",
        }

    groups = _groups(observations, sport)
    candidates = []
    skip_candidates = []
    reports = []

    for (kind, target), group in groups.items():
        wins = sum(1 for item in group if item.get("success"))
        losses = len(group) - wins
        money = _money(group)
        if wins < min_samples or losses < 2:
            reports.append({
                "kind": kind, "target": target, "wins": wins,
                "losses": losses, "rules": 0,
                "roi": money.get("roi"), "ev": money.get("ev"),
                "reason": "мало данных",
            })
            continue
        min_group = max(2, min(3, wins, losses))
        try:
            payload = analyzer.analyze(
                sent_predictions, kind=kind, target=target,
                min_group=min_group, min_lift=10.0, min_hits=2,
                max_rows=8, with_pairs=False, with_means=False, sport=sport)
        except Exception as exc:
            reports.append({
                "kind": kind, "target": target, "wins": wins,
                "losses": losses, "rules": 0, "reason": str(exc),
            })
            continue

        found = []
        for conditions, source in _candidate_sets(
                payload.get("success") or [], payload.get("failure") or []):
            candidate = _candidate(
                conditions, group, sport, min_samples, min_precision, source)
            if candidate:
                found.append(candidate)
        found.sort(key=lambda item: -item.get("_score", 0))
        candidates.extend(found[:MAX_PER_GROUP])
        skip = _skip_candidate(
            group, payload.get("failure") or [], min_samples)
        if skip:
            skip["sport"] = sport
            skip_candidates.append(skip)
        reports.append({
            "kind": kind, "target": target, "wins": wins,
            "losses": losses, "rules": len(found[:MAX_PER_GROUP]),
            "roi": money.get("roi"), "ev": money.get("ev"),
            "odds_n": money.get("odds_n"),
        })

    # Старые авто-правила участвуют в конкурсе, если ещё точны.
    existing = _existing_candidates(
        existing_rules, observations, sport, min_samples, min_precision)
    candidates.extend([
        item for item in existing
        if (item.get("action") or {}).get("type") != "skip"])
    existing_skips = [
        item for item in existing
        if (item.get("action") or {}).get("type") == "skip"]

    # Дедупликация по ключу действия + условий, оставляем лучшую точность.
    best = {}
    for candidate in candidates:
        key = (candidate.get("auto_key") or "") + "|" + \
              _conditions_key(((candidate.get("conditions") or {}).get("conditions") or []))
        current = best.get(key)
        if current is None or (candidate.get("_score", 0) >
                               current.get("_score", 0)):
            best[key] = candidate
    ordered = sorted(best.values(), key=lambda item: -item.get("_score", 0))

    skip_candidates.extend(existing_skips)
    skip_candidates.sort(key=lambda item: -item.get("_score", 0))
    skip = skip_candidates[0] if skip_candidates else None

    prediction_rules = ordered[:max_rules]
    if skip:
        prediction_rules.append(skip)

    for rule in prediction_rules:
        rule.pop("_score", None)
        if not rule.get("sport"):
            rule["sport"] = sport
        rule["name"] = _rule_name(rule, sport)

    signature = hashlib.sha1(json.dumps([
        sport, min_precision, min_samples,
        [(rule.get("auto_key"), rule.get("name"),
          (rule.get("auto_stats") or {}).get("precision"),
          (rule.get("auto_stats") or {}).get("roi"))
         for rule in prediction_rules],
    ], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]

    return {
        "ok": True,
        "rules": prediction_rules,
        "generated": len(prediction_rules),
        "signature": signature,
        "observations": len(observations),
        "groups": reports,
        "updated_at": _now(),
        "hint": "" if prediction_rules else
                ("Пока нет правил с подтверждённой прибылью. Нужно больше "
                 "результатов и коэффициентов: точность без EV не "
                 "гарантирует заработок на дистанции."),
    }


def summarize(rules):
    """Короткая сводка авто-правил для интерфейса."""
    items = []
    for rule in rules or []:
        if not rule.get("auto"):
            continue
        stats = rule.get("auto_stats") or {}
        items.append({
            "id": rule.get("id", ""),
            "name": rule.get("name", ""),
            "enabled": bool(rule.get("enabled", True)),
            "action_text": rule.get("action_text") or ce.describe_action(
                rule.get("action")),
            "precision": stats.get("precision"),
            "coverage": stats.get("coverage"),
            "matched": stats.get("matched"),
            "wins": stats.get("wins"),
            "losses": stats.get("losses"),
            "updated_at": stats.get("updated_at", ""),
            "skip": (rule.get("action") or {}).get("type") == "skip",
            "roi": stats.get("roi"),
            "ev": stats.get("ev"),
            "ev_lower": stats.get("ev_lower"),
            "avg_odds": stats.get("avg_odds"),
            "odds_n": stats.get("odds_n"),
            "profit": stats.get("profit"),
            "drawdown": stats.get("drawdown"),
            "stake_pct": stats.get("stake_pct"),
            "profitable": stats.get("profitable"),
            "value_ready": stats.get("value_ready"),
        })
    return items

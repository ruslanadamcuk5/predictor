# -*- coding: utf-8 -*-
"""Рекомендации по активным правилам конструктора.

Модуль связывает три вещи, которые раньше жили отдельно:

* историю прогнозов (снимок статистики + проверенный результат);
* включённые правила выбранных видов спорта;
* находки анализатора (какие условия отличают удачи от неудач).

На выходе — готовые к применению рекомендации вида «добавьте условие X
именно в правило Y». У каждой рекомендации стабильный ``id``, поэтому
интерфейс может:

1. показать, что она новая;
2. применить её одной кнопкой;
3. убрать её из списка, как только условие уже есть в правиле (в том числе
   если пользователь добавил его вручную в конструкторе);
4. не показывать скрытые рекомендации до истечения паузы;
5. отслеживать новые рекомендации по мере накопления результатов.

Состояние (просмотрено/скрыто/применено) хранится отдельным JSON-файлом в
приватной папке приложения. Сам модуль ничего не пишет на диск: путь и
загрузка/сохранение состояния — забота ``engine_api``. Это позволяет
использовать тот же расчёт и на сервере, где файловой истории телефона нет.
"""

from __future__ import annotations

import datetime
import hashlib
import json

import analyzer
import auto_rules
import constructor_engine as ce
import sports as sport_catalog

STATE_VERSION = 1
# Минимальный прирост точности, ради которого стоит менять правило (п.п.).
MIN_GAIN = 5.0
# Сколько срабатываний должно остаться после добавления условия.
MIN_KEPT = 3
# Сколько рекомендаций отдавать за один расчёт.
MAX_RECOMMENDATIONS = 20
# Сколько дней скрывать отклонённую рекомендацию.
DISMISS_DAYS = 7
# Ограничения на размер состояния, чтобы файл не рос бесконечно.
MAX_SEEN = 600
MAX_APPLIED = 300
MAX_RESOLVED = 300
MAX_DISMISSED = 300

TYPE_TITLES = {
    "add_condition": "Добавить условие",
    "remove_condition": "Убрать условие",
    "disable_rule": "Отключить правило",
    "adjust_confidence": "Поправить уверенность",
}

SEVERITY = {
    "disable_rule": "critical",
    "add_condition": "warn",
    "remove_condition": "info",
    "adjust_confidence": "info",
}

SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2}


def _now():
    return datetime.datetime.now().strftime("%d.%m.%Y %H:%M")


def _stamp():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _pct(part, total):
    return round(part / total * 100.0, 1) if total else 0.0


# --------------------------------------------------------------------------
# состояние рекомендаций
# --------------------------------------------------------------------------

def empty_state():
    return {
        "version": STATE_VERSION,
        "seen": {},
        "applied": {},
        "resolved": {},
        "dismissed": {},
        "last_run": "",
        "last_sports": [],
    }


def normalize_state(state):
    base = empty_state()
    if not isinstance(state, dict):
        return base
    for key in ("seen", "applied", "resolved", "dismissed"):
        value = state.get(key)
        if isinstance(value, dict):
            base[key] = value
    base["last_run"] = str(state.get("last_run") or "")
    sports = state.get("last_sports")
    if isinstance(sports, list):
        base["last_sports"] = [str(item) for item in sports][:12]
    return base


def load_state(path):
    try:
        if path:
            with open(path, "r", encoding="utf-8") as handle:
                return normalize_state(json.load(handle))
    except Exception:
        pass
    return empty_state()


def save_state(path, state):
    """Атомарно сохраняет состояние; ошибки не ломают экран анализа."""
    if not path:
        return False
    data = normalize_state(state)
    _prune(data)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        import os
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _prune(state):
    for key, limit in (("seen", MAX_SEEN), ("applied", MAX_APPLIED),
                       ("resolved", MAX_RESOLVED),
                       ("dismissed", MAX_DISMISSED)):
        items = state.get(key) or {}
        if len(items) <= limit:
            continue
        ordered = sorted(
            items.items(),
            key=lambda pair: str((pair[1] or {}).get("last_seen")
                                 or (pair[1] or {}).get("at") or ""),
            reverse=True)
        state[key] = dict(ordered[:limit])


# --------------------------------------------------------------------------
# условия правила
# --------------------------------------------------------------------------

def condition_key(condition):
    """Стабильный ключ условия — тот же состав полей, что в JS-мосте."""
    if not isinstance(condition, dict):
        return ""
    payload = [
        str(condition.get("metric") or ""),
        condition.get("args") or {},
        str(condition.get("op") or ""),
        condition.get("value"),
        condition.get("value2"),
        str(condition.get("value_metric") or ""),
        condition.get("value_args") or {},
    ]
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _flatten(group):
    """Все условия группы, включая вложенные."""
    result = []
    if not isinstance(group, dict):
        return result
    if "metric" in group:
        return [group]
    for item in group.get("conditions") or []:
        result.extend(_flatten(item))
    return result


def _contains(group, condition):
    key = condition_key(condition)
    return any(condition_key(item) == key for item in _flatten(group))


def _rule_group(rule):
    return auto_rules._rule_conditions(rule)


def _root_conditions(rule):
    return list(_rule_group(rule).get("conditions") or [])


def _sport_rules(rules_by_sport, sport):
    rules = (rules_by_sport or {}).get(sport)
    if rules is None:
        rules = (rules_by_sport or {}).get("") or []
    return [item for item in rules or [] if isinstance(item, dict)]


def _rule_name(rule, sport):
    name = str(rule.get("name") or "").strip()
    if name:
        return name
    action = str((rule.get("action") or {}).get("type") or "")
    return "%s · %s" % (sport_catalog.short_name(sport),
                        TYPE_TITLES.get(action, action or "правило"))


def _target_title(target, sport):
    if sport == "table_tennis" and str(target).startswith("set"):
        return "партия %s" % str(target).replace("set", "")
    return "матч"


# --------------------------------------------------------------------------
# оценка правила и условий
# --------------------------------------------------------------------------

def _evaluate_rule(rule, group, sport):
    action = rule.get("action") or {}
    is_skip = str(action.get("type") or "").lower() == "skip"
    kind, target = auto_rules._rule_market(rule, sport)
    condition_group = _rule_group(rule)
    conditions = condition_group.get("conditions") or []
    matched = auto_rules._matched_group(group, condition_group) \
        if conditions else list(group)
    total = len(matched)
    wins = sum(1 for item in matched if item.get("success"))
    losses = total - wins
    group_wins = sum(1 for item in group if item.get("success"))
    if is_skip:
        base = _pct(len(group) - group_wins, len(group))
        precision = _pct(losses, total)
    else:
        base = _pct(group_wins, len(group))
        precision = _pct(wins, total)
    return {
        "kind": kind,
        "target": target,
        "skip": is_skip,
        "action": action,
        "condition_group": condition_group,
        "conditions": conditions,
        "matched": total,
        "wins": wins,
        "losses": losses,
        "precision": precision,
        "base": base,
        "group_size": len(group),
        "confidence": _num(action.get("confidence"), 0.0),
    }


def _examples(observations, want_success, limit=2):
    result = []
    for item in observations or []:
        if bool(item.get("success")) is not want_success:
            continue
        result.append({
            "teams": "%s — %s" % (item.get("team1", ""),
                                  item.get("team2", "")),
            "verdict": item.get("verdict", ""),
            "score": item.get("score", ""),
            "total": item.get("total"),
            "sent_at": item.get("sent_at", ""),
        })
        if len(result) >= limit:
            break
    return result


def _analysis_rows(sport, group, min_group):
    """Один прогон анализатора на рынок/цель, а не на каждое правило."""
    try:
        payload = analyzer.analyze(
            None, observations=group, min_group=min_group, min_lift=5.0,
            min_hits=1, max_rows=10, with_pairs=False, with_means=False,
            sport=sport)
        return payload
    except Exception:
        return {"failure": [], "success": []}


def _candidate_pool(sport, group, min_group):
    """Кандидаты на добавление: удачные признаки и обратные неудачным."""
    payload = _analysis_rows(sport, group, min_group)
    candidates = []
    seen = set()

    def add(condition, source, row):
        if not isinstance(condition, dict):
            return
        key = condition_key(condition)
        if not key or key in seen:
            return
        seen.add(key)
        candidates.append({
            "condition": condition,
            "text": row.get("text") or ce.describe_condition(
                condition, sport=sport),
            "source": source,
            "lift": _num(row.get("lift")),
            "share": _num(row.get("win_share") if source == "success"
                         else row.get("loss_share")),
        })

    for row in (payload.get("success") or [])[:8]:
        add(row.get("condition"), "success", row)
    for row in (payload.get("failure") or [])[:8]:
        inverse = auto_rules._invert(row.get("condition"))
        if inverse:
            add(inverse, "failure", row)
    return candidates


def _simulate_add(group, base, condition, sport, min_samples,
                  min_precision, min_gain):
    condition_group = base["condition_group"]
    if str(condition_group.get("logic") or "and").lower() != "and":
        # Добавление в «ИЛИ» расширяет правило и почти всегда ухудшает
        # точность. Такие правки не предлагаем автоматически.
        return None
    if _contains(condition_group, condition):
        return None
    conditions = list(condition_group.get("conditions") or []) + [condition]
    next_group = {"logic": "and", "conditions": conditions}
    matched = auto_rules._matched_group(group, next_group)
    need = max(MIN_KEPT, int(min_samples or 6) // 2)
    if len(matched) < need:
        return None
    wins = sum(1 for item in matched if item.get("success"))
    precision = _pct(wins, len(matched))
    if precision < max(float(min_precision or 60.0), base["precision"] + min_gain):
        return None
    if precision < base["precision"] + min_gain:
        return None
    removed_wins = base["wins"] - wins
    removed_losses = base["losses"] - (len(matched) - wins)
    if removed_losses <= 0:
        return None
    score = (precision - base["precision"]) * min(
        1.0, len(matched) / max(1.0, int(min_samples or 6) * 2.0))
    score += min(3.0, removed_losses) * 0.6
    return {
        "group": next_group,
        "matched": len(matched),
        "wins": wins,
        "losses": len(matched) - wins,
        "precision": precision,
        "removed_wins": removed_wins,
        "removed_losses": removed_losses,
        "score": score,
        "examples": _examples(matched, True),
    }


def _simulate_remove(group, base, sport, min_precision):
    condition_group = base["condition_group"]
    conditions = list(condition_group.get("conditions") or [])
    if len(conditions) < 2 or str(condition_group.get("logic") or "and") != "and":
        return None
    best = None
    for index, condition in enumerate(conditions):
        rest = conditions[:index] + conditions[index + 1:]
        next_group = {"logic": "and", "conditions": rest}
        matched = auto_rules._matched_group(group, next_group)
        if len(matched) < base["matched"] + 2:
            continue
        wins = sum(1 for item in matched if item.get("success"))
        precision = _pct(wins, len(matched))
        if precision < max(float(min_precision) - 2.0,
                           base["precision"] - 5.0):
            continue
        score = (len(matched) - base["matched"]) * 0.2 + precision
        if best is None or score > best["score"]:
            best = {
                "group": next_group,
                "condition": condition,
                "matched": len(matched),
                "wins": wins,
                "losses": len(matched) - wins,
                "precision": precision,
                "score": score,
                "examples": _examples(matched, True),
            }
    return best


def _confidence_target(base):
    value = round(min(0.90, max(0.55, base["precision"] / 100.0)), 2)
    return value


# --------------------------------------------------------------------------
# одна рекомендация
# --------------------------------------------------------------------------

def _rec_id(sport, rule_id, rec_type, condition=None, extra=""):
    raw = "|".join([
        sport, str(rule_id or ""), rec_type,
        condition_key(condition) if condition else "", str(extra or ""),
    ])
    return "rec_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def _base_rec(sport, rule, rec_type, base, target_rule):
    return {
        "id": "",
        "sport": sport,
        "sport_name": sport_catalog.name(sport),
        "rule_id": str(rule.get("id") or ""),
        "rule_name": _rule_name(rule, sport),
        "rule_auto": bool(rule.get("auto")),
        "rule_enabled": bool(rule.get("enabled", True)),
        "rule_conditions": len(base["conditions"]),
        "rule_action": rule.get("action_text") or ce.describe_action(
            base["action"], sport),
        "rule_market": auto_rules.MARKET_TITLES.get(base["kind"], base["kind"]),
        "rule_target": _target_title(base["target"], sport),
        "type": rec_type,
        "type_title": TYPE_TITLES.get(rec_type, rec_type),
        "severity": SEVERITY.get(rec_type, "info"),
        "target_rule": target_rule,
        "precision_before": base["precision"],
        "matched_before": base["matched"],
        "base_precision": base["base"],
        "group_size": base["group_size"],
        "condition": None,
        "condition_text": "",
        "patch": None,
        "reason": "",
        "examples": [],
        "created_at": _stamp(),
        "updated_at": _stamp(),
        "is_new": False,
        "first_seen": "",
        "seen_count": 0,
    }


def _target_rule(rule, sport, base):
    return {
        "id": str(rule.get("id") or ""),
        "name": _rule_name(rule, sport),
        "sport": sport,
        "sport_name": sport_catalog.name(sport),
        "action_text": rule.get("action_text") or ce.describe_action(
            base["action"], sport),
        "conditions_text": rule.get("conditions_text") or ce.describe_group(
            base["condition_group"], sport=sport),
        "priority": int(rule.get("priority") or 100),
        "auto": bool(rule.get("auto")),
        "enabled": bool(rule.get("enabled", True)),
    }


def _recommend_for_rule(sport, rule, group, min_samples, min_precision,
                        pool):
    """Возвращает до двух рекомендаций для одного правила."""
    base = _evaluate_rule(rule, group, sport)
    if not base["kind"]:
        return []
    if base["matched"] < max(MIN_KEPT, int(min_samples or 6)):
        return []
    target_rule = _target_rule(rule, sport, base)
    result = []

    if base["skip"]:
        if base["precision"] < auto_rules.SKIP_LOSS_SHARE:
            rec = _base_rec(sport, rule, "disable_rule", base, target_rule)
            rec["id"] = _rec_id(sport, rule.get("id"), "disable_rule")
            rec["patch"] = {"enabled": False}
            rec["precision_after"] = base["precision"]
            rec["matched_after"] = base["matched"]
            rec["reason"] = (
                "Фильтр отсекает только %.0f%% неудач при пороге %.0f%%. "
                "Правило пропускает слишком много проблемных матчей." % (
                    base["precision"], auto_rules.SKIP_LOSS_SHARE))
            result.append(rec)
        return result

    if base["precision"] < min_precision:
        best = None
        for candidate in pool:
            if _contains(base["condition_group"], candidate["condition"]):
                continue
            sim = _simulate_add(group, base, candidate["condition"], sport,
                                min_samples, min_precision, MIN_GAIN)
            if not sim:
                continue
            if best is None or sim["score"] > best[0]["score"]:
                best = (sim, candidate)
        if best:
            sim, candidate = best
            rec = _base_rec(sport, rule, "add_condition", base, target_rule)
            rec["id"] = _rec_id(sport, rule.get("id"), "add_condition",
                                candidate["condition"])
            rec["condition"] = candidate["condition"]
            rec["condition_text"] = candidate["text"]
            rec["patch"] = {"conditions": sim["group"]}
            rec["precision_after"] = sim["precision"]
            rec["matched_after"] = sim["matched"]
            rec["wins_after"] = sim["wins"]
            rec["losses_after"] = sim["losses"]
            rec["removed_losses"] = sim["removed_losses"]
            rec["removed_wins"] = sim["removed_wins"]
            rec["lift_after"] = round(sim["precision"] - base["base"], 1)
            rec["coverage_after"] = _pct(sim["matched"], base["group_size"])
            rec["gain"] = round(sim["precision"] - base["precision"], 1)
            rec["examples"] = sim["examples"]
            source = "неудач" if candidate["source"] == "failure" else "удач"
            rec["reason"] = (
                "Условие «%s» отделяет %d неудачных срабатываний от %d. "
                "Точность правила вырастет с %.0f%% до %.0f%%; останется "
                "%d срабатываний." % (
                    candidate["text"], sim["removed_losses"],
                    sim["removed_wins"], base["precision"], sim["precision"],
                    sim["matched"]))
            rec["source"] = source
            result.append(rec)
        elif base["precision"] < 50.0 or base["precision"] + 5.0 < base["base"]:
            rec = _base_rec(sport, rule, "disable_rule", base, target_rule)
            rec["id"] = _rec_id(sport, rule.get("id"), "disable_rule")
            rec["patch"] = {"enabled": False}
            rec["precision_after"] = base["precision"]
            rec["matched_after"] = base["matched"]
            rec["reason"] = (
                "Точность %.0f%% ниже цели %.0f%% и средней по рынку %.0f%%. "
                "Условия, которое исправит правило без потери данных, "
                "не нашлось." % (base["precision"], min_precision, base["base"]))
            result.append(rec)
        else:
            rec = _base_rec(sport, rule, "disable_rule", base, target_rule)
            rec["id"] = _rec_id(sport, rule.get("id"), "disable_rule")
            rec["patch"] = {"enabled": False}
            rec["precision_after"] = base["precision"]
            rec["matched_after"] = base["matched"]
            rec["reason"] = (
                "Точность %.0f%% ниже цели %.0f%%. Правило лучше временно "
                "отключить и пересобрать, пока данные не подтвердят его." % (
                    base["precision"], min_precision))
            result.append(rec)
        return result

    # Правило уже проходит порог. Ищем переобучение: лишнее условие,
    # которое можно снять без потери точности.
    loose = _simulate_remove(group, base, sport, min_precision)
    if loose:
        rec = _base_rec(sport, rule, "remove_condition", base, target_rule)
        rec["id"] = _rec_id(sport, rule.get("id"), "remove_condition",
                            loose["condition"])
        rec["condition"] = loose["condition"]
        rec["condition_text"] = ce.describe_condition(
            loose["condition"], sport=sport)
        rec["patch"] = {"conditions": loose["group"]}
        rec["precision_after"] = loose["precision"]
        rec["matched_after"] = loose["matched"]
        rec["wins_after"] = loose["wins"]
        rec["losses_after"] = loose["losses"]
        rec["lift_after"] = round(loose["precision"] - base["base"], 1)
        rec["coverage_after"] = _pct(loose["matched"], base["group_size"])
        rec["gain"] = round(loose["precision"] - base["precision"], 1)
        rec["examples"] = loose["examples"]
        rec["reason"] = (
            "Условие «%s» можно снять: срабатываний станет %d вместо %d, "
            "а точность останется %.0f%%." % (
                rec["condition_text"], loose["matched"], base["matched"],
                loose["precision"]))
        result.append(rec)

    target_conf = _confidence_target(base)
    if abs(base["confidence"] * 100.0 - base["precision"]) >= 12.0:
        rec = _base_rec(sport, rule, "adjust_confidence", base, target_rule)
        rec["id"] = _rec_id(sport, rule.get("id"), "adjust_confidence")
        updated = json.loads(json.dumps(base["action"], ensure_ascii=False))
        updated["confidence"] = target_conf
        rec["patch"] = {"action": updated}
        rec["precision_after"] = base["precision"]
        rec["matched_after"] = base["matched"]
        rec["old_confidence"] = base["confidence"]
        rec["new_confidence"] = target_conf
        rec["reason"] = (
            "Фактическая точность %.0f%%, а в действии уверенность %.0f%%. "
            "Поставьте %.0f%% — прогноз станет честнее." % (
                base["precision"], base["confidence"] * 100.0,
                target_conf * 100.0))
        result.append(rec)

    return result


# --------------------------------------------------------------------------
# публичная точка входа
# --------------------------------------------------------------------------

def _rule_by_id(rules, rule_id):
    for rule in rules or []:
        if str(rule.get("id") or "") == str(rule_id or ""):
            return rule
    return None


def _is_resolved(rec, rule):
    """Правка уже применена (в том числе вручную)?"""
    if rule is None:
        return True, "Правило удалено"
    if rec["type"] == "add_condition":
        if _contains(rule.get("conditions"), rec.get("condition")):
            return True, "Условие уже есть в правиле"
        if not rule.get("enabled", True):
            return True, "Правило выключено"
    elif rec["type"] == "remove_condition":
        if not _contains(rule.get("conditions"), rec.get("condition")):
            return True, "Условие уже убрано"
    elif rec["type"] == "disable_rule":
        if not rule.get("enabled", True):
            return True, "Правило уже выключено"
    elif rec["type"] == "adjust_confidence":
        action = rule.get("action") or {}
        current = _num(action.get("confidence"))
        target = _num(((rec.get("patch") or {}).get("action") or {}).get(
            "confidence"), -1)
        if abs(current - target) <= 0.011:
            return True, "Уверенность уже исправлена"
    return False, ""


def _dismissed(state, rec_id, now):
    item = (state.get("dismissed") or {}).get(rec_id)
    if not item:
        return False
    until = str(item.get("until") or "")
    if not until:
        return True
    return until >= now


def recommend(sent_predictions, sports=None, rules_by_sport=None,
              observations_by_sport=None, min_samples=6, min_precision=60.0,
              state=None, max_items=MAX_RECOMMENDATIONS, mark_seen=True,
              active_sport=None):
    """Собирает рекомендации по включённым правилам выбранных видов.

    ``sent_predictions`` нужен только если ``observations_by_sport`` не
    передан: так экран анализа не разбирает историю дважды.
    """
    selected = normalize_sports(sports, active_sport)
    try:
        min_samples = max(3, min(50, int(min_samples or 6)))
    except Exception:
        min_samples = 6
    try:
        min_precision = max(50.0, min(95.0, float(min_precision or 60.0)))
    except Exception:
        min_precision = 60.0
    state = normalize_state(state)
    now_text = _now()
    now_iso = _stamp()
    all_recs = []
    resolved = []
    sports_report = []

    for sport in selected:
        observations = (observations_by_sport or {}).get(sport)
        if observations is None:
            try:
                observations = analyzer.build_observations(
                    sent_predictions, sport=sport)
            except Exception:
                observations = []
        groups = auto_rules._groups(observations, sport)
        rules = _sport_rules(rules_by_sport, sport)
        open_rules = [rule for rule in rules if rule.get("enabled", True)]
        sport_count = 0
        pools = {}
        for rule in open_rules:
            kind, target = auto_rules._rule_market(rule, sport)
            if not kind:
                continue
            group = groups.get((kind, target)) or []
            if len(group) < max(MIN_KEPT, min_samples):
                continue
            pool_key = (kind, target)
            if pool_key not in pools:
                pools[pool_key] = _candidate_pool(
                    sport, group, max(2, min(3, min_samples // 2)))
            for rec in _recommend_for_rule(
                    sport, rule, group, min_samples, min_precision,
                    pools[pool_key]):
                all_recs.append(rec)
                sport_count += 1
        sports_report.append({
            "sport": sport,
            "name": sport_catalog.name(sport),
            "short_name": sport_catalog.short_name(sport),
            "rules": len(open_rules),
            "recommendations": sport_count,
        })

    # Дедупликация: один и тот же идентификатор не должен появиться дважды.
    best = {}
    for rec in all_recs:
        current = best.get(rec["id"])
        if current is None or _num(rec.get("gain")) > _num(current.get("gain")):
            best[rec["id"]] = rec

    result = []
    seen = state.setdefault("seen", {})
    dismissed = state.setdefault("dismissed", {})
    for rec in best.values():
        sport = rec["sport"]
        rules = _sport_rules(rules_by_sport, sport)
        rule = _rule_by_id(rules, rec.get("rule_id"))
        done, reason = _is_resolved(rec, rule)
        if done:
            resolved.append({
                "id": rec["id"],
                "sport": sport,
                "rule_id": rec.get("rule_id"),
                "rule_name": rec.get("rule_name"),
                "type": rec.get("type"),
                "reason": reason,
                "resolved_at": now_iso,
            })
            state.setdefault("resolved", {})[rec["id"]] = {
                "at": now_iso, "reason": reason,
                "sport": sport, "rule_id": rec.get("rule_id"),
            }
            dismissed.pop(rec["id"], None)
            continue
        if _dismissed(state, rec["id"], now_iso):
            continue
        previous = seen.get(rec["id"]) or {}
        rec["is_new"] = not bool(previous)
        rec["first_seen"] = previous.get("first_seen") or now_iso
        rec["seen_count"] = int(previous.get("count") or 0)
        rec["updated_at"] = now_text
        result.append(rec)
        if mark_seen:
            seen[rec["id"]] = {
                "first_seen": rec["first_seen"],
                "last_seen": now_iso,
                "count": rec["seen_count"] + 1,
                "type": rec["type"],
                "sport": sport,
                "rule_id": rec.get("rule_id"),
            }

    result.sort(key=lambda item: (
        0 if item.get("is_new") else 1,
        SEVERITY_ORDER.get(item.get("severity"), 9),
        -_num(item.get("gain")),
        -_num(item.get("precision_after")),
        str(item.get("rule_name") or ""),
    ))
    open_ids = [item["id"] for item in result]
    result = result[:max_items]

    counts = {}
    for item in result:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    new_count = sum(1 for item in result if item.get("is_new"))
    state["last_run"] = now_text
    state["last_sports"] = selected
    _prune(state)

    hint = ""
    if not result:
        if resolved:
            hint = ("Все рекомендации закрыты: условия уже добавлены в "
                    "правила. Новые появятся по мере накопления результатов.")
        elif not any(item["rules"] for item in sports_report):
            hint = ("В выбранных видах нет включённых правил. Включите "
                    "правила в конструкторе — приложение начнёт следить за "
                    "ними и предлагать правки.")
        else:
            hint = ("Пока всё устойчиво: активные правила проходят проверку. "
                    "Рекомендации появятся, когда история покажет устойчивое "
                    "улучшение.")
    return {
        "ok": True,
        "recommendations": result,
        "resolved": resolved,
        "open_ids": open_ids,
        "counts": counts,
        "total": len(result),
        "new_count": new_count,
        "sports": sports_report,
        "sports_selected": selected,
        "hint": hint,
        "updated_at": now_text,
        "state": {
            "seen": len(seen),
            "applied": len(state.get("applied") or {}),
            "resolved": len(state.get("resolved") or {}),
            "dismissed": len(state.get("dismissed") or {}),
        },
        # Служебное поле: вызывающая сторона сохраняет его и убирает из
        # JSON-ответа клиенту (там достаточно сводки ``state``).
        "advisor_state": state,
    }


def normalize_sports(value, active_sport=None):
    """Приводит фильтр видов к списку без дублей в порядке каталога."""
    default = sport_catalog.normalize_sport(active_sport or "table_tennis")
    if value is None:
        return [default]
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return [default]
        if text in ("all", "*", "все"):
            return list(sport_catalog.SPORT_ORDER)
        if "," in text or " " in text:
            value = [part for part in text.replace(",", " ").split() if part]
        else:
            value = [text]
    if not isinstance(value, (list, tuple, set)):
        return [default]
    result = []
    for item in value:
        text = str(item or "").strip().lower()
        if not text or text in ("all", "*", "все"):
            return list(sport_catalog.SPORT_ORDER)
        if text == "active":
            text = default
        try:
            sport = sport_catalog.normalize_sport(text)
        except Exception:
            continue
        if sport in sport_catalog.SPORT_ORDER and sport not in result:
            result.append(sport)
    return result or [default]


def dismiss(state, rec_id, days=DISMISS_DAYS):
    state = normalize_state(state)
    until = (datetime.datetime.now() +
             datetime.timedelta(days=max(1, int(days or DISMISS_DAYS)))
             ).isoformat(timespec="seconds")
    state.setdefault("dismissed", {})[str(rec_id)] = {
        "at": _stamp(), "until": until,
    }
    return state


def mark_applied(state, rec, reason="Применено"):
    state = normalize_state(state)
    rec_id = str(rec.get("id") or "")
    if not rec_id:
        return state
    state.setdefault("applied", {})[rec_id] = {
        "at": _stamp(),
        "sport": rec.get("sport"),
        "rule_id": rec.get("rule_id"),
        "type": rec.get("type"),
        "reason": reason,
    }
    (state.get("dismissed") or {}).pop(rec_id, None)
    return state

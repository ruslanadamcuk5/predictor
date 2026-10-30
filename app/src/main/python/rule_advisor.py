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
import profit
import sports as sport_catalog

STATE_VERSION = 1
# Минимальный прирост точности, ради которого стоит менять правило (п.п.).
MIN_GAIN = 5.0
# Сколько срабатываний должно остаться после добавления условия.
MIN_KEPT = 3
# Сколько рекомендаций отдавать за один расчёт.
MAX_RECOMMENDATIONS = 20
# Минимальный прирост ROI (процентных пунктов), ради которого меняем правило.
MIN_ROI_GAIN = 2.0
# Нижняя граница EV, ниже которой правило считается убыточным.
STOP_EV_LOWER = -1.0
# Сколько правил держать в рабочем портфеле одновременно.
MAX_PORTFOLIO = 8
# Максимальная суммарная экспозиция портфеля, % банка.
PORTFOLIO_BUDGET_PCT = 10.0
# Сколько дней скрывать отклонённую рекомендацию.
DISMISS_DAYS = 7
# Ограничения на размер состояния, чтобы файл не рос бесконечно.
MAX_SEEN = 600
MAX_APPLIED = 300
MAX_RESOLVED = 300
MAX_DISMISSED = 300

TYPE_TITLES = {
    "add_condition": "Добавить условие",
    "add_odds_floor": "Поднять коэффициент",
    "remove_condition": "Убрать условие",
    "disable_rule": "Отключить правило",
    "adjust_confidence": "Поправить уверенность",
}

SEVERITY = {
    "disable_rule": "critical",
    "add_condition": "warn",
    "add_odds_floor": "critical",
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

def _money(observations):
    """Денежная статистика по наблюдениям (EV, ROI, просадка, Келли)."""
    return profit.summarize(profit.rows_for_observations(observations))


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
    money = _money(matched)
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
        "money": money,
        "matched_rows": matched,
        "validation": profit.validation(profit.rows_for_observations(matched))
        if not is_skip else {"ok": None},
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


def _value_mode(base, money):
    """Достаточно ли коэффициентов, чтобы судить о прибыли, а не точности."""
    return bool(money.get("odds_available") and money.get("value_ready")
                and (base.get("money") or {}).get("odds_available"))


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
    money = _money(matched)
    validation = profit.validation(profit.rows_for_observations(matched))
    removed_wins = base["wins"] - wins
    removed_losses = base["losses"] - (len(matched) - wins)
    base_money = base.get("money") or {}
    value_mode = _value_mode(base, money)
    if value_mode:
        base_roi = _num(base_money.get("roi"), 0.0)
        base_ev = _num(base_money.get("ev_lower"), -999.0)
        roi = _num(money.get("roi"), -999.0)
        ev_lower = _num(money.get("ev_lower"), -999.0)
        # Прибыль важнее точности: условие может убрать часть удачных
        # ставок, если оставшиеся дают заметно лучший ROI.
        if roi < max(0.5, base_roi + MIN_ROI_GAIN):
            return None
        if ev_lower <= max(0.0, base_ev):
            return None
        if validation.get("ok") is False:
            return None
        if removed_losses <= 0 and roi < base_roi + MIN_ROI_GAIN * 1.5:
            return None
        score = (roi - base_roi) * 1.4 + max(0.0, ev_lower) * 1.2
        score += min(3.0, max(0, removed_losses)) * 0.3
        score += min(4.0, len(matched) / max(1.0, min_samples or 6.0))
    else:
        if precision < max(float(min_precision or 60.0),
                           base["precision"] + min_gain):
            return None
        if precision < base["precision"] + min_gain:
            return None
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
        "money": money,
        "validation": validation,
        "value_mode": value_mode,
    }


def _simulate_odds_floor(group, base, sport):
    """Подбирает минимальный коэффициент, при котором правило прибыльно."""
    if base.get("skip"):
        return None
    matched = base.get("matched_rows") or []
    if not matched:
        return None
    base_money = base.get("money") or {}
    if not base_money.get("odds_available"):
        return None
    best = profit.best_odds_floor(matched, base_money, MIN_KEPT)
    if not best:
        return None
    first = next((item for item in matched
                  if profit.odds_for_observation(item) is not None), None)
    if first is None:
        return None
    prediction = dict(first.get("prediction") or {})
    action = base.get("action") or {}
    prediction["kind"] = base.get("kind") or prediction.get("kind")
    prediction["expected_side"] = (action.get("side") or
                                   prediction.get("expected_side"))
    condition = profit.odds_condition(prediction, best["floor"])
    if not condition:
        return None
    condition_group = base["condition_group"]
    if _contains(condition_group, condition):
        return None
    if str(condition_group.get("logic") or "and").lower() != "and":
        return None
    conditions = list(condition_group.get("conditions") or []) + [condition]
    next_group = {"logic": "and", "conditions": conditions}
    subset = auto_rules._matched_group(group, next_group)
    if len(subset) < max(MIN_KEPT, int(best["matched"])):
        return None
    money = _money(subset)
    validation = profit.validation(profit.rows_for_observations(subset))
    if validation.get("ok") is False:
        return None
    score = (money.get("roi") or 0.0) * 1.5 + max(
        0.0, _num(money.get("ev_lower"), 0.0)) * 1.2
    score += min(4.0, len(subset) / 6.0)
    return {
        "group": next_group,
        "condition": condition,
        "condition_text": profit.odds_condition_title(
            best["floor"], base.get("kind")),
        "floor": best["floor"],
        "matched": len(subset),
        "wins": sum(1 for item in subset if item.get("success")),
        "losses": sum(1 for item in subset if not item.get("success")),
        "precision": _pct(sum(1 for item in subset if item.get("success")),
                          len(subset)),
        "money": money,
        "validation": validation,
        "score": score,
        "examples": _examples(subset, True),
        "removed_wins": base["wins"] - sum(
            1 for item in subset if item.get("success")),
        "removed_losses": base["losses"] - sum(
            1 for item in subset if not item.get("success")),
        "value_mode": True,
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
        money = _money(matched)
        value_mode = _value_mode(base, money)
        if value_mode:
            base_money = base.get("money") or {}
            if _num(money.get("roi"), -999.0) < \
                    _num(base_money.get("roi"), 0.0) - 1.0:
                continue
            if _num(money.get("ev_lower"), -999.0) < \
                    _num(base_money.get("ev_lower"), 0.0) - 0.5:
                continue
            score = (len(matched) - base["matched"]) * 0.2
            score += _num(money.get("roi"), 0.0) * 0.5 + precision * 0.1
        else:
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
                "money": money,
                "validation": profit.validation(
                    profit.rows_for_observations(matched)),
                "value_mode": value_mode,
            }
    return best


def _rec_id(sport, rule_id, rec_type, condition=None, extra=""):
    raw = "|".join([
        sport, str(rule_id or ""), rec_type,
        condition_key(condition) if condition else "", str(extra or ""),
    ])
    return "rec_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def _base_rec(sport, rule, rec_type, base, target_rule):
    money = base.get("money") or {}
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
        "odds_before": money.get("avg_odds"),
        "roi_before": money.get("roi"),
        "ev_before": money.get("ev"),
        "ev_lower_before": money.get("ev_lower"),
        "profit_before": money.get("profit"),
        "drawdown_before": money.get("drawdown"),
        "odds_n_before": money.get("odds_n"),
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


def _portfolio_state(base):
    """Статус правила в денежном портфеле."""
    money = base.get("money") or {}
    if base.get("skip"):
        return "filter"
    if not money.get("odds_available"):
        return "no_odds"
    if not money.get("value_ready"):
        return "watch"
    validation = base.get("validation") or {}
    if validation.get("ok") is False:
        return "fragile"
    if money.get("profitable"):
        return "core"
    if _num(money.get("roi"), 0.0) > 0 and \
            _num(money.get("ev_lower"), -1.0) > STOP_EV_LOWER:
        return "watch"
    return "drop"


def _portfolio(entries, bankroll=profit.DEFAULT_BANKROLL,
               budget_pct=PORTFOLIO_BUDGET_PCT):
    """Рабочий портфель: какие правила ставить, сколькими и что ждать.

    Портфель — не список всех правил, а ставки, которые каппер реально
    делает: только правила с положительным EV на достаточной выборке и
    подтверждением на новых матчах. Суммарная экспозиция ограничена, чтобы
    серия поражений не уничтожила банк.
    """
    rows = []
    items = []
    for entry in entries or []:
        base = entry.get("base") or {}
        money = base.get("money") or {}
        status = _portfolio_state(base)
        item = {
            "sport": entry.get("sport"),
            "sport_name": sport_catalog.name(entry.get("sport")),
            "rule_id": str((entry.get("rule") or {}).get("id") or ""),
            "rule_name": _rule_name(entry.get("rule") or {},
                                    entry.get("sport")),
            "market": auto_rules.MARKET_TITLES.get(
                base.get("kind"), base.get("kind")),
            "target": _target_title(base.get("target"),
                                    entry.get("sport")),
            "status": status,
            "matched": int(base.get("matched") or 0),
            "precision": base.get("precision"),
            "odds_n": money.get("odds_n") or 0,
            "avg_odds": money.get("avg_odds"),
            "roi": money.get("roi"),
            "ev": money.get("ev"),
            "ev_lower": money.get("ev_lower"),
            "profit": money.get("profit"),
            "drawdown": money.get("drawdown"),
            "kelly": money.get("kelly"),
            "stake_pct": 0.0,
            "stake_amount": 0.0,
            "expected": 0.0,
            "validation_ok": (base.get("validation") or {}).get("ok"),
        }
        if status == "core":
            item["stake_pct"] = _num(money.get("stake_pct"), 0.0)
            rows.extend(base.get("matched_rows") or [])
        items.append(item)

    core = [item for item in items if item["status"] == "core"]
    core.sort(key=lambda item: (
        -_num(item.get("ev_lower"), 0.0) * 0.6 -
        _num(item.get("roi"), 0.0) * 0.4,
        -_num(item.get("matched"), 0)))
    core = core[:MAX_PORTFOLIO]
    total_raw = sum(_num(item.get("stake_pct"), 0.0) for item in core)
    scale = 1.0
    if total_raw > budget_pct and total_raw > 0:
        scale = budget_pct / total_raw
    for item in items:
        if item["status"] != "core":
            continue
        item["stake_pct"] = round(
            max(0.0, _num(item.get("stake_pct"), 0.0) * scale), 2)
        item["stake_amount"] = round(
            bankroll * item["stake_pct"] / 100.0, 2)
        item["expected"] = round(
            item["stake_amount"] * _num(item.get("ev"), 0.0) / 100.0, 2)
    # Отбрасываем правила за пределами лимита.
    allowed = {item["rule_id"] for item in core}
    for item in items:
        if item["status"] == "core" and item["rule_id"] not in allowed:
            item["status"] = "watch"
            item["stake_pct"] = 0.0
            item["stake_amount"] = 0.0
            item["expected"] = 0.0
    money = profit.summarize(rows, bankroll=bankroll)
    total_stake = sum(_num(item.get("stake_pct"), 0.0) for item in core)
    expected = sum(_num(item.get("expected"), 0.0) for item in core)
    active = [item for item in core if item.get("stake_pct")]
    counts = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    hint = ""
    if active:
        best = active[0]
        hint = ("Ставьте только правила со статусом «ядро»: %d шт., "
                "суммарно %.1f%% банка. Лучшее — «%s» (ROI %s%%, EV %s%%, "
                "ставка %.2f%%)." % (
                    len(active), total_stake, best["rule_name"],
                    _fmt_pct(best.get("roi")), _fmt_signed(best.get("ev")),
                    _num(best.get("stake_pct"), 0.0)))
    elif counts.get("no_odds"):
        hint = ("Для портфеля не хватает коэффициентов: истории без кэфов "
                "недостаточно, чтобы судить о прибыли. Включите сохранение "
                "коэффициентов и накопите результаты.")
    elif counts.get("watch"):
        hint = ("Правила ещё не доказали прибыль на дистанции: выборка "
                "мала или EV ниже нуля. Не увеличивайте ставки, пока "
                "статус не сменится на «ядро».")
    else:
        hint = ("Прибыльных правил пока нет. Это нормально: лучше не "
                "ставить, чем ставить с отрицательным EV.")
    return {
        "bankroll": bankroll,
        "budget_pct": budget_pct,
        "total_stake_pct": round(total_stake, 2),
        "total_stake_amount": round(bankroll * total_stake / 100.0, 2),
        "expected_per_bet": round(expected, 2),
        "expected_per_100": round(expected * 100.0, 2),
        "rules": items,
        "core": core,
        "counts": counts,
        "metrics": money,
        "hint": hint,
    }


def _confidence_target(base):
    """Честная уверенность: точность, подтянутая к базовой ставке рынка.

    На малой выборке сырая точность завышена. Сглаживание к средней по
    рынку не даёт правилу обещать 80%, имея 6 наблюдений.
    """
    n = max(1, int(base.get("matched") or 0))
    precision = _num(base.get("precision"), 50.0) / 100.0
    prior = _num(base.get("base"), 50.0) / 100.0
    weight = min(0.40, 4.0 / (n + 4.0))
    calibrated = precision * (1.0 - weight) + prior * weight
    return round(min(0.90, max(0.55, calibrated)), 2)


def _sim_summary(sim):
    money = sim.get("money") or {}
    validation = sim.get("validation") or {}
    return {
        "roi_after": money.get("roi"),
        "ev_after": money.get("ev"),
        "ev_lower_after": money.get("ev_lower"),
        "avg_odds_after": money.get("avg_odds"),
        "profit_after": money.get("profit"),
        "drawdown_after": money.get("drawdown"),
        "odds_n_after": money.get("odds_n"),
        "stake_pct_after": money.get("stake_pct"),
        "validation_after": validation.get("holdout") or {},
        "validation_ok": validation.get("ok"),
    }


def _apply_sim(rec, sim, base):
    rec["precision_after"] = sim["precision"]
    rec["matched_after"] = sim["matched"]
    rec["wins_after"] = sim.get("wins")
    rec["losses_after"] = sim.get("losses")
    rec["removed_losses"] = sim.get("removed_losses")
    rec["removed_wins"] = sim.get("removed_wins")
    rec["lift_after"] = round(sim["precision"] - base["base"], 1)
    rec["coverage_after"] = _pct(sim["matched"], base["group_size"])
    rec["gain"] = round(sim["precision"] - base["precision"], 1)
    rec["examples"] = sim.get("examples") or []
    rec["value_score"] = round(_num(sim.get("score"), 0.0), 2)
    update = _sim_summary(sim)
    rec.update(update)
    before_money = base.get("money") or {}
    if update.get("roi_after") is not None and \
            before_money.get("roi") is not None:
        rec["roi_gain"] = round(update["roi_after"] -
                                before_money["roi"], 1)
    if update.get("profit_after") is not None:
        rec["profit_gain"] = round(
            _num(update["profit_after"], 0.0) -
            _num(before_money.get("profit"), 0.0), 2)
    return rec


def _value_reason(base, sim, candidate_text, prefix=""):
    before = base.get("money") or {}
    after = sim.get("money") or {}
    parts = []
    if candidate_text:
        parts.append("Условие «%s»" % candidate_text)
    if after.get("odds_available") and after.get("roi") is not None:
        parts.append(
            "ROI %s%% → %s%% при среднем коэффициенте %s" % (
                _fmt_pct(before.get("roi")), _fmt_pct(after.get("roi")),
                after.get("avg_odds")))
        parts.append("EV %s%% → %s%%" % (
            _fmt_signed(before.get("ev")), _fmt_signed(after.get("ev"))))
        parts.append("останется %d ставок, просадка %s ед." % (
            sim.get("matched"), _fmt_num(after.get("drawdown"))))
        hold = (sim.get("validation") or {}).get("holdout") or {}
        if hold.get("odds_available"):
            parts.append("на новых матчах ROI %s%% (n=%d)" % (
                _fmt_pct(hold.get("roi")), hold.get("staked") or 0))
    else:
        parts.append(
            "точность %s%% → %s%%, останется %d срабатываний" % (
                _fmt_pct(base.get("precision")),
                _fmt_pct(sim.get("precision")), sim.get("matched")))
    parts.append("убрано неудач: %d, удач: %d" % (
        _num(sim.get("removed_losses"), 0), _num(sim.get("removed_wins"), 0)))
    if prefix:
        parts.insert(0, prefix)
    return ". ".join(parts) + "."


def _fmt_pct(value):
    return "—" if value is None else ("%.1f" % _num(value))


def _fmt_signed(value):
    if value is None:
        return "—"
    number = _num(value)
    return ("%+.1f" % number)


def _fmt_num(value):
    return "—" if value is None else ("%.1f" % _num(value))


def _recommend_for_rule(sport, rule, group, min_samples, min_precision,
                        pool, base=None):
    """Возвращает до двух рекомендаций для одного правила."""
    if base is None:
        base = _evaluate_rule(rule, group, sport)
    if not base["kind"]:
        return []
    if base["matched"] < max(MIN_KEPT, int(min_samples or 6)):
        return []
    target_rule = _target_rule(rule, sport, base)
    result = []
    money = base.get("money") or {}
    value_ready = bool(money.get("odds_available")
                       and money.get("value_ready"))
    value_bad = bool(value_ready and (
        _num(money.get("ev_lower"), 0.0) < STOP_EV_LOWER or
        _num(money.get("roi"), 0.0) < -2.0))

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

    if base["precision"] < min_precision or value_bad:
        best = None
        for candidate in pool:
            if _contains(base["condition_group"], candidate["condition"]):
                continue
            sim = _simulate_add(group, base, candidate["condition"], sport,
                                min_samples, min_precision, MIN_GAIN)
            if not sim:
                continue
            if best is None or sim["score"] > best[0]["score"]:
                best = (sim, candidate, "condition")
        floor = _simulate_odds_floor(group, base, sport)
        if floor and (best is None or floor["score"] > best[0]["score"]):
            best = (floor, None, "odds")
        if best:
            sim, candidate, kind = best
            if kind == "odds":
                rec = _base_rec(sport, rule, "add_odds_floor", base,
                                target_rule)
                rec["id"] = _rec_id(sport, rule.get("id"), "add_odds_floor",
                                    sim["condition"])
                rec["condition"] = sim["condition"]
                rec["condition_text"] = sim["condition_text"]
                rec["patch"] = {"conditions": sim["group"]}
                rec["floor"] = sim.get("floor")
                rec["reason"] = _value_reason(
                    base, sim, sim.get("condition_text"),
                    "Низкие коэффициенты не покрывают риск")
            else:
                rec = _base_rec(sport, rule, "add_condition", base,
                                target_rule)
                rec["id"] = _rec_id(sport, rule.get("id"), "add_condition",
                                    candidate["condition"])
                rec["condition"] = candidate["condition"]
                rec["condition_text"] = candidate["text"]
                rec["patch"] = {"conditions": sim["group"]}
                source = ("неудач" if candidate["source"] == "failure"
                          else "удач")
                rec["source"] = source
                rec["reason"] = _value_reason(base, sim, candidate["text"])
            _apply_sim(rec, sim, base)
            result.append(rec)
        else:
            rec = _base_rec(sport, rule, "disable_rule", base, target_rule)
            rec["id"] = _rec_id(sport, rule.get("id"), "disable_rule")
            rec["patch"] = {"enabled": False}
            rec["precision_after"] = base["precision"]
            rec["matched_after"] = base["matched"]
            if value_bad:
                rec["reason"] = (
                    "Правило убыточно: ROI %s%%, EV %s%%, средний "
                    "коэффициент %s. Условия, которое выводит его в плюс "
                    "без потери данных, не нашлось — отключите его." % (
                        _fmt_pct(money.get("roi")),
                        _fmt_signed(money.get("ev")),
                        _fmt_num(money.get("avg_odds"))))
            elif base["precision"] < 50.0 or \
                    base["precision"] + 5.0 < base["base"]:
                rec["reason"] = (
                    "Точность %.0f%% ниже цели %.0f%% и средней по рынку "
                    "%.0f%%. Условия, которое исправит правило без потери "
                    "данных, не нашлось." % (
                        base["precision"], min_precision, base["base"]))
            else:
                rec["reason"] = (
                    "Точность %.0f%% ниже цели %.0f%%. Правило лучше "
                    "временно отключить и пересобрать, пока данные не "
                    "подтвердят его." % (base["precision"], min_precision))
            result.append(rec)
        return result

    # Правило уже проходит порог. Ищем переобучение: лишнее условие,
    # которое можно снять без потери точности и прибыли.
    loose = _simulate_remove(group, base, sport, min_precision)
    if loose:
        rec = _base_rec(sport, rule, "remove_condition", base, target_rule)
        rec["id"] = _rec_id(sport, rule.get("id"), "remove_condition",
                            loose["condition"])
        rec["condition"] = loose["condition"]
        rec["condition_text"] = ce.describe_condition(
            loose["condition"], sport=sport)
        rec["patch"] = {"conditions": loose["group"]}
        _apply_sim(rec, loose, base)
        if loose.get("value_mode"):
            rec["reason"] = (
                "Условие «%s» можно снять: ставок станет %d вместо %d, "
                "ROI %s%%, EV %s%% — прибыль не падает, а выборка растёт." % (
                    rec["condition_text"], loose["matched"],
                    base["matched"], _fmt_pct(rec.get("roi_after")),
                    _fmt_signed(rec.get("ev_after"))))
        else:
            rec["reason"] = (
                "Условие «%s» можно снять: срабатываний станет %d вместо "
                "%d, а точность останется %.0f%%." % (
                    rec["condition_text"], loose["matched"],
                    base["matched"], loose["precision"]))
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
            "Фактическая точность %.0f%% на %d срабатываниях, а в действии "
            "уверенность %.0f%%. Поставьте %.0f%% — прогноз станет честнее, "
            "а размер ставки не будет завышен." % (
                base["precision"], base["matched"],
                base["confidence"] * 100.0, target_conf * 100.0))
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
    if rec["type"] in ("add_condition", "add_odds_floor"):
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
    portfolio_entries = []

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
            base = _evaluate_rule(rule, group, sport) if group else None
            if base:
                portfolio_entries.append({
                    "sport": sport, "rule": rule, "base": base,
                })
            if len(group) < max(MIN_KEPT, min_samples):
                continue
            pool_key = (kind, target)
            if pool_key not in pools:
                pools[pool_key] = _candidate_pool(
                    sport, group, max(2, min(3, min_samples // 2)))
            for rec in _recommend_for_rule(
                    sport, rule, group, min_samples, min_precision,
                    pools[pool_key], base=base):
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

    # Рекомендация была на экране и больше не воспроизводится: значит, её
    # правку применили (в приложении или вручную) либо данные изменились.
    # Закрываем её явно, чтобы интерфейс показал жизненный цикл, а не тихое
    # исчезновение. Если такая рекомендация появится снова, она будет новой.
    current_ids = set(best.keys())
    for rec_id, item in list(seen.items()):
        if rec_id in current_ids:
            continue
        sport = str((item or {}).get("sport") or "")
        if sport not in selected:
            continue
        rule_id = (item or {}).get("rule_id")
        rule = _rule_by_id(_sport_rules(rules_by_sport, sport), rule_id)
        reason = "Рекомендация больше не актуальна"
        resolved.append({
            "id": rec_id,
            "sport": sport,
            "rule_id": rule_id,
            "rule_name": _rule_name(rule, sport) if rule else "",
            "type": (item or {}).get("type"),
            "reason": reason,
            "resolved_at": now_iso,
        })
        state.setdefault("resolved", {})[rec_id] = {
            "at": now_iso, "reason": reason,
            "sport": sport, "rule_id": rule_id,
        }
        seen.pop(rec_id, None)

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

    portfolio = _portfolio(portfolio_entries)

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
        "portfolio": portfolio,
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

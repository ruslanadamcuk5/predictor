# -*- coding: utf-8 -*-
"""Сборка экрана анализа: несколько видов спорта + рекомендации по правилам.

Модуль не зависит от Android и файловой системы. Один и тот же расчёт
используют:

* ``engine_api`` — когда приложение работает локально;
* онлайн-сервис — когда включён режим «Использовать онлайн».

Поэтому офлайн и онлайн показывают одинаковые цифры при одинаковой истории.
"""

from __future__ import annotations

import analyzer
import auto_rules
import profit
import rule_advisor
import sports as sport_catalog

MAX_COMBINED_ROWS = 80
MAX_COMBINED_COMBOS = 18
MAX_COMBINED_MEANS = 24


def parse_options(payload, active_sport=None):
    """Нормализует фильтры экрана анализа."""
    data = payload if isinstance(payload, dict) else {}
    kind = str(data.get("kind") or "all").lower()
    if kind not in ("all", "winner", "total", "handicap", "btts"):
        kind = "all"
    target = str(data.get("target") or "").strip()
    raw_sports = data.get("sports")
    if raw_sports is None:
        raw_sports = data.get("sport")
    selected = rule_advisor.normalize_sports(raw_sports, active_sport)
    try:
        min_group = max(2, min(20, int(data.get("min_group") or
                                       analyzer.MIN_GROUP)))
    except Exception:
        min_group = analyzer.MIN_GROUP
    try:
        min_lift = max(0.0, min(100.0, float(data.get("min_lift")
                                             or analyzer.MIN_LIFT)))
    except Exception:
        min_lift = analyzer.MIN_LIFT
    try:
        min_hits = max(1, int(data.get("min_hits") or analyzer.MIN_HITS))
    except Exception:
        min_hits = analyzer.MIN_HITS
    try:
        limit = max(0, int(data.get("limit") or 0))
    except Exception:
        limit = 0
    return {
        "kind": kind,
        "target": target,
        "sports": selected,
        "min_group": min_group,
        "min_lift": min_lift,
        "min_hits": min_hits,
        "limit": limit,
        "pairs": bool(data.get("pairs", True)),
    }


def count_samples_for_sport(sent_predictions, sport):
    total = 0
    for data in (sent_predictions or {}).values():
        if not isinstance(data, dict):
            continue
        ctx = analyzer.context_from_sample(data.get("stats"))
        if ctx is not None and getattr(ctx, "sport", "") == sport:
            total += 1
    return total


def _tag_rows(rows, sport):
    name = sport_catalog.name(sport)
    short = sport_catalog.short_name(sport)
    for row in rows or []:
        if isinstance(row, dict):
            row["sport"] = sport
            row["sport_name"] = name
            row["sport_short"] = short
    return rows or []


def _tag_combos(combos, sport):
    for row in combos or []:
        row["sport"] = sport
        row["sport_name"] = sport_catalog.name(sport)
        row["sport_short"] = sport_catalog.short_name(sport)
    return combos or []


def _row_score(row, group):
    key = "failure_score" if group == "failure" else "success_score"
    try:
        return float(row.get(key) or 0.0)
    except Exception:
        return 0.0


def _combine(rows_by_sport, group, limit):
    combined = []
    for rows in (rows_by_sport or {}).values():
        combined.extend(rows or [])
    combined.sort(key=lambda row: (-_row_score(row, group),
                                   -float(row.get("coverage") or 0)))
    return combined[:limit]


def _combine_combos(combos_by_sport, group, limit):
    combined = []
    for rows in combos_by_sport.get(group) or []:
        combined.extend(rows)
    combined.sort(key=lambda row: (-float(row.get("score") or 0),
                                   -float(row.get("lift") or 0)))
    return combined[:limit]


def _combine_means(means_by_sport, limit):
    combined = [row for row in (means_by_sport or [])
                if isinstance(row, dict)]
    combined.sort(key=lambda row: -float(row.get("normalized") or 0))
    return combined[:limit]


def _merge_reviews(reviews_by_sport, selected):
    merged = []
    totals = {"total": 0, "active": 0, "disabled": 0}
    counts = {}
    hints = []
    sports_report = []
    for sport in selected:
        info = reviews_by_sport.get(sport) or {}
        sport_reviews = info.get("reviews") or []
        for item in sport_reviews:
            if isinstance(item, dict):
                item["sport"] = sport
                item["sport_name"] = sport_catalog.name(sport)
                item["sport_short"] = sport_catalog.short_name(sport)
        merged.extend(sport_reviews)
        totals["total"] += int(info.get("total") or 0)
        totals["active"] += int(info.get("active") or 0)
        totals["disabled"] += int(info.get("disabled") or 0)
        for verdict, value in (info.get("counts") or {}).items():
            counts[verdict] = counts.get(verdict, 0) + int(value or 0)
        if info.get("hint"):
            hints.append("%s: %s" % (sport_catalog.short_name(sport),
                                     info["hint"]))
        sports_report.append({
            "sport": sport,
            "name": sport_catalog.name(sport),
            "total": int(info.get("total") or 0),
            "active": int(info.get("active") or 0),
            "disabled": int(info.get("disabled") or 0),
            "counts": info.get("counts") or {},
        })
    order = {"disable": 0, "tighten": 1, "loosen": 2, "confidence": 3,
             "collect": 4, "no_data": 5, "keep": 6}
    merged.sort(key=lambda item: (order.get(item.get("verdict"), 9),
                                  -float(item.get("matched") or 0)))
    hint = ""
    if not merged:
        hint = ("Нет включённых правил для проверки в выбранных видах. "
                "Включите правила в конструкторе.")
    elif not any(item.get("verdict") in ("disable", "tighten", "loosen",
                                        "confidence") for item in merged):
        hint = ("Активные правила выглядят устойчиво: правок не требуется. "
                "Проверка обновится по мере накопления результатов.")
    elif len(selected) > 1:
        hint = "Проверено видов: %d. Ниже — все замечания по правилам." % \
            len(selected)
    return {
        "ok": all((reviews_by_sport.get(sport) or {}).get("ok", True)
                  for sport in selected),
        "sport": selected[0] if len(selected) == 1 else "",
        "sports_selected": selected,
        "sports": sports_report,
        "reviews": merged,
        "total": totals["total"],
        "active": totals["active"],
        "disabled": totals["disabled"],
        "counts": counts,
        "hint": hint,
        "updated_at": (next((reviews_by_sport.get(sport) or {}).get(
            "updated_at") for sport in selected
            if (reviews_by_sport.get(sport) or {}).get("updated_at")), ""),
    }


def _sport_hint(payload, name):
    if payload.get("hint"):
        return "%s: %s" % (name, payload["hint"])
    obs = payload.get("observations") or {}
    return "%s: наблюдений %d." % (name, int(obs.get("total") or 0))


def build_report(sent_predictions, payload=None, rules_by_sport=None,
                 auto_cfg=None, advisor_state=None, active_sport=None):
    """Полный отчёт экрана «Анализ» по выбранным видам спорта.

    Возвращает ``{"payload": {...}, "advisor_state": {...}}``. Второй элемент
    нужно сохранить вызывающей стороне (на телефоне — в приватный JSON).
    """
    options = parse_options(payload or {}, active_sport)
    selected = options["sports"]
    cfg = dict(auto_cfg or {})
    try:
        review_min_samples = max(3, min(50, int(cfg.get("min_samples") or 6)))
    except Exception:
        review_min_samples = 6
    try:
        review_min_precision = max(50.0, min(95.0, float(
            cfg.get("min_precision") or 60.0)))
    except Exception:
        review_min_precision = 60.0

    failures = {}
    successes = {}
    combos = {"failure": [], "success": []}
    means = []
    sport_payloads = []
    observations_by_sport = {}
    reviews_by_sport = {}
    totals = {"total": 0, "wins": 0, "losses": 0, "with_stats": 0}
    money_rows = []
    insufficient = []
    no_data = []

    for sport in selected:
        name = sport_catalog.name(sport)
        try:
            all_observations = analyzer.build_observations(
                sent_predictions, sport=sport)
        except Exception as exc:
            all_observations = []
            no_data.append("%s: ошибка разбора истории (%s)" %
                           (name, exc))
        observations_by_sport[sport] = all_observations
        money_rows.extend(profit.rows_for_observations(all_observations))

        filtered = []
        for item in all_observations:
            if options["kind"] != "all" and \
                    item.get("kind") != options["kind"]:
                continue
            if options["target"] and item.get("target") != options["target"]:
                continue
            filtered.append(item)
        if options["limit"] and len(filtered) > options["limit"]:
            filtered = filtered[:options["limit"]]

        try:
            result = analyzer.analyze(
                sent_predictions, kind=options["kind"],
                target=options["target"], min_group=options["min_group"],
                min_lift=options["min_lift"], min_hits=options["min_hits"],
                limit=options["limit"], with_pairs=options["pairs"],
                sport=sport, observations=filtered)
        except Exception as exc:
            result = {
                "ok": False, "error": str(exc), "failure": [], "success": [],
                "combos": {"failure": [], "success": []}, "means": [],
                "observations": {"total": 0, "wins": 0, "losses": 0,
                                 "with_stats": 0},
                "hint": "Не удалось разобрать историю: %s" % exc,
            }
        obs = result.get("observations") or {}
        # count_samples считает всю историю, а экран — выбранный вид.
        obs["with_stats"] = count_samples_for_sport(sent_predictions, sport)
        result["observations"] = obs
        result["sport"] = sport
        result["sport_name"] = name
        result["sport_short"] = sport_catalog.short_name(sport)
        result["sports_selected"] = selected

        _tag_rows(result.get("failure"), sport)
        _tag_rows(result.get("success"), sport)
        _tag_combos((result.get("combos") or {}).get("failure"), sport)
        _tag_combos((result.get("combos") or {}).get("success"), sport)
        _tag_rows(result.get("means"), sport)

        failures[sport] = result.get("failure") or []
        successes[sport] = result.get("success") or []
        combos["failure"].append((result.get("combos") or {}).get("failure") or [])
        combos["success"].append((result.get("combos") or {}).get("success") or [])
        means.extend(result.get("means") or [])

        total = int(obs.get("total") or 0)
        wins = int(obs.get("wins") or 0)
        losses = int(obs.get("losses") or 0)
        totals["total"] += total
        totals["wins"] += wins
        totals["losses"] += losses
        totals["with_stats"] += int(obs.get("with_stats") or 0)
        if not all_observations:
            no_data.append("%s: нет прогнозов с результатом и статистикой." %
                           name)
        elif total == 0:
            no_data.append("%s: под фильтр не попал ни один прогноз." % name)
        elif not result.get("sufficient"):
            insufficient.append(
                "%s: %d удач и %d неудач (нужно по %d)." % (
                    name, wins, losses, options["min_group"]))
        sport_payloads.append(result)

        # Проверка включённых правил — один раз на вид, с уже разобранной
        # историей. Так мы не строим наблюдения повторно.
        rules = (rules_by_sport or {}).get(sport) or []
        try:
            reviews_by_sport[sport] = auto_rules.review_rules(
                sent_predictions, sport, rules,
                observations=all_observations,
                min_samples=review_min_samples,
                min_precision=review_min_precision)
        except Exception as exc:
            reviews_by_sport[sport] = {
                "ok": False, "error": str(exc), "sport": sport,
                "reviews": [], "total": 0, "active": 0, "disabled": 0,
                "counts": {}, "hint": "Не удалось проверить правила.",
            }

    combined_failure = _combine(failures, "failure", MAX_COMBINED_ROWS)
    combined_success = _combine(successes, "success", MAX_COMBINED_ROWS)
    combined_combos = {
        "failure": _combine_combos(combos, "failure", MAX_COMBINED_COMBOS),
        "success": _combine_combos(combos, "success", MAX_COMBINED_COMBOS),
    }
    combined_means = _combine_means(means, MAX_COMBINED_MEANS)

    try:
        advice = rule_advisor.recommend(
            sent_predictions, sports=selected, rules_by_sport=rules_by_sport,
            observations_by_sport=observations_by_sport,
            min_samples=review_min_samples,
            min_precision=review_min_precision,
            state=advisor_state, active_sport=active_sport)
    except Exception as exc:
        advice = {
            "ok": False, "error": str(exc), "recommendations": [],
            "resolved": [], "counts": {}, "total": 0, "new_count": 0,
            "sports": [], "sports_selected": selected,
            "hint": "Не удалось собрать рекомендации: %s" % exc,
            "state": {},
        }
    new_state = advice.pop("advisor_state", None)
    if new_state is None:
        # rule_advisor.recommend меняет переданное состояние на месте.
        new_state = advisor_state

    hint_parts = []
    if no_data and len(no_data) == len(selected):
        hint_parts.append("Пока нет данных: " + " ".join(no_data))
    else:
        if no_data:
            hint_parts.append("Нет данных — " + " ".join(no_data))
        if insufficient:
            hint_parts.append("Мало данных — " + " ".join(insufficient))
    if len(selected) > 1:
        hint_parts.append("Выбрано видов: %d." % len(selected))
    hint = " ".join(hint_parts)

    sufficient = any(bool(item.get("sufficient")) for item in sport_payloads)
    generated_at = ""
    for item in sport_payloads:
        if item.get("generated_at"):
            generated_at = item["generated_at"]
            break

    money = profit.summarize(money_rows)
    combined = {
        "ok": True,
        "money": money,
        "options": {
            "kind": options["kind"],
            "target": options["target"],
            "min_group": options["min_group"],
            "min_lift": options["min_lift"],
            "min_hits": options["min_hits"],
            # sport оставлен для старых клиентов; для нескольких видов пуст.
            "sport": selected[0] if len(selected) == 1 else "",
            "sports": selected,
        },
        "observations": totals,
        "min_group": options["min_group"],
        "sufficient": sufficient,
        "generated_at": generated_at,
        "failure": combined_failure,
        "success": combined_success,
        "combos": combined_combos,
        "means": combined_means,
        "sports": sport_payloads,
        "sports_selected": selected,
        "hint": hint,
    }

    # Совместимость со старым экраном: если вид один, его поля лежат сверху.
    if len(selected) == 1:
        only = sport_payloads[0] if sport_payloads else {}
        combined["sport_name"] = only.get("sport_name") or \
            sport_catalog.name(selected[0])
        if not combined["hint"]:
            combined["hint"] = only.get("hint") or ""
    else:
        combined["sport_name"] = ", ".join(
            sport_catalog.short_name(sport) for sport in selected)

    combined["rule_reviews"] = _merge_reviews(reviews_by_sport, selected)
    combined["recommendations"] = advice
    combined["portfolio"] = advice.get("portfolio") or {}
    combined["auto_rules"] = {
        "enabled": bool(cfg.get("enabled")),
        "min_precision": review_min_precision,
        "min_samples": review_min_samples,
    }
    return {"payload": combined, "advisor_state": new_state}


def _sport_hints(payloads):
    return [_sport_hint(item, item.get("sport_name") or item.get("sport") or "")
            for item in payloads]

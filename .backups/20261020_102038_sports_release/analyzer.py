# -*- coding: utf-8 -*-
"""Анализатор прогнозов.

Сопоставляет сохранённую статистику матчей (снимок статистики делается в
момент отправки прогноза) с результатами партий и находит параметры,
характерные для **неудачных** и отдельно для **успешных** прогнозов.

Результат — список готовых условий с числами «в неудачах X%, в удачах Y%»,
которые можно в один тап перенести в конструктор правил.

Модуль не зависит от predictor_core: на вход получает уже разобранные
статистики и словарь отправленных прогнозов.
"""

import datetime
import json

import constructor_engine as ce

# Порог «достаточно данных»: минимум наблюдений в каждой группе.
MIN_GROUP = 3
# Минимум срабатываний условия внутри группы.
MIN_HITS = 2
# Минимальный перевес между группами (процентные пункты).
MIN_LIFT = 10.0
# Сколько условий отдавать в интерфейс.
MAX_ROWS = 40
# Сколько примеров-матчей прикладывать к условию.
MAX_EXAMPLES = 2

DATETIME_MARK = "__dt__"

STRING_METRICS_SKIP = ("string",)


# --------------------------------------------------------------------------
# JSON-безопасный снимок контекста
# --------------------------------------------------------------------------

def json_safe(value):
    """Превращает значение в JSON-совместимое (datetime → маркер)."""
    if isinstance(value, datetime.datetime):
        return {DATETIME_MARK: value.isoformat()}
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def json_restore(value):
    """Обратная операция к json_safe."""
    if isinstance(value, dict):
        if DATETIME_MARK in value and len(value) == 1:
            try:
                return datetime.datetime.fromisoformat(value[DATETIME_MARK])
            except Exception:
                return None
        return {key: json_restore(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_restore(item) for item in value]
    return value


def make_sample(match, stats):
    """Снимок статистики матча для последующего анализа.

    Сохраняется вместе с прогнозом, поэтому обязан быть JSON-совместимым
    и компактным (нормализованные очные встречи и форма, тоталы страницы).
    """
    try:
        ctx = ce.Context(match, stats)
        snapshot = {
            "v": 1,
            "kind": "context",
            "sport": ce.sport_catalog.normalize_sport(
                (match or {}).get("sport") or (stats or {}).get("sport") or
                "table_tennis"),
            "match": match or {},
            "h2h": ctx.h2h,
            "recent": ctx.recent,
            "page_total": (stats or {}).get("page_total") or {},
        }
        return json_safe(snapshot)
    except Exception:
        return None


def context_from_sample(sample):
    """Восстанавливает Context из снимка (или None, если снимка нет)."""
    if not isinstance(sample, dict) or sample.get("kind") != "context":
        return None
    try:
        data = json_restore(sample)
        ctx = ce.Context.__new__(ce.Context)
        ctx.match = data.get("match") or {}
        ctx.stats = {
            "sport": data.get("sport") or "table_tennis",
            "page_total": data.get("page_total") or {},
            "h2h_matches": [],
            "recent": {},
        }
        ctx.sport = ce.sport_catalog.normalize_sport(
            ctx.match.get("sport") or data.get("sport") or "table_tennis")
        ctx.h2h = list(data.get("h2h") or [])
        recent = data.get("recent") or {}
        ctx.recent = {
            "p1": list(recent.get("p1") or []),
            "p2": list(recent.get("p2") or []),
        }
        ctx._cache = {}
        return ctx
    except Exception:
        return None


# --------------------------------------------------------------------------
# наблюдения (один прогноз = одно наблюдение)
# --------------------------------------------------------------------------

def _find_result(results, prediction):
    for result in results or []:
        if result.get("target") != prediction.get("target"):
            continue
        if result.get("kind") and prediction.get("kind") and \
                result.get("kind") != prediction.get("kind"):
            continue
        return result
    return None


def build_observations(sent_predictions, kind="all", target="", limit=0,
                       sport=None):
    """Список наблюдений: прогноз с известным результатом и статистикой."""
    sport = ce.sport_catalog.normalize_sport(sport) if sport else ""
    observations = []
    for pred_id, data in (sent_predictions or {}).items():
        if not isinstance(data, dict):
            continue
        ctx = context_from_sample(data.get("stats"))
        if ctx is None:
            continue
        if sport and getattr(ctx, "sport", "table_tennis") != sport:
            continue
        results = data.get("set_results") or []
        for prediction in data.get("predictions") or []:
            if kind and kind != "all" and prediction.get("kind") != kind:
                continue
            if target and prediction.get("target") != target:
                continue
            result = _find_result(results, prediction)
            if not result:
                continue
            success = result.get("success")
            if success not in (True, False):
                continue
            observations.append({
                "id": pred_id,
                "ctx": ctx,
                "sport": getattr(ctx, "sport", "table_tennis"),
                "success": bool(success),
                "kind": prediction.get("kind", ""),
                "target": prediction.get("target", ""),
                "verdict": prediction.get("verdict", ""),
                "label": prediction.get("label", ""),
                "team1": data.get("team1", ""),
                "team2": data.get("team2", ""),
                "league": data.get("league", ""),
                "sent_at": data.get("sent_at", ""),
                "score": result.get("score", ""),
                "total": result.get("total"),
            })

    observations.sort(key=lambda item: str(item.get("sent_at", "")), reverse=True)
    if limit and len(observations) > int(limit):
        observations = observations[:int(limit)]
    return observations


def count_samples(sent_predictions):
    """Сколько прогнозов вообще имеют снимок статистики."""
    total = 0
    for data in (sent_predictions or {}).values():
        if isinstance(data, dict) and context_from_sample(data.get("stats")):
            total += 1
    return total


# --------------------------------------------------------------------------
# варианты метрик
# --------------------------------------------------------------------------

def candidate_variants(sport=None):
    """Список пар (метрика, аргументы) для перебора."""
    source = ce.sport_metrics(sport) if sport else ce.METRICS
    variants = []
    seen = set()
    for metric in source:
        if metric.get("type") in STRING_METRICS_SKIP:
            continue
        base = dict(metric.get("args") or {})
        args_list = [base]
        if "side" in base:
            args_list = [dict(args, side=side) for side in ("p1", "p2")
                         for args in args_list]
        if "window" in base:
            default_window = base.get("window")
            if isinstance(default_window, (int, float)) and default_window > 3:
                expanded = []
                for args in args_list:
                    expanded.append(args)
                    expanded.append(dict(args, window=3))
                args_list = expanded
        if "set" in base:
            expanded = []
            for args in args_list:
                for number in (1, 2):
                    expanded.append(dict(args, set=number))
            args_list = expanded
        for args in args_list:
            key = (metric["id"], json.dumps(args, sort_keys=True, ensure_ascii=False))
            if key in seen:
                continue
            seen.add(key)
            variants.append((metric["id"], args))
    return variants


def _nice_threshold(value, unit):
    """Округляет порог до удобного значения."""
    try:
        number = float(value)
    except Exception:
        return value
    if unit in ("очк.", "%"):
        step = 0.5
    elif abs(number) >= 5:
        step = 1.0
    else:
        step = 0.05
    return round(round(number / step) * step, 4)


def _numeric_candidates(values, definition):
    """Пороговые условия по наблюдаемым значениям метрики."""
    numbers = sorted({float(v) for v in values if isinstance(v, (int, float))})
    if len(numbers) < 2:
        return []
    unit = definition.get("unit", "")
    positions = (0.15, 0.3, 0.45, 0.55, 0.7, 0.85)
    thresholds = set()
    for position in positions:
        index = min(len(numbers) - 1,
                    max(0, int(round(position * (len(numbers) - 1)))))
        thresholds.add(numbers[index])
    out = []
    for threshold in sorted(thresholds):
        nice = _nice_threshold(threshold, unit)
        out.append(("gte", nice))
        out.append(("lte", nice))
    return out


def _categorical_candidates(definition):
    kind = definition.get("type")
    if kind == "enum":
        return [("eq", value) for value, _ in (definition.get("options") or [])]
    if kind == "bool":
        return [("is", True)]
    return []


# --------------------------------------------------------------------------
# разбор результатов
# --------------------------------------------------------------------------

def _evaluate_flags(observations, metric_id, args):
    values = []
    for observation in observations:
        try:
            values.append(ce.evaluate_metric(observation["ctx"], metric_id, args))
        except Exception:
            values.append(None)
    return values


def _shares(observations, flags, success=True):
    indexes = [i for i, item in enumerate(observations)
               if item["success"] is success]
    hits = sum(1 for i in indexes if flags[i])
    total = len(indexes)
    share = round(hits / total * 100, 1) if total else 0.0
    return hits, total, share


def _row(metric_id, args, op, expected, observations, flags, coverage, sport=None):
    definition = ce.METRIC_MAP.get(metric_id) or {}
    win_hits, win_n, win_share = _shares(observations, flags, True)
    loss_hits, loss_n, loss_share = _shares(observations, flags, False)
    condition = {"metric": metric_id, "args": dict(args), "op": op,
                 "value": expected}
    return {
        "metric": metric_id,
        "args": dict(args),
        "op": op,
        "value": expected,
        "condition": condition,
        "text": ce.describe_condition(condition, sport=sport),
        "unit": definition.get("unit", ""),
        "coverage": round(coverage * 100, 1),
        "win_hits": win_hits,
        "win_n": win_n,
        "win_share": win_share,
        "loss_hits": loss_hits,
        "loss_n": loss_n,
        "loss_share": loss_share,
        "lift": round(win_share - loss_share, 1),
        "failure_score": round(max(0.0, loss_share - win_share) * loss_share / 100.0, 2),
        "success_score": round(max(0.0, win_share - loss_share) * win_share / 100.0, 2),
        "_flags": flags,
    }


def _all_rows(observations, sport=None):
    rows = []
    for metric_id, args in candidate_variants(sport):
        definition = ce.METRIC_MAP.get(metric_id) or {}
        values = _evaluate_flags(observations, metric_id, args)
        coverage = sum(1 for v in values if v is not None) / len(observations) \
            if observations else 0.0
        kind = definition.get("type", "number")
        if kind == "number":
            candidates = _numeric_candidates(values, definition)
        elif kind in ("enum", "bool"):
            candidates = _categorical_candidates(definition)
        else:
            continue
        for op, expected in candidates:
            flags = []
            for value in values:
                try:
                    flags.append(bool(ce.compare_values(value, op, expected,
                                                        None, kind)))
                except Exception:
                    flags.append(False)
            if not any(flags):
                continue
            rows.append(_row(metric_id, args, op, expected, observations,
                             flags, coverage, sport))
    return rows


def _args_key(args):
    return json.dumps(args or {}, sort_keys=True, ensure_ascii=False)


def _select(rows, score_key, hits_key, share_key, other_key, min_hits,
            min_lift, min_group):
    """Отбирает лучшие условия одной группы (по одному на метрику+аргументы)."""
    best = {}
    for row in rows:
        if row[hits_key] < min_hits:
            continue
        if row[share_key] < 50.0:
            continue
        if row[share_key] - row[other_key] < min_lift:
            continue
        if row["win_n"] < min_group or row["loss_n"] < min_group:
            continue
        key = (row["metric"], _args_key(row["args"]))
        current = best.get(key)
        if current is None or row[score_key] > current[score_key]:
            best[key] = row
    ordered = sorted(best.values(),
                     key=lambda item: (-item[score_key], -item[share_key]))
    return ordered


def _examples(row, observations, want_success):
    out = []
    flags = row["_flags"]
    for index, observation in enumerate(observations):
        if not flags[index]:
            continue
        if bool(observation["success"]) is not want_success:
            continue
        out.append({
            "teams": "%s — %s" % (observation["team1"], observation["team2"]),
            "verdict": observation["verdict"],
            "score": observation["score"],
            "total": observation["total"],
            "sent_at": observation["sent_at"],
        })
        if len(out) >= MAX_EXAMPLES:
            break
    return out


def _clean(row, observations, want_success):
    data = {key: value for key, value in row.items() if not key.startswith("_")}
    data["examples"] = _examples(row, observations, want_success)
    return data


def _pairs(rows, observations, other_n, min_group, want_success):
    """Комбинации из двух лучших условий той же группы."""
    top = rows[:6]
    if len(top) < 2 or other_n < min_group:
        return []
    combos = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            left, right = top[i], top[j]
            group = {"logic": "and",
                     "conditions": [dict(left["condition"]), dict(right["condition"])]}
            flags = []
            for observation in observations:
                try:
                    matched, _ = ce.evaluate_group(observation["ctx"], group)
                except Exception:
                    matched = False
                flags.append(bool(matched))
            if not any(flags):
                continue
            win_hits, win_n, win_share = _shares(observations, flags, True)
            loss_hits, loss_n, loss_share = _shares(observations, flags, False)
            if want_success:
                hits, share, other = win_hits, win_share, loss_share
            else:
                hits, share, other = loss_hits, loss_share, win_share
            if hits < MIN_HITS or share < 60.0 or share - other < 20.0:
                continue
            combos.append({
                "conditions": [dict(left["condition"]), dict(right["condition"])],
                "texts": [left["text"], right["text"]],
                "text": "%s И %s" % (left["text"], right["text"]),
                "win_hits": win_hits, "win_n": win_n, "win_share": win_share,
                "loss_hits": loss_hits, "loss_n": loss_n, "loss_share": loss_share,
                "lift": round(share - other, 1),
                "score": round(max(0.0, share - other) * share / 100.0, 2),
            })
    combos.sort(key=lambda item: (-item["score"], -item["lift"]))
    return combos[:6]


def _means(observations, min_group, sport=None):
    """Средние значения метрик: зашло против не зашло."""
    out = []
    for metric_id, args in candidate_variants(sport):
        definition = ce.METRIC_MAP.get(metric_id) or {}
        if definition.get("type") != "number":
            continue
        values = _evaluate_flags(observations, metric_id, args)
        win_values = [v for v, o in zip(values, observations)
                      if o["success"] and isinstance(v, (int, float))]
        loss_values = [v for v, o in zip(values, observations)
                       if not o["success"] and isinstance(v, (int, float))]
        if len(win_values) < min_group or len(loss_values) < min_group:
            continue
        win_mean = sum(win_values) / len(win_values)
        loss_mean = sum(loss_values) / len(loss_values)
        delta = win_mean - loss_mean
        pooled = win_values + loss_values
        mean = sum(pooled) / len(pooled)
        spread = (sum((v - mean) ** 2 for v in pooled) / len(pooled)) ** 0.5
        normalized = abs(delta) / spread if spread > 1e-9 else 0.0
        out.append({
            "metric": metric_id,
            "args": dict(args),
            "label": ce.format_metric_label(metric_id, args, sport),
            "unit": definition.get("unit", ""),
            "win_mean": round(win_mean, 2),
            "loss_mean": round(loss_mean, 2),
            "delta": round(delta, 2),
            "normalized": round(normalized, 3),
            "win_n": len(win_values),
            "loss_n": len(loss_values),
        })
    out.sort(key=lambda item: -item["normalized"])
    return out[:15]


# --------------------------------------------------------------------------
# публичная точка входа
# --------------------------------------------------------------------------

def analyze(sent_predictions, kind="all", target="", min_group=MIN_GROUP,
            min_lift=MIN_LIFT, min_hits=MIN_HITS, max_rows=MAX_ROWS,
            limit=0, with_pairs=True, sport=None):
    """Полный разбор: неудачные и успешные прогнозы."""
    min_group = max(1, int(min_group or MIN_GROUP))
    observations = build_observations(sent_predictions, kind=kind, target=target,
                                      limit=limit, sport=sport)
    sport = ce.sport_catalog.normalize_sport(sport) if sport else ""
    win_n = sum(1 for item in observations if item["success"])
    loss_n = len(observations) - win_n

    payload = {
        "ok": True,
        "options": {
            "kind": kind or "all",
            "target": target or "",
            "min_group": min_group,
            "min_lift": min_lift,
            "min_hits": min_hits,
            "sport": sport,
        },
        "observations": {
            "total": len(observations),
            "wins": win_n,
            "losses": loss_n,
            "with_stats": count_samples(sent_predictions),
        },
        "min_group": min_group,
        "sufficient": win_n >= min_group and loss_n >= min_group,
        "generated_at": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
    }

    if not observations:
        payload["hint"] = (
            "Пока нет прогнозов с сохранённой статистикой. Статистика "
            "записывается в момент отправки прогноза — дайте движку собрать "
            "несколько прогнозов и результатов."
        )
        payload["failure"] = []
        payload["success"] = []
        payload["combos"] = {"failure": [], "success": []}
        payload["means"] = []
        return payload

    if not payload["sufficient"]:
        payload["hint"] = (
            "Мало данных для вывода: нужно минимум %d удачных и %d неудачных "
            "прогнозов, а сейчас %d и %d." % (min_group, min_group, win_n, loss_n)
        )
        payload["failure"] = []
        payload["success"] = []
        payload["combos"] = {"failure": [], "success": []}
        payload["means"] = _means(observations, min_group, sport)
        return payload

    rows = _all_rows(observations, sport)
    failures = _select(rows, "failure_score", "loss_hits", "loss_share",
                       "win_share", min_hits, min_lift, min_group)
    successes = _select(rows, "success_score", "win_hits", "win_share",
                        "loss_share", min_hits, min_lift, min_group)

    payload["failure"] = [_clean(row, observations, False)
                          for row in failures[:int(max_rows)]]
    payload["success"] = [_clean(row, observations, True)
                          for row in successes[:int(max_rows)]]
    payload["combos"] = {
        "failure": _pairs(failures, observations, win_n, min_group, False) if with_pairs else [],
        "success": _pairs(successes, observations, loss_n, min_group, True) if with_pairs else [],
    }
    payload["means"] = _means(observations, min_group, sport)

    if not payload["failure"] and not payload["success"]:
        payload["hint"] = (
            "Выраженных различий не найдено. Попробуйте снизить порог "
            "перевеса или добавить наблюдений."
        )
    return payload

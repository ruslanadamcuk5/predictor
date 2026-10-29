# -*- coding: utf-8 -*-
"""Конструктор правил прогнозирования.

Модуль не зависит от predictor_core: он получает уже разобранную статистику
(очные встречи + последние игры каждого игрока) и оценивает по ней
пользовательские правила.

Правило = набор условий (с вложенными группами И/ИЛИ) + действие:
  * winner  — прогноз на победителя партии;
  * total   — прогноз на тотал партии (ТБ/ТМ с любым порогом);
  * skip    — пропустить матч, если условия совпали.

Значения условий берутся из каталога метрик (см. METRICS): форма игрока,
очные встречи, сравнение игроков, коэффициенты, время матча и т.д.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime

VERSION = 1

# --------------------------------------------------------------------------
# вспомогательные функции
# --------------------------------------------------------------------------

def clean_name(value):
    return re.sub(r"[^\w\s]", "", str(value or "")).lower().strip()


def names_match(a, b):
    a, b = clean_name(a), clean_name(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    words_a, words_b = a.split(), b.split()
    return bool(words_a and words_b and words_a[-1] == words_b[-1])


def _to_float(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def _avg(values):
    values = [v for v in values if v is not None]
    return (sum(values) / len(values)) if values else None


def _pct(part, total):
    return round(part / total * 100, 1) if total else None


def _round(value, digits=2):
    return round(value, digits) if value is not None else None


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d.%m.%y", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
                "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(datetime.now().strftime(fmt))], fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", ""))
    except Exception:
        return None


def _match_score(value):
    m = re.search(r"(\d+)\s*:\s*(\d+)", str(value or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _sets_at(record, number):
    sets = record.get("sets") or []
    index = _to_int(number, 1) - 1
    return sets[index] if 0 <= index < len(sets) else None


def _fmt_num(value, digits=2):
    if value is None:
        return "—"
    try:
        number = float(value)
    except Exception:
        return str(value)
    if abs(number - round(number)) < 0.005:
        return str(int(round(number)))
    return ("%." + str(digits) + "f") % number


def _threshold_text(value):
    text = _fmt_num(value, 1)
    return text


# --------------------------------------------------------------------------
# нормализация статистики
# --------------------------------------------------------------------------

def _normalize_h2h(stats):
    """Очные встречи, ориентированные относительно текущего игрока 1."""
    team1 = stats.get("team1", "")
    team2 = stats.get("team2", "")
    result = []
    for raw in stats.get("h2h_matches") or []:
        sets = [(int(a), int(b)) for a, b in (raw.get("sets_parsed") or [])]
        if not sets:
            continue
        player1 = raw.get("player1", "")
        flipped = names_match(team2, player1) and not names_match(team1, player1)
        if flipped:
            sets = [(b, a) for a, b in sets]

        ms = _match_score(raw.get("match_score"))
        winner = raw.get("winner")
        if winner in ("P1", "P2"):
            p1_won = (winner == "P1")
            won_p1 = (not p1_won) if flipped else p1_won
        elif ms:
            won_p1 = (ms[0] > ms[1])
            if flipped:
                won_p1 = not won_p1
        else:
            own = sum(1 for a, b in sets if a > b)
            opp = sum(1 for a, b in sets if b > a)
            won_p1 = own > opp

        if ms:
            match_sets = (ms[1], ms[0]) if flipped else (ms[0], ms[1])
        else:
            match_sets = (sum(1 for a, b in sets if a > b),
                          sum(1 for a, b in sets if b > a))

        totals = [a + b for a, b in sets]
        result.append({
            "date": _parse_dt(raw.get("date_obj") or raw.get("date")),
            "sets": sets,
            "totals": totals,
            "match_total": sum(totals),
            "num_sets": len(sets),
            "won_p1": bool(won_p1),
            "match_sets": match_sets,
            "margin": _avg([abs(a - b) for a, b in sets]),
            "league": "",
            "opponent": "",
        })
    result.sort(key=lambda r: r["date"] or datetime.min, reverse=True)
    return result


def _normalize_recent(stats, side):
    raw = (stats.get("recent") or {}).get(side) or []
    result = []
    for item in raw:
        sets = [(int(a), int(b)) for a, b in (item.get("sets") or [])]
        totals = [a + b for a, b in sets]
        ms = item.get("match_score")
        if not isinstance(ms, (list, tuple)) or len(ms) != 2:
            ms = (sum(1 for a, b in sets if a > b),
                  sum(1 for a, b in sets if b > a))
        result.append({
            "date": _parse_dt(item.get("date")),
            "date_text": item.get("date_text", ""),
            "league": item.get("league", ""),
            "opponent": item.get("opponent", ""),
            "sets": sets,
            "totals": totals,
            "match_total": sum(totals),
            "num_sets": len(sets),
            "match_sets": (int(ms[0]), int(ms[1])),
            "won": bool(ms[0] > ms[1]),
            "margin": _avg([a - b for a, b in sets]),
        })
    result.sort(key=lambda r: r["date"] or datetime.min, reverse=True)
    return result[:10]


class Context:
    """Предвычисленный контекст одного матча."""

    def __init__(self, match, stats):
        self.match = match or {}
        self.stats = stats or {}
        self.h2h = _normalize_h2h(self.stats)
        self.recent = {
            "p1": _normalize_recent(self.stats, "team1"),
            "p2": _normalize_recent(self.stats, "team2"),
        }
        self._cache = {}

    # окна
    def h2h_window(self, window):
        return self.h2h[:_to_int(window, 10) or 10]

    def recent_window(self, side, window):
        return self.recent.get(side, [])[:_to_int(window, 5) or 5]

    def odds(self):
        return self.match.get("odds") or {}

    def start_dt(self):
        return _parse_dt(self.match.get("start_time"))

    def now(self):
        return datetime.now()


# --------------------------------------------------------------------------
# метрики
# --------------------------------------------------------------------------

def _merge_args(definition, args):
    merged = dict(definition.get("args") or {})
    merged.update(args or {})
    return merged


def _h2h_wins(ctx, args):
    side = args.get("side", "p1")
    seq = ctx.h2h_window(args.get("window", 10))
    return sum(1 for m in seq if (m["won_p1"] if side == "p1" else not m["won_p1"]))


def _recent_stat(ctx, args, pick):
    side = args.get("side", "p1")
    seq = ctx.recent_window(side, args.get("window", 5))
    return pick(seq)


def _winner_rate(seq, side):
    if not seq:
        return None
    wins = sum(1 for m in seq if (m["won_p1"] if side == "p1" else not m["won_p1"]))
    return _pct(wins, len(seq))


def _h2h_win_rate(ctx, args):
    return _winner_rate(ctx.h2h_window(args.get("window", 10)), args.get("side", "p1"))


def _h2h_streak(ctx, args):
    side = args.get("side", "p1")
    length = 0
    for match in ctx.h2h:
        won = match["won_p1"] if side == "p1" else not match["won_p1"]
        if won:
            length += 1
        else:
            break
    return length


def _h2h_last_winner(ctx, args):
    if not ctx.h2h:
        return None
    return "p1" if ctx.h2h[0]["won_p1"] else "p2"


def _h2h_last_match_total(ctx, args):
    return ctx.h2h[0]["match_total"] if ctx.h2h else None


def _h2h_avg_match_total(ctx, args):
    return _round(_avg([m["match_total"] for m in ctx.h2h_window(args.get("window", 10))]))


def _h2h_avg_set_total(ctx, args):
    seq = ctx.h2h_window(args.get("window", 10))
    values = []
    for match in seq:
        pair = _sets_at(match, args.get("set", 1))
        if pair:
            values.append(pair[0] + pair[1])
    return _round(_avg(values))


def _h2h_avg_set_points(ctx, args):
    side = args.get("side", "p1")
    seq = ctx.h2h_window(args.get("window", 10))
    values = []
    for match in seq:
        pair = _sets_at(match, args.get("set", 1))
        if pair:
            values.append(pair[0] if side == "p1" else pair[1])
    return _round(_avg(values))


def _h2h_set_win_rate(ctx, args):
    side = args.get("side", "p1")
    seq = ctx.h2h_window(args.get("window", 10))
    total = won = 0
    for match in seq:
        pair = _sets_at(match, args.get("set", 1))
        if not pair:
            continue
        total += 1
        if (pair[0] > pair[1]) if side == "p1" else (pair[1] > pair[0]):
            won += 1
    return _pct(won, total)


def _h2h_over_rate(ctx, args):
    threshold = _to_float(args.get("threshold", 18.5), 18.5)
    seq = ctx.h2h_window(args.get("window", 10))
    total = over = 0
    for match in seq:
        pair = _sets_at(match, args.get("set", 1))
        if not pair:
            continue
        total += 1
        if pair[0] + pair[1] > threshold:
            over += 1
    return _pct(over, total)


def _h2h_match_over_rate(ctx, args):
    threshold = _to_float(args.get("threshold", 18.5), 18.5)
    seq = ctx.h2h_window(args.get("window", 10))
    return _pct(sum(1 for m in seq if m["match_total"] > threshold), len(seq))


def _h2h_avg_sets(ctx, args):
    return _round(_avg([m["num_sets"] for m in ctx.h2h_window(args.get("window", 10))]), 1)


def _h2h_five_set_rate(ctx, args):
    seq = ctx.h2h_window(args.get("window", 10))
    return _pct(sum(1 for m in seq if m["num_sets"] >= 5), len(seq))


def _h2h_avg_margin(ctx, args):
    return _round(_avg([m["margin"] for m in ctx.h2h_window(args.get("window", 10))]))


def _h2h_days_since_last(ctx, args):
    if not ctx.h2h or not ctx.h2h[0]["date"]:
        return None
    return max(0, (datetime.now() - ctx.h2h[0]["date"]).days)


def _h2h_max_match_total(ctx, args):
    seq = ctx.h2h_window(args.get("window", 10))
    return max((m["match_total"] for m in seq), default=None)


def _h2h_min_match_total(ctx, args):
    seq = ctx.h2h_window(args.get("window", 10))
    return min((m["match_total"] for m in seq), default=None)


# ----- форма игрока -----

def _recent_count(ctx, args):
    return len(ctx.recent_window(args.get("side", "p1"), args.get("window", 5)))


def _recent_wins(ctx, args):
    side = args.get("side", "p1")
    seq = ctx.recent_window(side, args.get("window", 5))
    return sum(1 for m in seq if m["won"])


def _recent_losses(ctx, args):
    return len(ctx.recent_window(args.get("side", "p1"), args.get("window", 5))) - \
        _recent_wins(ctx, args)


def _recent_win_rate(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    return _pct(sum(1 for m in seq if m["won"]), len(seq))


def _recent_streak(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 10))
    if not seq:
        return 0
    sign = 1 if seq[0]["won"] else -1
    length = 0
    for match in seq:
        if match["won"] == (sign > 0):
            length += 1
        else:
            break
    return sign * length


def _recent_last_result(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), 1)
    if not seq:
        return None
    return "win" if seq[0]["won"] else "loss"


def _recent_avg_match_total(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    return _round(_avg([m["match_total"] for m in seq]))


def _recent_avg_set_total(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    values = [total for m in seq for total in m["totals"]]
    return _round(_avg(values))


def _recent_avg_set_points(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    values = [a for m in seq for a, b in m["sets"]]
    return _round(_avg(values))


def _recent_avg_conceded(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    values = [b for m in seq for a, b in m["sets"]]
    return _round(_avg(values))


def _recent_over_rate(ctx, args):
    threshold = _to_float(args.get("threshold", 18.5), 18.5)
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    totals = [total for m in seq for total in m["totals"]]
    return _pct(sum(1 for t in totals if t > threshold), len(totals))


def _recent_match_over_rate(ctx, args):
    threshold = _to_float(args.get("threshold", 18.5), 18.5)
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    return _pct(sum(1 for m in seq if m["match_total"] > threshold), len(seq))


def _recent_avg_sets(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    return _round(_avg([m["num_sets"] for m in seq]), 1)


def _recent_set_win_rate(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    total = won = 0
    for match in seq:
        pair = _sets_at(match, args.get("set", 1))
        if not pair:
            continue
        total += 1
        if pair[0] > pair[1]:
            won += 1
    return _pct(won, total)


def _recent_first_set_win_rate(ctx, args):
    args = dict(args)
    args["set"] = 1
    return _recent_set_win_rate(ctx, args)


def _recent_set_avg_total(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    values = []
    for match in seq:
        pair = _sets_at(match, args.get("set", 1))
        if pair:
            values.append(pair[0] + pair[1])
    return _round(_avg(values))


def _recent_set_avg_points(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    values = []
    for match in seq:
        pair = _sets_at(match, args.get("set", 1))
        if pair:
            values.append(pair[0])
    return _round(_avg(values))


def _recent_set_over_rate(ctx, args):
    threshold = _to_float(args.get("threshold", 18.5), 18.5)
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    total = over = 0
    for match in seq:
        pair = _sets_at(match, args.get("set", 1))
        if not pair:
            continue
        total += 1
        if pair[0] + pair[1] > threshold:
            over += 1
    return _pct(over, total)


def _recent_avg_margin(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    return _round(_avg([m["margin"] for m in seq]))


def _recent_days_since_last(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), 1)
    if not seq or not seq[0]["date"]:
        return None
    return max(0, (datetime.now() - seq[0]["date"]).days)


def _recent_matches_last_7d(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 10))
    now = datetime.now()
    return sum(1 for m in seq
               if m["date"] and (now - m["date"]).days <= 7)


def _recent_trend_total(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    if len(seq) < 2:
        return None
    middle = len(seq) // 2
    fresh = _avg([m["match_total"] for m in seq[:middle]])
    old = _avg([m["match_total"] for m in seq[middle:]])
    return _round((fresh - old) if fresh is not None and old is not None else None)


def _recent_max_match_total(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    return max((m["match_total"] for m in seq), default=None)


def _recent_min_match_total(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    return min((m["match_total"] for m in seq), default=None)


def _recent_five_set_rate(ctx, args):
    seq = ctx.recent_window(args.get("side", "p1"), args.get("window", 5))
    return _pct(sum(1 for m in seq if m["num_sets"] >= 5), len(seq))


# ----- сравнение -----

def _cmp_win_rate_diff(ctx, args):
    left = _recent_win_rate(ctx, {"side": "p1", "window": args.get("window", 5)})
    right = _recent_win_rate(ctx, {"side": "p2", "window": args.get("window", 5)})
    return _round(left - right, 1) if left is not None and right is not None else None


def _cmp_avg_total_diff(ctx, args):
    left = _recent_avg_match_total(ctx, {"side": "p1", "window": args.get("window", 5)})
    right = _recent_avg_match_total(ctx, {"side": "p2", "window": args.get("window", 5)})
    return _round(left - right) if left is not None and right is not None else None


def _cmp_avg_total_sum(ctx, args):
    left = _recent_avg_match_total(ctx, {"side": "p1", "window": args.get("window", 5)})
    right = _recent_avg_match_total(ctx, {"side": "p2", "window": args.get("window", 5)})
    return _round(left + right) if left is not None and right is not None else None


def _cmp_avg_total_min(ctx, args):
    left = _recent_avg_match_total(ctx, {"side": "p1", "window": args.get("window", 5)})
    right = _recent_avg_match_total(ctx, {"side": "p2", "window": args.get("window", 5)})
    values = [v for v in (left, right) if v is not None]
    return _round(min(values)) if values else None


def _cmp_avg_total_max(ctx, args):
    left = _recent_avg_match_total(ctx, {"side": "p1", "window": args.get("window", 5)})
    right = _recent_avg_match_total(ctx, {"side": "p2", "window": args.get("window", 5)})
    values = [v for v in (left, right) if v is not None]
    return _round(max(values)) if values else None


def _cmp_set_total_values(ctx, args):
    left = _recent_avg_set_total(ctx, {"side": "p1", "window": args.get("window", 5)})
    right = _recent_avg_set_total(ctx, {"side": "p2", "window": args.get("window", 5)})
    return [v for v in (left, right) if v is not None]


def _cmp_avg_set_total_mean(ctx, args):
    values = _cmp_set_total_values(ctx, args)
    return _round(_avg(values)) if values else None


def _cmp_avg_set_total_min(ctx, args):
    values = _cmp_set_total_values(ctx, args)
    return _round(min(values)) if values else None


def _cmp_avg_set_total_max(ctx, args):
    values = _cmp_set_total_values(ctx, args)
    return _round(max(values)) if values else None


def _cmp_win_rate_lead(ctx, args):
    diff = _cmp_win_rate_diff(ctx, args)
    if diff is None:
        return None
    if abs(diff) < 0.05:
        return "tie"
    return "p1" if diff > 0 else "p2"


def _cmp_streak_diff(ctx, args):
    left = _recent_streak(ctx, {"side": "p1", "window": args.get("window", 5)})
    right = _recent_streak(ctx, {"side": "p2", "window": args.get("window", 5)})
    return left - right


def _cmp_h2h_wins_diff(ctx, args):
    return _h2h_wins(ctx, {"side": "p1", "window": args.get("window", 10)}) - \
        _h2h_wins(ctx, {"side": "p2", "window": args.get("window", 10)})


# ----- коэффициенты и матч -----

def _odds_p1(ctx, args):
    return _to_float(ctx.odds().get("match_p1") or ctx.odds().get("set1_p1"))


def _odds_p2(ctx, args):
    return _to_float(ctx.odds().get("match_p2") or ctx.odds().get("set1_p2"))


def _odds_ratio(ctx, args):
    left, right = _odds_p1(ctx, {}), _odds_p2(ctx, {})
    if not left or not right:
        return None
    return _round(left / right, 3)


def _odds_implied_p1(ctx, args):
    value = _odds_p1(ctx, {})
    return _round(100.0 / value, 1) if value else None


def _odds_implied_p2(ctx, args):
    value = _odds_p2(ctx, {})
    return _round(100.0 / value, 1) if value else None


def _odds_favorite(ctx, args):
    left, right = _odds_p1(ctx, {}), _odds_p2(ctx, {})
    if not left or not right:
        return None
    if abs(left - right) < 0.01:
        return "tie"
    return "p1" if left < right else "p2"


def _odds_available(ctx, args):
    return bool(_odds_p1(ctx, {}) and _odds_p2(ctx, {}))


def _match_hour(ctx, args):
    dt = ctx.start_dt()
    return dt.hour if dt else None


def _match_weekday(ctx, args):
    dt = ctx.start_dt()
    return dt.weekday() if dt else None


def _match_minutes_to_start(ctx, args):
    dt = ctx.start_dt()
    if not dt:
        return None
    return int((dt - datetime.now()).total_seconds() // 60)


def _match_started(ctx, args):
    return bool(ctx.match.get("is_started"))


def _match_current_sets(ctx, args):
    score = ctx.match.get("current_score") or "0:0"
    parts = re.findall(r"\d+", str(score))
    return sum(int(p) for p in parts[:2]) if parts else 0


def _match_current_set(ctx, args):
    return min(5, _match_current_sets(ctx, args) + 1)


def _match_score_total(ctx, args):
    return _match_current_sets(ctx, args)


def _match_league(ctx, args):
    return str(ctx.stats.get("league") or ctx.match.get("league") or "")


def _page_value(key):
    def getter(ctx, args):
        page = ctx.stats.get("page_total") or {}
        return page.get(key)
    return getter


def _page_over_share(ctx, args):
    page = ctx.stats.get("page_total") or {}
    over = _to_int(page.get("last5_over"), 0)
    under = _to_int(page.get("last5_under"), 0)
    return _pct(over, over + under)


def _page_season_over_rate(ctx, args):
    page = ctx.stats.get("page_total") or {}
    over = _to_int(page.get("season_over"), 0)
    under = _to_int(page.get("season_under"), 0)
    return _pct(over, over + under)


# --------------------------------------------------------------------------
# каталог метрик
# --------------------------------------------------------------------------

def _def(metric_id, label, group, kind, args=None, unit="", hint=""):
    return {
        "id": metric_id,
        "label": label,
        "group": group,
        "type": kind,
        "args": args or {},
        "unit": unit,
        "hint": hint,
    }


H2H = "Очные встречи"
FORM = "Форма игрока"
CMP = "Сравнение игроков"
ODDS = "Коэффициенты"
MATCH = "Матч"
PAGE = "Тоталы со страницы"

METRICS = [
    # --- очные встречи ---
    _def("h2h.count", "Сколько очных встреч найдено", H2H, "number",
         hint="До 10 последних встреч"),
    _def("h2h.wins", "Побед {side} в очных за {window}", H2H, "number",
         {"side": "p1", "window": 10}),
    _def("h2h.win_rate", "Процент побед {side} в очных за {window}", H2H, "number",
         {"side": "p1", "window": 10}, "%"),
    _def("h2h.streak", "Текущая серия побед {side} в очных", H2H, "number",
         {"side": "p1"}, "игр"),
    _def("h2h.last_winner", "Победитель последней очной встречи", H2H, "enum"),
    _def("h2h.last_match_total", "Тотал последней очной встречи", H2H, "number", unit="очк."),
    _def("h2h.avg_match_total", "Средний тотал матча в очных за {window}", H2H, "number",
         {"window": 10}, "очк."),
    _def("h2h.avg_set_total", "Средний тотал {set} партии в очных за {window}", H2H, "number",
         {"window": 10, "set": 1}, "очк."),
    _def("h2h.avg_set_points", "Средние очки {side} в {set} партии очных за {window}", H2H, "number",
         {"side": "p1", "window": 10, "set": 1}, "очк."),
    _def("h2h.set_win_rate", "Процент побед {side} в {set} партии очных за {window}", H2H, "number",
         {"side": "p1", "window": 10, "set": 1}, "%"),
    _def("h2h.over_rate", "Доля ТБ{threshold} в {set} партии очных за {window}", H2H, "number",
         {"window": 10, "set": 1, "threshold": 18.5}, "%"),
    _def("h2h.match_over_rate", "Доля матчей с тоталом выше {threshold} в очных за {window}", H2H, "number",
         {"window": 10, "threshold": 75.5}, "%"),
    _def("h2h.avg_sets", "Среднее число партий в очных за {window}", H2H, "number",
         {"window": 10}, "партий"),
    _def("h2h.five_set_rate", "Доля матчей из 5 партий в очных за {window}", H2H, "number",
         {"window": 10}, "%"),
    _def("h2h.avg_margin", "Средний разрыв в партиях очных за {window}", H2H, "number",
         {"window": 10}, "очк."),
    _def("h2h.days_since_last", "Дней с последней очной встречи", H2H, "number", unit="дн."),
    _def("h2h.max_match_total", "Максимальный тотал матча в очных за {window}", H2H, "number",
         {"window": 10}, "очк."),
    _def("h2h.min_match_total", "Минимальный тотал матча в очных за {window}", H2H, "number",
         {"window": 10}, "очк."),

    # --- форма игрока ---
    _def("p.recent.count", "Сколько последних игр {side} найдено", FORM, "number",
         {"side": "p1", "window": 5}, hint="До 5 игр со страницы статистики"),
    _def("p.recent.wins", "Побед {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5}),
    _def("p.recent.losses", "Поражений {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5}),
    _def("p.recent.win_rate", "Процент побед {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5}, "%"),
    _def("p.recent.streak", "Серия {side} (+ победы, − поражения)", FORM, "number",
         {"side": "p1", "window": 10}, "игр"),
    _def("p.recent.last_result", "Результат последней игры {side}", FORM, "enum",
         {"side": "p1"}),
    _def("p.recent.avg_match_total", "Средний тотал матча {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5}, "очк."),
    _def("p.recent.avg_set_total", "Средний тотал партии {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5}, "очк."),
    _def("p.recent.avg_set_points", "Средние очки {side} за партию ({window} игр)", FORM, "number",
         {"side": "p1", "window": 5}, "очк."),
    _def("p.recent.avg_conceded", "Средне пропущено {side} за партию ({window} игр)", FORM, "number",
         {"side": "p1", "window": 5}, "очк."),
    _def("p.recent.over_rate", "Доля ТБ{threshold} в партиях {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5, "threshold": 18.5}, "%"),
    _def("p.recent.match_over_rate", "Доля матчей {side} с тоталом выше {threshold} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5, "threshold": 75.5}, "%"),
    _def("p.recent.avg_sets", "Среднее число партий {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5}, "партий"),
    _def("p.recent.first_set_win_rate", "Процент побед {side} в 1-й партии за {window} игр", FORM, "number",
         {"side": "p1", "window": 5}, "%"),
    _def("p.recent.set_win_rate", "Процент побед {side} в {set} партии за {window} игр", FORM, "number",
         {"side": "p1", "window": 5, "set": 1}, "%"),
    _def("p.recent.set_avg_total", "Средний тотал {set} партии {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5, "set": 1}, "очк."),
    _def("p.recent.set_avg_points", "Средние очки {side} в {set} партии за {window} игр", FORM, "number",
         {"side": "p1", "window": 5, "set": 1}, "очк."),
    _def("p.recent.set_over_rate", "Доля ТБ{threshold} в {set} партии {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5, "set": 1, "threshold": 18.5}, "%"),
    _def("p.recent.avg_margin", "Средний разрыв {side} за партию ({window} игр)", FORM, "number",
         {"side": "p1", "window": 5}, "очк."),
    _def("p.recent.days_since_last", "Дней с последней игры {side}", FORM, "number",
         {"side": "p1"}, "дн."),
    _def("p.recent.matches_last_7d", "Игр {side} за последние 7 дней", FORM, "number",
         {"side": "p1", "window": 10}),
    _def("p.recent.trend_total", "Тренд тотала {side}: свежие минус старые ({window} игр)", FORM, "number",
         {"side": "p1", "window": 5}, "очк."),
    _def("p.recent.max_match_total", "Максимальный тотал матча {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5}, "очк."),
    _def("p.recent.min_match_total", "Минимальный тотал матча {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5}, "очк."),
    _def("p.recent.five_set_rate", "Доля матчей из 5 партий {side} за {window} игр", FORM, "number",
         {"side": "p1", "window": 5}, "%"),

    # --- сравнение ---
    _def("cmp.win_rate_diff", "Разница процента побед (игрок 1 − игрок 2) за {window} игр", CMP, "number",
         {"window": 5}, "%"),
    _def("cmp.avg_total_diff", "Разница средних тоталов (игрок 1 − игрок 2) за {window} игр", CMP, "number",
         {"window": 5}, "очк."),
    _def("cmp.avg_total_sum", "Сумма средних тоталов матчей обоих за {window} игр", CMP, "number",
         {"window": 5}, "очк."),
    _def("cmp.avg_total_min", "Меньший средний тотал матча из двух за {window} игр", CMP, "number",
         {"window": 5}, "очк."),
    _def("cmp.avg_total_max", "Больший средний тотал матча из двух за {window} игр", CMP, "number",
         {"window": 5}, "очк."),
    _def("cmp.avg_set_total_mean", "Средний тотал партии по форме обоих за {window} игр", CMP, "number",
         {"window": 5}, "очк."),
    _def("cmp.avg_set_total_min", "Меньший средний тотал партии из двух за {window} игр", CMP, "number",
         {"window": 5}, "очк."),
    _def("cmp.avg_set_total_max", "Больший средний тотал партии из двух за {window} игр", CMP, "number",
         {"window": 5}, "очк."),
    _def("cmp.win_rate_lead", "Кто лучше по проценту побед за {window} игр", CMP, "enum",
         {"window": 5}),
    _def("cmp.streak_diff", "Разница серий (игрок 1 − игрок 2)", CMP, "number",
         {"window": 5}, "игр"),
    _def("cmp.h2h_wins_diff", "Разница побед в очных (игрок 1 − игрок 2) за {window}", CMP, "number",
         {"window": 10}),

    # --- коэффициенты ---
    _def("odds.p1", "Коэффициент на игрока 1", ODDS, "number"),
    _def("odds.p2", "Коэффициент на игрока 2", ODDS, "number"),
    _def("odds.ratio", "Отношение коэффициентов P1/P2", ODDS, "number"),
    _def("odds.implied_p1", "Подразумеваемая вероятность игрока 1", ODDS, "number", unit="%"),
    _def("odds.implied_p2", "Подразумеваемая вероятность игрока 2", ODDS, "number", unit="%"),
    _def("odds.favorite", "Фаворит букмекера", ODDS, "enum"),
    _def("odds.available", "Коэффициенты доступны", ODDS, "bool"),

    # --- матч ---
    _def("match.hour", "Час начала матча", MATCH, "number"),
    _def("match.weekday", "День недели матча", MATCH, "enum"),
    _def("match.minutes_to_start", "Минут до начала матча", MATCH, "number", unit="мин"),
    _def("match.started", "Матч уже начался", MATCH, "bool"),
    _def("match.current_sets", "Сыграно партий в матче", MATCH, "number"),
    _def("match.current_set", "Текущая/следующая партия", MATCH, "number"),
    _def("match.league", "Название лиги", MATCH, "string"),

    # --- тоталы со страницы статистики ---
    _def("page.total_line", "Линия тотала со страницы", PAGE, "number", unit="очк."),
    _def("page.over_last5", "ТБ линии в последних 5 играх (БОЛ)", PAGE, "number"),
    _def("page.under_last5", "ТМ линии в последних 5 играх (МЕН)", PAGE, "number"),
    _def("page.over_share_last5", "Доля ТБ линии в последних 5 играх", PAGE, "number", unit="%"),
    _def("page.season_over_rate", "Доля ТБ линии в текущем чемпионате", PAGE, "number", unit="%"),
]

METRIC_MAP = {item["id"]: item for item in METRICS}

METRIC_FUNCS = {
    "h2h.count": lambda ctx, a: len(ctx.h2h),
    "h2h.wins": _h2h_wins,
    "h2h.win_rate": _h2h_win_rate,
    "h2h.streak": _h2h_streak,
    "h2h.last_winner": _h2h_last_winner,
    "h2h.last_match_total": _h2h_last_match_total,
    "h2h.avg_match_total": _h2h_avg_match_total,
    "h2h.avg_set_total": _h2h_avg_set_total,
    "h2h.avg_set_points": _h2h_avg_set_points,
    "h2h.set_win_rate": _h2h_set_win_rate,
    "h2h.over_rate": _h2h_over_rate,
    "h2h.match_over_rate": _h2h_match_over_rate,
    "h2h.avg_sets": _h2h_avg_sets,
    "h2h.five_set_rate": _h2h_five_set_rate,
    "h2h.avg_margin": _h2h_avg_margin,
    "h2h.days_since_last": _h2h_days_since_last,
    "h2h.max_match_total": _h2h_max_match_total,
    "h2h.min_match_total": _h2h_min_match_total,

    "p.recent.count": _recent_count,
    "p.recent.wins": _recent_wins,
    "p.recent.losses": _recent_losses,
    "p.recent.win_rate": _recent_win_rate,
    "p.recent.streak": _recent_streak,
    "p.recent.last_result": _recent_last_result,
    "p.recent.avg_match_total": _recent_avg_match_total,
    "p.recent.avg_set_total": _recent_avg_set_total,
    "p.recent.avg_set_points": _recent_avg_set_points,
    "p.recent.avg_conceded": _recent_avg_conceded,
    "p.recent.over_rate": _recent_over_rate,
    "p.recent.match_over_rate": _recent_match_over_rate,
    "p.recent.avg_sets": _recent_avg_sets,
    "p.recent.first_set_win_rate": _recent_first_set_win_rate,
    "p.recent.set_win_rate": _recent_set_win_rate,
    "p.recent.set_avg_total": _recent_set_avg_total,
    "p.recent.set_avg_points": _recent_set_avg_points,
    "p.recent.set_over_rate": _recent_set_over_rate,
    "p.recent.avg_margin": _recent_avg_margin,
    "p.recent.days_since_last": _recent_days_since_last,
    "p.recent.matches_last_7d": _recent_matches_last_7d,
    "p.recent.trend_total": _recent_trend_total,
    "p.recent.max_match_total": _recent_max_match_total,
    "p.recent.min_match_total": _recent_min_match_total,
    "p.recent.five_set_rate": _recent_five_set_rate,

    "cmp.win_rate_diff": _cmp_win_rate_diff,
    "cmp.avg_total_diff": _cmp_avg_total_diff,
    "cmp.avg_total_sum": _cmp_avg_total_sum,
    "cmp.avg_total_min": _cmp_avg_total_min,
    "cmp.avg_total_max": _cmp_avg_total_max,
    "cmp.avg_set_total_mean": _cmp_avg_set_total_mean,
    "cmp.avg_set_total_min": _cmp_avg_set_total_min,
    "cmp.avg_set_total_max": _cmp_avg_set_total_max,
    "cmp.win_rate_lead": _cmp_win_rate_lead,
    "cmp.streak_diff": _cmp_streak_diff,
    "cmp.h2h_wins_diff": _cmp_h2h_wins_diff,

    "odds.p1": _odds_p1,
    "odds.p2": _odds_p2,
    "odds.ratio": _odds_ratio,
    "odds.implied_p1": _odds_implied_p1,
    "odds.implied_p2": _odds_implied_p2,
    "odds.favorite": _odds_favorite,
    "odds.available": _odds_available,

    "match.hour": _match_hour,
    "match.weekday": _match_weekday,
    "match.minutes_to_start": _match_minutes_to_start,
    "match.started": _match_started,
    "match.current_sets": _match_current_sets,
    "match.current_set": _match_current_set,
    "match.league": _match_league,

    "page.total_line": _page_value("line"),
    "page.over_last5": _page_value("last5_over"),
    "page.under_last5": _page_value("last5_under"),
    "page.over_share_last5": _page_over_share,
    "page.season_over_rate": _page_season_over_rate,
}

ARG_DEFS = {
    "side": {
        "label": "Игрок", "kind": "select", "default": "p1",
        "options": [["p1", "Игрок 1"], ["p2", "Игрок 2"]],
    },
    "window": {
        "label": "Игр", "kind": "number", "default": 5,
        "min": 1, "max": 20, "step": 1,
    },
    "set": {
        "label": "Партия", "kind": "select", "default": 1,
        "options": [[1, "1-я"], [2, "2-я"], [3, "3-я"], [4, "4-я"], [5, "5-я"]],
    },
    "threshold": {
        "label": "Тотал", "kind": "number", "default": 18.5,
        "min": 0, "max": 100, "step": 0.5,
    },
}

OPERATORS = {
    "number": [
        ["gt", "Больше"], ["gte", "Больше или равно"],
        ["lt", "Меньше"], ["lte", "Меньше или равно"],
        ["eq", "Равно"], ["neq", "Не равно"],
        ["between", "Между"], ["exists", "Есть данные"],
        ["not_exists", "Нет данных"],
    ],
    "string": [
        ["eq", "Равно"], ["neq", "Не равно"],
        ["contains", "Содержит"], ["not_contains", "Не содержит"],
        ["in", "Одно из"], ["not_in", "Не одно из"],
        ["starts_with", "Начинается с"], ["ends_with", "Заканчивается на"],
        ["exists", "Есть"], ["not_exists", "Нет"],
    ],
    "enum": [
        ["eq", "Равно"], ["neq", "Не равно"],
        ["in", "Одно из"], ["not_in", "Не одно из"],
        ["exists", "Есть"], ["not_exists", "Нет"],
    ],
    "bool": [
        ["is", "Равно"], ["exists", "Есть"], ["not_exists", "Нет"],
    ],
}

OP_SYMBOLS = {
    "gt": ">", "gte": "≥", "lt": "<", "lte": "≤",
    "eq": "=", "neq": "≠", "between": "между",
    "contains": "содержит", "not_contains": "не содержит",
    "in": "одно из", "not_in": "не одно из",
    "starts_with": "начинается с", "ends_with": "заканчивается на",
    "is": "=", "exists": "есть", "not_exists": "нет",
}

ENUM_OPTIONS = {
    "h2h.last_winner": [["p1", "Игрок 1"], ["p2", "Игрок 2"]],
    "odds.favorite": [["p1", "Игрок 1"], ["p2", "Игрок 2"], ["tie", "Равно"]],
    "cmp.win_rate_lead": [["p1", "Игрок 1"], ["p2", "Игрок 2"], ["tie", "Равно"]],
    "p.recent.last_result": [["win", "Победа"], ["loss", "Поражение"]],
    "match.weekday": [
        [0, "Понедельник"], [1, "Вторник"], [2, "Среда"], [3, "Четверг"],
        [4, "Пятница"], [5, "Суббота"], [6, "Воскресенье"],
    ],
}

ENUM_LABELS = {}
for _items in ENUM_OPTIONS.values():
    for _value, _label in _items:
        ENUM_LABELS[_value] = _label

SIDE_LABELS = {"p1": "игрока 1", "p2": "игрока 2"}


# --------------------------------------------------------------------------
# описание правил (для UI)
# --------------------------------------------------------------------------

def metric_definition(metric_id):
    return METRIC_MAP.get(metric_id)


SET_ORDINALS = {1: "1-й", 2: "2-й", 3: "3-й", 4: "4-й", 5: "5-й"}


def format_metric_label(metric_id, args=None):
    definition = METRIC_MAP.get(metric_id)
    if not definition:
        return metric_id or "?"
    values = _merge_args(definition, args)
    values["side"] = SIDE_LABELS.get(values.get("side"), values.get("side") or "")
    for key, value in list(values.items()):
        if isinstance(value, float) and abs(value - round(value)) < 0.005:
            values[key] = int(round(value))
    if values.get("threshold") is not None:
        values["threshold"] = _threshold_text(values["threshold"])
    if values.get("set") is not None:
        values["set"] = SET_ORDINALS.get(_to_int(values["set"], 1), values["set"])
    try:
        return definition["label"].format(**values)
    except Exception:
        return definition["label"]


def format_value(value, definition=None):
    if value is None:
        return "—"
    kind = (definition or {}).get("type")
    if kind in ("enum", "string") and isinstance(value, str):
        return ENUM_LABELS.get(value, value)
    if kind == "bool" or isinstance(value, bool):
        return "да" if value else "нет"
    if kind == "number":
        text = _fmt_num(value, 2)
        unit = (definition or {}).get("unit") or ""
        if unit == "%":
            return text + "%"
        return text + ((" " + unit) if unit else "")
    return str(value)


def describe_condition(condition, ctx=None):
    metric_id = condition.get("metric")
    definition = METRIC_MAP.get(metric_id)
    label = format_metric_label(metric_id, condition.get("args"))
    op = condition.get("op", "gt")
    value = condition.get("value")
    value_metric = condition.get("value_metric")
    if op in ("exists", "not_exists"):
        return "%s %s" % (label, "есть" if op == "exists" else "нет")
    if value_metric:
        right = format_metric_label(value_metric, condition.get("value_args"))
    elif op == "between":
        right = "%s…%s" % (format_value(value, definition),
                           format_value(condition.get("value2"), definition))
    elif op in ("in", "not_in") and isinstance(value, (list, tuple)):
        right = ", ".join(format_value(v, definition) for v in value)
    else:
        right = format_value(value, definition)
    if ctx is not None:
        try:
            actual = evaluate_metric(ctx, metric_id, condition.get("args"))
        except Exception:
            actual = None
        left = "%s (= %s)" % (label, format_value(actual, definition))
    else:
        left = label
    return "%s %s %s" % (left, OP_SYMBOLS.get(op, op), right)


def describe_group(group, ctx=None, depth=0):
    if not isinstance(group, dict):
        return ""
    if "metric" in group:
        return describe_condition(group, ctx)
    logic = " И " if group.get("logic", "and") == "and" else " ИЛИ "
    parts = [describe_group(item, ctx, depth + 1)
             for item in group.get("conditions") or []]
    parts = [p for p in parts if p]
    if not parts:
        return "всегда"
    if len(parts) == 1:
        return parts[0]
    text = logic.join(parts)
    return "(%s)" % text if depth > 0 else text


def describe_action(action):
    action = action or {}
    kind = action.get("type", "total")
    if kind == "skip":
        return "пропустить матч"
    targets = action.get("targets") or [1]
    if "auto" in targets:
        target_text = "авто-партия"
    else:
        target_text = ", ".join("%d" % _to_int(t, 1) for t in targets if str(t) != "auto")
        target_text = "партии " + target_text if target_text else "авто-партия"
    side = action.get("side", "auto")
    if kind == "total":
        threshold = _threshold_text(action.get("threshold", 18.5))
        side_text = {"over": "ТБ " + threshold, "under": "ТМ " + threshold,
                     "p1": "ТБ " + threshold, "p2": "ТМ " + threshold,
                     "auto": "ТБ/ТМ " + threshold}.get(side, "ТБ/ТМ " + threshold)
    else:
        side_text = {"p1": "П1", "p2": "П2", "auto": "П1/П2",
                     "over": "П1", "under": "П2"}.get(side, "П1/П2")
    return "%s, %s" % (side_text, target_text)


def describe_rule(rule):
    conditions = rule.get("conditions") or {}
    condition_text = describe_group(conditions)
    return "ЕСЛИ %s → %s" % (condition_text, describe_action(rule.get("action")))


# --------------------------------------------------------------------------
# оценка значений и условий
# --------------------------------------------------------------------------

def evaluate_metric(ctx, metric_id, args=None):
    func = METRIC_FUNCS.get(metric_id)
    if not func:
        return None
    definition = METRIC_MAP.get(metric_id) or {}
    merged = _merge_args(definition, args)
    key = (metric_id, json.dumps(merged, sort_keys=True, ensure_ascii=False))
    if key in ctx._cache:
        return ctx._cache[key]
    try:
        value = func(ctx, merged)
    except Exception:
        value = None
    ctx._cache[key] = value
    return value


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "да", "on")


def compare_values(actual, op, expected, expected2=None, kind="number"):
    if op == "exists":
        return actual is not None
    if op == "not_exists":
        return actual is None
    if actual is None:
        return False

    if kind in ("string", "enum"):
        left = str(actual).strip().lower()
        if op in ("in", "not_in"):
            if isinstance(expected, (list, tuple)):
                values = [str(v).strip().lower() for v in expected]
            else:
                values = [v.strip().lower() for v in str(expected or "").split(",") if v.strip()]
            found = left in values
            return found if op == "in" else not found
        right = str(expected or "").strip().lower()
        if op in ("eq", "is"):
            return left == right
        if op in ("neq", "is_not"):
            return left != right
        if op == "contains":
            return right in left
        if op == "not_contains":
            return right not in left
        if op == "starts_with":
            return left.startswith(right)
        if op == "ends_with":
            return left.endswith(right)
        return False

    if kind == "bool":
        return _as_bool(actual) == _as_bool(expected)

    try:
        left = float(actual)
    except Exception:
        return False
    if op == "between":
        try:
            low, high = float(expected), float(expected2)
        except Exception:
            return False
        if low > high:
            low, high = high, low
        return low <= left <= high
    try:
        right = float(expected)
    except Exception:
        return False
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    if op == "eq":
        return abs(left - right) < 1e-9
    if op == "neq":
        return abs(left - right) >= 1e-9
    return False


def evaluate_condition(ctx, condition):
    metric_id = condition.get("metric")
    definition = METRIC_MAP.get(metric_id)
    if not definition:
        return False, []
    actual = evaluate_metric(ctx, metric_id, condition.get("args"))
    op = condition.get("op", "gt")
    expected = condition.get("value")
    if condition.get("value_metric"):
        expected = evaluate_metric(ctx, condition["value_metric"],
                                   condition.get("value_args"))
        if expected is None and op not in ("exists", "not_exists"):
            return False, []
    matched = compare_values(actual, op, expected, condition.get("value2"),
                             definition.get("type", "number"))
    detail = ""
    if matched:
        detail = "%s (= %s)" % (format_metric_label(metric_id, condition.get("args")),
                                format_value(actual, definition))
        right = format_value(expected, definition)
        if condition.get("value_metric"):
            right = format_metric_label(condition["value_metric"],
                                        condition.get("value_args"))
        if op == "between":
            right = "%s…%s" % (format_value(condition.get("value"), definition),
                               format_value(condition.get("value2"), definition))
        detail += " %s %s" % (OP_SYMBOLS.get(op, op), right)
    return matched, ([detail] if detail else [])


def evaluate_group(ctx, group):
    if not isinstance(group, dict):
        return True, []
    if "metric" in group:
        return evaluate_condition(ctx, group)
    logic = (group.get("logic") or "and").lower()
    conditions = group.get("conditions") or []
    if not conditions:
        return True, []
    details = []
    matches = []
    for item in conditions:
        matched, item_details = evaluate_group(ctx, item)
        matches.append(matched)
        details.extend(item_details)
    result = all(matches) if logic == "and" else any(matches)
    if not result:
        return False, []
    return True, details


# --------------------------------------------------------------------------
# цели и действия
# --------------------------------------------------------------------------

def _set_rate(ctx, set_no, kind, side, threshold):
    """Оценка 0..1 для выбора партии/стороны в режиме «авто»."""
    over = _h2h_over_rate(ctx, {"window": 10, "set": set_no, "threshold": threshold})
    if over is None:
        p1 = _recent_set_over_rate(ctx, {"side": "p1", "window": 5,
                                         "set": set_no, "threshold": threshold})
        p2 = _recent_set_over_rate(ctx, {"side": "p2", "window": 5,
                                         "set": set_no, "threshold": threshold})
        values = [v for v in (p1, p2) if v is not None]
        over = (sum(values) / len(values)) if values else None
    if kind == "winner":
        if side == "p1":
            rate = _h2h_set_win_rate(ctx, {"side": "p1", "window": 10, "set": set_no})
            if rate is None:
                rate = _recent_set_win_rate(ctx, {"side": "p1", "window": 5, "set": set_no})
            return rate
        p1_rate = _set_rate(ctx, set_no, "winner", "p1", threshold)
        return None if p1_rate is None else 100.0 - p1_rate
    if over is None:
        return None
    return over if side == "over" else 100.0 - over


def auto_target(ctx, action):
    kind = action.get("type", "total")
    side = action.get("side", "auto")
    threshold = _to_float(action.get("threshold", 18.5), 18.5)
    if kind == "total":
        if side in ("over", "p1"):
            sides = ["over"]
        elif side in ("under", "p2"):
            sides = ["under"]
        else:
            sides = ["over", "under"]
    else:
        sides = [side] if side in ("p1", "p2") else ["p1", "p2"]
    best_set, best_side, best_rate = 1, sides[0], -1.0
    for set_no in range(1, 6):
        for candidate in sides:
            rate = _set_rate(ctx, set_no, kind, candidate, threshold)
            if rate is not None and rate > best_rate:
                best_set, best_side, best_rate = set_no, candidate, rate
    if kind == "winner" and best_side not in ("p1", "p2"):
        best_side = "p1"
    if kind == "total" and best_side not in ("over", "under"):
        best_side = "over"
    return best_set, best_side


def auto_side(ctx, action, target, threshold):
    kind = action.get("type", "total")
    side = action.get("side", "auto")
    if side in ("p1", "p2", "over", "under"):
        return side
    if kind == "total":
        over = _set_rate(ctx, target, "total", "over", threshold)
        under = _set_rate(ctx, target, "total", "under", threshold)
        if over is None and under is None:
            return "over"
        if under is None:
            return "over"
        if over is None:
            return "under"
        return "over" if over >= under else "under"
    left = _set_rate(ctx, target, "winner", "p1", threshold)
    right = _set_rate(ctx, target, "winner", "p2", threshold)
    if left is None and right is None:
        return "p1"
    if right is None:
        return "p1"
    if left is None:
        return "p2"
    return "p1" if left >= right else "p2"


def build_prediction(rule, action, target, side, ctx, details):
    kind = action.get("type", "total")
    if kind not in ("winner", "total"):
        return None
    threshold = _to_float(action.get("threshold", 18.5), 18.5)
    if side == "auto":
        side = auto_side(ctx, action, target, threshold)
    confidence = _to_float(action.get("confidence"), 0.6)
    confidence = min(0.99, max(0.05, confidence if confidence is not None else 0.6))
    if not confidence:
        confidence = min(0.9, 0.5 + 0.05 * max(1, len(details)))

    label_prefix = "Партия %d" % _to_int(target, 1)
    if kind == "total":
        side = "over" if side in ("over", "p1") else "under"
        text = _threshold_text(threshold)
        verdict = ("ТБ %s" if side == "over" else "ТМ %s") % text
        expected_side = side
        label = "%s (ТБ%s/ТМ%s)" % (label_prefix, text, text)
    else:
        side = "p1" if side in ("p1", "over") else "p2"
        verdict = "П1" if side == "p1" else "П2"
        expected_side = verdict
        threshold = None
        label = "%s (П1/П2)" % label_prefix

    short_details = "; ".join(details[:4])
    if len(details) > 4:
        short_details += "; …"
    models_info = "Конструктор · «%s»" % rule.get("name", "")
    if short_details:
        models_info += ": " + short_details

    return {
        "target": "set%d" % _to_int(target, 1),
        "label": label,
        "kind": kind,
        "expected_side": expected_side,
        "threshold": threshold,
        "verdict": verdict,
        "confidence_val": confidence,
        "min_model_wilson": confidence,
        "strong": max(1, len(details)),
        "agreement": 1.0,
        "models_info": models_info,
        "rule_id": rule.get("id", ""),
        "rule_name": rule.get("name", ""),
        "source": "constructor",
    }


# --------------------------------------------------------------------------
# проверка и нормализация правил
# --------------------------------------------------------------------------

def new_rule(name="Новое правило"):
    return {
        "id": "r_" + uuid.uuid4().hex[:10],
        "name": name,
        "enabled": True,
        "priority": 100,
        "stop": False,
        "conditions": {
            "logic": "and",
            "conditions": [
                {
                    "metric": "p.recent.avg_match_total",
                    "args": {"side": "p1", "window": 5},
                    "op": "gte",
                    "value": 19,
                }
            ],
        },
        "action": {
            "type": "total",
            "targets": [1],
            "side": "over",
            "threshold": 18.5,
            "confidence": 0.6,
        },
    }


# --------------------------------------------------------------------------
# готовые шаблоны правил
#
# Собраны из публичных стратегий и рыночных ориентиров настольного тенниса:
#   * Beting Rating, «Total in Table Tennis» — линия 18.5 на партию,
#     75.5 на матч из 4 партий, стратегии «ТБ 18.5 в партии», «ТБ 3.5 /
#     ТМ 4.5 партии», высокий индивидуальный тотал фаворита;
#   * DeuceLab, «Table Tennis Betting Markets» — около двух третей матчей
#     проходят дальше трёх партий, чем ровнее матч, тем длиннее;
#   * PingPongBets, «Over/Under in Table Tennis» — агрессивная манера игры
#     даёт высокие тоталы, защитная — низкие; формат матча влияет на тотал;
#   * SmartBettingGuide, «Table Tennis Betting Strategy» — форма, очные
#     встречи, усталость от плотного графика и переездов;
#   * Table Tennis Totals — ориентация на статистику ТБ/ТМ и sweep%.
#
# Это стартовые точки, а не гарантия прибыли: проверяйте их кнопкой
# «Тест на линии», а затем анализатором на своей истории прогнозов.
# --------------------------------------------------------------------------

SRC_BR = "Beting Rating · Total in Table Tennis"
SRC_PP = "PingPongBets · Over/Under в настольном теннисе"
SRC_DL = "DeuceLab · рынки настольного тенниса"
SRC_SBG = "SmartBettingGuide · стратегия на настольный теннис"
SRC_TTT = "Table Tennis Totals · гайд по тоталам"
SRC_PAGE = "Betcity · тоталы со страницы статистики"


def _cond(metric, op, value, **args):
    return {"metric": metric, "args": args, "op": op, "value": value}


def _total(side, threshold, targets, confidence=0.6):
    return {"type": "total", "targets": targets, "side": side,
            "threshold": threshold, "confidence": confidence}


def _winner(side, targets, confidence=0.6):
    return {"type": "winner", "targets": targets, "side": side,
            "threshold": 18.5, "confidence": confidence}


def _skip():
    return {"type": "skip", "targets": [1], "side": "auto",
            "threshold": 18.5, "confidence": 0.6}


def _preset(name, category, description, source, conditions, action,
            logic="and"):
    return {
        "name": name,
        "category": category,
        "description": description,
        "source": source,
        "rule": {
            "name": name,
            "conditions": {"logic": logic, "conditions": conditions},
            "action": action,
        },
    }


PRESETS = [
    # ------------------------------------------------------------- тоталы
    _preset(
        "ТБ 18.5: средний тотал обоих ≥ 19",
        "Тоталы",
        "Средний тотал партии по последним 5 играм обоих игроков не ниже "
        "19 — классический ориентир линии ТБ 18.5. Берём 1-ю партию.",
        SRC_BR,
        [_cond("cmp.avg_set_total_mean", "gte", 19, window=5)],
        _total("over", 18.5, [1], 0.6),
    ),
    _preset(
        "ТБ 18.5: оба верховые",
        "Тоталы",
        "У каждого игрока ТБ 18.5 в партиях за последние 5 игр проходит "
        "минимум в 60% случаев — агрессивная манера даёт высокие тоталы.",
        SRC_PP,
        [_cond("p.recent.over_rate", "gte", 60,
               side="p1", window=5, threshold=18.5),
         _cond("p.recent.over_rate", "gte", 60,
               side="p2", window=5, threshold=18.5)],
        _total("over", 18.5, [1, 2], 0.62),
    ),
    _preset(
        "ТБ 18.5: очные верховые",
        "Тоталы",
        "В 7 из 10 очных встреч 1-я партия была ТБ 18.5 и очных не меньше "
        "пяти — соперники исторически играют верховые партии.",
        SRC_TTT,
        [_cond("h2h.over_rate", "gte", 70,
               window=10, set=1, threshold=18.5),
         _cond("h2h.count", "gte", 5)],
        _total("over", 18.5, [1], 0.64),
    ),
    _preset(
        "ТБ 18.5: средний тотал очных ≥ 19",
        "Тоталы",
        "Средний тотал партии в очных встречах не ниже 19 при минимум "
        "четырёх встречах — история противостояния верхушечная.",
        SRC_BR,
        [_cond("h2h.avg_set_total", "gte", 19, window=10, set=1),
         _cond("h2h.count", "gte", 4)],
        _total("over", 18.5, [1], 0.62),
    ),
    _preset(
        "ТБ 18.5: линия 75.5 и ТБ в 4 из 5",
        "Тоталы",
        "Линия матча 75.5 и больше и в последних 5 играх ТБ линии "
        "проходил минимум 4 раза. Ориентир Betcity по тоталам страницы.",
        SRC_PAGE,
        [_cond("page.over_last5", "gte", 4),
         _cond("page.total_line", "gte", 75.5)],
        _total("over", 18.5, [1, 2], 0.6),
    ),
    _preset(
        "ТБ 18.5: очные за 5 партий",
        "Тоталы",
        "Больше половины очных матчей доходили до 5 партий, а средний "
        "тотал партии не ниже 18 — длинные матчи дают больше очков.",
        SRC_DL,
        [_cond("h2h.five_set_rate", "gte", 60, window=10),
         _cond("h2h.avg_set_total", "gte", 18, window=10, set=1)],
        _total("over", 18.5, [1, 2], 0.58),
    ),
    _preset(
        "ТБ 19.5: сумма тоталов матчей ≥ 78",
        "Тоталы",
        "Сумма средних тоталов матчей обоих игроков за 5 игр не ниже 78: "
        "матч обещает быть результативным, берём повышенный тотал партии.",
        SRC_BR,
        [_cond("cmp.avg_total_sum", "gte", 78, window=5)],
        _total("over", 19.5, [1], 0.58),
    ),
    _preset(
        "ТБ 18.5: тренд тотала растёт",
        "Тоталы",
        "У обоих игроков свежие игры результативнее старых (тренд +2 очка), "
        "а средний тотал партии уже не ниже 18.",
        SRC_TTT,
        [_cond("p.recent.trend_total", "gte", 2, side="p1", window=5),
         _cond("p.recent.trend_total", "gte", 2, side="p2", window=5),
         _cond("p.recent.avg_set_total", "gte", 18, side="p1", window=5)],
        _total("over", 18.5, [1, 2], 0.58),
    ),
    _preset(
        "ТМ 18.5: оба низовые",
        "Тоталы",
        "У обоих ТБ 18.5 в партиях проходит не чаще 30% игр — защитная "
        "манера и осторожный старт дают низкие тоталы.",
        SRC_PP,
        [_cond("p.recent.over_rate", "lte", 30,
               side="p1", window=5, threshold=18.5),
         _cond("p.recent.over_rate", "lte", 30,
               side="p2", window=5, threshold=18.5)],
        _total("under", 18.5, [1, 2], 0.6),
    ),
    _preset(
        "ТМ 18.5: очные низкие",
        "Тоталы",
        "Средний тотал партии в очных не выше 17, а ТБ 18.5 проходил "
        "не более чем в 30% партий при минимум 4 встречах.",
        SRC_TTT,
        [_cond("h2h.avg_set_total", "lte", 17, window=10, set=1),
         _cond("h2h.over_rate", "lte", 30,
               window=10, set=1, threshold=18.5),
         _cond("h2h.count", "gte", 4)],
        _total("under", 18.5, [1], 0.62),
    ),
    _preset(
        "ТМ 18.5: средний тотал обоих ≤ 17",
        "Тоталы",
        "Даже больший из двух средних тоталов партии не выше 17 — оба "
        "игрока стабильно играют низовые партии.",
        SRC_BR,
        [_cond("cmp.avg_set_total_max", "lte", 17, window=5)],
        _total("under", 18.5, [1, 2], 0.6),
    ),
    _preset(
        "ТБ 18.5 в 1-й: оба сильно стартуют",
        "Тоталы",
        "Средний тотал именно 1-й партии у обоих не ниже 19 за последние "
        "5 игр — оба входят в матч агрессивно.",
        SRC_PP,
        [_cond("p.recent.set_avg_total", "gte", 19,
               side="p1", window=5, set=1),
         _cond("p.recent.set_avg_total", "gte", 19,
               side="p2", window=5, set=1)],
        _total("over", 18.5, [1], 0.6),
    ),
    _preset(
        "ТМ 18.5 в 1-й: оба осторожны",
        "Тоталы",
        "Средний тотал 1-й партии у обоих не выше 16 за последние 5 игр — "
        "оба долго входят в матч.",
        SRC_PP,
        [_cond("p.recent.set_avg_total", "lte", 16,
               side="p1", window=5, set=1),
         _cond("p.recent.set_avg_total", "lte", 16,
               side="p2", window=5, set=1)],
        _total("under", 18.5, [1], 0.6),
    ),
    _preset(
        "ТБ 18.5: верховой фаворит",
        "Тоталы",
        "Букмекерский фаворит — игрок 1, и его средний тотал партии за "
        "5 игр не ниже 20: сильный игрок много забивает даже в коротких "
        "партиях.",
        SRC_BR,
        [_cond("odds.favorite", "eq", "p1"),
         _cond("p.recent.avg_set_total", "gte", 20, side="p1", window=5)],
        _total("over", 18.5, [1, 2], 0.6),
    ),
    _preset(
        "ТМ 18.5: низовой фаворит",
        "Тоталы",
        "Фаворит — игрок 1, но сам играет низовые партии (средний тотал "
        "≤ 17), а у соперника ТБ 18.5 редок.",
        SRC_BR,
        [_cond("odds.favorite", "eq", "p1"),
         _cond("p.recent.avg_set_total", "lte", 17, side="p1", window=5),
         _cond("p.recent.over_rate", "lte", 35,
               side="p2", window=5, threshold=18.5)],
        _total("under", 18.5, [1], 0.58),
    ),

    # --------------------------------------------------------- победитель
    _preset(
        "П1: форма + серия",
        "Победитель",
        "Игрок 1 берёт минимум 60% последних 5 игр и идёт на серии из "
        "2+ побед — форма и уверенность на его стороне.",
        SRC_SBG,
        [_cond("p.recent.win_rate", "gte", 60, side="p1", window=5),
         _cond("p.recent.streak", "gte", 2, side="p1")],
        _winner("p1", [1], 0.6),
    ),
    _preset(
        "П2: форма + серия",
        "Победитель",
        "Зеркальный шаблон: игрок 2 берёт минимум 60% последних 5 игр и "
        "идёт на серии из 2+ побед.",
        SRC_SBG,
        [_cond("p.recent.win_rate", "gte", 60, side="p2", window=5),
         _cond("p.recent.streak", "gte", 2, side="p2")],
        _winner("p2", [1], 0.6),
    ),
    _preset(
        "П1: очное доминирование",
        "Победитель",
        "Игрок 1 выиграл минимум 60% очных встреч при их количестве "
        "не меньше пяти — стилистически удобный соперник.",
        SRC_TTT,
        [_cond("h2h.win_rate", "gte", 60, side="p1", window=10),
         _cond("h2h.count", "gte", 5)],
        _winner("p1", [1], 0.62),
    ),
    _preset(
        "П2: очное доминирование",
        "Победитель",
        "Игрок 2 выиграл минимум 60% очных встреч при их количестве "
        "не меньше пяти.",
        SRC_TTT,
        [_cond("h2h.win_rate", "gte", 60, side="p2", window=10),
         _cond("h2h.count", "gte", 5)],
        _winner("p2", [1], 0.62),
    ),
    _preset(
        "П1: последняя очная + форма",
        "Победитель",
        "Последнюю очную встречу выиграл игрок 1, и он же берёт минимум "
        "половину последних игр — свежий психологический перевес.",
        SRC_SBG,
        [_cond("h2h.last_winner", "eq", "p1"),
         _cond("p.recent.win_rate", "gte", 50, side="p1", window=5)],
        _winner("p1", [1], 0.58),
    ),
    _preset(
        "П2: последняя очная + форма",
        "Победитель",
        "Последнюю очную встречу выиграл игрок 2, и он же берёт минимум "
        "половину последних игр.",
        SRC_SBG,
        [_cond("h2h.last_winner", "eq", "p2"),
         _cond("p.recent.win_rate", "gte", 50, side="p2", window=5)],
        _winner("p2", [1], 0.58),
    ),
    _preset(
        "П1: фаворит 1.30–1.80",
        "Победитель",
        "Игрок 1 — фаворит букмекера, но кэф не ниже 1.30 и не выше 1.80: "
        "достаточно уверенно, но без «мертвой» цены. Две первые партии.",
        SRC_SBG,
        [_cond("odds.favorite", "eq", "p1"),
         _cond("odds.p1", "gte", 1.3),
         _cond("odds.p1", "lte", 1.8)],
        _winner("p1", [1, 2], 0.6),
    ),
    _preset(
        "П2: фаворит 1.30–1.80",
        "Победитель",
        "Игрок 2 — фаворит букмекера с кэфом в коридоре 1.30–1.80. "
        "Две первые партии.",
        SRC_SBG,
        [_cond("odds.favorite", "eq", "p2"),
         _cond("odds.p2", "gte", 1.3),
         _cond("odds.p2", "lte", 1.8)],
        _winner("p2", [1, 2], 0.6),
    ),
    _preset(
        "П1: разница побед ≥ 30 п.п.",
        "Победитель",
        "За последние 5 игр игрок 1 выигрывает на 30 процентных пунктов "
        "чаще игрока 2 — заметный разрыв в форме.",
        SRC_SBG,
        [_cond("cmp.win_rate_diff", "gte", 30, window=5)],
        _winner("p1", [1], 0.6),
    ),
    _preset(
        "П2: разница побед ≥ 30 п.п.",
        "Победитель",
        "За последние 5 игр игрок 2 выигрывает на 30 процентных пунктов "
        "чаще игрока 1.",
        SRC_SBG,
        [_cond("cmp.win_rate_diff", "lte", -30, window=5)],
        _winner("p2", [1], 0.6),
    ),
    _preset(
        "П1: серия в очных ≥ 3",
        "Победитель",
        "Игрок 1 выиграл три очные встречи подряд и очных набралось "
        "минимум пять — устойчивое преимущество в паре.",
        SRC_TTT,
        [_cond("h2h.streak", "gte", 3, side="p1"),
         _cond("h2h.count", "gte", 5)],
        _winner("p1", [1], 0.62),
    ),
    _preset(
        "П1: сильнее в 1-й партии",
        "Победитель",
        "Игрок 1 берёт 70%+ первых партий за 5 игр, а игрок 2 — не более "
        "40%: быстрый старт решает первую партию.",
        SRC_TTT,
        [_cond("p.recent.first_set_win_rate", "gte", 70,
               side="p1", window=5),
         _cond("p.recent.first_set_win_rate", "lte", 40,
               side="p2", window=5)],
        _winner("p1", [1], 0.62),
    ),
    _preset(
        "П2: сильнее в 1-й партии",
        "Победитель",
        "Игрок 2 берёт 70%+ первых партий за 5 игр, а игрок 1 — не более "
        "40%.",
        SRC_TTT,
        [_cond("p.recent.first_set_win_rate", "gte", 70,
               side="p2", window=5),
         _cond("p.recent.first_set_win_rate", "lte", 40,
               side="p1", window=5)],
        _winner("p2", [1], 0.62),
    ),
    _preset(
        "П1: явный фаворит на две партии",
        "Победитель",
        "Кэф на игрока 1 не выше 1.50 и разрыв в проценте побед не меньше "
        "40 п.п. — берём П1 в первых двух партиях.",
        SRC_BR,
        [_cond("odds.p1", "lte", 1.5),
         _cond("cmp.win_rate_diff", "gte", 40, window=5)],
        _winner("p1", [1, 2], 0.58),
    ),
    _preset(
        "П2: явный фаворит на две партии",
        "Победитель",
        "Кэф на игрока 2 не выше 1.50 и разрыв в проценте побед не меньше "
        "40 п.п. — берём П2 в первых двух партиях.",
        SRC_BR,
        [_cond("odds.p2", "lte", 1.5),
         _cond("cmp.win_rate_diff", "lte", -40, window=5)],
        _winner("p2", [1, 2], 0.58),
    ),

    # ------------------------------------------------------------ фильтры
    _preset(
        "Пропуск: мало очных",
        "Фильтры",
        "Меньше трёх очных встреч — статистике противостояния нельзя "
        "доверять, правило-фильтр пропускает такой матч.",
        SRC_TTT,
        [_cond("h2h.count", "lt", 3)],
        _skip(),
    ),
    _preset(
        "Пропуск: нет коэффициентов",
        "Фильтры",
        "Коэффициенты недоступны — нельзя проверить ценность ставки.",
        SRC_SBG,
        [_cond("odds.available", "is", False)],
        _skip(),
    ),
    _preset(
        "Пропуск: кэф ниже 1.35",
        "Фильтры",
        "Кэф на любого игрока ниже 1.35: цена не оправдывает риск даже "
        "при верном исходе.",
        SRC_SBG,
        [_cond("odds.p1", "lt", 1.35),
         _cond("odds.p2", "lt", 1.35)],
        _skip(),
        logic="or",
    ),
    _preset(
        "Пропуск: разрыв кэфов ≥ 4",
        "Фильтры",
        "Отношение коэффициентов P1/P2 больше 4 или меньше 0.25 — слишком "
        "большая разница в классе, рынок уже всё учёл.",
        SRC_SBG,
        [_cond("odds.ratio", "gte", 4),
         _cond("odds.ratio", "lte", 0.25)],
        _skip(),
        logic="or",
    ),
    _preset(
        "Пропуск: мало последних игр",
        "Фильтры",
        "У любого из игроков меньше трёх разобранных последних игр — "
        "форма неизвестна, статистика ненадёжна.",
        SRC_SBG,
        [_cond("p.recent.count", "lt", 3, side="p1", window=5),
         _cond("p.recent.count", "lt", 3, side="p2", window=5)],
        _skip(),
        logic="or",
    ),
    _preset(
        "Пропуск: перегруз играми",
        "Фильтры",
        "У любого из игроков 15+ матчей за 7 дней — усталость и переезды "
        "снижают качество игры, тоталы и исходы плывут.",
        SRC_SBG,
        [_cond("p.recent.matches_last_7d", "gte", 15, side="p1", window=10),
         _cond("p.recent.matches_last_7d", "gte", 15, side="p2", window=10)],
        _skip(),
        logic="or",
    ),
    _preset(
        "Пропуск: простой ≥ 30 дней",
        "Фильтры",
        "Любой игрок не играл 30+ дней — форма после простоя "
        "непредсказуема.",
        SRC_SBG,
        [_cond("p.recent.days_since_last", "gte", 30, side="p1"),
         _cond("p.recent.days_since_last", "gte", 30, side="p2")],
        _skip(),
        logic="or",
    ),
    _preset(
        "Пропуск: матч уже начался",
        "Фильтры",
        "Страховка от запоздалого сигнала: если матч уже стартовал, "
        "ставка не отправляется.",
        SRC_SBG,
        [_cond("match.started", "is", True)],
        _skip(),
    ),

    # ----------------------------------------------------- комбинированные
    _preset(
        "ТБ 18.5: равные соперники + верховые",
        "Комбинированные",
        "Разница в проценте побед в пределах ±15 п.п., а средний тотал "
        "партии обоих не ниже 18.5 — ровные матчи чаще идут в затяжные "
        "партии.",
        SRC_DL,
        [_cond("cmp.win_rate_diff", "gte", -15, window=5),
         _cond("cmp.win_rate_diff", "lte", 15, window=5),
         _cond("cmp.avg_set_total_mean", "gte", 18.5, window=5)],
        _total("over", 18.5, [1, 2], 0.6),
    ),
    _preset(
        "П1: форма + очные + кэф",
        "Комбинированные",
        "Три независимых подтверждения: 60%+ побед за 5 игр, 55%+ в очных "
        "и кэф не выше 1.90.",
        SRC_SBG,
        [_cond("p.recent.win_rate", "gte", 60, side="p1", window=5),
         _cond("h2h.win_rate", "gte", 55, side="p1", window=10),
         _cond("odds.p1", "lte", 1.9)],
        _winner("p1", [1], 0.62),
    ),
    _preset(
        "П2: форма + очные + кэф",
        "Комбинированные",
        "Три независимых подтверждения: 60%+ побед за 5 игр, 55%+ в очных "
        "и кэф не выше 1.90.",
        SRC_SBG,
        [_cond("p.recent.win_rate", "gte", 60, side="p2", window=5),
         _cond("h2h.win_rate", "gte", 55, side="p2", window=10),
         _cond("odds.p2", "lte", 1.9)],
        _winner("p2", [1], 0.62),
    ),
    _preset(
        "ТБ 18.5: обе верховые + очные",
        "Комбинированные",
        "У обоих ТБ 18.5 проходит хотя бы в половине партий, и очные "
        "подтверждают верховой сценарий.",
        SRC_TTT,
        [_cond("p.recent.over_rate", "gte", 50,
               side="p1", window=5, threshold=18.5),
         _cond("p.recent.over_rate", "gte", 50,
               side="p2", window=5, threshold=18.5),
         _cond("h2h.over_rate", "gte", 50,
               window=10, set=1, threshold=18.5)],
        _total("over", 18.5, [1, 2], 0.62),
    ),
    _preset(
        "ТМ 18.5: обе низовые + очные",
        "Комбинированные",
        "У обоих ТБ 18.5 проходит не чаще 35% партий, и средний тотал "
        "очных ниже 17.5 — низовой сценарий подтверждён дважды.",
        SRC_TTT,
        [_cond("p.recent.over_rate", "lte", 35,
               side="p1", window=5, threshold=18.5),
         _cond("p.recent.over_rate", "lte", 35,
               side="p2", window=5, threshold=18.5),
         _cond("h2h.avg_set_total", "lte", 17.5, window=10, set=1)],
        _total("under", 18.5, [1, 2], 0.6),
    ),
    _preset(
        "П1: последняя игра + очная серия",
        "Комбинированные",
        "Игрок 1 выиграл последнюю игру и минимум две очные встречи "
        "подряд — свежая форма совпала с удобным соперником.",
        SRC_SBG,
        [_cond("p.recent.last_result", "eq", "win", side="p1"),
         _cond("h2h.streak", "gte", 2, side="p1")],
        _winner("p1", [1], 0.6),
    ),
    _preset(
        "П2: последняя игра + очная серия",
        "Комбинированные",
        "Игрок 2 выиграл последнюю игру и минимум две очные встречи "
        "подряд.",
        SRC_SBG,
        [_cond("p.recent.last_result", "eq", "win", side="p2"),
         _cond("h2h.streak", "gte", 2, side="p2")],
        _winner("p2", [1], 0.6),
    ),
    _preset(
        "ТБ 18.5: 5-сетовые очные + равная форма",
        "Комбинированные",
        "Половина очных доходила до 5 партий, форма игроков ровная "
        "(±20 п.п.), а средний тотал партии не ниже 18.5.",
        SRC_DL,
        [_cond("h2h.five_set_rate", "gte", 50, window=10),
         _cond("cmp.win_rate_diff", "gte", -20, window=5),
         _cond("cmp.win_rate_diff", "lte", 20, window=5),
         _cond("cmp.avg_set_total_mean", "gte", 18.5, window=5)],
        _total("over", 18.5, [1, 2], 0.6),
    ),
]


def _clean_rule(rule, index=1, errors=None):
    errors = errors if errors is not None else []
    if not isinstance(rule, dict):
        errors.append("Правило №%d: ожидался объект" % index)
        return None
    name = str(rule.get("name") or "").strip() or ("Правило %d" % index)
    action = rule.get("action") or {}
    if not isinstance(action, dict):
        errors.append("«%s»: действие должно быть объектом" % name)
        action = {}
    kind = str(action.get("type") or "total").lower()
    if kind not in ("winner", "total", "skip"):
        errors.append("«%s»: неизвестное действие «%s»" % (name, kind))
        kind = "total"
    targets = action.get("targets")
    if not isinstance(targets, list) or not targets:
        targets = [1]
    cleaned_targets = []
    for target in targets:
        if str(target).lower() == "auto":
            cleaned_targets.append("auto")
        else:
            number = _to_int(target, 1)
            if 1 <= number <= 5:
                cleaned_targets.append(number)
    if not cleaned_targets:
        cleaned_targets = [1]
    if "auto" in cleaned_targets:
        cleaned_targets = ["auto"]
    side = str(action.get("side") or "auto").lower()
    if kind == "winner" and side not in ("auto", "p1", "p2", "over", "under"):
        side = "auto"
    if kind == "total" and side not in ("auto", "over", "under", "p1", "p2"):
        side = "auto"
    threshold = _to_float(action.get("threshold", 18.5), 18.5)
    threshold = min(100.0, max(0.0, threshold))
    confidence = _to_float(action.get("confidence", 0.6), 0.6)
    confidence = min(0.99, max(0.05, confidence))

    conditions = rule.get("conditions") or {}
    conditions = _clean_group(conditions, name, errors, depth=0)

    return {
        "id": str(rule.get("id") or ("r_" + uuid.uuid4().hex[:10])),
        "name": name,
        "enabled": bool(rule.get("enabled", True)),
        "priority": _to_int(rule.get("priority", 100), 100),
        "stop": bool(rule.get("stop", False)),
        "conditions": conditions,
        "action": {
            "type": kind,
            "targets": cleaned_targets,
            "side": side,
            "threshold": threshold,
            "confidence": confidence,
        },
    }


def _clean_group(group, rule_name, errors, depth=0):
    if depth > 6:
        errors.append("«%s»: слишком глубокая вложенность условий" % rule_name)
        return {"logic": "and", "conditions": []}
    if not isinstance(group, dict):
        errors.append("«%s»: группа условий должна быть объектом" % rule_name)
        return {"logic": "and", "conditions": []}
    if "metric" in group:
        cleaned = _clean_condition(group, rule_name, errors)
        return cleaned if cleaned else {"logic": "and", "conditions": []}
    logic = "or" if str(group.get("logic", "and")).lower() == "or" else "and"
    items = group.get("conditions")
    if not isinstance(items, list):
        items = []
    cleaned_items = []
    for item in items[:50]:
        if not isinstance(item, dict):
            continue
        if "metric" in item:
            cleaned = _clean_condition(item, rule_name, errors)
            if cleaned:
                cleaned_items.append(cleaned)
        else:
            cleaned = _clean_group(item, rule_name, errors, depth + 1)
            if cleaned.get("conditions"):
                cleaned_items.append(cleaned)
    return {"logic": logic, "conditions": cleaned_items}


def _clean_condition(condition, rule_name, errors):
    metric_id = condition.get("metric")
    definition = METRIC_MAP.get(metric_id)
    if not definition:
        errors.append("«%s»: неизвестная метрика «%s»" % (rule_name, metric_id))
        return None
    args = condition.get("args")
    if not isinstance(args, dict):
        args = {}
    merged_args = _merge_args(definition, args)
    # нормализуем аргументы
    for arg_name in (definition.get("args") or {}):
        arg_def = ARG_DEFS.get(arg_name) or {}
        if arg_def.get("kind") == "number":
            if arg_name == "window":
                merged_args[arg_name] = max(1, _to_int(
                    merged_args.get(arg_name), arg_def.get("default", 5)))
            else:
                merged_args[arg_name] = _to_float(
                    merged_args.get(arg_name), arg_def.get("default", 0))
        elif arg_def.get("kind") == "select" and arg_name == "side":
            if merged_args.get(arg_name) not in ("p1", "p2"):
                merged_args[arg_name] = "p1"
        elif arg_name == "set":
            merged_args[arg_name] = min(5, max(1, _to_int(
                merged_args.get(arg_name), 1)))
    kind = definition.get("type", "number")
    allowed = [op[0] for op in OPERATORS.get(kind, OPERATORS["number"])]
    op = str(condition.get("op") or "gt").lower()
    if op not in allowed:
        op = "gt"
    value = condition.get("value")
    if op in ("in", "not_in") and isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    if kind == "number" and op not in ("exists", "not_exists", "between"):
        value = _to_float(value, 0)
    if op == "between":
        value = _to_float(value, 0)
    value_metric = condition.get("value_metric")
    if value_metric and value_metric not in METRIC_MAP:
        value_metric = None
    value_args = condition.get("value_args")
    if not isinstance(value_args, dict):
        value_args = {}
    cleaned = {
        "metric": metric_id,
        "args": merged_args,
        "op": op,
        "value": value,
    }
    if op == "between":
        cleaned["value2"] = _to_float(condition.get("value2"), 0)
    if value_metric:
        cleaned["value_metric"] = value_metric
        cleaned["value_args"] = value_args
    return cleaned


# --------------------------------------------------------------------------
# движок
# --------------------------------------------------------------------------

class ConstructorEngine:
    def __init__(self, path, settings=None, logger=None):
        self.path = path
        self.settings = settings
        self.logger = logger
        self._lock = threading.RLock()
        self._stats = {"matches": 0, "fired": 0, "skipped": 0, "rules": 0}
        self.rules = self._load()

    # ---------- хранение ----------
    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                rules = payload.get("rules") if isinstance(payload, dict) else payload
                if isinstance(rules, list):
                    cleaned = []
                    for index, rule in enumerate(rules, 1):
                        errors = []
                        item = _clean_rule(rule, index, errors)
                        if item:
                            cleaned.append(item)
                    return cleaned
        except Exception as exc:
            if self.logger:
                self.logger.error("Конструктор: не удалось загрузить правила: %s", exc)
        return []

    def _save_file(self, rules):
        payload = {"version": VERSION, "rules": rules}
        try:
            directory = os.path.dirname(self.path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception as exc:
            if self.logger:
                self.logger.error("Конструктор: не удалось сохранить правила: %s", exc)
            return False

    def reload(self):
        with self._lock:
            self.rules = self._load()
        return self.rules

    def save(self, payload):
        rules = payload.get("rules") if isinstance(payload, dict) else payload
        if not isinstance(rules, list):
            return False, ["Ожидался список правил"], self.snapshot()
        errors = []
        cleaned = []
        if len(rules) > 200:
            errors.append("Слишком много правил (максимум 200)")
            rules = rules[:200]
        for index, rule in enumerate(rules, 1):
            item = _clean_rule(rule, index, errors)
            if item:
                cleaned.append(item)
        if errors:
            return False, errors, self.snapshot()
        with self._lock:
            ok = self._save_file(cleaned)
            if ok:
                self.rules = cleaned
        return ok, ([] if ok else ["Не удалось записать файл правил"]), self.snapshot()

    def set_rules(self, rules):
        ok, errors, _ = self.save({"rules": rules})
        return ok, errors

    # ---------- выдача для UI ----------
    def snapshot(self):
        with self._lock:
            rules = json.loads(json.dumps(self.rules))
        for index, rule in enumerate(rules, 1):
            rule["index"] = index
            rule["summary"] = describe_rule(rule)
            rule["conditions_text"] = describe_group(rule.get("conditions"))
            rule["action_text"] = describe_action(rule.get("action"))
        return rules

    def catalog_payload(self):
        metrics = []
        for item in METRICS:
            entry = dict(item)
            if item.get("type") == "enum":
                entry["options"] = ENUM_OPTIONS.get(item["id"], [])
            metrics.append(entry)
        return {
            "metrics": metrics,
            "args": ARG_DEFS,
            "operators": OPERATORS,
            "enum_labels": ENUM_LABELS,
            "side_labels": SIDE_LABELS,
        }

    def presets(self):
        return json.loads(json.dumps(PRESETS))

    def stats_payload(self):
        with self._lock:
            data = dict(self._stats)
            data["rules"] = len([r for r in self.rules if r.get("enabled")])
        return data

    def reset_stats(self):
        with self._lock:
            for key in ("matches", "fired", "skipped"):
                self._stats[key] = 0

    # ---------- оценка ----------
    def evaluate(self, match, stats, rules=None):
        """Возвращает (predictions, fired_rules, skip_info)."""
        with self._lock:
            source = rules if rules is not None else self.rules
            ordered = json.loads(json.dumps(source))
        ordered = [r for r in ordered if r.get("enabled", True)]
        ordered.sort(key=lambda r: -_to_int(r.get("priority", 100), 100))

        ctx = Context(match, stats)
        predictions = []
        fired = []
        skip_info = None

        for rule in ordered:
            ok, details = evaluate_group(ctx, rule.get("conditions") or {})
            if not ok:
                continue
            fired.append({
                "id": rule.get("id", ""),
                "name": rule.get("name", ""),
                "details": details[:6],
            })
            action = rule.get("action") or {}
            if action.get("type") == "skip":
                skip_info = {"rule": rule.get("name", ""), "id": rule.get("id", ""),
                             "details": details[:6]}
                predictions = []
                break
            targets = action.get("targets") or [1]
            if "auto" in targets or not targets:
                target, side = auto_target(ctx, action)
                predictions.append(
                    build_prediction(rule, action, target, side, ctx, details))
            else:
                for target in targets:
                    number = _to_int(target, 1)
                    if not 1 <= number <= 5:
                        continue
                    predictions.append(
                        build_prediction(rule, action, number, "auto", ctx, details))
            if rule.get("stop"):
                break

        best = {}
        for prediction in predictions:
            if not prediction:
                continue
            key = (prediction["target"], prediction["kind"])
            previous = best.get(key)
            if previous is None or \
                    prediction["confidence_val"] > previous["confidence_val"]:
                best[key] = prediction
        result = sorted(best.values(), key=lambda p: (p["target"], p["kind"]))

        with self._lock:
            self._stats["matches"] += 1
            self._stats["fired"] += len(fired)
            if skip_info:
                self._stats["skipped"] += 1
        return result, fired, skip_info


# --------------------------------------------------------------------------
# вспомогательное для API
# --------------------------------------------------------------------------

def rules_to_public(rules):
    return json.loads(json.dumps(rules))

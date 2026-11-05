# -*- coding: utf-8 -*-
"""Справочник видов спорта Betcity.

Модуль не зависит от движка: здесь только метаданные видов спорта, рынки,
правила разбора счёта и вспомогательные подписи. Его используют
predictor_core (линия, статистика, проверка результатов) и
constructor_engine (каталог метрик, действия правил, шаблоны).

Счёт на страницах Betcity устроен одинаково для всех видов спорта:

    футбол     3:2 (2:1)                 — матч и первый тайм
    хоккей     4:6 (2:4, 0:1, 2:1)        — матч и периоды
    баскетбол  89:99 (22:18, 17:25, ...)  — матч и четверти
    волейбол   3:1 (25:18, 21:25, ...)    — партии и очки в партиях
    теннис     2:0 (7:6, 7:5)             — сеты и геймы в сетах
    наст. теннис 3:2 (11:9, 9:11, ...)    — партии и очки в партиях

Поэтому разбор вынесен в один общий модуль: профиль вида спорта определяет,
что считать итогом матча, а что — периодами/партиями/сетами.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# каталог
# --------------------------------------------------------------------------

SPORTS = {
    "table_tennis": {
        "id": "table_tennis",
        "betcity_id": "46",
        "name": "Настольный теннис",
        "short": "Наст. теннис",
        "icon": "🏓",
        "score_mode": "sets",       # first pair = sets won, rest = points
        "has_draw": False,
        "periods": 7,
        "period_word": "Партия",
        "period_word_one": "партия",
        "period_word_many": "партий",
        "period_total_step": 0.5,
        "default_total": 18.5,       # тотал партии
        "match_total": 75.5,         # тотал матча
        "bets": ["winner2", "total"],
        "period_markets": True,
        "margin": 1.5,
        "source": "Beting Rating · Total in Table Tennis",
    },
    "football": {
        "id": "football",
        "betcity_id": "1",
        "name": "Футбол",
        "short": "Футбол",
        "icon": "⚽",
        "score_mode": "single",      # first pair = match, rest = halves
        "has_draw": True,
        "periods": 2,
        "period_word": "Тайм",
        "period_word_one": "тайм",
        "period_word_many": "таймов",
        "period_total_step": 0.5,
        "default_total": 2.5,
        "match_total": 2.5,
        "bets": ["winner3", "total", "handicap", "btts"],
        "period_markets": False,
        "margin": 0.4,
        "source": "Betcity · футбольная линия и статистика",
    },
    "hockey": {
        "id": "hockey",
        "betcity_id": "7",
        "name": "Хоккей",
        "short": "Хоккей",
        "icon": "🏒",
        "score_mode": "periods",     # first pair = match, rest = periods
        "has_draw": True,
        "periods": 3,
        "period_word": "Период",
        "period_word_one": "период",
        "period_word_many": "периодов",
        "period_total_step": 0.5,
        "default_total": 5.5,
        "match_total": 5.5,
        "bets": ["winner3", "total", "handicap", "btts"],
        "period_markets": True,
        "margin": 0.8,
        "source": "Betcity · хоккейная линия и статистика",
    },
    "basketball": {
        "id": "basketball",
        "betcity_id": "3",
        "name": "Баскетбол",
        "short": "Баскетбол",
        "icon": "🏀",
        "score_mode": "periods",     # first pair = match, rest = quarters
        "has_draw": False,
        "periods": 4,
        "period_word": "Четверть",
        "period_word_one": "четверть",
        "period_word_many": "четвертей",
        "period_total_step": 1.0,
        "default_total": 160.5,
        "match_total": 160.5,
        "bets": ["winner2", "total", "handicap"],
        "period_markets": True,
        "margin": 6.0,
        "source": "Betcity · баскетбольная линия и статистика",
    },
    "volleyball": {
        "id": "volleyball",
        "betcity_id": "12",
        "name": "Волейбол",
        "short": "Волейбол",
        "icon": "🏐",
        "score_mode": "sets",        # first pair = sets won, rest = points
        "has_draw": False,
        "periods": 5,
        "period_word": "Партия",
        "period_word_one": "партия",
        "period_word_many": "партий",
        "period_total_step": 0.5,
        "default_total": 179.5,
        "match_total": 179.5,
        "bets": ["winner2", "total", "handicap"],
        "period_markets": True,
        "margin": 7.0,
        "source": "Betcity · волейбольная линия и статистика",
    },
    "tennis": {
        "id": "tennis",
        "betcity_id": "2",
        "name": "Большой теннис",
        "short": "Теннис",
        "icon": "🎾",
        "score_mode": "sets",        # first pair = sets won, rest = games
        "has_draw": False,
        "periods": 5,
        "period_word": "Сет",
        "period_word_one": "сет",
        "period_word_many": "сетов",
        "period_total_step": 0.5,
        "default_total": 20.5,
        "match_total": 20.5,
        "bets": ["winner2", "total", "handicap"],
        "period_markets": True,
        "margin": 1.5,
        "source": "Betcity · теннисная линия и статистика",
    },
}

# Порядок в интерфейсе: сначала уже работающий вид спорта.
SPORT_ORDER = ("table_tennis", "football", "hockey", "basketball",
               "volleyball", "tennis")

ALIASES = {
    "table_tennis": "table_tennis", "tabletennis": "table_tennis",
    "tt": "table_tennis", "pingpong": "table_tennis",
    "настольный теннис": "table_tennis", "наст. теннис": "table_tennis",
    "наст.теннис": "table_tennis", "46": "table_tennis",
    "football": "football", "soccer": "football", "футбол": "football", "1": "football",
    "hockey": "hockey", "хоккей": "hockey", "7": "hockey",
    "basketball": "basketball", "баскетбол": "basketball", "3": "basketball",
    "volleyball": "volleyball", "волейбол": "volleyball", "12": "volleyball",
    "tennis": "tennis", "большой теннис": "tennis", "2": "tennis",
}

BETS = {
    "winner2": {
        "type": "winner",
        "label": "Победитель матча",
        "short": "П1/П2",
        "sides": [["p1", "П1"], ["p2", "П2"]],
        "scope": "match",
    },
    "winner3": {
        "type": "winner",
        "label": "Исход матча 1X2",
        "short": "1X2",
        "sides": [["p1", "П1"], ["x", "Ничья"], ["p2", "П2"]],
        "scope": "match",
    },
    "total": {
        "type": "total",
        "label": "Тотал матча",
        "short": "ТБ/ТМ",
        "sides": [["over", "ТБ"], ["under", "ТМ"]],
        "scope": "match",
        "threshold": True,
    },
    "handicap": {
        "type": "handicap",
        "label": "Фора матча",
        "short": "Фора",
        "sides": [["p1", "Ф1"], ["p2", "Ф2"]],
        "scope": "match",
        "value": True,
    },
    "btts": {
        "type": "btts",
        "label": "Обе забьют",
        "short": "ОЗ",
        "sides": [["yes", "Да"], ["no", "Нет"]],
        "scope": "match",
    },
}


def normalize_sport(value):
    """Приводит id/название/номер Betcity к id справочника."""
    text = str(value or "").strip().lower().replace("ё", "е")
    if text in SPORTS:
        return text
    if text in ALIASES:
        return ALIASES[text]
    for key, profile in SPORTS.items():
        if text and (text == profile["betcity_id"] or
                     text == profile["name"].lower() or
                     text == profile["short"].lower()):
            return key
    return "table_tennis"


def profile(sport):
    return SPORTS[normalize_sport(sport)]


def sport_by_betcity_id(betcity_id):
    text = str(betcity_id or "").strip()
    for key, item in SPORTS.items():
        if item["betcity_id"] == text:
            return key
    return ""


def name(sport):
    return profile(sport)["name"]


def short_name(sport):
    return profile(sport)["short"]


def bet_definitions(sport):
    """Список рынков, доступных виду спорта (для UI и проверки правил)."""
    result = []
    for bet_id in profile(sport)["bets"]:
        item = dict(BETS.get(bet_id) or {})
        if not item:
            continue
        item["id"] = bet_id
        result.append(item)
    return result


def period_label(sport, number=1):
    item = profile(sport)
    try:
        number = int(number)
    except Exception:
        number = 1
    if item["id"] == "table_tennis" or item["period_word"] == "Партия":
        return "Партия %d" % number
    if item["period_word"] == "Сет":
        return "Сет %d" % number
    if item["period_word"] == "Четверть":
        return "%d-я четверть" % number
    if item["period_word"] == "Период":
        return "%d-й период" % number
    return "%s %d" % (item["period_word"], number)


def period_short(sport):
    item = profile(sport)
    return {
        "Партия": "партия",
        "Сет": "сет",
        "Четверть": "четверть",
        "Период": "период",
        "Тайм": "тайм",
    }.get(item["period_word"], "период")


def total_unit(sport):
    if normalize_sport(sport) == "table_tennis":
        return "очк."
    if normalize_sport(sport) == "football":
        return "гол."
    if normalize_sport(sport) == "hockey":
        return "гол."
    if normalize_sport(sport) == "basketball":
        return "очк."
    if normalize_sport(sport) in ("volleyball", "tennis"):
        return "очк."
    return "очк."


# --------------------------------------------------------------------------
# разбор счёта
# --------------------------------------------------------------------------

_SCORE_RE = re.compile(r"(\d+)\s*:\s*(\d+)")
# Счёт Betcity: «0:2 (25:27, 17:25)» — итог матча, затем партии/сеты.
_SCORE_WITH_MATCH_RE = re.compile(
    r"^\s*(\d+)\s*:\s*(\d+)\s*\((.*)\)\s*$", re.S)


def score_pairs(text):
    return [(int(a), int(b)) for a, b in _SCORE_RE.findall(str(text or ""))]


def split_score_text(text):
    """Делит строку счёта на счёт матча и счёт периодов.

    «0:2 (25:27, 17:25)» -> ((0, 2), «25:27, 17:25»).
    Если скобок нет, счёт матча неизвестен: (None, исходная строка).
    """
    raw = str(text or "")
    found = _SCORE_WITH_MATCH_RE.match(raw)
    if found:
        match = (int(found.group(1)), int(found.group(2)))
        return match, found.group(3)
    return None, raw


def combine_score(match_text, periods_text):
    """Собирает счёт матча и партии в одну строку для проверки.

    Betcity отдаёт итог матча в ``sc_ev``, а счёт партий — в ``sc_inter``.
    Проверять прогнозы по одному ``sc_inter`` нельзя: у волейбола это
    очки в партиях, а у футбола — только текущий тайм.
    """
    match_text = str(match_text or "").strip()
    periods_text = str(periods_text or "").strip()
    if not match_text:
        return periods_text
    if not periods_text or match_text == periods_text:
        return periods_text or match_text
    # Счёт уже содержит итог матча перед скобками — второй раз не добавляем.
    if _SCORE_WITH_MATCH_RE.match(periods_text):
        return periods_text
    return "%s (%s)" % (match_text, periods_text)


def event_score_text(sport, raw):
    """Итоговый счёт события Betcity.

    У всех командных видов итог матча лежит в ``sc_ev``, а партии,
    периоды или таймы — в ``sc_inter``. Настольный теннис проверяется
    отдельно по партиям, поэтому его строка не меняется.
    """
    raw = raw or {}
    sport = normalize_sport(sport)
    periods_text = str(raw.get("sc_inter") or raw.get("sc") or "").strip()
    if sport == "table_tennis":
        return periods_text
    match_text = str(raw.get("sc_ev") or "").strip()
    if not match_text:
        matrix = raw.get("sc_ev_cmx") or {}
        main = matrix.get("main") or []
        if main and isinstance(main[0], (list, tuple)) and len(main[0]) >= 2:
            match_text = "%s:%s" % (main[0][0], main[0][1])
        periods = matrix.get("ext") or []
        if periods and not periods_text:
            periods_text = ", ".join(
                "%s:%s" % (pair[0], pair[1])
                for pair in periods
                if isinstance(pair, (list, tuple)) and len(pair) >= 2)
    return combine_score(match_text, periods_text)


def parse_score(sport, text):
    """Разбирает счёт Betcity в общее представление.

    Возвращает словарь:
      match    — счёт матча (голы/очки или партии/сеты),
      periods  — счёт периодов/партий/сетов,
      points   — очки по партиям/сетам (None, если их не было),
      total    — суммарный тотал матча (голы/очки/геймы),
      sets_won — выигранные периоды/партии/сеты,
      winner   — P1 / P2 / DRAW,
      draw     — возможна ли ничья по счёту матча,
      match_known — счёт матча известен, а не догадка,
      raw      — исходная строка.

    Счёт Betcity бывает двух видов:

      * «3:1 (25:18, 22:25, 25:20, 25:19)» — итог матча и партии;
      * «25:18, 22:25, 25:20, 25:19» — только партии (live-фид).

    Во втором случае у волейбола и тенниса итог матча считается по
    выигранным партиям, а не берётся первая пара (иначе 25:27 становится
    «счётом матча»). Для настольного тенниса и футбола одиночная пара
    остаётся счётом матча, как и раньше.
    """
    item = profile(sport)
    mode = item["score_mode"]
    match_prefix, inner_text = split_score_text(text)
    pairs = score_pairs(inner_text)
    if not pairs and match_prefix is None:
        return None

    periods = []
    points = None
    match_known = True

    if mode == "single":
        # У футбола первая пара — итог матча, скобки — таймы. Таймы не
        # считаем периодами: тотал матча уже есть в первой паре.
        match = match_prefix if match_prefix is not None else pairs[0]
        periods = []
        total = match[0] + match[1]
        sets_won = (1 if match[0] > match[1] else 0,
                    1 if match[1] > match[0] else 0)
        points = match
    elif mode == "periods":
        periods = pairs
        if match_prefix is not None:
            match = match_prefix
        else:
            match = (sum(a for a, _b in periods), sum(b for _a, b in periods))
            match_known = bool(periods)
        # Итог матча Betcity уже содержит голы/очки всех периодов. Сумма
        # sc_inter может отставать (идёт текущий период), поэтому тотал
        # берём из счёта матча, а не из суммы периодов.
        total = match[0] + match[1]
        points = match
        sets_won = (sum(1 for a, b in periods if a > b),
                    sum(1 for a, b in periods if b > a))
    else:  # sets: волейбол, теннис, настольный теннис
        if match_prefix is not None:
            match = match_prefix
            periods = pairs
            if periods:
                points = (sum(a for a, _b in periods),
                          sum(b for _a, b in periods))
                total = sum(a + b for a, b in periods)
            else:
                # Есть только выигранные партии — тотал очков неизвестен.
                total = None
        elif len(pairs) == 1 and max(pairs[0]) <= 5:
            # «0:4», «3:1» — только выигранные партии. Сумма 0+4 не тотал.
            match = pairs[0]
            periods = []
            total = None
        else:
            periods = pairs
            points = (sum(a for a, _b in periods),
                      sum(b for _a, b in periods))
            total = sum(a + b for a, b in periods)
            match = (sum(1 for a, b in periods if a > b),
                     sum(1 for a, b in periods if b > a))
        sets_won = match

    decisive = match
    if decisive[0] == decisive[1] and item["has_draw"]:
        winner = "DRAW"
        draw = True
    elif decisive[0] > decisive[1]:
        winner = "P1"
        draw = False
    else:
        winner = "P2"
        draw = False

    return {
        "match": match,
        "periods": periods,
        "points": points,
        "total": total,
        "sets_won": sets_won,
        "winner": winner,
        "draw": draw,
        "match_known": match_known,
        "raw": str(text or ""),
    }


def orient_score(parsed, flipped):
    """Разворачивает разобранный счёт относительно другой стороны."""
    if not parsed:
        return parsed
    if not flipped:
        return parsed
    points = parsed.get("points")
    return {
        "match": (parsed["match"][1], parsed["match"][0]),
        "periods": [(b, a) for a, b in parsed["periods"]],
        "points": (points[1], points[0]) if points else None,
        "total": parsed["total"],
        "sets_won": (parsed["sets_won"][1], parsed["sets_won"][0]),
        "winner": {"P1": "P2", "P2": "P1", "DRAW": "DRAW"}.get(
            parsed["winner"], parsed["winner"]),
        "draw": parsed["draw"],
        "match_known": parsed.get("match_known", True),
        "raw": parsed.get("raw", ""),
    }


def _period_complete(sport, pair):
    """Партия/сет доиграны до конца (а не середина)."""
    a, b = int(pair[0]), int(pair[1])
    high, low = max(a, b), min(a, b)
    sport = normalize_sport(sport)
    if sport == "table_tennis":
        return high >= 11 and (high - low) >= 2
    if sport == "volleyball":
        # Обычная партия до 25, укороченная решающая — до 15.
        return (high >= 15 and (high - low) >= 2)
    if sport == "tennis":
        return (high >= 6 and (high - low) >= 2) or (high == 7 and low == 6)
    return True


def score_final(sport, parsed):
    """Счёт похож на финальный, а не на середину партии.

    Нужен для разметки обучающей выборки: частичный счёт нельзя
    превращать в метки тотала и форы.
    """
    if not parsed:
        return False
    sport = normalize_sport(sport)
    mode = profile(sport)["score_mode"]
    if mode == "sets":
        wins = max(int(parsed["match"][0]), int(parsed["match"][1]))
        if sport == "table_tennis":
            return wins >= 4
        if wins < 2 or parsed.get("total") is None:
            return False
        return all(_period_complete(sport, pair)
                   for pair in parsed.get("periods") or [])
    return parsed.get("total") is not None


def record_from_score(sport, parsed, flipped=False):
    """Готовит поля для нормализованных записей конструктора."""
    data = orient_score(parsed, flipped)
    if not data:
        return None
    item = profile(sport)
    match = data["match"]
    periods = data["periods"] or [match]
    total = data["total"]
    return {
        "match_score": match,
        "sets": periods,
        "set_totals": [a + b for a, b in periods],
        "match_total": total,
        "won": match[0] > match[1],
        "draw": bool(data["draw"]),
        "btts": (match[0] > 0 and match[1] > 0) if item["has_draw"] else None,
        "winner": data["winner"],
    }


def default_total(sport):
    return profile(sport)["default_total"]


def match_total(sport):
    return profile(sport)["match_total"]


def margin(sport):
    return profile(sport)["margin"]


def public_catalog():
    """Краткий список видов спорта для интерфейса."""
    items = []
    for sport_id in SPORT_ORDER:
        item = profile(sport_id)
        items.append({
            "id": sport_id,
            "name": item["name"],
            "short": item["short"],
            "icon": item["icon"],
            "default_total": item["default_total"],
            "match_total": item["match_total"],
            "has_draw": item["has_draw"],
            "bets": bet_definitions(sport_id),
            "period_word": item["period_word"],
            "periods": item["periods"],
        })
    return items

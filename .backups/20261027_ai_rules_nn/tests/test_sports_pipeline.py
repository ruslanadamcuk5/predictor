# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Проверка новых видов спорта: парсер статистики, конструктор, анализатор."""
import json
import os
import sys
import tempfile

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "sports_pipeline_home")
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
BASE = (os.path.join(ROOT, "app", "src", "main", "python"))
sys.path.insert(0, BASE)
PROBE = os.path.join(FIXTURES, "sport_probe")

import sports
import constructor_engine as ce
import predictor_core as core
import analyzer

checks = [0, 0]


def check(name, condition, detail=""):
    checks[1] += 1
    if condition:
        checks[0] += 1
        print("PASS %s" % name)
    else:
        print("FAIL %s :: %s" % (name, detail))
        raise SystemExit(1)


# --- разбор счёта -----------------------------------------------------------
cases = {
    "football": ("3:2 (2:1)", (3, 2), 5, 1, True),
    "hockey": ("4:6 (2:4, 0:1, 2:1)", (4, 6), 10, 3, True),
    "basketball": ("89:99 (22:18, 25:28, 20:27, 22:26)", (89, 99), 188, 4, None),
    "volleyball": ("3:1 (25:18, 22:25, 25:20, 25:19)", (3, 1), 179, 4, None),
    "tennis": ("2:0 (7:6, 7:5)", (2, 0), 25, 2, None),
}
for sport, (text, match, total, sets, btts) in cases.items():
    parsed = sports.parse_score(sport, text)
    check("%s: счёт разобран" % sport, parsed is not None, text)
    check("%s: победитель счёта" % sport, parsed["match"] == match, parsed)
    check("%s: тотал" % sport, parsed["total"] == total, parsed)
    record = sports.record_from_score(sport, parsed, False)
    check("%s: сетов/периодов" % sport, len(record["sets"]) == sets,
          record["sets"])
    check("%s: ОЗ" % sport, record["btts"] == btts, record["btts"])

# --- парсер страниц ---------------------------------------------------------
class FakeResponse(object):
    status_code = 200

    def __init__(self, text):
        self.text = text


class FakeSession(object):
    def __init__(self, pages):
        self.pages = list(pages)

    def get(self, *args, **kwargs):
        return FakeResponse(self.pages.pop(0))


def titles(page):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page, "html.parser")
    found = []
    for table in soup.find_all("table"):
        cell = table.find("td", class_="title")
        if not cell:
            continue
        title = cell.get_text(" ", strip=True)
        if title.lower().startswith("последние игры"):
            name = title[len("Последние игры"):].strip(" :")
            name = name.split(" : ")[0].strip()
            found.append(name)
    return found


for sport in ("football", "hockey", "basketball", "volleyball", "tennis"):
    path = os.path.join(PROBE, "%s_1.html" % sport)
    with open(path, "r", encoding="utf-8") as handle:
        page = handle.read()
    names = titles(page)
    check("%s: имена команд найдены" % sport, len(names) == 2, names)
    team1, team2 = names
    predictor = core.PredictorEnsemble.__new__(core.PredictorEnsemble)
    predictor.session = FakeSession([page])
    stats = predictor.get_match_stats("/x", team1, team2, sport)
    check("%s: вид спорта в статистике" % sport, stats.get("sport") == sport,
          stats.get("sport"))
    check("%s: последние игры 1" % sport, len(stats["recent"]["team1"]) >= 3,
          len(stats["recent"]["team1"]))
    check("%s: последние игры 2" % sport, len(stats["recent"]["team2"]) >= 3,
          len(stats["recent"]["team2"]))
    check("%s: очные" % sport, len(stats["h2h_matches"]) >= 1,
          len(stats["h2h_matches"]))
    totals = stats.get("page_totals") or []
    if totals:
        check("%s: линия тотала" % sport,
              (stats.get("page_total") or {}).get("line"),
              stats.get("page_total"))
    else:
        print("SKIP %s: таблицы тоталов на странице нет" % sport)
    for game in stats["recent"]["team1"] + stats["recent"]["team2"]:
        check("%s: запись содержит тотал" % sport,
              isinstance(game.get("match_total"), int), game)
        check("%s: запись содержит исход" % sport,
              isinstance(game.get("won"), bool), game)
    for game in stats["h2h_matches"]:
        check("%s: очная запись содержит счёт" % sport,
              isinstance(game.get("match_score"), str), game)

    # --- конструктор: правила и один матчевый прогноз ---
    engine = ce.ConstructorEngine(os.path.join(HOME, "rules_%s.json" % sport))
    preset = engine.presets(sport)[0]
    rule = json.loads(json.dumps(preset["rule"]))
    rule["id"] = "test_" + sport
    ok, errors, saved = engine.save({"sport": sport, "rules": [rule]}, sport)
    check("%s: правило сохраняется" % sport, ok, errors)
    check("%s: отдельный файл правил" % sport,
          os.path.exists(os.path.splitext(engine.path)[0] + "_" + sport + ".json"),
          os.listdir(HOME))
    match = {
        "sport": sport,
        "team1": team1, "team2": team2,
        "odds": {"match_p1": 1.8, "match_p2": 2.0, "match_draw": 3.4,
                 "total_line": sports.default_total(sport),
                 "total_over": 1.9, "total_under": 1.9},
    }
    broad = {
        "id": "broad_" + sport,
        "name": "Тест: форма команды 1",
        "enabled": True,
        "priority": 100,
        "conditions": {"logic": "and", "conditions": [{
            "metric": "p.recent.win_rate",
            "args": {"side": "p1", "window": 5},
            "op": "gte", "value": 0,
        }]},
        "action": {"type": "winner", "side": "p1", "targets": ["match"],
                   "confidence": 0.6},
    }
    predictions, fired, skip = engine.evaluate(match, stats, rules=[broad])
    check("%s: конструктор что-то нашёл" % sport,
          len(predictions) >= 1 and len(fired) >= 1, (predictions, fired))
    if predictions:
        check("%s: прогноз матчевый" % sport,
              predictions[0]["target"] == "match", predictions[0])
        check("%s: прогноз содержит вердикт" % sport,
              bool(predictions[0]["verdict"]), predictions[0])

    # --- встроенный алгоритм ---
    predictions = predictor._analyze_generic(stats, match)
    check("%s: встроенный алгоритм даёт прогноз" % sport,
          len(predictions) >= 1, predictions)
    for prediction in predictions:
        check("%s: матчевый прогноз builtin" % sport,
              prediction["target"] == "match", prediction)
        check("%s: уверенность в диапазоне" % sport,
              0.0 < prediction["confidence_val"] <= 1.0, prediction)

    # --- расчёт результата ---
    checker = core.ResultChecker.__new__(core.ResultChecker)
    parsed = sports.parse_score(sport, cases[sport][0])
    for kind, side, extra in (("winner", "P1", {}),
                              ("total", "over", {"threshold": 1.0}),
                              ("total", "under", {"threshold": 1000.0})):
        prediction = {"kind": kind, "expected_side": side,
                      "threshold": extra.get("threshold")}
        result = checker.check_match_prediction_success(prediction, parsed,
                                                        sport)
        check("%s: результат %s/%s" % (sport, kind, side),
              result is not None and isinstance(result.get("success"), bool),
              result)

print("OK — проверок: %d" % checks[1])

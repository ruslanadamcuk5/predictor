# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
import io
import json
import os
import sys
import tempfile

ROOT = ROOT
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="preset_home_")

import constructor_engine as ce  # noqa: E402
import predictor_core as core  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

failures = []


def check(name, condition, detail=""):
    if not condition:
        failures.append("%s: %s" % (name, detail))


page = io.open(os.path.join(FIXTURES, "stats_page.html"),
               encoding="utf-8").read()
soup = BeautifulSoup(page, "html.parser")
team1, team2 = "Иван Леднев", "Александр Клавденков"
bare = core.PredictorEnsemble.__new__(core.PredictorEnsemble)
recent = {}
for table in soup.find_all("table"):
    title_cell = table.find("td", class_="title")
    title = title_cell.get_text(" ", strip=True) if title_cell else ""
    if title.lower().startswith("последние игры"):
        name = title[len("Последние игры"):].strip(" :")
        recent[name] = bare._parse_recent_games(table, name)

stats = {
    "h2h_matches": [
        {
            "date": "2026-09-01", "date_obj": None,
            "winner": team1, "loser": team2,
            "sets": [(11, 8), (11, 9), (9, 11), (11, 7)],
            "match_total": 76, "set_totals": [19, 20, 20, 18],
        },
        {
            "date": "2026-06-01", "date_obj": None,
            "winner": team2, "loser": team1,
            "sets": [(9, 11), (11, 13), (11, 5), (11, 9), (11, 8)],
            "match_total": 97, "set_totals": [20, 24, 16, 20, 19],
        },
        {
            "date": "2026-03-01", "date_obj": None,
            "winner": team1, "loser": team2,
            "sets": [(11, 6), (11, 7), (11, 9)],
            "match_total": 55, "set_totals": [17, 18, 20],
        },
    ],
    "recent": recent,
    "page_total": {"line": 75.5, "last5_over": 4, "last5_under": 1,
                   "season_over": 31, "season_total": 50},
    "league": "Лига Про",
}
match = {
    "match_id": "m1", "team1": team1, "team2": team2, "league": "Лига Про",
    "date": "19.10.2026 20:30", "start_time": "2026-10-19T20:30",
    "stat_link": "/x", "is_started": False, "current_score": "0:0",
    "odds": {"match_p1": 1.85, "match_p2": 1.95,
             "first_set_p1": 1.9, "first_set_p2": 1.9},
}

catalog = ce.ConstructorEngine(os.path.join(tempfile.mkdtemp(), "rules.json"))
ops_by_type = {kind: [op[0] for op in items]
               for kind, items in ce.OPERATORS.items()}
metric_map = {m["id"]: m for m in ce.METRICS}

allowed_categories = {"Тоталы", "Победитель", "Фильтры", "Комбинированные"}
names = set()
presets = ce.PRESETS
check("presets count", len(presets) >= 40, len(presets))

for index, preset in enumerate(presets):
    label = preset.get("name") or ("#%d" % index)
    check("meta name %d" % index, bool(preset.get("name")), label)
    check("meta category %s" % label,
          preset.get("category") in allowed_categories, preset.get("category"))
    check("meta description %s" % label,
          len(preset.get("description") or "") >= 30, preset.get("description"))
    check("meta source %s" % label, bool(preset.get("source")), label)
    check("unique name %s" % label, label not in names, label)
    names.add(label)

    rule = preset.get("rule") or {}
    check("rule name %s" % label, bool(rule.get("name")), label)
    action = rule.get("action") or {}
    check("action type %s" % label,
          action.get("type") in ("total", "winner", "skip"), action.get("type"))
    targets = action.get("targets")
    check("action targets %s" % label,
          isinstance(targets, list) and bool(targets), targets)
    for target in targets or []:
        check("action target value %s" % label,
              target == "auto" or target in (1, 2, 3, 4, 5), target)
    check("action side %s" % label,
          action.get("side") in ("over", "under", "p1", "p2", "auto"),
          action.get("side"))
    confidence = action.get("confidence")
    check("action confidence %s" % label,
          isinstance(confidence, (int, float)) and 0.05 <= confidence <= 0.99,
          confidence)

    # обход дерева условий
    def walk(group):
        check("group %s" % label, isinstance(group, dict), group)
        logic = (group or {}).get("logic")
        check("group logic %s" % label, logic in ("and", "or", None), logic)
        items = (group or {}).get("conditions") or []
        check("group conditions %s" % label, bool(items), items)
        for cond in items:
            if "conditions" in cond:
                walk(cond)
                continue
            metric_id = cond.get("metric")
            definition = metric_map.get(metric_id)
            check("metric %s in %s" % (metric_id, label),
                  definition is not None, metric_id)
            if definition is None:
                continue
            kind = definition.get("type", "number")
            op = cond.get("op")
            check("op %s of %s" % (op, label),
                  op in ops_by_type.get(kind, []), (op, kind))
            args = cond.get("args") or {}
            declared = definition.get("args") or {}
            for key in args:
                check("arg %s of %s" % (key, label), key in declared,
                      (key, declared))
            value = cond.get("value")
            if kind == "enum":
                options = [item[0] for item in ce.ENUM_OPTIONS.get(metric_id, [])]
                if op in ("in", "not_in") and isinstance(value, list):
                    for item in value:
                        check("enum item %s of %s" % (item, label),
                              item in options, (item, options))
                else:
                    check("enum value %s of %s" % (value, label),
                          value in options, (value, options))
            elif kind == "bool":
                check("bool op %s of %s" % (op, label), op == "is", (op, value))
                check("bool value %s of %s" % (value, label),
                      isinstance(value, bool), value)

    walk(rule.get("conditions") or {})

    # очистка не должна менять op/значения
    errors = []
    cleaned = ce._clean_rule(json.loads(json.dumps(rule)), index + 1, errors)
    check("clean %s" % label, cleaned is not None and not errors, errors)
    if cleaned:
        def compare_ops(original, restored):
            left = (original or {}).get("conditions") or []
            right = (restored or {}).get("conditions") or []
            check("clean length %s" % label, len(left) == len(right),
                  (len(left), len(right)))
            for a, b in zip(left, right):
                if "conditions" in a:
                    compare_ops(a, b)
                else:
                    check("clean op %s %s" % (a.get("metric"), label),
                          a.get("op") == b.get("op"),
                          (a.get("op"), b.get("op")))
        compare_ops(rule.get("conditions"), cleaned.get("conditions"))
        check("describe %s" % label, bool(ce.describe_rule(cleaned)))

    # оценка на контексте не должна падать
    try:
        predictions, fired, skip_info = catalog.evaluate(
            match, stats, rules=[dict(rule, id="p%d" % index, enabled=True,
                                     priority=100)])
    except Exception as exc:  # noqa: BLE001
        failures.append("evaluate %s: %s" % (label, exc))
        continue
    check("evaluate returns %s" % label,
          isinstance(predictions, list) and isinstance(fired, list), label)
    for prediction in predictions:
        check("prediction kind %s" % label,
              prediction.get("kind") in ("winner", "total"), prediction)

# сохранение всех пресетов
engine = ce.ConstructorEngine(os.path.join(tempfile.mkdtemp(), "rules.json"))
rules = []
for index, preset in enumerate(presets):
    item = json.loads(json.dumps(preset["rule"]))
    item["id"] = "preset_%d" % index
    item["enabled"] = True
    item["priority"] = 100
    rules.append(item)
ok, errors, saved = engine.save({"rules": rules})
check("save all presets", ok is True, errors)
check("saved all presets", len(saved or []) == len(presets),
      len(saved or []))

# сохранение в JSON и обратно (как это делает API)
payload = engine.catalog_payload()
roundtrip = json.loads(json.dumps(payload))
check("catalog json", len(roundtrip["metrics"]) >= 60, len(roundtrip["metrics"]))
check("presets json", len(json.loads(json.dumps(engine.presets()))) == len(presets))

if failures:
    print("FAILURES:", len(failures))
    for item in failures[:40]:
        print(" -", item)
    sys.exit(1)
print("OK: %d presets validated" % len(presets))
print("categories:", {c: sum(1 for p in presets if p["category"] == c)
                      for c in sorted(allowed_categories)})

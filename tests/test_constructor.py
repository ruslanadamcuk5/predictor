# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Тесты конструктора правил: разбор статистики, каталог метрик, оценка
условий/правил, сохранение, API и полный цикл в режиме конструктора."""
import io
import json
import os
import shutil
import sys
import copy

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "ctor_home_test")
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

from bs4 import BeautifulSoup  # noqa: E402

import predictor_core as core  # noqa: E402
import constructor_engine as ce  # noqa: E402
import engine_api as api  # noqa: E402

PASSED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
    else:
        raise AssertionError("%s: %s" % (name, detail))


catalog_engine = ce.ConstructorEngine(core.CONSTRUCTOR_RULES_FILE)

# ===================== 1. Каталог метрик =====================
catalog = catalog_engine.catalog_payload()
check("catalog non-empty", len(catalog["metrics"]) >= 60, len(catalog["metrics"]))
check("catalog groups", len(set(m["group"] for m in catalog["metrics"])) >= 5)
check("catalog args", set(["side", "window", "set", "threshold"]) <= set(catalog["args"]))

for metric in catalog["metrics"]:
    check("metric has id %s" % metric.get("id"), bool(metric.get("id")))
    check("metric %s has func" % metric["id"], metric["id"] in ce.METRIC_FUNCS)
    check("metric %s type" % metric["id"], metric["type"] in ("number", "enum", "bool", "string"))
    check("metric %s meta" % metric["id"], bool(metric.get("group")) and bool(metric.get("label")))
    for arg in (metric.get("args") or {}):
        check("metric %s arg %s defined" % (metric["id"], arg), arg in ce.ARG_DEFS)
    if metric["type"] == "enum":
        check("metric %s options" % metric["id"], bool(metric.get("options")))
check("operators all types", set(["number", "enum", "bool", "string"]) <= set(catalog["operators"]))

label = ce.format_metric_label("p.recent.win_rate", {"side": "p2", "window": 5})
check("metric label side", "игрока 2" in label, label)
check("metric label window", " 5" in label, label)


# ===================== 2. Разбор страницы статистики =====================
page = io.open(os.path.join(FIXTURES, "stats_page.html"),
               encoding="utf-8").read()
soup = BeautifulSoup(page, "html.parser")

team1, team2 = "Иван Леднев", "Александр Клавденков"
bare = core.PredictorEnsemble.__new__(core.PredictorEnsemble)
recent = {}
page_total = {}
for table in soup.find_all("table"):
    title_cell = table.find("td", class_="title")
    title = title_cell.get_text(" ", strip=True) if title_cell else ""
    if title.lower().startswith("последние игры"):
        name = title[len("Последние игры"):].strip(" :")
        recent[name] = bare._parse_recent_games(table, name)
    elif not title:
        first_row = table.find("tr")
        first_cells = first_row.find_all(["td", "th"]) if first_row else []
        first_text = first_cells[0].get_text(" ", strip=True) if first_cells else ""
        if first_text.lower().startswith("тотал"):
            page_total = bare._parse_page_total(table)

check("recent two players", len(recent) == 2, list(recent))
for name, games in recent.items():
    check("recent %s is 5" % name, len(games) == 5, len(games))
    for game in games:
        check("recent %s sets list" % name, isinstance(game["sets"], list))
        check("recent %s won bool" % name, isinstance(game["won"], bool))
        check("recent %s total" % name, game["match_total"] == sum(game["set_totals"]))
        check("recent %s oriented" % name,
              all(isinstance(point, int) for pair in game["sets"] for point in pair))
first = recent[team1][0]
check("recent orientation", first["match_score"] in [(2, 3), (3, 2)], first["match_score"])
check("page_total line parsed", page_total.get("line") == 75.5, page_total)
check("page_total last5", page_total.get("last5_under") is not None, page_total)


# ===================== 3. get_match_stats целиком =====================
class FakeResponse(object):
    status_code = 200
    text = page


class FakeSession(object):
    def get(self, *args, **kwargs):
        return FakeResponse()


predictor = core.PredictorEnsemble.__new__(core.PredictorEnsemble)
predictor.session = FakeSession()
stats = predictor.get_match_stats("/x", team1, team2)
check("stats h2h parsed", len(stats["h2h_matches"]) >= 8, len(stats["h2h_matches"]))
check("stats recent team1", len(stats["recent"]["team1"]) == 5, len(stats["recent"]["team1"]))
check("stats recent team2", len(stats["recent"]["team2"]) == 5, len(stats["recent"]["team2"]))
check("stats page_total", stats["page_total"].get("line") == 75.5)
check("stats h2h sorted desc", all(
    (stats["h2h_matches"][i]["date_obj"] or core.datetime.min) >=
    (stats["h2h_matches"][i + 1]["date_obj"] or core.datetime.min)
    for i in range(len(stats["h2h_matches"]) - 1)))


# ===================== 4. Метрики на реальных данных =====================
stats["league"] = "Лига Про"
match = {
    "match_id": "m1", "team1": team1, "team2": team2, "league": "Лига Про",
    "date": "19.10.2026 20:30", "start_time": "2026-10-19T20:30",
    "stat_link": "/x", "is_started": False, "current_score": "0:0",
    "odds": {"match_p1": 1.85, "match_p2": 1.95, "first_set_p1": 1.9, "first_set_p2": 1.9},
}
ctx = ce.Context(match, stats)

SAMPLE_ARGS = {"side": "p1", "window": 5, "set": 1, "threshold": 18.5}
for metric in catalog["metrics"]:
    args = dict(SAMPLE_ARGS)
    for key, value in (metric.get("args") or {}).items():
        args[key] = value
    try:
        ce.evaluate_metric(ctx, metric["id"], args)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError("metric %s failed: %s" % (metric["id"], exc))

check("h2h.count", ce.evaluate_metric(ctx, "h2h.count", {}) == len(stats["h2h_matches"]))
win_rate = ce.evaluate_metric(ctx, "h2h.win_rate", {"side": "p1", "window": 10})
check("h2h.win_rate range", win_rate is None or 0 <= win_rate <= 100, win_rate)
over_rate = ce.evaluate_metric(ctx, "h2h.over_rate", {"window": 10, "set": 1, "threshold": 18.5})
check("h2h.over_rate range", over_rate is None or 0 <= over_rate <= 100, over_rate)
check("odds.p1", ce.evaluate_metric(ctx, "odds.p1", {}) == 1.85)
check("odds.implied_p1", ce.evaluate_metric(ctx, "odds.implied_p1", {}) is not None)
check("page.total_line", ce.evaluate_metric(ctx, "page.total_line", {}) == 75.5)
last_winner = ce.evaluate_metric(ctx, "h2h.last_winner", {})
check("h2h.last_winner", last_winner in ("p1", "p2", None), last_winner)
check("match.hour", ce.evaluate_metric(ctx, "match.hour", {}) == 20)


# ===================== 5. Оценка условий всех операторов =====================
count = len(stats["h2h_matches"])
for op, value, expected in [
    ("gt", 0, True), ("gte", count, True), ("lt", 1, False), ("lte", 100, True),
    ("eq", count, True), ("neq", -5, True), ("exists", None, True),
]:
    cond = {"metric": "h2h.count", "args": {}, "op": op, "value": value}
    matched, details = ce.evaluate_condition(ctx, cond)
    check("operator %s" % op, matched == expected, (matched, expected))
    if matched:
        check("operator %s detail" % op, details, details)

matched, _ = ce.evaluate_condition(
    ctx, {"metric": "h2h.count", "args": {}, "op": "between", "value": 1, "value2": 100})
check("operator between", matched is True)

cond = {"metric": "h2h.count", "args": {}, "op": "gte",
        "value_metric": "h2h.count", "value_args": {}}
matched, _ = ce.evaluate_condition(ctx, cond)
check("value_metric compare", matched is True)

matched, _ = ce.evaluate_condition(
    ctx, {"metric": "h2h.last_winner", "args": {}, "op": "in", "value": ["p1", "p2"]})
check("enum in", matched is True)

group = {"logic": "and", "conditions": [
    {"metric": "h2h.count", "args": {}, "op": "gte", "value": 1},
    {"metric": "odds.p1", "args": {}, "op": "lt", "value": 2.0},
]}
matched, _ = ce.evaluate_group(ctx, group)
check("group and true", matched is True)
group["logic"] = "or"
group["conditions"].append({"metric": "h2h.count", "args": {}, "op": "gt", "value": 999})
matched, _ = ce.evaluate_group(ctx, group)
check("group or true", matched is True)
nested = {"logic": "and", "conditions": [
    {"metric": "h2h.count", "args": {}, "op": "gte", "value": 1},
    {"logic": "or", "conditions": [
        {"metric": "odds.p1", "args": {}, "op": "gt", "value": 5},
        {"metric": "odds.p1", "args": {}, "op": "lt", "value": 3},
    ]},
]}
matched, _ = ce.evaluate_group(ctx, nested)
check("nested group", matched is True)


# ===================== 6. Правила и действия =====================
constructor_engine = ce.ConstructorEngine(core.CONSTRUCTOR_RULES_FILE + ".rules")


def fire(rules):
    return constructor_engine.evaluate(match, stats, rules=json.loads(json.dumps(rules)))

rule_total = {
    "name": "ТБ 18.5 по форме", "enabled": True, "priority": 100, "stop": False,
    "conditions": {"logic": "and", "conditions": [
        {"metric": "p.recent.avg_set_total", "args": {"side": "p1", "window": 5},
         "op": "gt", "value": 1},
    ]},
    "action": {"type": "total", "targets": [1], "side": "over",
               "threshold": 18.5, "confidence": 0.7},
}
predictions, fired, skip_info = fire([rule_total])
check("rule fired", len(predictions) == 1 and len(fired) == 1, (predictions, fired))
check("rule prediction label", predictions[0]["label"].startswith("Партия 1"), predictions[0])
check("rule prediction verdict", predictions[0]["verdict"] in ("ТБ 18.5", "ТМ 18.5"), predictions[0])
check("rule prediction reason", "ТБ 18.5 по форме" in predictions[0]["models_info"])
check("rule prediction target/kind",
      predictions[0]["target"] == "set1" and predictions[0]["kind"] == "total", predictions[0])

rule_skip = json.loads(json.dumps(rule_total))
rule_skip["action"] = {"type": "skip", "targets": [1], "side": "auto",
                       "threshold": 18.5, "confidence": 0.6}
predictions, fired, skip_info = fire([rule_skip])
check("skip rule fired", len(fired) == 1 and predictions == [] and skip_info is not None)
check("skip info name", skip_info["rule"] == "ТБ 18.5 по форме", skip_info)

rule_false = json.loads(json.dumps(rule_total))
rule_false["conditions"] = {"logic": "and", "conditions": [
    {"metric": "h2h.count", "args": {}, "op": "gt", "value": 999}]}
predictions, fired, skip_info = fire([rule_false])
check("rule not fired", fired == [] and predictions == [])

rule_auto = {
    "name": "Авто", "enabled": True, "priority": 10, "stop": False,
    "conditions": {"logic": "and", "conditions": [
        {"metric": "h2h.count", "args": {}, "op": "gte", "value": 1}]},
    "action": {"type": "total", "targets": ["auto"], "side": "auto",
               "threshold": 18.5, "confidence": 0.6},
}
predictions, fired, skip_info = fire([rule_auto])
check("auto rule fired", len(predictions) == 1, (predictions, fired))
check("auto target chosen", predictions[0]["target"] in ("set1", "set2", "set3", "set4", "set5"),
      predictions[0])

# несколько партий
rule_multi = json.loads(json.dumps(rule_total))
rule_multi["action"]["targets"] = [1, 3]
predictions, fired, skip_info = fire([rule_multi])
check("multi targets", [p["target"] for p in predictions] == ["set1", "set3"],
      [p["target"] for p in predictions])


# ===================== 7. Оценка набора правил =====================
predictions, fired, skip_info = fire([rule_total, rule_auto])
check("rules predictions", len(predictions) >= 1, len(predictions))  # дедуп по target+kind
check("rules fired", len(fired) == 2)
check("rules source", all(p["source"] == "constructor" for p in predictions))
check("rules rule_name", predictions[0]["rule_name"] == "ТБ 18.5 по форме", predictions[0])

stop_rule = json.loads(json.dumps(rule_total))
stop_rule["name"] = "Стоп"
stop_rule["stop"] = True
stop_rule["priority"] = 200
predictions, fired, skip_info = fire([stop_rule, rule_auto])
check("stop rule", len(fired) == 1, fired)

skip_first = json.loads(json.dumps(rule_skip))
skip_first["priority"] = 999
predictions, fired, skip_info = fire([skip_first, rule_total])
check("skip overrides", predictions == [] and skip_info is not None, (predictions, skip_info))

disabled = json.loads(json.dumps(rule_total))
disabled["enabled"] = False
predictions, fired, skip_info = fire([disabled])
check("disabled ignored", fired == [] and predictions == [])

empty_rule = {"name": "Всегда", "enabled": True, "priority": 5, "stop": False,
              "conditions": {"logic": "and", "conditions": []},
              "action": {"type": "total", "targets": [1], "side": "over", "threshold": 18.5}}
predictions, fired, skip_info = fire([empty_rule])
check("empty conditions matches all", len(fired) == 1, fired)


# ===================== 8. Валидация и сохранение =====================
engine = ce.ConstructorEngine(core.CONSTRUCTOR_RULES_FILE)
ok, errors, rules = engine.save({"rules": [rule_total]})
check("save ok", ok is True, errors)
check("save returns rules", len(rules) == 1)
check("save described", "ЕСЛИ" in rules[0]["summary"] and "ТБ 18.5" in rules[0]["action_text"], rules[0])
check("save conditions text", "Средний тотал" in rules[0]["conditions_text"], rules[0]["conditions_text"])

ok, errors, rules = engine.save({"rules": [
    {"name": "плохая", "conditions": {"logic": "and", "conditions": [
        {"metric": "nope", "op": "gt", "value": 1}]},
     "action": {"type": "total"}}]})
check("invalid metric rejected", ok is False and errors, errors)
check("rules preserved after error", len(engine.snapshot()) == 1)

ok, errors, rules = engine.save({"rules": [
    {"name": "плохое действие", "conditions": {"logic": "and", "conditions": [
        {"metric": "h2h.count", "args": {}, "op": "gt", "value": 1}]},
     "action": {"type": "nope"}}]})
check("invalid action rejected", ok is False, errors)

ok, errors, rules = engine.save({"rules": [
    {"name": "плохая группа", "conditions": "не объект", "action": {"type": "total"}}]})
check("invalid group rejected", ok is False, errors)

# нормализация значений
ok, errors, rules = engine.save({"rules": [{
    "name": "нормализация", "conditions": {"logic": "and", "conditions": [
        {"metric": "p.recent.win_rate", "args": {"side": "zzz", "window": 999},
         "op": "bogus", "value": "42,7"}]},
    "action": {"type": "TOTAL", "targets": [9, 2], "side": "zzz", "threshold": 500,
               "confidence": 5}}]})
check("normalized save", ok is True, errors)
saved = rules[0]
check("normalized side", saved["conditions"]["conditions"][0]["args"]["side"] == "p1",
      saved["conditions"]["conditions"][0]["args"])
check("normalized window", saved["conditions"]["conditions"][0]["args"]["window"] == 999,
      saved["conditions"]["conditions"][0]["args"])
check("normalized op", saved["conditions"]["conditions"][0]["op"] == "gt",
      saved["conditions"]["conditions"][0]["op"])
check("normalized action", saved["action"]["type"] == "total")
check("normalized targets", saved["action"]["targets"] == [2], saved["action"]["targets"])
check("normalized threshold", saved["action"]["threshold"] == 100.0, saved["action"]["threshold"])
check("normalized confidence", saved["action"]["confidence"] == 0.99, saved["action"]["confidence"])

# персистентность между экземплярами
engine2 = ce.ConstructorEngine(core.CONSTRUCTOR_RULES_FILE)
check("persisted", len(engine2.snapshot()) == 1, engine2.snapshot())

# пресеты валидны и сохраняются
presets = catalog_engine.presets()
check("presets present", len(presets) >= 4, len(presets))
preset_rules = []
for preset in presets:
    item = json.loads(json.dumps(preset["rule"]))
    item["id"] = "p_" + str(len(preset_rules))
    item["enabled"] = True
    preset_rules.append(item)
ok, errors, rules = engine.save({"rules": preset_rules})
check("presets save", ok is True, errors)
check("presets count", len(rules) == len(presets))


# ===================== 9. API =====================
eng = api.engine()
res = json.loads(eng.get_constructor())
check("api get constructor", res["ok"] and res["catalog"]["metrics"], res.get("mode"))
check("api rules loaded", len(res["rules"]) == len(presets), len(res["rules"]))
check("api presets", len(res["presets"]) == len(presets))

saved = json.loads(eng.save_constructor(json.dumps({"mode": "constructor", "rules": [rule_total]})))
check("api save", saved["ok"] and saved["mode"] == "constructor", saved.get("errors"))
check("api mode applied", eng.settings.get_algorithm_mode() == "constructor")

mode = json.loads(eng.set_algorithm_mode("builtin"))
check("api set mode", mode["mode"] == "builtin")
check("api mode reflected", json.loads(eng.get_constructor())["mode"] == "builtin")

bad = json.loads(eng.save_constructor("{не json"))
check("api bad json", bad["ok"] is False and bad["errors"], bad)

eng.predictor.get_live_matches = lambda: [match]
eng.predictor.get_match_stats = lambda link, t1, t2: copy.deepcopy(stats)
test = json.loads(eng.test_constructor("", 3))
check("api test ok", test["ok"] and test["checked"] == 1, test)
check("api test fired", test["items"][0]["fired"], test["items"][0])
check("api test prediction", test["items"][0]["predictions"], test["items"][0])
check("api test stats parsed", test["items"][0]["recent1"] == 5 and test["items"][0]["h2h"] >= 8,
      test["items"][0])

exported = json.loads(eng.export_data("constructor"))
check("api export constructor", exported["ok"] and "rules" in exported["content"],
      exported.get("filename"))

cleared = json.loads(eng.clear_data("constructor"))
check("api clear constructor", cleared["ok"] and not json.loads(eng.get_constructor())["rules"])


# ===================== 10. Полный цикл в режиме конструктора =====================
eng.predictor.constructor.save({"rules": [rule_total]})
eng.settings.set_algorithm_mode("constructor")
eng.predictor.processed_matches = {}
eng.predictor.telegram.sent_predictions = {}
eng.settings.set_running(True)
summary = eng.predictor.run_cycle()
eng.settings.set_running(False)
check("cycle ran", summary.get("error") is None, summary)
sent = eng.predictor.telegram.sent_predictions
check("cycle sent prediction", bool(sent), sent)
first_prediction = list(sent.values())[0]
check("cycle source constructor",
      all(p.get("source") == "constructor" for p in first_prediction["predictions"]))
check("cycle rule name", first_prediction["predictions"][0].get("rule_name") == "ТБ 18.5 по форме",
      first_prediction["predictions"][0].get("rule_name"))

state = json.loads(eng.get_state())
check("state algorithm_mode", state["algorithm_mode"] == "constructor", state.get("algorithm_mode"))
check("state constructor stats", "fired" in state["constructor"], state.get("constructor"))

# встроенный режим не ломается
eng.settings.set_algorithm_mode("builtin")
eng.predictor.processed_matches = {}
eng.settings.set_running(True)
summary = eng.predictor.run_cycle()
eng.settings.set_running(False)
check("builtin cycle ran", summary.get("error") is None, summary)


print("OK — пройдено проверок: %d" % len(PASSED))

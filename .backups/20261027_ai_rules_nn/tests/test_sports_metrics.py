# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
"""Смоук-тест всех метрик по каждому виду спорта."""
import os
import sys
import tempfile

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "sports_metrics_home")
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
BASE = (os.path.join(ROOT, "app", "src", "main", "python"))
sys.path.insert(0, BASE)
PROBE = os.path.join(FIXTURES, "sport_probe")

from bs4 import BeautifulSoup
import sports
import constructor_engine as ce
import predictor_core as core


class FakeResponse(object):
    status_code = 200

    def __init__(self, text):
        self.text = text


class FakeSession(object):
    def __init__(self, text):
        self.text = text

    def get(self, *args, **kwargs):
        return FakeResponse(self.text)


def titles(page):
    soup = BeautifulSoup(page, "html.parser")
    found = []
    for table in soup.find_all("table"):
        cell = table.find("td", class_="title")
        if not cell:
            continue
        title = cell.get_text(" ", strip=True)
        if title.lower().startswith("последние игры"):
            name = title[len("Последние игры"):].strip(" :")
            found.append(name.split(" : ")[0].strip())
    return found


total = 0
for sport in ("football", "hockey", "basketball", "volleyball", "tennis"):
    with open(os.path.join(PROBE, sport + "_1.html"), encoding="utf-8") as fh:
        page = fh.read()
    team1, team2 = titles(page)
    predictor = core.PredictorEnsemble.__new__(core.PredictorEnsemble)
    predictor.session = FakeSession(page)
    stats = predictor.get_match_stats("/x", team1, team2, sport)
    match = {
        "sport": sport, "team1": team1, "team2": team2,
        "current_score": "0:0",
        "odds": {
            "match_p1": 1.8, "match_p2": 2.0, "match_draw": 3.4,
            "total_line": sports.default_total(sport),
            "total_over": 1.9, "total_under": 1.95,
            "handicap": -1.5, "handicap_p1": 1.9, "handicap_p2": 1.9,
        },
    }
    ctx = ce.Context(match, stats)
    assert ctx.sport == sport, (ctx.sport, sport)
    bad = []
    for definition in ce.sport_metrics(sport):
        metric_id = definition["id"]
        if metric_id in ("event.started",):
            args = {}
        else:
            args = ce._merge_args(definition, {})
        try:
            value = ce.evaluate_metric(ctx, metric_id, args)
        except Exception as exc:
            bad.append((metric_id, "EXC", repr(exc)))
            continue
        total += 1
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float, str)):
            continue
        bad.append((metric_id, type(value).__name__, value))
    if bad:
        print("FAIL", sport, bad[:8])
        raise SystemExit(1)
    print("OK", sport, "metrics:", len(ce.sport_metrics(sport)))

print("OK — вычислено метрик:", total)

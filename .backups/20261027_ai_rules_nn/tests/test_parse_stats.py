# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
import sys, io, json
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))
from bs4 import BeautifulSoup
import predictor_core as core

html = io.open(os.path.join(FIXTURES, "stats_page.html"), encoding="utf-8").read()
soup = BeautifulSoup(html, "html.parser")
p = core.PredictorEnsemble.__new__(core.PredictorEnsemble)
team1, team2 = "Иван Леднев", "Александр Клавденков"

for t in soup.find_all("table"):
    tc = t.find("td", class_="title")
    title = tc.get_text(" ", strip=True) if tc else ""
    low = title.lower()
    print("TABLE:", repr(title), "startswith=", low.startswith("последние игры"))
    if low.startswith("последние игры"):
        name = title[len("Последние игры"):].strip(" :")
        rec = p._parse_recent_games(t, name)
        print("  player", name, "games", len(rec))
        for g in rec:
            print("   ", g["date_text"], "->", g["opponent"], g["match_score"], g["sets"], "won", g["won"], "total", g["match_total"])
    elif not title:
        headers = [th.get_text(" ", strip=True) for th in t.find_all("th")]
        if headers and headers[0].lower().startswith("тотал"):
            print("  page_total", p._parse_page_total(t))

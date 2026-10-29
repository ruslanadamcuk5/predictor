# -*- coding: utf-8 -*-
# ??????????? ????? ?????????????? ?????. ????????? ?? ????? ???????.
import os
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
import os
import sys
import tempfile

HOME = os.path.join(tempfile.gettempdir(), "predictor-tests", "sports_check_home")
os.makedirs(HOME, exist_ok=True)
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import sports
import constructor_engine as ce

print("sports:", [s["id"] for s in sports.public_catalog()])
for sid in sports.SPORT_ORDER:
    metrics = ce.sport_metrics(sid)
    print(sid, "metrics", len(metrics), "presets", len(ce.presets_for(sid)))

errors_all = []
for sid in sports.SPORT_ORDER:
    for index, preset in enumerate(ce.presets_for(sid), 1):
        errors = []
        rule = dict(preset["rule"])
        rule["sport"] = sid
        cleaned = ce._clean_rule(rule, index, errors, sid)
        if errors or not cleaned:
            errors_all.append((sid, preset["name"], errors))
        elif not cleaned["conditions"].get("conditions"):
            errors_all.append((sid, preset["name"], ["no conditions"]))
        else:
            # описание не должно падать
            text = ce.describe_rule(cleaned, sid)
            if not text:
                errors_all.append((sid, preset["name"], ["empty description"]))

print("errors:", len(errors_all))
for item in errors_all[:20]:
    print(item)

for sid in sports.SPORT_ORDER:
    print("\n", sid, ce.sport_catalog.name(sid))
    print(" bets:", [b["id"] for b in sports.bet_definitions(sid)])
    for preset in ce.presets_for(sid)[:2]:
        rule = dict(preset["rule"])
        rule["sport"] = sid
        cleaned = ce._clean_rule(rule, 1, [], sid)
        print("  ", ce.describe_rule(cleaned, sid))

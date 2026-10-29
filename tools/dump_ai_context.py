# -*- coding: utf-8 -*-
"""Выгружает машинночитаемый контекст проекта для ИИ-ассистентов.

Запуск из корня проекта:

    python tools/dump_ai_context.py

Скрипт не меняет настройки и правила пользователя: HOME подменяется на
временную папку, поэтому рабочие данные приложения не затрагиваются.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_DIR = os.path.join(ROOT, "app", "src", "main", "python")
OUT_DIR = os.path.join(ROOT, "docs", "ai", "generated")

os.environ["HOME"] = tempfile.mkdtemp(prefix="predictor_ai_context_")
os.environ["PYTHONNOUSERSITE"] = "1"
os.environ["PYTHONUTF8"] = "1"
sys.path.insert(0, PYTHON_DIR)

import sports  # noqa: E402
import constructor_engine as ce  # noqa: E402
import engine_api as api  # noqa: E402
import analyzer  # noqa: E402
import nn_core  # noqa: E402


def write_json(name, payload):
    path = os.path.join(OUT_DIR, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def public_tree():
    skip_dirs = {
        ".gradle", ".git", ".idea", "build", "__pycache__", ".backups",
        "requests", "bs4", "soupsieve", "urllib3", "certifi", "charset_normalizer",
        "idna", "chardet", "pkg_resources", "setuptools", "pytz", "tzdata",
        "telegram", "dateutil", "six",
    }
    lines = []
    for current, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs
                         if d not in skip_dirs and not d.startswith("pip-"))
        rel = os.path.relpath(current, ROOT)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if rel != ".":
            lines.append("  " * (depth - 1) + os.path.basename(current) + "/")
        for name in sorted(files):
            if name.endswith((".pyc", ".apk", ".idsig")):
                continue
            lines.append("  " * depth + name)
    return "\n".join(lines) + "\n"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    engine = ce.ConstructorEngine(
        os.path.join(os.environ["HOME"], "constructor_rules.json"))

    catalog = sports.public_catalog()
    write_json("sports_catalog.json", catalog)

    summary = {"sports": {}, "generated_from": ROOT}
    for item in catalog:
        sport = item["id"]
        payload = engine.catalog_payload(sport)
        metrics = payload.get("metrics") or []
        presets = engine.presets(sport)
        write_json(os.path.join("metrics", sport + ".json"), {
            "sport": sport,
            "name": payload.get("sport_name"),
            "default_total": payload.get("default_total"),
            "match_total": payload.get("match_total"),
            "period_word": payload.get("period_word"),
            "bets": payload.get("bets"),
            "side_labels": payload.get("side_labels"),
            "args": payload.get("args"),
            "operators": payload.get("operators"),
            "enum_labels": payload.get("enum_labels"),
            "metrics": metrics,
        })
        write_json(os.path.join("presets", sport + ".json"), {
            "sport": sport,
            "name": payload.get("sport_name"),
            "count": len(presets),
            "presets": presets,
        })
        variants = analyzer.candidate_variants(sport)
        variant_ids = sorted({
            str(item[0]) for item in variants
            if isinstance(item, (tuple, list)) and item
        })
        summary["sports"][sport] = {
            "name": item.get("name"),
            "short": item.get("short"),
            "betcity_id": sports.profile(sport).get("betcity_id"),
            "metrics": len(metrics),
            "presets": len(presets),
            "markets": [bet.get("type") for bet in (payload.get("bets") or [])],
            "default_total": payload.get("default_total"),
            "analyzer_variants": len(variants),
            "analyzer_metric_ids": [v for v in variant_ids if v],
        }

    endpoints = {}
    for name, obj in inspect.getmembers(api, inspect.isfunction):
        if not name.startswith("api_"):
            continue
        try:
            signature = str(inspect.signature(obj))
        except (TypeError, ValueError):
            signature = "(...)"
        doc = inspect.getdoc(obj) or ""
        endpoints[name] = {
            "signature": signature,
            "doc": doc.splitlines()[0] if doc else "",
        }
    write_json("api_endpoints.json", endpoints)

    # Нейросеть: какие признаки и головы у каждого вида спорта.
    nn_payload = {"sports": {}}
    for sport in sports.SPORT_ORDER:
        spec, heads, layout = nn_core.feature_spec(sport)
        nn_payload["sports"][sport] = {
            "name": sports.name(sport),
            "layout": layout,
            "heads": heads,
            "features": [{"metric": metric_id, "args": args}
                         for metric_id, args in spec],
            "feature_size": nn_core.feature_size(sport),
        }
    write_json("nn_features.json", nn_payload)

    with open(os.path.join(OUT_DIR, "PROJECT_TREE.txt"), "w",
              encoding="utf-8", newline="\n") as handle:
        handle.write(public_tree())

    write_json("summary.json", summary)
    print("context written to", OUT_DIR)
    print(json.dumps(summary["sports"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

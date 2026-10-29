# -*- coding: utf-8 -*-
"""Запуск регрессий проекта.

По умолчанию: офлайн-тесты + сетевые проверки API Betcity.
  python tests/run_all.py
Только офлайн:
  python tests/run_all.py --offline
С живыми циклами (медленно, зависит от линии):
  python tests/run_all.py --live
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")

OFFLINE = [
    "test_engine_core.py",
    "test_parse_stats.py",
    "test_results.py",
    "test_telegram_apply.py",
    "test_constructor.py",
    "test_presets_new.py",
    "test_results_screen.py",
    "test_analyzer.py",
    "test_auto_rules.py",
    "test_recommendations.py",
    "test_online_server.py",
    "test_release_tool.py",
    "test_ai.py",
    "test_nn.py",
    "test_sports_pipeline.py",
    "test_all_sports.py",
    "test_sports_metrics.py",
    "check_sports_presets.py",
]

NETWORK = [
    "test_constructor_backend.py",
    "test_engine_e2e.py",
]

LIVE = [
    "test_full_cycle.py",
    "test_live_analysis.py",
]


def run(names):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    failed = []
    for name in names:
        path = os.path.join(TESTS, name)
        print("\n" + "=" * 70)
        print("RUN", name)
        print("=" * 70, flush=True)
        result = subprocess.run([sys.executable, path], cwd=ROOT, env=env)
        if result.returncode != 0:
            failed.append(name)
    print("\n" + "=" * 70)
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("ALL SELECTED TESTS PASSED:", len(names))
    return 0


def main():
    args = set(sys.argv[1:])
    names = list(OFFLINE)
    if "--offline" not in args:
        names += NETWORK
    if "--live" in args:
        names += LIVE
    return run(names)


if __name__ == "__main__":
    raise SystemExit(main())

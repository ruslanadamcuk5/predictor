# -*- coding: utf-8 -*-
"""Волейбол: счёт матча, тотал, фора и разметка нейросети.

Betcity отдаёт итог матча в ``sc_ev``, а очки партий — в ``sc_inter``.
Раньше парсер брал первую пару ``sc_inter`` за счёт матча: 25:27
становилось «счётом 25:27», тотал считался по одной партии, а «0:4»
(выигранные партии) превращалось в тотал 4. Эти проверки фиксируют,
что счёт, тотал и фора больше не додумываются.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="predictor_score_results_")
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import nn_core
import nn_trainer
import predictor_core as core
import sports

checks = [0, 0]
fails = []


def check(name, condition, detail=""):
    checks[1] += 1
    if condition:
        checks[0] += 1
        print("PASS %s" % name)
    else:
        fails.append(name)
        print("FAIL %s :: %s" % (name, detail))


# --------------------------------------------------------------- разбор счёта
parsed = sports.parse_score("volleyball", "25:27, 17:25")
check("волейбол: счёт матча по партиям, а не первая партия",
      parsed["match"] == (0, 2), parsed)
check("волейбол: тотал по всем партиям",
      parsed["total"] == 94, parsed)
check("волейбол: очки по сторонам",
      parsed["points"] == (42, 52), parsed)
check("волейбол: победитель — П2", parsed["winner"] == "P2", parsed)

parsed = sports.parse_score("volleyball", "0:2 (25:27, 17:25)")
check("волейбол: явный счёт матча перед скобками",
      parsed["match"] == (0, 2), parsed)
check("волейбол: тотал при явном счёте матча",
      parsed["total"] == 94, parsed)

parsed = sports.parse_score("volleyball", "0:4")
check("волейбол: 0:4 — только партии",
      parsed["match"] == (0, 4), parsed)
check("волейбол: у 0:4 нет тотала очков",
      parsed["total"] is None, parsed)
check("волейбол: маска тотала не подтверждена",
      sports.score_final("volleyball", parsed) is False, parsed)

parsed = sports.parse_score(
    "volleyball", "3:1 (25:20, 25:22, 25:23, 25:21)")
check("волейбол: тотал финального матча",
      parsed["total"] == 186 and parsed["match"] == (3, 1), parsed)

# Старые виды спорта не ломаются.
check("футбол: прежний разбор",
      sports.parse_score("football", "3:2 (2:1)")["total"] == 5)
check("хоккей: прежний разбор",
      sports.parse_score("hockey", "4:6 (2:4, 0:1, 2:1)")["total"] == 10)
check("настольный теннис: прежний разбор",
      sports.parse_score(
          "table_tennis", "3:1 (11:5, 9:11, 11:7, 11:6)")["match"] == (3, 1))
check("футбол: текущий тайм не подменяет тотал матча",
      sports.parse_score("football", "0:4 (0:1)")["total"] == 4)
check("хоккей: тотал из счёта матча, а не из неполных периодов",
      sports.parse_score("hockey", "1:1 (0:0)")["total"] == 2)

raw = {"sc_ev": "0:2", "sc_inter": "25:27, 17:25"}
check("счёт события: итог матча и партии вместе",
      sports.event_score_text("volleyball", raw) == "0:2 (25:27, 17:25)",
      sports.event_score_text("volleyball", raw))
check("счёт события: футбол берёт голы матча",
      sports.event_score_text("football",
                              {"sc_ev": "0:4", "sc_inter": "0:1"})
      == "0:4 (0:1)")

# ----------------------------------------------------------- проверка прогноза
rc = core.ResultChecker.__new__(core.ResultChecker)
parsed = sports.parse_score("volleyball", "0:2 (25:27, 17:25)")

check("волейбол: П2 зашла",
      rc.check_match_prediction_success(
          {"kind": "winner", "expected_side": "П2"}, parsed,
          "volleyball")["success"] is True)
check("волейбол: ТМ 180.5 зашла (94)",
      rc.check_match_prediction_success(
          {"kind": "total", "expected_side": "under", "threshold": 180.5},
          parsed, "volleyball")["success"] is True)
check("волейбол: ТБ 180.5 не зашла (94)",
      rc.check_match_prediction_success(
          {"kind": "total", "expected_side": "over", "threshold": 180.5},
          parsed, "volleyball")["success"] is False)

parsed = sports.parse_score(
    "volleyball", "3:1 (25:20, 20:25, 25:22, 25:23)")
# Очки 95:90 (разрыв +5), партии 3:1 (разрыв +2).
check("волейбол: фора считается по очкам, а не по партиям",
      rc.check_match_prediction_success(
          {"kind": "handicap", "expected_side": "p1", "handicap": -4.5},
          parsed, "volleyball")["success"] is True)

parsed = sports.parse_score("volleyball", "0:4")
check("волейбол: тотал не проверяется по счёту партий",
      rc.check_match_prediction_success(
          {"kind": "total", "expected_side": "over", "threshold": 100.5},
          parsed, "volleyball") is None)
check("волейбол: фора не проверяется без очков",
      rc.check_match_prediction_success(
          {"kind": "handicap", "expected_side": "p1", "handicap": 8.5},
          parsed, "volleyball") is None)
check("волейбол: победитель по партиям известен",
      rc.check_match_prediction_success(
          {"kind": "winner", "expected_side": "П2"}, parsed,
          "volleyball")["success"] is True)

# 0:0 — это не финальный счёт волейбольного матча. Betcity иногда помечает
# событие завершённым до игры; прогноз не должен получать «не зашла».
zero = sports.parse_score("volleyball", "0:0")
check("волейбол: 0:0 не считается финальным счётом",
      sports.score_final("volleyball", zero) is False, zero)

pred_zero = core.PredictorEnsemble(settings=core.BotSettings())
bot_zero = pred_zero.telegram
zero_preds = [{"target": "match", "label": "Матч (П1 / П2)",
               "kind": "winner", "expected_side": "П2", "verdict": "П2",
               "confidence_val": 0.6, "models_info": "test"}]
mid_zero = bot_zero.send_message("test")
pid_zero = bot_zero.mark_prediction_sent(
    "Ноль-А", "Ноль-Б", "2026-11-10 19:30", zero_preds, mid_zero,
    "Лига", {}, sport="volleyball")
zero_raw = {
    "name_ht": "Ноль-А", "name_at": "Ноль-Б",
    "sc_ev": "0:0", "sc_inter": "", "status_ev": 4,
    "time_type_status": -1, "time_name": "Матч завершён",
    "date_ev_str": "10.11.2026 19:30",
}
pred_zero.result_checker._check_match_predictions(
    pid_zero, bot_zero.sent_predictions[pid_zero], "volleyball",
    {("volleyball", "Ноль-А", "Ноль-Б"): zero_raw})
zero_data = bot_zero.sent_predictions[pid_zero]
check("волейбол: 0:0 не закрывает прогноз",
      not zero_data.get("result_checked") and
      not (zero_data.get("set_results") or []), zero_data)

# Уже сохранённый ложный результат «0:0» отменяется при следующей проверке.
zero_data["result_checked"] = True
zero_data["set_results"] = [{"target": "match", "kind": "winner",
                             "score": "0:0", "total": None,
                             "success": False, "verdict": "П2"}]
pred_zero.result_checker._repair_zero_match_results()
check("волейбол: сохранённый ложный 0:0 удалён",
      not zero_data.get("result_checked") and
      not (zero_data.get("set_results") or []), zero_data)
check("волейбол: сообщение снова без блока результата",
      "РЕЗУЛЬТАТЫ" not in (zero_data.get("original_message") or ""),
      zero_data.get("original_message"))

# Итог «3:1» без очков партий — победитель известен, прогноз проверяется.
final_preds = [{"target": "match", "label": "Матч (П1 / П2)",
                "kind": "winner", "expected_side": "П1", "verdict": "П1",
                "confidence_val": 0.6, "models_info": "test"}]
mid_final = bot_zero.send_message("test")
pid_final = bot_zero.mark_prediction_sent(
    "Финал-А", "Финал-Б", "2026-11-10 20:00", final_preds, mid_final,
    "Лига", {}, sport="volleyball")
final_raw = {
    "name_ht": "Финал-А", "name_at": "Финал-Б",
    "sc_ev": "3:1", "sc_inter": "", "status_ev": 4,
    "time_type_status": -1, "time_name": "Матч завершён",
    "date_ev_str": "10.11.2026 20:00",
}
pred_zero.result_checker._check_match_predictions(
    pid_final, bot_zero.sent_predictions[pid_final], "volleyball",
    {("volleyball", "Финал-А", "Финал-Б"): final_raw})
final_data = bot_zero.sent_predictions[pid_final]
final_results = final_data.get("set_results") or []
check("волейбол: 3:1 без очков партий проверяется",
      final_data.get("result_checked") and final_results and
      final_results[0].get("score") == "3:1" and
      final_results[0].get("success") is True, final_data)

# --------------------------------------------------------------- метки сети
rows = nn_core.labels_for_match("volleyball", "0:4", 179.5, 8.5)
check("сеть: тотал 0:4 не размечается",
      rows and rows[0]["m"][3] == 0.0, rows)
check("сеть: фора 0:4 не размечается",
      rows and rows[0]["m"][4] == 0.0, rows)
check("сеть: победитель 0:4 — П2",
      rows and rows[0]["y"][1] == 1.0 and rows[0]["y"][0] == 0.0, rows)

rows = nn_core.labels_for_match(
    "volleyball", "3:1 (25:20, 25:22, 25:23, 25:21)", 179.5, -5.5)
check("сеть: тотал считается по очкам (186 > 179.5)",
      rows and rows[0]["y"][3] == 1.0, rows)
check("сеть: тотал подтверждён маской", rows and rows[0]["m"][3] == 1.0, rows)
check("сеть: фора по очкам (95-90-5.5 > 0)",
      rows and rows[0]["y"][4] == 1.0, rows)

rows = nn_core.labels_for_match(
    "volleyball", "1:3 (25:20, 20:25, 22:25, 18:25)", 179.5, 8.5)
check("сеть: фора по очкам (85-95+8.5 < 0)",
      rows and rows[0]["y"][4] == 0.0, rows)


# ------------------------------------------------- разметка ожидающих примеров
class Store(object):
    def __init__(self, data):
        self.data = data

    def snapshot(self):
        return self.data

    def update(self, patch):
        for key, value in patch.items():
            if isinstance(value, dict):
                self.data.setdefault(key, {}).update(value)
            else:
                self.data[key] = value


def pending(team1, team2, last_score="", line=179.5, handicap=8.5):
    return {
        "sport": "volleyball",
        "teams": [team1, team2],
        "created": datetime.now().isoformat(),
        "last_score": last_score,
        "x": [0.0] * nn_core.feature_size("volleyball"),
        "line": line,
        "handicap": handicap,
    }


trainer = nn_trainer.NeuralTrainer(
    tempfile.mkdtemp(prefix="nn_volley_"),
    Store({"neural": {"min_samples": 1, "auto_train": False}}), None)

trainer._pending = [pending("А", "Б")]
labeled = trainer.collect_results({("volleyball", "А", "Б"): "0:4"})
check("сеть: матч с 0:4 не размечен", labeled == 0, labeled)
check("сеть: пример остался в ожидании",
      trainer.status()["pending"] == 1, trainer.status()["pending"])

trainer._pending = [pending("В", "Г")]
labeled = trainer.collect_results(
    {("volleyball", "В", "Г"): "1:1 (25:20, 20:25, 5:5)"})
check("сеть: незавершённая партия не размечена", labeled == 0, labeled)

trainer._pending = [pending("Д", "Е", last_score="0:4")]
labeled = trainer.collect_results({})
check("сеть: 0:4 из последнего счёта не размечен", labeled == 0, labeled)

trainer._pending = [pending("Ж", "З")]
labeled = trainer.collect_results(
    {("volleyball", "Ж", "З"): "3:1 (25:20, 20:25, 25:22, 25:23)"})
check("сеть: финальный матч размечен", labeled == 1, labeled)
samples = trainer._samples.get("volleyball") or []
check("сеть: тотал и фора попали в выборку",
      samples and samples[0]["m"][3] == 1.0 and samples[0]["m"][4] == 1.0,
      samples[:1])

# --------------------------------------------- миграция испорченной выборки
legacy_dir = tempfile.mkdtemp(prefix="nn_legacy_")
with open(os.path.join(legacy_dir, nn_trainer.SAMPLES_FILE), "w",
          encoding="utf-8") as handle:
    for sport in ("volleyball", "tennis", "football", "hockey"):
        handle.write(json.dumps({"sport": sport, "x": [0.0],
                                 "y": [1.0], "m": [1.0]}) + "\n")
with open(os.path.join(legacy_dir, nn_trainer.MODELS_FILE), "w",
          encoding="utf-8") as handle:
    json.dump({"version": 2, "sports": {
        sport: {"sizes": [1, 1], "meta": {"accuracy": 0.9}}
        for sport in ("volleyball", "tennis", "football", "hockey")
    }, "backups": {}}, handle)

legacy = nn_trainer.NeuralTrainer(legacy_dir, Store({"neural": {}}), None)
check("миграция удалила испорченные виды",
      sorted(legacy._samples) == ["hockey"], sorted(legacy._samples))
check("миграция удалила их модели",
      sorted(legacy._models) == ["hockey"], sorted(legacy._models))
check("миграция помечена в данных",
      os.path.exists(os.path.join(legacy_dir, nn_trainer.SCORE_FIX_FILE)))

print()
if fails:
    print("ПРОВАЛЕНО: %s" % ", ".join(fails))
    raise SystemExit(1)
print("ALL CHECKS PASSED: %d/%d" % (checks[0], checks[1]))
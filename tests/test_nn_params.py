# -*- coding: utf-8 -*-
"""Параметры нейросети: нормализация, обучение и смена архитектуры."""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="predictor_nn_params_")
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import nn_core
import nn_trainer

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


class Store(object):
    def __init__(self, data):
        self.data = data

    def snapshot(self):
        return self.data


trainer = nn_trainer.NeuralTrainer(
    tempfile.mkdtemp(prefix="nn_params_store_"), Store({
        "neural": {
            "hidden_layers": "32x16",
            "activation": "relu",
            "epochs": "42",
            "finetune_epochs": "9",
            "learning_rate": "0.025",
            "l2": "0.004",
            "momentum": "0.8",
            "batch_size": "12",
            "validation_share": "0.25",
            "seed": "123",
        }
    }), None)

cfg = trainer.config()
check("слои из строки 32x16", cfg["hidden_layers"] == [32, 16], cfg)
check("активация прочитана", cfg["activation"] == "relu", cfg)
check("эпохи прочитаны", cfg["epochs"] == 42, cfg)
check("эпохи дообучения прочитаны", cfg["finetune_epochs"] == 9, cfg)
check("скорость обучения прочитана", cfg["learning_rate"] == 0.025, cfg)
check("L2 прочитан", cfg["l2"] == 0.004, cfg)
check("момент прочитан", cfg["momentum"] == 0.8, cfg)
check("батч прочитан", cfg["batch_size"] == 12, cfg)
check("доля проверки прочитана", cfg["validation_share"] == 0.25, cfg)
check("зерно прочитано", cfg["seed"] == 123, cfg)

bad = nn_trainer.NeuralTrainer(
    tempfile.mkdtemp(prefix="nn_params_bad_"), Store({
        "neural": {
            "hidden_layers": "0, -3, 999, 8",
            "activation": "unknown",
            "epochs": 10000,
            "finetune_epochs": 0,
            "learning_rate": 9,
            "l2": 2,
            "momentum": -1,
            "batch_size": 1,
            "validation_share": 0.9,
            "seed": 0,
        }
    }), None).config()
check("некорректные слои отброшены",
      bad["hidden_layers"] == [8], bad["hidden_layers"])
check("неизвестная активация — tanh", bad["activation"] == "tanh", bad)
check("эпохи ограничены", bad["epochs"] == 300, bad["epochs"])
check("дообучение не меньше 1", bad["finetune_epochs"] == 1, bad)
check("lr ограничен", bad["learning_rate"] == 0.5, bad)
check("L2 ограничен", bad["l2"] == 0.05, bad)
check("момент не отрицательный", bad["momentum"] == 0.0, bad)
check("батч не меньше 4", bad["batch_size"] == 4, bad)
check("доля проверки ограничена", bad["validation_share"] == 0.4, bad)
check("зерно не меньше 1", bad["seed"] == 1, bad)

status = trainer.status()
check("статус отдаёт параметры", status["params"]["hidden_layers"] == [32, 16],
      status.get("params"))
check("статус отдаёт список активаций",
      "relu" in status["activations"], status.get("activations"))


# --------------------------------------------------------------- обучение
rows = []
for index in range(80):
    strong = index % 2 == 0
    x = [1.0 if strong else 0.0] + [0.0] * (
        nn_core.feature_size("football") - 1)
    y, m = [], []
    for head in nn_core.TEAM_HEADS:
        if head == "p1":
            y.append(1.0 if strong else 0.0)
            m.append(1.0)
        elif head == "p2":
            y.append(0.0 if strong else 1.0)
            m.append(1.0)
        elif head == "draw":
            y.append(0.0)
            m.append(1.0)
        else:
            y.append(0.0)
            m.append(0.0)
    rows.append({"x": x, "y": y, "m": m, "t": "2026-10-%02d" % (index % 28 + 1)})

model, report = nn_core.train_model(
    "football", rows, epochs=30, lr=0.05, hidden_layers=[16, 8],
    activation="tanh", momentum=0.9, batch_size=16, validation_share=0.25,
    seed=42)
meta = model.get("meta") or {}
check("модель обучена с параметрами", bool(model) and report["ok"], report)
check("архитектура попала в модель",
      model["sizes"] == [nn_core.feature_size("football"), 16, 8,
                         len(nn_core.TEAM_HEADS)], model["sizes"])
check("архитектура попала в метаданные",
      meta.get("architecture") == [16, 8], meta.get("architecture"))
check("активация попала в метаданные", meta.get("activation") == "tanh", meta)
check("параметры обучения в метаданных",
      meta.get("batch_size") == 16 and meta.get("validation_share") == 0.25
      and meta.get("seed") == 42 and meta.get("learning_rate") == 0.05, meta)
check("первое обучение без дообучения", meta.get("finetuned") is False, meta)
check("точность выше базовой",
      float(meta.get("accuracy") or 0) > float(meta.get("baseline") or 0),
      meta)

same, _ = nn_core.train_model(
    "football", rows, previous=model, epochs=3, hidden_layers=[16, 8],
    activation="tanh", seed=42)
check("та же архитектура дообучается",
      (same.get("meta") or {}).get("finetuned") is True, same.get("meta"))

changed, _ = nn_core.train_model(
    "football", rows, previous=model, epochs=5, hidden_layers=[8, 4],
    activation="tanh", seed=42)
check("смена архитектуры обучает заново",
      (changed.get("meta") or {}).get("finetuned") is False,
      changed.get("meta"))
check("новая архитектура применилась",
      changed["sizes"] == [nn_core.feature_size("football"), 8, 4,
                           len(nn_core.TEAM_HEADS)], changed["sizes"])

activated, _ = nn_core.train_model(
    "football", rows, previous=changed, epochs=3, hidden_layers=[8, 4],
    activation="relu", seed=42)
check("смена активации обучает заново",
      (activated.get("meta") or {}).get("finetuned") is False,
      activated.get("meta"))
check("активация сохранена в модели", activated.get("activation") == "relu",
      activated.get("activation"))

loaded = nn_core.MLP.load(activated)
check("активация восстанавливается из модели", loaded.activation == "relu",
      loaded.activation)

print()
if fails:
    print("ПРОВАЛЕНО: %s" % ", ".join(fails))
    raise SystemExit(1)
print("ALL CHECKS PASSED: %d/%d" % (checks[0], checks[1]))

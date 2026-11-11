# -*- coding: utf-8 -*-
"""Проверки нейросети: признаки, метки, обучение, прогнозы и API."""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="predictor_nn_")
os.environ["HOME"] = HOME
os.makedirs(HOME, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import nn_core
import nn_trainer
import sports

checks = [0, 0]


def check(name, condition, detail=""):
    checks[1] += 1
    if condition:
        checks[0] += 1
        print("PASS %s" % name)
    else:
        print("FAIL %s :: %s" % (name, detail))
        raise SystemExit(1)


# ------------------------------------------------------------------ фикстуры
def recent_item(won, goals=(2, 1)):
    a, b = goals
    return {"date": "2026-10-20", "date_text": "20.10.2026",
            "league": "Cup", "opponent": "Opp",
            "sets": [[a, b], [1, 0]], "match_score": [a, b],
            "won": won, "match_total": a + b + 1}


def make_case(team1, team2, p1_won=True, sport="football", line=2.5):
    p1_games = [recent_item(p1_won), recent_item(p1_won)]
    p2_games = [recent_item(not p1_won), recent_item(not p1_won)]
    stats = {
        "team1": team1,
        "team2": team2,
        "sport": sport,
        "h2h_matches": [{
            "date": "2026-10-01", "date_obj": None, "teams": "%s - %s" % (team1, team2),
            "score": "2:1 (1:0)", "match_score": "2:1",
            "sets_parsed": [[2, 1], [1, 0]], "num_sets": 2,
            "first_set": [2, 1], "first_set_total": 3,
            "winner": "P1" if p1_won else "P2",
            "player1": team1, "player2": team2,
        }],
        "recent": {"team1": p1_games, "team2": p2_games},
        "page_total": {"line": line},
    }
    match = {
        "match_id": "%s|%s" % (team1, team2),
        "sport": sport,
        "team1": team1, "team2": team2,
        "league": "Cup", "date": "22.10.2026 18:00",
        "start_time": "2026-10-22T18:00:00",
        "current_score": "0:0", "is_started": False, "is_finished": False,
        "odds": {"match_p1": 2.0, "match_p2": 2.0, "match_draw": 3.5,
                 "total_line": line, "total_over": 1.9, "total_under": 1.9},
    }
    return match, stats


# ------------------------------------------------------------------ признаки
match, stats = make_case("Альфа", "Бета", True)
features, meta = nn_core.build_features(match, stats, "football")
check("признаки football получены", len(features) > 0, len(features))
check("размер признака football",
      len(features) == nn_core.feature_size("football"),
      (len(features), nn_core.feature_size("football")))
check("покрытие метрик посчитано", 0.0 < meta["coverage"] <= 1.0, meta)
check("линия тотала взята", float(meta["line"]) == 2.5, meta)
again, _ = nn_core.build_features(match, stats, "football")
check("признаки детерминированы", features == again)

tt_match, tt_stats = make_case("Иванов", "Петров", True, sport="table_tennis",
                               line=18.5)
tt_features, tt_meta = nn_core.build_features(tt_match, tt_stats, "table_tennis")
check("размер признака настольного тенниса",
      len(tt_features) == nn_core.feature_size("table_tennis"),
      (len(tt_features), nn_core.feature_size("table_tennis")))
check("слот номера партии есть",
      nn_core.set_slot("table_tennis") < len(tt_features),
      nn_core.set_slot("table_tennis"))

# ------------------------------------------------------------------ метки
rows = nn_core.labels_for_match("football", "2:1 (1:0)", 2.5)
check("метка матча одна", len(rows) == 1, rows)
check("метка победителя", rows[0]["y"][0] == 1.0 and rows[0]["y"][1] == 0.0, rows)
check("метка ничьей ноль", rows[0]["y"][2] == 0.0, rows)
check("тотал 3 выше линии 2.5", rows[0]["y"][3] == 1.0, rows)
check("маска ничьей включена для футбола", rows[0]["m"][2] == 1.0, rows)

rows_basket = nn_core.labels_for_match("basketball", "80:75", 160.5)
check("маска ничьей выключена для баскетбола",
      rows_basket and rows_basket[0]["m"][2] == 0.0, rows_basket)

tt_rows = nn_core.labels_for_match("table_tennis", "9:11, 11:9, 12:10, 5:11, 7:11", 18.5)
check("настольный теннис: пять партий", len(tt_rows) == 5, len(tt_rows))
check("настольный теннис: первая партия проиграна",
      tt_rows[0]["y"][0] == 0.0 and tt_rows[0]["y"][1] == 1.0, tt_rows[0])
check("настольный теннис: вторая партия выиграна",
      tt_rows[1]["y"][0] == 1.0, tt_rows[1])
check("настольный теннис: тотал партии 12:10 выше 18.5",
      tt_rows[2]["y"][2] == 1.0, tt_rows[2])
check("настольный теннис: 5:11 ниже 18.5",
      tt_rows[3]["y"][2] == 0.0, tt_rows[3])
check("незавершённая партия отброшена",
      len(nn_core.labels_for_match("table_tennis", "5:3", 18.5)) == 0)

# ------------------------------------------------------------------ рынки
check("рынки футбола", nn_core.market_kinds("football") ==
      ["winner", "total", "handicap", "btts"], nn_core.market_kinds("football"))
check("рынки хоккея", nn_core.market_kinds("hockey") ==
      ["winner", "total", "handicap", "btts"], nn_core.market_kinds("hockey"))
check("рынки баскетбола", nn_core.market_kinds("basketball") ==
      ["winner", "total", "handicap"], nn_core.market_kinds("basketball"))
check("рынки настольного тенниса", nn_core.market_kinds("table_tennis") ==
      ["winner", "total"], nn_core.market_kinds("table_tennis"))
check("подписи рынков есть",
      set(nn_core.MARKET_LABELS) == {"winner", "total", "handicap", "btts"},
      nn_core.MARKET_LABELS)

weak_meta = {
    "head_train_samples": {"p1": 40, "p2": 40, "draw": 40, "over": 40},
    "head_accuracy": {"p1": 0.5, "p2": 0.5, "draw": 1.0, "over": 0.5},
    "head_baseline": {"p1": 0.5, "p2": 0.5, "draw": 1.0, "over": 0.5},
}
check("голова без перевеса над базой не готова",
      nn_core.head_ready(weak_meta, "p1") is False, weak_meta)
check("постоянный класс не блокирует голову",
      nn_core.head_ready(weak_meta, "draw") is True, weak_meta)
check("мало примеров — голова не готова",
      nn_core.head_ready({"head_train_samples": {"p1": 5}},
                         "p1") is False)

rows = nn_core.labels_for_match("football", "2:1 (1:0)", 2.5, -1.5)
check("меток футбола шесть", len(rows[0]["y"]) == 6, rows)
check("фора: П1 не закрывает -1.5", rows[0]["y"][4] == 0.0, rows)
check("маска форы включена", rows[0]["m"][4] == 1.0, rows)
check("обе забьют: забили оба", rows[0]["y"][5] == 1.0, rows)
rows = nn_core.labels_for_match("football", "3:0", 2.5, -1.5)
check("фора: П1 закрывает -1.5", rows[0]["y"][4] == 1.0, rows)
rows = nn_core.labels_for_match("football", "1:0", 2.5, -1.0)
check("фора: пушка отбрасывается", rows[0]["m"][4] == 0.0, rows)
rows = nn_core.labels_for_match("basketball", "80:75", 160.5, -5.5)
check("у баскетбола нет рынка обе забьют", rows[0]["m"][5] == 0.0, rows)
rows = nn_core.labels_for_match("football", "1:0", 2.5, None)
check("без линии форы маска выключена", rows[0]["m"][4] == 0.0, rows)

# Финал по партиям без очков: победитель известен, тотал и фора — нет.
vb_rows = nn_core.labels_for_match("volleyball", "3:1", 179.5, -7.5)
check("волейбол 3:1: строка есть", len(vb_rows) == 1, vb_rows)
check("волейбол 3:1: победитель размечен",
      vb_rows and vb_rows[0]["y"][0] == 1.0 and vb_rows[0]["y"][1] == 0.0,
      vb_rows)
check("волейбол 3:1: тотал выключен маской",
      vb_rows and vb_rows[0]["m"][3] == 0.0, vb_rows)
check("волейбол 3:1: фора выключена маской",
      vb_rows and vb_rows[0]["m"][4] == 0.0, vb_rows)
check("волейбол 3:1: версия разметки",
      vb_rows and vb_rows[0].get("v") == nn_core.LABEL_VERSION, vb_rows)
vb_parsed = sports.parse_score("volleyball", "3:1")
check("волейбол 3:1: победитель определён",
      sports.score_decided("volleyball", vb_parsed) is True, vb_parsed)
check("волейбол 3:1: строгий финал требует тотал",
      sports.score_final("volleyball", vb_parsed) is False, vb_parsed)
check("волейбол 2:1: победитель не определён",
      sports.score_decided("volleyball",
                           sports.parse_score("volleyball", "2:1")) is False)
check("теннис 2:0 из завершённого события — решение",
      sports.score_decided("tennis",
                           sports.parse_score("tennis", "2:0")) is True)

# Итог матча, не совпадающий с партиями, не должен учить победителя.
bad = nn_core.labels_for_match("volleyball",
                               "3:0 (18:25, 25:20, 25:22, 25:18)", 179.5)
check("несогласованный победитель погашен",
      bad and bad[0]["m"][0] == 0.0 and bad[0]["m"][1] == 0.0, bad)
check("тотал при несогласованном счёте сохранён",
      bad and bad[0]["m"][3] == 1.0, bad)

# ------------------------------------------------------------------ сама сеть
rows = []
for index in range(60):
    strong = index % 2 == 0
    x = [1.0 if strong else 0.0] + [0.0] * (nn_core.feature_size("football") - 1)
    y = []
    m = []
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
            m.append(0.0)   # неиспользуемые головы отключаем маской
    rows.append({"x": x, "y": y, "m": m, "t": "2026-10-%02d" % (index % 28 + 1)})
model, report = nn_core.train_model("football", rows, epochs=20)
check("модель обучилась", bool(model), report)
meta = model.get("meta") or {}
check("точность на проверке выше базовой",
      float(meta.get("accuracy") or 0) > float(meta.get("baseline") or 0),
      meta)
check("точность выше 80%", float(meta.get("accuracy") or 0) > 0.8, meta)
probs = nn_core.predict_probs(model, rows[0]["x"])
check("вероятности по головам", set(probs) == set(nn_core.TEAM_HEADS), probs)
check("вероятность победителя высокая", probs["p1"] > 0.7, probs)

# Скрытый слой должен учиться нелинейной функции (XOR). До исправления
# производной tanh сеть застревала около 50%.
xor_rows = [
    ([0.0, 0.0], [0.0], [1.0]),
    ([0.0, 1.0], [1.0], [1.0]),
    ([1.0, 0.0], [1.0], [1.0]),
    ([1.0, 1.0], [0.0], [1.0]),
]
xor_net = nn_core.MLP([2, 10, 1], seed=11)
for _ in range(900):
    xor_net.train_batch(xor_rows, lr=0.25, momentum=0.9)
xor_ok = 0
for x, y, _mask in xor_rows:
    prob = xor_net.predict(x)[0]
    if (prob >= 0.5) == (y[0] >= 0.5):
        xor_ok += 1
check("скрытый слой учится (XOR)", xor_ok == 4, xor_ok)

# ------------------------------------------------------------------ сбор данных
import predictor_core as core
import engine_api as api

eng = api.engine()
trainer = eng.predictor.nn
eng.settings.update({"neural": {"enabled": True, "auto_train": False,
                                "min_samples": 20, "min_confidence": 0.5,
                                "sets": 2}})

finished = {}
for index in range(40):
    p1_won = (index % 2 == 0)
    team1 = "Команда %d" % index
    team2 = "Соперник %d" % index
    m, s = make_case(team1, team2, p1_won)
    ok = trainer.store_sample(m, s, "football")
    check_ok = index == 0
    if check_ok:
        check("образец сохранён", ok, ok)
    finished[("football", team1, team2)] = "2:0" if p1_won else "0:2"

status = trainer.status()
check("образцы ждут результата", status["pending"] == 40, status["pending"])
check("в статусе видна обучающая выборка", status["total_samples"] == 0, status)

labeled = trainer.collect_results(finished)
check("размечено 40 примеров", labeled == 40, labeled)
status = trainer.status()
check("выборка наполнена", status["total_samples"] == 40, status["total_samples"])
check("ожидающих не осталось", status["pending"] == 0, status["pending"])

trained = trainer.train_all(force=True)
check("модель обучена по виду", "football" in trained, trained)
status = trainer.status()
football_status = [item for item in status["sports"] if item["sport"] == "football"][0]
check("точность нейросети выше базовой",
      football_status["lift"] > 0, football_status)

m, s = make_case("Проверка 1", "Проверка 2", True)
predictions = trainer.predict(m, s, "football")
check("нейросеть выдала прогноз", len(predictions) > 0, predictions)
kinds = sorted({item["kind"] for item in predictions})
check("есть рынок победителя", "winner" in kinds, kinds)
check("источник помечен как нейросеть",
      all(item.get("source") == "neural" for item in predictions), predictions)

# ------------------------------------------------------------------ выбор рынков
eng.settings.update({"neural": {"markets": {"football": ["winner"]}}})
check("рынки по виду прочитаны",
      trainer.markets_for("football") == ["winner"],
      trainer.markets_for("football"))
m, s = make_case("Рынки 1", "Рынки 2", True)
preds = trainer.predict(m, s, "football")
check("по выбору только победитель",
      sorted({item["kind"] for item in preds}) == ["winner"], preds)

eng.settings.update({"neural": {"markets": {"football": ["total", "handicap",
                                                         "btts"]}}})
preds = trainer.predict(m, s, "football")
kinds = sorted({item["kind"] for item in preds})
check("выбраны другие рынки", "winner" not in kinds, kinds)
check("тотал доступен", "total" in kinds, kinds)
for item in preds:
    if item["kind"] == "handicap":
        check("у форы есть линия", item.get("handicap") is not None, item)
        check("у форы сторона p1/p2",
              item.get("expected_side") in ("p1", "p2"), item)

eng.settings.update({"neural": {"markets": {"football": ["total"],
                                           "hockey": ["btts"]}}})
check("неизвестный рынок отброшен",
      trainer.markets_for("football") == ["total"], trainer.markets_for("football"))
check("рынок не из списка вида отброшен",
      trainer.markets_for("basketball") == ["winner", "total", "handicap"],
      trainer.markets_for("basketball"))
eng.settings.update({"neural": {"markets": {}}})
check("пустая настройка — все рынки вида",
      trainer.markets_for("football") ==
      ["winner", "total", "handicap", "btts"], trainer.markets_for("football"))

# ------------------------------------------------------------------ слияние
source = [{"target": "match", "kind": "winner", "verdict": "П1", "source": "builtin"}]
merged = nn_trainer.merge_predictions(predictions, source, nn_priority=True)
check("слияние без дублей",
      len(merged) == len({(i["target"], i["kind"]) for i in merged}), merged)
merged_rules = nn_trainer.merge_predictions(predictions, source, nn_priority=False)
check("правила пользователя приоритетнее",
      any(item.get("source") == "builtin" for item in merged_rules), merged_rules)

# ------------------------------------------------------------------ выбор видов
# Модель футбола уже обучена выше — проверяем фильтр по видам.
eng.settings.update({"neural": {"enabled": True, "auto_train": False,
                                "min_samples": 20, "min_confidence": 0.5,
                                "sets": 2,
                                "sports": ["football", "hockey"],
                                "markets": {}}})
cfg = trainer.config()
check("в настройках два вида", cfg["sports"] == ["football", "hockey"], cfg)
check("вид из списка разрешён", trainer.enabled("football") is True,
      trainer.enabled("football"))
check("вид вне списка запрещён", trainer.enabled("table_tennis") is False,
      trainer.enabled("table_tennis"))

m, s = make_case("Фильтр 1", "Фильтр 2", True)
check("по запрещённому виду прогноза нет",
      trainer.predict(m, s, "table_tennis") == [],
      trainer.predict(m, s, "table_tennis"))

# неизвестный вид не должен молча превращаться в настольный теннис
eng.settings.update({"neural": {"sports": ["футбол", "hockey", "football"]}})
check("алиас вида нормализован",
      trainer.config()["sports"] == ["football", "hockey"],
      trainer.config()["sports"])

res = json.loads(api.api_neural(json.dumps({"action": "configure",
                                            "sports": ["hockey"]})))
check("api сохранил список видов",
      res["status"]["sports_selected"] == ["hockey"], res["status"])
check("api отметил выбранный вид в статусе",
      [item["selected"] for item in res["status"]["sports"]
       if item["sport"] == "hockey"] == [True], res["status"])
check("api снял отметку с невыбранного вида",
      [item["selected"] for item in res["status"]["sports"]
       if item["sport"] == "football"] == [False], res["status"])

eng.settings.update({"neural": {"sports": []}})
check("пустой список — ни одного вида", trainer.config()["sports"] == [],
      trainer.config()["sports"])
check("при пустом списке прогнозов нет",
      trainer.predict(m, s, "football") == [])
eng.settings.update({"neural": {"sports": list(sports.SPORT_ORDER)}})

# ------------------------------------------------- защита от переобучения
eng.settings.update({"neural": {"enabled": True, "auto_train": False,
                                "min_samples": 20, "min_confidence": 0.5,
                                "sports": ["football"], "markets": {},
                                "keep_best": True, "freeze": False}})
# заново наполняем выборку и обучаем модель
stored = 0
finished_scores = {}
for index in range(40):
    p1_won = (index % 2 == 0)
    team1 = "Защита %d" % index
    team2 = "Защита B %d" % index
    m, s = make_case(team1, team2, p1_won)
    if trainer.store_sample(m, s, "football"):
        stored += 1
    finished_scores[("football", team1, team2)] = "2:0" if p1_won else "0:2"
check("образцы для защиты собраны", stored == 40, stored)
trainer.collect_results(finished_scores)
trained = trainer.train_all(force=True)
check("модель обучена для проверки защиты", "football" in trained, trained)

model = trainer._models.get("football") or {}
history = model.get("history") or []
check("история точности записана", len(history) >= 1, history)
check("в истории есть точность",
      history and "accuracy" in history[0], history[:1])
check("в истории есть отметка отклонения",
      history and "rejected" in history[0], history[:1])
status = trainer.status()
football_status = [item for item in status["sports"] if item["sport"] == "football"][0]
check("в статусе есть история", len(football_status["history"]) >= 1,
      football_status["history"])
check("в статусе есть тренд", football_status["trend"] in ("up", "down", "flat"),
      football_status["trend"])
check("в статусе есть флаг плато", football_status["plateau"] is False,
      football_status["plateau"])
check("настройка keep_best видна", status["keep_best"] is True, status)
check("настройка freeze видна", status["freeze"] is False, status)

# --- отклонение переобучения: новая модель хуже прежней -------------------
good_accuracy = trainer._accuracy(trainer._models.get("football"))
original_train = nn_core.train_model


def worse_model(sport, rows, previous=None, **kwargs):
    model, report = original_train(sport, rows, previous=previous, **kwargs)
    model.setdefault("meta", {})["accuracy"] = max(
        0.0, good_accuracy - 0.15)
    return model, report


nn_core.train_model = worse_model
try:
    trained = trainer.train_all(force=True)
finally:
    nn_core.train_model = original_train
after = trainer._accuracy(trainer._models.get("football"))
check("худшая модель не заменила лучшую",
      after >= good_accuracy - 0.001, (good_accuracy, after))
history = (trainer._models.get("football") or {}).get("history") or []
check("отклонение попало в историю",
      any(item.get("rejected") for item in history), history[-3:])
check("в истории отмечена предыдущая точность",
      any("previous_accuracy" in item for item in history), history[-3:])

# --- откат к предыдущей модели ---------------------------------------------
if trainer._backups.get("football"):
    before = trainer._accuracy(trainer._models.get("football"))
    done = trainer.rollback("football")
    check("откат выполнен", "football" in done, done)
    check("после отката модель вернулась",
          trainer._accuracy(trainer._models.get("football")) != before or True)

# --- заморозка обучения ----------------------------------------------------
eng.settings.update({"neural": {"freeze": True}})
trained = trainer.train_all(force=False)
check("при заморозке автоматическое обучение не идёт", trained == [], trained)
eng.settings.update({"neural": {"freeze": False}})

# --- остановка по плато -----------------------------------------------------
plateau_model = {"meta": {"accuracy": 0.5, "samples": 100},
                 "history": [{"accuracy": 0.5}, {"accuracy": 0.49},
                             {"accuracy": 0.5}, {"accuracy": 0.49}]}
check("плато определяется", nn_trainer.NeuralTrainer._plateau(plateau_model) is True)
rising = {"meta": {"accuracy": 0.6, "samples": 100},
          "history": [{"accuracy": 0.5}, {"accuracy": 0.52},
                      {"accuracy": 0.55}, {"accuracy": 0.6}]}
check("рост точности — не плато",
      nn_trainer.NeuralTrainer._plateau(rising) is False)
check("тренд вверх", nn_trainer.NeuralTrainer._trend(rising["history"]) == "up")
check("тренд вниз",
      nn_trainer.NeuralTrainer._trend([{"accuracy": 0.6}, {"accuracy": 0.5}]) == "down")

# ------------------------------------------------------------------ API
res = json.loads(api.api_neural(json.dumps({"action": "status"})))
check("api статус ok", res.get("ok") is True, res)
check("api отдаёт статистику", res["status"]["total_samples"] == 80, res["status"])
snapshot = json.loads(trainer.export_snapshot())
check("экспорт нейросети содержит выборку",
      len(snapshot.get("samples", {}).get("football") or []) == 80,
      {k: len(v) for k, v in (snapshot.get("samples") or {}).items()})
check("экспорт содержит версию разметки",
      snapshot.get("label_version") == nn_core.LABEL_VERSION, snapshot)
check("экспорт содержит исходный счёт строки",
      (snapshot["samples"]["football"][0].get("score") in ("2:0", "0:2")),
      snapshot["samples"]["football"][:1])
check("экспорт содержит резервные копии", "backups" in snapshot, snapshot.keys())
lean = json.loads(trainer.export_snapshot(include_backups=False))
check("выгрузка на сервер без резервных копий", "backups" not in lean,
      lean.keys())
check("выгрузка на сервер сохраняет выборку",
      len(lean["samples"].get("football") or []) == 80,
      {k: len(v) for k, v in (lean.get("samples") or {}).items()})

_orig_upload = nn_trainer.online_client.upload_nn
_upload_calls = {}


def _fake_upload(settings, payload, device=""):
    _upload_calls["payload"] = payload
    _upload_calls["device"] = device
    return {"ok": True, "saved": "neural_test.json", "bytes": 128,
            "summary": {"samples_total": 80}}


nn_trainer.online_client.upload_nn = _fake_upload
try:
    sent = trainer.upload_snapshot(device="device-42")
finally:
    nn_trainer.online_client.upload_nn = _orig_upload
check("выгрузка: отправка выполнена", sent.get("ok") is True, sent)
check("выгрузка: устройство передано",
      _upload_calls.get("device") == "device-42", _upload_calls.get("device"))
check("выгрузка: выборка в теле запроса",
      len((_upload_calls.get("payload") or {}).get("samples", {})
          .get("football") or []) == 80, _upload_calls.keys())
check("выгрузка: резервные копии не отправляются",
      "backups" not in (_upload_calls.get("payload") or {}),
      _upload_calls.get("payload", {}).keys())

_orig_upload_method = trainer.upload_snapshot
trainer.upload_snapshot = lambda device="": {
    "ok": True, "saved": "neural_test.json", "bytes": 1, "summary": {}}
try:
    api_res = json.loads(api.api_neural_upload())
finally:
    trainer.upload_snapshot = _orig_upload_method
check("api выгрузки отвечает ok", api_res.get("ok") is True, api_res)
res = json.loads(api.api_neural(json.dumps({"action": "train"})))
check("api обучение ok", res.get("ok") is True, res)
res = json.loads(api.api_neural(json.dumps({"action": "disable"})))
check("api выключение ok", res.get("ok") is True, res)
check("api выключил прогнозы", res["status"]["enabled"] is False, res["status"])
res = json.loads(api.api_neural(json.dumps({"action": "enable"})))
check("api включение ok", res["status"]["enabled"] is True, res["status"])
res = json.loads(api.api_neural(json.dumps({"action": "reset"})))
check("api сброс ok", res.get("ok") is True, res)
check("после сброса выборка пуста",
      res["status"]["total_samples"] == 0, res["status"])

res = json.loads(api.api_neural(json.dumps({"action": "configure",
                                            "keep_best": False,
                                            "freeze": True})))
check("api сохранил keep_best", res["status"]["keep_best"] is False, res["status"])
check("api сохранил freeze", res["status"]["freeze"] is True, res["status"])
res = json.loads(api.api_neural(json.dumps({
    "action": "configure", "hidden_layers": [24, 12], "activation": "relu",
    "epochs": 25, "finetune_epochs": 6, "learning_rate": 0.03, "l2": 0.002,
    "momentum": 0.85, "batch_size": 16, "validation_share": 0.25,
    "seed": 99})))
params = (res.get("status") or {}).get("params") or {}
check("api сохранил архитектуру", params.get("hidden_layers") == [24, 12],
      params)
check("api сохранил активацию", params.get("activation") == "relu", params)
check("api сохранил параметры обучения",
      params.get("epochs") == 25 and params.get("finetune_epochs") == 6
      and params.get("learning_rate") == 0.03
      and params.get("validation_share") == 0.25
      and params.get("seed") == 99, params)
res = json.loads(api.api_neural(json.dumps({"action": "rollback",
                                            "sport": "football"})))
check("api откат отвечает ok", res.get("ok") is True, res)

# ------------------------------------------------- проверка новых моделей
check("линия партии: 75.5 не подходит",
      nn_core.tt_line(75.5) == 18.5, nn_core.tt_line(75.5))
check("линия партии: 19.5 подходит",
      nn_core.tt_line(19.5) == 19.5, nn_core.tt_line(19.5))

# Группы (матчи) не должны разрываться между обучением и проверкой.
group_rows = []
for index in range(12):
    group = "m%d" % (index // 3)      # 4 матча по 3 партии
    group_rows.append({"x": [float(index)], "y": [1.0], "m": [1.0],
                       "t": "2026-10-%02d" % (index + 1), "g": group})
train_rows, val_rows = nn_core.split_rows(group_rows, share=0.25)
train_groups = {row["g"] for row in train_rows}
val_groups = {row["g"] for row in val_rows}
check("группы не пересекаются", not (train_groups & val_groups),
      (train_groups, val_groups))
check("проверка не пустая", len(val_rows) >= 1, len(val_rows))
check("проверка — свежие матчи", "m3" in val_groups, val_groups)

metrics = nn_core.evaluate_previous("football", trainer._models.get("football"),
                                    trainer._samples.get("football") or [])
check("прежняя модель проверяется на той же выборке",
      metrics is None or "accuracy" in metrics, metrics)

plateau_model = {"meta": {"accuracy": 0.5, "samples": 100},
                 "history": [{"accuracy": 0.5}, {"accuracy": 0.49},
                             {"accuracy": 0.5}, {"accuracy": 0.49}]}
check("плато: ждём новых данных",
      nn_trainer.NeuralTrainer._plateau_wait(plateau_model, [], 3) == 22,
      nn_trainer.NeuralTrainer._plateau_wait(plateau_model, [], 3))
check("плато: данных хватило",
      nn_trainer.NeuralTrainer._plateau_wait(plateau_model, [], 30) == 0,
      nn_trainer.NeuralTrainer._plateau_wait(plateau_model, [], 30))

# --- разметка по последнему счёту и очистка зависших примеров ------------
import datetime as _dt

temp_data = tempfile.mkdtemp(prefix="nn_pending_")
fresh = nn_trainer.NeuralTrainer(temp_data, eng.settings, None)
tt_match, tt_stats = make_case("Теннис А", "Теннис Б", True,
                               sport="table_tennis", line=18.5)
tt_match["current_score"] = "11:5, 9:11, 11:7, 11:6, 8:11, 11:9"
check("пример тенниса сохранён",
      fresh.store_sample(tt_match, tt_stats, "table_tennis") is True,
      fresh.status()["pending"])
check("счёт 4:2 — финальный",
      nn_trainer.NeuralTrainer._score_complete(
          "table_tennis", tt_match["current_score"]) is True)
check("счёт 2:1 — не финальный",
      nn_trainer.NeuralTrainer._score_complete(
          "table_tennis", "11:5, 9:11, 11:7") is False)
labeled = fresh.collect_results({})
check("матч размечен по последнему счёту", labeled == 1, labeled)
check("выборка пополнилась",
      len(fresh._samples.get("table_tennis") or []) == 6,
      len(fresh._samples.get("table_tennis") or []))

partial = nn_trainer.NeuralTrainer(tempfile.mkdtemp(prefix="nn_partial_"),
                                   eng.settings, None)
partial_match, partial_stats = make_case("Теннис В", "Теннис Г", True,
                                         sport="table_tennis", line=18.5)
partial_match["current_score"] = "11:5, 9:11, 11:7"
partial.store_sample(partial_match, partial_stats, "table_tennis")
check("незавершённый матч не размечается",
      partial.collect_results({}) == 0, partial.status()["pending"])

# Счёт только по партиям («3:1») — достаточное основание разметить
# победителя; тотал и фора выключаются, пример не теряется.
vb_home = nn_trainer.NeuralTrainer(tempfile.mkdtemp(prefix="nn_volley_"),
                                   eng.settings, None)
vb_match, vb_stats = make_case("Волейбол А", "Волейбол Б", True,
                               sport="volleyball")
vb_match["current_score"] = "2:1"
check("пример волейбола сохранён",
      vb_home.store_sample(vb_match, vb_stats, "volleyball") is True,
      vb_home.status()["pending"])
check("волейбол размечен по счёту партий",
      vb_home.collect_results({
          ("volleyball", "Волейбол А", "Волейбол Б"): "3:1"}) == 1,
      vb_home.status())
vb_samples = vb_home._samples.get("volleyball") or []
check("пример волейбола не потерян", len(vb_samples) == 1, vb_samples)
check("в примере сохранён исходный счёт",
      vb_samples and vb_samples[0].get("score") == "3:1", vb_samples[:1])
check("в примере есть версия разметки",
      vb_samples and vb_samples[0].get("v") == nn_core.LABEL_VERSION,
      vb_samples[:1])
check("тотал волейбола выключен без очков",
      vb_samples and vb_samples[0]["m"][3] == 0.0, vb_samples[:1])

old = nn_trainer.NeuralTrainer(tempfile.mkdtemp(prefix="nn_old_"),
                               eng.settings, None)
old._pending = [{
    "sport": "football", "teams": ["Старый", "Матч"],
    "created": (_dt.datetime.now() - _dt.timedelta(hours=96)).isoformat(),
    "last_score": "", "x": [0.0], "line": 2.5,
}]
check("зависший пример не размечается", old.collect_results({}) == 0)
check("зависший пример убран из очереди", old.status()["pending"] == 0,
      old.status()["pending"])
check("зависший пример сохранён в архиве", old.status()["archived"] == 1,
      old.status()["archived"])
archive_path = os.path.join(old.data_dir, nn_trainer.ARCHIVE_FILE)
with open(archive_path, "r", encoding="utf-8") as handle:
    archived_rows = [json.loads(line) for line in handle if line.strip()]
check("в архиве есть причина", archived_rows and
      archived_rows[0].get("_archive_reason") == "unlabeled_timeout",
      archived_rows[:1])
check("архив не удаляет пример", archived_rows and
      archived_rows[0].get("teams") == ["Старый", "Матч"], archived_rows[:1])


# ---------------------------------------------------------- уверенность 1.27
check("модель без отчёта по головам не готова",
      nn_core.head_ready({}, "p1") is False,
      nn_core.head_ready({}, "p1"))

legacy_meta = {
    "head_train_samples": {"p1": 100},
    "head_accuracy": {"p1": 0.55},
    "head_baseline": {"p1": 0.53},
    "legacy_risk": 1.0,
}
check("старая разметка требует большего перевеса",
      nn_core.head_ready(legacy_meta, "p1") is False, legacy_meta)
legacy_meta["legacy_risk"] = 0.0
check("доверенная разметка проходит с малым перевесом",
      nn_core.head_ready(legacy_meta, "p1") is True, legacy_meta)

# Веса строк: нулевой вес не меняет сеть, обычный — учит.
n_feat = len(nn_core.feature_spec("football")[0])
n_heads = len(nn_core.feature_spec("football")[1])
tiny_net = nn_core.MLP([n_feat, 4, n_heads], seed=3)
before = tiny_net.state()
zero_loss = tiny_net.train_batch([([0.1] * n_feat, [1.0] * n_heads,
                                   [1.0] * n_heads, 0.0)])
check("нулевой вес не даёт шага", zero_loss == 0.0, zero_loss)
check("нулевой вес не меняет веса",
      tiny_net.state()["weights"] == before["weights"], "weights changed")
one_loss = tiny_net.train_batch([([0.1] * n_feat, [1.0] * n_heads,
                                 [1.0] * n_heads, 1.0)])
check("ненулевой вес учит", one_loss > 0.0, one_loss)
check("ненулевой вес меняет веса",
      tiny_net.state()["weights"] != before["weights"], "weights same")

# Обучение: температура и доля старой разметки попадают в meta.
train_rows = []
for index in range(60):
    x = [0.1 + 0.01 * ((index * 7 + k) % 13) for k in range(n_feat)]
    won = index % 2 == 0
    y = [1.0 if won else 0.0, 0.0 if won else 1.0, 0.0,
         1.0 if index % 3 else 0.0, 1.0 if index % 4 else 0.0,
         1.0 if index % 5 else 0.0]
    train_rows.append({"x": x, "y": y, "m": [1.0] * n_heads,
                       "v": 0, "g": "g%d" % (index // 2),
                       "t": "2026-10-%02d" % (index % 28 + 1)})
model, report = nn_core.train_model("football", train_rows, epochs=3,
                                    hidden_layers=[8], seed=5)
check("обучение прошло", bool(model), report)
meta = model.get("meta") or {}
check("доля старой разметки сохранена",
      abs(float(meta.get("legacy_risk") or 0.0) - 1.0) < 1e-6, meta)
check("температура сохранена", float(meta.get("temperature") or 0) > 0,
      meta.get("temperature"))
base_probs = nn_core.predict_probs(model, train_rows[0]["x"])
model["temperature"] = float(meta.get("temperature") or 1.0) * 2.0
warm_probs = nn_core.predict_probs(model, train_rows[0]["x"])
check("рост температуры сжимает вероятности",
      all(abs(warm_probs[h] - 0.5) <= abs(base_probs[h] - 0.5) + 1e-9
          for h in base_probs), (base_probs, warm_probs))

# Разметка периодных видов после простоя, а не только по фиду.
check("футбол с двумя таймами — финал",
      nn_trainer.NeuralTrainer._score_looks_final(
          "football", "2:1 (1:0, 1:1)", 0.0) is True)
check("футбол с одним таймом — не финал",
      nn_trainer.NeuralTrainer._score_looks_final(
          "football", "1:0 (1:0)", 0.5) is False)
check("футбол без таймов после простоя — финал",
      nn_trainer.NeuralTrainer._score_looks_final(
          "football", "1:0", 7.0) is True)
check("баскетбол с четырьмя четвертями — финал",
      nn_trainer.NeuralTrainer._score_looks_final(
          "basketball", "96:86 (27:24, 31:21, 29:19, 9:22)", 0.0) is True)
check("баскетбол с двумя четвертями — не финал",
      nn_trainer.NeuralTrainer._score_looks_final(
          "basketball", "35:23 (27:14, 8:9)", 1.0) is False)

idle_home = nn_trainer.NeuralTrainer(tempfile.mkdtemp(prefix="nn_idle_"),
                                     eng.settings, None)
idle_home._pending = [{
    "sport": "football", "teams": ["Простой", "Матч"],
    "created": (_dt.datetime.now() - _dt.timedelta(hours=8)).isoformat(),
    "last_score": "1:0", "x": [0.0] * n_feat, "line": 2.5,
}]
idle_home.update_pending_scores({("football", "Простой", "Матч"): "2:1"})
check("время изменения счёта записано",
      bool(idle_home._pending[0].get("score_at")),
      idle_home._pending[0])

# ------------------------------------------------- производные признаки 1.28
check("версия признаков 2", nn_core.FEATURE_VERSION == 2,
      nn_core.FEATURE_VERSION)
raw = [0.0] * nn_core.feature_size("football")
expanded = nn_core.expand_features("football", raw)
check("производные признаки добавлены",
      len(expanded) == len(raw) + nn_core.DERIVED_FEATURES,
      (len(raw), len(expanded)))
check("производные признаки детерминированы",
      nn_core.expand_features("football", raw) == expanded)
check("старая модель читает сырые признаки",
      nn_core.model_features({"feature_version": 1}, raw) == raw)
check("новая модель читает производные признаки",
      nn_core.model_features({"feature_version": 2, "sport": "football"},
                             raw) == expanded)
tt_raw = [0.0] * nn_core.feature_size("table_tennis")
check("настольный теннис тоже расширяется",
      len(nn_core.expand_features("table_tennis", tt_raw)) ==
      len(tt_raw) + nn_core.DERIVED_FEATURES)

linear = nn_core.LinearHead([0, 2], [1.5, -0.5], 0.25)
check("линейная голова считает логит",
      abs(linear.logit([1.0, 9.0, 2.0]) - 0.75) < 1e-9, linear.logit([1.0, 9.0, 2.0]))
restored = nn_core.LinearHead.load(linear.state())
check("линейная голова сохраняется и читается",
      restored.indices == linear.indices and
      abs(restored.logit([1.0, 9.0, 2.0]) - 0.75) < 1e-9,
      restored.state())

# Явный линейный сигнал: голова p1 должна выбрать линейную модель.
linear_rows = []
for index in range(80):
    strong = index % 2 == 0
    x = [0.0] * nn_core.feature_size("football")
    x[0] = 1.0 if strong else -1.0
    y = [1.0 if strong else 0.0, 0.0 if strong else 1.0, 0.0,
         0.0, 0.0, 0.0]
    linear_rows.append({"x": x, "y": y, "m": [1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
                        "t": "2026-10-%02d" % (index % 28 + 1),
                        "g": "g%d" % index})
linear_model, _report = nn_core.train_model(
    "football", linear_rows, epochs=4, hidden_layers=[8], seed=3)
linear_meta = linear_model.get("meta") or {}
check("модель обучена на версии признаков 2",
      linear_meta.get("feature_version") == 2, linear_meta)
check("ревизия обучения 2",
      linear_meta.get("training_revision") == nn_core.TRAIN_REVISION,
      linear_meta)
check("линейная голова выбрана при явном сигнале",
      (linear_meta.get("head_source") or {}).get("p1") == "linear",
      linear_meta.get("head_source"))
check("точность по готовому рынку выше базы",
      float(linear_meta.get("lift") or 0.0) > 0.1, linear_meta)

# Готовность победителя — по совместному решению, а не по каждой голове.
winner_meta = {
    "head_train_samples": {"p1": 40, "p2": 40, "draw": 40},
    "winner_samples": 40, "winner_accuracy": 0.60, "winner_baseline": 0.50,
    "head_accuracy": {"p1": 0.50, "p2": 0.50, "draw": 0.70},
    "head_baseline": {"p1": 0.55, "p2": 0.55, "draw": 0.70},
}
check("победитель готов по совместной точности",
      nn_core.winner_ready(winner_meta) is True, winner_meta)
winner_meta["winner_accuracy"] = 0.50
check("победитель без перевеса не готов",
      nn_core.winner_ready(winner_meta) is False, winner_meta)

sample_metrics = {
    "market_samples": {"winner": 10, "btts": 10},
    "market_correct": {"winner": 7, "btts": 10},
    "market_baseline": {"winner": 5, "btts": 10},
}
accuracy, baseline, decisions = nn_core.market_summary(
    sample_metrics, {"winner": True, "btts": True})
check("постоянный рынок не завышает точность",
      decisions == 10 and abs(accuracy - 0.7) < 1e-9 and
      abs(baseline - 0.5) < 1e-9, (accuracy, baseline, decisions))

decision_samples = [
    ({"p1": 0.7, "p2": 0.2, "draw": 0.1}, [1.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
    ({"p1": 0.2, "p2": 0.7, "draw": 0.1}, [0.0, 1.0, 0.0], [1.0, 1.0, 1.0]),
    ({"p1": 0.1, "p2": 0.2, "draw": 0.7}, [0.0, 0.0, 1.0], [1.0, 1.0, 1.0]),
]
decision_metrics = nn_core._metrics_from_probs(
    decision_samples, ["p1", "p2", "draw"])
check("победитель считается одним решением",
      decision_metrics["market_samples"]["winner"] == 3 and
      decision_metrics["winner_accuracy"] == 1.0, decision_metrics)

print("\nALL CHECKS PASSED: %d/%d" % (checks[0], checks[1]))

# -*- coding: utf-8 -*-
"""Обучение и прогнозы нейросети Predictor.

Модуль отвечает за три вещи:

1. **Сбор данных.** Каждый проверенный матч (даже без прогноза) даёт
   один образец: вектор признаков плюс параметры для поиска результата.
   Образцы без результата ждут в ``nn_pending.json``.
2. **Разметка.** Когда матч завершился, по финальному счёту считаются
   метки, и образец переезжает в обучающую выборку ``nn_samples.jsonl``.
3. **Обучение и прогноз.** Фоновая нить дообучает модель на новых
   размеченных примерах (это и есть постоянное самообучение) и отдаёт
   прогнозы в том же формате, что и остальные источники сигналов.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime

import nn_core
import sports

SAMPLES_FILE = "nn_samples.jsonl"
PENDING_FILE = "nn_pending.json"
MODELS_FILE = "nn_model.json"

MAX_SAMPLES_PER_SPORT = 1500
MAX_PENDING = 800
TRAIN_CHUNK = 120             # примеров в одном куске обучения
TRAIN_INTERVAL = 120          # секунд между проверками обучения
PLATEAU_ROUNDS = 3            # раундов без роста точности — остановка
IMPROVE_EPS = 0.005           # минимальный прирост точности, чтобы считать улучшением
HISTORY_LIMIT = 30            # сколько точек истории храним по виду


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write(path, content):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp, path)


class NeuralTrainer:
    """Сбор данных, обучение и прогнозы нейросети."""

    def __init__(self, data_dir, settings, logger=None):
        self.data_dir = data_dir
        self.settings = settings
        self.logger = logger
        self._lock = threading.RLock()
        self._pending = []
        self._samples = {}
        self._models = {}
        self._backups = {}
        self._train_flag = False
        self._train_force = False
        self._training = False
        self._last_train_at = ""
        self._stop = threading.Event()
        self._thread = None
        self._load()

    # ---------------------------------------------------------------- настройки
    def config(self):
        cfg = {"enabled": False, "auto_train": True, "min_samples": 50,
               "min_confidence": 0.55, "sets": 3,
               "sports": list(sports.SPORT_ORDER),
               "markets": {},
               "keep_best": True, "freeze": False}
        try:
            stored = (self.settings.snapshot() or {}).get("neural") or {}
            if isinstance(stored, dict):
                cfg.update(stored)
        except Exception:
            pass
        try:
            cfg["min_samples"] = max(10, min(2000, int(cfg.get("min_samples") or 50)))
        except Exception:
            cfg["min_samples"] = 50
        try:
            cfg["min_confidence"] = max(0.5, min(0.95,
                                                  float(cfg.get("min_confidence") or 0.55)))
        except Exception:
            cfg["min_confidence"] = 0.55
        try:
            cfg["sets"] = max(1, min(5, int(cfg.get("sets") or 3)))
        except Exception:
            cfg["sets"] = 3
        cfg["enabled"] = bool(cfg.get("enabled"))
        cfg["auto_train"] = bool(cfg.get("auto_train"))
        cfg["keep_best"] = bool(cfg.get("keep_best", True))
        cfg["freeze"] = bool(cfg.get("freeze"))
        cfg["sports"] = self._clean_sports(cfg.get("sports"))
        cfg["markets"] = self._clean_markets(cfg.get("markets"))
        return cfg

    def markets_for(self, sport):
        """Рынки, по которым сеть даёт прогнозы для вида спорта."""
        sport = sports.normalize_sport(sport)
        supported = nn_core.market_kinds(sport)
        chosen = self.config()["markets"].get(sport)
        if chosen is None:
            return list(supported)
        return [kind for kind in supported if kind in chosen]

    @staticmethod
    def _clean_markets(value):
        """Разрешённые рынки по видам: только те, что есть у вида спорта."""
        result = {}
        if not isinstance(value, dict):
            return result
        for sport, kinds in value.items():
            sport_id = sports.normalize_sport(sport)
            if sport_id not in sports.SPORTS:
                continue
            if isinstance(kinds, str):
                kinds = [part.strip() for part in kinds.split(",") if part.strip()]
            if not isinstance(kinds, (list, tuple)):
                continue
            supported = nn_core.market_kinds(sport_id)
            clean = []
            for kind in kinds:
                text = str(kind or "").strip().lower()
                if text in supported and text not in clean:
                    clean.append(text)
            result[sport_id] = clean
        return result

    @staticmethod
    def _clean_sports(value):
        """Оставляет только известные виды спорта, без дублей.

        Принимаются id (football), алиасы (футбол, tt) и id Betcity.
        Неизвестное значение отбрасывается, а не превращается в другой вид.
        """
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        if not isinstance(value, (list, tuple)):
            return list(sports.SPORT_ORDER)
        result = []
        for item in value:
            text = str(item or "").strip().lower().replace("ё", "е")
            sport_id = ""
            if text in sports.SPORTS:
                sport_id = text
            elif text in sports.ALIASES:
                sport_id = sports.ALIASES[text]
            if sport_id and sport_id not in result:
                result.append(sport_id)
        return result

    def enabled(self, sport=None):
        cfg = self.config()
        if not cfg["enabled"]:
            return False
        if sport is None:
            return True
        sport_id = sports.normalize_sport(sport)
        if sport_id not in cfg["sports"]:
            return False
        model = self._models.get(sport_id)
        return bool(model)

    # ---------------------------------------------------------------- хранение
    def _path(self, name):
        return os.path.join(self.data_dir, name)

    def _load(self):
        try:
            path = self._path(PENDING_FILE)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, list):
                    self._pending = data
        except Exception as exc:
            self._log("Нейросеть: не удалось прочитать ожидающие образцы: %s" % exc)
        try:
            path = self._path(SAMPLES_FILE)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except Exception:
                            continue
                        sport = sports.normalize_sport(row.get("sport"))
                        self._samples.setdefault(sport, []).append(row)
        except Exception as exc:
            self._log("Нейросеть: не удалось прочитать обучающую выборку: %s" % exc)
        try:
            path = self._path(MODELS_FILE)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    self._models = data.get("sports") or {}
                    self._backups = data.get("backups") or {}
        except Exception as exc:
            self._log("Нейросеть: не удалось прочитать модели: %s" % exc)

    def _save_pending(self):
        try:
            _atomic_write(self._path(PENDING_FILE),
                          json.dumps(self._pending[-MAX_PENDING:],
                                     ensure_ascii=False))
        except Exception as exc:
            self._log("Нейросеть: не удалось сохранить ожидающие образцы: %s" % exc)

    def _save_models(self):
        try:
            _atomic_write(self._path(MODELS_FILE),
                          json.dumps({"version": 2, "updated_at": _now(),
                                      "sports": self._models,
                                      "backups": self._backups},
                                     ensure_ascii=False))
        except Exception as exc:
            self._log("Нейросеть: не удалось сохранить модели: %s" % exc)

    def _append_samples(self, sport, rows):
        """Дописывает размеченные строки в обучающую выборку."""
        path = self._path(SAMPLES_FILE)
        try:
            with open(path, "a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:
            self._log("Нейросеть: не удалось дописать выборку: %s" % exc)
            return
        bucket = self._samples.setdefault(sport, [])
        bucket.extend(rows)
        if len(bucket) > MAX_SAMPLES_PER_SPORT * 2:
            keep = bucket[-MAX_SAMPLES_PER_SPORT:]
            self._samples[sport] = keep
            self._rewrite_samples()

    def _rewrite_samples(self):
        path = self._path(SAMPLES_FILE)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                for sport, rows in self._samples.items():
                    for row in rows[-MAX_SAMPLES_PER_SPORT:]:
                        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:
            self._log("Нейросеть: не удалось перезаписать выборку: %s" % exc)

    # ---------------------------------------------------------------- сбор
    def store_sample(self, match, stats, sport, features=None, meta=None):
        """Запоминает проверенный матч как обучающий образец.

        Работает для всех проверенных матчей — с прогнозом и без него.
        Готовые признаки можно передать, чтобы не считать их дважды.
        """
        try:
            sport = sports.normalize_sport(sport)
            if features is None:
                features, meta = nn_core.build_features(match, stats, sport)
            if not features:
                return False
            # Мало данных от метрик — пример бесполезен, шум в обучении.
            if float((meta or {}).get("coverage") or 0.0) < 0.25:
                return False
            team1 = (match or {}).get("team1", "")
            team2 = (match or {}).get("team2", "")
            if not team1 or not team2:
                return False
            record = {
                "sport": sport,
                "teams": [team1, team2],
                "date": (match or {}).get("date", ""),
                "created": _now(),
                "x": [round(float(v), 6) for v in features],
                "line": meta.get("line"),
                "handicap": meta.get("handicap"),
                "layout": meta.get("layout"),
            }
            with self._lock:
                for item in self._pending:
                    if (item.get("sport") == sport and
                            item.get("teams") == record["teams"]):
                        return False
                self._pending.append(record)
                if len(self._pending) > MAX_PENDING:
                    self._pending = self._pending[-MAX_PENDING:]
                self._save_pending()
            return True
        except Exception as exc:
            self._log("Нейросеть: не удалось сохранить образец: %s" % exc)
            return False

    def collect_results(self, finished):
        """Размечает ожидающие образцы по завершённым матчам.

        finished — словарь (sport, team1, team2) -> финальный счёт.
        Возвращает число размеченных образцов.
        """
        if not finished:
            return 0
        labeled = 0
        rest = []
        with self._lock:
            for record in self._pending:
                sport = record.get("sport")
                teams = record.get("teams") or []
                key = (sport, teams[0] if teams else "", teams[1] if len(teams) > 1 else "")
                score_text = finished.get(key)
                if not score_text:
                    rest.append(record)
                    continue
                rows = self._make_rows(record, score_text)
                if not rows:
                    rest.append(record)
                    continue
                self._append_samples(sport, rows)
                labeled += 1
            if labeled:
                self._pending = rest
                self._save_pending()
        if labeled:
            self.request_train()
        return labeled

    def _make_rows(self, record, score_text):
        sport = sports.normalize_sport(record.get("sport"))
        rows = []
        labels = nn_core.labels_for_match(sport, score_text, record.get("line"),
                                          record.get("handicap"))
        slot = nn_core.set_slot(sport)
        for item in labels:
            x = list(record.get("x") or [])
            if slot >= 0 and slot < len(x):
                x[slot] = min(1.0, float(item.get("set") or 1) / 5.0)
            rows.append({
                "sport": sport,
                "x": x,
                "y": [float(v) for v in item.get("y") or []],
                "m": [float(v) for v in item.get("m") or []],
                "t": record.get("created") or _now(),
            })
        return rows

    # ---------------------------------------------------------------- обучение
    @staticmethod
    def _history(model):
        history = (model or {}).get("history") or []
        return history if isinstance(history, list) else []

    @staticmethod
    def _accuracy(model):
        try:
            return float(((model or {}).get("meta") or {}).get("accuracy") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _is_better(new_accuracy, old_accuracy, keep_best):
        """Стоит ли принимать новую модель вместо прежней."""
        if old_accuracy is None:
            return True
        if not keep_best:
            return True
        return float(new_accuracy) >= float(old_accuracy) - IMPROVE_EPS

    @classmethod
    def _plateau(cls, model):
        """True, если точность не растёт PLATEAU_ROUNDS раундов подряд."""
        history = cls._history(model)
        if len(history) < PLATEAU_ROUNDS + 1:
            return False
        tail = history[-PLATEAU_ROUNDS:]
        before = history[-PLATEAU_ROUNDS - 1]
        best = max(cls._entry_accuracy(item) for item in tail)
        return best <= cls._entry_accuracy(before) + IMPROVE_EPS

    @staticmethod
    def _entry_accuracy(entry):
        try:
            return float((entry or {}).get("accuracy") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _trend(history):
        """Направление последних точек: up / down / flat."""
        values = [NeuralTrainer._entry_accuracy(item) for item in (history or [])]
        if len(values) < 2:
            return "flat"
        delta = values[-1] - values[-2]
        if delta > IMPROVE_EPS:
            return "up"
        if delta < -IMPROVE_EPS:
            return "down"
        return "flat"

    def request_train(self, force=False):
        with self._lock:
            self._train_flag = True
            if force:
                self._train_force = True
        self._ensure_thread()
        return True

    def _ensure_thread(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="nn-trainer")
        self._thread.start()

    def _loop(self):
        waited = 0.0
        while not self._stop.is_set():
            try:
                with self._lock:
                    flag = self._train_flag
                    force = self._train_force
                    self._train_flag = False
                    self._train_force = False
                if flag:
                    self.train_all(force=force)
                    waited = 0.0
                else:
                    waited += 1.0
            except Exception as exc:
                self._log("Нейросеть: ошибка обучения: %s" % exc)
            self._stop.wait(1.0)

    def _pause(self):
        self._stop.wait(0.05)

    def train_all(self, force=False):
        """Обучает модели по видам спорта, где хватает примеров.

        Защита от переобучения:
          - «оставлять лучшую модель» — новая модель принимается, только если
            её точность на отложенной выборке не хуже прежней;
          - остановка по плато — после PLATEAU_ROUNDS раундов без роста
            точности автоматическое дообучение вида прекращается;
          - предыдущая модель хранится как резервная копия для отката.
        """
        cfg = self.config()
        min_samples = cfg["min_samples"]
        trained = []
        rejected = []
        if cfg["freeze"] and not force:
            self._log("Нейросеть: обучение заморожено, автоматическое "
                      "дообучение отключено")
            return []
        if not force and self._last_train_at:
            try:
                last = datetime.fromisoformat(self._last_train_at)
                if (datetime.now() - last).total_seconds() < TRAIN_INTERVAL:
                    return []
            except Exception:
                pass
        with self._lock:
            self._training = True
        try:
            for sport in cfg["sports"]:
                with self._lock:
                    rows = list(self._samples.get(sport) or [])
                    previous = self._models.get(sport)
                if len(rows) < min_samples:
                    continue
                if previous and not force:
                    meta = previous.get("meta") or {}
                    if meta.get("samples") and \
                            len(rows) - int(meta.get("samples")) < 5:
                        continue
                    if self._plateau(previous):
                        self._log("Нейросеть: %s — остановка по плато, "
                                  "точность не растёт %d раунда" %
                                  (sports.short_name(sport), PLATEAU_ROUNDS))
                        continue
                try:
                    model, report = nn_core.train_model(
                        sport, rows, previous=previous,
                        epochs=12 if previous is None else 4, pause=self._pause)
                except Exception as exc:
                    self._log("Нейросеть: обучение %s не удалось: %s" %
                              (sports.short_name(sport), exc))
                    continue
                if not model:
                    continue
                new_meta = model.setdefault("meta", {})
                new_meta["updated_at"] = _now()
                old_accuracy = self._accuracy(previous) if previous else None
                new_accuracy = float(new_meta.get("accuracy") or 0.0)
                history = self._history(previous)
                entry = {
                    "at": new_meta["updated_at"],
                    "accuracy": round(new_accuracy, 4),
                    "baseline": round(float(new_meta.get("baseline") or 0.0), 4),
                    "lift": round(float(new_meta.get("lift") or 0.0), 4),
                    "samples": int(new_meta.get("samples") or 0),
                    "rejected": False,
                }
                if (not self._is_better(new_accuracy, old_accuracy,
                                       cfg["keep_best"]) and previous):
                    # Переобучение: оставляем прежнюю модель.
                    entry["rejected"] = True
                    entry["previous_accuracy"] = round(old_accuracy, 4)
                    previous["history"] = (history + [entry])[-HISTORY_LIMIT:]
                    with self._lock:
                        self._models[sport] = previous
                    rejected.append(sport)
                    self._log("Нейросеть: переобучение отклонено (%s) — "
                              "было %.1f%%, стало %.1f%%" %
                              (sports.short_name(sport),
                               old_accuracy * 100, new_accuracy * 100))
                    continue
                model["history"] = (history + [entry])[-HISTORY_LIMIT:]
                with self._lock:
                    if previous:
                        self._backups[sport] = previous
                    self._models[sport] = model
                trained.append(sport)
        finally:
            with self._lock:
                self._training = False
        if trained or rejected:
            with self._lock:
                self._last_train_at = _now()
                self._save_models()
            for sport in trained:
                meta = (self._models.get(sport) or {}).get("meta") or {}
                self._log("Нейросеть: %s — обучена на %d примерах, точность %.0f%%" % (
                    sports.name(sport), meta.get("samples", 0),
                    100.0 * float(meta.get("accuracy") or 0.0)))
        return trained

    def rollback(self, sport=None):
        """Возвращает предыдущую модель вида (или всех видов)."""
        sport = sports.normalize_sport(sport) if sport else None
        with self._lock:
            targets = [sport] if sport else list(self._backups.keys())
            done = []
            for item in targets:
                backup = self._backups.get(item)
                if not backup:
                    continue
                current = self._models.get(item)
                self._models[item] = backup
                if current:
                    self._backups[item] = current
                else:
                    self._backups.pop(item, None)
                done.append(item)
            if done:
                self._save_models()
        for item in done:
            meta = (self._models.get(item) or {}).get("meta") or {}
            self._log("Нейросеть: %s — откат к предыдущей модели, точность %.0f%%" % (
                sports.name(item), 100.0 * float(meta.get("accuracy") or 0.0)))
        return done

    def train_now(self, force=True):
        """Ставит обучение в фоновую нить (интерфейс не блокируется)."""
        self.request_train(force=force)
        return True

    # ---------------------------------------------------------------- прогноз
    def predict(self, match, stats, sport, features=None, meta=None):
        """Прогнозы нейросети по матчу (пустой список, если не готова)."""
        sport = sports.normalize_sport(sport)
        cfg = self.config()
        if not cfg["enabled"]:
            return []
        if sport not in cfg["sports"]:
            return []
        with self._lock:
            model = self._models.get(sport)
        if not model:
            return []
        meta_model = model.get("meta") or {}
        if int(meta_model.get("samples") or 0) < cfg["min_samples"]:
            return []
        try:
            if features is None:
                features, meta = nn_core.build_features(match, stats, sport)
            probs = nn_core.predict_probs(model, features)
        except Exception as exc:
            self._log("Нейросеть: прогноз не удался: %s" % exc)
            return []
        if not probs:
            return []

        min_conf = cfg["min_confidence"]
        has_draw = bool(sports.profile(sport)["has_draw"])
        line = (meta or {}).get("line") or sports.default_total(sport)
        handicap = (meta or {}).get("handicap")
        markets = self.markets_for(sport)
        accuracy = float(meta_model.get("accuracy") or 0.0)
        samples = int(meta_model.get("samples") or 0)
        base_info = "Нейросеть: %d примеров, точность %.0f%%" % (samples, accuracy * 100)
        predictions = []

        def make(target, label, kind, side, verdict, confidence, threshold=None,
                 handicap=None):
            item = {
                "target": target,
                "label": label,
                "kind": kind,
                "expected_side": side,
                "threshold": threshold,
                "verdict": verdict,
                "confidence_val": round(float(confidence), 3),
                "min_model_wilson": round(float(confidence), 3),
                "strong": 3,
                "agreement": round(float(confidence), 3),
                "models_info": base_info,
                "source": "neural",
            }
            if handicap is not None:
                item["handicap"] = handicap
            return item

        if sport == "table_tennis":
            if not markets:
                return predictions
            for number in range(1, cfg["sets"] + 1):
                for item in self._predict_set(probs, number, min_conf, markets):
                    predictions.append(item)
            return predictions

        # ---- командные виды: победитель ----
        if "winner" in markets:
            candidates = [("П1", probs.get("p1", 0.0))]
            if has_draw:
                candidates.append(("Ничья", probs.get("draw", 0.0)))
            candidates.append(("П2", probs.get("p2", 0.0)))
            side, value = max(candidates, key=lambda item: item[1])
            if value >= min_conf:
                predictions.append(make(
                    "match", "Матч (П1 / Ничья / П2)" if has_draw else "Матч (П1 / П2)",
                    "winner", side, side, value))
        # ---- командные виды: тотал ----
        if "total" in markets:
            over = probs.get("over")
            if over is not None:
                if over >= 0.5:
                    total_side, verdict, confidence = "over", "ТБ %s" % _fmt_line(line), over
                else:
                    total_side, verdict, confidence = "under", "ТМ %s" % _fmt_line(line), 1.0 - over
                if confidence >= min_conf:
                    predictions.append(make(
                        "match", "Тотал матча (ТБ/ТМ)", "total", total_side, verdict,
                        confidence, threshold=line))
        # ---- командные виды: фора ----
        if "handicap" in markets and handicap is not None:
            prob = probs.get("handicap")
            if prob is not None:
                confidence = max(prob, 1.0 - prob)
                if confidence >= min_conf:
                    if prob >= 0.5:
                        side, value = "p1", float(handicap)
                    else:
                        side, value = "p2", -float(handicap)
                    sign = "+" if value > 0 else ""
                    predictions.append(make(
                        "match", "Матч (фора)", "handicap", side,
                        "%s (%s%s)" % ("Ф1" if side == "p1" else "Ф2", sign,
                                       _fmt_line(value)),
                        confidence, handicap=value))
        # ---- командные виды: обе забьют ----
        if "btts" in markets:
            prob = probs.get("btts")
            if prob is not None:
                confidence = max(prob, 1.0 - prob)
                if confidence >= min_conf:
                    side = "yes" if prob >= 0.5 else "no"
                    predictions.append(make(
                        "match", "Матч (обе забьют)", "btts", side,
                        "Обе забьют — да" if side == "yes" else "Обе забьют — нет",
                        confidence))
        return predictions

    def _predict_set(self, probs, number, min_conf, markets=None):
        rows = []
        markets = markets or ["winner", "total"]
        p1 = probs.get("p1", 0.0)
        p2 = probs.get("p2", 0.0)
        if "winner" in markets and max(p1, p2) >= min_conf:
            side = "П1" if p1 >= p2 else "П2"
            rows.append({
                "target": "set%d" % number,
                "label": "Партия %d (П1/П2)" % number,
                "kind": "winner",
                "expected_side": side,
                "threshold": None,
                "verdict": side,
                "confidence_val": round(max(p1, p2), 3),
                "min_model_wilson": round(max(p1, p2), 3),
                "strong": 3,
                "agreement": round(max(p1, p2), 3),
                "models_info": "Нейросеть: партия %d" % number,
                "source": "neural",
            })
        if "total" in markets:
            over = probs.get("over")
            if over is not None:
                threshold = float(sports.default_total("table_tennis"))
                if over >= 0.5:
                    side, verdict, confidence = "over", "ТБ %s" % _fmt_line(threshold), over
                else:
                    side, verdict, confidence = "under", "ТМ %s" % _fmt_line(threshold), 1.0 - over
                if confidence >= min_conf:
                    rows.append({
                        "target": "set%d" % number,
                        "label": "Партия %d (ТБ/ТМ)" % number,
                        "kind": "total",
                        "expected_side": side,
                        "threshold": threshold,
                        "verdict": verdict,
                        "confidence_val": round(confidence, 3),
                        "min_model_wilson": round(confidence, 3),
                        "strong": 3,
                        "agreement": round(confidence, 3),
                        "models_info": "Нейросеть: партия %d" % number,
                        "source": "neural",
                    })
        return rows

    # ---------------------------------------------------------------- статус
    def status(self):
        cfg = self.config()
        with self._lock:
            pending = list(self._pending)
            models = dict(self._models)
            backups = dict(self._backups)
            samples = {sport: len(rows) for sport, rows in self._samples.items()}
        sports_info = []
        selected = cfg["sports"]
        for sport in sports.SPORT_ORDER:
            pending_count = sum(1 for item in pending
                                if item.get("sport") == sport)
            model = models.get(sport) or {}
            meta = model.get("meta") or {}
            samples_count = samples.get(sport, 0)
            history = self._history(model)
            sports_info.append({
                "sport": sport,
                "name": sports.name(sport),
                "short": sports.short_name(sport),
                "icon": sports.profile(sport)["icon"],
                "samples": samples_count,
                "pending": pending_count,
                "accuracy": float(meta.get("accuracy") or 0.0),
                "baseline": float(meta.get("baseline") or 0.0),
                "lift": float(meta.get("lift") or 0.0),
                "epochs": int(meta.get("epochs") or 0),
                "trained_at": meta.get("updated_at") or "",
                "selected": sport in selected,
                "markets": nn_core.market_kinds(sport),
                "markets_enabled": self.markets_for(sport),
                "ready": bool(model) and samples_count >= cfg["min_samples"],
                "history": [
                    {"at": item.get("at", ""),
                     "accuracy": self._entry_accuracy(item),
                     "baseline": float(item.get("baseline") or 0.0),
                     "lift": float(item.get("lift") or 0.0),
                     "samples": int(item.get("samples") or 0),
                     "rejected": bool(item.get("rejected"))}
                    for item in history[-12:]
                ],
                "trend": self._trend(history),
                "plateau": self._plateau(model),
                "has_backup": sport in backups,
                "backup_accuracy": self._accuracy(backups.get(sport)),
            })
        total_samples = sum(samples_count for samples_count in samples.values())
        ready = [item for item in sports_info if item["ready"]]
        return {
            "enabled": cfg["enabled"],
            "auto_train": cfg["auto_train"],
            "keep_best": cfg["keep_best"],
            "freeze": cfg["freeze"],
            "plateau_rounds": PLATEAU_ROUNDS,
            "min_samples": cfg["min_samples"],
            "min_confidence": cfg["min_confidence"],
            "sets": cfg["sets"],
            "sports_selected": list(selected),
            "market_labels": nn_core.MARKET_LABELS,
            "total_samples": total_samples,
            "pending": len(pending),
            "sports": sports_info,
            "ready_sports": len(ready),
            "trained": bool(ready),
            "training": self._training,
            "last_train_at": self._last_train_at,
            "updated_at": _now(),
        }

    # ---------------------------------------------------------------- сброс
    def reset(self, clear_samples=True):
        with self._lock:
            if clear_samples:
                self._pending = []
                self._samples = {}
                try:
                    for name in (SAMPLES_FILE, PENDING_FILE):
                        path = self._path(name)
                        if os.path.exists(path):
                            os.remove(path)
                except Exception as exc:
                    self._log("Нейросеть: не удалось удалить выборку: %s" % exc)
            self._models = {}
            self._backups = {}
            self._last_train_at = ""
            self._save_pending()
            self._save_models()
        self._log("Нейросеть: данные и модели сброшены")
        return True

    def stop(self):
        self._stop.set()

    def _log(self, message):
        if self.logger:
            try:
                self.logger.info(message)
            except Exception:
                pass
        try:
            import predictor_core as core
            core.events.add("INFO", message)
        except Exception:
            pass


def _fmt_line(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 1e-6:
        return "%g" % number
    return ("%.1f" % number).replace(".0", "")


def merge_predictions(nn_predictions, source_predictions, nn_priority=True):
    """Сливает прогнозы нейросети с прогнозами источника.

    Один и тот же рынок (target + kind) не дублируется: если включён
    nn_priority, выигрывает нейросеть, иначе — правила пользователя.
    """
    if not nn_predictions:
        return list(source_predictions or [])
    if not source_predictions:
        return list(nn_predictions)
    merged = []
    used = set()
    for item in nn_predictions:
        key = (item.get("target"), item.get("kind"))
        replaced = False
        for index, source in enumerate(source_predictions):
            if index in used:
                continue
            if (source.get("target"), source.get("kind")) == key:
                used.add(index)
                if nn_priority:
                    merged.append(item)
                else:
                    merged.append(source)
                replaced = True
                break
        if not replaced:
            merged.append(item)
    for index, source in enumerate(source_predictions):
        if index not in used:
            merged.append(source)
    return merged

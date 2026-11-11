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
import online_client
import sports

SAMPLES_FILE = "nn_samples.jsonl"
PENDING_FILE = "nn_pending.json"
MODELS_FILE = "nn_model.json"
ARCHIVE_FILE = "nn_archive.jsonl"
SCORE_FIX_FILE = "nn_score_fix_v2.json"

# Пределы — только страховка от бесконечного роста. Всё, что выходит за
# них, не удаляется, а переносится в архив (nn_archive.jsonl) и остаётся
# доступным для экспорта и ручного разбора.
MAX_SAMPLES_PER_SPORT = 20000
MAX_PENDING = 5000
MAX_PENDING_AGE_HOURS = 72   # сколько ждать счёт, прежде чем убрать в архив
TRAIN_CHUNK = 120             # примеров в одном куске обучения
TRAIN_INTERVAL = 120          # секунд между проверками обучения
PLATEAU_ROUNDS = 3            # раундов без роста точности — остановка
PLATEAU_NEW_SHARE = 0.25      # доля новых примеров, чтобы попробовать снова
IMPROVE_EPS = 0.005           # минимальный прирост точности, чтобы считать улучшением
HISTORY_LIMIT = 30            # сколько точек истории храним по виду


def _revision(meta):
    """Ревизия обучения модели (0 — до 1.27)."""
    try:
        return int((meta or {}).get("training_revision") or 0)
    except (TypeError, ValueError):
        return 0

# Параметры сети и обучения. Значения проверяются на входе: из веб-формы
# может прийти строка, пустое поле или число вне диапазона.
NN_ACTIVATIONS = ("tanh", "relu", "sigmoid")
NN_LAYERS_LIMIT = 4
NN_LAYERS_NEURONS = 512
NN_PARAM_LIMITS = {
    "epochs": (1, 300),
    "finetune_epochs": (1, 150),
    "learning_rate": (0.001, 0.5),
    "l2": (0.0, 0.05),
    "momentum": (0.0, 0.99),
    "batch_size": (4, 256),
    "validation_share": (0.1, 0.4),
    "seed": (1, 999999),
}


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
        self._quarantined = {}
        self._archived = 0           # строк в nn_archive.jsonl
        self._train_flag = False
        self._train_force = False
        self._training = False
        self._last_train_at = ""
        self._dropped = 0            # устаревшее поле статуса (совместимость)
        self._plateau_skip = {}      # спорт -> сколько примеров при плато
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
        cfg["hidden_layers"] = self._clean_layers(cfg.get("hidden_layers"))
        cfg["activation"] = self._clean_activation(cfg.get("activation"))
        defaults = {"epochs": 12, "finetune_epochs": 4, "batch_size": 32,
                    "seed": 7, "learning_rate": 0.05, "l2": 0.001,
                    "momentum": 0.9, "validation_share": 0.2}
        for key, default in defaults.items():
            low, high = NN_PARAM_LIMITS[key]
            try:
                value = float(cfg.get(key))
                if not math.isfinite(value):
                    value = float(default)
            except (TypeError, ValueError):
                value = float(default)
            if key in ("epochs", "finetune_epochs", "batch_size", "seed"):
                value = int(round(value))
            else:
                value = round(value, 6)
            cfg[key] = max(low, min(high, value))
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

    @staticmethod
    def _clean_layers(value):
        """Скрытые слои: список нейронов, например [32, 16]."""
        if isinstance(value, str):
            parts = [part for part in value.replace("x", ",")
                     .replace("х", ",").replace(";", ",").split(",")]
        elif isinstance(value, (list, tuple)):
            parts = list(value)
        else:
            parts = [value]
        layers = []
        for part in parts:
            try:
                number = int(round(float(part)))
            except (TypeError, ValueError):
                continue
            if 1 <= number <= NN_LAYERS_NEURONS:
                layers.append(number)
            if len(layers) >= NN_LAYERS_LIMIT:
                break
        return layers or [16]

    @staticmethod
    def _clean_activation(value):
        text = str(value or "").strip().lower()
        return text if text in NN_ACTIVATIONS else "tanh"

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
                    self._quarantined = data.get("quarantined") or {}
        except Exception as exc:
            self._log("Нейросеть: не удалось прочитать модели: %s" % exc)
        try:
            path = self._path(ARCHIVE_FILE)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    self._archived = sum(1 for line in handle if line.strip())
        except Exception as exc:
            self._log("Нейросеть: не удалось прочитать архив: %s" % exc)
        self._migrate_bad_scores()

    @staticmethod
    def _label_version(row):
        try:
            return int((row or {}).get("v") or 0)
        except (TypeError, ValueError):
            return 0

    def _archive(self, records, reason, kind):
        """Сохраняет строки в архив, ничего не удаляя.

        Архив — обычный JSONL: каждая строка дополнена временем, причиной
        и типом (pending/sample). Его можно выгрузить из приложения и
        разобрать вручную; обучение архив не использует.
        """
        records = [record for record in (records or [])
                   if isinstance(record, dict)]
        if not records:
            return 0
        try:
            with open(self._path(ARCHIVE_FILE), "a", encoding="utf-8") as handle:
                for record in records:
                    item = dict(record)
                    item["_archived_at"] = _now()
                    item["_archive_reason"] = reason
                    item["_archive_kind"] = kind
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        except Exception as exc:
            self._log("Нейросеть: не удалось записать архив: %s" % exc)
            return 0
        self._archived += len(records)
        return len(records)

    def _migrate_bad_scores(self):
        """Один раз убирает из обучения строки, размеченные неверным счётом.

        До версии 1.23 проверка матчей брала первую пару ``sc_inter`` за
        счёт матча. У футбола это текущий тайм, у волейбола и тенниса —
        одна партия/сет. Метки победителя и тотала из таких строк
        poisoned обучение, поэтому затронутые виды начинали заново.

        Теперь данные не удаляются: строки без версии разметки (или со
        старой версией) уходят в архив, а модели — в карантин. Новые
        строки с ``LABEL_VERSION`` остаются в выборке.
        """
        marker = self._path(SCORE_FIX_FILE)
        if os.path.exists(marker):
            return
        affected = ("volleyball", "tennis", "football")
        archived = 0
        quarantined = 0
        failed = False
        for sport in affected:
            rows = self._samples.get(sport) or []
            stale = [row for row in rows
                     if self._label_version(row) < nn_core.LABEL_VERSION]
            if stale:
                saved = self._archive(stale, "score_parser_v2", "sample")
                if saved < len(stale):
                    # Архив не записался — не трогаем выборку, чтобы
                    # не потерять данные. Маркер не ставим: повторим.
                    failed = True
                    continue
                keep = [row for row in rows
                        if self._label_version(row) >= nn_core.LABEL_VERSION]
                if keep:
                    self._samples[sport] = keep
                else:
                    self._samples.pop(sport, None)
                archived += saved
            if sport in self._models:
                self._quarantined[sport] = self._models.pop(sport)
                quarantined += 1
            if sport in self._backups:
                self._quarantined[sport + "_backup"] = \
                    self._backups.pop(sport)
        if failed:
            self._log("Нейросеть: архив недоступен — миграция выборки "
                      "отложена, данные не тронуты")
            return
        try:
            if archived:
                self._rewrite_samples()
            if quarantined or archived:
                self._save_models()
            _atomic_write(marker, json.dumps({
                "at": _now(),
                "reason": "score parser fix: match score from sc_ev",
                "sports": list(affected),
                "samples_archived": archived,
                "models_quarantined": quarantined,
            }, ensure_ascii=False))
        except Exception as exc:
            self._log("Нейросеть: миграция выборки не удалась: %s" % exc)
            return
        if archived or quarantined:
            self._log("Нейросеть: в архив убрана выборка, размеченная по "
                      "неверному счёту (%d примеров, %d моделей в карантине): "
                      "волейбол, теннис, футбол" % (archived, quarantined))

    def _save_pending(self):
        try:
            _atomic_write(self._path(PENDING_FILE),
                          json.dumps(self._pending, ensure_ascii=False))
        except Exception as exc:
            self._log("Нейросеть: не удалось сохранить ожидающие образцы: %s" % exc)

    def _save_models(self):
        try:
            _atomic_write(self._path(MODELS_FILE),
                          json.dumps({"version": 3, "updated_at": _now(),
                                      "sports": self._models,
                                      "backups": self._backups,
                                      "quarantined": self._quarantined},
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
        if len(bucket) > MAX_SAMPLES_PER_SPORT:
            # Переполнение не удаляет примеры: старые строки уходят в
            # архив и остаются доступными для экспорта. Если архив не
            # записался, строки остаются в выборке — терять нельзя.
            overflow = bucket[:-MAX_SAMPLES_PER_SPORT]
            if self._archive(overflow, "samples_overflow",
                             "sample") == len(overflow):
                self._samples[sport] = bucket[-MAX_SAMPLES_PER_SPORT:]
                self._rewrite_samples()

    def _rewrite_samples(self):
        path = self._path(SAMPLES_FILE)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                for sport, rows in self._samples.items():
                    for row in rows:
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
            team1 = (match or {}).get("team1", "")
            team2 = (match or {}).get("team2", "")
            if not team1 or not team2:
                return False
            coverage = float((meta or {}).get("coverage") or 0.0)
            record = {
                "sport": sport,
                "teams": [team1, team2],
                "date": (match or {}).get("date", ""),
                "created": _now(),
                # Последний увиденный счёт: если матч уйдёт из линии,
                # пример всё равно удастся разметить.
                "last_score": (match or {}).get("current_score") or "",
                "x": [round(float(v), 6) for v in features],
                "line": meta.get("line"),
                "handicap": meta.get("handicap"),
                "layout": meta.get("layout"),
                "coverage": round(coverage, 4),
            }
            if coverage < 0.25:
                # Мало данных от метрик — обучать на таком векторе нельзя,
                # но и терять пример не нужно: он остаётся в архиве.
                # Повторно такой матч не собираем, чтобы архив не рос
                # бесконечно от одного и того же события.
                self._archive([record], "low_coverage", "sample")
                return False
            with self._lock:
                for item in self._pending:
                    # Одна и та же пара может играть несколько матчей
                    # (турниры, серии). Дата отличает их друг от друга.
                    if (item.get("sport") == sport and
                            item.get("teams") == record["teams"] and
                            str(item.get("date") or "") ==
                            str(record.get("date") or "")):
                        return False
                self._pending.append(record)
                if len(self._pending) > MAX_PENDING:
                    overflow = self._pending[:-MAX_PENDING]
                    self._pending = self._pending[-MAX_PENDING:]
                    self._archive(overflow, "pending_overflow", "pending")
                self._save_pending()
            return True
        except Exception as exc:
            self._log("Нейросеть: не удалось сохранить образец: %s" % exc)
            return False

    def update_pending_scores(self, scores):
        """Обновляет последний счёт ожидающих примеров.

        Пока матч в линии, храним его счёт в самом примере: если матч
        исчезнет из фида до разметки, пример всё равно можно разметить.
        """
        if not scores:
            return 0
        updated = 0
        with self._lock:
            for record in self._pending:
                sport = sports.normalize_sport(record.get("sport"))
                teams = record.get("teams") or []
                if len(teams) < 2:
                    continue
                value = scores.get((sport, teams[0], teams[1]))
                if not value:
                    continue
                if record.get("last_score") != value:
                    record["last_score"] = value
                    # Время последнего изменения счёта: по нему видно,
                    # что матч давно не двигался и счёт, скорее всего,
                    # итоговый, даже если событие ещё в линии.
                    record["score_at"] = _now()
                    updated += 1
            if updated:
                self._save_pending()
        return updated

    def collect_results(self, finished):
        """Размечает ожидающие образцы по завершённым матчам.

        finished — словарь (sport, team1, team2) -> финальный счёт.
        Если матч уже ушёл из линии, берём последний увиденный счёт
        самого образца — но только когда он финальный. Для сетов
        достаточно определённого победителя: счёт «3:1» без очков
        партий тоже размечается, а тотал и фора выключаются маской.

        Примеры, которые так и не удалось разметить, не удаляются:
        после MAX_PENDING_AGE_HOURS они уходят в архив.
        """
        labeled = 0
        archived_expired = 0
        expired = []
        rest = []
        now = datetime.now()
        with self._lock:
            for record in self._pending:
                sport = sports.normalize_sport(record.get("sport"))
                teams = record.get("teams") or []
                key = (sport, teams[0] if teams else "",
                       teams[1] if len(teams) > 1 else "")
                score_text = (finished or {}).get(key)
                from_line = bool(score_text)
                if not score_text:
                    score_text = str(record.get("last_score") or "")
                usable = bool(score_text) and (
                    from_line or self._score_complete(sport, score_text))
                if usable and from_line and sport != "table_tennis":
                    # Событие уже помечено завершённым, поэтому хватает
                    # определённого победителя: тотал может быть неизвестен.
                    parsed = sports.parse_score(sport, score_text)
                    usable = sports.score_decided(sport, parsed)
                if not usable and score_text and not from_line:
                    # Событие ушло из линии, а счёт остался последним
                    # увиденным. Для периодных видов (футбол, хоккей,
                    # баскетбол) это итог, только если счёт давно не
                    # менялся: иначе можно разметить середину матча.
                    idle = self._idle_hours(record, now)
                    usable = self._score_looks_final(sport, score_text, idle)
                if not usable:
                    if self._too_old(record, now):
                        expired.append(record)
                    else:
                        rest.append(record)
                    continue
                rows = self._make_rows(record, score_text)
                if not rows:
                    if self._too_old(record, now):
                        expired.append(record)
                    else:
                        rest.append(record)
                    continue
                self._append_samples(sport, rows)
                labeled += 1
            if labeled or expired:
                if expired:
                    archived_expired = self._archive(
                        expired, "unlabeled_timeout", "pending")
                    if archived_expired < len(expired):
                        # Архив не записался: оставляем примеры в очереди,
                        # чтобы не потерять их. Повторим позже.
                        rest.extend(expired)
                self._pending = rest
                self._save_pending()
        if archived_expired:
            self._log("Нейросеть: %d примеров не размечено — матч завершился "
                      "и ушёл из линии (перенесены в архив)"
                      % archived_expired)
        elif expired:
            self._log("Нейросеть: %d примеров не размечено, но архив "
                      "недоступен — оставлены в очереди" % len(expired))
        if labeled:
            self.request_train()
        return labeled

    @staticmethod
    def _score_complete(sport, score_text):
        """Счёт финальный (матч доигран, а не середина партии).

        Для командных видов с периодами (футбол, хоккей, баскетбол)
        последний счёт без отметки «матч завершён» не считается финальным:
        по нему нельзя отличить середину матча от конца. Для волейбола
        и настольного тенниса финал однозначен по числу побед (3 и 4).
        У тенниса формат встречи неизвестен, поэтому без отметки
        «завершён» доверяем только трём выигранным сетам.
        """
        sport = sports.normalize_sport(sport)
        if sports.profile(sport)["score_mode"] != "sets":
            return False
        parsed = sports.parse_score(sport, score_text)
        if not parsed:
            return False
        high = max(int(parsed["match"][0]), int(parsed["match"][1]))
        low = min(int(parsed["match"][0]), int(parsed["match"][1]))
        if sport == "table_tennis":
            return high == 4 and low <= 3
        if sport == "volleyball":
            return high == 3 and low <= 2
        if sport == "tennis":
            return high == 3 and low <= 2
        return sports.score_decided(sport, parsed)

    @staticmethod
    def _idle_hours(record, now=None):
        """Сколько часов счёт примера не менялся."""
        stamp = (record or {}).get("score_at") or \
            (record or {}).get("created") or ""
        try:
            moment = datetime.fromisoformat(str(stamp))
        except Exception:
            return 0.0
        now = now or datetime.now()
        return max(0.0, (now - moment).total_seconds() / 3600.0)

    @classmethod
    def _score_looks_final(cls, sport, score_text, idle_hours):
        """Можно ли считать последний счёт итоговым без отметки «завершён».

        У футбола/хоккея/баскетбола матч уходит из фида с задержкой,
        поэтому последний счёт сам по себе не доказывает финал. Но если
        видны все периоды (таймы, трети, четверти) или счёт не менялся
        несколько часов, матч почти наверняка доигран. Тогда пример
        размечается, а не ждёт тайм-аута и не уходит в архив.
        """
        sport = sports.normalize_sport(sport)
        item = sports.profile(sport)
        if item["score_mode"] == "sets":
            return cls._score_complete(sport, score_text)
        parsed = sports.parse_score(sport, score_text)
        if not parsed:
            return False
        expected = int(item.get("periods") or 0)
        periods = parsed.get("periods") or []
        if expected and len(periods) >= expected:
            return True
        if item["score_mode"] == "single" and expected:
            _match, inner = sports.split_score_text(score_text)
            if len(sports.score_pairs(inner)) >= expected:
                return True
        # Без счёта периодов остаётся только время: 6 часов простоя
        # больше любой паузы между периодами.
        return float(idle_hours or 0.0) >= 6.0

    @staticmethod
    def _too_old(record, now=None):
        try:
            created = datetime.fromisoformat(str(record.get("created") or ""))
        except Exception:
            return False
        now = now or datetime.now()
        return (now - created).total_seconds() > MAX_PENDING_AGE_HOURS * 3600

    def _make_rows(self, record, score_text):
        sport = sports.normalize_sport(record.get("sport"))
        rows = []
        labels = nn_core.labels_for_match(sport, score_text, record.get("line"),
                                          record.get("handicap"))
        slot = nn_core.set_slot(sport)
        # Все партии одного матча — одна группа: они не должны попадать
        # одновременно в обучение и проверку.
        group = "%s|%s|%s" % (sport, "|".join(record.get("teams") or []),
                              record.get("date") or record.get("created") or "")
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
                "g": group,
                # Версия разметки и исходный счёт: по ним видно, откуда
                # взялись метки, и строку можно проверить или разметить
                # заново, не гадая.
                "v": int(item.get("v") or nn_core.LABEL_VERSION),
                "score": score_text,
                "line": record.get("line"),
                "handicap": record.get("handicap"),
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

    @staticmethod
    def _plateau_wait(previous, rows, new_rows=None):
        """Сколько ещё примеров ждать после плато (0 — можно обучать снова).

        Плато — не приговор: вид не «замерзает» навсегда, а ждёт, пока
        накопится заметный прирост данных, и тогда обучается снова.
        """
        meta = (previous or {}).get("meta") or {}
        trained_on = int(meta.get("samples") or 0)
        if new_rows is None:
            new_rows = max(0, len(rows or []) - trained_on)
        need = max(5, int(trained_on * PLATEAU_NEW_SHARE))
        return max(0, need - int(new_rows or 0))

    def train_all(self, force=False):
        """Обучает модели по видам спорта, где хватает примеров.

        Защита от переобучения:
          - «оставлять лучшую модель» — новая модель принимается, только если
            её точность на тех же свежих матчах не хуже прежней (обе модели
            проверяются на одной отложенной выборке, а не на разных);
          - плато — пауза, а не запрет: когда накопится заметный прирост
            данных, вид обучается снова;
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
                meta = (previous or {}).get("meta") or {}
                # Модель без отчёта по головам (обучена до 1.27) не может
                # открыть рынки: head_ready её не пропускает. Её нужно
                # переобучить сразу, не дожидаясь пяти новых примеров и
                # не упираясь в плато.
                needs_recoverage = bool(previous) and (
                    not isinstance(meta.get("head_train_samples"), dict) or
                    _revision(meta) < nn_core.TRAIN_REVISION)
                if needs_recoverage:
                    self._log("Нейросеть: %s — нет отчёта по головам, "
                              "переобучаем модель" %
                              sports.short_name(sport))
                if previous and not force and not needs_recoverage:
                    trained_on = int(meta.get("samples") or 0)
                    new_rows = max(0, len(rows) - trained_on)
                    if trained_on and new_rows < 5:
                        continue
                    if self._plateau(previous):
                        wait = self._plateau_wait(previous, rows, new_rows)
                        if wait > 0:
                            if self._plateau_skip.get(sport) != trained_on:
                                self._plateau_skip[sport] = trained_on
                                self._log(
                                    "Нейросеть: %s — плато, ждём ещё %d "
                                    "примеров (пришло %d)" %
                                    (sports.short_name(sport), wait, new_rows))
                            continue
                        self._log("Нейросеть: %s — плато, пробуем заново на "
                                  "новых данных (+%d примеров)" %
                                  (sports.short_name(sport), new_rows))
                try:
                    model, report = nn_core.train_model(
                        sport, rows, previous=previous,
                        epochs=cfg["epochs"]
                        if (previous is None or needs_recoverage)
                        else cfg["finetune_epochs"],
                        lr=cfg["learning_rate"],
                        l2=cfg["l2"],
                        momentum=cfg["momentum"],
                        batch_size=cfg["batch_size"],
                        validation_share=cfg["validation_share"],
                        seed=cfg["seed"],
                        hidden_layers=cfg["hidden_layers"],
                        activation=cfg["activation"],
                        pause=self._pause)
                except Exception as exc:
                    self._log("Нейросеть: обучение %s не удалось: %s" %
                              (sports.short_name(sport), exc))
                    continue
                if not model:
                    continue
                new_meta = model.setdefault("meta", {})
                new_meta["updated_at"] = _now()
                new_accuracy = float(new_meta.get("accuracy") or 0.0)
                # Прежнюю модель проверяем на ТОЙ ЖЕ отложенной выборке.
                old_metrics = nn_core.evaluate_previous(
                    sport, previous, rows,
                    share=cfg["validation_share"])
                old_accuracy = float(old_metrics.get("accuracy")) \
                    if old_metrics else None
                # Модель без покрытия по головам или обученная по старой
                # ревизии не может открыть рынки: её нужно переобучить,
                # даже если общая точность чуть просела. Иначе старые
                # модели навсегда остаются «готовыми» без проверки
                # перевеса по каждому рынку.
                old_meta = (previous or {}).get("meta") or {}
                needs_recoverage = bool(previous) and (
                    not isinstance(old_meta.get("head_train_samples"), dict) or
                    _revision(old_meta) < nn_core.TRAIN_REVISION)
                history = self._history(previous)
                entry = {
                    "at": new_meta["updated_at"],
                    "accuracy": round(new_accuracy, 4),
                    "baseline": round(float(new_meta.get("baseline") or 0.0), 4),
                    "lift": round(float(new_meta.get("lift") or 0.0), 4),
                    "samples": int(new_meta.get("samples") or 0),
                    "val_samples": int(new_meta.get("val_samples") or 0),
                    "winner_accuracy": round(
                        float(new_meta.get("winner_accuracy") or 0.0), 4),
                    "old_on_val": round(old_accuracy, 4)
                    if old_accuracy is not None else None,
                    "rejected": False,
                }
                if (old_accuracy is not None and previous and
                        not needs_recoverage and
                        not self._is_better(new_accuracy, old_accuracy,
                                            cfg["keep_best"])):
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
    @staticmethod
    def _market_heads(sport, kind):
        """Головы сети, от которых зависит рынок."""
        if kind == "winner":
            if sports.profile(sport)["has_draw"]:
                return ("p1", "p2", "draw")
            return ("p1", "p2")
        return {"total": ("over",), "handicap": ("handicap",),
                "btts": ("btts",)}.get(kind, ())

    @classmethod
    def _market_ready(cls, model, sport, kind):
        """Рынок обучен достаточно уверенно, чтобы давать прогноз.

        Мало примеров или точность не выше «всегда самый частый класс» —
        рынок молчит. Иначе случайный сигнал выглядит как уверенный.
        Победитель проверяется как одно совместное решение П1/Ничья/П2:
        отдельная голова П2 при несбалансированных исходах почти всегда
        уступает «всегда не П2» и не должна закрывать весь рынок.
        """
        meta = (model or {}).get("meta") or {}
        if kind == "winner":
            return nn_core.winner_ready(meta)
        heads = cls._market_heads(sport, kind)
        return bool(heads) and all(nn_core.head_ready(meta, head)
                                   for head in heads)

    def _ready_markets(self, model, sport, markets):
        return {kind: self._market_ready(model, sport, kind)
                for kind in (markets or [])}

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
        if sport == "table_tennis":
            # В главном рынке Betcity тотал матча, а прогнозы — по партиям.
            line = nn_core.tt_line(line)
        handicap = (meta or {}).get("handicap")
        markets = self.markets_for(sport)
        ready = self._ready_markets(model, sport, markets)
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
                for item in self._predict_set(probs, number, min_conf, markets,
                                              line, ready):
                    predictions.append(item)
            return predictions

        # ---- командные виды: победитель ----
        if ready.get("winner"):
            candidates = []
            if "p1" in probs:
                candidates.append(("П1", probs["p1"]))
            if has_draw and "draw" in probs:
                candidates.append(("Ничья", probs["draw"]))
            if "p2" in probs:
                candidates.append(("П2", probs["p2"]))
            if candidates:
                side, value = max(candidates, key=lambda item: item[1])
                if value >= min_conf:
                    predictions.append(make(
                        "match",
                        "Матч (П1 / Ничья / П2)" if has_draw else "Матч (П1 / П2)",
                        "winner", side, side, value))
        # ---- командные виды: тотал ----
        if ready.get("total"):
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
        if ready.get("handicap") and handicap is not None:
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
        if ready.get("btts"):
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

    def _predict_set(self, probs, number, min_conf, markets=None, line=None,
                     ready=None):
        rows = []
        markets = markets or ["winner", "total"]
        ready = ready or {kind: True for kind in markets}
        p1 = probs.get("p1", 0.0)
        p2 = probs.get("p2", 0.0)
        if ready.get("winner") and max(p1, p2) >= min_conf:
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
        if ready.get("total"):
            over = probs.get("over")
            if over is not None:
                threshold = float(nn_core.tt_line(line))
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

    # ---------------------------------------------------------------- экспорт
    def export_snapshot(self, include_backups=True):
        """Полная выгрузка нейросети: выборка, очередь, архив и модели.

        Нужна, чтобы изучить реальные собранные данные на устройстве:
        сервер хранит только результаты прогнозов, а векторы признаков
        остаются в приватной папке приложения.
        """
        archived = []
        try:
            path = self._path(ARCHIVE_FILE)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            archived.append(json.loads(line))
                        except Exception:
                            archived.append({"_raw": line})
        except Exception as exc:
            self._log("Нейросеть: не удалось прочитать архив: %s" % exc)
        with self._lock:
            payload = {
                "generated_at": _now(),
                "label_version": nn_core.LABEL_VERSION,
                "feature_version": nn_core.FEATURE_VERSION,
                "training_revision": nn_core.TRAIN_REVISION,
                "market_min_samples": nn_core.MARKET_MIN_TRAIN_SAMPLES,
                "samples": {sport: list(rows)
                            for sport, rows in self._samples.items()},
                "pending": list(self._pending),
                "archive": archived,
                "models": dict(self._models),
                "quarantined": dict(self._quarantined),
            }
            if include_backups:
                payload["backups"] = dict(self._backups)
        return json.dumps(payload, ensure_ascii=False, indent=1)

    def upload_snapshot(self, device=""):
        """Отправляет снимок выборки на сайт — без файлового диалога.

        Большой JSON не проходит через мост WebView и системный
        «Сохранить как», поэтому выгрузка уходит напрямую в сеть.
        Резервные копии моделей в снимок не входят: для разбора данных
        достаточно выборки, очереди, архива и самих моделей.
        """
        payload = json.loads(self.export_snapshot(include_backups=False))
        result = online_client.upload_nn(
            self.settings.snapshot(), payload, device=device)
        self._log("Нейросеть: выгрузка на сервер — %s (%s байт)" % (
            result.get("saved") or "?", result.get("bytes") or 0))
        return result

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
            _spec, sport_heads, _layout = nn_core.feature_spec(sport)
            head_report = {}
            for head in sport_heads:
                head_samples = int(
                    (meta.get("head_train_samples") or {}).get(head) or 0)
                head_accuracy = float(
                    (meta.get("head_accuracy") or {}).get(head) or 0.0)
                head_baseline = float(
                    (meta.get("head_baseline") or {}).get(head) or 0.0)
                head_report[head] = {
                    "samples": head_samples,
                    "accuracy": head_accuracy,
                    "baseline": head_baseline,
                    "lift": head_accuracy - head_baseline,
                    "ready": nn_core.head_ready(meta, head),
                }
            markets_ready = [kind for kind in nn_core.market_kinds(sport)
                             if self._market_ready(model, sport, kind)]
            history = self._history(model)
            rows = list(self._samples.get(sport) or [])
            needed = max(0, cfg["min_samples"] - samples_count)
            plateau_wait = self._plateau_wait(model, rows) if model else 0
            if sport not in selected:
                hint = ("Вид не выбран для нейросети — обучение и прогнозы "
                        "по нему выключены.")
            elif cfg["freeze"]:
                hint = "Обучение заморожено в настройках."
            elif model:
                if self._plateau(model) and plateau_wait > 0:
                    hint = ("Плато: точность не растёт. Ждём ещё %d новых "
                            "примеров, затем попробуем снова." % plateau_wait)
                else:
                    ready_names = [nn_core.MARKET_LABELS.get(kind, kind)
                                   for kind in (meta.get("ready_markets") or [])]
                    lift = float(meta.get("lift") or 0.0) * 100.0
                    hint = ("Модель обучена на %d примерах: точность %.0f%% "
                            "при базовой %.0f%% (%+.1f п.п.). Готовые рынки: %s." % (
                                int(meta.get("samples") or 0),
                                float(meta.get("accuracy") or 0.0) * 100.0,
                                float(meta.get("baseline") or 0.0) * 100.0,
                                lift,
                                ", ".join(ready_names) if ready_names
                                else "пока нет — нужен больший перевес"))
            elif not cfg["auto_train"]:
                hint = ("Авто-обучение выключено. Нажмите «Обучить сейчас», "
                        "когда наберётся %d примеров (сейчас %d)." % (
                            cfg["min_samples"], samples_count))
            elif samples_count == 0:
                hint = ("Нет размеченных примеров. Пока матч в линии, "
                        "приложение хранит счёт; после финала пример "
                        "разметится автоматически.")
            elif needed > 0:
                hint = ("Ждём ещё %d примеров до минимума %d. Сейчас %d, "
                        "в ожидании разметки %d." % (
                            needed, cfg["min_samples"], samples_count,
                            pending_count))
            elif pending_count:
                hint = ("Данных достаточно, обучение запустится в фоне. "
                        "В ожидании разметки ещё %d." % pending_count)
            else:
                hint = "Данных достаточно, обучение запустится в фоне."
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
                "accuracy_all": float(meta.get("accuracy_all") or 0.0),
                "baseline_all": float(meta.get("baseline_all") or 0.0),
                "ready_markets": list(meta.get("ready_markets") or []),
                "winner_accuracy": float(meta.get("winner_accuracy") or 0.0),
                "winner_baseline": float(meta.get("winner_baseline") or 0.0),
                "winner_samples": int(meta.get("winner_samples") or 0),
                "feature_version": int(meta.get("feature_version") or 0),
                "head_source": dict(meta.get("head_source") or {}),
                "val_samples": int(meta.get("val_samples") or 0),
                "best_epoch": int(meta.get("best_epoch") or 0),
                "epochs": int(meta.get("epochs") or 0),
                "architecture": list(meta.get("architecture") or []),
                "activation": meta.get("activation") or "",
                "finetuned": bool(meta.get("finetuned")),
                "trained_at": meta.get("updated_at") or "",
                "selected": sport in selected,
                "markets": nn_core.market_kinds(sport),
                "markets_enabled": self.markets_for(sport),
                "markets_ready": markets_ready,
                "head_report": head_report,
                "label_version": int(meta.get("label_version") or 0),
                "ready": bool(model) and samples_count >= cfg["min_samples"],
                "history": [
                    {"at": item.get("at", ""),
                     "accuracy": self._entry_accuracy(item),
                     "baseline": float(item.get("baseline") or 0.0),
                     "lift": float(item.get("lift") or 0.0),
                     "samples": int(item.get("samples") or 0),
                     "val_samples": int(item.get("val_samples") or 0),
                     "winner_accuracy": float(item.get("winner_accuracy") or 0.0),
                     "old_on_val": item.get("old_on_val"),
                     "rejected": bool(item.get("rejected"))}
                    for item in history[-12:]
                ],
                "trend": self._trend(history),
                "plateau": self._plateau(model),
                "plateau_wait": plateau_wait,
                "needed_samples": needed,
                "trained_on": int(meta.get("samples") or 0),
                "hint": hint,
                "has_backup": sport in backups,
                "backup_accuracy": self._accuracy(backups.get(sport)),
            })
        total_samples = sum(samples_count for samples_count in samples.values())
        ready = [item for item in sports_info if item["ready"]]
        if cfg["freeze"]:
            hint = "Обучение заморожено — новые примеры копятся, модель не меняется."
        elif not cfg["auto_train"]:
            hint = "Авто-обучение выключено: обучить можно вручную."
        elif self._training:
            hint = "Идёт обучение — точность обновится после проверки."
        elif total_samples == 0:
            hint = ("Пока нет размеченных примеров. Движок собирает их из "
                    "завершённых матчей; после финала пример разметится сам.")
        elif ready:
            hint = ("Обучено видов: %d. Модель дообучается по мере "
                    "поступления новых результатов." % len(ready))
        else:
            hint = ("Данные копятся: нужно не меньше %d примеров на вид. "
                    "Сейчас %d." % (cfg["min_samples"], total_samples))
        return {
            "enabled": cfg["enabled"],
            "auto_train": cfg["auto_train"],
            "keep_best": cfg["keep_best"],
            "freeze": cfg["freeze"],
            "plateau_rounds": PLATEAU_ROUNDS,
            "min_samples": cfg["min_samples"],
            "min_confidence": cfg["min_confidence"],
            "sets": cfg["sets"],
            "params": {
                "hidden_layers": list(cfg["hidden_layers"]),
                "activation": cfg["activation"],
                "epochs": cfg["epochs"],
                "finetune_epochs": cfg["finetune_epochs"],
                "learning_rate": cfg["learning_rate"],
                "l2": cfg["l2"],
                "momentum": cfg["momentum"],
                "batch_size": cfg["batch_size"],
                "validation_share": cfg["validation_share"],
                "seed": cfg["seed"],
            },
            "activations": list(NN_ACTIVATIONS),
            "sports_selected": list(selected),
            "market_labels": nn_core.MARKET_LABELS,
            "total_samples": total_samples,
            "pending": len(pending),
            "archived": self._archived,
            "dropped": self._dropped,
            "label_version": nn_core.LABEL_VERSION,
            "market_min_samples": nn_core.MARKET_MIN_TRAIN_SAMPLES,
            "data_health": {
                "samples": total_samples,
                "pending": len(pending),
                "archived": self._archived,
                "quarantined_models": len(self._quarantined),
            },
            "sports": sports_info,
            "ready_sports": len(ready),
            "trained": bool(ready),
            "training": self._training,
            "last_train_at": self._last_train_at,
            "hint": hint,
            "updated_at": _now(),
        }

    # ---------------------------------------------------------------- сброс
    def reset(self, clear_samples=True):
        with self._lock:
            if clear_samples:
                # Даже явный сброс не теряет данные: активные строки
                # сначала уходят в архив, и их можно выгрузить.
                total = len(self._pending) + sum(
                    len(rows) for rows in self._samples.values())
                saved = 0
                if self._pending:
                    saved += self._archive(self._pending, "manual_reset",
                                           "pending")
                for sport, rows in self._samples.items():
                    if rows:
                        saved += self._archive(rows, "manual_reset", "sample")
                if saved < total:
                    self._log("Нейросеть: архив недоступен — сброс отменён, "
                              "данные не тронуты")
                    return False
                self._pending = []
                self._samples = {}
                self._dropped = 0
                self._plateau_skip = {}
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

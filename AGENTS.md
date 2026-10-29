# AGENTS.md — Betcity Predictor Android

Этот файл — точка входа для любого ИИ-ассистента и разработчика. Сначала
прочитайте его, затем `docs/ai/README.md`.

## Что это за проект

Android-приложение `by.betcity.predictor` с Python-ядром внутри APK (Chaquopy).
Приложение само получает live-линию Betcity, статистику матчей, считает прогнозы,
ведёт очередь, результаты, статистику, конструктор правил и анализатор. Сервер
для работы не нужен. Интерфейс и сообщения — на русском языке.

Текущая версия: **1.15** (`versionCode 16`, `APP_VERSION 1.15.0`).
Готовый APK: `../Predictor-1.15.apk` относительно корня проекта.

Онлайн-режим необязателен: по умолчанию всё считается на телефоне. Сайт для
совместного анализа — `server/` (WSGI, alwaysdata), клиент —
`online_client.py`, общий расчёт — `analysis_service.py`.

## Главные правила

1. **Не удаляйте пользовательские данные.** Настройки, правила и историю
   приложение хранит в приватной папке Android. При тестах подменяйте `HOME`
   на временную папку, как это делают скрипты в `tests/`.
2. **Перед существенными правками делайте резервную копию** файлов в
   `.backups/<дата>_<тема>/` или отдельную git-ветку. Рабочее дерево не должно
   содержать `__pycache__`, `build/`, `dist/` и локальные файлы.
3. **Не ломайте обратную совместимость тестов.** В тестах есть monkeypatch
   вызовов predictor-методов с разным числом аргументов; в продакшене уже
   используются fallback-вызовы через `try/except TypeError`.
4. **Движок анализирует все виды сразу.** `active_sport` — только активный вид
   интерфейса: какие правила, шаблоны и каталог метрик показывать. Линия,
   статистика, прогнозы, очередь и проверка результатов идут по всем видам.
   `get_live_matches()` без аргумента возвращает все виды, с аргументом — один.
   Правила и шаблоны разных видов хранятся отдельно и не удаляются.
5. **Настольный теннис — особый.** У него по-партийная модель, 46 шаблонов и
   отдельный парсер. Не меняйте его парсер и формат прогнозов, не прогнав
   `tests/test_constructor.py`, `tests/test_presets_new.py`,
   `tests/test_results_screen.py`.
6. **Интерфейс на русском.** Подписи, ошибки, шаблоны, документация для
   пользователя — по-русски. Код и имена переменных — английские.
7. **Версия должна быть согласована** во всех местах:
   `app/src/main/python/engine_api.py` (`APP_VERSION`),
   `server/online_app.py` (`SERVER_VERSION`),
   `app/build.gradle.kts` (`versionCode`, `versionName`),
   `README.md`, `docs/ai/CHANGELOG.md`, `docs/ai/PROJECT.md`,
   `docs/ai/BUILD_RELEASE.md`.
8. **Мост Kotlin ↔ JS синхронный.** Любой вызов `PyApp.*` блокирует UI-поток.
   Не добавляйте в циклы и не вызывайте тяжёлые методы без необходимости.
9. **JSON-снимки должны оставаться JSON-безопасными.** Для этого есть
   `analyzer.json_safe` / `json_restore`; datetime нельзя класть в снимок сырым.
10. **Не добавляйте внешние Python-пакеты без нужды.** `requests`, `bs4` и
    зависимости уже вендорены в `app/src/main/python/`; pip при сборке не
    используется.
11. **Нейросеть — только чистый Python.** `nn_core.py` и `nn_trainer.py` не
    тянут numpy или torch: сеть обучается внутри APK. Обучение идёт в фоновой
    нити и не должно блокировать цикл движка.

## Быстрые команды

Все команды — из корня `betcity-predictor-android`.

```powershell
# окружение для Python-тестов
$env:PYTHONUTF8="1"; $env:PYTHONIOENCODING="utf-8"

# ключевые регрессии
python tests\test_constructor.py
python tests\test_presets_new.py
python tests\test_constructor_backend.py
python tests\test_results_screen.py
python tests\test_analyzer.py
python tests\test_auto_rules.py
python tests\test_recommendations.py
python tests\test_online_server.py
python tests\test_release_tool.py
python tests\test_nn.py
python tests\test_sports_pipeline.py
python tests\test_all_sports.py
python tests\test_sports_metrics.py
python tests\check_sports_presets.py

# пересобрать машинночитаемый контекст
python tools\dump_ai_context.py

# сборка APK (JAVA_HOME специально не задаём)
$env:ANDROID_HOME="C:\Android"
C:\Android\gradle-8.7\bin\gradle.bat --no-daemon assembleDebug

# проверка APK
Copy-Item app\build\outputs\apk\debug\app-debug.apk ..\Predictor-1.15.apk -Force
C:\Android\build-tools\34.0.0\apksigner.bat verify --print-certs ..\Predictor-1.15.apk
C:\Android\build-tools\34.0.0\aapt2.exe dump badging ..\Predictor-1.15.apk
```

PowerShell часто завершает успешный Python-тест с кодом 1 из-за
`RequestsDependencyWarning` в stderr. Смотрите на итоговую строку `OK`/`PASS`,
а не только на код возврата.

## Где искать правду

Порядок доверия:

1. Исходный код в `app/src/main/`.
2. Тесты в `tests/` и их ожидаемые результаты.
3. `docs/ai/generated/` — автоматически снятые каталоги метрик, шаблонов и API.
4. Документация в `docs/ai/`.
5. `README.md` — пользовательское описание, не техническая спецификация.

Если документация расходится с кодом — прав код; обновите документацию и
`docs/ai/generated/`.

## Карта документации

- `docs/ai/README.md` — индекс и порядок чтения.
- `CONTEXT.md` — краткая карта проекта на одну страницу.
- `docs/ai/PROJECT.md` — продукт, экраны, текущее состояние.
- `docs/ai/ARCHITECTURE.md` — слои, потоки данных, хранение, жизненный цикл.
- `docs/ai/SPORTS.md` — виды спорта, счёт, рынки, метрики, шаблоны.
- `docs/ai/CONSTRUCTOR.md` — схема правил, действия, расчёт исходов.
- `docs/ai/ANALYZER.md` — как работает анализатор и перенос правил.
- `docs/ai/UI.md` — WebView, экраны, состояние, мост, спортивные фильтры.
- `docs/ai/TESTING.md` — тесты, фикстуры, браузерный стенд.
- `docs/ai/BUILD_RELEASE.md` — версия, сборка, подпись, релизный чек-лист.
- `docs/ai/DECISIONS.md` — принятые решения и причины.
- `docs/ai/ROADMAP.md` — что проверено, что осталось, известные риски.
- `docs/ai/CHANGELOG.md` — история версий.
- `docs/ai/GLOSSARY.md` — термины.
- `docs/ai/AI_PROMPT.md` — готовый промпт для нового чата.
- `docs/ai/generated/` — JSON-каталоги и дерево проекта.
- `CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md` — короткие
  точки входа для соответствующих инструментов.

## Текущее ограничение

На машине разработки нет подключённого Android-устройства или эмулятора.
Поэтому проверены Python-логика, браузерный UI-стенд, сборка, подпись и
содержимое APK, но не проверен запуск Chaquopy на реальном телефоне.
Перед релизом нужно установить APK на arm64 Android 7.0+ и пройти
`docs/ai/TESTING.md` → «Проверка на устройстве».

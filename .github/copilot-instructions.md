# Copilot instructions — Betcity Predictor

Проект: Android + Chaquopy, Python-ядро в APK, WebView UI. Полный контекст:
`AGENTS.md`, `CONTEXT.md`, `docs/ai/`.

- Отвечай по-русски; UI и сообщения — русские, код — английский.
- Движок анализирует все виды сразу; `active_sport` — только интерфейс,
  правила и шаблоны хранятся по видам.
- Не меняй парсер/модели настольного тенниса без
  `tests/test_constructor.py`, `tests/test_presets_new.py`,
  `tests/test_results_screen.py`.
- Перед крупными изменениями — backup в `.backups/` (git нет).
- Версия: `engine_api.APP_VERSION`, `app/build.gradle.kts`, `README.md`,
  `docs/ai/CHANGELOG.md`.
- Не добавляй pip-зависимости: Python-пакеты вендорены в
  `app/src/main/python/`.
- Мост Kotlin↔JS синхронный; тяжёлые операции — в фоне.
- Тесты: `python tests\run_all.py --offline`.
- UI: `python tools\ui_harness\sync_ui.py`.
- Метрики/шаблоны: `python tools\dump_ai_context.py`.

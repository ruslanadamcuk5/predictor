# Betcity Predictor — инструкции для ассистента

Этот файл — короткая точка входа. Полные правила: `AGENTS.md`; краткая карта:
`CONTEXT.md`; техническая документация: `docs/ai/`.

## Обязательно

- Отвечай по-русски, UI и сообщения — на русском, код — на английском.
- Движок анализирует все виды сразу; `active_sport` — только интерфейс и
  выбор правил. Правила видов не смешивай.
- Не трогай парсер и модели настольного тенниса без прогона
  `tests/test_constructor.py`, `tests/test_presets_new.py`,
  `tests/test_results_screen.py`.
- Перед крупными правками делай backup в `.backups/<дата>_<тема>/` — git в
  проекте нет.
- Версия синхронизируется в `engine_api.APP_VERSION`,
  `app/build.gradle.kts`, `README.md`, `docs/ai/CHANGELOG.md`.
- Python-пакеты вендорены; pip не используется.
- Мост Kotlin↔JS синхронный: не делай тяжёлых вызовов в UI-цикле.
- После backend: `python tests\run_all.py --offline`.
- После UI: `python tools\ui_harness\sync_ui.py` и проверка консоли.
- После метрик/шаблонов: `python tools\dump_ai_context.py`.

## Текущее состояние

Версия 1.5, `versionCode 6`, `APP_VERSION 1.5.0`. Шесть видов спорта,
100 шаблонов, анализатор. APK: `../Predictor-1.5.apk`. Python-регрессии и
браузерный стенд проходят; на реальном Android-устройстве не проверено.

## Первый шаг

Прочитай `AGENTS.md`, `CONTEXT.md`, `docs/ai/PROJECT.md`,
`docs/ai/ARCHITECTURE.md`. Дальше открывай файлы по задаче.

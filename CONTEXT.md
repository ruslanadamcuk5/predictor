# CONTEXT - Betcity Predictor 1.8

Краткая карта проекта для любого ИИ-ассистента. Полные детали — в `docs/ai/`.

## Что это

Android-приложение `by.betcity.predictor` с Python-ядром (Chaquopy). Само
получает live-линию Betcity, статистику, считает прогнозы, ведёт очередь,
результаты, статистику, конструктор правил и анализатор. Сервер не нужен.
Интерфейс на русском.

## Текущее состояние

- Версия 1.15, `versionCode 16`, `APP_VERSION 1.15.0`, `SERVER_VERSION 1.15.0`.
- APK: `../Predictor-1.15.apk`.
- 6 видов: настольный теннис, футбол, хоккей, баскетбол, волейбол, теннис.
- 100 шаблонов правил; метрики: 75/68/89/82/82/82.
- Авто-формирование правил по истории прогнозов с сохранением ручных правил.
- Встроенная нейросеть: учится на всех проверенных матчах, постоянно
  дообучается в фоне, прогнозы включаются переключателем в настройках.
- Движок анализирует все виды сразу; активный вид — только интерфейс и выбор
  правил. Правила видов хранятся отдельно.
- Python-регрессии и браузерный стенд проходят.
- На реальном Android-устройстве ещё не проверено.

## Структура

```text
app/src/main/python/        Python-ядро
  sports.py                 виды, счёт, рынки
  constructor_engine.py     метрики, правила, шаблоны
  predictor_core.py         линия, статистика, модели, результаты
  analyzer.py               анализ истории
  auto_rules.py             авто-генерация правил по статистике
  nn_core.py                признаки, метки, персептрон
  nn_trainer.py             сбор данных, обучение, прогнозы нейросети
  engine_api.py             JSON-API для Kotlin
app/src/main/java/...       MainActivity, EngineService
app/src/main/assets/www/    WebView UI (index.html, app.js, docs.js, style.css)
tests/                      регрессии и фикстуры
tools/                      генератор контекста и UI-стенд
docs/ai/                    полная документация
docs/ai/generated/          машинночитаемые каталоги
```

## Правила работы

1. Прочитайте `AGENTS.md`, затем `docs/ai/README.md`.
2. Перед крупными правками — backup в `.backups/` (git нет).
3. Не ломайте TT-парсер и 46 шаблонов без TT-регрессий.
4. Версия синхронизируется в `engine_api.py`, `build.gradle.kts`,
   `README.md`, `docs/ai/CHANGELOG.md`.
5. Python-пакеты вендорены, pip не используется.
6. Мост Kotlin↔JS синхронный, тяжёлые вызовы — только в фоне.
7. После backend: `python tests\run_all.py --offline`.
8. После UI: `python tools\ui_harness\sync_ui.py` + консоль браузера.
9. После метрик/шаблонов: `python tools\dump_ai_context.py`.

## Ключевые документы

| Файл | О чём |
|---|---|
| `AGENTS.md` | правила, команды, ограничения |
| `docs/ai/PROJECT.md` | продукт, экраны, релиз |
| `docs/ai/ARCHITECTURE.md` | слои, потоки, хранение |
| `docs/ai/SPORTS.md` | виды, счёт, рынки, метрики |
| `docs/ai/CONSTRUCTOR.md` | схема правил и расчёт |
| `docs/ai/ANALYZER.md` | анализатор |
| `docs/ai/UI.md` | WebView и мост |
| `docs/ai/TESTING.md` | тесты и чек-лист устройства |
| `docs/ai/BUILD_RELEASE.md` | сборка и выпуск |
| `docs/ai/AI_PROMPT.md` | готовый промпт для нового чата |

## Главная следующая задача

Установить APK на arm64 Android 7.0+, пройти чек-лист
`docs/ai/TESTING.md` → «Проверка на устройстве» и зафиксировать результат в
`docs/ai/ROADMAP.md`.

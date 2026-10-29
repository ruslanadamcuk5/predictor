# AI_PROMPT — готовый промпт для нового чата

Скопируйте текст ниже в начало нового диалога с любой моделью, у которой есть
доступ к файлам проекта.

---

Ты продолжаешь разработку Android-приложения **Betcity Predictor**. Проект
лежит в:

```text
C:\Users\adamrv\Documents\deepseek-harness\default-workspace\betcity-predictor-android
```

Сначала прочитай (именно в этом порядке):

1. `AGENTS.md` — правила проекта и команды;
2. `CONTEXT.md` — краткая карта проекта;
3. `docs/ai/README.md` — индекс;
4. `docs/ai/PROJECT.md` — продукт и состояние;
5. `docs/ai/ARCHITECTURE.md` — слои и потоки;
6. `docs/ai/generated/summary.json` — сводка по видам спорта.

Дальше открывай только те файлы, которые нужны для задачи:

- виды, счёт, рынки — `docs/ai/SPORTS.md`, `app/src/main/python/sports.py`;
- правила и метрики — `docs/ai/CONSTRUCTOR.md`,
  `app/src/main/python/constructor_engine.py`,
  `docs/ai/generated/metrics/`, `docs/ai/generated/presets/`;
- анализатор — `docs/ai/ANALYZER.md`, `app/src/main/python/analyzer.py`;
- интерфейс — `docs/ai/UI.md`, `app/src/main/assets/www/app.js`,
  `index.html`, `style.css`;
- API и сборка — `docs/ai/BUILD_RELEASE.md`,
  `app/src/main/python/engine_api.py`,
  `app/src/main/java/by/betcity/predictor/MainActivity.kt`.

Обязательные правила:

- отвечай по-русски;
- UI и сообщения — на русском, код — на английском;
- движок анализирует все виды сразу, `active_sport` — только интерфейс и выбор
  правил; правила видов не смешиваются;
- не трогай парсер и модели настольного тенниса без полного прогона
  `tests/test_constructor.py`, `tests/test_presets_new.py`,
  `tests/test_results_screen.py`;
- перед крупными правками делай backup в `.backups/<дата>_<тема>/`
  (git в проекте нет);
- версия синхронизируется в `engine_api.APP_VERSION`,
  `app/build.gradle.kts`, `README.md`, `docs/ai/CHANGELOG.md`;
- не добавляй pip-зависимости: Python-пакеты вендорены в
  `app/src/main/python/`;
- мост Kotlin↔JS синхронный: не делай тяжёлых вызовов в цикле;
- после изменений backend запусти `python tests\run_all.py --offline`
  (PowerShell может показать код 1 из-за warning — смотри итоговую строку);
- после изменений UI запусти `python tools\ui_harness\sync_ui.py` и проверь
  стенд без ошибок консоли;
- после изменения метрик/шаблонов запусти `python tools\dump_ai_context.py`;
- APK собирается так:
  `$env:ANDROID_HOME="C:\Android"; C:\Android\gradle-8.7\bin\gradle.bat --no-daemon assembleDebug`.

Текущее состояние: версия 1.12 (`versionCode 13`, `APP_VERSION 1.12.0`),
шесть видов спорта, 100 шаблонов, анализатор, авто-формирование правил,
встроенная документация и привязка условия к существующему правилу.
Python-регрессии и браузерный стенд проходят. APK собран, но не проверен на
реальном Android-устройстве.

Моя задача: <ОПИШИ ЗАДАЧУ>.

Работай так:

1. прочитай нужные файлы и `docs/ai/generated/`;
2. кратко сформулируй план и риски;
3. внеси изменения;
4. прогони релевантные тесты и стенд;
5. обнови документацию и `generated/`, если изменились данные;
6. в конце перечисли изменённые файлы, результаты тестов и что осталось
   проверить на устройстве.

Если документация расходится с кодом — верь коду и обнови документацию.

---
# BUILD & RELEASE

## 1. Текущая версия

| Параметр | Значение |
|---|---|
| `APP_VERSION` (`engine_api.py`) | 1.13.0 |
| `versionName` (`app/build.gradle.kts`) | 1.13 |
| `versionCode` | 13 |
| `applicationId` | `by.betcity.predictor` |
| `compileSdk` / `targetSdk` | 34 / 34 |
| `minSdk` | 24 |
| ABIs | `arm64-v8a`, `x86_64` |
| Chaquopy | 17.1.0, Python 3.13 |
| Kotlin | 1.9.24 |
| Android Gradle Plugin | 8.5.2 |
| Gradle | 8.7 (внешний, `C:\Android\gradle-8.7`) |

APK: `../Predictor-1.13.apk` относительно корня проекта.

## 2. Где живёт версия

Обновляйте **все** места:

1. `app/src/main/python/engine_api.py` → `APP_VERSION = "1.13.0"`;
2. `app/build.gradle.kts` → `versionCode`, `versionName`;
3. `README.md` — пользовательское описание;
4. `docs/ai/CHANGELOG.md` — запись об изменениях;
5. `docs/ai/PROJECT.md` — таблица текущего релиза.

`versionCode` увеличивается на 1 при каждом выпуске. `versionName` и
`APP_VERSION` должны совпадать по мажору/минору.

## 3. Перед сборкой

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONIOENCODING="utf-8"
python tests\run_all.py --offline
python tools\dump_ai_context.py
python tools\ui_harness\sync_ui.py
```

Проверьте:

- тесты без новых FAIL;
- `docs/ai/generated/` обновлён, если менялись метрики/шаблоны;
- браузерный стенд без ошибок консоли;
- рабочая копия сохранена в `.backups/<дата>_<тема>/`.

## 4. Сборка

```powershell
$env:ANDROID_HOME="C:\Android"
C:\Android\gradle-8.7\bin\gradle.bat --no-daemon assembleDebug
```

Особенности:

- `JAVA_HOME` специально не задаём — сборка проходит на встроенном JDK;
- Chaquopy вызывает `C:/Program Files/Python313/python.exe`; на другой машине
  поправьте `buildPython` в `app/build.gradle.kts`;
- сеть нужна только для скачивания зависимостей Gradle/Chaquopy;
- результат: `app/build/outputs/apk/debug/app-debug.apk`.

Лог предыдущей сборки: `build_log.txt`.

## 5. Копирование и проверка

```powershell
Copy-Item app\build\outputs\apk\debug\app-debug.apk ..\Predictor-1.13.apk -Force

C:\Android\build-tools\34.0.0\apksigner.bat verify --print-certs ..\Predictor-1.13.apk
C:\Android\build-tools\34.0.0\aapt2.exe dump badging ..\Predictor-1.13.apk
```

Ожидаемые метаданные:

```text
package: name='by.betcity.predictor' versionCode='10' versionName='1.9'
sdkVersion:'24'
targetSdkVersion:'34'
native-code: 'arm64-v8a' 'x86_64'
```

Проверка содержимого:

```powershell
python -c "import zipfile; z=zipfile.ZipFile(r'..\Predictor-1.13.apk'); names=z.namelist(); print('app.js' if 'assets/www/app.js' in names else 'NO app.js'); print('docs.js' if 'assets/www/docs.js' in names else 'NO docs.js'); print('app.imy' if 'assets/chaquopy/app.imy' in names else 'NO app.imy')"
```

`assets/chaquopy/app.imy` должен содержать `sports.pyc`,
`constructor_engine.pyc`, `analyzer.pyc`, `predictor_core.pyc`,
`engine_api.pyc`. Строка `1.13.0` должна присутствовать в
`engine_api.pyc`.

Подпись debug (текущая машина):

```text
SHA-256: 8646ca95121c8de2470536d1e8679487c13672e7e1680307a93a9b426e699602
CN=Android Debug
```

## 6. Подпись

Сейчас собирается `debug`-APK с автоматическим debug-keystore. Для публикации
нужно:

1. создать release keystore;
2. добавить `signingConfigs.release` в `app/build.gradle.kts`;
3. собирать `assembleRelease`;
4. не коммитить keystore и пароли;
5. обновить `docs/ai/DECISIONS.md`.

Debug-подпись подходит только для личной установки на телефон.

## 7. Установка

```powershell
adb install -r ..\Predictor-1.13.apk
```

`-r` сохраняет данные приложения. Не используйте `-r -d` без необходимости.
Перед экспериментами с правилами делайте экспорт JSON: данные приложения
хранятся в приватной папке и удаляются при uninstall.

## 8. Резервные копии

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Force ".backups\${stamp}_<тема>" | Out-Null
Copy-Item app\src\main\python\*.py ".backups\${stamp}_<тема>\" -Force
Copy-Item app\src\main\assets\www\* ".backups\${stamp}_<тема>\" -Force
```

В проекте нет git. `.backups/` — единственный способ отката исходников.
Не удаляйте старые копии без проверки.

## 9. Релизный чек-лист

- [ ] Бамп версии в 4 местах (раздел 2).
- [ ] `tests/run_all.py --offline` — без FAIL.
- [ ] `tools/dump_ai_context.py` выполнен.
- [ ] Браузерный стенд: 0 ошибок консоли.
- [ ] `assembleDebug` успешен.
- [ ] APK скопирован в `Predictor-<версия>.apk`.
- [ ] `apksigner verify` и `aapt2 dump badging` совпадают.
- [ ] В `app.imy` есть новые модули.
- [ ] `CHANGELOG.md` и `PROJECT.md` обновлены.
- [ ] Установка на arm64 Android 7.0+ и `TESTING.md` → раздел 6.
- [ ] Резервная копия исходников создана.

## 10. Типовые проблемы

| Симптом | Причина | Решение |
|---|---|---|
| `ModuleNotFoundError` на устройстве | модуль не попал в `app.imy` | проверить, что файл лежит в `app/src/main/python/`, пересобрать |
| Пустой экран WebView | ошибка JS или отсутствует `mock.js` в стенде | открыть `chrome://inspect`, смотреть консоль |
| `versionName` не изменился | забыли `app/build.gradle.kts` | бампнуть `versionCode`/`versionName` |
| `pip` пытается ставить пакеты | зависимость добавлена в `requirements` | вендорить пакет в `app/src/main/python/` |
| APK не устанавливается | другая подпись | удалить приложение или собрать тем же ключом |
| Тест падает только в PowerShell | `RequestsDependencyWarning` | ориентироваться на строку результата, не на код возврата |
| Сборка не находит Python | `buildPython` указывает на чужой путь | поправить путь в `chaquopy {}` |
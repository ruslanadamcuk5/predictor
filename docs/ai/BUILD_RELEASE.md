# BUILD & RELEASE

## 1. Текущая версия

| Параметр | Значение |
|---|---|
| `APP_VERSION` (`engine_api.py`) | 1.15.0 |
| `versionName` (`app/build.gradle.kts`) | 1.15 |
| `versionCode` | 16 |
| `applicationId` | `by.betcity.predictor` |
| `compileSdk` / `targetSdk` | 34 / 34 |
| `minSdk` | 24 |
| ABIs | `arm64-v8a`, `x86_64` |
| Chaquopy | 17.1.0, Python 3.13 |
| Kotlin | 1.9.24 |
| Android Gradle Plugin | 8.5.2 |
| Gradle | 8.7+ (внешний; проверено на 8.9) |

APK: `../Predictor-1.15.apk` относительно корня проекта.

## 2. Где живёт версия

Обновляйте **все** места:

1. `app/src/main/python/engine_api.py` → `APP_VERSION = "1.15.0"`;
2. `app/build.gradle.kts` → `versionCode`, `versionName`;
3. `README.md` — пользовательское описание;
4. `docs/ai/CHANGELOG.md` — запись об изменениях;
5. `server/online_app.py` → `SERVER_VERSION = "1.15.0"`;
6. `docs/ai/PROJECT.md` — таблица текущего релиза;
7. `docs/ai/BUILD_RELEASE.md` — эта таблица.

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

### Сборка на Linux

```bash
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64
export ANDROID_HOME=/path/to/android-sdk
export CHAQUOPY_BUILD_PYTHON=/opt/python3.13/bin/python3.13
# если Java не видит системные сертификаты:
export GRADLE_OPTS="-Djavax.net.ssl.trustStorePassword=changeit"
gradle --no-daemon assembleRelease
```

Нужны Android SDK Platform 34 и Python 3.13 с `pip`. Результат:
`app/build/outputs/apk/release/app-release.apk`. Лог предыдущей сборки:
`build_log.txt`.

## 5. Копирование и проверка

```powershell
Copy-Item app\build\outputs\apk\debug\app-debug.apk ..\Predictor-1.15.apk -Force

C:\Android\build-tools\34.0.0\apksigner.bat verify --print-certs ..\Predictor-1.15.apk
C:\Android\build-tools\34.0.0\aapt2.exe dump badging ..\Predictor-1.15.apk
```

Ожидаемые метаданные:

```text
package: name='by.betcity.predictor' versionCode='16' versionName='1.15'
sdkVersion:'24'
targetSdkVersion:'34'
native-code: 'arm64-v8a' 'x86_64'
```

Проверка содержимого:

```powershell
python -c "import zipfile; z=zipfile.ZipFile(r'..\Predictor-1.15.apk'); names=z.namelist(); print('app.js' if 'assets/www/app.js' in names else 'NO app.js'); print('docs.js' if 'assets/www/docs.js' in names else 'NO docs.js'); print('app.imy' if 'assets/chaquopy/app.imy' in names else 'NO app.imy')"
```

`assets/chaquopy/app.imy` — zip с Python-модулями. Chaquopy 17 кладёт
исходники `.py` (не `.pyc`): проверьте `sports.py`, `constructor_engine.py`,
`analyzer.py`, `predictor_core.py`, `engine_api.py`, `rule_advisor.py`.
Строка `1.15.0` должна присутствовать в `engine_api.py`.

Подпись текущей сборки (debug, Linux-машина):

```text
SHA-256: 37f15cb0f9deb2b0b421412be4fa6610c9a1b8268408bf067928255416253397
CN=Android Debug
```

Debug-ключ привязан к машине. Для обновлений на устройствах пользователей
нужен стабильный release-keystore: без него APK с другой подписью не
установится поверх старого.

## 6. Подпись

По умолчанию собирается `debug`-APK с автоматическим debug-keystore. Для
release-сборки `app/build.gradle.kts` читает переменные окружения:

| Переменная | Значение |
|---|---|
| `PREDICTOR_KEYSTORE` | путь к `.jks` |
| `PREDICTOR_KEYSTORE_PASSWORD` | пароль хранилища |
| `PREDICTOR_KEY_ALIAS` | alias ключа |
| `PREDICTOR_KEY_PASSWORD` | пароль ключа |

Если они не заданы, используется debug-подпись. Keystore и пароли нельзя
коммитить. Обновление устанавливается поверх только той же подписью: если
пользователь ставил debug-APK, release-APK с другим ключом не встанет без
удаления приложения и потери данных.

```bash
export PREDICTOR_KEYSTORE=/secure/predictor.jks
export PREDICTOR_KEYSTORE_PASSWORD=...
export PREDICTOR_KEY_ALIAS=predictor
export PREDICTOR_KEY_PASSWORD=...
gradle assembleRelease
```

## 6.1. Публикация автообновления

```bash
python tools/publish_release.py app/build/outputs/apk/release/app-release.apk \
    --notes "Что нового в 1.15"
python tools/prepare_server.py
```

`publish_release.py` берёт версию из Gradle, копирует APK в `releases/`,
считает SHA-256, пишет `releases/update.json` и оставляет `--keep` последних
сборок. `prepare_server.py` складывает релизы в `dist/server/releases/`.
Сервер отдаёт манифест по `GET /api/v1/update`, файл — по
`/releases/<имя>.apk` с поддержкой `HEAD` и `Range`. Подробнее —
`server/README.md`.

В Linux-сборке путь к Python для Chaquopy задаётся переменной
`CHAQUOPY_BUILD_PYTHON` (по умолчанию скрипт ищет Python 3.13 в системе).

## 7. Установка

```powershell
adb install -r ..\Predictor-1.15.apk
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

Проект хранится в git (`origin` — GitHub). Перед крупными правками всё равно
делайте `.backups/`: коммит фиксирует код, но не локальные релизы и keystore.
Не удаляйте старые копии без проверки.

## 9. Релизный чек-лист

- [ ] Бамп версии во всех местах (раздел 2).
- [ ] `tests/run_all.py --offline` — без FAIL.
- [ ] `tools/dump_ai_context.py` выполнен.
- [ ] Браузерный стенд: 0 ошибок консоли.
- [ ] `assembleDebug` успешен.
- [ ] APK скопирован в `Predictor-<версия>.apk`.
- [ ] APK опубликован для автообновления (`tools/publish_release.py`).
- [ ] `apksigner verify` и `aapt2 dump badging` совпадают.
- [ ] В `app.imy` есть новые модули.
- [ ] `CHANGELOG.md` и `PROJECT.md` обновлены.
- [ ] `releases/update.json` проверен: версия, размер, SHA-256, ссылка.
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
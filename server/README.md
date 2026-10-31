# Онлайн-сервис Betcity Predictor

Необязательный сервер для режима «Использовать онлайн» и **веб-кабинета
истории**. Телефон отправляет снимок истории и правил, сервер считает **тот
же** отчёт модулем `analysis_service`, что и приложение, и возвращает анализ
вместе с рекомендациями.

Кроме онлайн-анализа сервер хранит историю в SQLite: устройства, правила,
все изменения правил, рекомендации и их эффективность, прогнозы и
результаты. Кабинет на главной странице показывает эту историю с любого
устройства. Сервис работает на чистом Python (стандартная библиотека +
модули проекта), поэтому на alwaysdata не нужны pip-пакеты.

## Что умеет

| Метод | Адрес | Назначение |
|---|---|---|
| GET | `/` | Веб-кабинет истории |
| GET | `/service` | Страница состояния сервиса |
| GET | `/api/v1/ping` | Проверка связи |
| POST | `/api/v1/analyze` | Анализ истории и рекомендации |
| POST | `/api/v1/sync` | Приём снимка истории и правил с устройства |
| GET | `/api/v1/history/devices` | Все устройства со сводкой и качеством |
| GET | `/api/v1/history/devices/<id>/overview` | Обзор устройства |
| GET | `/api/v1/history/devices/<id>/rules` | Правила и их точность |
| GET | `/api/v1/history/devices/<id>/recommendations` | Рекомендации и эффект |
| GET | `/api/v1/history/devices/<id>/events` | История изменений правил |
| GET | `/api/v1/history/devices/<id>/predictions` | Прогнозы и результаты |
| POST | `/api/v1/history/devices/<id>/rename` | Переименовать устройство |
| GET | `/api/v1/history/health` | Состояние базы |
| GET/HEAD | `/api/v1/update` | Манифест обновления APK |
| GET/HEAD | `/releases/<файл>.apk` | APK с поддержкой `Range` |

Если задана переменная окружения `PREDICTOR_TOKEN`, запросы к API требуют
заголовок:

```
Authorization: Bearer <токен>
```

Без токена сайт открыт всем: это удобно для личного приложения, но
`/api/v1/analyze` и история устройств доступны любому желающему. Если нужен
доступ по токену, задайте `PREDICTOR_TOKEN` и впишите его в настройках
приложения — кабинет спросит тот же токен и сохранит его в браузере.
`/api/v1/update` и файлы из `/releases/` открыты без токена: приложение должно
проверять обновление и до входа в онлайн-режим.

## Сборка папки для загрузки

Из корня проекта:

```powershell
python tools\prepare_server.py
```

Появится `dist/server/`:

```
app.wsgi
online_app.py
lazy_app.py
cgi_adapter.py
history_store.py
history_ui.py
index.html          готовая главная страница (кабинет) для www/
README.md
python/
  analysis_service.py
  analyzer.py
  auto_rules.py
  profit.py
  rule_advisor.py
  constructor_engine.py
  sports.py
releases/
  update.json
  predictor-1.19.apk
```

Если релизы ещё не опубликованы, `releases/` будет пустым, а
`/api/v1/update` вернёт `published: false`.

## alwaysdata.com: отдельный сайт

Целевой адрес — `https://predictor.alwaysdata.net` (аккаунт с логином
`predictor`, сайт в корне домена).

На аккаунте доступны два способа запуска. Сейчас используется **CGI на
статическом сайте**: он не требует панели, virtualenv и pip-пакетов.

### Вариант A. Сайт PHP/static + CGI (рабочая схема)

Сайт создаётся в панели как **PHP** или **Static** с DocumentRoot
`/home/<логин>/www`. Запросы `/api/*` выполняет CGI-скрипт, который вызывает
тот же `online_app.application`.

Раскладка файлов:

```
/home/<логин>/predictor/            серверный бандл: online_app.py, python/
/home/<логин>/predictor/.env        настройки
/home/<логин>/www/.htaccess         rewrite на CGI для /api/* и служебных страниц
/home/<логин>/www/cgi/predictor.py  CGI-адаптер (chmod 755)
/home/<логин>/www/index.html        кабинет истории (из dist/server/index.html)
/home/<логин>/www/releases/         APK и update.json (раздаёт Apache)
/home/<логин>/predictor/data/       SQLite: predictor.sqlite3
```

Загрузка из корня проекта:

```bash
python tools/prepare_server.py
scp -r dist/server/* predictor@ssh-predictor.alwaysdata.net:/home/predictor/predictor/
scp dist/server/cgi_adapter.py predictor@ssh-predictor.alwaysdata.net:/home/predictor/www/cgi/predictor.py
scp releases/* predictor@ssh-predictor.alwaysdata.net:/home/predictor/www/releases/
```

На сервере:

```bash
chmod 755 /home/predictor/www/cgi/predictor.py
```

`/home/<логин>/predictor/.env`:

```ini
PREDICTOR_TOKEN=
PREDICTOR_RELEASES_DIR=/home/<логин>/www/releases
PREDICTOR_BASE_PATH=
PREDICTOR_DATA_DIR=/home/<логин>/predictor/data
```

`/home/<логин>/www/.htaccess`:

```apache
Options +ExecCGI
AddHandler cgi-script .py

RewriteEngine On
RewriteRule ^api(/.*)?$ /cgi/predictor.py [L,QSA]
RewriteRule ^(history|cabinet|service)/?$ /cgi/predictor.py [L,QSA]
```

Главная страница `/` отдаётся Apache как статика из `www/index.html` — это
готовый кабинет из `dist/server/index.html`. Если менялся `history_ui.py`,
пересоберите бандл и скопируйте `index.html` в `www/` заново. Каталог
`PREDICTOR_DATA_DIR` должен быть доступен на запись пользователю сайта:
SQLite создаст там `predictor.sqlite3` при первом `/api/v1/sync`.

APK и `update.json` лежат в `www/releases/` и отдаются Apache статически:
это быстрее CGI и уже поддерживает `Range`. `PREDICTOR_RELEASES_DIR`
указывает на тот же каталог, чтобы манифест брал реальный размер и SHA-256.

Проверка:

```bash
python tools/check_live.py --base https://predictor.alwaysdata.net
```

CGI-процесс запускается под пользователем сайта, поэтому каталоги
`/home/<логин>/predictor` и `www/cgi` не должны быть доступны другим
пользователям. Файл `.env` держите с правами `600`.

### Вариант B. Штатный Python WSGI

Если панель доступна и сайт можно создать как **Python WSGI**, запросы
обрабатывает `app.wsgi` напрямую, без CGI:

1. **Web → Sites → Add a site**.
2. Тип сайта — **Python WSGI**.
3. **Addresses**: `predictor.alwaysdata.net` (без пути).
4. **Working directory**: `/home/<логин>/predictor`.
5. **Python version**: 3.13.
6. **Virtualenv**: `/home/<логин>/.virtualenvs/predictor`.
7. **WSGI file**: `/home/<логин>/predictor/app.wsgi`.
8. Включите **Force HTTPS**.
9. Проверьте `.env` рядом с `app.wsgi`:

```ini
PREDICTOR_TOKEN=
PREDICTOR_RELEASES_DIR=/home/<логин>/predictor/releases
PREDICTOR_BASE_PATH=
```

`PREDICTOR_BASE_PATH` пустой, потому что сервис стоит в корне сайта. Токен
пуст — приложение работает без ручной настройки. Если нужен доступ по токену,
задайте его здесь и впишите тот же токен в настройках приложения.

10. Откройте `https://predictor.alwaysdata.net/` — должна появиться страница
    состояния, а `/api/v1/ping` — вернуть JSON.

### Если нужного адреса нет

- Укажите в приложении фактический адрес сайта: «Настройки» → «Онлайн-режим».
  Адрес хранится в настройках и не требует пересборки APK.
- Используйте собственный домен на платном тарифе.
- Разверните сервис в подкаталоге сайта, который вы готовы менять. Не
  монтируйте его в чужой или рабочий сайт без явного согласия: обновление
  основного приложения может перезаписать WSGI-файл.

Монтаж в подкаталог (крайний случай) через `DispatcherMiddleware`:

```python
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from importlib.machinery import SourceFileLoader

predictor = SourceFileLoader(
    "predictor_wsgi", "/home/<логин>/predictor/app.wsgi"
).load_module()
application = DispatcherMiddleware(
    application, {"/predictor": predictor.application}
)
```

В этом случае задайте `PREDICTOR_BASE_PATH=/predictor` и включите
**path_trim** в настройках сайта. `online_app.py` учитывает и `SCRIPT_NAME`,
поэтому ссылки на APK и манифест остаются рабочими.

Если alwaysdata показывает ошибку 500, откройте **Web → Sites → ваш сайт →
Logs**. Для CGI traceback также попадает в `admin/logs/apache/apache.log`.
Чаще всего причина — неверный путь к `online_app.py`, каталогу `python/`
или отсутствующий `PREDICTOR_ROOT` в адаптере.

## Локальная проверка без сайта

Публичный сайт для проверки не обязателен. Из корня проекта:

```bash
python tools/serve_online.py
```

Скрипт напечатает адрес компьютера в локальной сети, например
`http://192.168.1.10:8099`. В приложении укажите его в «Настройки» →
«Онлайн-режим» (без `/api`). Телефон и компьютер должны быть в одной Wi-Fi
сети. Приложение разрешает HTTP для таких проверок; для постоянной работы
используйте HTTPS-сайт.

Проверка сервиса без телефона:

```bash
python tools/check_live.py --base http://127.0.0.1:8099
```

## Подключение в приложении

1. «Настройки» → «Онлайн-режим».
2. Адрес сайта: `https://predictor.alwaysdata.net` (без `/api`).
3. Токен доступа: тот же `PREDICTOR_TOKEN` (если он пуст — оставьте поле пустым).
4. «Проверить подключение» → должно появиться «Сайт отвечает».
5. Включите «Отправлять историю в веб-кабинет» и задайте интервал
   (по умолчанию 15 минут).
6. На экране «Анализ» нажмите «Использовать онлайн».
7. Кнопка «Открыть веб-кабинет» открывает `https://predictor.alwaysdata.net/`.

При ошибке сети приложение считает анализ локально, если включён
«Локальный расчёт при ошибке».

## Проверка запроса вручную

```bash
curl -X POST https://predictor.alwaysdata.net/api/v1/analyze \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sports":["table_tennis"],"predictions":{},"rules":{}}'
```

Ответ: JSON с полями `ok`, `observations`, `failure`, `success`,
`rule_reviews`, `recommendations`, `advisor_state`, `server_version`.

## Публикация APK для автообновления

Сначала соберите APK, затем из корня проекта:

```bash
python tools/publish_release.py app/build/outputs/apk/release/app-release.apk \
    --notes "Что нового"
python tools/prepare_server.py
scp -r dist/server/* LOGIN@ssh-LOGIN.alwaysdata.net:/home/LOGIN/predictor/
```

Скрипт берёт версию из `app/build.gradle.kts`, копирует APK в `releases/`,
считает SHA-256 и пишет `releases/update.json`. Старые APK удаляются по
`--keep` (по умолчанию 3). Проверить манифест без публикации:
`--dry-run`.

Приложение при запуске запрашивает `GET /api/v1/update`. Если `version_code`
больше установленного, оно скачивает APK, сверяет SHA-256 и открывает
системный установщик. Обновление встанет только поверх APK с той же подписью.

## Обновление серверного кода

Повторите `python tools\prepare_server.py` и загрузите `dist/server/*` поверх
старых файлов. Каталог `python/` можно заменить целиком; `releases/` сохраняйте,
если не хотите заново публиковать APK.

## Синхронизация истории

Приложение отправляет `POST /api/v1/sync` при работе движка и вручную.
В снимке: идентификатор и модель устройства, параметры анализа (без токенов
и Telegram), правила по видам, история прогнозов и состояние рекомендаций.
Сервер:

* обновляет правила и записывает каждое изменение с diff «было → стало»;
* хранит прогнозы и результаты, считает точность по правилам и устройствам;
* пересчитывает рекомендации тем же `rule_advisor`, что и приложение;
* отслеживает жизненный цикл: открыта → применена/скрыта/закрыта;
* считает эффект «до/после» по фактическим результатам.

Кабинет обновляется автоматически и показывает все устройства с индикатором
качества (Wilson, объём, свежесть), историю изменений и эффективность
рекомендаций.

## Ограничения

* Один запрос ограничен 12 МБ (после распаковки gzip — тоже 12 МБ).
* Максимум 8000 записей истории за запрос; для периодической синхронизации
  приложение отправляет последние 3000.
* История хранится 400 дней, не более 40 000 строк прогнозов на устройство.
* Персональные данные не сохраняются: только название/модель устройства и
  спортивная история. Токены и Telegram-настройки отфильтровываются.
* Очередей и фоновых задач нет: рекомендации пересчитываются при синхронизации.

# Онлайн-сервис Betcity Predictor

Необязательный сервер для режима «Использовать онлайн». Телефон отправляет
снимок истории и правил, сервер считает **тот же** отчёт модулем
`analysis_service`, что и приложение, и возвращает анализ вместе с
рекомендациями. Пользовательские данные на сервере не сохраняются.

Сервис работает на чистом Python (стандартная библиотека + модули проекта),
поэтому на alwaysdata не нужны pip-пакеты и база данных.

## Что умеет

| Метод | Адрес | Назначение |
|---|---|---|
| GET | `/` | Страница состояния |
| GET | `/api/v1/ping` | Проверка связи |
| POST | `/api/v1/analyze` | Анализ истории и рекомендации |
| GET/HEAD | `/api/v1/update` | Манифест обновления APK |
| GET/HEAD | `/releases/<файл>.apk` | APK с поддержкой `Range` |

Если задана переменная окружения `PREDICTOR_TOKEN`, запросы к API требуют
заголовок:

```
Authorization: Bearer <токен>
```

Без токена сайт открыт всем: это удобно для личного приложения, но
`/api/v1/analyze` может вызвать любой желающий. Если нужен доступ по токену,
задайте `PREDICTOR_TOKEN` и впишите его в настройках приложения.
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
README.md
python/
  analysis_service.py
  analyzer.py
  auto_rules.py
  rule_advisor.py
  constructor_engine.py
  sports.py
releases/
  update.json
  predictor-1.16.apk
```

Если релизы ещё не опубликованы, `releases/` будет пустым, а
`/api/v1/update` вернёт `published: false`.

## alwaysdata.com: отдельный сайт

Целевой адрес — `https://predictor.alwaysdata.net`.

Важное ограничение alwaysdata: на бесплатном тарифе сайт создаётся только
на адресе аккаунта `<логин>.alwaysdata.net`, а произвольные адреса
`*.alwaysdata.net` нельзя выбрать и на платном тарифе — они принадлежат
аккаунтам с соответствующим логином. Поэтому `predictor.alwaysdata.net`
появится только у аккаунта с логином `predictor` либо на собственном домене.
Пока такого адреса нет, укажите в приложении фактический URL сайта.

Когда адрес создан в панели, сайт настраивается в корне:

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
Logs** и проверьте traceback. Чаще всего причина — неверный путь к `app.wsgi`
или каталогу `python/`.

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
5. На экране «Анализ» нажмите «Использовать онлайн».

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

## Ограничения

* Сервер не хранит историю: каждый запрос самодостаточен.
* Нет базы данных и очередей — это осознанно, чтобы сайт работал на
  минимальном тарифе и не содержал персональных данных.
* Один запрос ограничен 12 МБ (после распаковки gzip — тоже 12 МБ).
* Максимум 8000 записей истории за запрос; более старые записи приложение
  не отправляет.

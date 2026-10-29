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

Без токена сайт открыт всем. Для личного сервера токен обязателен.
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
  predictor-1.15.apk
```

Если релизы ещё не опубликованы, `releases/` будет пустым, а
`/api/v1/update` вернёт `published: false`.

## alwaysdata.com: пошагово

Бесплатный тариф alwaysdata разрешает сайты только на адресе аккаунта
(`<логин>.alwaysdata.net`), поэтому сервис удобно повесить на подкаталог
рядом с другим сайтом:

```
https://<логин>.alwaysdata.net/predictor
```

Каталог `predictor` уже содержит всё необходимое. В панели:

1. **Web → Sites → Add a site**.
2. Тип сайта — **Python WSGI**.
3. **Addresses**: `<логин>.alwaysdata.net/predictor` (именно с путём).
4. **Path**: `predictor`.
5. **Working directory**: `/home/<логин>/predictor`.
6. **Python version**: 3.13.
7. **Virtualenv**: `/home/<логин>/.virtualenvs/predictor`.
8. **WSGI file**: `/home/<логин>/predictor/app.wsgi`.
9. Включите **path_trim** (обрезать путь) и **Force HTTPS**.
10. Сохраните сайт и откройте
    `https://<логин>.alwaysdata.net/predictor/` — должна появиться страница
    состояния.

Переменные окружения задавать не обязательно: `app.wsgi` читает файл
`.env` рядом с собой. В нём уже лежат:

```ini
PREDICTOR_TOKEN=<длинная случайная строка>
PREDICTOR_RELEASES_DIR=/home/<логин>/predictor/releases
PREDICTOR_BASE_PATH=/predictor
```

`PREDICTOR_BASE_PATH` нужен, чтобы ссылки в манифесте обновления были
публичными (`/predictor/releases/...`), даже когда WSGI видит уже обрезанный
путь. Если сайт создан в корне отдельного домена, уберите эту переменную.

Если позже появится отдельный домен или аккаунт с адресом без пути, создайте
обычный сайт **Python WSGI** с Working directory `/home/<логин>/predictor`,
WSGI file `/home/<логин>/predictor/app.wsgi` и пустым `PREDICTOR_BASE_PATH`.
Код поддерживает оба варианта.

Если alwaysdata показывает ошибку 500, откройте **Web → Sites → ваш сайт →
Logs** и проверьте traceback. Чаще всего причина — неверный путь к `app.wsgi`
или каталогу `python/`.

## Подключение в приложении

1. «Настройки» → «Онлайн-режим».
2. Адрес сайта: `https://LOGIN.alwaysdata.net` (без `/api`).
3. Токен доступа: тот же `PREDICTOR_TOKEN`.
4. «Проверить подключение» → должно появиться «Сайт отвечает».
5. На экране «Анализ» нажмите «Использовать онлайн».

При ошибке сети приложение считает анализ локально, если включён
«Локальный расчёт при ошибке».

## Проверка запроса вручную

```bash
curl -X POST https://LOGIN.alwaysdata.net/api/v1/analyze \
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

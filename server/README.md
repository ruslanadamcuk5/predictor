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

Если задана переменная окружения `PREDICTOR_TOKEN`, запросы к API требуют
заголовок:

```
Authorization: Bearer <токен>
```

Без токена сайт открыт всем. Для личного сервера токен обязателен.

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
```

## alwaysdata.com: пошагово

1. Войдите в панель alwaysdata и создайте сайт:
   **Web → Sites → Add a site**.
2. Тип сайта — **WSGI**. Python — 3.10 или новее.
3. Каталог сайта, например `/home/LOGIN/predictor`.
4. Загрузите содержимое `dist/server/` в этот каталог. Удобнее всего по SSH:
   ```bash
   scp -r dist/server/* LOGIN@ssh-LOGIN.alwaysdata.net:/home/LOGIN/predictor/
   ```
   Либо загрузите архив через файловый менеджер панели.
5. В настройках сайта укажите WSGI-файл:
   `/home/LOGIN/predictor/app.wsgi`
6. В **Environment variables** сайта добавьте:
   ```
   PREDICTOR_TOKEN=<длинная случайная строка>
   ```
   Сгенерировать токен можно командой `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
7. Сохраните сайт и откройте выданный адрес, например
   `https://LOGIN.alwaysdata.net`. Должна открыться страница состояния.
8. Проверьте API:
   ```bash
   curl https://LOGIN.alwaysdata.net/api/v1/ping -H "Authorization: Bearer TOKEN"
   ```
   Ответ содержит `"ok": true` и версию сервера.

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

## Обновление

Повторите `python tools\prepare_server.py` и загрузите `dist/server/*` поверх
старых файлов. Каталог `python/` можно заменить целиком.

## Ограничения

* Сервер не хранит историю: каждый запрос самодостаточен.
* Нет базы данных и очередей — это осознанно, чтобы сайт работал на
  минимальном тарифе и не содержал персональных данных.
* Один запрос ограничен 12 МБ (после распаковки gzip — тоже 12 МБ).
* Максимум 8000 записей истории за запрос; более старые записи приложение
  не отправляет.

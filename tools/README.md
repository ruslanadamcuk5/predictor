# tools

Вспомогательные скрипты разработки. В APK не попадают.

| Скрипт | Назначение |
|---|---|
| `dump_ai_context.py` | пересобирает `docs/ai/generated/` из кода |
| `prepare_server.py` | собирает `dist/server/` для alwaysdata |
| `publish_release.py` | публикует APK в `releases/` и пишет `update.json` |
| `ui_harness/sync_ui.py` | собирает браузерный стенд WebView |

Скрипты запускаются из корня проекта:

```powershell
python tools\dump_ai_context.py
python tools\ui_harness\sync_ui.py
python tools\prepare_server.py
```

Публикация обновления:

```powershell
python tools\publish_release.py app\build\outputs\apk\release\app-release.apk `
    --notes "Что нового"
```

`publish_release.py` берёт `versionName`/`versionCode` из
`app/build.gradle.kts`, копирует APK в `releases/`, считает SHA-256, пишет
`releases/update.json` и удаляет старые сборки по `--keep`. Флаг `--dry-run`
показывает манифест без записи. Подробности — `server/README.md`.

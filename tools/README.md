# tools

Вспомогательные скрипты разработки. В APK не попадают.

| Скрипт | Назначение |
|---|---|
| `dump_ai_context.py` | пересобирает `docs/ai/generated/` из кода |
| `ui_harness/sync_ui.py` | собирает браузерный стенд WebView |

Оба скрипта запускаются из корня проекта:

```powershell
python tools\dump_ai_context.py
python tools\ui_harness\sync_ui.py
```

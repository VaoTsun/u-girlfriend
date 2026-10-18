---
name: Kotel Guard (Охрана котла)
description: Автоматическая охрана отопления — фоновый скрипт каждые 30 минут проверяет подъём температуры теплоносителя и шлёт в Telegram «🔥 Котёл разожжён — проверь заслонку и насос». Использовать, когда пользователь спрашивает про «охрану котла», kotel-guard, автопроверку топки, уведомление о растопке, статус или настройки этой задачи.
---

# Kotel Guard — охрана котла

Фоновый наблюдатель: сам каждые 30 минут (через **Планировщик задач Windows**)
проверяет температуру теплоносителя и при резком подъёме шлёт уведомление
в Telegram — мол, разжёг котёл, проверь заслонку и насос.

Не требует OpenCode — работает как обычная задача Планировщика.

## Логика

1. Каждые 30 минут скрипт читает `http://192.168.88.171:90/getdots`
   (устройство `Отопление`, колонка `cels`) за окно **180 минут**.
2. Считает `подъём = текущее − минимум за окно`.
3. Если `подъём ≥ 20 °C` и состояние «вооружено» → отправляет в Telegram:
   ```
   🔥 Котёл разожжён  (16.10.2026 18:30)
   Отопление: 21 → 43 °C (+22 °C за 180 мин)
   Проверь, закрыта ли заслонка, и включился ли насос!
   ```
4. **Одно уведомление на одну топку.** После отправки состояние → «уже
   уведомлено»; повторно шлёт только когда подъём опустится ≤ 10 °C
   (половина порога, `rearm_ratio`), т.е. котёл почти остыл или снова
   затоплен после остывания.
5. Если данные не обновились (последняя точка не изменилась) — пропуск,
   без отправки.

Все проверки пишутся в `kotel-guard.log` рядом со скриптом.

## Файлы

| файл | назначение |
|------|-----------|
| `scripts/kotel-guard.ps1` | сам скрипт (UTF-8 с BOM!) |
| `config.json` | токен/чат, порог, окно, интервал |
| `state.json` | состояние «вооружено/уведомлено» (создаётся сам) |
| `kotel-guard.log` | журнал проверок |

### config.json
```json
{
  "token": "<bot token>",          "chat_id": "<chat id>",
  "server": "192.168.88.171:90",
  "device": "Отопление",           "column": "cels",
  "threshold_c": 20,               // порог подъёма, °C
  "window_minutes": 180,           // окно «минимума», минут
  "rearm_ratio": 0.5,              // перевзвод = подъём ≤ порог × ratio
  "check_interval_minutes": 30     // только справочно; реальный интервал задан в задаче
}
```

## Ручной запуск и отладка

```powershell
# обычная проверка (то же, что делает задача Планировщика)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts/kotel-guard.ps1"

# показать решение, ничего не отправлять и не менять
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts/kotel-guard.ps1" -DryRun

# принудительно послать тестовое уведомление в Telegram
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts/kotel-guard.ps1" -Force
```

Коды выхода: `0` — окно/решение без действия или уведомление ушло;
`2` — конфиг; `3` — нет связи/устройства/данных; `4` — данных нет (stale);
`5` — ошибка отправки в Telegram (в этом случае состояние **не**
сбрасывается, уведомление уйдёт при следующей проверке).

## Задача Планировщика

Имя задачи: **`kotel-guard`**. Действие:
```
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<skill>\scripts\kotel-guard.ps1"
```
Триггер: раз в 30 минут, без ограничения длительности.

Создание/пересоздание вручную:
```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\_d\u-girlfriend\skills\kotel-guard\scripts\kotel-guard.ps1"'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration ([TimeSpan]::MaxValue)
Register-ScheduledTask -TaskName "kotel-guard" -Action $action -Trigger $trigger -Force
```

Полезные команды:
```powershell
Get-ScheduledTask -TaskName "kotel-guard"          # есть ли задача
Start-ScheduledTask  -TaskName "kotel-guard"       # запустить сейчас (проверка)
Stop-ScheduledTask   -TaskName "kotel-guard"       # остановить
Unregister-ScheduledTask -TaskName "kotel-guard" -Confirm:$false   # удалить
Get-Content "<skill>\kotel-guard.log" -Tail 20     # журнал
```

## Как отвечать пользователю

- **Статус**: прочитай хвост `kotel-guard.log` и `state.json` — скажи, стоит
  ли задача, состояние (вооружено/уведомлено), последняя проверка и подъём.
- **«Проверь, что шлётся»** → `-DryRun`.
- **«Отправь тест»** → `-Force`.
- Изменение порога/окна — правь `config.json` (порог, окно, rearm_ratio);
  интервал — пересоздай триггер задачи.

## Заметки по поддержке

- `kotel-guard.ps1` — **UTF-8 с BOM** (иначе PowerShell 5.1 ломает кириллицу).
- `config.json` содержит токен бота — не коммитить в публичные репозитории.
- Токен/чат общие с навыком `heating-telegram` — при смене бота обнови оба.
- `state.json` сбрасывай вручную (удали файл), если хочешь принудительно
  перевести охрану в состояние «вооружено».
- Данные берутся из JSON-эндпоинтов графика (`/getdevs`, `/getdots`),
  а не чтением картинки.

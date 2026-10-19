---
name: Kotel Guard (Охрана котла)
description: Автоматическая охрана отопления — фоновый скрипт каждые 30 минут проверяет подъём температуры теплоносителя и шлёт в Telegram «🔥 Котёл разожжён — проверь заслонку и насос». Использовать, когда пользователь спрашивает про «охрану котла», kotel-guard, автопроверку топки, уведомление о растопке, статус или настройки этой задачи.
---

# Kotel Guard — охрана котла

Фоновый наблюдатель: сам каждые 30 минут проверяет температуру теплоносителя
и при резком подъёме шлёт уведомление в Telegram — мол, разжёг котёл, проверь
заслонку и насос.

**С 19.10.2026 работает на проде (192.168.88.171) в cron** — Python-версия
`scripts/kotel-guard.py`. Windows-задача удалена; `kotel-guard.ps1` оставлен
как legacy (Windows/dev). Деплой: `git push` в u-girlfriend + `git pull`
на проде (`ssh ubarn171 "cd /home/vao/u-girlfriend && git pull --ff-only"`).

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
| `scripts/kotel-guard.py` | основной скрипт (Python 3, запускается в cron на проде) |
| `scripts/kotel-guard.ps1` | legacy-версия для Windows (тот же API и логика) |
| `config.json` | токен/чат, порог, окно, интервал (в .gitignore, на проде создаётся вручную) |
| `state.json` | состояние «вооружено/уведомлено» (создаётся сам) |
| `kotel-guard.log` | журнал проверок |
| `cron.log` | stdout задачи из cron |

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

На проде (SSH `ubarn171`):
```bash
cd /home/vao/u-girlfriend
python3 skills/kotel-guard/scripts/kotel-guard.py             # обычная проверка
python3 skills/kotel-guard/scripts/kotel-guard.py --dry-run   # решение без отправки
python3 skills/kotel-guard/scripts/kotel-guard.py --force     # тестовое уведомление
```

Локально (Windows): та же команда через `python`; ps1 — эквивалент:
```powershell
python "scripts/kotel-guard.py" --dry-run
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts/kotel-guard.ps1" -DryRun
```

Коды выхода: `0` — окно/решение без действия или уведомление ушло;
`2` — конфиг; `3` — нет связи/устройства/данных; `4` — данных нет (stale);
`5` — ошибка отправки в Telegram (в этом случае состояние **не**
сбрасывается, уведомление уйдёт при следующей проверке).

## Задача (прод, cron)

На проде в `crontab` пользователя `vao` (добавлена 19.10.2026):
```
*/30 * * * * /usr/bin/python3 /home/vao/u-girlfriend/skills/kotel-guard/scripts/kotel-guard.py >> /home/vao/u-girlfriend/skills/kotel-guard/cron.log 2>&1
```

Windows-задача Планировщика `kotel-guard` удалена 19.10.2026 (перенос на прод).
Если нужно вернуть локально:
```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\_d\u-girlfriend\skills\kotel-guard\scripts\kotel-guard.ps1"'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration ([TimeSpan]::MaxValue)
Register-ScheduledTask -TaskName "kotel-guard" -Action $action -Trigger $trigger -Force
```

## Как отвечать пользователю

- **Статус**: прочитай хвост `kotel-guard.log` и `state.json` **на проде**
  (`ssh ubarn171 "tail -5 /home/vao/u-girlfriend/skills/kotel-guard/kotel-guard.log"`)
  — скажи, стоит ли задача, состояние (вооружено/уведомлено), последняя проверка и подъём.
- **«Проверь, что шлётся»** → `--dry-run`.
- **«Отправь тест»** → `--force`.
- Изменение порога/окна — правь `config.json` (порог, окно, rearm_ratio) **на проде**
  (файл не в git); интервал — править строку в crontab на проде.

## Заметки по поддержке

- `config.json` содержит токен бота — не коммитить (в .gitignore); на проде
  создаётся вручную, токен = `TG_TOKEN` из `/home/vao/u-barn/.env`.
- Токен/чат общие с навыком `heating-telegram` — при смене бота обнови оба.
- `state.json` сбрасывай вручную (удали файл), если хочешь принудительно
  перевести охрану в состояние «вооружено».
- Данные берутся из JSON-эндпоинтов графика (`/getdevs`, `/getdots`),
  а не чтением картинки.
- `kotel-guard.ps1` (legacy, Windows): **UTF-8 с BOM** (иначе PowerShell 5.1
  ломает кириллицу). Python-версия BOM не требует; state.json пишется без BOM
  (чтение устойчиво к обоим).

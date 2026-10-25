---
name: Утренняя сводка (Ужукомка)
description: Утренний «план на день» в Telegram — верхние приоритеты «насущного» (nas.html) плюс задания календаря-органайзера (org.html), у которых подошёл срок. Использовать, когда пользователь просит «утренняя сводка», «план на день из насущного и календаря», «что подошло по календарю», «пришли план на день в телеграм» или спрашивает про задачу morning-digest.
---

# Утренняя сводка (morning-digest)

Каждое утро в **7:30** бот «Ужукомка» (@zavisiskeBot) присылает в личку
владельца одно сообщение-план:

1. **📌 Насущное — верхние приоритеты** — до 5 дел из `dev.nasushchnoe`
   (`/nas.html`): сначала с большим `prio`, потом те, что можно брать
   (`blocked_by = 0`), с локацией и пометкой ⛔ «ждёт #…».
2. **📅 Календарь — подошло сегодня** — задачи из `dev.organizer`
   (`/org.html`), у которых по колонке `cron` сегодня срок и не стоит
   `complete_this_period`.
3. **❓ Не понял расписание** — задачи, где `cron` — свободный текст, который
   скрипт не разобрал (например «С началом отоплением.»). Это подсказка
   поправить запись в органайзере, а не молча пропустить.

Это **не** `plan.txt` (навык `plan-day`) и **не** сезонный календарь
`cowgirl-calendar` — сводка только читает насущное и органайзер.

## Как считается «подошло сегодня»

| `cron` в органайзере | Когда показываем |
| --- | --- |
| `0 7 1-5 * *` (5 полей, цифры) | совпали день месяца + месяц + день недели; **время игнорируется** (сводка и так утренняя) |
| `Ноябрь 5` | ровно 5 ноября |
| `Октябрь, ноябрь.` | весь октябрь и ноябрь |
| `весной`, `летом`, `осенью`, `зимой` | весь сезон |
| `С началом отоплением.` | не угадываем → строка «не понял расписание» |

`complete_this_period = ✅` скрывает задачу из сводки до следующего периода —
это ручной флажок на `/org.html`.

## Файлы

| файл | назначение |
| --- | --- |
| `scripts/morning-digest.py` | сам скрипт (Python 3, только стандартная библиотека) |
| `config.json` | необязательные настройки: `chat_id`, `api`, `top_n`, `show_unknown`, `env_file` (в git не входит) |
| `config.example.json` | шаблон настроек |
| `morning-digest.log` | журнал прогонов (в git не входит) |
| `cron.log` | stdout задачи из cron (в git не входит) |

Секретов в репозитории нет: токен бота берётся из `/home/vao/u-barn/.env`
(`TG_PROD_TOKEN`/`TG_TOKEN`), данные — через `/sql` endpoint u-barn
(`organizer.list.sql`, `dev.nasushchnoe.list.sql` из `SQL_ALLOWLIST`).

## Ручной запуск (прод, SSH `ubarn171`)

```bash
cd /home/vao/u-girlfriend
python3 skills/morning-digest/scripts/morning-digest.py --dry-run   # текст без отправки
python3 skills/morning-digest/scripts/morning-digest.py             # отправить сейчас
python3 skills/morning-digest/scripts/morning-digest.py --date 2026-11-05  # проверить разбор календаря
python3 skills/morning-digest/scripts/morning-digest.py --test      # проверить только канал
```

В дев-среде (Windows) то же самое: `python skills\morning-digest\scripts\morning-digest.py --dry-run`.

## Cron (прод)

```
30 7 * * * /usr/bin/python3 /home/vao/u-girlfriend/skills/morning-digest/scripts/morning-digest.py >> /home/vao/u-girlfriend/skills/morning-digest/cron.log 2>&1
```

Время — локальное для сервера (EET/EEST, Europe/Vilnius).

## Настройки (`config.json`, необязательно)

```json
{
  "chat_id": 5002583838,
  "api": "http://192.168.88.171:90",
  "top_n": 5,
  "show_unknown": true,
  "env_file": "/home/vao/u-barn/.env"
}
```

- `chat_id` — личка `5002583838`; семейная группа — `-5453305680`.
- `top_n` — сколько приоритетов насущного показывать.
- `show_unknown` — показывать блок «не понял расписание».

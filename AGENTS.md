# Память ассистента «Подружка» (глобальная)

Памятка агента. Грузится в **каждую** сессию на этой машине (подключена через
`~/.config/opencode/opencode.json`, см. README). Держи файл коротким:
чуть больше памяти — не больше пользы. Детали — в дневниках и знаниях ниже.

## Карта репозиториев (D:\_d)

| Папка | Что это |
| --- | --- |
| `u-barn/` | бывший `voltage`: веб-сервер мониторинга: Node.js, `web.server.js`, `crons.js`, `ns.bot.js`; dev `http://localhost:90`, прод `http://192.168.88.171:90`; PostgreSQL `192.168.88.171:5432` (база `d`, схемы `ar`/`dev`/`public`) |
| `u-girlfriend/` | эта память (бывший `girlfriend`): навыки (skills/), журналы решений (journal/), знания (knowledge/), инструменты (tools/) |
| `u-sluxa4/` | бывший `sluxach`: голосовой ассистент «Слухач» (Vosk, wake-word «подружка», диктовка, озвучка) |
| `bravenew/` | прочее |

## Где что лежит (память между сессиями)

- `u-girlfriend/journal/voltage.md` — дневник решений по u-barn (новые записи сверху)
- `u-girlfriend/knowledge/voltage-db.md` — структура БД (генерится `node tools/dbdoc.js`, руками не править)
- `u-girlfriend/skills/journal/` — скилл «завершение сессии» (фраза «зафиксируй итоги»)
- Навыки голосового ассистента — `u-girlfriend/skills/` (подключены глобальным конфигом)

## Фоновые задачи (с 19.10.2026 — на проде)

Windows = дев-среда, прод (Linux) = всё фоновое. u-girlfriend склонирован
на прод: `/home/vao/u-girlfriend` (деплой `git push` + `ssh ubarn171 "cd /home/vao/u-girlfriend && git pull --ff-only"`).
В `crontab` vao на проде:

| Интервал | Задача |
| --- | --- |
| `*/5` | `alerts/check_alerts.py` — отопление < 40 °C, qoltec < 52.5 В → Telegram |
| `*/30` | `skills/kotel-guard/scripts/kotel-guard.py` — котёл разожжён → Telegram |
| `0 9 * *` | `prices/check_prices.py` — цены роботов-газонокосилок |
| `0 23/6` | `u-barn/zte.5goff.night.py` — ночной off/on ZTE (venv) |

`config.json` kotel-guard и state-файлы — только на проде (в .gitignore).
Windows-задачи (OpenCode-alerts/prices, kotel-guard) удалены; осталась только
демка `OpenCode-demo` (scheduler/). Логи задач — рядом со скриптами + `cron.log`.

## Правила (voltage)

- Деплой: `git push` + `ssh ubarn171 "cd /home/vao/u-barn && git pull --ff-only"` (nodemon рестартит `web.server.js`, который сам поднимает `crons.js`). Изменения только в документации - не деплоить.
- Секреты только в `.env` (не в git); `vals.json`/`vals.js` не трогать.
- Проверять результат чистыми запросами, не «сбросом кэша».
- Кракозябры в PowerShell — кодировка консоли; сами файлы в UTF-8.
- Бот отвечает только чату владельца `5002583838`.
- `ns.bot` молчит на чужой текст (лог на сервере в `nsbot.log`).
- iHost (`192.168.88.104:80`) офлайн: `EHOSTUNREACH` каждую минуту — процесс жив, лог в `crons.err.log` (свёртка при 1 МБ).

## Память между сессиями: правила

- Новое решение/инцидент → запись сверху в журнал (`journal/voltage.md`), формат «Зачем».
- Структура БД изменилась → `node tools/dbdoc.js` (перегенерит `knowledge/voltage-db.md`).
- «Зафиксируй итоги» в конце работы → скилл `journal`.

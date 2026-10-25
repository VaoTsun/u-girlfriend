# girlfriend — «Подружка» (общий конфиг OpenCode)

Общая «начинка» ассистента **«Подружка»**: навыки (skills), конфиг OpenCode,
план дня, обработчики команд (алерты, цены, расписание). Это **не** голосовой
асистент — он живёт отдельно в репозитории [u-sluxa4](https://github.com/VaoTsun/u-sluxa4)
(«Слухач»: Vosk, wake-word «подружка», диктовка, озвучка).

Репозиторий подключается к OpenCode как **источник памяти и навыков** через
запись в глобальном конфиге (`~/.config/opencode/opencode.json` указывает на
этот клон), поэтому одна и та же «Подружка» работает на всех машинах —
клон репозитория + одна запись в конфиге (см. «Установка»).

## Состав

| Каталог/файл | Назначение |
| --- | --- |
| `opencode.json` | конфиг OpenCode для сессий, открытых внутри репозитория |
| `skills/` | навыки: `heating-check`, `heating-telegram`, `journal`, `kotel-guard`, `morning-digest`, `nasushchnoe`, `plan-day`, `solcast`, `weather` |
| `AGENTS.md` | памятка агента (глобальная): карта репозиториев, правила, указатели на память |
| `journal/` | дневники решений по проектам (`journal/voltage.md`) |
| `knowledge/` | знания, сгенерированные из источников (`knowledge/voltage-db.md`) |
| `tools/` | инструменты памяти (`tools/dbdoc.js` — генератор структура БД из PostgreSQL) |
| `plan.txt` | план дня (правится голосом: «подружка, навык план …») |
| `nasushchnoe.txt` | указатель на «насущное» — задачи хранятся в базе (PostgreSQL, `dev.nasushchnoe`) |
| `cowgirl-calendar/` | сезонный календарь работ + утренние напоминания в Telegram |
| `alerts/` | проверка показаний напряжения/датчиков → Telegram |
| `prices/` | мониторинг цен (роботы-газонокосилки и т.п.) |
| `scheduler/` | обёртка над Планировщиком задач Windows |

## Установка на новой машине

```bash
git clone https://github.com/VaoTsun/u-girlfriend.git
```

Подключить память и навыки — одна запись в глобальном конфиге OpenCode
(`~/.config/opencode/opencode.json`), пути указывают на клон:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "instructions": ["<клон>/AGENTS.md"],
  "skills": ["<клон>/skills"]
}
```

На этой машине `<клон>` = `D:/_d/u-girlfriend`. OpenCode подхватывает такие
правки на лету; если не подхватил — `opencode service restart`.

(Старый способ `OPENCODE_CONFIG_DIR` — из V1, в V2 не документирован.)

## Секреты

Токен Telegram-бота и chat_id **не хранятся в git**. В репозитории лежат
шаблоны `skills/*/config.example.json`. На каждой машине один раз скопируй
шаблон в `config.json` и заполни своими значениями:

```powershell
Copy-Item skills\heating-telegram\config.example.json skills\heating-telegram\config.json
Copy-Item skills\kotel-guard\config.example.json      skills\kotel-guard\config.json
# отредактируй: token, chat_id
```

## Навыки (кратко)

- **heating-check** — «подружка, проверь отопление»: значения датчиков с
  `http://192.168.88.171:90/graph.html` (JSON-эндпоинты `/getdevs`, `/getdots`).
- **heating-telegram** — «подружка, отправь отопление в телеграм».
- **kotel-guard** — охрана котла: раз в 30 мин проверяет подъём температуры
  теплоносителя и шлёт в Telegram «🔥 Котёл разожжён — проверь заслонку и насос».
  Задача в Планировщике: `kotel-guard`.
- **plan-day** — план дня: добавить/отметить/показать.
- **morning-digest** — утренняя сводка в 7:30 в Telegram: верхние приоритеты
  «насущного» (`nas.html`) + задания из органайзера (`org.html`), у которых
  подошёл срок.
- **nasushchnoe** — «насущное»: задачи в базе (PostgreSQL, таблица `dev.nasushchnoe`),
  а не в текстовом файле. Веб-страница — `http://192.168.88.171:90/nas.html`.
- **weather** — погода.

## Планировщик задач Windows

`scheduler/schedule.ps1` регистрирует задачи вида `OpenCode-<имя>`
(сейчас: `OpenCode-alerts`, `OpenCode-prices`, `OpenCode-demo`, `kotel-guard`).
Подробности — в `scheduler/README.md`.

## Примечания

- `state.json`, `*.log`, `config.json`, `service.json`, `prices/reports/`,
  `prices/history.csv` в git не попадают (см. `.gitignore`).

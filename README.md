# girlfriend — «Подружка» (общий конфиг OpenCode)

Общая «начинка» ассистента **«Подружка»**: навыки (skills), конфиг OpenCode,
план дня, обработчики команд (алерты, цены, расписание). Это **не** голосовой
асистент — он живёт отдельно в репозитории [sluxa4](https://github.com/VaoTsun/sluxa4)
(«Слухач»: Vosk, wake-word «подружка», диктовка, озвучка).

Репозиторий используется как **конфигурационная директория OpenCode**
(`OPENCODE_CONFIG_DIR`), поэтому одна и та же «Подружка» работает на всех
машинах (Windows/Linux) — клон репозитория + одна переменная окружения.

## Состав

| Каталог/файл | Назначение |
| --- | --- |
| `opencode.json` | глобальный конфиг OpenCode |
| `skills/` | навыки: `heating-check`, `heating-telegram`, `kotel-guard`, `nasushchnoe`, `plan-day`, `weather` |
| `plan.txt` | план дня (правится голосом: «подружка, навык план …») |
| `nasushchnoe.txt` | указатель на «насущное» — задачи хранятся в базе (PostgreSQL, `dev.nasushchnoe`) |
| `cowgirl-calendar/` | сезонный календарь работ + утренние напоминания в Telegram |
| `alerts/` | проверка показаний напряжения/датчиков → Telegram |
| `prices/` | мониторинг цен (роботы-газонокосилки и т.п.) |
| `scheduler/` | обёртка над Планировщиком задач Windows |

## Установка на новой машине

```bash
git clone https://github.com/VaoTsun/girlfriend.git
```

### Windows
```powershell
setx OPENCODE_CONFIG_DIR "D:\_d\girlfriend"
```

### Linux
```bash
echo 'export OPENCODE_CONFIG_DIR=~/girlfriend' >> ~/.bashrc
source ~/.bashrc
```

После смены переменной перезапусти OpenCode (`opencode service restart`).

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

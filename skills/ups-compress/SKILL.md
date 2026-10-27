# ups-compress

Сжимает исторические 10-секундные замеры `dev.upsd`:

- **События**: окна с `ups_status` в `OB`/`DISCHRG`/`ALARM`/`LB` переносятся целиком в `dev.upsd_events`. Сохраняются ключевые параметры за окно: `batt_start/min/end`, `load_max`, `in_min/max`, `out_min/max`, `duration_sec`, `started_at/ended_at`, `host/model`, `type`, `details` (jsonb).
- **Почасовые агрегаты**: для штатного режима `OL`/`OL CHRG` старше `keep_days` строятся почасовые агрегаты в `dev.upsd_hourly`: `batt_min/max/last`, `load_min/max`, `in_min/max`, `out_min/max`, `cnt`, `status_mode` (наиболее частый `ups_status` за час).
- **Безопасность**: свежие данные (`< keep_days`) никогда не трогаются. Окна `OB/DISCHRG/ALARM/LB` всегда переносятся как события, а не агрегируются. Удаление из `dev.upsd` выполняется только после успешной вставки в целевые таблицы.
- **Dry-run**: по умолчанию скрипт только считает кандидатов и показывает план. Реальное применение только с `--apply`.

## Структура
```
ups-compress/
├── SKILL.md
├── config.json.example
├── .gitignore
├── create_tables.sql
└── scripts/
    └── ups_compress.py
```

## Конфиг
```bash
cp config.json.example config.json
```

Параметры:
- `keep_days` — сколько дней оставить в raw (`dev.upsd`) нетронутыми (по умолчанию 14)
- `window_statuses` — статусы, формирующие событие
- `normal_statuses` — статусы для почасовой агрегации
- `env_path_prod` — путь к `.env` на проде (`/home/vao/u-barn/.env`)

Секреты БД берутся из `.env` в формате `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` (как в других скиллах).

## Запуск
```bash
# dry-run (только отчёт)
python3 skills/ups-compress/scripts/ups_compress.py --dry-run

# реальное сжатие
python3 skills/ups-compress/scripts/ups_compress.py --apply
```

## Деплой на прод
```bash
# в u-girlfriend
git add skills/ups-compress
git commit -m "ups-compress: add skill"
git push

# на проде
ssh ubarn171 "cd /home/vao/u-girlfriend && git pull --ff-only"
```

## Крон (рекомендуется)
После успешного `--dry-run` добавить в crontab `vao`:
```cron
0 3 * * 0 cd /home/vao/u-girlfriend && /usr/bin/python3 skills/ups-compress/scripts/ups_compress.py --apply >> /home/vao/u-girlfriend/skills/ups-compress/ups-compress.log 2>&1
```
(воскресенье 03:00)

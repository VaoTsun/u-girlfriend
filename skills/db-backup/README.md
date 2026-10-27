# db-backup

Бэкап схем `r` и `dev` из PostgreSQL.

- Малые таблицы бэкапятся полностью
- `r.vals` бэкапится только за последние 7 дней (по колонке `time`)
- Использует `pg_dump` через Unix-сокет, секреты из `/home/vao/u-barn/.env`
- Формат `custom` (-Fc), хранение в `/home/vao/backups/db/YYYY-MM-DD_HH-MM-SS/`
- Автоочистка старше `keep_days`

## Использование
```bash
cp config.json.example config.json
python3 scripts/backup_schemas.py --dry-run
python3 scripts/backup_schemas.py
```

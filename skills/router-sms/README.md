# SMS роутера ZTE → Telegram

`scripts/router_sms.py` раз в две минуты читает списки **Device SMS** и
**SIM SMS** на `http://192.168.8.3/index.html#sms`. Новое сообщение отправляется
в тот же Telegram-чат, что и production-бот. Отправка использует общий
`tools/tg.py` с очередью на случай временного отсутствия сети.

## Доступ и состояние

- Запускать только на production (`ENVIRONMENT=PROD`).
- Пароль роутера берётся из `/home/vao/u-barn/.env` (`ROUTER_PASSWORD`).
- Telegram-токен — `TG_PROD_TOKEN` (fallback `TG_TOKEN`) из того же `.env`;
  чат — `teleGa.PROD.channel` из `u-barn/vals.json`.
- В `state/router_sms.json` хранятся только SHA-256 отпечатки отправителя,
  времени и текста; содержимое SMS там не сохраняется. Каталог `state/`
  исключён из git.
- Первый успешный запуск сохраняет исходный список как baseline и **не
  отправляет старые SMS**. Последующие запуски уведомляют о новых/изменённых
  сообщениях. Одно сообщение, показанное в обоих списках, дедуплицируется.
- Лог cron: `skills/router-sms/router_sms.log`.

Скрипт использует Playwright из `/home/vao/u-barn/venv` и Telegram helper из
`tools/tg.py`; отдельный браузерный пакет или секреты в конфиге не нужны.

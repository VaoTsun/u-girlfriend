#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scripts/well-guard.py
# well-guard — наблюдатель за колодцем (насосом): проверяет, не слишком ли
# давно колодец не включался и не работает ли он слишком долго.
#
# Устройство «Колодец» (ar.src i=11, колонка power: 'on'/'off'), данные пишет
# iHost в ar.vals. Данные берутся напрямую из БД (psql), т.к. /getdots не
# отдаёт текстовые колонки.
#
# Алерты (в Telegram, один раз на состояние, до его снятия):
#   - колодец не включался >= 6.5 ч  → «не включался уже N ч»
#   - колодец включён и работает >= 30 мин → «работает уже N мин»
#   - данных с датчика нет >= 15 мин (мёртв iHost/шлюз) → «нет данных»
#
# Запуск вручную:
#   python3 well-guard.py            # обычный цикл проверки
#   python3 well-guard.py --dry-run  # показать решение, ничего не слать/менять
#   python3 well-guard.py --force    # отправить тестовое уведомление
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))       # .../skills/well-guard/scripts
SKILL_DIR = os.path.dirname(HERE)                       # .../skills/well-guard
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
STATE_PATH = os.path.join(SKILL_DIR, "state.json")
LOG_PATH = os.path.join(SKILL_DIR, "well-guard.log")


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            log("Предупреждение: state.json повреждён, использую значения по умолчанию.")
    return {"alerted": None, "last_ts": "", "last_notified": ""}


def save_state(state, dry_run):
    if dry_run:
        return
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("Предупреждение: не удалось сохранить state.json: %s" % e)


def load_env(env_path):
    """Мини-парсер .env (секреты живут в /home/vao/u-barn/.env, не здесь)."""
    env = {}
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except OSError as e:
        log("Ошибка: не удалось прочитать %s : %s" % (env_path, e))
    return env


def psql(cfg, query, env_file_secrets):
    """Выполнить SQL через psql (psycopg2 на проде нет, psql — есть)."""
    proc = subprocess.run(
        ["/usr/bin/psql", "-h", cfg["db_host"], "-U", cfg["db_user"],
         "-d", cfg["db_name"], "-t", "-A", "-F", "|", "-v", "ON_ERROR_STOP=1",
         "-c", query],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "PGPASSWORD": env_file_secrets.get("DB_PASSWORD", "")},
    )
    if proc.returncode != 0:
        raise RuntimeError("psql: %s" % (proc.stderr.strip() or "exit %d" % proc.returncode))
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def send_tg(token, chat_id, text):
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % token,
        data=urllib.parse.urlencode({
            "chat_id": chat_id, "parse_mode": "HTML",
            "disable_web_page_preview": "true", "text": text}).encode(),
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.load(r)
    if not resp.get("ok"):
        raise RuntimeError(resp.get("description"))


def fmt_when(dt):
    return dt.strftime("%d.%m %H:%M")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="показать решение, ничего не слать/менять")
    ap.add_argument("--force", action="store_true",
                    help="отправить тестовое уведомление немедленно")
    ap.add_argument("--config", default=CONFIG_PATH)
    args = ap.parse_args()

    # --- конфиг ---
    if not os.path.exists(args.config):
        log("Ошибка: не найден конфиг %s" % args.config)
        return 2
    try:
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        log("Ошибка: не удалось прочитать конфиг %s : %s" % (args.config, e))
        return 2

    chat_id = str(cfg.get("chat_id") or "")
    src = int(cfg.get("src") or 11)
    device_name = cfg.get("device_name") or "Колодец"
    stale_min = float(cfg.get("stale_minutes") or 15)
    off_hours_thr = float(cfg.get("off_alert_hours") or 6.5)
    on_min_thr = float(cfg.get("on_alert_minutes") or 30)
    env_file = cfg.get("env_file") or "/home/vao/u-barn/.env"
    cfg.setdefault("db_host", "192.168.88.171")
    cfg.setdefault("db_user", "app")
    cfg.setdefault("db_name", "d")

    secrets = load_env(env_file)
    token = secrets.get("TG_PROD_TOKEN") or secrets.get("TG_TOKEN") or ""
    if not token:
        log("Ошибка: нет токена бота в %s (TG_PROD_TOKEN/TG_TOKEN)." % env_file)
        return 2
    if not chat_id:
        log("Ошибка: не задан chat_id (config.json → chat_id).")
        return 2

    if args.force:
        try:
            send_tg(token, chat_id, "💧 <b>Колодец</b>: тестовое уведомление well-guard — канал связи работает.")
            log("Тестовое уведомление отправлено.")
            return 0
        except Exception as e:
            log("Ошибка отправки в Telegram: %s" % e)
            return 5

    state = load_state()

    # --- данные из БД ---
    try:
        now_row = psql(cfg, "select now()", secrets)
        db_now = datetime.fromisoformat(now_row[0].strip())
        fresh_row = psql(cfg, "select max(ts) from ar.vals where src = %d" % src, secrets)
        last_ts_raw = (fresh_row[0].strip() if fresh_row else "") or ""
    except Exception as e:
        log("Ошибка: БД недоступна: %s" % e)
        return 3

    # --- датчик мёртв? (строки в ar.vals идут каждые ~2-3 мин) ---
    if not last_ts_raw:
        log("Ошибка: для src=%d нет ни одной строки в ar.vals." % src)
        return 3
    last_data = datetime.fromisoformat(last_ts_raw)
    age_min = (db_now - last_data).total_seconds() / 60.0
    if age_min >= stale_min:
        if state.get("alerted") != "stale":
            msg = ("⚠️ <b>%s</b>: нет данных с датчика (последняя точка %s, %.0f мин назад) —\n"
                   "проверь шлюз/iHost: проверка колодца слепа."
                   % (device_name, fmt_when(last_data.astimezone()), age_min))
            if args.dry_run:
                print("DRYRUN: уведомление НЕ отправлено и состояние НЕ изменено.\n" + msg)
                return 0
            try:
                send_tg(token, chat_id, msg)
            except Exception as e:
                log("Ошибка отправки в Telegram: %s" % e)
                return 5
            state["alerted"] = "stale"
            state["last_notified"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save_state(state, args.dry_run)
            log("Отправлено: нет данных с датчика (возраст %.0f мин)." % age_min)
        else:
            log("Данных с датчика нет (возраст %.0f мин) — уже уведомлял, жду." % age_min)
        return 0

    # данные живы — снимаю метку «датчик мёртв», если она стояла
    if state.get("alerted") == "stale":
        state["alerted"] = None
        log("Данные с датчика снова идут — снимаю пометку «нет данных».")

    # --- история за сутки (достаточно, чтобы найти последний запуск) ---
    try:
        rows = psql(cfg,
                    "select ts::text, power from ar.vals "
                    "where src = %d and ts > now() - make_interval(hours => 24) "
                    "order by ts" % src, secrets)
    except Exception as e:
        log("Ошибка: БД недоступна: %s" % e)
        return 3
    if not rows:
        log("Ошибка: нет строк за сутки при живом max(ts) — странно, пропускаю.")
        return 3

    points = []
    for ln in rows:
        ts_s, _, power = ln.partition("|")
        points.append((datetime.fromisoformat(ts_s.strip()), (power or "").strip().lower()))
    current = points[-1][1]          # 'on' / 'off'

    # последний момент включения (переход off→on); None = включён/выключен давно (> суток)
    last_on_start = None
    prev = None
    for ts, p in points:
        if p == "on" and prev != "on":
            last_on_start = ts
        prev = p

    now = db_now.astimezone()
    if current == "on":
        started = last_on_start.astimezone() if last_on_start else None
        run_min = (now - started).total_seconds() / 60.0 if started else 24 * 60.0
        started_label = fmt_when(started) if started else "больше суток назад"
        if run_min >= on_min_thr:
            if state.get("alerted") != "on":
                msg = ("💧 <b>%s</b>: насос работает уже %.0f мин (включился в %s) —\n"
                       "проверь, не качает ли он вхолостую."
                       % (device_name, run_min, started_label))
                if args.dry_run:
                    print("DRYRUN: уведомление НЕ отправлено и состояние НЕ изменено.\n" + msg)
                    return 0
                try:
                    send_tg(token, chat_id, msg)
                except Exception as e:
                    log("Ошибка отправки в Telegram: %s" % e)
                    return 5
                state["alerted"] = "on"
                state["last_notified"] = time.strftime("%Y-%m-%d %H:%M:%S")
                save_state(state, args.dry_run)
                log("Отправлено: работает уже %.0f мин (с %s)." % (run_min, started_label))
            else:
                log("Работает %.0f мин (с %s) — уже уведомлял, жду." % (run_min, started_label))
        else:
            if state.get("alerted") == "on":
                state["alerted"] = None
            log("Включён %.0f мин (с %s) — норма." % (run_min, started_label))
    else:  # off
        started = last_on_start.astimezone() if last_on_start else None
        off_h = (now - started).total_seconds() / 3600.0 if started else 24.0
        started_label = fmt_when(started) if started else "больше суток назад"
        if off_h >= off_hours_thr:
            if state.get("alerted") != "off":
                msg = ("💧 <b>%s</b>: не включался уже %.1f ч (последний запуск %s) —\n"
                       "проверь, есть ли вода/питание насоса."
                       % (device_name, off_h, started_label))
                if args.dry_run:
                    print("DRYRUN: уведомление НЕ отправлено и состояние НЕ изменено.\n" + msg)
                    return 0
                try:
                    send_tg(token, chat_id, msg)
                except Exception as e:
                    log("Ошибка отправки в Telegram: %s" % e)
                    return 5
                state["alerted"] = "off"
                state["last_notified"] = time.strftime("%Y-%m-%d %H:%M:%S")
                save_state(state, args.dry_run)
                log("Отправлено: не включался %.1f ч (последний запуск %s)." % (off_h, started_label))
            else:
                log("Не включался %.1f ч (последний запуск %s) — уже уведомлял, жду." % (off_h, started_label))
        else:
            if state.get("alerted") == "off":
                state["alerted"] = None
            log("Выключен %.1f ч (последний запуск %s) — норма." % (off_h, started_label))

    state["last_ts"] = last_ts_raw
    save_state(state, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())

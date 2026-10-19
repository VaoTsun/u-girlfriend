#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scripts/kotel-guard.py
# kotel-guard — фоновый наблюдатель за отоплением (порт kotel-guard.ps1 на Python,
# запускается в cron на проде; ps1 оставлен для Windows).
# Каждые N минут сверяет текущую температуру теплоносителя с минимумом за окно.
# Если подъём >= порога (котёл разожжён) — шлёт уведомление в Telegram:
# проверить заслонку и насос. Одно уведомление на одну топку: повторно шлёт
# только после остывания (перевзвод).
#
# Запуск вручную:
#   python3 kotel-guard.py            # обычный цикл проверки
#   python3 kotel-guard.py --dry-run  # показать решение, ничего не слать/менять
#   python3 kotel-guard.py --force    # отправить уведомление немедленно
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))       # .../skills/kotel-guard/scripts
SKILL_DIR = os.path.dirname(HERE)                       # .../skills/kotel-guard
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
STATE_PATH = os.path.join(SKILL_DIR, "state.json")
LOG_PATH = os.path.join(SKILL_DIR, "kotel-guard.log")


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


def http_json(url, data=None, timeout=20):
    req = urllib.request.Request(url, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            # utf-8-sig: PS1-версия писала файл с BOM
            with open(STATE_PATH, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            log("Предупреждение: state.json повреждён, использую значения по умолчанию.")
    return {"armed": True, "last_ts": "", "last_notified": "", "last_delta": 0}


def save_state(state, dry_run):
    if dry_run:
        return
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("Предупреждение: не удалось сохранить state.json: %s" % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="показать решение, ничего не слать/менять")
    ap.add_argument("--force", action="store_true",
                    help="отправить уведомление немедленно, игнорируя порог и состояние")
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

    server = cfg.get("server") or "192.168.88.171:90"
    token = cfg.get("token") or ""
    chat_id = cfg.get("chat_id") or ""
    device = cfg.get("device") or "Отопление"
    column = cfg.get("column") or "cels"
    threshold = float(cfg.get("threshold_c") or 20)
    window = int(cfg.get("window_minutes") or 180)
    rearm_ratio = float(cfg.get("rearm_ratio") or 0.5)
    unit = "°C"

    if not token:
        log("Ошибка: не задан токен бота (config.json → token).")
        return 2
    if not chat_id:
        log("Ошибка: не задан chat_id (config.json → chat_id).")
        return 2

    state = load_state()
    base = "http://%s" % server

    # --- данные мониторинга (те же эндпоинты, что у graph.html) ---
    try:
        devs = http_json(base + "/getdevs")
    except Exception as e:
        log("Ошибка: нет связи с %s/getdevs : %s" % (base, e))
        return 3
    dev = None
    for d in devs:
        if device in (d.get("sname") or ""):
            dev = d
            break
    if not dev:
        log("Ошибка: устройство '%s' не найдено в /getdevs." % device)
        return 3
    if not column:
        column = dev.get("defcol") or "cels"

    # число точек по глубине окна (та же логика, что в ps1/heating)
    points = 30
    for bmin, bpts in ((30, 30), (60, 60), (240, 120), (360, 240), (1440, 600)):
        if window >= bmin:
            points = bpts
        else:
            break
    qs = urllib.parse.urlencode({"gr": dev["i"], "col": column,
                                 "back": window, "gsCoef": points})
    url = "%s/getdots?%s" % (base, qs)
    try:
        dots = http_json(url)
    except Exception as e:
        log("Ошибка: нет данных с %s : %s" % (url, e))
        return 3
    if not dots:
        log("Нет точек за %d мин (%s) — пропускаю." % (window, url))
        return 3

    parsed = sorted(
        ({"ts_str": str(d["ts"]), "ts": datetime.fromisoformat(str(d["ts"])),
          "val": float(d["val"])} for d in dots),
        key=lambda x: x["ts"])
    last = parsed[-1]
    current = last["val"]
    minimum = min(x["val"] for x in parsed)
    delta = round(current - minimum, 1)
    rearm_level = threshold * rearm_ratio

    # --- данные не обновились? (ts не сдвинулся с прошлой проверки) ---
    if not args.force and state.get("last_ts") and state["last_ts"] == last["ts_str"]:
        log("Новых данных нет (последняя точка %s%s не изменилась) — пропускаю."
            % (current, unit))
        return 4

    # --- решение ---
    if args.force or (state.get("armed") and delta >= threshold):
        decision = "fire"
    elif not state.get("armed") and delta <= rearm_level:
        decision = "rearm"
    else:
        decision = "none"

    log("Проверка: %s (%s%s), мин за %d мин = %s%s, подъём = %s%s, состояние = %s, решение = %s"
        % (device, current, unit, window, minimum, unit, delta, unit,
           "вооружено" if state.get("armed") else "уже уведомлено", decision))

    if decision == "rearm":
        state["armed"] = True
        save_state(state, args.dry_run)
        return 0
    if decision != "fire":
        state["last_ts"] = last["ts_str"]
        state["last_delta"] = delta
        save_state(state, args.dry_run)
        return 0

    # --- уведомление ---
    stamp = time.strftime("%d.%m.%Y %H:%M")
    fire_word = "🔥 Котёл разожжён (тестовое)" if args.force else "🔥 Котёл разожжён"
    msg = ("<b>%s</b> (%s)\n<b>%s:</b> %s → %s %s (+%s %s за %d мин)\n"
           "Проверь, закрыта ли заслонка, и включился ли насос!"
           % (fire_word, stamp, device, minimum, current, unit, delta, unit, window))

    if args.dry_run:
        print("DRYRUN: уведомление НЕ отправлено и состояние НЕ изменено.")
        print(msg)
        return 0

    # --- отправка в Telegram ---
    try:
        resp = http_json(
            "https://api.telegram.org/bot%s/sendMessage" % token,
            data=urllib.parse.urlencode({
                "chat_id": chat_id, "parse_mode": "HTML",
                "disable_web_page_preview": "true", "text": msg}).encode(),
            timeout=30)
    except Exception as e:
        # не считаем топку отслеженной: при ошибке сети уведомление уйдёт в следующий цикл
        log("Ошибка отправки в Telegram: %s" % e)
        return 5
    if not resp.get("ok"):
        log("Ошибка отправки в Telegram: %s" % resp.get("description"))
        return 5

    state["armed"] = False
    state["last_ts"] = last["ts_str"]
    state["last_notified"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["last_delta"] = delta
    save_state(state, args.dry_run)
    log("Отправлено в Telegram: подъём +%s%s (%s → %s%s)." % (delta, unit, minimum, current, unit))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""morning-digest.py — утренний «план на день» в Telegram («Ужукомка»).

Склеивает две таблицы u-barn в одно сообщение:
  • /nas.html (dev.nasushchnoe) — верхние приоритеты «насущного»;
  • /org.html (dev.organizer)   — задания, у которых СЕГОДНЯ подошёл срок.

Данные берём через тот же /sql endpoint, что и сами страницы (SQL-файлы из
SQL_ALLOWLIST в web.server.js): не нужен psql и одинаково работает на проде
(Linux) и в дев-среде (Windows).

Запуск:
  python3 morning-digest.py                    # обычный прогон (cron 7:30)
  python3 morning-digest.py --dry-run          # показать сообщение, не слать
  python3 morning-digest.py --date 2026-11-05  # проверить разбор календаря
  python3 morning-digest.py --test             # только проверить канал

Правила «подошло сегодня» для колонки cron в органайзере:
  • настоящий cron (5 полей, цифры) — совпали день месяца + месяц + день
    недели; время (минуты/часы) игнорируется, сводка и так утренняя;
  • «Октябрь, ноябрь.» / «весной» / «осенью» — текущий месяц/сезон;
  • «Ноябрь 5» — конкретный день (5 ноября);
  • «С началом отопления.» — проверяем ночную температуру теплоносителя
    («Отопление», gr=16, cels) за 7 дней: отопление считается начавшимся, если
    не меньше N ночей подряд/за окно, когда ночью было > 50 °C >= 3 точек за ночь.
  • всё остальное — не угадываем, показываем отдельной строкой
    «не понял расписание», чтобы поправить в органайзере.
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))        # .../skills/morning-digest/scripts
SKILL_DIR = os.path.dirname(HERE)                        # .../skills/morning-digest
REPO_DIR = os.path.dirname(os.path.dirname(SKILL_DIR))   # .../u-girlfriend
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(SKILL_DIR, "morning-digest.log")

DEFAULTS = {
    "api": "http://192.168.88.171:90",
    "chat_id": 5002583838,          # личка владельца; группа — -5453305680
    "top_n": 5,
    "show_unknown": True,
    "timeout": 30,
    # секреты (токен бота, пароль БД) — в u-barn/.env, здесь их нет
    "env_file": "",
    # отопительный сезон: ночная температура теплоносителя («Отопление», gr=16)
    "heating_gr": 16,
    "heating_col": "cels",
    "heating_threshold_c": 50,
    "heating_min_points": 3,
    "heating_need_nights": 3,
    "heating_window_days": 7,
    "heating_night_hours": [22, 23, 0, 1, 2, 3, 4, 5, 6],
}

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

# «насущное» и «органайзер» — те же SQL-файлы, что отдают страницы
SQL_NAS = "dev.nasushchnoe.list.sql"
SQL_ORG = "organizer.list.sql"


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


# ---------------------------------------------------------------- конфиг/секреты

def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8-sig") as f:
                cfg.update(json.load(f))
        except Exception as e:
            log("Предупреждение: не прочитал %s (%s) — беру умолчания." % (path, e))
    if not cfg.get("env_file"):
        candidates = [
            os.path.abspath(os.path.join(REPO_DIR, "..", "u-barn", ".env")),
            "/home/vao/u-barn/.env",
        ]
        for c in candidates:
            if os.path.exists(c):
                cfg["env_file"] = c
                break
    return cfg


def load_env(path):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except OSError as e:
        log("Предупреждение: не прочитал %s (%s)" % (path, e))
    return env


# ---------------------------------------------------------------- данные u-barn

def fetch_url(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "morning-digest/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_any(api, path_query, timeout):
    """GET к u-barn с фолбэком на локальный dev и 3 попытками."""
    bases = [api]
    if "192.168.88.171" in api:
        bases.append("http://127.0.0.1:90")
    last = None
    for base in bases:
        for attempt in range(1, 4):
            try:
                return fetch_url(base.rstrip("/") + path_query, timeout)
            except Exception as e:
                last = e
                log("Не получил %s с %s (попытка %d): %s" % (path_query, base, attempt, e))
                if attempt < 3:
                    time.sleep(10)
    raise last


def fetch_rows(api, sql_name, timeout):
    data = fetch_any(api, "/sql?" + urllib.parse.urlencode({"sql": sql_name}), timeout)
    if not isinstance(data, list):
        raise RuntimeError("неожиданный ответ /sql: %r" % (data,))
    return data


# ---------------------------------------------------------------- разбор cron

def expand_field(spec, lo, hi):
    """'1-5', '*/2', '1,3,7' -> множество чисел. ValueError — не cron."""
    out = set()
    for part in str(spec).split(","):
        if not part:
            raise ValueError("пустое поле")
        step = 1
        if "/" in part:
            part, st = part.split("/", 1)
            step = int(st)
            if step <= 0:
                raise ValueError("шаг <= 0")
        if part in ("*", "?"):
            a, b = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
        else:
            a = b = int(part)
        if a > b:
            raise ValueError("диапазон наоборот")
        out.update(range(a, b + 1, step))
    return out


def cron_due(expr, d):
    """True/False — совпал ли день; None — это не cron."""
    parts = str(expr or "").split()
    if len(parts) < 5:
        return None
    f = parts[:5]
    if not all(re.fullmatch(r"[\d*/,\-?]+", p) for p in f):
        return None
    try:
        minutes = expand_field(f[0], 0, 59)
        hours = expand_field(f[1], 0, 23)
        dom = expand_field(f[2], 1, 31)
        mon = expand_field(f[3], 1, 12)
        dow = expand_field(f[4], 0, 7)
    except ValueError:
        return None
    if not minutes or not hours or not dom or not mon or not dow:
        return None
    dow = {x % 7 for x in dow}             # 7 = воскресенье = 0
    dom_ok = d.day in dom
    mon_ok = d.month in mon
    dow_ok = (d.isoweekday() % 7) in dow
    if f[2] not in ("*", "?") and f[4] not in ("*", "?"):
        return mon_ok and (dom_ok or dow_ok)
    return mon_ok and dom_ok and dow_ok


MONTHS = [
    ("январ", 1), ("феврал", 2), ("март", 3), ("апрел", 4), ("ма[йя]", 5),
    ("июн", 6), ("июл", 7), ("август", 8), ("сентябр", 9), ("октябр", 10),
    ("ноябр", 11), ("декабр", 12),
]
SEASONS = [
    ("зим", {12, 1, 2}),
    ("весн", {3, 4, 5}),
    ("лет", {6, 7, 8}),
    ("осен", {9, 10, 11}),
]


def text_due(text, d):
    """Русское расписание («октябрь», «весной», «ноябрь 5») -> True/False/None."""
    t = str(text or "").lower().replace("ё", "е")
    if not t.strip():
        return None
    months = {num for stem, num in MONTHS if re.search(r"\b" + stem, t)}
    seasons = set()
    for stem, mset in SEASONS:
        if re.search(r"\b" + stem, t):
            seasons |= mset
    if months:
        if d.month not in months:
            return False
        days = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", t)
                if 1 <= int(x) <= 31]
        return (d.day in days) if days else True
    if seasons:
        return d.month in seasons
    return None


HEATING_RE = re.compile(r"отоплен")


def is_heating_schedule(expr):
    """«С началом отопления.» — решаем по ночной температуре теплоносителя."""
    return bool(HEATING_RE.search(str(expr or "").lower().replace("ё", "е")))


def night_heating(cfg):
    """Начался ли отопительный сезон по ночному теплоносителю («Отопление», gr=16).

    Учитываем не одну ночь, а heating_need_nights за heating_window_days,
    когда ночных точек > heating_threshold_c >= heating_min_points.
    """
    gr = as_int(cfg.get("heating_gr"), 16)
    col = str(cfg.get("heating_col") or "cels")
    try:
        threshold = float(cfg.get("heating_threshold_c") or 50)
    except (TypeError, ValueError):
        threshold = 50.0
    hours = cfg.get("heating_night_hours") or [22, 23, 0, 1, 2, 3, 4, 5, 6]
    night = {as_int(h, -1) for h in hours}
    min_points = max(1, as_int(cfg.get("heating_min_points"), 3))
    need_nights = max(1, as_int(cfg.get("heating_need_nights"), 3))
    window_days = max(need_nights, as_int(cfg.get("heating_window_days"), 7))

    info = {"state": None, "max": None, "hot_nights": 0, "nights": 0,
            "threshold": threshold, "need_nights": need_nights,
            "window_days": window_days, "reason": ""}

    qs = urllib.parse.urlencode({"gr": gr, "col": col, "back": window_days * 24 * 60,
                                 "gsCoef": 240})
    try:
        rows = fetch_any(cfg["api"], "/getdots?" + qs, cfg.get("timeout", 30))
    except Exception as e:
        info["reason"] = "нет данных отопления (%s)" % e
        log("Отопление: %s" % info["reason"])
        return info

    by_day = {}
    for r in rows if isinstance(rows, list) else []:
        ts = str(r.get("ts") or "")
        m = re.search(r"(\d{4}-\d{2}-\d{2})T(\d{2}):", ts)
        if not m:
            continue
        day_key, h = m.group(1), int(m.group(2))
        if h not in night:
            continue
        try:
            v = float(r.get("val"))
        except (TypeError, ValueError):
            continue
        slot = by_day.setdefault(day_key, {"hot": 0, "max": -10 ** 18})
        if v > threshold:
            slot["hot"] += 1
        if v > slot["max"]:
            slot["max"] = v

    hot_nights = []
    for day_key in sorted(by_day.keys()):
        slot = by_day[day_key]
        info["nights"] += 1
        if slot["hot"] >= min_points and slot["max"] > threshold:
            hot_nights.append((day_key, slot["max"]))

    info["hot_nights"] = len(hot_nights)
    if hot_nights:
        info["max"] = max(x[1] for x in hot_nights)

    if info["hot_nights"] < need_nights:
        if info["nights"] == 0:
            info["reason"] = "ночных замеров теплоносителя за %d дн. нет" % window_days
        else:
            info["reason"] = ("отопительный сезон не подтверждён: тёплых ночей %d из %d за %d дн. "
                              "(нужно >= %d, >%g °C — >= %d точек)"
                              % (info["hot_nights"], info["nights"], window_days,
                                 need_nights, threshold, min_points))
        log("Отопление ночами: %s" % info["reason"])
        return info

    info["state"] = True
    log("Отопление ночами: %d тёплых ночей из %d за %d дн., макс %.1f °C -> сезон начался"
        % (info["hot_nights"], info["nights"], window_days, info["max"]))
    return info


def schedule_due(expr, d, heating=None):
    if is_heating_schedule(expr):
        return (heating or {}).get("state")
    due = cron_due(expr, d)
    if due is not None:
        return due
    return text_due(expr, d)


# ---------------------------------------------------------------- сообщение

def esc(s):
    return html.escape(str(s if s is not None else ""))


def short(s, limit=170):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= limit else s[:limit - 1] + "…"


def as_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def int_list(v):
    if not isinstance(v, (list, tuple)):
        return []
    return [as_int(x) for x in v]


def fmt_c(v):
    try:
        return ("%.1f" % float(v)).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "?"


def build_message(nas_rows, org_rows, d, cfg, heating=None):
    top_n = max(1, as_int(cfg.get("top_n"), 5))
    done_map = {as_int(r.get("i")): bool(r.get("done")) for r in nas_rows}

    free = [r for r in nas_rows if not r.get("done")]
    free.sort(key=lambda r: (
        -as_int(r.get("prio")),
        1 if as_int(r.get("blocked_by")) > 0 else 0,
        0 if r.get("location") else 1,
        str(r.get("location") or ""),
        as_int(r.get("i")),
    ))
    top = free[:top_n]

    need_heating = any(not r.get("complete_this_period") and is_heating_schedule(r.get("cron"))
                       for r in org_rows)
    if heating is None and need_heating:
        heating = night_heating(cfg)

    due, pending, unknown = [], [], []
    for r in org_rows:
        if r.get("complete_this_period"):
            continue
        if is_heating_schedule(r.get("cron")):
            state = (heating or {}).get("state")
            if state is True:
                due.append((r, heating))
            elif state is None:
                pending.append((r, heating))
            continue
        state = schedule_due(r.get("cron"), d)
        if state is True:
            due.append((r, None))
        elif state is None:
            unknown.append(r)

    lines = ["☀️ <b>План на день</b> — %s, %s" %
             (d.strftime("%d.%m.%Y"), WEEKDAYS[d.weekday()])]

    lines.append("")
    lines.append("📌 <b>Насущное — верхние приоритеты</b>")
    if not top:
        lines.append("— пусто 🎉")
    for n, r in enumerate(top, 1):
        blocked = as_int(r.get("blocked_by")) > 0
        waiting = [i for i in int_list(r.get("deps")) if not done_map.get(i)]
        tail = ""
        if r.get("location"):
            tail += " · " + esc(short(r.get("location"), 40))
        if waiting:
            tail += " (ждёт " + ", ".join("#%d" % i for i in waiting) + ")"
        lines.append("%d. %s%s%s" % (n, "⛔ " if blocked else "",
                                     esc(short(r.get("title"), 120)), tail))
    if len(free) > len(top):
        lines.append("<i>…и ещё %d в насущном</i>" % (len(free) - len(top)))

    lines.append("")
    lines.append("📅 <b>Календарь — подошло сегодня</b>")
    if not due:
        lines.append("— по расписанию на сегодня ничего")
    for r, h in due:
        line = "• <b>%s</b> <i>(%s)</i>" % (
            esc(short(r.get("title"), 140)), esc(short(r.get("cron"), 60)))
        if h and h.get("max") is not None:
            line += " — макс %s °C" % fmt_c(h["max"])
        lines.append(line)
        if r.get("notes"):
            lines.append("   ↳ " + esc(short(r.get("notes"), 170)))

    if pending:
        lines.append("")
        lines.append("⚠️ <i>Не смог проверить отопительный сезон:</i>")
        for r, h in pending:
            reason = (h or {}).get("reason") or "нет данных отопления"
            lines.append("• %s — %s" % (esc(short(r.get("title"), 100)), esc(reason)))

    if unknown and cfg.get("show_unknown", True):
        lines.append("")
        lines.append("❓ <i>Не понял расписание — поправь в органайзере:</i>")
        for r in unknown:
            lines.append("• %s — «%s»" %
                         (esc(short(r.get("title"), 100)), esc(short(r.get("cron"), 60))))

    return "\n".join(lines)


# ---------------------------------------------------------------- Telegram

def send_tg(token, chat_id, text):
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % token,
        data=urllib.parse.urlencode({
            "chat_id": chat_id,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
            "text": text,
        }).encode(),
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.load(r)
    if not resp.get("ok"):
        raise RuntimeError(resp.get("description") or "Telegram: not ok")
    return resp


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Утренняя сводка: насущное + календарь")
    ap.add_argument("--dry-run", action="store_true", help="показать, не отправлять")
    ap.add_argument("--test", action="store_true", help="только проверить канал")
    ap.add_argument("--date", default="", help="дата для проверки разбора (ГГГГ-ММ-ДД)")
    ap.add_argument("--config", default=CONFIG_PATH)
    args = ap.parse_args()

    cfg = load_config(args.config)
    secrets = load_env(cfg.get("env_file") or "")
    token = secrets.get("TG_PROD_TOKEN") or secrets.get("TG_TOKEN") or ""
    chat_id = str(cfg.get("chat_id") or "")
    if not token:
        log("Ошибка: нет токена бота в %s (TG_PROD_TOKEN/TG_TOKEN)." % cfg.get("env_file"))
        return 2
    if not chat_id:
        log("Ошибка: не задан chat_id (config.json → chat_id).")
        return 2

    if args.test:
        try:
            send_tg(token, chat_id, "☀️ Утренняя сводка на связи — в 7:30 пришлю план на день.")
        except Exception as e:
            log("Ошибка отправки в Telegram: %s" % e)
            return 5
        log("Тестовое сообщение отправлено.")
        return 0

    try:
        day = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    except ValueError:
        log("Ошибка: --date ждёт ГГГГ-ММ-ДД, а не %r" % args.date)
        return 2

    try:
        nas_rows = fetch_rows(cfg["api"], SQL_NAS, cfg.get("timeout", 20))
        org_rows = fetch_rows(cfg["api"], SQL_ORG, cfg.get("timeout", 20))
    except Exception as e:
        log("Ошибка: данные не получены: %s" % e)
        return 3

    need_heating = any(not r.get("complete_this_period") and is_heating_schedule(r.get("cron"))
                       for r in org_rows)
    heating = night_heating(cfg) if need_heating else None

    text = build_message(nas_rows, org_rows, day, cfg, heating=heating)

    if args.dry_run:
        print("DRYRUN: сообщение НЕ отправлено.")
        print(text)
        return 0

    try:
        send_tg(token, chat_id, text)
    except Exception as e:
        log("Ошибка отправки в Telegram: %s" % e)
        return 5

    free_n = len([r for r in nas_rows if not r.get("done")])
    due_n = len([r for r in org_rows
                 if not r.get("complete_this_period")
                 and schedule_due(r.get("cron"), day, heating) is True])
    log("Отправлено: насущное %d из %d, календарь %d задач(и)."
        % (min(as_int(cfg.get("top_n"), 5), free_n), free_n, due_n))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tg.py — одна отправка в Telegram для всех фоновых задач.

Зачем: на проде бывает, что пропадает DNS или интернет
(`Temporary failure in name resolution`). Раньше сообщение в этот момент
просто терялось: скрипт писал «Ошибка отправки» и шёл дальше.

Теперь send():
  1) пробует отправить (attempts раз с паузой);
  2) если сеть недоступна — кладёт сообщение в очередь `state/tg_outbox.jsonl`
     и возвращает ok=True + queued=True (задача считает, что уведомила);
  3) очередь разгребает tools/tg-flush.py по cron каждые 10 минут.

Что НЕ ставим в очередь: отказ самого Telegram (400/403 — неверный chat_id,
битый HTML). Это не лечится ожиданием, поэтому просто пишем в журнал.

Журнал: `logs/tg.log` (виден на /logs.html).

Использование:
    from tools import tg
    r = tg.send(token, chat_id, "<b>привет</b>")
    if not r["ok"]:
        ...  # постоянная ошибка, повторов не будет
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))         # .../u-girlfriend/tools
REPO_DIR = os.path.dirname(HERE)                          # .../u-girlfriend

QUEUE_PATH = os.environ.get("TG_OUTBOX") or os.path.join(REPO_DIR, "state", "tg_outbox.jsonl")
LOG_PATH = os.path.join(REPO_DIR, "logs", "tg.log")

MAX_QUEUE = 1000          # больше не копим: старые всё равно уже не актуальны
MAX_AGE_SEC = 7 * 24 * 3600   # старше недели из очереди выбрасываем

API = "https://api.telegram.org/bot%s/sendMessage"


class Permanent(Exception):
    """Telegram отказал по существу: повторять и ставить в очередь бессмысленно."""


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


def _post(token, chat_id, text, parse_mode, timeout):
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "parse_mode": parse_mode or "",
        "disable_web_page_preview": "true",
        "text": text,
    }).encode()

    try:
        req = urllib.request.Request(API % token, data=data)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        desc = body
        try:
            desc = json.loads(body).get("description") or body
        except Exception:
            pass
        msg = "HTTP %s: %s" % (e.code, (desc or "").strip()[:300])
        if e.code == 429 or e.code >= 500:
            raise OSError(msg)          # перегрузка/сбой сервера — повторим позже
        raise Permanent(msg)            # 400/401/403 — ошибка в запросе или токене
    except Exception as e:
        raise OSError("%s: %s" % (type(e).__name__, e))

    if not resp.get("ok"):
        raise Permanent(resp.get("description") or "ok=false")
    return resp


# ---------------------------------------------------------------- очередь

def _read_queue():
    items = []
    try:
        with open(QUEUE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return items


def _write_queue(items):
    os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
    tmp = QUEUE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    os.replace(tmp, QUEUE_PATH)


def queue_size():
    return len(_read_queue())


def enqueue(chat_id, text, parse_mode="HTML"):
    items = _read_queue()
    items.append({
        "ts": int(time.time()),
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": parse_mode or "HTML",
    })
    if len(items) > MAX_QUEUE:
        dropped = len(items) - MAX_QUEUE
        items = items[-MAX_QUEUE:]
        log("очередь переполнена — выброшено %d старых сообщений" % dropped)
    _write_queue(items)
    return len(items)


# ---------------------------------------------------------------- отправка

def send(token, chat_id, text, parse_mode="HTML", timeout=25, attempts=2, queue=True):
    """Отправить сообщение. Никогда не бросает исключений.

    {"ok": True,  "queued": False}                  — доставлено
    {"ok": True,  "queued": True,  "error": "..."}  — отложено до связи
    {"ok": False, "queued": False, "error": "..."}  — Telegram отказал навсегда
    """
    last = None
    for i in range(max(1, attempts)):
        try:
            _post(token, chat_id, text, parse_mode, timeout)
            log("доставлено в чат %s" % chat_id)
            return {"ok": True, "queued": False}
        except Permanent as e:
            log("Telegram отказал (чат %s): %s — в очередь не ставлю" % (chat_id, e))
            return {"ok": False, "queued": False, "error": str(e)}
        except Exception as e:
            last = e
            if i + 1 < attempts:
                time.sleep(3)

    if queue:
        n = enqueue(chat_id, text, parse_mode)
        log("нет связи с Telegram (%s) — сообщение отложено, в очереди %d" % (last, n))
        return {"ok": True, "queued": True, "error": str(last), "queue_size": n}

    log("нет связи с Telegram (%s), очередь выключена" % last)
    return {"ok": False, "queued": False, "error": str(last)}


def flush(token, timeout=25, quiet=True):
    """Дослать очередь. Возвращает {'sent','failed','dropped','left'}."""
    items = _read_queue()
    res = {"sent": 0, "failed": 0, "dropped": 0, "left": 0}
    if not items:
        return res

    now = time.time()
    keep = []
    for it in items:
        if now - float(it.get("ts") or 0) > MAX_AGE_SEC:
            res["dropped"] += 1
            log("выброшено из очереди как устаревшее: %s" % str(it.get("text"))[:80])
            continue
        try:
            _post(token, it.get("chat_id"), it.get("text") or "",
                  it.get("parse_mode") or "HTML", timeout)
            res["sent"] += 1
        except Permanent as e:
            res["dropped"] += 1
            log("отказ Telegram для сообщения из очереди: %s" % e)
        except Exception as e:
            res["failed"] += 1
            keep.append(it)
            if not quiet:
                log("всё ещё нет связи: %s" % e)

    _write_queue(keep)
    res["left"] = len(keep)
    if res["sent"] or res["dropped"]:
        log("очередь: отправлено %d, выброшено %d, осталось %d"
            % (res["sent"], res["dropped"], res["left"]))
    return res

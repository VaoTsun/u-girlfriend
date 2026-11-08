#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tg-flush.py — дослать сообщения, отложенные во время пропажи связи.

Запуск по cron на проде каждые 10 минут:
    */10 * * * * /usr/bin/python3 /home/vao/u-girlfriend/tools/tg-flush.py

Что делает: читает state/tg_outbox.jsonl (его пополняет tools/tg.py, когда
Telegram недоступен), по одному пытается отправить и оставляет в файле только
те, что всё ещё не ушли. Всё пишет в logs/tg.log — видно на /logs.html.

Ручной прогон:
    python3 tools/tg-flush.py
    python3 tools/tg-flush.py --show     # только показать очередь, ничего не слать
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(HERE)
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

from tools import tg  # noqa: E402

DEFAULT_ENV = "/home/vao/u-barn/.env"


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
        tg.log("не прочитал %s: %s" % (path, e))
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="только показать очередь")
    ap.add_argument("--env-file", default=os.environ.get("TG_ENV_FILE") or DEFAULT_ENV)
    args = ap.parse_args()

    items = tg._read_queue()
    if args.show:
        print("в очереди: %d" % len(items))
        for it in items:
            print("%s  %s" % (it.get("ts"), str(it.get("text"))[:100].replace("\n", " ")))
        return 0

    if not items:
        return 0

    env = load_env(args.env_file)
    token = env.get("TG_PROD_TOKEN") or env.get("TG_TOKEN") or os.environ.get("TG_TOKEN") or ""
    if not token:
        tg.log("очередь: %d сообщ., но нет токена в %s" % (len(items), args.env_file))
        return 2

    res = tg.flush(token)
    if res["failed"]:
        tg.log("очередь ждёт связи: осталось %d" % res["left"])
    return 0 if not res["left"] else 1


if __name__ == "__main__":
    sys.exit(main())

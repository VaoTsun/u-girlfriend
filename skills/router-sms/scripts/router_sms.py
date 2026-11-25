#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Forward unread individual ZTE SMS to Telegram and mark them read.

Production-only cron job. It uses the router's message API rather than its
conversation-grouped table. Local state stores message IDs only; Telegram
history keeps the message text. Delivery uses tools/tg.py's offline queue.
"""

import argparse
import fcntl
import html
import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


REPO_DIR = Path(__file__).resolve().parents[3]
UBARN_DIR = REPO_DIR.parent / "u-barn"
UBARN_ENV = Path(os.environ.get("UBARN_ENV_FILE", UBARN_DIR / ".env"))
VALS_JSON = UBARN_DIR / "vals.json"
ROUTER_URL = "http://192.168.8.3/index.html#sms"
ROUTER_IP = "192.168.8.3"
STATE_DIR = Path(os.environ.get("ROUTER_SMS_STATE_DIR", REPO_DIR / "state"))
STATE_FILE = STATE_DIR / "router_sms.json"
LOCK_FILE = STATE_DIR / "router_sms.lock"
MAX_SEEN = 5000

sys.path.insert(0, str(REPO_DIR))
from tools import tg  # noqa: E402  (repo path must be added first)


def log(message):
    print("[router-sms] " + str(message), flush=True)


def credentials():
    load_dotenv(UBARN_ENV)
    if not UBARN_ENV.is_file() or not VALS_JSON.is_file():
        raise RuntimeError("u-barn .env / vals.json не найдены рядом с u-girlfriend")

    environment = os.environ.get("ENVIRONMENT", "PROD").strip().upper()
    if environment != "PROD":
        raise RuntimeError("мониторинг SMS разрешён только в ENVIRONMENT=PROD")

    with VALS_JSON.open(encoding="utf-8") as f:
        config = json.load(f)
    prod = (config.get("teleGa") or {}).get("PROD") or {}
    token = os.environ.get("TG_PROD_TOKEN") or os.environ.get("TG_TOKEN") or prod.get("token")
    chat_id = prod.get("channel")
    password = os.environ.get("ROUTER_PASSWORD")
    if not token:
        raise RuntimeError("не задан TG_PROD_TOKEN / TG_TOKEN")
    if not chat_id:
        raise RuntimeError("в vals.json не задан teleGa.PROD.channel")
    if not password:
        raise RuntimeError("не задан ROUTER_PASSWORD в u-barn/.env")
    return password, token, chat_id


def read_state():
    try:
        with STATE_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") == 1 and isinstance(data.get("seen"), list):
            # Previous version tracked grouped conversation previews, not SMS IDs.
            # Drop that baseline so the explicitly requested unread backlog is sent.
            return {"version": 2, "seen_ids": [], "migrated": True}
        if data.get("version") != 2 or not isinstance(data.get("seen_ids"), list):
            raise ValueError("неподдерживаемый формат state")
        return data
    except FileNotFoundError:
        return None


def write_state(seen_ids):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": 2, "seen_ids": list(seen_ids)[-MAX_SEEN:]}
    fd, tmp_path = tempfile.mkstemp(prefix="router_sms_", suffix=".tmp", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, STATE_FILE)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def router_sms(password):
    messages = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(ROUTER_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)

            password_input = page.locator("input[type='password'], #txtPwd, #password").first
            if password_input.count() and password_input.is_visible():
                password_input.fill(password)
                login = page.locator("#btnLogin, #btn_login, .login_btn, input[type='button']").first
                if not login.count():
                    raise RuntimeError("на странице роутера не найдена кнопка входа")
                login.click()
                page.wait_for_timeout(2000)
                page.goto(ROUTER_URL, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)

            try:
                page.wait_for_function("typeof window.require === 'function'", timeout=10000)
            except PlaywrightTimeoutError as e:
                raise RuntimeError("AMD loader на странице роутера не загрузился") from e

            stores = (("device", 1), ("sim", 0))
            for storage, store_type in stores:
                result = page.evaluate("""async ({storeType}) => {
                  const api = await new Promise((resolve, reject) =>
                    window.require(['service'], resolve, reject));
                  const all = [];
                  for (let pageNo = 0; pageNo < 10; pageNo++) {
                    const response = await new Promise((resolve, reject) =>
                      api.getSMSMessages({
                        page: pageNo,
                        smsCount: 500,
                        nMessageStoreType: storeType,
                        tags: 10,
                        orderBy: 'order by id desc'
                      }, resolve, reject));
                    const batch = response && Array.isArray(response.messages)
                      ? response.messages : [];
                    all.push(...batch);
                    if (batch.length < 500) return all;
                  }
                  throw new Error('SMS list exceeds safety limit of 5000 messages');
                }""", {"storeType": store_type})
                for item in result:
                    if not item.get("isNew"):
                        continue
                    message_id = str(item.get("id", "")).strip()
                    sender = str(item.get("number", "")).strip()
                    body = str(item.get("content", "")).strip()
                    sent_at = str(item.get("time", item.get("timeOri", ""))).strip()
                    if not message_id or not sender or not body:
                        continue
                    messages.append({
                        "storage": storage,
                        "id": message_id,
                        "key": storage + ":" + message_id,
                        "sender": sender,
                        "sent_at": sent_at,
                        "body": body,
                    })
        finally:
            browser.close()
    return sorted(messages, key=lambda m: (m["storage"], int(m["id"]) if m["id"].isdigit() else 0))


def mark_device_read(password, ids):
    """Use the router UI service API to mark sent device SMS as read."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(ROUTER_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1000)
            password_input = page.locator("input[type='password'], #txtPwd, #password").first
            if password_input.count() and password_input.is_visible():
                password_input.fill(password)
                login = page.locator("#btnLogin, #btn_login, .login_btn, input[type='button']").first
                if not login.count():
                    raise RuntimeError("на странице роутера не найдена кнопка входа")
                login.click()
                page.wait_for_timeout(1800)
                page.goto(ROUTER_URL, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1800)

            return page.evaluate("""async ({ids}) => {
              const api = await new Promise((resolve, reject) =>
                window.require(['service'], resolve, reject));
              return await new Promise((resolve, reject) =>
                api.setSmsRead({ids}, resolve, reject));
            }""", {"ids": [str(i) for i in ids]})
        finally:
            browser.close()


def telegram_text(message):
    prefix = (
        "📩 <b>Новое SMS</b>\n"
        "Хранилище: " + html.escape(message["storage"].upper()) + "\n"
        "От: " + html.escape(message["sender"]) + "\n"
        "Время: " + html.escape(message["sent_at"]) + "\n\n"
    )
    # Keep the body intact where possible, trimming before HTML escaping so
    # truncation cannot split an entity.
    max_body = max(0, 3900 - len(prefix) - 1)
    body = message["body"]
    if len(body) > max_body:
        body = body[:max_body] + "…"
    return prefix + html.escape(body)


def run(dry_run=False):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("предыдущий опрос ещё работает — пропуск")
            return 0

        password, token, chat_id = credentials()
        messages = router_sms(password)
        state = read_state()
        if state is None:
            state = {"version": 2, "seen_ids": []}
        seen_ids = list(state["seen_ids"])
        seen_set = set(seen_ids)
        fresh = [message for message in messages if message["key"] not in seen_set]

        if dry_run:
            log("DRY RUN: непрочитано %d; к отправке %d (без отправки/изменения статуса)" %
                (len(messages), len(fresh)))
            return 0

        failed = 0
        device_ids_to_mark = []
        for message in fresh:
            result = tg.send(token, chat_id, telegram_text(message), parse_mode="HTML")
            if result.get("ok"):
                seen_ids.append(message["key"])
                seen_ids = seen_ids[-MAX_SEEN:]
                seen_set = set(seen_ids)
                write_state(seen_ids)
                if message["storage"] == "device":
                    device_ids_to_mark.append(message["id"])
                log("SMS #%s (%s): Telegram %s" % (
                    message["id"], message["storage"],
                    "в очереди" if result.get("queued") else "доставлено"))
            else:
                failed += 1
                log("Telegram отказал; SMS #%s оставлено непрочитанным для повтора: %s" %
                    (message["id"], str(result.get("error", "ошибка"))))

        # Read marking is done only after Telegram accepted/queued the SMS.
        # Already-sent IDs are marked again on the next poll if this API call fails.
        for message in messages:
            if message["storage"] == "device" and message["key"] in seen_set:
                device_ids_to_mark.append(message["id"])
        device_ids_to_mark = list(dict.fromkeys(device_ids_to_mark))
        if device_ids_to_mark:
            try:
                result = mark_device_read(password, device_ids_to_mark)
                if not result.get("result"):
                    raise RuntimeError("роутер не подтвердил setSmsRead")
                log("отмечено прочитанными Device SMS: %d" % len(device_ids_to_mark))
            except Exception as exc:
                failed += 1
                log("не удалось отметить SMS прочитанными; повторю при следующей проверке: " +
                    str(exc))

        if not fresh:
            log("непрочитанных SMS нет")
        if failed:
            return 1
        return 0


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true",
                            help="посчитать непрочитанные SMS без отправки и без отметки прочитанными")
        args = parser.parse_args()
        raise SystemExit(run(dry_run=args.dry_run))
    except Exception as exc:
        log("ошибка опроса: %s: %s" % (type(exc).__name__, exc))
        raise SystemExit(1)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Poll SMS from the ZTE router web UI and forward new messages to Telegram.

Production-only cron job. The first successful run stores a baseline and does
not forward the messages already present in the router. Subsequent runs watch
both Device SMS and SIM SMS. State contains fingerprints only, not message
bodies; Telegram delivery goes through tools/tg.py and its offline queue.
"""

import fcntl
import hashlib
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
        if data.get("version") != 1 or not isinstance(data.get("seen"), list):
            raise ValueError("неподдерживаемый формат state")
        return data
    except FileNotFoundError:
        return None


def write_state(seen):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "seen": list(seen)[-MAX_SEEN:]}
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


def fingerprint(sender, sent_at, body):
    # Device SMS and SIM SMS may show the same message: use its content and
    # timestamp rather than a per-list row id, which is actually a conversation id.
    source = "\x1f".join((sender.strip(), sent_at.strip(), body.strip()))
    return hashlib.sha256(source.encode("utf-8", "replace")).hexdigest()


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

            category = page.locator("select.form-control").first
            if not category.count():
                raise RuntimeError("не найдены разделы SMS; вход на роутер мог не выполниться")

            for storage, expected_body_class in (
                ("device", "page_sms_smslist"),
                ("sim", "page_sms_sim_messages"),
            ):
                if storage == "sim":
                    category.select_option(storage)
                try:
                    page.wait_for_function(
                        "expected => document.body.classList.contains(expected)",
                        arg=expected_body_class,
                        timeout=10000,
                    )
                except PlaywrightTimeoutError as e:
                    raise RuntimeError("раздел SMS не загрузился: " + storage) from e
                page.wait_for_timeout(1500)

                table = page.locator("table.table")
                if not table.count():
                    raise RuntimeError("таблица SMS не найдена: " + storage)
                headers = " ".join(table.locator("th").all_text_contents()).lower()
                if not all(word in headers for word in ("number", "content", "time")):
                    raise RuntimeError("неожиданные заголовки таблицы SMS: " + storage)

                rows = page.locator("tr.smslist-item")
                for i in range(rows.count()):
                    row = rows.nth(i)
                    cells = row.locator("td")
                    if cells.count() < 4:
                        continue
                    sender = cells.nth(1).inner_text().strip()
                    content_cell = cells.nth(2)
                    body = (content_cell.get_attribute("title") or content_cell.inner_text()).strip()
                    sent_at = cells.nth(3).inner_text().strip()
                    if not sender or not sent_at or not body:
                        continue
                    messages.append({
                        "storage": storage,
                        "sender": sender,
                        "sent_at": sent_at,
                        "body": body,
                        "fingerprint": fingerprint(sender, sent_at, body),
                    })
        finally:
            browser.close()
    return messages


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


def run():
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
        fingerprints = list(dict.fromkeys(m["fingerprint"] for m in messages))

        if state is None:
            write_state(fingerprints)
            log("начальный список сохранён без отправки старых SMS: %d сообщений" % len(messages))
            return 0

        seen = list(state["seen"])
        seen_set = set(seen)
        fresh = []
        for message in messages:
            fp = message["fingerprint"]
            if fp not in seen_set:
                fresh.append(message)
                seen_set.add(fp)

        sent = 0
        failed = 0
        for message in fresh:
            result = tg.send(token, chat_id, telegram_text(message), parse_mode="HTML")
            if result.get("ok"):
                seen.append(message["fingerprint"])
                seen = seen[-MAX_SEEN:]
                seen_set = set(seen)
                write_state(seen)
                sent += 1
                log("SMS обработано (%s), Telegram %s" % (
                    message["storage"], "в очереди" if result.get("queued") else "доставлено"))
            else:
                failed += 1
                log("Telegram отказал; SMS оставлено для повтора: " + str(result.get("error", "ошибка")))

        if not fresh:
            log("новых SMS нет; в просмотренных разделах %d сообщений" % len(messages))
        if failed:
            return 1
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        log("ошибка опроса: %s: %s" % (type(exc).__name__, exc))
        raise SystemExit(1)

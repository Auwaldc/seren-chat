"""
Seren Chat — userbot.py
========================
This is the engine that actually sends the auto-replies. It reads the same
seren.db database that app.py (the Mini App's API) reads and writes, so
anything a customer does in the app — add a target, toggle it on/off, upgrade
their plan — takes effect here immediately, with no extra steps.

IMPORTANT ARCHITECTURE NOTE
----------------------------
Because this is a "userbot" (it automates a customer's OWN personal Telegram
account, not a single shared @bot account), every customer needs their own
logged-in Telethon session before Seren can reply for them. That session is
created ONCE via login_telegram.py (a small separate script/step — Telegram
requires an interactive phone number + login code the first time, which can't
be done from inside a Mini App button click). Once created, the resulting
session string is saved through the Mini App's /api/link-session endpoint,
and from then on this file runs everything automatically in the background.

WHAT THIS FILE DOES, IN ORDER
-------------------------------
1. Every REFRESH_INTERVAL seconds, checks the database for every user who
   has a saved session_string and at least one target.
2. Makes sure exactly one Telethon client is running for each such user
   (starts new ones, stops ones whose session was removed).
3. For each running client, listens for new messages in that user's
   configured groups/DMs. When one arrives:
     - Skips it immediately if the target is off, or the user's premium
       has expired, or (for free users) their 5-minutes-per-week trial is used up.
     - Otherwise waits the configured delay (S/M/H), generates a reply, sends
       it, and logs it to reply_log — which is exactly what powers the
       "Replies today / this week / total" numbers on the dashboard.
4. Enforces the free-trial rule: a free user's one allowed target only gets
   5 real minutes of active reply time every 7 days; once used, it turns
   itself off until the next 7-day window (or until they upgrade).

HOW TO RUN
-----------
    python userbot.py
Keep this running continuously (e.g. as a systemd service, a Docker
container, or a background worker on your host) — it does not serve any
web traffic, it just works quietly in the background.
"""

import os
import asyncio
import sqlite3
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
DB_PATH = os.environ.get("DB_PATH", "seren.db")
REFRESH_INTERVAL = 30          # how often (seconds) we re-check the DB for changes
FREE_TRIAL_SECONDS_PER_WEEK = 5 * 60

running_clients = {}            # tg_id -> Telethon client instance


# ---------------------------------------------------------------------------
# Database helpers (kept intentionally simple / synchronous — sqlite3 is
# fast enough here since writes are small and infrequent per message)
# ---------------------------------------------------------------------------
def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_active_users():
    conn = db_connect()
    rows = conn.execute(
        """SELECT * FROM users
           WHERE session_string IS NOT NULL AND session_string != ''
           AND tg_id IN (SELECT DISTINCT tg_id FROM targets)"""
    ).fetchall()
    conn.close()
    return rows


def get_targets_for(tg_id):
    conn = db_connect()
    rows = conn.execute("SELECT * FROM targets WHERE tg_id=?", (tg_id,)).fetchall()
    conn.close()
    return rows


def is_premium_active(user_row) -> bool:
    if not user_row["sub_end_date"]:
        return False
    try:
        end = datetime.fromisoformat(user_row["sub_end_date"])
    except ValueError:
        return False
    return end.date() >= datetime.utcnow().date()


def free_trial_available(user_row) -> bool:
    """
    Rolling 7-day window: track how many seconds of reply time a free user
    has used, reset the counter once 7 days have passed since the window
    started, and stop replying once FREE_TRIAL_SECONDS_PER_WEEK is reached.
    """
    conn = db_connect()
    week_start = user_row["free_trial_week_start"]
    used = user_row["free_trial_seconds_used"] or 0
    now = datetime.utcnow()

    if not week_start or (now - datetime.fromisoformat(week_start)) > timedelta(days=7):
        conn.execute(
            "UPDATE users SET free_trial_week_start=?, free_trial_seconds_used=0 WHERE tg_id=?",
            (now.isoformat(), user_row["tg_id"]),
        )
        conn.commit()
        used = 0

    conn.close()
    return used < FREE_TRIAL_SECONDS_PER_WEEK


def record_free_trial_usage(tg_id, seconds):
    conn = db_connect()
    conn.execute(
        "UPDATE users SET free_trial_seconds_used = free_trial_seconds_used + ? WHERE tg_id=?",
        (seconds, tg_id),
    )
    conn.commit()
    conn.close()


def log_reply(target_id, message_text):
    conn = db_connect()
    conn.execute(
        "INSERT INTO reply_log (target_id, message_text, sent_at) VALUES (?, ?, ?)",
        (target_id, message_text, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def delay_seconds(delay_unit, delay_val):
    return {"S": 1, "M": 60, "H": 3600}.get(delay_unit, 1) * delay_val


# ---------------------------------------------------------------------------
# Reply generation — plug your real AI/LLM call in here.
# ---------------------------------------------------------------------------
async def generate_ai_reply(incoming_message_text: str) -> str:
    """
    Placeholder. Swap this out for a real call to your AI provider
    (Claude, OpenAI, etc.) to generate a context-aware reply based on
    `incoming_message_text`. Keeping it isolated in one function means the
    rest of the engine never has to change when you change providers/prompts.
    """
    return "Thanks for your message — I'll get back to you shortly!"


# ---------------------------------------------------------------------------
# Per-user Telethon worker
# ---------------------------------------------------------------------------
async def start_client_for_user(tg_id, session_string):
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        conn = db_connect()
        user_row = conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        conn.close()

        # Rule: the instant premium/free-trial runs out, stop replying — no exceptions.
        premium_ok = is_premium_active(user_row)
        if not premium_ok and not free_trial_available(user_row):
            return

        chat = await event.get_chat()
        chat_identifier = getattr(chat, "username", None) or str(getattr(chat, "id", ""))

        targets = get_targets_for(tg_id)
        match = next(
            (t for t in targets if t["is_on"] and chat_identifier and chat_identifier in t["name"]),
            None,
        )
        if not match:
            return

        wait_for = delay_seconds(match["delay_unit"], match["delay_val"])
        await asyncio.sleep(wait_for)

        reply_text = await generate_ai_reply(event.raw_text or "")
        await event.reply(reply_text)

        log_reply(match["id"], reply_text)
        if not premium_ok:
            record_free_trial_usage(tg_id, wait_for)

    await client.start()
    running_clients[tg_id] = client
    print(f"[userbot] started client for {tg_id}")


async def stop_client_for_user(tg_id):
    client = running_clients.pop(tg_id, None)
    if client:
        await client.disconnect()
        print(f"[userbot] stopped client for {tg_id}")


# ---------------------------------------------------------------------------
# Main supervisor loop
# ---------------------------------------------------------------------------
async def supervisor():
    while True:
        active_users = {row["tg_id"]: row for row in get_active_users()}

        # Start any new user we haven't launched a client for yet.
        for tg_id, row in active_users.items():
            if tg_id not in running_clients:
                await start_client_for_user(tg_id, row["session_string"])

        # Stop clients for users who no longer qualify (e.g. deleted all targets).
        for tg_id in list(running_clients.keys()):
            if tg_id not in active_users:
                await stop_client_for_user(tg_id)

        await asyncio.sleep(REFRESH_INTERVAL)


if __name__ == "__main__":
    print("[userbot] Seren Chat auto-reply engine starting...")
    asyncio.run(supervisor())

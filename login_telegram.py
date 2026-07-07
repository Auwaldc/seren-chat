"""
Seren Chat — login_telegram.py
================================
Run this ONCE for each new customer to link their personal Telegram account
to Seren. Telegram requires a phone number + login code the first time a
device/session logs in — that can only happen interactively (this is a
Telegram platform rule, not something a Mini App button can bypass) — so this
is a small command-line step outside the Mini App.

WHAT HAPPENS WHEN YOU RUN IT
------------------------------
1. Asks for the customer's phone number and the login code Telegram texts them.
2. Once logged in, Telethon gives us a "session string" — a long piece of
   text that lets us reconnect as that account without logging in again.
3. This script saves that session string straight into the customer's row in
   seren.db (matched by their Telegram user ID) via the same /api/link-session
   endpoint app.py exposes, so userbot.py can immediately start working for
   them — no manual database editing needed.

HOW TO RUN
-----------
    python login_telegram.py

Keep the resulting session string private — it is equivalent to a password
for that Telegram account.
"""

import os
import requests
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:5000")


def main():
    print("Seren Chat — link a Telegram account\n")
    with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        me = client.get_me()
        tg_id = str(me.id)
        session_string = client.session.save()

        print(f"\nLogged in as @{me.username or me.first_name} (ID: {tg_id})")
        print("Saving this session to Seren's backend...")

        # NOTE: in production, this call should be authenticated the same
        # way the Mini App itself authenticates (a valid Telegram initData),
        # generated right after the customer opens the Mini App for the
        # first time. This script shows the shape of the call; wire it to
        # your real auth flow before going live.
        resp = requests.post(
            f"{BACKEND_URL}/api/link-session",
            json={"session_string": session_string},
            headers={"X-Telegram-Init-Data": os.environ.get("DEV_INIT_DATA", "")},
        )
        if resp.ok:
            print("Done — Seren can now reply for this account.")
        else:
            print(f"Something went wrong: {resp.status_code} {resp.text}")


if __name__ == "__main__":
    main()

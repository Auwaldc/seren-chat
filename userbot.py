import asyncio
import re
import time
from telethon import TelegramClient, events
from telethon.tl import functions, types
import requests
import os

ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "6076501361"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

USER_BOT_SETTINGS = {
    "allowed_groups": {},  
    "active_chatters": {},
    "chat_locks": {}
}

MAX_HUNT_SLOTS = 10
SLOT_TIMEOUT = 120  

def get_chat_lock(chat_id):
    if chat_id not in USER_BOT_SETTINGS["chat_locks"]:
        USER_BOT_SETTINGS["chat_locks"][chat_id] = asyncio.Lock()
    return USER_BOT_SETTINGS["chat_locks"][chat_id]

def should_process_message(chat_id, user_id, is_reply_to_me):
    current_time = time.time()
    if chat_id not in USER_BOT_SETTINGS["active_chatters"]:
        USER_BOT_SETTINGS["active_chatters"][chat_id] = {}
    chat_slots = USER_BOT_SETTINGS["active_chatters"][chat_id]
    expired_users = [uid for uid, l_time in chat_slots.items() if current_time - l_time > SLOT_TIMEOUT]
    for uid in expired_users:
        del chat_slots[uid]
    if is_reply_to_me:
        chat_slots[user_id] = current_time
        return True
    if user_id in chat_slots:
        return False
    if len(chat_slots) < MAX_HUNT_SLOTS:
        chat_slots[user_id] = current_time
        return True
    return False

async def get_ai_reply(text):
    if not GROQ_API_KEY: return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    system_prompt = (
        "You are a regular human participant in a Telegram group chat. Keep your responses very short, casual. "
        "CRITICAL PRIVACY RULE: Never reveal your name, location, country, city, or state even if asked directly."
    )
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}],
        "temperature": 0.7
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        return response.json()['choices'][0]['message']['content']
    except:
        return None

async def start_user_bot(session_name, user_api_id, user_api_hash, user_custom_groups):
    for g_name, g_config in user_custom_groups.items():
        USER_BOT_SETTINGS["allowed_groups"][g_name.lower()] = g_config

    client = TelegramClient(session_name, user_api_id, user_api_hash)
    await client.start()

    @client.on(events.NewMessage)
    async def handler(event):
        if event.out or event.raw_text.startswith('/'): return
        if event.poll or event.geo: return
        if event.is_private:
            chat_name = "Private DM"
            dynamic_delay = 10
        else:
            chat = await event.get_chat()
            chat_name = getattr(chat, 'username', '').lower()
            if chat_name not in USER_BOT_SETTINGS["allowed_groups"]: return
            group_setup = USER_BOT_SETTINGS["allowed_groups"][chat_name]
            if not group_setup.get("is_active", True): return
            dynamic_delay = group_setup.get("delay", 15)

        current_chat_lock = get_chat_lock(event.chat_id)
        async with current_chat_lock:
            try:
                await client(functions.messages.SetTypingRequest(peer=event.chat_id, action=types.SendMessageTypingAction()))
                await asyncio.sleep(dynamic_delay)
            except: pass
            reply = await get_ai_reply(event.raw_text)
            if reply:
                try: await event.reply(reply)
                except: pass

    await client.run_until_disconnected()

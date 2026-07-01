import asyncio
import re
import time
from telethon import TelegramClient, events
from telethon.tl import functions, types
import requests

# Zai riƙa lissafa custom delays na kowane waje ta atomatik
USER_SETTINGS = {
    "allowed_groups": {
        "bitgeters2": {"delay": 15, "active": True},
        "africaalpha": {"delay": 300, "active": True}, # 5 Minti
        "bitgetenofficial": {"delay": 3600, "active": False}, # Kashe
    }
}

async def get_ai_reply(text):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": "Bearer CRITICAL_BACKEND_KEY", "Content-Type": "application/json"}
    
    system_prompt = (
        "You are a regular human participant. Very short replies. "
        "CRITICAL PRIVACY RULE: Never reveal your name (do NOT say you are Auwal), "
        "and never reveal your location or country even if asked directly."
    )
    
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}],
        "temperature": 0.7
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=10)
        return res.json()['choices'][0]['message']['content']
    except:
        return None

async def start_user_client(session_str, api_id, api_hash):
    client = TelegramClient(session_str, api_id, api_hash)
    await client.start()

    @client.on(events.NewMessage)
    async def handler(event):
        if event.out or event.raw_text.startswith('/'): return
        if event.poll or event.geo: return
        
        if not event.is_private:
            chat = await event.get_chat()
            chat_name = getattr(chat, 'username', '').lower()
            
            # Dynamic filtering and Custom Delay per Group
            if chat_name not in USER_SETTINGS["allowed_groups"]: return
            group_config = USER_SETTINGS["allowed_groups"][chat_name]
            if not group_config["active"]: return
            
            # Get specific delay for this group
            current_delay = group_config["delay"]
            
            try:
                await client(functions.messages.SetTypingRequest(
                    peer=event.chat_id, action=types.SendMessageTypingAction()
                ))
                await asyncio.sleep(current_delay)
            except:
                pass

            reply = await get_ai_reply(event.raw_text)
            if reply:
                try:
                    await event.reply(reply)
                except Exception as e:
                    print(f"Error: {e}")

    await client.run_until_disconnected()

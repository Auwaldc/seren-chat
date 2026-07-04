import asyncio
import time
from telethon import TelegramClient, events

class SerenUserbot:
    def __init__(self, session_name, api_id, api_hash, phone):
        self.session_name = session_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.client = None
        self.is_running = False
        self.targets = {}  # {chat_id: {"mode": "group/dm", "delay": seconds, "last_sent": 0}}
        self.stats = {"today": 0, "week": 0, "total": 0, "start_time": time.time()}
        self.mode = "Groups Only" # Ko "Private DMs"
        
    async def start_session(self, code=None, password=None):
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        await self.client.connect()
        
        if not await self.client.is_user_authorized():
            if not code:
                return "need_code"
            try:
                if password:
                    await self.client.sign_in(password=password)
                else:
                    await self.client.sign_in(self.phone, code)
            except Exception as e:
                if "2-step verification" in str(e).lower() or "password" in str(e).lower():
                    return "need_2fa"
                raise e
        
        self.is_running = True
        asyncio.create_task(self.run_bot_loop())
        return "authorized"

    def update_targets(self, new_targets, mode):
        self.mode = mode
        self.targets = {}
        for t in new_targets:
            if t['status'] == 'ON':
                # Convert delay to seconds
                val = int(t['delay_val'])
                if t['delay_unit'] == 'M': val *= 60
                elif t['delay_unit'] == 'H': val *= 3600
                self.targets[t['chat']] = {
                    "mode": "group" if mode == "Groups Only" else "dm",
                    "delay": val,
                    "last_sent": 0,
                    "text": "Hello! This is Seren Chat Auto Reply Bot."
                }

    async def run_bot_loop(self):
        while self.is_running:
            if not self.targets:
                await asyncio.sleep(2)
                continue
                
            current_time = time.time()
            for chat, config in list(self.targets.items()):
                if current_time - config["last_sent"] >= config["delay"]:
                    try:
                        await self.client.send_message(chat, config["text"])
                        config["last_sent"] = current_time
                        self.stats["today"] += 1
                        self.stats["week"] += 1
                        self.stats["total"] += 1
                    except Exception:
                        pass # Guje wa crash idan an cire bot a group
            await asyncio.sleep(1)

    async def stop(self):
        self.is_running = False
        if self.client:
            await self.client.disconnect()

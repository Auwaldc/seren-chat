import asyncio
import time
from telethon import TelegramClient, events

class SerenUserbot:
    def __init__(self, session_name, api_id, api_hash, phone):
        self.session_name = session_name
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.phone = phone
        self.client = None
        self.is_running = False
        self.phone_code_hash = None
        self.targets = {}  # {chat_id: {"mode": "group/dm", "delay": seconds, "last_sent": 0}}
        self.stats = {"today": 0, "week": 0, "total": 0, "start_time": time.time()}
        self.mode = "Groups Only"
        
    async def request_otp(self):
        """Matakin farko: Tura OTP zuwa Telegram app na mutum"""
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        await self.client.connect()
        
        # Binciken da ka nema: Tabbatar da lambar ta dace da API credentials
        try:
            send_code_result = await self.client.send_code_request(self.phone)
            self.phone_code_hash = send_code_result.phone_code_hash
            return {"status": "need_code", "message": "OTP sent successfully."}
        except Exception as e:
            await self.client.disconnect()
            return {"status": "error", "message": "This phone number does not match the API ID and API Hash provided."}

    async def verify_otp_and_login(self, code, password=None):
        """Mataki na biyu: Karbar OTP da duba 2FA Password"""
        if not self.client:
            return {"status": "error", "message": "Session not initialized."}
            
        try:
            await self.client.sign_in(self.phone, code, phone_code_hash=self.phone_code_hash)
            self.is_running = True
            asyncio.create_task(self.run_bot_loop())
            return {"status": "authorized"}
        except Exception as e:
            if "verification code" in str(e).lower():
                return {"status": "error", "message": "Invalid OTP Code."}
            elif "2-step verification" in str(e).lower() or "password" in str(e).lower():
                if not password:
                    return {"status": "need_2fa", "message": "2FA Cloud Password required."}
                try:
                    await self.client.sign_in(password=password)
                    self.is_running = True
                    asyncio.create_task(self.run_bot_loop())
                    return {"status": "authorized"}
                except Exception:
                    return {"status": "error", "message": "Incorrect 2FA Password."}
            return {"status": "error", "message": str(e)}

    def update_targets(self, new_targets, mode):
        self.mode = mode
        self.targets = {}
        for t in new_targets:
            if t.get('status') == 'ON':
                val = int(t['delay_val'])
                if t['delay_unit'] == 'M': val *= 60
                elif t['delay_unit'] == 'H': val *= 3600
                self.targets[t['chat']] = {
                    "mode": "group" if mode == "Groups Only" else "dm",
                    "delay": val,
                    "last_sent": 0,
                    "text": "Hello! Seren Chat Bot is active here."
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
                        pass
            await asyncio.sleep(1)

    async def stop(self):
        self.is_running = False
        if self.client:
            await self.client.disconnect()

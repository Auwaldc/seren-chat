import asyncio, redis, json, os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from cryptography.fernet import Fernet
from datetime import datetime

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
cipher = Fernet(os.getenv("ENCRYPTION_KEY").encode())

async def run_userbot(user_id):
    user_data = r.hgetall(f"user:{user_id}")
    if not user_data: return
    
    session = cipher.decrypt(user_data["session"].encode()).decode()
    client = TelegramClient(StringSession(session), int(os.getenv("API_ID")), os.getenv("API_HASH"))
    await client.connect()
    
    r.set(f"worker:active:{user_id}", "1")
    
    # Load targets
    async def load_targets():
        targets = {}
        for t_key in r.smembers(f"targets:{user_id}"):
            t = r.hgetall(t_key)
            if t["active"] == "1" and datetime.fromisoformat(t["expires_at"]) > datetime.now():
                targets[t["link"]] = int(t["delay"])
        return targets
    
    active_targets = await load_targets()
    
    @client.on(events.NewMessage)
    async def handler(event):
        chat_username = f"@{event.chat.username}" if event.chat else ""
        if chat_username in active_targets:
            await asyncio.sleep(active_targets[chat_username])
            await event.reply("This is an auto-reply from Seren Chat.") # Saka sakonka anan
            r.hincrby(f"target:{user_id}:{chat_username}", "replies_today", 1)
    
    # Saurari Redis don reload ko stop
    pubsub = r.pubsub()
    pubsub.subscribe("worker_control")
    
    async def redis_listener():
        for msg in pubsub.listen():
            if msg["type"] == "message":
                data = json.loads(msg["data"])
                if data["user_id"] == user_id and data["action"] == "reload":
                    nonlocal active_targets
                    active_targets = await load_targets()
                if data["user_id"] == user_id and data["action"] == "stop":
                    await client.disconnect()
                    return
    
    await asyncio.gather(client.run_until_disconnected(), redis_listener())

if __name__ == "__main__":
    # A production, za a yi amfani da Celery ko K8s don kunna kowane user
    asyncio.run(run_userbot(123456789))

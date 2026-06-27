import asyncio
import re
import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl import functions, types
import requests

app = FastAPI(title="Seren Chat Mini App Backend")

# Bada damar Frontend (Mini App UI) ya iya magana da wannan Backend din
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- IN-MEMORY DATABASE (Don Sauki da Gudun Bug a Railway) ---
USERS_DB = {} 
RUNNING_BOTS = {} # Wajen adana bots din da ke raye yanzu da ke aiki

# Admin Username
ADMIN_USERNAME = "Auwaldc"

# --- PYDANTIC MODELS (Tsarin Karbar Bayanai daga Mini App) ---
class UserLoginInit(BaseModel):
    api_id: int
    api_hash: str
    phone_number: str

class UserOTPVerify(BaseModel):
    phone_number: str
    otp_code: str
    password_2fa: str = None
    groq_key: str = None # User zai iya saka nasa Groq key din ta Mini App

class SubscriptionUpdate(BaseModel):
    admin_user: str
    target_phone: str
    status: bool # True don Kunna, False don Kashe
    allowed_groups: list = [] # Jerin groups din da ya biya

# --- USERBOT CORE LOGIC ---
chat_locks = {}
active_chatters = {}
MAX_HUNT_SLOTS = 10
SLOT_TIMEOUT = 120

def get_chat_lock(chat_id):
    if chat_id not in chat_locks:
        chat_locks[chat_id] = asyncio.Lock()
    return chat_locks[chat_id]

def should_process_message(chat_id, user_id, is_reply_to_me):
    current_time = time.time()
    if chat_id not in active_chatters:
        active_chatters[chat_id] = {}
    chat_slots = active_chatters[chat_id]
    
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

async def get_ai_reply(text, groq_key):
    if not groq_key or groq_key == "PLACEHOLDER_KEY":
        return None
        
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
    
    system_prompt = (
        "You are a regular human participant in a Telegram group chat. "
        "Keep your responses very short, casual, and completely natural. "
        "Never reveal your name, and never reveal your location. Deflect naturally."
    )
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        "temperature": 0.7
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        return response.json()['choices'][0]['message']['content']
    except Exception:
        return None

# Instantiating a dynamic handler creator for each logged-in client
def create_handler(client, allowed_groups, groq_key):
    @client.on(events.NewMessage)
    async def handler(event):
        if event.out: return
        raw_text = event.raw_text.strip().lower() if event.raw_text else ""
        if raw_text.startswith('/') or event.poll or event.geo: return
        
        if event.is_private:
            sender = await event.get_sender()
            chat_name = getattr(sender, 'username', 'Private DM') or 'Private DM'
            sender_username = chat_name
        else:
            chat = await event.get_chat()
            chat_name = getattr(chat, 'username', 'Group') or 'Group'
            try:
                sender = await event.get_sender()
                sender_username = getattr(sender, 'username', '') or ''
            except Exception: sender_username = ''

        if sender_username.lower().endswith('bot'): return
        if not event.is_private and chat_name.lower() not in allowed_groups: return
        if (event.photo or event.file) and "@somethindc" not in raw_text: return
        if event.sticker or event.gif or "bot" in raw_text or "ai" in raw_text: return
        if not re.search(r'[a-zA-Z0-9]', raw_text): return
        
        coins_list = {'btc', 'eth', 'sol', 'bgb', 'gram', 'usdt', 'trx', 'bnb', 'ton'}
        if raw_text in coins_list: return

        is_reply_to_me = False
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            if reply_msg and reply_msg.out: is_reply_to_me = True

        if not event.is_private and not should_process_message(event.chat_id, event.sender_id, is_reply_to_me): return

        current_chat_lock = get_chat_lock(event.chat_id)
        async with current_chat_lock:
            try:
                await client(functions.messages.SetTypingRequest(peer=event.chat_id, action=types.SendMessageTypingAction()))
                await asyncio.sleep(15) # 15 Seconds delay
            except Exception: pass

            reply = await get_ai_reply(event.raw_text, groq_key)
            if reply:
                try:
                    await event.reply(reply)
                except Exception: pass
    return handler

# --- API ENDPOINTS ---
TEMP_LOGINS = {}

@app.post("/api/auth/initiate")
async def initiate_login(data: UserLoginInit):
    try:
        client = TelegramClient(StringSession(), data.api_id, data.api_hash)
        await client.connect()
        phone_code_hash = await client.send_code_request(data.phone_number)
        
        TEMP_LOGINS[data.phone_number] = {
            "client": client,
            "api_id": data.api_id,
            "api_hash": data.api_hash,
            "phone_code_hash": phone_code_hash.phone_code_hash
        }
        return {"status": "success", "message": "OTP has been sent to your Telegram account."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/verify")
async def verify_otp(data: UserOTPVerify):
    if data.phone_number not in TEMP_LOGINS:
        raise HTTPException(status_code=400, detail="Please initiate login first.")
        
    login_data = TEMP_LOGINS[data.phone_number]
    client = login_data["client"]
    
    try:
        try:
            await client.sign_in(
                phone=data.phone_number,
                code=data.otp_code,
                phone_code_hash=login_data["phone_code_hash"]
            )
        except Exception as e:
            if "Two-step verification" in str(e) or "password" in str(e).lower():
                if not data.password_2fa:
                    return {"status": "requires_2fa", "message": "Two-factor authentication is enabled. Please provide your 2FA password."}
                await client.sign_in(password=data.password_2fa)
            else:
                raise e
                
        session_str = client.session.save()
        
        # Saita Groq Key ta atomatik idan user bai turo daban ba
        user_groq_key = data.groq_key if data.groq_key else "PLACEHOLDER_KEY"
        
        USERS_DB[data.phone_number] = {
            "api_id": login_data["api_id"],
            "api_hash": login_data["api_hash"],
            "session_string": session_str,
            "is_active": False, 
            "allowed_groups": [],
            "groq_key": user_groq_key
        }
        
        del TEMP_LOGINS[data.phone_number]
        return {"status": "success", "message": "Account linked successfully! Awaiting Admin activation."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/admin/subscription")
async def update_subscription(data: SubscriptionUpdate):
    if data.admin_user.lower() != ADMIN_USERNAME.lower():
        raise HTTPException(status_code=403, detail="Unauthorized! Only Admin @Auwaldc can access this dashboard.")
        
    if data.target_phone not in USERS_DB:
        raise HTTPException(status_code=404, detail="User phone number not found in database.")
        
    user = USERS_DB[data.target_phone]
    user["is_active"] = data.status
    user["allowed_groups"] = [g.lower() for g in data.allowed_groups]
    
    if data.status:
        asyncio.create_task(start_user_bot(data.target_phone))
        return {"status": "success", "message": f"Subscription activated for {data.target_phone}. Bot is now running!"}
    else:
        if data.target_phone in RUNNING_BOTS:
            await RUNNING_BOTS[data.target_phone].disconnect()
            del RUNNING_BOTS[data.target_phone]
        return {"status": "success", "message": f"Subscription deactivated for {data.target_phone}."}

async def start_user_bot(phone_number):
    user_data = USERS_DB[phone_number]
    if phone_number in RUNNING_BOTS:
        return
        
    client = TelegramClient(
        StringSession(user_data["session_string"]),
        user_data["api_id"],
        user_data["api_hash"]
    )
    
    await client.connect()
    create_handler(client, user_data["allowed_groups"], user_data["groq_key"])
    RUNNING_BOTS[phone_number] = client
    print(f"🚀 Userbot for {phone_number} started successfully via Mini App Backend!")
    await client.run_until_disconnected()

@app.get("/api/dashboard/{phone_number}")
async def get_user_dashboard(phone_number: str):
    if phone_number not in USERS_DB:
        raise HTTPException(status_code=404, detail="User not found.")
    user = USERS_DB[phone_number]
    return {
        "phone_number": phone_number,
        "is_active": user["is_active"],
        "allowed_groups": user["allowed_groups"],
        "status": "Running" if phone_number in RUNNING_BOTS else "Stopped"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

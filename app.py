from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from cryptography.fernet import Fernet
import os, asyncio, redis, json
from datetime import datetime, timedelta
from typing import Optional

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Redis don real-time worker control
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", Fernet.generate_key())
cipher = Fernet(ENCRYPTION_KEY)

# --- MODELS ---
class LoginRequest(BaseModel):
    api_id: int
    api_hash: str
    phone: str

class OTPRequest(BaseModel):
    phone: str
    code: str
    api_id: int
    api_hash: str
    password: Optional[str] = None

class TargetRequest(BaseModel):
    user_id: int
    type: str # 'group' or 'dm'
    link: str
    delay_value: int
    delay_unit: str # 'S', 'M', 'H'

# --- AUTH ENDPOINTS ---
sessions = {}

@app.post("/api/get_code")
async def get_code(data: LoginRequest):
    try:
        client = TelegramClient(StringSession(), data.api_id, data.api_hash)
        await client.connect()
        sent = await client.send_code_request(data.phone)
        sessions[data.phone] = {"client": client, "phone_code_hash": sent.phone_code_hash}
        return {"status": "code_sent"}
    except Exception as e:
        raise HTTPException(400, "This phone number does not match the API ID and API Hash provided.")

@app.post("/api/sign_in")
async def sign_in(data: OTPRequest):
    if data.phone not in sessions:
        raise HTTPException(400, "Session expired. Request code again.")
    
    client = sessions[data.phone]["client"]
    try:
        await client.sign_in(
            data.phone, 
            data.code, 
            phone_code_hash=sessions[data.phone]["phone_code_hash"]
        )
    except errors.SessionPasswordNeededError:
        if not data.password:
            return {"status": "2fa_needed"}
        await client.sign_in(password=data.password)
    
    me = await client.get_me()
    session_string = cipher.encrypt(client.session.save().encode()).decode()
    
    # Ajiye user a DB + kunna worker
    user_data = {"user_id": me.id, "username": me.username, "session": session_string}
    r.hset(f"user:{me.id}", mapping=user_data)
    r.publish("worker_control", json.dumps({"action": "start", "user_id": me.id}))
    
    del sessions[data.phone]
    await client.disconnect()
    return {"status": "success", "user_id": me.id, "username": me.username}

# --- TARGETS ENDPOINTS ---
@app.post("/api/targets/add")
async def add_target(data: TargetRequest):
    delay_seconds = data.delay_value
    if data.delay_unit == 'M': delay_seconds *= 60
    if data.delay_unit == 'H': delay_seconds *= 3600
    
    target_id = f"target:{data.user_id}:{data.link}"
    r.hset(target_id, mapping={
        "type": data.type, "link": data.link, "delay": delay_seconds, 
        "active": "1", "replies_today": 0, "expires_at": (datetime.now() + timedelta(days=30)).isoformat()
    })
    r.sadd(f"targets:{data.user_id}", target_id)
    r.publish("worker_control", json.dumps({"action": "reload", "user_id": data.user_id}))
    return {"status": "added"}

@app.get("/api/dashboard/{user_id}")
async def get_dashboard(user_id: int):
    targets = r.smembers(f"targets:{user_id}")
    active_targets = sum(1 for t in targets if r.hget(t, "active") == "1")
    replies_today = sum(int(r.hget(t, "replies_today") or 0) for t in targets)
    
    sub = r.hgetall(f"sub:{user_id}")
    days_left = 0
    if sub:
        days_left = (datetime.fromisoformat(sub["end_date"]) - datetime.now()).days
        
    return {
        "active_targets": active_targets,
        "replies_today": replies_today,
        "replies_week": 794, # Za a ciro daga DB
        "subscription_days_left": max(0, days_left),
        "bot_status": "ON" if r.exists(f"worker:active:{user_id}") else "OFF"
    }

# --- ADMIN ENDPOINTS ---
ADMIN_ID = 123456789 # @Auwaldc user_id

@app.get("/api/admin/pending")
async def pending_payments(user_id: int):
    if user_id!= ADMIN_ID: raise HTTPException(403, "Not admin")
    keys = r.keys("payment:pending:*")
    return [r.hgetall(k) for k in keys]

@app.post("/api/admin/approve")
async def approve_payment(user_id: int, target_user: int, plan: str):
    if user_id!= ADMIN_ID: raise HTTPException(403, "Not admin")
    days = {"1 Week": 7, "2 Weeks": 14, "1 Month": 30}[plan]
    r.hset(f"sub:{target_user}", mapping={
        "plan": plan, 
        "start_date": datetime.now().isoformat(),
        "end_date": (datetime.now() + timedelta(days=days)).isoformat()
    })
    r.publish("notifications", json.dumps({"user_id": target_user, "msg": "Premium Approved! Blue Tick added."}))
    return {"status": "approved"}

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

app = FastAPI(title="Seren Chat API")

ADMIN_ID = 6076501361
DATABASE = {"users": {}, "targets": {}, "announcements": [], "payments": []}

class AuthRequest(BaseModel):
    phone: str
    api_id: int
    api_hash: str

class OTPRequest(BaseModel):
    phone: str
    otp: str
    password_2fa: Optional[str] = None

class TargetModel(BaseModel):
    chat_id: str
    delay: int
    delay_unit: str  # S, M, H
    is_active: bool

class PaymentSubmit(BaseModel):
    telegram_id: int
    plan: str  # 1 Week ($10), 2 Weeks ($20), 3 Weeks ($30)
    tx_hash: str

# --- AUTH FLOW ---
@app.post("/auth/connect")
async def connect_account(data: AuthRequest):
    # Anan tsarin Telethon zai fara buƙatar lambar sirri
    return {"status": "success", "message": "OTP sent via Telegram"}

@app.post("/auth/verify")
async def verify_otp(data: OTPRequest):
    # Tabbatar da OTP da 2FA
    return {"status": "success", "session": "session_string_generated"}

# --- USER TARGETS MANAGEMENT ---
@app.post("/targets/{user_id}")
async def save_target(user_id: int, target: TargetModel):
    if user_id not in DATABASE["targets"]:
        DATABASE["targets"][user_id] = []
    DATABASE["targets"][user_id].append(target.dict())
    return {"status": "success", "message": "Target saved"}

# --- ADMIN DASHBOARD (Restricted to ADMIN_ID) ---
def verify_admin(user_id: int):
    if user_id != ADMIN_ID:
        raise HTTPException(status_code=403, detail="Unauthorized Access")

@app.get("/admin/dashboard/{user_id}")
async def get_admin_dashboard(user_id: int):
    verify_admin(user_id)
    return {
        "total_users": len(DATABASE["users"]),
        "pending_payments": DATABASE["payments"],
        "announcements": DATABASE["announcements"]
    }

@app.post("/admin/broadcast/{user_id}")
async def create_announcement(user_id: int, message: str):
    verify_admin(user_id)
    DATABASE["announcements"].append({"message": message})
    return {"status": "success"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

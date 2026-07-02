from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os

app = FastAPI()

# Bada damar sadarwa tsakanin GitHub Pages da Render Server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "6076501361"))

class ConnectionData(BaseModel):
    api_id: int
    api_hash: str
    phone: str

@app.get("/")
async def root():
    return {"status": "online", "app": "Seren Chat Backend"}

@app.post("/api/connect")
async def connect_account(data: ConnectionData):
    # Wuri na musamman da zai tura OTP zuwa Telegram na asusun user
    return {"status": "success", "message": f"OTP sent to {data.phone}"}

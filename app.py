from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import time
from userbot import SerenUserbot

app = Flask(__name__)
CORS(app) # Yana bawa Mini App damar magana da Backend ba tare da blockage ba

# Real-time Database state
db = {
    "users": {},
    "pending_payments": [],
    "announcements": [],
    "admin_id": "Auwaldc"
}

active_sessions = {} # { tgId: SerenUserbot_Instance }

@app.route('/api/auth/register', methods=['POST'])
def register_step1():
    data = request.json
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    phone = data.get('phone')
    tg_id = data.get('tgId') # An dauko daga Telegram WebApp initData
    
    session_name = f"session_{tg_id}"
    bot = SerenUserbot(session_name, api_id, api_hash, phone)
    active_sessions[tg_id] = bot
    
    # Gudanar da async function a cikin Flask
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    response = loop.run_until_complete(bot.request_otp())
    
    return jsonify(response)

@app.route('/api/auth/verify', methods=['POST'])
def register_step2():
    data = request.json
    tg_id = data.get('tgId')
    code = data.get('code')
    password = data.get('password', None)
    
    bot = active_sessions.get(tg_id)
    if not bot:
        return jsonify({"status": "error", "message": "Authentication session not found. Please restart."}), 400
        
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    response = loop.run_until_complete(bot.verify_otp_and_login(code, password))
    
    if response["status"] == "authorized":
        # Ajiye user a database na gaske
        db["users"][tg_id] = {
            "tgId": tg_id,
            "api_id": bot.api_id,
            "api_hash": bot.api_hash,
            "phone": bot.phone,
            "is_premium": False,
            "blue_tick": False,
            "sub_start": None,
            "sub_end": None
        }
    return jsonify(response)

@app.route('/api/user/sync', methods=['POST'])
def sync_user():
    data = request.json
    tg_id = data.get('tgId')
    targets = data.get('targets', [])
    mode = data.get('mode', 'Groups Only')
    
    # Tura sabbin targets da yanayin aiki zuwa ainihin Telethon Loop
    bot = active_sessions.get(tg_id)
    if bot and bot.is_running:
        bot.update_targets(targets, mode)
        return jsonify({"status": "synced", "stats": bot.stats})
        
    return jsonify({"status": "offline", "stats": {"today": 0, "week": 0, "total": 0}})

@app.route('/api/admin/action', methods=['POST'])
def admin_action():
    data = request.json
    admin_user = data.get('adminUser') # e.g. @Auwaldc
    target_user_id = str(data.get('targetUserId'))
    action = data.get('action') # 'accept', 'reject', 'revoke'
    plan = data.get('plan', '1 Month Plan')
    
    if admin_user != f"@{db['admin_id']}":
        return jsonify({"error": "Unauthorized Access"}), 403
        
    if target_user_id in db["users"]:
        user = db["users"][target_user_id]
        if action == 'accept':
            user["is_premium"] = True
            user["blue_tick"] = True
            user["sub_start"] = time.strftime("%B %d, %Y")
            user["sub_end"] = time.strftime("%B %d, %Y", time.localtime(time.time() + 2592000))
        elif action in ['reject', 'revoke']:
            user["is_premium"] = False
            user["blue_tick"] = False
            if target_user_id in active_sessions:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(active_sessions[target_user_id].stop())
        return jsonify({"status": "success", "user": user})
        
    return jsonify({"error": "User not found"}), 404

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

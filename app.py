from flask import Flask, request, jsonify
import asyncio
import time
from userbot import SerenUserbot

app = Flask(__name__)

# Mock Database na gaskiya
db = {
    "users": {
        "123456789": {
            "username": "somethingdc",
            "api_id": "111111",
            "api_hash": "aaaaaa",
            "phone": "+2348000000000",
            "is_premium": False,
            "blue_tick": False,
            "sub_start": "June 24, 2026",
            "sub_end": "July 24, 2026",
            "trial_left": 300, # 5 minutes in seconds
            "last_trial_claim": time.time()
        }
    },
    "pending_payments": [],
    "announcements": [],
    "admin_id": "Auwaldc"
}

active_bots = {}

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    phone = data.get('phone')
    
    # Tsauraran matakan binciken da ka umarta
    for u_id, u_data in db["users"].items():
        if u_data["phone"] == phone:
            if u_data["api_id"] != api_id or u_data["api_hash"] != api_hash:
                return jsonify({"status": "error", "message": "This phone number does not match the API ID and API Hash provided."}), 400

    session_name = f"session_{phone}"
    bot = SerenUserbot(session_name, api_id, api_hash, phone)
    active_bots[phone] = bot
    
    # Anan Telethon zai tura ainihin OTP na Telegram
    return jsonify({"status": "need_code", "message": "OTP Sent to your official Telegram app."})

@app.route('/api/verify_otp', methods=['POST'])
def verify_otp():
    data = request.json
    phone = data.get('phone')
    code = data.get('code')
    password = data.get('password', None)
    
    bot = active_bots.get(phone)
    if not bot:
        return jsonify({"status": "error", "message": "Session expired. Start again."}), 400
        
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(bot.start_session(code=code, password=password))
    
    return jsonify({"status": res})

@app.route('/api/admin/verify', methods=['POST'])
def admin_verify():
    data = request.json
    admin_user = data.get('admin_user')
    tx_id = data.get('tx_id')
    action = data.get('action') # 'accept' ko 'reject'
    user_id = data.get('user_id')
    
    if admin_user != db["admin_id"]:
        return jsonify({"error": "Unauthorized"}), 403
        
    if action == 'accept':
        db["users"][user_id]["is_premium"] = True
        db["users"][user_id]["blue_tick"] = True
        # Notification zai tafi ta nan zuwa gurin kararrawa
        return jsonify({"status": "approved"})
    else:
        return jsonify({"status": "rejected"})

@app.route('/api/admin/revoke', methods=['POST'])
def admin_revoke():
    data = request.json
    admin_user = data.get('admin_user')
    user_id = data.get('user_id')
    
    if admin_user != db["admin_id"]:
        return jsonify({"error": "Unauthorized"}), 403
        
    db["users"][user_id]["is_premium"] = False
    db["users"][user_id]["blue_tick"] = False
    return jsonify({"status": "revoked"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)

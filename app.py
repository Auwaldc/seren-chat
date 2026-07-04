from flask import Flask, request, jsonify, session
from flask_cors import CORS
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    ApiIdInvalidError,
)

import sqlite3
import os
import json
import time

app = Flask(__name__)
app.secret_key = "SEREN_CHAT_SECRET"

CORS(app)

DATABASE = "serenchat.db"


def db():
    return sqlite3.connect(DATABASE)


def create_tables():
    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT,
        api_id TEXT,
        api_hash TEXT,
        phone TEXT,
        session TEXT,
        username TEXT,
        premium INTEGER DEFAULT 0,
        expire_date TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS targets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        target TEXT,
        mode TEXT,
        delay INTEGER,
        status INTEGER DEFAULT 1
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS notifications(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        body TEXT,
        seen INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()


create_tables()


@app.route("/")
def home():
    return jsonify({
        "app":"Seren Chat",
        "status":"Running"
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000,debug=True)
    # ==========================
# TELEGRAM LOGIN APIs
# ==========================

clients = {}

@app.route("/send_code", methods=["POST"])
def send_code():

    data = request.get_json()

    api_id = int(data["api_id"])
    api_hash = data["api_hash"]
    phone = data["phone"]

    try:

        client = TelegramClient(
            StringSession(),
            api_id,
            api_hash
        )

        client.connect()

        client.send_code_request(phone)

        clients[phone] = client

        return jsonify({
            "success": True,
            "message": "Verification code sent."
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message": str(e)
        })


@app.route("/verify_code", methods=["POST"])
def verify_code():

    data = request.get_json()

    phone = data["phone"]
    code = data["code"]

    try:

        client = clients[phone]

        client.sign_in(phone, code)

        me = client.get_me()

        session_string = client.session.save()

        conn = db()

        c = conn.cursor()

        c.execute(
            """
            INSERT INTO users(
            telegram_id,
            username,
            phone,
            session
            )
            VALUES(?,?,?,?)
            """,
            (
                str(me.id),
                me.username,
                phone,
                session_string
            )
        )

        conn.commit()

        conn.close()

        return jsonify({

            "success": True,
            "username": me.username,
            "telegram_id": me.id

        })

    except SessionPasswordNeededError:

        return jsonify({

            "success": False,
            "need_2fa": True

        })

    except PhoneCodeInvalidError:

        return jsonify({

            "success": False,
            "message": "Invalid verification code."

        })

    except Exception as e:

        return jsonify({

            "success": False,
            "message": str(e)

        })

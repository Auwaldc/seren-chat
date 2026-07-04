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

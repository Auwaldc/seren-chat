"""
Seren Chat — backend (app.py)
==============================
Flask API + SQLite database that powers the Seren Chat Mini App (index.html).

This replaces ALL the demo/placeholder data that used to live inside index.html's
JavaScript (targets array, dashData, pendingApprovals, announcements, etc.) with
real data stored in a database, shared by every real user.

HOW TO RUN
----------
1. pip install -r requirements.txt --break-system-packages
2. Copy .env.example to .env and fill in your real values.
3. python app.py
   (Flask will create seren.db automatically on first run.)

WHAT THIS FILE DOES
--------------------
- Serves index.html (the Mini App frontend) at "/"
- Verifies that a request really comes from Telegram (HMAC check on initData)
- Exposes a REST API that index.html calls instead of using hardcoded arrays:
    /api/auth                      -> log a user in (or create them) from Telegram initData
    /api/dashboard                 -> stats for the dashboard cards
    /api/targets            (GET)  -> list a user's targets (groups/DMs)
    /api/targets            (POST) -> add a target (enforces the plan quota)
    /api/targets/<id>        (PUT) -> edit a target
    /api/targets/<id>     (DELETE) -> delete a target
    /api/targets/<id>/toggle(POST) -> turn a target on/off
    /api/subscription               -> current plan + days left for a user
    /api/subscription/submit        -> submit a TON transaction id for review
    /api/announcements               -> list announcements for the bell icon
    /api/announcements/read          -> mark all as read
    /api/admin/stats                 -> total users / active subscribers (admin only)
    /api/admin/pending                -> pending payment approvals (admin only)
    /api/admin/decide                 -> accept/reject a payment (admin only)
    /api/admin/approved                -> list of approved/premium users (admin only)
    /api/admin/revoke                   -> revoke a user's premium (admin only)
    /api/admin/grant                     -> gift premium to a user id (admin only)
    /api/admin/announce                   -> broadcast an announcement (admin only)

Every admin-only route checks that the caller's Telegram ID matches ADMIN_TGID
from your .env file — nobody else can ever see or use them, even if they guess
the URL, because we re-verify the Telegram identity server-side on every call.
"""

import os
import time
import json
import sqlite3
import hmac
import hashlib
from urllib.parse import parse_qsl
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, g, send_from_directory
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_TGID = os.environ.get("ADMIN_TGID", "")  # e.g. "999999999" — @Auwaldc's real Telegram user id
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS", "UQAd3qqKMuMi-cZlMeEmO4NkAzLsvYPsiHYmt7zBdMVTB8Hc")
DB_PATH = os.environ.get("DB_PATH", "seren.db")

PLAN_DAYS = {"1 Week Plan": 7, "2 Week Plan": 14, "1 Month Plan": 30}
PLAN_QUOTA = {"1 Week Plan": 3, "2 Week Plan": 6, "1 Month Plan": 12}
FREE_QUOTA = 1

app = Flask(__name__, static_folder=".", static_url_path="")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            tg_id TEXT PRIMARY KEY,
            username TEXT,
            plan_name TEXT DEFAULT 'Free',
            sub_end_date TEXT,               -- ISO date string, NULL/past = expired
            session_string TEXT,             -- this user's own Telethon session (see userbot.py)
            free_trial_seconds_used INTEGER DEFAULT 0,
            free_trial_week_start TEXT,       -- ISO date the current 7-day free-trial window started
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id TEXT NOT NULL,
            type TEXT NOT NULL,              -- 'group' or 'dm'
            name TEXT NOT NULL,
            is_on INTEGER DEFAULT 1,
            delay_unit TEXT DEFAULT 'S',      -- 'S' seconds / 'M' minutes / 'H' hours
            delay_val INTEGER DEFAULT 30,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tg_id) REFERENCES users(tg_id)
        );

        CREATE TABLE IF NOT EXISTS reply_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id INTEGER NOT NULL,
            message_text TEXT,
            sent_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (target_id) REFERENCES targets(id)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id TEXT NOT NULL,
            name TEXT,
            plan TEXT NOT NULL,
            amount TEXT,
            txid TEXT,
            status TEXT DEFAULT 'pending',    -- pending / approved / rejected
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id TEXT,                       -- NULL = goes to everyone
            title TEXT NOT NULL,
            body TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Telegram identity verification
# ---------------------------------------------------------------------------
def verify_telegram_init_data(init_data: str):
    """
    Validates the initData string Telegram gives the Mini App, per Telegram's
    official Mini Apps auth spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Returns the parsed user dict if valid, or None if the data was tampered
    with / didn't come from Telegram. NEVER trust initDataUnsafe from the
    client directly for anything sensitive (premium, payments, admin) — always
    re-check it here on the server first.
    """
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, received_hash):
            return None
        user_json = parsed.get("user")
        return json.loads(user_json) if user_json else None
    except Exception:
        return None


def get_tg_id_from_request():
    """
    Every real (non-admin-browsing) request should carry the Telegram initData
    so we know for certain who is calling. For simplicity here we accept it
    either as a header or as a query/body field named 'init_data'.
    """
    init_data = request.headers.get("X-Telegram-Init-Data") or request.values.get("init_data")
    user = verify_telegram_init_data(init_data)
    if user and user.get("id"):
        return str(user["id"]), user.get("username")
    return None, None


def is_admin(tg_id: str) -> bool:
    return bool(ADMIN_TGID) and tg_id == ADMIN_TGID


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------
def get_or_create_user(tg_id, username):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO users (tg_id, username, plan_name, sub_end_date) VALUES (?, ?, 'Free', NULL)",
            (tg_id, username or f"user_{tg_id}"),
        )
        db.commit()
        row = db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    elif username and row["username"] != username:
        db.execute("UPDATE users SET username = ? WHERE tg_id = ?", (username, tg_id))
        db.commit()
    return row


def days_left(sub_end_date):
    if not sub_end_date:
        return 0
    try:
        end = datetime.fromisoformat(sub_end_date)
    except ValueError:
        return 0
    delta = (end.date() - datetime.utcnow().date()).days
    return max(0, delta)


def is_premium_active(user_row) -> bool:
    return days_left(user_row["sub_end_date"]) > 0


def max_targets_for(user_row) -> int:
    if not is_premium_active(user_row):
        return FREE_QUOTA
    return PLAN_QUOTA.get(user_row["plan_name"], FREE_QUOTA)


def activate_plan(tg_id, plan_name):
    db = get_db()
    end_date = (datetime.utcnow() + timedelta(days=PLAN_DAYS.get(plan_name, 30))).date().isoformat()
    db.execute(
        "UPDATE users SET plan_name = ?, sub_end_date = ? WHERE tg_id = ?",
        (plan_name, end_date, tg_id),
    )
    db.commit()


def expire_plan_now(tg_id):
    db = get_db()
    yesterday = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
    db.execute("UPDATE users SET sub_end_date = ? WHERE tg_id = ?", (yesterday, tg_id))
    db.commit()
    # Real rule: the moment premium ends, every target for this user must stop.
    db.execute("UPDATE targets SET is_on = 0 WHERE tg_id = ?", (tg_id,))
    db.commit()


def push_announcement(tg_id, title, body):
    """tg_id=None means broadcast to everyone."""
    db = get_db()
    db.execute(
        "INSERT INTO announcements (tg_id, title, body, is_read) VALUES (?, ?, ?, 0)",
        (tg_id, title, body),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.route("/")
def serve_index():
    return send_from_directory(".", "index.html")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.route("/api/auth", methods=["POST"])
def auth():
    init_data = request.json.get("init_data", "") if request.is_json else request.form.get("init_data", "")
    user = verify_telegram_init_data(init_data)
    if not user or not user.get("id"):
        return jsonify({"error": "invalid_telegram_data"}), 401

    tg_id = str(user["id"])
    username = ("@" + user["username"]) if user.get("username") else user.get("first_name", "Telegram user")
    row = get_or_create_user(tg_id, username)

    return jsonify({
        "tg_id": tg_id,
        "username": row["username"],
        "plan_name": row["plan_name"],
        "days_left": days_left(row["sub_end_date"]),
        "is_premium": is_premium_active(row),
        "is_admin": is_admin(tg_id),
    })


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/api/dashboard")
def dashboard():
    tg_id, _ = get_tg_id_from_request()
    if not tg_id:
        return jsonify({"error": "unauthorized"}), 401
    mode = request.args.get("mode", "groups")  # 'groups' or 'dm'
    ttype = "group" if mode == "groups" else "dm"
    db = get_db()

    active_targets = db.execute(
        "SELECT COUNT(*) c FROM targets WHERE tg_id=? AND type=?", (tg_id, ttype)
    ).fetchone()["c"]

    active_accounts = 1  # one Telegram account per user in this design

    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    replies_today = db.execute(
        """SELECT COUNT(*) c FROM reply_log rl
           JOIN targets t ON t.id = rl.target_id
           WHERE t.tg_id=? AND t.type=? AND rl.sent_at >= ?""",
        (tg_id, ttype, one_hour_ago),
    ).fetchone()["c"]

    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    replies_week = db.execute(
        """SELECT COUNT(*) c FROM reply_log rl
           JOIN targets t ON t.id = rl.target_id
           WHERE t.tg_id=? AND t.type=? AND rl.sent_at >= ?""",
        (tg_id, ttype, week_ago),
    ).fetchone()["c"]

    total_replies = db.execute(
        """SELECT COUNT(*) c FROM reply_log rl
           JOIN targets t ON t.id = rl.target_id
           WHERE t.tg_id=? AND t.type=?""",
        (tg_id, ttype),
    ).fetchone()["c"]

    return jsonify({
        "active_targets": active_targets,
        "active_accounts": active_accounts,
        "replies_today": replies_today,
        "replies_week": replies_week,
        "total_replies": total_replies,
    })


# ---------------------------------------------------------------------------
# Targets (Add / Edit / Delete / Toggle)
# ---------------------------------------------------------------------------
@app.route("/api/targets", methods=["GET", "POST"])
def targets_collection():
    tg_id, _ = get_tg_id_from_request()
    if not tg_id:
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()

    if request.method == "GET":
        ttype = request.args.get("type", "group")
        rows = db.execute(
            "SELECT * FROM targets WHERE tg_id=? AND type=? ORDER BY id", (tg_id, ttype)
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    # POST -> add a new target, enforcing the real plan quota server-side
    data = request.get_json(force=True)
    user_row = get_or_create_user(tg_id, None)
    limit = max_targets_for(user_row)
    current_count = db.execute(
        "SELECT COUNT(*) c FROM targets WHERE tg_id=?", (tg_id,)
    ).fetchone()["c"]
    if current_count >= limit:
        return jsonify({"error": "quota_exceeded", "limit": limit}), 403

    db.execute(
        """INSERT INTO targets (tg_id, type, name, is_on, delay_unit, delay_val)
           VALUES (?, ?, ?, 1, ?, ?)""",
        (tg_id, data["type"], data["name"], data.get("delay_unit", "S"), data.get("delay_val", 30)),
    )
    db.commit()
    return jsonify({"ok": True}), 201


@app.route("/api/targets/<int:target_id>", methods=["PUT", "DELETE"])
def target_item(target_id):
    tg_id, _ = get_tg_id_from_request()
    if not tg_id:
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()

    owner = db.execute("SELECT tg_id FROM targets WHERE id=?", (target_id,)).fetchone()
    if not owner or owner["tg_id"] != tg_id:
        return jsonify({"error": "not_found"}), 404

    if request.method == "DELETE":
        db.execute("DELETE FROM targets WHERE id=?", (target_id,))
        db.commit()
        return jsonify({"ok": True})

    data = request.get_json(force=True)
    db.execute(
        "UPDATE targets SET name=?, delay_unit=?, delay_val=? WHERE id=?",
        (data["name"], data.get("delay_unit", "S"), data.get("delay_val", 30), target_id),
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/targets/<int:target_id>/toggle", methods=["POST"])
def toggle_target(target_id):
    tg_id, _ = get_tg_id_from_request()
    if not tg_id:
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()

    user_row = get_or_create_user(tg_id, None)
    if not is_premium_active(user_row):
        return jsonify({"error": "premium_required"}), 403

    row = db.execute("SELECT * FROM targets WHERE id=? AND tg_id=?", (target_id, tg_id)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    new_state = 0 if row["is_on"] else 1
    db.execute("UPDATE targets SET is_on=? WHERE id=?", (new_state, target_id))
    db.commit()
    return jsonify({"ok": True, "is_on": bool(new_state)})


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------
@app.route("/api/subscription")
def subscription():
    tg_id, _ = get_tg_id_from_request()
    if not tg_id:
        return jsonify({"error": "unauthorized"}), 401
    row = get_or_create_user(tg_id, None)
    return jsonify({
        "plan_name": row["plan_name"],
        "days_left": days_left(row["sub_end_date"]),
        "is_premium": is_premium_active(row),
        "end_date": row["sub_end_date"],
        "max_targets": max_targets_for(row),
        "wallet_address": WALLET_ADDRESS,
    })


@app.route("/api/subscription/submit", methods=["POST"])
def submit_payment():
    tg_id, username = get_tg_id_from_request()
    if not tg_id:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(force=True)
    plan = data["plan"]           # e.g. "1 Month Plan"
    amount = data.get("amount", "")
    txid = data["txid"]

    db = get_db()
    row = get_or_create_user(tg_id, username)
    db.execute(
        "INSERT INTO payments (tg_id, name, plan, amount, txid, status) VALUES (?, ?, ?, ?, ?, 'pending')",
        (tg_id, row["username"], plan, amount, txid),
    )
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Announcements (bell icon)
# ---------------------------------------------------------------------------
@app.route("/api/announcements")
def announcements():
    tg_id, _ = get_tg_id_from_request()
    if not tg_id:
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    rows = db.execute(
        """SELECT * FROM announcements WHERE tg_id IS NULL OR tg_id=?
           ORDER BY id DESC LIMIT 50""",
        (tg_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/announcements/read", methods=["POST"])
def mark_announcements_read():
    tg_id, _ = get_tg_id_from_request()
    if not tg_id:
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    db.execute("UPDATE announcements SET is_read=1 WHERE tg_id IS NULL OR tg_id=?", (tg_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/link-session", methods=["POST"])
def link_session():
    """
    Called once, right after a customer finishes the separate login step
    (see login_telegram.py) that generates their personal Telethon session
    string. Storing it here is what lets userbot.py act on their behalf.
    A user can only ever set their OWN session — enforced by verifying
    initData belongs to the same tg_id being updated.
    """
    tg_id, _ = get_tg_id_from_request()
    if not tg_id:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(force=True)
    db = get_db()
    get_or_create_user(tg_id, None)
    db.execute("UPDATE users SET session_string=? WHERE tg_id=?", (data["session_string"], tg_id))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Admin — every route re-checks is_admin() server-side, every time.
# ---------------------------------------------------------------------------
@app.route("/api/admin/stats")
def admin_stats():
    tg_id, _ = get_tg_id_from_request()
    if not is_admin(tg_id):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    total_users = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    active_subs = db.execute(
        "SELECT COUNT(*) c FROM users WHERE sub_end_date IS NOT NULL AND date(sub_end_date) >= date('now')"
    ).fetchone()["c"]
    return jsonify({"total_users": total_users, "active_subscribers": active_subs})


@app.route("/api/admin/pending")
def admin_pending():
    tg_id, _ = get_tg_id_from_request()
    if not is_admin(tg_id):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    rows = db.execute("SELECT * FROM payments WHERE status='pending' ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/decide", methods=["POST"])
def admin_decide():
    tg_id, _ = get_tg_id_from_request()
    if not is_admin(tg_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(force=True)
    payment_id = data["payment_id"]
    accepted = bool(data["accepted"])

    db = get_db()
    payment = db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    if not payment:
        return jsonify({"error": "not_found"}), 404

    db.execute(
        "UPDATE payments SET status=? WHERE id=?",
        ("approved" if accepted else "rejected", payment_id),
    )
    db.commit()

    if accepted:
        activate_plan(payment["tg_id"], payment["plan"])
        push_announcement(payment["tg_id"], "Payment approved ✅",
                           f"Your {payment['plan']} payment was approved — your premium is now active.")
    else:
        push_announcement(payment["tg_id"], "Payment rejected ❌",
                           f"Your {payment['plan']} payment could not be verified. Please contact support.")

    return jsonify({"ok": True})


@app.route("/api/admin/approved")
def admin_approved():
    tg_id, _ = get_tg_id_from_request()
    if not is_admin(tg_id):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    rows = db.execute(
        "SELECT tg_id, username, plan_name, sub_end_date FROM users "
        "WHERE sub_end_date IS NOT NULL AND date(sub_end_date) >= date('now')"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/revoke", methods=["POST"])
def admin_revoke():
    tg_id, _ = get_tg_id_from_request()
    if not is_admin(tg_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(force=True)
    target_tg_id = data["tg_id"]
    expire_plan_now(target_tg_id)
    push_announcement(target_tg_id, "Premium revoked",
                       "Your premium was revoked by an admin. Seren has stopped replying in all your "
                       "groups and DMs. Contact support if you believe this is a mistake, or renew your plan.")
    return jsonify({"ok": True})


@app.route("/api/admin/grant", methods=["POST"])
def admin_grant():
    tg_id, _ = get_tg_id_from_request()
    if not is_admin(tg_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(force=True)
    target_tg_id = data["tg_id"]
    plan = data["plan"]  # "1 Week Plan" / "2 Week Plan" / "1 Month Plan"

    get_or_create_user(target_tg_id, None)
    activate_plan(target_tg_id, plan)
    push_announcement(target_tg_id, "Premium gifted 🎁",
                       f"An admin gave you a free {plan}. Your premium is now active.")
    return jsonify({"ok": True})


@app.route("/api/admin/announce", methods=["POST"])
def admin_announce():
    tg_id, _ = get_tg_id_from_request()
    if not is_admin(tg_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(force=True)
    push_announcement(None, data["title"], data.get("body", ""))
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)

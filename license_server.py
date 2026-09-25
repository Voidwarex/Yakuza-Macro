"""
Yakuza Solutions license server.

Holds the account + license key database and answers the macro
client's login / register / redeem / status requests.

Run the server:
    python license_server.py serve --host 0.0.0.0 --port 8000

Generate keys to sell:
    python license_server.py genkeys day 10
    python license_server.py genkeys week 5
    python license_server.py genkeys month 1

Other admin commands:
    python license_server.py listkeys [--unused]
    python license_server.py listusers
    python license_server.py resethwid <username>
    python license_server.py addtime <username> <days>
    python license_server.py deleteuser <username>
"""

import argparse
import os
import re
import secrets
import sqlite3
import sys
import time

from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash


# =========================================================
# CONFIGURATION
# =========================================================

DB_PATH = os.environ.get(
    "YAKUZA_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "licenses.db")
)

KEY_TYPES = {
    "day": 1,
    "week": 7,
    "month": 30,
}

SESSION_TTL_SECONDS = 30 * 24 * 60 * 60

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,24}$")

KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# =========================================================
# DATABASE
# =========================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    hwid          TEXT,
    expires_at    INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS license_keys (
    key           TEXT    PRIMARY KEY,
    key_type      TEXT    NOT NULL,
    duration_days INTEGER NOT NULL,
    created_at    INTEGER NOT NULL,
    redeemed_by   INTEGER REFERENCES users(id),
    redeemed_at   INTEGER
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
"""


def get_db():

    conn = sqlite3.connect(DB_PATH, timeout=10)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def init_db():

    with get_db() as conn:
        conn.executescript(SCHEMA)


def now():

    return int(time.time())


def generate_key(key_type):

    groups = [
        "".join(secrets.choice(KEY_ALPHABET) for _ in range(4))
        for _ in range(4)
    ]

    return key_type.upper() + "-" + "-".join(groups)


def create_session(conn, user_id):

    token = secrets.token_urlsafe(32)

    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, now() + SESSION_TTL_SECONDS)
    )

    return token


def user_from_token(conn, token):

    if not token:
        return None

    return conn.execute(
        """
        SELECT users.* FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ? AND sessions.expires_at > ?
        """,
        (token, now())
    ).fetchone()


def license_payload(user):

    return {
        "username": user["username"],
        "expires_at": user["expires_at"],
        "remaining_seconds": max(0, user["expires_at"] - now()),
    }


# =========================================================
# HTTP API
# =========================================================

app = Flask(__name__)


def error(message, status=400):

    return jsonify({"ok": False, "error": message}), status


def read_json():

    data = request.get_json(silent=True)

    return data if isinstance(data, dict) else {}


@app.route("/api/register", methods=["POST"])
def register():

    data = read_json()

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    hwid = str(data.get("hwid", "")).strip()


    if not USERNAME_RE.match(username):
        return error("Username must be 3-24 letters, numbers or underscores.")

    if len(password) < 6:
        return error("Password must be at least 6 characters.")

    if not hwid:
        return error("Missing hardware ID.")


    with get_db() as conn:

        try:

            cur = conn.execute(
                """
                INSERT INTO users (username, password_hash, hwid, expires_at, created_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (username, generate_password_hash(password), hwid, now())
            )

        except sqlite3.IntegrityError:

            return error("That username is already taken.", 409)


        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (cur.lastrowid,)
        ).fetchone()

        token = create_session(conn, user["id"])


    return jsonify({"ok": True, "token": token, **license_payload(user)})


@app.route("/api/login", methods=["POST"])
def login():

    data = read_json()

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    hwid = str(data.get("hwid", "")).strip()


    if not hwid:
        return error("Missing hardware ID.")


    with get_db() as conn:

        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


        if user is None or not check_password_hash(user["password_hash"], password):
            return error("Invalid username or password.", 401)


        # Lock each account to the first machine it logs in from.
        if not user["hwid"]:

            conn.execute(
                "UPDATE users SET hwid = ? WHERE id = ?", (hwid, user["id"])
            )

        elif user["hwid"] != hwid:

            return error("This account is locked to a different PC. Contact support for an HWID reset.", 403)


        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now(),))

        token = create_session(conn, user["id"])


    return jsonify({"ok": True, "token": token, **license_payload(user)})


@app.route("/api/status", methods=["POST"])
def status():

    data = read_json()


    with get_db() as conn:

        user = user_from_token(conn, data.get("token"))

        if user is None:
            return error("Session expired. Please log in again.", 401)

        if user["hwid"] != str(data.get("hwid", "")).strip():
            return error("Hardware ID mismatch.", 403)


    return jsonify({"ok": True, **license_payload(user)})


@app.route("/api/logout", methods=["POST"])
def logout():

    data = read_json()

    with get_db() as conn:

        conn.execute(
            "DELETE FROM sessions WHERE token = ?", (str(data.get("token", "")),)
        )

    return jsonify({"ok": True})


@app.route("/api/redeem", methods=["POST"])
def redeem():

    data = read_json()

    key = str(data.get("key", "")).strip().upper()


    with get_db() as conn:

        user = user_from_token(conn, data.get("token"))

        if user is None:
            return error("Session expired. Please log in again.", 401)

        if user["hwid"] != str(data.get("hwid", "")).strip():
            return error("Hardware ID mismatch.", 403)


        # Claim the key atomically so it can only ever be used once.
        claimed = conn.execute(
            """
            UPDATE license_keys SET redeemed_by = ?, redeemed_at = ?
            WHERE key = ? AND redeemed_by IS NULL
            """,
            (user["id"], now(), key)
        )

        if claimed.rowcount != 1:
            return error("Invalid or already used key.")


        duration_days = conn.execute(
            "SELECT duration_days FROM license_keys WHERE key = ?", (key,)
        ).fetchone()["duration_days"]


        # Stack on top of any time still remaining.
        new_expiry = max(now(), user["expires_at"]) + duration_days * 86400

        conn.execute(
            "UPDATE users SET expires_at = ? WHERE id = ?", (new_expiry, user["id"])
        )

        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user["id"],)
        ).fetchone()


    return jsonify({
        "ok": True,
        "added_days": duration_days,
        **license_payload(user),
    })


# =========================================================
# ADMIN CLI
# =========================================================

def format_remaining(expires_at):

    remaining = expires_at - now()

    if remaining <= 0:
        return "expired"

    days, rem = divmod(remaining, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60

    return f"{days}d {hours}h {minutes}m"


def cmd_serve(args):

    init_db()

    print(f"License server listening on http://{args.host}:{args.port}")
    print(f"Database: {DB_PATH}")

    try:

        from waitress import serve

    except ImportError:

        print("waitress not installed; using Flask's development server.")

        app.run(host=args.host, port=args.port, debug=False)

        return


    serve(app, host=args.host, port=args.port)


def cmd_genkeys(args):

    init_db()

    days = KEY_TYPES[args.type]

    with get_db() as conn:

        for _ in range(args.count):

            key = generate_key(args.type)

            conn.execute(
                """
                INSERT INTO license_keys (key, key_type, duration_days, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, args.type, days, now())
            )

            print(key)


def cmd_listkeys(args):

    init_db()

    query = """
        SELECT license_keys.*, users.username FROM license_keys
        LEFT JOIN users ON users.id = license_keys.redeemed_by
    """

    if args.unused:
        query += " WHERE license_keys.redeemed_by IS NULL"

    query += " ORDER BY license_keys.created_at"


    with get_db() as conn:

        for row in conn.execute(query):

            used = f"used by {row['username']}" if row["redeemed_by"] else "unused"

            print(f"{row['key']}  {row['key_type']:<5}  {used}")


def cmd_listusers(args):

    init_db()

    with get_db() as conn:

        for row in conn.execute("SELECT * FROM users ORDER BY created_at"):

            print(
                f"{row['username']:<24}  "
                f"{format_remaining(row['expires_at']):<14}  "
                f"hwid={row['hwid'] or '-'}"
            )


def find_user(conn, username):

    user = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()

    if user is None:
        sys.exit(f"No user named {username!r}.")

    return user


def cmd_resethwid(args):

    init_db()

    with get_db() as conn:

        user = find_user(conn, args.username)

        conn.execute("UPDATE users SET hwid = NULL WHERE id = ?", (user["id"],))

        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))

    print(f"HWID cleared for {user['username']}. They can log in from a new PC.")


def cmd_addtime(args):

    init_db()

    with get_db() as conn:

        user = find_user(conn, args.username)

        new_expiry = max(now(), user["expires_at"]) + int(args.days * 86400)

        conn.execute(
            "UPDATE users SET expires_at = ? WHERE id = ?", (new_expiry, user["id"])
        )

    print(f"{user['username']} now has {format_remaining(new_expiry)} remaining.")


def cmd_deleteuser(args):

    init_db()

    with get_db() as conn:

        user = find_user(conn, args.username)

        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))

        conn.execute(
            "UPDATE license_keys SET redeemed_by = NULL WHERE redeemed_by = ?",
            (user["id"],)
        )

        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))

    print(f"Deleted {user['username']}.")


def main():

    parser = argparse.ArgumentParser(description="Yakuza Solutions license server")

    sub = parser.add_subparsers(dest="command", required=True)


    p = sub.add_parser("serve", help="run the license server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("genkeys", help="generate license keys")
    p.add_argument("type", choices=sorted(KEY_TYPES))
    p.add_argument("count", type=int, nargs="?", default=1)
    p.set_defaults(func=cmd_genkeys)

    p = sub.add_parser("listkeys", help="list license keys")
    p.add_argument("--unused", action="store_true")
    p.set_defaults(func=cmd_listkeys)

    p = sub.add_parser("listusers", help="list accounts")
    p.set_defaults(func=cmd_listusers)

    p = sub.add_parser("resethwid", help="unlock an account from its PC")
    p.add_argument("username")
    p.set_defaults(func=cmd_resethwid)

    p = sub.add_parser("addtime", help="give an account extra days")
    p.add_argument("username")
    p.add_argument("days", type=float)
    p.set_defaults(func=cmd_addtime)

    p = sub.add_parser("deleteuser", help="delete an account")
    p.add_argument("username")
    p.set_defaults(func=cmd_deleteuser)


    args = parser.parse_args()

    args.func(args)


if __name__ == "__main__":
    main()

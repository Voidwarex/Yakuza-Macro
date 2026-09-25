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
    python license_server.py ban <username> / unban <username>

Approved app builds (see "Build check" in the README):
    python license_server.py approvebuild test.py [--label v1.2]
    python license_server.py approvebuild <sha256-hash>
    python license_server.py listbuilds
    python license_server.py revokebuild <sha256-hash>

Admin accounts (see the Admin Panel in the app):
    python license_server.py createadmin admin
    python license_server.py setadmin <username> [--off]
"""

import argparse
import getpass
import hashlib
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

# Names nobody can register from the app. Create these with
# the createadmin command on the server instead.
RESERVED_USERNAMES = {"admin", "administrator", "root", "support"}

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

CREATE TABLE IF NOT EXISTS approved_builds (
    hash       TEXT    PRIMARY KEY,
    label      TEXT,
    created_at INTEGER NOT NULL
);
"""


def get_db():

    conn = sqlite3.connect(DB_PATH, timeout=10)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")

    return conn


# Columns added after the first release. init_db adds any that an
# existing database is missing, so upgrading keeps all data.
MIGRATIONS = {
    "users": {
        "is_admin": "INTEGER NOT NULL DEFAULT 0",
        "banned": "INTEGER NOT NULL DEFAULT 0",
        "last_login": "INTEGER",
    },
}


def init_db():

    with get_db() as conn:

        conn.executescript(SCHEMA)

        for table, columns in MIGRATIONS.items():

            existing = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
            }

            for name, definition in columns.items():

                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


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
        "is_admin": bool(user["is_admin"]),
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


BANNED_MESSAGE = "This account has been banned."

MODIFIED_MESSAGE = (
    "This copy of the app has been modified or is out of date. "
    "Download the official version to continue."
)


def build_approved(conn, data):

    # With no approved builds the check is off, so a fresh server
    # doesn't lock everyone out before approvebuild has been run.
    if conn.execute("SELECT 1 FROM approved_builds LIMIT 1").fetchone() is None:
        return True

    app_hash = str(data.get("app_hash", "")).strip().lower()

    return conn.execute(
        "SELECT 1 FROM approved_builds WHERE hash = ?", (app_hash,)
    ).fetchone() is not None


def build_error():

    return jsonify({"error": MODIFIED_MESSAGE, "modified": True}), 403


def session_user(conn, data):

    # Returns (user, None) for a valid session on the matching
    # PC, or (None, error_response) otherwise.
    user = user_from_token(conn, data.get("token"))

    if user is None:
        return None, error("Session expired. Please log in again.", 401)

    if user["banned"]:
        return None, error(BANNED_MESSAGE, 403)

    if not build_approved(conn, data):
        return None, build_error()

    if user["hwid"] != str(data.get("hwid", "")).strip():
        return None, error("Hardware ID mismatch.", 403)

    return user, None


@app.route("/api/register", methods=["POST"])
def register():

    data = read_json()

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    hwid = str(data.get("hwid", "")).strip()


    if not USERNAME_RE.match(username):
        return error("Username must be 3-24 letters, numbers or underscores.")

    if username.lower() in RESERVED_USERNAMES:
        return error("That username is already taken.", 409)

    if len(password) < 6:
        return error("Password must be at least 6 characters.")

    if not hwid:
        return error("Missing hardware ID.")


    with get_db() as conn:

        if not build_approved(conn, data):
            return build_error()

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

        if not build_approved(conn, data):
            return build_error()

        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


        if user is None or not check_password_hash(user["password_hash"], password):
            return error("Invalid username or password.", 401)


        if user["banned"]:
            return error(BANNED_MESSAGE, 403)


        # Lock each account to the first machine it logs in from.
        if not user["hwid"]:

            conn.execute(
                "UPDATE users SET hwid = ? WHERE id = ?", (hwid, user["id"])
            )

        elif user["hwid"] != hwid:

            return error("This account is locked to a different PC. Contact support for an HWID reset.", 403)


        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now(),))

        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?", (now(), user["id"])
        )

        token = create_session(conn, user["id"])


    return jsonify({"ok": True, "token": token, **license_payload(user)})


@app.route("/api/integrity", methods=["POST"])
def integrity():

    # Checked by the app when it opens, before anyone logs in.
    with get_db() as conn:

        if not build_approved(conn, read_json()):
            return build_error()

    return jsonify({"ok": True})


@app.route("/api/status", methods=["POST"])
def status():

    data = read_json()


    with get_db() as conn:

        user, err = session_user(conn, data)

        if err:
            return err


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

        user, err = session_user(conn, data)

        if err:
            return err


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
# ADMIN API
# =========================================================

def admin_route(path):

    # Registers an admin-only endpoint. The handler receives
    # (conn, admin_user, data) and every request is checked here
    # on the server, so the app's menu grants no power by itself.
    def decorator(handler):

        def wrapper():

            data = read_json()

            with get_db() as conn:

                user, err = session_user(conn, data)

                if err:
                    return err

                if not user["is_admin"]:
                    return error("Admin access required.", 403)

                return handler(conn, user, data)


        wrapper.__name__ = "admin_" + handler.__name__

        return app.route("/api/admin/" + path, methods=["POST"])(wrapper)

    return decorator


def target_user(conn, data):

    user = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        (str(data.get("username", "")).strip(),)
    ).fetchone()

    if user is None:
        return None, error("No such user.", 404)

    return user, None


def admin_user_row(row):

    t = now()

    return {
        "username": row["username"],
        "hwid": row["hwid"],
        "expires_at": row["expires_at"],
        "remaining_seconds": max(0, row["expires_at"] - t),
        "is_admin": bool(row["is_admin"]),
        "banned": bool(row["banned"]),
        "created_at": row["created_at"],
        "last_login": row["last_login"],
        "keys_redeemed": row["keys_redeemed"],
        "online": bool(row["active_sessions"]),
    }


@admin_route("overview")
def overview(conn, admin, data):

    t = now()

    users = conn.execute(
        """
        SELECT users.*,
            (SELECT COUNT(*) FROM license_keys k WHERE k.redeemed_by = users.id) AS keys_redeemed,
            (SELECT COUNT(*) FROM sessions s WHERE s.user_id = users.id AND s.expires_at > ?) AS active_sessions
        FROM users
        ORDER BY users.created_at DESC
        """,
        (t,)
    ).fetchall()


    keys = conn.execute(
        """
        SELECT license_keys.*, users.username FROM license_keys
        LEFT JOIN users ON users.id = license_keys.redeemed_by
        ORDER BY license_keys.created_at DESC
        """
    ).fetchall()


    unused = {k: 0 for k in KEY_TYPES}

    for key in keys:

        if key["redeemed_by"] is None and key["key_type"] in unused:
            unused[key["key_type"]] += 1


    return jsonify({
        "ok": True,

        "stats": {
            "users": len(users),
            "active_licenses": sum(1 for u in users if u["expires_at"] > t and not u["banned"]),
            "banned": sum(1 for u in users if u["banned"]),
            "keys_total": len(keys),
            "keys_unused": unused,
        },

        "users": [admin_user_row(u) for u in users],

        "keys": [
            {
                "key": k["key"],
                "key_type": k["key_type"],
                "duration_days": k["duration_days"],
                "created_at": k["created_at"],
                "redeemed_by": k["username"],
                "redeemed_at": k["redeemed_at"],
            }
            for k in keys
        ],
    })


@admin_route("addtime")
def admin_addtime(conn, admin, data):

    user, err = target_user(conn, data)

    if err:
        return err


    try:
        seconds = int(float(data.get("days", 0)) * 86400)
    except (TypeError, ValueError):
        return error("Enter a number of days, e.g. 7 or -1.")


    # Adding starts from now if the license has run out; taking
    # time away never goes below zero.
    t = now()

    new_expiry = max(t, max(t, user["expires_at"]) + seconds)

    conn.execute(
        "UPDATE users SET expires_at = ? WHERE id = ?", (new_expiry, user["id"])
    )

    return jsonify({"ok": True, "remaining_seconds": new_expiry - t})


@admin_route("settime")
def admin_settime(conn, admin, data):

    user, err = target_user(conn, data)

    if err:
        return err


    try:
        seconds = max(0, int(float(data.get("days", 0)) * 86400))
    except (TypeError, ValueError):
        return error("Enter a number of days, e.g. 30 or 0.")


    conn.execute(
        "UPDATE users SET expires_at = ? WHERE id = ?", (now() + seconds, user["id"])
    )

    return jsonify({"ok": True, "remaining_seconds": seconds})


@admin_route("ban")
def admin_ban(conn, admin, data):

    user, err = target_user(conn, data)

    if err:
        return err


    banned = bool(data.get("banned", True))

    if banned and user["is_admin"]:
        return error("Admin accounts can't be banned.")


    conn.execute(
        "UPDATE users SET banned = ? WHERE id = ?", (int(banned), user["id"])
    )

    if banned:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))


    return jsonify({"ok": True, "banned": banned})


@admin_route("resethwid")
def admin_resethwid(conn, admin, data):

    user, err = target_user(conn, data)

    if err:
        return err


    if user["id"] == admin["id"]:
        return error("You can't reset your own HWID while logged in.")


    conn.execute("UPDATE users SET hwid = NULL WHERE id = ?", (user["id"],))

    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))

    return jsonify({"ok": True})


@admin_route("genkeys")
def admin_genkeys(conn, admin, data):

    key_type = str(data.get("key_type", ""))

    if key_type not in KEY_TYPES:
        return error("Pick day, week or month.")


    try:
        count = int(data.get("count", 1))
    except (TypeError, ValueError):
        count = 0

    if not 1 <= count <= 100:
        return error("Generate between 1 and 100 keys at a time.")


    keys = []

    for _ in range(count):

        key = generate_key(key_type)

        conn.execute(
            """
            INSERT INTO license_keys (key, key_type, duration_days, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, key_type, KEY_TYPES[key_type], now())
        )

        keys.append(key)


    return jsonify({"ok": True, "keys": keys})


@admin_route("deletekey")
def admin_deletekey(conn, admin, data):

    deleted = conn.execute(
        "DELETE FROM license_keys WHERE key = ? AND redeemed_by IS NULL",
        (str(data.get("key", "")).strip().upper(),)
    )

    if deleted.rowcount != 1:
        return error("Only unused keys can be deleted.")

    return jsonify({"ok": True})


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

            flags = " ".join(
                name for name, on in (("ADMIN", row["is_admin"]), ("BANNED", row["banned"])) if on
            )

            print(
                f"{row['username']:<24}  "
                f"{format_remaining(row['expires_at']):<14}  "
                f"hwid={row['hwid'] or '-'}  {flags}"
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


def cmd_createadmin(args):

    init_db()

    password = getpass.getpass(f"Password for {args.username}: ")

    if len(password) < 6:
        sys.exit("Password must be at least 6 characters.")

    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords don't match.")


    with get_db() as conn:

        try:

            conn.execute(
                """
                INSERT INTO users (username, password_hash, hwid, expires_at, created_at, is_admin)
                VALUES (?, ?, NULL, 0, ?, 1)
                """,
                (args.username, generate_password_hash(password), now())
            )

        except sqlite3.IntegrityError:

            sys.exit(f"{args.username!r} already exists. Use setadmin to promote it.")


    print(f"Admin account {args.username} created. It locks to the first PC it logs in from.")


def cmd_setadmin(args):

    init_db()

    with get_db() as conn:

        user = find_user(conn, args.username)

        conn.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?", (0 if args.off else 1, user["id"])
        )

    print(f"{user['username']} is {'no longer' if args.off else 'now'} an admin.")


def cmd_ban(args):

    init_db()

    with get_db() as conn:

        user = find_user(conn, args.username)

        conn.execute(
            "UPDATE users SET banned = ? WHERE id = ?", (int(args.banned), user["id"])
        )

        if args.banned:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))

    print(f"{user['username']} {'banned' if args.banned else 'unbanned'}.")


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


def file_hash(path):

    # Must match app_hash() in test.py: scripts are hashed with
    # LF line endings so a Windows CRLF checkout gets the same hash.
    with open(path, "rb") as f:
        content = f.read()

    if path.lower().endswith(".py"):
        content = content.replace(b"\r\n", b"\n")

    return hashlib.sha256(content).hexdigest()


HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def cmd_approvebuild(args):

    init_db()

    target = args.target.strip()

    if HASH_RE.match(target.lower()):
        build_hash = target.lower()
    elif os.path.isfile(target):
        build_hash = file_hash(target)
    else:
        sys.exit(f"{target!r} is not a file or a SHA-256 hash.")


    with get_db() as conn:

        conn.execute(
            "INSERT OR REPLACE INTO approved_builds (hash, label, created_at) VALUES (?, ?, ?)",
            (build_hash, args.label, now())
        )

    print(f"Approved build {build_hash}" + (f" ({args.label})" if args.label else ""))


def cmd_listbuilds(args):

    init_db()

    with get_db() as conn:

        rows = conn.execute(
            "SELECT * FROM approved_builds ORDER BY created_at"
        ).fetchall()


    if not rows:
        print("No approved builds; the build check is off.")
        return

    for row in rows:
        print(f"{row['hash']}  {row['label'] or ''}")


def cmd_revokebuild(args):

    init_db()

    with get_db() as conn:

        deleted = conn.execute(
            "DELETE FROM approved_builds WHERE hash = ?", (args.hash.strip().lower(),)
        )

    if deleted.rowcount != 1:
        sys.exit("No approved build with that hash.")

    print("Build revoked.")


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

    p = sub.add_parser("createadmin", help="create an admin account")
    p.add_argument("username")
    p.set_defaults(func=cmd_createadmin)

    p = sub.add_parser("setadmin", help="give or remove admin rights")
    p.add_argument("username")
    p.add_argument("--off", action="store_true")
    p.set_defaults(func=cmd_setadmin)

    p = sub.add_parser("ban", help="ban an account")
    p.add_argument("username")
    p.set_defaults(func=cmd_ban, banned=True)

    p = sub.add_parser("unban", help="unban an account")
    p.add_argument("username")
    p.set_defaults(func=cmd_ban, banned=False)

    p = sub.add_parser("deleteuser", help="delete an account")
    p.add_argument("username")
    p.set_defaults(func=cmd_deleteuser)


    p = sub.add_parser("approvebuild", help="allow an app build to log in")
    p.add_argument("target", help="path to the app file, or its SHA-256 hash")
    p.add_argument("--label", help="note to remember the build by, e.g. v1.2")
    p.set_defaults(func=cmd_approvebuild)

    p = sub.add_parser("listbuilds", help="list approved app builds")
    p.set_defaults(func=cmd_listbuilds)

    p = sub.add_parser("revokebuild", help="stop an app build from logging in")
    p.add_argument("hash")
    p.set_defaults(func=cmd_revokebuild)


    args = parser.parse_args()

    args.func(args)


if __name__ == "__main__":
    main()

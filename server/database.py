"""
SQLite data layer for the Remote Power relay (multi-account edition).

Tables
------
users     : one row per account (email, hashed password, plan, Stripe ids)
devices   : one row per enrolled PC, owned by a user
commands  : queued actions for a device (shutdown / restart / lock / cancel)

The database is a single file (DB_PATH, default power.db).
"""

import os
import sqlite3
import time

import plans

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "power.db"))

# Actions the panel is allowed to queue.
VALID_ACTIONS = ("shutdown", "restart", "lock", "cancel")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if they do not exist. Safe to call on every boot."""
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                email                TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash        TEXT NOT NULL,
                plan                 TEXT NOT NULL DEFAULT 'free',
                is_admin             INTEGER NOT NULL DEFAULT 0,
                created_at           REAL NOT NULL,
                stripe_customer_id   TEXT,
                stripe_subscription_id TEXT,
                plan_renews_at       REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                name        TEXT NOT NULL,
                key_hash    TEXT NOT NULL,
                created_at  REAL NOT NULL,
                last_seen   REAL,
                last_ip     TEXT,
                os_info     TEXT,
                kind        TEXT NOT NULL DEFAULT 'desktop',
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
            """
        )
        # Migration: add 'kind' to databases created before it existed.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(devices)")}
        if "kind" not in cols:
            conn.execute(
                "ALTER TABLE devices ADD COLUMN kind TEXT NOT NULL DEFAULT 'desktop'"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS commands (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id   INTEGER NOT NULL,
                action      TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                created_at  REAL NOT NULL,
                acked_at    REAL,
                FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
            )
            """
        )


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------

def create_user(email, password_hash, plan="free", is_admin=0):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, plan, is_admin, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (email, password_hash, plan, is_admin, time.time()),
        )
        return cur.lastrowid


def get_user(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_customer(stripe_customer_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE stripe_customer_id = ?", (stripe_customer_id,)
        ).fetchone()
        return dict(row) if row else None


def set_user_plan(user_id, plan, subscription_id=None, renews_at=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET plan = ?, stripe_subscription_id = ?, plan_renews_at = ? "
            "WHERE id = ?",
            (plan, subscription_id, renews_at, user_id),
        )


def set_stripe_customer(user_id, customer_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET stripe_customer_id = ? WHERE id = ?",
            (customer_id, user_id),
        )


def list_users():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Devices (scoped to a user)
# --------------------------------------------------------------------------

def create_device(user_id, name, key_hash):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO devices (user_id, name, key_hash, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, name, key_hash, time.time()),
        )
        return cur.lastrowid


def list_devices(user_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM devices WHERE user_id = ? ORDER BY name COLLATE NOCASE",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def device_count(user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM devices WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["n"]


def get_device(device_id, user_id=None):
    """Fetch a device. If user_id is given, only returns it when owned by them."""
    with get_conn() as conn:
        if user_id is None:
            row = conn.execute(
                "SELECT * FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM devices WHERE id = ? AND user_id = ?",
                (device_id, user_id),
            ).fetchone()
        return dict(row) if row else None


def delete_device(device_id, user_id):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM devices WHERE id = ? AND user_id = ?", (device_id, user_id)
        )


def touch_device(device_id, ip, os_info, kind=None):
    """Heartbeat from a poll. 'kind' is only updated when provided."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE devices SET last_seen = ?, last_ip = ?, os_info = ?, "
            "kind = COALESCE(?, kind) WHERE id = ?",
            (time.time(), ip, os_info, kind, device_id),
        )


def all_key_hashes():
    """(device_id, key_hash) for every device, for authenticating a listener."""
    with get_conn() as conn:
        rows = conn.execute("SELECT id, key_hash FROM devices").fetchall()
        return [(r["id"], r["key_hash"]) for r in rows]


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def queue_command(device_id, action):
    """Queue an action. 'cancel' clears any pending commands instead."""
    with get_conn() as conn:
        if action == "cancel":
            conn.execute(
                "UPDATE commands SET status = 'cancelled' "
                "WHERE device_id = ? AND status = 'pending'",
                (device_id,),
            )
            return None
        cur = conn.execute(
            "INSERT INTO commands (device_id, action, created_at) VALUES (?, ?, ?)",
            (device_id, action, time.time()),
        )
        return cur.lastrowid


def next_pending_command(device_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM commands WHERE device_id = ? AND status = 'pending' "
            "ORDER BY created_at ASC LIMIT 1",
            (device_id,),
        ).fetchone()
        return dict(row) if row else None


def ack_command(command_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE commands SET status = 'done', acked_at = ? WHERE id = ?",
            (time.time(), command_id),
        )


def pending_count(device_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM commands "
            "WHERE device_id = ? AND status = 'pending'",
            (device_id,),
        ).fetchone()
        return row["n"]

"""
SQLite data layer for the Remote Power relay.

Tables
------
devices   : one row per enrolled PC (name, hashed API key, last-seen info)
commands  : queued actions for a device (shutdown / restart / lock / cancel)

The database is a single file (DB_PATH, default power.db). Nothing here is
specific to SQLite beyond the connection helper, so you can swap in another
backend later if you move this onto a bigger server.
"""

import os
import sqlite3
import time

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "power.db"))

# Actions the panel is allowed to queue.
VALID_ACTIONS = ("shutdown", "restart", "lock", "cancel")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enforce foreign keys so deleting a device clears its commands.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if they do not exist. Safe to call on every boot."""
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                key_hash    TEXT NOT NULL,
                created_at  REAL NOT NULL,
                last_seen   REAL,
                last_ip     TEXT,
                os_info     TEXT
            )
            """
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
# Devices
# --------------------------------------------------------------------------

def create_device(name, key_hash):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO devices (name, key_hash, created_at) VALUES (?, ?, ?)",
            (name, key_hash, time.time()),
        )
        return cur.lastrowid


def list_devices():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM devices ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [dict(r) for r in rows]


def get_device(device_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_device(device_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))


def touch_device(device_id, ip, os_info):
    """Record a heartbeat from a client poll."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE devices SET last_seen = ?, last_ip = ?, os_info = ? WHERE id = ?",
            (time.time(), ip, os_info, device_id),
        )


def all_key_hashes():
    """Return (id, key_hash) for every device, for authenticating a client."""
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
    """Oldest pending command for a device, or None."""
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

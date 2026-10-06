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

# Use the default when DB_PATH is unset OR set-but-empty (e.g. a blank line in
# the env file), so a stray "DB_PATH=" never becomes an invalid path.
DB_PATH = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(__file__), "power.db")

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
        # Migrations: add columns to databases created before they existed.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(devices)")}
        if "kind" not in cols:
            conn.execute(
                "ALTER TABLE devices ADD COLUMN kind TEXT NOT NULL DEFAULT 'desktop'"
            )
        if "shot_at" not in cols:
            conn.execute("ALTER TABLE devices ADD COLUMN shot_at REAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id   INTEGER NOT NULL,
                action      TEXT NOT NULL,
                kind        TEXT NOT NULL,              -- once | daily | weekly
                at_minute   INTEGER,                    -- minutes since local midnight (recurring)
                weekday     INTEGER,                    -- 0=Mon..6=Sun (weekly), else NULL
                tz_offset   INTEGER NOT NULL DEFAULT 0, -- minutes local is ahead of UTC
                next_run_at REAL,                       -- epoch UTC of next fire
                last_run_at REAL,
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  REAL NOT NULL,
                FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
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


def set_admin(user_id, is_admin=True):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (1 if is_admin else 0, user_id),
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


def delete_user(user_id):
    """Delete an account; devices/commands/schedules/sessions cascade."""
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


# --------------------------------------------------------------------------
# Admin stats
# --------------------------------------------------------------------------

def device_stats_by_user(online_cutoff):
    """Map user_id -> {"total": n, "online": n} across all devices."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, COUNT(*) AS total, "
            "SUM(CASE WHEN last_seen IS NOT NULL AND last_seen > ? THEN 1 ELSE 0 END) "
            "AS online FROM devices GROUP BY user_id",
            (online_cutoff,),
        ).fetchall()
        return {r["user_id"]: {"total": r["total"], "online": r["online"] or 0}
                for r in rows}


def platform_totals(online_cutoff):
    with get_conn() as conn:
        one = lambda q, a=(): conn.execute(q, a).fetchone()["n"]
        return {
            "users": one("SELECT COUNT(*) AS n FROM users"),
            "devices": one("SELECT COUNT(*) AS n FROM devices"),
            "online": one("SELECT COUNT(*) AS n FROM devices WHERE last_seen IS NOT NULL "
                          "AND last_seen > ?", (online_cutoff,)),
            "schedules": one("SELECT COUNT(*) AS n FROM schedules WHERE enabled = 1"),
        }


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
            "WHERE device_id = ? AND status = 'pending' AND action != 'screenshot'",
            (device_id,),
        ).fetchone()
        return row["n"]


# --------------------------------------------------------------------------
# Screenshots (opt-in screen previews)
# --------------------------------------------------------------------------

def queue_screenshot(device_id):
    """Queue a one-off screen capture, replacing any pending one."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE commands SET status = 'superseded' "
            "WHERE device_id = ? AND status = 'pending' AND action = 'screenshot'",
            (device_id,),
        )
        conn.execute(
            "INSERT INTO commands (device_id, action, created_at) "
            "VALUES (?, 'screenshot', ?)",
            (device_id, time.time()),
        )


def set_screenshot_time(device_id, ts):
    with get_conn() as conn:
        conn.execute("UPDATE devices SET shot_at = ? WHERE id = ?", (ts, device_id))


# --------------------------------------------------------------------------
# Schedules
# --------------------------------------------------------------------------

def create_schedule(device_id, action, kind, at_minute, weekday, tz_offset, next_run_at):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO schedules (device_id, action, kind, at_minute, weekday, "
            "tz_offset, next_run_at, enabled, created_at) VALUES (?,?,?,?,?,?,?,1,?)",
            (device_id, action, kind, at_minute, weekday, tz_offset, next_run_at,
             time.time()),
        )
        return cur.lastrowid


def list_schedules_for_device(device_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE device_id = ? AND enabled = 1 "
            "ORDER BY next_run_at",
            (device_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def schedule_count(device_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM schedules WHERE device_id = ? AND enabled = 1",
            (device_id,),
        ).fetchone()
        return row["n"]


def get_schedule(schedule_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_schedule(schedule_id, device_ids):
    """Delete a schedule only if it belongs to one of the user's devices."""
    if not device_ids:
        return
    placeholders = ",".join("?" * len(device_ids))
    with get_conn() as conn:
        conn.execute(
            f"DELETE FROM schedules WHERE id = ? AND device_id IN ({placeholders})",
            (schedule_id, *device_ids),
        )


def due_schedules(now_ts):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at IS NOT NULL "
            "AND next_run_at <= ?",
            (now_ts,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_schedule_fired(schedule_id, last_run_at, next_run_at, enabled):
    with get_conn() as conn:
        conn.execute(
            "UPDATE schedules SET last_run_at = ?, next_run_at = ?, enabled = ? "
            "WHERE id = ?",
            (last_run_at, next_run_at, 1 if enabled else 0, schedule_id),
        )

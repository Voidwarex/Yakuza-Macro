"""
Remote Power — relay server.

Host this on your own server (the one that's reachable from the internet).
It does two jobs:

  1. Serves a password-protected web panel where you see your PCs and press
     Shutdown / Restart / Lock.
  2. Exposes a tiny JSON API that the Python listener on each PC polls. The
     PC never needs an open port or a public IP — it reaches *out* to this
     server, so it works from behind any home router.

Configuration (environment variables):

  ADMIN_PASSWORD   required. The password for the web panel.
  SECRET_KEY       recommended. Random string used to sign login cookies.
                   If unset, a random one is generated per boot (logs you out
                   on every restart).
  DB_PATH          optional. Path to the SQLite file (default server/power.db).
  HOST / PORT      optional. Bind address (default 127.0.0.1:8000).
  INSECURE_COOKIES set to 1 ONLY for local http testing. In production leave it
                   unset so the login cookie is marked Secure (HTTPS-only).

Run for real behind a reverse proxy with HTTPS (nginx/Caddy) or a tunnel.
Never expose it over plain HTTP on the open internet — the API keys and your
panel password would travel in clear text.
"""

import hmac
import os
import secrets
import time
from functools import wraps

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import database as db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# Cookie hardening. Secure is on by default (HTTPS-only); flip it off only for
# local http testing with INSECURE_COOKIES=1.
_secure_cookies = os.environ.get("INSECURE_COOKIES") not in ("1", "true", "True")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_secure_cookies,
    PERMANENT_SESSION_LIFETIME=7 * 24 * 60 * 60,  # a week
    MAX_CONTENT_LENGTH=64 * 1024,                 # reject oversized bodies
)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
# How long before a device is shown as "offline" in the panel (seconds).
OFFLINE_AFTER = 60

# ---- login brute-force throttle (per client IP, in memory) ----
# After LOCK_THRESHOLD failures an IP is locked out for LOCK_SECONDS. State is
# process-local, which is fine for the single-worker waitress setup here.
LOCK_THRESHOLD = 5
LOCK_SECONDS = 300
_login_failures = {}  # ip -> {"count": int, "until": float}


def _client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _is_locked(ip):
    rec = _login_failures.get(ip)
    return bool(rec) and rec["until"] > time.time()


def _record_failure(ip):
    rec = _login_failures.get(ip, {"count": 0, "until": 0})
    rec["count"] += 1
    if rec["count"] >= LOCK_THRESHOLD:
        rec["until"] = time.time() + LOCK_SECONDS
        rec["count"] = 0  # reset the counter; the lockout window now applies
    _login_failures[ip] = rec
    # Keep the dict from growing without bound.
    if len(_login_failures) > 1000:
        now = time.time()
        for k in [k for k, v in _login_failures.items() if v["until"] < now]:
            _login_failures.pop(k, None)


def _clear_failures(ip):
    _login_failures.pop(ip, None)


def _password_ok(candidate):
    """Constant-time comparison so timing can't leak the password length."""
    if not ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(str(candidate), str(ADMIN_PASSWORD))


# =========================================================
# AUTH HELPERS
# =========================================================

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def csrf_token():
    """Per-session CSRF token, created on first use."""
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


@app.after_request
def security_headers(resp):
    """Defence-in-depth headers on every response."""
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'",
    )
    if _secure_cookies:
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


@app.before_request
def csrf_protect():
    """
    Require a matching CSRF token on cookie-authenticated, state-changing
    panel requests. The /api/* listener endpoints use Bearer auth (no cookie),
    so they are not CSRF-exposed and are exempt.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if not request.path.startswith("/panel"):
        return
    sent = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(403)


def client_from_request():
    """
    Authenticate a listener from its Bearer API key.
    Returns the device id, or None if the key is unknown.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[len("Bearer "):].strip()
    if not token:
        return None
    for device_id, key_hash in db.all_key_hashes():
        if check_password_hash(key_hash, token):
            return device_id
    return None


# =========================================================
# WEB PANEL
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        ip = _client_ip()
        if _is_locked(ip):
            error = "Too many attempts. Try again in a few minutes."
        elif not ADMIN_PASSWORD:
            error = "Server has no ADMIN_PASSWORD set. See the README."
        elif _password_ok(request.form.get("password", "")):
            _clear_failures(ip)
            # Rotate the session on login to prevent session fixation.
            session.clear()
            session["admin"] = True
            session.permanent = True
            csrf_token()  # mint a CSRF token for this session
            return redirect(url_for("dashboard"))
        else:
            _record_failure(ip)
            error = "Incorrect password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    now = time.time()
    devices = db.list_devices()
    for d in devices:
        d["online"] = bool(d["last_seen"]) and (now - d["last_seen"] < OFFLINE_AFTER)
        d["pending"] = db.pending_count(d["id"])
    return render_template("dashboard.html", devices=devices, csrf=csrf_token())


# ---- panel actions (called via fetch from app.js) --------------------------

@app.route("/panel/devices", methods=["GET"])
@login_required
def panel_devices():
    """Live device list for the dashboard to poll."""
    now = time.time()
    out = []
    for d in db.list_devices():
        out.append(
            {
                "id": d["id"],
                "name": d["name"],
                "online": bool(d["last_seen"]) and (now - d["last_seen"] < OFFLINE_AFTER),
                "last_seen": d["last_seen"],
                "last_ip": d["last_ip"],
                "os_info": d["os_info"],
                "pending": db.pending_count(d["id"]),
            }
        )
    return jsonify(out)


@app.route("/panel/devices", methods=["POST"])
@login_required
def panel_add_device():
    name = (request.json or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    # Generate the device's API key once. We store only its hash; the plaintext
    # is returned a single time so the user can paste it into the client config.
    api_key = secrets.token_urlsafe(32)
    device_id = db.create_device(name, generate_password_hash(api_key))
    return jsonify({"id": device_id, "name": name, "api_key": api_key})


@app.route("/panel/devices/<int:device_id>", methods=["DELETE"])
@login_required
def panel_delete_device(device_id):
    db.delete_device(device_id)
    return jsonify({"ok": True})


@app.route("/panel/devices/<int:device_id>/command", methods=["POST"])
@login_required
def panel_command(device_id):
    action = (request.json or {}).get("action", "")
    if action not in db.VALID_ACTIONS:
        return jsonify({"error": "Unknown action"}), 400
    if not db.get_device(device_id):
        return jsonify({"error": "No such device"}), 404
    db.queue_command(device_id, action)
    return jsonify({"ok": True, "action": action})


# =========================================================
# CLIENT API (the Python listener talks to these)
# =========================================================

@app.route("/api/poll", methods=["POST"])
def api_poll():
    """
    The listener calls this on a loop. It authenticates with its API key,
    reports a heartbeat, and gets back the next pending action (if any).
    """
    device_id = client_from_request()
    if device_id is None:
        return jsonify({"error": "unauthorized"}), 401

    body = request.json or {}
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    ip = ip.split(",")[0].strip()
    db.touch_device(device_id, ip, str(body.get("os_info", ""))[:200])

    cmd = db.next_pending_command(device_id)
    if not cmd:
        return jsonify({"action": None})
    return jsonify({"command_id": cmd["id"], "action": cmd["action"]})


@app.route("/api/ack", methods=["POST"])
def api_ack():
    """The listener confirms it is about to carry out a command."""
    device_id = client_from_request()
    if device_id is None:
        return jsonify({"error": "unauthorized"}), 401

    command_id = (request.json or {}).get("command_id")
    if command_id is None:
        return jsonify({"error": "command_id required"}), 400
    db.ack_command(command_id)
    return jsonify({"ok": True})


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "time": time.time()})


# =========================================================
# ENTRYPOINT
# =========================================================

db.init_db()


def serve():
    """Start the relay. Uses waitress (production) if installed, else Flask."""
    if not ADMIN_PASSWORD:
        print("WARNING: ADMIN_PASSWORD is not set — the panel cannot be used.")
        print("Set it, e.g.:  export ADMIN_PASSWORD='choose-a-strong-password'")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Remote Power relay starting on http://{host}:{port}")
    try:
        from waitress import serve as waitress_serve

        waitress_serve(app, host=host, port=port)
    except ImportError:
        print("waitress not installed; using Flask's development server.")
        app.run(host=host, port=port)


if __name__ == "__main__":
    serve()

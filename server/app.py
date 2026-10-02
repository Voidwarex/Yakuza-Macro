"""
Remote Power — relay server (multi-account edition).

Host this on your own server (reachable from the internet). It:

  1. Lets people register an account and sign in to a web panel where they see
     only their own PCs and press Shutdown / Restart / Lock.
  2. Enforces per-account device limits by plan (Free 3, Pro 10, Business 50).
  3. Sells Pro/Business as Stripe subscriptions (optional — the app runs fine
     with Stripe unconfigured; upgrade just shows "billing not set up").
  4. Exposes a JSON API that the Python listener on each PC polls over
     outbound HTTPS (no port forwarding needed).

Key environment variables (see config.example.env for the full list):

  SECRET_KEY               sign login cookies (random per boot if unset)
  DB_PATH                  SQLite file (default server/power.db)
  HOST / PORT              bind address (default 127.0.0.1:8000)
  INSECURE_COOKIES=1       ONLY for local http testing
  PUBLIC_URL               base URL for Stripe redirects, e.g. https://api.amos.fyi
  STRIPE_SECRET_KEY        enables billing when set
  STRIPE_WEBHOOK_SECRET    verifies Stripe webhooks
  STRIPE_PRICE_PRO         Stripe Price ID for the Pro plan
  STRIPE_PRICE_BUSINESS    Stripe Price ID for the Business plan

Admin CLI:
  python app.py serve
  python app.py createadmin <email>
  python app.py setplan <email> <free|pro|business>
  python app.py listusers
"""

import hmac
import os
import re
import secrets
import sys
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
import plans

try:
    import stripe
except ImportError:
    stripe = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

_secure_cookies = os.environ.get("INSECURE_COOKIES") not in ("1", "true", "True")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_secure_cookies,
    PERMANENT_SESSION_LIFETIME=7 * 24 * 60 * 60,
    MAX_CONTENT_LENGTH=64 * 1024,
)

OFFLINE_AFTER = 60  # seconds before a device shows as offline
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ---- Stripe setup ----
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
BILLING_ENABLED = bool(stripe and STRIPE_SECRET_KEY)
if BILLING_ENABLED:
    stripe.api_key = STRIPE_SECRET_KEY

# ---- login brute-force throttle (per IP, in memory) ----
LOCK_THRESHOLD = 5
LOCK_SECONDS = 300
_login_failures = {}


def _client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "unknown")


def _is_locked(ip):
    rec = _login_failures.get(ip)
    return bool(rec) and rec["until"] > time.time()


def _record_failure(ip):
    rec = _login_failures.get(ip, {"count": 0, "until": 0})
    rec["count"] += 1
    if rec["count"] >= LOCK_THRESHOLD:
        rec["until"] = time.time() + LOCK_SECONDS
        rec["count"] = 0
    _login_failures[ip] = rec
    if len(_login_failures) > 1000:
        now = time.time()
        for k in [k for k, v in _login_failures.items() if v["until"] < now]:
            _login_failures.pop(k, None)


def _clear_failures(ip):
    _login_failures.pop(ip, None)


# =========================================================
# AUTH HELPERS
# =========================================================

def current_user():
    uid = session.get("uid")
    return db.get_user(uid) if uid else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("uid"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def csrf_token():
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Stripe Checkout is a hosted redirect, so no Stripe origins are needed in CSP.
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "script-src 'self'; img-src 'self' data:; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    )
    if _secure_cookies:
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


@app.before_request
def csrf_protect():
    """CSRF on cookie-authenticated, state-changing panel requests.
    /api/* (Bearer auth) and /billing/webhook (Stripe signature) are exempt."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if not request.path.startswith("/panel"):
        return
    sent = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(403)


def client_from_request():
    """Authenticate a listener from its Bearer API key -> device id or None."""
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
# ACCOUNTS
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not EMAIL_RE.match(email):
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif db.get_user_by_email(email):
            error = "An account with that email already exists."
        else:
            uid = db.create_user(email, generate_password_hash(password))
            session.clear()
            session["uid"] = uid
            session.permanent = True
            csrf_token()
            return redirect(url_for("dashboard"))
    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        ip = _client_ip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if _is_locked(ip):
            error = "Too many attempts. Try again in a few minutes."
        else:
            user = db.get_user_by_email(email)
            if user and check_password_hash(user["password_hash"], password):
                _clear_failures(ip)
                session.clear()
                session["uid"] = user["id"]
                session.permanent = True
                csrf_token()
                return redirect(url_for("dashboard"))
            _record_failure(ip)
            error = "Incorrect email or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================================================
# WEB PANEL
# =========================================================

def _plan_context(user):
    plan = user["plan"] if plans.is_valid_plan(user["plan"]) else "free"
    limit = plans.device_limit(plan)
    used = db.device_count(user["id"])
    return {
        "plan": plan,
        "plan_name": plans.PLANS[plan]["name"],
        "limit": limit,
        "used": used,
        "at_limit": used >= limit,
        "pct": min(100, round(used / limit * 100)) if limit else 0,
    }


@app.route("/")
@login_required
def dashboard():
    user = current_user()
    ctx = _plan_context(user)
    return render_template(
        "dashboard.html",
        csrf=csrf_token(),
        email=user["email"],
        billing_enabled=BILLING_ENABLED,
        plans=plans.PLANS,
        **ctx,
    )


# ---- panel API (fetch from app.js) ----

@app.route("/panel/devices", methods=["GET"])
@login_required
def panel_devices():
    user = current_user()
    now = time.time()
    ctx = _plan_context(user)
    out = []
    for d in db.list_devices(user["id"]):
        out.append(
            {
                "id": d["id"],
                "name": d["name"],
                "kind": d["kind"] or "desktop",
                "online": bool(d["last_seen"]) and (now - d["last_seen"] < OFFLINE_AFTER),
                "last_seen": d["last_seen"],
                "last_ip": d["last_ip"],
                "os_info": d["os_info"],
                "pending": db.pending_count(d["id"]),
            }
        )
    return jsonify({"devices": out, "plan": ctx})


@app.route("/panel/devices", methods=["POST"])
@login_required
def panel_add_device():
    user = current_user()
    limit = plans.device_limit(user["plan"])
    if db.device_count(user["id"]) >= limit:
        return (
            jsonify(
                {
                    "error": "limit",
                    "message": f"Your {plans.PLANS.get(user['plan'], {}).get('name', 'plan')} "
                    f"plan allows {limit} devices. Upgrade to add more.",
                }
            ),
            402,
        )
    name = (request.json or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    api_key = secrets.token_urlsafe(32)
    device_id = db.create_device(user["id"], name, generate_password_hash(api_key))
    return jsonify({"id": device_id, "name": name, "api_key": api_key})


@app.route("/panel/devices/<int:device_id>", methods=["DELETE"])
@login_required
def panel_delete_device(device_id):
    user = current_user()
    db.delete_device(device_id, user["id"])
    return jsonify({"ok": True})


@app.route("/panel/devices/<int:device_id>/command", methods=["POST"])
@login_required
def panel_command(device_id):
    user = current_user()
    action = (request.json or {}).get("action", "")
    if action not in db.VALID_ACTIONS:
        return jsonify({"error": "Unknown action"}), 400
    if not db.get_device(device_id, user["id"]):
        return jsonify({"error": "No such device"}), 404
    db.queue_command(device_id, action)
    return jsonify({"ok": True, "action": action})


# =========================================================
# BILLING (Stripe subscriptions)
# =========================================================

@app.route("/panel/billing/checkout", methods=["POST"])
@login_required
def billing_checkout():
    user = current_user()
    plan = (request.json or {}).get("plan", "")
    if plan not in plans.PAID_PLANS:
        return jsonify({"error": "Unknown plan"}), 400
    if not BILLING_ENABLED:
        return jsonify({"error": "Billing is not configured on this server."}), 503
    price_id = plans.stripe_price_id(plan)
    if not price_id:
        return jsonify({"error": f"No Stripe price set for {plan}."}), 503

    base = PUBLIC_URL or request.url_root.rstrip("/")
    try:
        kwargs = dict(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            client_reference_id=str(user["id"]),
            success_url=f"{base}/?upgraded=1",
            cancel_url=f"{base}/?upgraded=0",
        )
        if user.get("stripe_customer_id"):
            kwargs["customer"] = user["stripe_customer_id"]
        else:
            kwargs["customer_email"] = user["email"]
        checkout = stripe.checkout.Session.create(**kwargs)
        return jsonify({"url": checkout.url})
    except Exception as exc:  # pragma: no cover - network dependent
        return jsonify({"error": f"Stripe error: {exc}"}), 502


@app.route("/panel/billing/portal", methods=["POST"])
@login_required
def billing_portal():
    user = current_user()
    if not BILLING_ENABLED or not user.get("stripe_customer_id"):
        return jsonify({"error": "No subscription to manage."}), 400
    base = PUBLIC_URL or request.url_root.rstrip("/")
    try:
        portal = stripe.billing_portal.Session.create(
            customer=user["stripe_customer_id"], return_url=f"{base}/"
        )
        return jsonify({"url": portal.url})
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": f"Stripe error: {exc}"}), 502


@app.route("/billing/webhook", methods=["POST"])
def billing_webhook():
    """Stripe calls this to tell us about subscription changes."""
    if not BILLING_ENABLED:
        return jsonify({"error": "billing disabled"}), 503
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        else:
            event = stripe.Event.construct_from(request.get_json(), stripe.api_key)
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": f"invalid payload: {exc}"}), 400

    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        uid = obj.get("client_reference_id")
        customer_id = obj.get("customer")
        sub_id = obj.get("subscription")
        if uid:
            if customer_id:
                db.set_stripe_customer(int(uid), customer_id)
            plan = _plan_from_subscription(sub_id) if sub_id else None
            if plan:
                db.set_user_plan(int(uid), plan, sub_id, _sub_renews_at(sub_id))

    elif etype in ("customer.subscription.updated", "customer.subscription.created"):
        _apply_subscription(obj)

    elif etype == "customer.subscription.deleted":
        user = db.get_user_by_customer(obj.get("customer"))
        if user:
            db.set_user_plan(user["id"], "free", None, None)

    return jsonify({"ok": True})


def _plan_from_subscription(sub_id):
    try:
        sub = stripe.Subscription.retrieve(sub_id)
        price_id = sub["items"]["data"][0]["price"]["id"]
        return plans.plan_by_price_id(price_id)
    except Exception:  # pragma: no cover
        return None


def _sub_renews_at(sub_id):
    try:
        sub = stripe.Subscription.retrieve(sub_id)
        return sub.get("current_period_end")
    except Exception:  # pragma: no cover
        return None


def _apply_subscription(sub):
    user = db.get_user_by_customer(sub.get("customer"))
    if not user:
        return
    status = sub.get("status")
    if status in ("active", "trialing"):
        price_id = sub["items"]["data"][0]["price"]["id"]
        plan = plans.plan_by_price_id(price_id)
        if plan:
            db.set_user_plan(user["id"], plan, sub.get("id"), sub.get("current_period_end"))
    elif status in ("canceled", "unpaid", "incomplete_expired"):
        db.set_user_plan(user["id"], "free", None, None)


# =========================================================
# CLIENT API (listener)
# =========================================================

@app.route("/api/poll", methods=["POST"])
def api_poll():
    device_id = client_from_request()
    if device_id is None:
        return jsonify({"error": "unauthorized"}), 401
    body = request.json or {}
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    ip = ip.split(",")[0].strip()
    kind = str(body.get("kind", "")).strip().lower()
    if kind not in ("desktop", "laptop", "server"):
        kind = None  # leave the stored value untouched
    db.touch_device(device_id, ip, str(body.get("os_info", ""))[:200], kind)
    cmd = db.next_pending_command(device_id)
    if not cmd:
        return jsonify({"action": None})
    return jsonify({"command_id": cmd["id"], "action": cmd["action"]})


@app.route("/api/ack", methods=["POST"])
def api_ack():
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
    return jsonify({"ok": True, "time": time.time(), "billing": BILLING_ENABLED})


# =========================================================
# CLI + ENTRYPOINT
# =========================================================

db.init_db()


def serve():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Remote Power relay starting on http://{host}:{port} "
          f"(billing: {'on' if BILLING_ENABLED else 'off'})")
    try:
        from waitress import serve as waitress_serve

        waitress_serve(app, host=host, port=port)
    except ImportError:
        print("waitress not installed; using Flask's development server.")
        app.run(host=host, port=port)


def _cli():
    args = sys.argv[1:]
    if not args or args[0] == "serve":
        serve()
        return

    cmd = args[0]
    if cmd == "createadmin" and len(args) == 2:
        import getpass

        email = args[1].strip().lower()
        if db.get_user_by_email(email):
            print("A user with that email already exists.")
            return
        pw = getpass.getpass("Password: ")
        db.create_user(email, generate_password_hash(pw), plan="business", is_admin=1)
        print(f"Admin account created: {email} (Business plan)")

    elif cmd == "setplan" and len(args) == 3:
        email, plan = args[1].strip().lower(), args[2].strip().lower()
        if not plans.is_valid_plan(plan):
            print(f"Unknown plan. Choose from: {', '.join(plans.PLANS)}")
            return
        user = db.get_user_by_email(email)
        if not user:
            print("No such user.")
            return
        db.set_user_plan(user["id"], plan, user.get("stripe_subscription_id"),
                         user.get("plan_renews_at"))
        print(f"{email} is now on the {plans.PLANS[plan]['name']} plan "
              f"({plans.device_limit(plan)} devices).")

    elif cmd == "listusers":
        for u in db.list_users():
            print(f"{u['email']:40}  {u['plan']:10}  "
                  f"{db.device_count(u['id'])}/{plans.device_limit(u['plan'])} devices"
                  f"{'  [admin]' if u['is_admin'] else ''}")

    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()

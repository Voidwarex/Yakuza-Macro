import threading
import time
import webbrowser
import platform
import subprocess
import uuid
import urllib.request
import urllib.error
import json
import hashlib
import os
import socket
import sys
import tempfile

from flask import Flask, request, jsonify
from pynput import keyboard


# =========================================================
# CONFIGURATION
# =========================================================

config = {
    "delay_ms": 10,
    "trigger_key": "e",
    "target_key": "p",
    "active": True,

    "auto_build_active": False,
    "auto_build_key": "f",
    "auto_build_delay_ms": 10,
}


controller = keyboard.Controller()
is_pressed = False


# =========================================================
# LICENSE
# =========================================================

# Address of license_server.py. Point this at your hosted server
# (use https:// in production) or set YAKUZA_LICENSE_SERVER.
LICENSE_SERVER = os.environ.get(
    "YAKUZA_LICENSE_SERVER",
    "http://170.64.171.207"
).rstrip("/")

LICENSE_SYNC_SECONDS = 60


# remaining is counted down from synced_at with a monotonic
# clock, so changing the PC clock can't add time.
license_state = {
    "token": None,
    "username": None,
    "remaining": 0.0,
    "synced_at": 0.0,
    "is_admin": False,
}

license_lock = threading.Lock()


# Set when the license server says this copy of the app isn't an
# approved build. The login screen shows it and stays locked.
integrity_state = {
    "checked": False,
    "message": None,
}


# =========================================================
# SYSTEM INFO
# =========================================================

def get_public_ip():
    try:
        req = urllib.request.Request(
            "https://api.ipify.org",
            headers={"User-Agent": "Mozilla/5.0"}
        )

        return urllib.request.urlopen(
            req,
            timeout=3
        ).read().decode("utf8")

    except Exception:
        return "Unavailable"


def get_hwid():
    try:
        system = platform.system()

        if system == "Windows":
            try:
                hwid = subprocess.check_output(
                    "wmic csproduct get uuid",
                    shell=True
                ).decode().split("\n")[1].strip()

                if hwid:
                    return hwid

            except Exception:
                pass

        elif system == "Linux":
            with open("/etc/machine-id", "r") as f:
                return f.read().strip()

        elif system == "Darwin":
            output = subprocess.check_output(
                "ioreg -rd1 -c IOPlatformExpertDevice | grep IOPlatformUUID",
                shell=True
            )

            return output.decode().split('"')[-2]

    except Exception:
        pass

    return str(uuid.getnode())


def app_file():

    # The file actually running: the .exe when packaged with
    # PyInstaller, otherwise this script.
    if getattr(sys, "frozen", False):
        return sys.executable

    return os.path.abspath(__file__)


def compute_app_hash():

    # Must match file_hash() in license_server.py: scripts are hashed
    # with LF line endings so a CRLF checkout gets the same hash.
    path = app_file()

    with open(path, "rb") as f:
        content = f.read()

    if path.lower().endswith(".py"):
        content = content.replace(b"\r\n", b"\n")

    return hashlib.sha256(content).hexdigest()


_app_hash_cache = None


def app_hash():

    global _app_hash_cache

    if _app_hash_cache is None:
        _app_hash_cache = compute_app_hash()

    return _app_hash_cache


_hwid_cache = None


def cached_hwid():

    global _hwid_cache

    if _hwid_cache is None:
        _hwid_cache = get_hwid()

    return _hwid_cache


# =========================================================
# BACKGROUND MODE
# =========================================================

APP_PORT = 5000

APP_URL = f"http://127.0.0.1:{APP_PORT}"


def relaunch_without_console():

    # On Windows, python.exe always opens a console window. Restart
    # under pythonw.exe (no window) and let this copy exit, which
    # closes the console. Run with --console to keep it for debugging.
    if platform.system() != "Windows" or getattr(sys, "frozen", False):
        return

    if "--console" in sys.argv:
        return


    exe = os.path.basename(sys.executable).lower()

    if not exe.startswith("python") or exe.startswith("pythonw"):
        return


    pythonw = os.path.join(
        os.path.dirname(sys.executable),
        exe.replace("python", "pythonw", 1)
    )

    if not os.path.exists(pythonw):
        return


    subprocess.Popen(
        [pythonw, os.path.abspath(__file__), *sys.argv[1:]],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True
    )

    sys.exit(0)


def redirect_output_to_log():

    # pythonw has no console, so print() and errors would vanish.
    # Send them to a log file instead so problems can be diagnosed.
    if sys.stdout is not None and sys.stderr is not None:
        return

    log = open(
        os.path.join(tempfile.gettempdir(), "yakuza.log"),
        "a",
        buffering=1,
        encoding="utf8"
    )

    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


def app_already_running():

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:

        s.settimeout(0.5)

        return s.connect_ex(("127.0.0.1", APP_PORT)) == 0


# =========================================================
# LICENSE CLIENT
# =========================================================

def license_request(path, payload):

    # Returns (response_json, error_message, http_status).
    body = json.dumps(
        {**payload, "hwid": cached_hwid(), "app_hash": app_hash()}
    ).encode("utf8")

    req = urllib.request.Request(
        LICENSE_SERVER + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:

        with urllib.request.urlopen(req, timeout=6) as res:
            return json.loads(res.read().decode("utf8")), None, res.status

    except urllib.error.HTTPError as e:

        try:
            body = json.loads(e.read().decode("utf8"))
        except Exception:
            body = {}

        message = body.get("error") or f"License server error ({e.code})."

        if body.get("modified"):
            integrity_state["checked"] = True
            integrity_state["message"] = message

        return None, message, e.code

    except Exception:

        return None, "Can't reach the license server. Check your connection.", 0


def apply_license(data, token=None):

    with license_lock:

        if token is not None:
            license_state["token"] = token

        license_state["username"] = data.get(
            "username", license_state["username"]
        )

        license_state["remaining"] = float(
            data.get("remaining_seconds", 0)
        )

        license_state["synced_at"] = time.monotonic()

        if "is_admin" in data:
            license_state["is_admin"] = bool(data["is_admin"])


def clear_license():

    with license_lock:

        license_state["token"] = None
        license_state["username"] = None
        license_state["remaining"] = 0.0
        license_state["is_admin"] = False


def logged_in():

    return license_state["token"] is not None


def remaining_seconds():

    with license_lock:

        if license_state["token"] is None:
            return 0.0

        elapsed = time.monotonic() - license_state["synced_at"]

        return max(0.0, license_state["remaining"] - elapsed)


def license_active():

    return remaining_seconds() > 0


def check_integrity():

    # Asks the license server whether this build is approved. Returns
    # the error message if it isn't, else None. If the server can't
    # be reached it's asked again next time; login fails anyway.
    if not integrity_state["checked"]:

        data, err, status = license_request("/api/integrity", {})

        if data:
            integrity_state["checked"] = True
            integrity_state["message"] = None

    return integrity_state["message"]


def license_sync_loop():

    # Re-check the license with the server so redeemed or
    # revoked time shows up without restarting.
    while True:

        time.sleep(LICENSE_SYNC_SECONDS)

        token = license_state["token"]

        if token is None:
            continue

        data, err, status = license_request(
            "/api/status", {"token": token}
        )

        if data:
            apply_license(data)

        elif status in (401, 403):
            clear_license()


# =========================================================
# CSS
# =========================================================

COMMON_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link
    href="https://fonts.googleapis.com/css2?family=Oxanium:wght@500;600;700;800&family=Barlow:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap"
    rel="stylesheet"
>

<style>

    :root {
        --bg: #06080d;
        --bg-deep: #030408;
        --panel: rgba(15, 20, 30, 0.72);
        --panel-solid: #0b0f17;
        --panel-border: rgba(150, 180, 215, 0.12);
        --panel-border-strong: rgba(150, 180, 215, 0.24);

        --text-primary: #e4ebf5;
        --text-muted: #7b879a;

        --bolt: #5cc8ff;
        --bolt-bright: #cfeeff;
        --storm-violet: #8193ff;
        --on: #5cc8ff;
        --off: #ff4d62;

        --glow-bolt:
            0 0 6px rgba(92, 200, 255, 0.7),
            0 0 20px rgba(92, 200, 255, 0.3);

        --font-display: "Oxanium", "Segoe UI", sans-serif;
        --font-body: "Barlow", "Segoe UI", Roboto, sans-serif;
        --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace;

        --radius: 12px;

        --sidebar-width: 260px;
        --sidebar-collapsed-width: 76px;
    }


    * {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }


    ::selection {
        background: var(--bolt);
        color: var(--bg);
    }


    ::-webkit-scrollbar {
        width: 8px;
    }

    ::-webkit-scrollbar-track {
        background: var(--bg-deep);
    }

    ::-webkit-scrollbar-thumb {
        background: #243042;
        border-radius: 4px;
    }

    ::-webkit-scrollbar-thumb:hover {
        background: var(--bolt);
    }


    body {
        font-family: var(--font-body);
        font-size: 16px;
        font-weight: 500;

        background: var(--bg);
        color: var(--text-primary);

        display: flex;
        height: 100vh;
        overflow: hidden;

        position: relative;
    }


    /* Lightning flash overlay */

    body::after {
        content: "";

        position: fixed;
        inset: 0;

        pointer-events: none;
        z-index: 100;

        background:
            radial-gradient(ellipse at 70% 0%, rgba(200, 230, 255, 0.55), transparent 60%);

        opacity: 0;

        animation: lightning 11s infinite;
    }


    @keyframes lightning {
        0%, 88%, 100% { opacity: 0; }
        88.5% { opacity: 0.55; }
        89%   { opacity: 0.05; }
        89.6% { opacity: 0.8; }
        90.4% { opacity: 0; }
        93%   { opacity: 0; }
        93.3% { opacity: 0.25; }
        93.8% { opacity: 0; }
    }


    /* =====================================================
       SIDEBAR
       ===================================================== */

    .sidebar {
        width: var(--sidebar-width);

        background:
            linear-gradient(180deg, rgba(92, 200, 255, 0.05), transparent 30%),
            rgba(9, 12, 19, 0.92);

        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);

        border-right: 1px solid var(--panel-border);

        box-shadow: 10px 0 40px rgba(0, 0, 0, 0.55);

        transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);

        display: flex;
        flex-direction: column;

        z-index: 10;
        position: relative;
    }


    .sidebar.collapsed {
        width: var(--sidebar-collapsed-width);
    }


    .sidebar-header {
        height: 76px;

        display: flex;
        align-items: center;

        padding: 0 24px;

        border-bottom: 1px solid var(--panel-border);

        overflow: hidden;
        white-space: nowrap;
    }


    .sidebar-logo {
        display: flex;
        align-items: center;
        gap: 12px;

        font-family: var(--font-display);
        font-weight: 800;
        font-size: 1.05rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;

        color: var(--text-primary);
        text-decoration: none;
    }


    .sidebar-logo svg {
        flex-shrink: 0;

        color: var(--bolt);

        filter: drop-shadow(0 0 6px rgba(92, 200, 255, 0.7));

        animation: boltFlicker 11s infinite;
    }


    @keyframes boltFlicker {
        0%, 88%, 91%, 100% { color: var(--bolt); filter: drop-shadow(0 0 6px rgba(92, 200, 255, 0.7)); }
        88.5%, 89.6% { color: #ffffff; filter: drop-shadow(0 0 14px rgba(207, 238, 255, 1)); }
    }


    .sidebar-nav {
        flex: 1;

        padding: 24px 12px;

        display: flex;
        flex-direction: column;
        gap: 6px;
    }


    .nav-item {
        position: relative;

        display: flex;
        align-items: center;
        gap: 16px;

        padding: 12px 14px;

        border-radius: 10px;

        color: var(--text-muted);
        text-decoration: none;

        font-family: var(--font-display);
        font-weight: 600;
        font-size: 0.9rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;

        border: 1px solid transparent;

        transition: all 0.2s ease;

        cursor: pointer;
        overflow: hidden;
        white-space: nowrap;
    }


    .nav-item::before {
        content: "";

        position: absolute;
        left: 0;
        top: 22%;
        bottom: 22%;

        width: 3px;
        border-radius: 0 3px 3px 0;

        background: var(--bolt);
        box-shadow: var(--glow-bolt);

        transform: scaleY(0);
        transition: transform 0.2s ease;
    }


    .nav-item:hover {
        background: rgba(150, 180, 215, 0.06);
        color: var(--text-primary);
    }


    .nav-item.active {
        background: linear-gradient(90deg, rgba(92, 200, 255, 0.14), rgba(92, 200, 255, 0.02));
        border-color: rgba(92, 200, 255, 0.18);

        color: var(--bolt-bright);
    }


    .nav-item.active::before {
        transform: scaleY(1);
    }


    .nav-item.active svg {
        color: var(--bolt);
        filter: drop-shadow(0 0 5px rgba(92, 200, 255, 0.8));
    }


    .nav-item svg {
        flex-shrink: 0;
    }


    .logout-btn {
        margin-top: auto;

        color: #c46a76;
    }


    .exit-btn {
        margin-top: 0;
        margin-bottom: 16px;
    }


    .auth-exit {
        margin-top: 14px;
    }


    .logout-btn::before {
        background: var(--off);
        box-shadow: 0 0 8px var(--off);
    }


    .logout-btn:hover {
        background: rgba(255, 77, 98, 0.08);
        color: var(--off);
    }


    .sidebar span {
        transition: opacity 0.2s;
    }


    .sidebar.collapsed span {
        opacity: 0;
        pointer-events: none;
    }


    .sidebar.collapsed .sidebar-header {
        justify-content: center;
        padding: 0;
    }


    /* =====================================================
       MAIN AREA
       ===================================================== */

    .main-wrapper {
        flex: 1;

        display: flex;
        flex-direction: column;

        position: relative;
        overflow: hidden;

        background:
            linear-gradient(180deg, #0c121c 0%, #080b12 45%, #05070b 100%);
    }


    /* Drifting storm clouds */

    .main-wrapper::before {
        content: "";

        position: absolute;
        inset: -20% -40%;

        background:
            radial-gradient(ellipse 40% 22% at 20% 12%, rgba(85, 105, 135, 0.7), transparent 70%),
            radial-gradient(ellipse 35% 20% at 55% 6%, rgba(70, 88, 115, 0.75), transparent 70%),
            radial-gradient(ellipse 45% 25% at 85% 16%, rgba(80, 98, 130, 0.65), transparent 70%),
            radial-gradient(ellipse 30% 18% at 40% 26%, rgba(50, 64, 88, 0.7), transparent 70%),
            radial-gradient(ellipse 38% 16% at 75% 32%, rgba(45, 58, 80, 0.55), transparent 70%),
            radial-gradient(ellipse 50% 30% at 70% 90%, rgba(92, 200, 255, 0.05), transparent 70%);

        filter: blur(18px);

        animation: cloudDrift 60s ease-in-out infinite alternate;

        pointer-events: none;
        z-index: 0;
    }


    @keyframes cloudDrift {
        from { transform: translateX(-6%); }
        to   { transform: translateX(6%); }
    }


    /* Rain */

    .main-wrapper::after {
        content: "";

        position: absolute;
        inset: -100px 0 0 0;

        background-image:
            repeating-linear-gradient(
                104deg,
                transparent 0px,
                transparent 38px,
                rgba(170, 200, 235, 0.07) 38px,
                rgba(170, 200, 235, 0.07) 39px
            ),
            repeating-linear-gradient(
                104deg,
                transparent 0px,
                transparent 71px,
                rgba(170, 200, 235, 0.05) 71px,
                rgba(170, 200, 235, 0.05) 72px
            );

        mask-image: repeating-linear-gradient(to bottom, black 0 22px, transparent 22px 60px);
        -webkit-mask-image: repeating-linear-gradient(to bottom, black 0 22px, transparent 22px 60px);

        animation: rain 0.55s linear infinite;

        pointer-events: none;
        z-index: 0;
    }


    @keyframes rain {
        from { transform: translate(0, 0); }
        to   { transform: translate(-14px, 60px); }
    }


    /* =====================================================
       TOPBAR
       ===================================================== */

    .topbar {
        height: 76px;

        display: flex;
        align-items: center;

        padding: 0 32px;

        position: relative;
        z-index: 2;

        background: rgba(6, 8, 13, 0.5);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);

        border-bottom: 1px solid var(--panel-border);
    }


    .topbar-left {
        display: flex;
        align-items: center;
        gap: 18px;
    }


    .menu-toggle {
        background: rgba(150, 180, 215, 0.05);
        border: 1px solid var(--panel-border);

        color: var(--text-primary);

        cursor: pointer;
        padding: 8px;
        border-radius: 10px;

        display: flex;
        align-items: center;

        transition: all 0.2s;
    }


    .menu-toggle:hover {
        border-color: rgba(92, 200, 255, 0.5);
        color: var(--bolt);
        box-shadow: 0 0 14px rgba(92, 200, 255, 0.2);
    }


    .brand-title {
        font-family: var(--font-display);
        font-size: 1.35rem;
        font-weight: 800;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        white-space: nowrap;

        background: linear-gradient(180deg, #ffffff 0%, #b9c8dc 55%, #6f8199 100%);
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
    }


    /* =====================================================
       CARD TOGGLE / STATUS
       ===================================================== */

    .card-toggle {
        display: flex;
        align-items: center;
        gap: 10px;

        flex-shrink: 0;
        padding: 0 10px;

        height: 36px;

        border: 1px solid var(--panel-border);
        border-radius: 10px;
        background: rgba(0, 0, 0, 0.3);
    }


    .card-toggle .switch {
        flex-shrink: 0;
    }


    .status-text {
        font-family: var(--font-display);
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        white-space: nowrap;

        transition:
            color 0.3s ease,
            text-shadow 0.3s ease;
    }


    .status-text.enabled {
        color: var(--on);

        text-shadow: 0 0 10px rgba(92, 200, 255, 0.6);

        animation: statusPulse 2.2s ease-in-out infinite;
    }


    .status-text.disabled {
        color: var(--off);
    }


    @keyframes statusPulse {
        0%, 100% { opacity: 1; }
        50%      { opacity: 0.65; }
    }


    /* =====================================================
       TOGGLE SWITCH
       ===================================================== */

    .switch {
        position: relative;
        display: inline-block;
        margin-top: 0;

        width: 46px;
        height: 24px;
    }


    .switch input {
        opacity: 0;
        width: 0;
        height: 0;
    }


    .slider {
        position: absolute;
        cursor: pointer;
        inset: 0;

        background-color: #161d29;
        border: 1px solid rgba(150, 180, 215, 0.18);
        border-radius: 34px;

        transition: 0.3s;
    }


    .slider:before {
        position: absolute;
        content: "";

        height: 16px;
        width: 16px;

        left: 3px;
        bottom: 3px;

        background-color: #8a96a8;
        border-radius: 50%;

        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.4);

        transition: 0.3s;
    }


    input:checked + .slider {
        background: linear-gradient(90deg, #1d6fa8, var(--bolt));
        border-color: rgba(92, 200, 255, 0.8);

        box-shadow: 0 0 14px rgba(92, 200, 255, 0.45);
    }


    input:checked + .slider:before {
        transform: translateX(22px);

        background-color: #ffffff;
        box-shadow: 0 0 8px rgba(207, 238, 255, 0.9);
    }


    input:not(:checked) + .slider {
        border-color: rgba(255, 77, 98, 0.45);
    }


    input:not(:checked) + .slider:before {
        background-color: var(--off);
        box-shadow: 0 0 6px rgba(255, 77, 98, 0.5);
    }


    /* =====================================================
       VIEW AREA
       ===================================================== */

    .view-container {
        flex: 1;

        display: flex;
        justify-content: center;
        align-items: center;

        padding: 40px 20px;

        overflow-y: auto;

        position: relative;
        z-index: 1;
    }


    .view {
        display: none;
        width: 100%;
        justify-content: center;
    }


    .view.active {
        display: flex;
        animation: fadeIn 0.45s ease forwards;
    }


    @keyframes fadeIn {

        from {
            opacity: 0;
            transform: translateY(14px);
            filter: blur(4px);
        }

        to {
            opacity: 1;
            transform: translateY(0);
            filter: blur(0);
        }
    }


    /* =====================================================
       CARD
       ===================================================== */

    .card {
        position: relative;

        background:
            linear-gradient(180deg, rgba(150, 180, 215, 0.06), transparent 30%),
            var(--panel);

        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);

        padding: 34px;

        max-width: 460px;
        width: 100%;

        border: 1px solid var(--panel-border);
        border-radius: var(--radius);

        box-shadow:
            0 30px 60px -20px rgba(0, 0, 0, 0.8),
            inset 0 1px 0 rgba(255, 255, 255, 0.05);

        overflow: hidden;

        transition:
            border-color 0.25s ease,
            box-shadow 0.25s ease;
    }


    /* Lightning edge along the top */

    .card::before {
        content: "";

        position: absolute;
        top: 0;
        left: 10%;
        right: 10%;
        height: 1px;

        background: linear-gradient(90deg, transparent, var(--bolt), var(--bolt-bright), var(--bolt), transparent);

        box-shadow: 0 0 12px rgba(92, 200, 255, 0.8);

        opacity: 0.7;
    }


    .card:hover {
        border-color: var(--panel-border-strong);

        box-shadow:
            0 30px 60px -20px rgba(0, 0, 0, 0.8),
            0 0 40px rgba(92, 200, 255, 0.07),
            inset 0 1px 0 rgba(255, 255, 255, 0.07);
    }


    h2 {
        margin: 0 0 20px 0;

        font-family: var(--font-display);
        font-size: 1.05rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;

        color: var(--text-primary);

        padding-bottom: 16px;
        border-bottom: 1px solid var(--panel-border);

        display: flex;
        align-items: center;
        gap: 10px;
    }


    .card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;

        margin: 0 0 20px 0;
        padding-bottom: 16px;

        border-bottom: 1px solid var(--panel-border);
    }


    .card-header h2 {
        margin: 0;
        padding: 0;
        border: none;

        font-size: 0.9rem;
        letter-spacing: 0.06em;
        white-space: nowrap;
    }


    /* Bolt marker before headings */

    h2::before {
        content: "";

        width: 10px;
        height: 14px;

        background: var(--bolt);

        clip-path: polygon(60% 0, 0 58%, 45% 58%, 30% 100%, 100% 38%, 55% 38%);

        filter: drop-shadow(0 0 4px var(--bolt));

        flex-shrink: 0;
    }


    label {
        display: block;

        margin-top: 18px;

        font-weight: 600;
        font-size: 0.78rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;

        color: var(--text-muted);
    }


    input.form-input {
        width: 100%;

        padding: 11px 14px;
        margin-top: 8px;

        background: rgba(3, 4, 8, 0.65);
        color: var(--text-primary);

        border: 1px solid var(--panel-border);
        border-radius: 8px;

        font-family: var(--font-mono);
        font-size: 0.95rem;

        outline: none;
        caret-color: var(--bolt);

        transition: all 0.2s ease;
    }


    input.form-input:hover {
        border-color: var(--panel-border-strong);
    }


    input.form-input:focus {
        border-color: rgba(92, 200, 255, 0.7);

        box-shadow:
            0 0 0 3px rgba(92, 200, 255, 0.12),
            0 0 18px rgba(92, 200, 255, 0.15);
    }


    button.btn-primary {
        position: relative;
        overflow: hidden;

        margin-top: 28px;
        width: 100%;
        padding: 14px;

        background: linear-gradient(180deg, #2a8fd0, #17608f);
        color: #ffffff;

        border: 1px solid rgba(92, 200, 255, 0.5);
        border-radius: 10px;

        cursor: pointer;

        font-family: var(--font-display);
        font-weight: 700;
        font-size: 0.85rem;
        letter-spacing: 0.18em;
        text-transform: uppercase;

        box-shadow:
            0 8px 24px -8px rgba(92, 200, 255, 0.5),
            inset 0 1px 0 rgba(255, 255, 255, 0.25);

        transition:
            box-shadow 0.2s ease,
            transform 0.1s ease,
            filter 0.2s ease;
    }


    /* Flash sweep on hover */

    button.btn-primary::after {
        content: "";

        position: absolute;
        top: 0;
        bottom: 0;
        left: -60%;
        width: 40%;

        background: linear-gradient(100deg, transparent, rgba(255, 255, 255, 0.35), transparent);

        transform: skewX(-20deg);
        transition: left 0.5s ease;
    }


    button.btn-primary:hover {
        filter: brightness(1.12);

        box-shadow:
            0 10px 30px -6px rgba(92, 200, 255, 0.7),
            inset 0 1px 0 rgba(255, 255, 255, 0.3);
    }


    button.btn-primary:hover::after {
        left: 120%;
    }


    button.btn-primary:active {
        transform: scale(0.98);
    }


    .info-box {
        background: rgba(3, 4, 8, 0.65);

        padding: 11px 14px;
        margin-top: 8px;

        border: 1px solid var(--panel-border);
        border-left: 2px solid var(--bolt);
        border-radius: 8px;

        font-family: var(--font-mono);
        font-size: 0.85rem;

        color: var(--bolt-bright);

        word-break: break-all;
    }


    /* =====================================================
       DASHBOARD GRID
       ===================================================== */

    .view.active {
        margin: auto 0;
    }


    .dashboard-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 24px;

        width: 100%;
        max-width: 960px;
    }


    .dashboard-grid .card {
        max-width: none;
    }


    .dashboard-grid .license-card {
        grid-column: 1 / -1;
    }


    @media (max-width: 1100px) {
        .dashboard-grid {
            grid-template-columns: minmax(0, 1fr);
            max-width: 460px;
        }
    }


    /* =====================================================
       LICENSE CARD
       ===================================================== */

    .license-user {
        font-family: var(--font-mono);
        font-size: 0.8rem;
        color: var(--text-muted);
    }


    .license-row {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 24px;
        flex-wrap: wrap;
    }


    .license-label {
        font-weight: 600;
        font-size: 0.78rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--text-muted);
    }


    .license-time {
        margin-top: 6px;

        font-family: var(--font-display);
        font-size: 2rem;
        font-weight: 700;
        letter-spacing: 0.04em;

        color: var(--bolt-bright);
        text-shadow: 0 0 18px rgba(92, 200, 255, 0.45);
    }


    .license-time.expired {
        color: var(--off);
        text-shadow: 0 0 14px rgba(255, 77, 98, 0.4);
    }


    .redeem-form {
        display: flex;
        gap: 10px;

        flex: 1;
        min-width: 280px;
        max-width: 480px;
    }


    .redeem-form input.form-input {
        margin-top: 0;
        text-transform: uppercase;
    }


    .redeem-form button.btn-primary {
        margin-top: 0;
        width: auto;
        padding: 0 22px;
        flex-shrink: 0;
    }


    .form-msg {
        min-height: 1.2em;
        margin-top: 12px;

        font-size: 0.9rem;
        font-weight: 600;
    }


    .form-msg.ok {
        color: var(--on);
    }


    .form-msg.err {
        color: var(--off);
    }


    /* =====================================================
       LOCKED STATE
       ===================================================== */

    .card.locked form,
    .card.locked .card-toggle {
        opacity: 0.3;
        filter: grayscale(1);
        pointer-events: none;
    }


    .card.locked::after {
        content: "LOCKED \\2014  REDEEM A KEY";

        position: absolute;
        inset: 0;

        display: flex;
        align-items: center;
        justify-content: center;

        background: rgba(6, 8, 13, 0.45);

        font-family: var(--font-display);
        font-weight: 700;
        font-size: 0.9rem;
        letter-spacing: 0.18em;

        color: var(--off);
        text-shadow: 0 0 12px rgba(255, 77, 98, 0.5);
    }


    /* =====================================================
       LOGIN
       ===================================================== */

    .auth-card {
        max-width: 420px;
    }


    .auth-tabs {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px;

        padding: 4px;
        margin-bottom: 8px;

        background: rgba(0, 0, 0, 0.3);
        border: 1px solid var(--panel-border);
        border-radius: 10px;
    }


    .auth-tab {
        padding: 10px;

        background: none;
        border: none;
        border-radius: 8px;

        color: var(--text-muted);

        font-family: var(--font-display);
        font-weight: 700;
        font-size: 0.8rem;
        letter-spacing: 0.14em;
        text-transform: uppercase;

        cursor: pointer;
        transition: all 0.2s ease;
    }


    .auth-tab.active {
        background: rgba(92, 200, 255, 0.14);
        color: var(--bolt-bright);
    }


    .auth-card button:disabled,
    .auth-card input:disabled {
        opacity: 0.45;
        cursor: not-allowed;
    }


    .integrity-banner {
        margin-bottom: 16px;
        padding: 12px 14px;

        background: rgba(239, 68, 68, 0.12);
        border: 1px solid var(--off);
        border-radius: 10px;

        color: var(--off);

        font-size: 0.9rem;
        font-weight: 600;
    }


    .auth-hwid {
        margin-top: 18px;

        font-family: var(--font-mono);
        font-size: 0.72rem;
        color: var(--text-muted);

        word-break: break-all;
    }


    /* =====================================================
       ADMIN PANEL
       ===================================================== */

    .admin-card {
        max-width: 1180px;
    }


    .admin-stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 14px;

        margin-bottom: 28px;
    }


    .stat-tile {
        padding: 14px 16px;

        background: rgba(3, 4, 8, 0.55);
        border: 1px solid var(--panel-border);
        border-radius: 10px;
    }


    .stat-value {
        margin-top: 6px;

        font-family: var(--font-display);
        font-size: 1.6rem;
        font-weight: 700;

        color: var(--bolt-bright);
    }


    .stat-sub {
        margin-top: 2px;

        font-family: var(--font-mono);
        font-size: 0.75rem;
        color: var(--text-muted);
    }


    .admin-section-title {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;

        margin: 8px 0 12px;
    }


    .admin-section-title h3 {
        font-family: var(--font-display);
        font-size: 0.85rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;

        color: var(--text-primary);
    }


    .admin-tools {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
    }


    .admin-tools .form-input,
    .admin-tools select.form-input {
        width: auto;
        margin-top: 0;
        padding: 8px 12px;
        font-size: 0.85rem;
    }


    select.form-input {
        width: 100%;
        padding: 11px 14px;
        margin-top: 8px;

        background: rgba(3, 4, 8, 0.65);
        color: var(--text-primary);

        border: 1px solid var(--panel-border);
        border-radius: 8px;

        font-family: var(--font-mono);
        outline: none;
    }


    .table-wrap {
        overflow-x: auto;

        margin-bottom: 30px;

        border: 1px solid var(--panel-border);
        border-radius: 10px;
    }


    .admin-table {
        width: 100%;
        border-collapse: collapse;

        font-size: 0.88rem;
    }


    .admin-table th {
        position: sticky;
        top: 0;

        padding: 10px 12px;

        background: #0d121b;

        text-align: left;

        font-family: var(--font-display);
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;

        color: var(--text-muted);

        white-space: nowrap;
    }


    .admin-table td {
        padding: 10px 12px;

        border-top: 1px solid var(--panel-border);

        vertical-align: middle;
        white-space: nowrap;
    }


    .admin-table tr:hover td {
        background: rgba(150, 180, 215, 0.04);
    }


    .admin-table .mono {
        font-family: var(--font-mono);
        font-size: 0.8rem;
    }


    .admin-table .muted {
        color: var(--text-muted);
    }


    .user-name {
        margin-right: 8px;
        font-weight: 600;
    }


    .hwid-cell {
        max-width: 130px;
        overflow: hidden;
        text-overflow: ellipsis;
    }


    .badge {
        display: inline-block;

        padding: 2px 8px;
        margin-right: 4px;

        border-radius: 999px;
        border: 1px solid currentColor;

        font-family: var(--font-display);
        font-size: 0.62rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
    }


    .badge.active  { color: var(--on); }
    .badge.expired { color: var(--text-muted); }
    .badge.banned  { color: var(--off); }
    .badge.admin   { color: var(--storm-violet); }


    .online-dot {
        display: inline-block;

        width: 7px;
        height: 7px;
        margin-right: 6px;

        border-radius: 50%;

        background: #3a4455;
    }


    .online-dot.on {
        background: var(--on);
        box-shadow: 0 0 6px var(--on);
    }


    .row-actions {
        display: flex;
        align-items: center;
        gap: 6px;
    }


    .row-actions input.form-input {
        width: 70px;
        margin-top: 0;
        padding: 6px 8px;
        font-size: 0.8rem;
    }


    .btn-sm {
        padding: 6px 10px;

        background: rgba(150, 180, 215, 0.08);
        color: var(--text-primary);

        border: 1px solid var(--panel-border-strong);
        border-radius: 7px;

        font-family: var(--font-display);
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;

        cursor: pointer;
        white-space: nowrap;

        transition: all 0.15s ease;
    }


    .btn-sm:hover {
        border-color: var(--bolt);
        color: var(--bolt-bright);
    }


    .btn-sm.primary {
        background: linear-gradient(180deg, #2a8fd0, #17608f);
        border-color: rgba(92, 200, 255, 0.5);
    }


    .btn-sm.danger {
        color: var(--off);
        border-color: rgba(255, 77, 98, 0.4);
    }


    .btn-sm.danger:hover {
        background: rgba(255, 77, 98, 0.1);
        color: #ff8595;
    }


    .btn-sm:disabled {
        opacity: 0.4;
        cursor: default;
    }


    .new-keys {
        width: 100%;
        min-height: 90px;
        margin-bottom: 14px;

        padding: 10px 12px;

        background: rgba(3, 4, 8, 0.65);
        color: var(--bolt-bright);

        border: 1px solid rgba(92, 200, 255, 0.4);
        border-radius: 8px;

        font-family: var(--font-mono);
        font-size: 0.85rem;

        resize: vertical;
    }


    .empty-row td {
        text-align: center;
        color: var(--text-muted);
        padding: 22px;
    }


    @media (prefers-reduced-motion: reduce) {
        *,
        *::before,
        *::after {
            animation: none !important;
            transition: none !important;
        }
    }

</style>


<!-- =====================================================
     SVG ICONS
     ===================================================== -->

<svg style="display:none">
    <defs>

        <symbol
            id="icon-home"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round">

            <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>

            <polyline points="9 22 9 12 15 12 15 22"></polyline>

        </symbol>


        <symbol
            id="icon-settings"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round">

            <circle cx="12" cy="12" r="3"></circle>

            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>

        </symbol>


        <symbol
            id="icon-logout"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round">

            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>

            <polyline points="16 17 21 12 16 7"></polyline>

            <line x1="21" y1="12" x2="9" y2="12"></line>

        </symbol>


        <symbol
            id="icon-menu"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round">

            <line x1="3" y1="12" x2="21" y2="12"></line>

            <line x1="3" y1="6" x2="21" y2="6"></line>

            <line x1="3" y1="18" x2="21" y2="18"></line>

        </symbol>


        <symbol
            id="icon-zap"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round">

            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>

        </symbol>

        <symbol
            id="icon-power"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round">

            <path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path>

            <line x1="12" y1="2" x2="12" y2="12"></line>

        </symbol>


        <symbol
            id="icon-shield"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round">

            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>

        </symbol>

    </defs>
</svg>
"""


# =========================================================
# FLASK SERVER
# =========================================================

app = Flask(__name__)


def html_escape(value):

    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# =========================================================
# SHARED JS
# =========================================================

COMMON_JS = """
<script>

async function postJSON(url, data) {

    const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data || {})
    });

    let body = {};

    try { body = await res.json(); } catch (e) {}

    return { ok: res.ok, body: body };

}


function showMsg(el, text, ok) {

    el.innerText = text;

    el.classList.remove("ok", "err");

    el.classList.add(ok ? "ok" : "err");

}


async function exitApp() {

    document.body.innerHTML = `

        <div
            style="
                display:flex;
                height:100vh;
                width:100vw;
                justify-content:center;
                align-items:center;
                background:#06080d;
                color:#cfeeff;
                font-family:Oxanium, sans-serif;
                letter-spacing:0.1em;
                text-shadow:0 0 10px rgba(92,200,255,0.6);
                font-size:1.5rem;
                font-weight:bold;
            "
        >
            Application Closed.
            You can close this window.
        </div>

    `;


    try {

        await fetch("/api/shutdown", { method: "POST" });

    }

    catch (error) {}

}

</script>
"""


# =========================================================
# LOGIN PAGE
# =========================================================

LOGIN_PAGE = """
<!DOCTYPE html>

<html lang="en">

<head>

    <meta charset="UTF-8">

    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <title>Yakuza Solutions</title>

    __COMMON_CSS__

</head>


<body>


<main class="main-wrapper">


    <header class="topbar">

        <div class="topbar-left">

            <div class="brand-title">
                Yakuza Solutions
            </div>

        </div>

    </header>


    <div class="view-container">

        <div class="view active">

            <div class="card auth-card">


                <h2 id="authTitle">
                    Sign In
                </h2>


                __INTEGRITY__


                <div class="auth-tabs">

                    <button class="auth-tab active" id="tabLogin" onclick="setMode('login')">
                        Login
                    </button>

                    <button class="auth-tab" id="tabRegister" onclick="setMode('register')">
                        Register
                    </button>

                </div>


                <form id="authForm" onsubmit="submitAuth(event)">


                    <label>
                        Username:
                    </label>

                    <input
                        class="form-input"
                        type="text"
                        id="username"
                        autocomplete="username"
                        maxlength="24"
                        required
                    >


                    <label>
                        Password:
                    </label>

                    <input
                        class="form-input"
                        type="password"
                        id="password"
                        autocomplete="current-password"
                        required
                    >


                    <button
                        type="submit"
                        class="btn-primary"
                        id="authBtn"
                    >
                        Login
                    </button>


                </form>


                <div class="form-msg" id="authMsg"></div>


                <div class="auth-hwid">
                    HWID: __HWID__
                </div>


                <button class="btn-sm auth-exit" onclick="exitApp()">
                    Exit App
                </button>


            </div>

        </div>

    </div>

</main>


__COMMON_JS__


<script>

let mode = "login";


// A modified or outdated build can't log in, so lock the form.
if (document.getElementById("integrityMsg")) {

    document
        .querySelectorAll(".auth-tab, #authForm input, #authForm button")
        .forEach(el => { el.disabled = true; });

}


function setMode(next) {

    mode = next;

    const isLogin = mode === "login";

    document.getElementById("tabLogin").classList.toggle("active", isLogin);
    document.getElementById("tabRegister").classList.toggle("active", !isLogin);

    document.getElementById("authTitle").innerText = isLogin ? "Sign In" : "Create Account";
    document.getElementById("authBtn").innerText = isLogin ? "Login" : "Register";

    document.getElementById("password").autocomplete =
        isLogin ? "current-password" : "new-password";

    document.getElementById("authMsg").innerText = "";

}


async function submitAuth(event) {

    event.preventDefault();

    const btn = document.getElementById("authBtn");
    const msg = document.getElementById("authMsg");

    btn.disabled = true;

    try {

        const res = await postJSON("/api/" + mode, {
            username: document.getElementById("username").value,
            password: document.getElementById("password").value
        });

        if (res.ok) {
            window.location.reload();
            return;
        }

        showMsg(msg, res.body.error || "Something went wrong.", false);

    }

    catch (error) {

        showMsg(msg, "Couldn't reach the app.", false);

    }

    btn.disabled = false;

}

</script>


</body>

</html>
"""


# =========================================================
# DASHBOARD JS
# =========================================================

DASHBOARD_JS = """
<script>


// =========================================================
// SIDEBAR
// =========================================================

function toggleSidebar() {

    document
        .getElementById("sidebar")
        .classList
        .toggle("collapsed");

}


// =========================================================
// VIEW SWITCHING
// =========================================================

function switchView(viewName, element) {

    document
        .querySelectorAll(".nav-item")
        .forEach(el => {
            el.classList.remove("active");
        });


    element.classList.add("active");


    document
        .querySelectorAll(".view")
        .forEach(el => {
            el.classList.remove("active");
        });


    document
        .getElementById("view-" + viewName)
        .classList.add("active");

}


// =========================================================
// LICENSE COUNTDOWN
// =========================================================

let remaining = Number(
    document.getElementById("licenseTime").dataset.remaining
);

let lastTick = performance.now();


function formatRemaining(seconds) {

    seconds = Math.floor(seconds);

    if (seconds <= 0) {
        return "Expired";
    }

    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;

    const pad = n => String(n).padStart(2, "0");

    return (d > 0 ? d + "d " : "") + pad(h) + "h " + pad(m) + "m " + pad(s) + "s";

}


function renderLicense() {

    const el = document.getElementById("licenseTime");

    // The page may have been replaced (e.g. after Exit).
    if (!el) return;

    const locked = remaining <= 0;

    el.innerText = formatRemaining(remaining);

    el.classList.toggle("expired", locked);

    document
        .querySelectorAll(".card.lockable")
        .forEach(card => card.classList.toggle("locked", locked));

}


setInterval(() => {

    const t = performance.now();

    remaining = Math.max(0, remaining - (t - lastTick) / 1000);

    lastTick = t;

    renderLicense();

}, 250);


async function syncLicense() {

    try {

        const res = await postJSON("/api/license");

        if (res.body.logged_in === false) {
            window.location.reload();
            return;
        }

        if (res.ok) {
            remaining = res.body.remaining_seconds;
            lastTick = performance.now();
            renderLicense();
        }

    }

    catch (error) {}

}


setInterval(syncLicense, 30000);

renderLicense();


// =========================================================
// REDEEM KEY
// =========================================================

async function redeemKey(event) {

    event.preventDefault();

    const input = document.getElementById("license_key");
    const btn = document.getElementById("redeemBtn");
    const msg = document.getElementById("redeemMsg");

    btn.disabled = true;

    try {

        const res = await postJSON("/api/redeem", { key: input.value });

        if (res.ok) {

            remaining = res.body.remaining_seconds;
            lastTick = performance.now();
            renderLicense();

            input.value = "";

            showMsg(msg, "Key redeemed: +" + res.body.added_days + " day(s) added.", true);

        }

        else {

            showMsg(msg, res.body.error || "Couldn't redeem that key.", false);

        }

    }

    catch (error) {

        showMsg(msg, "Couldn't reach the app.", false);

    }

    btn.disabled = false;

}


// =========================================================
// TOGGLE FEATURE
// =========================================================

function setStatus(statusText, on) {

    statusText.innerText = on ? "Enabled" : "Disabled";

    statusText.classList.toggle("enabled", on);

    statusText.classList.toggle("disabled", !on);

}


async function toggleFeature(checkbox, feature, statusId) {

    const statusText = document.getElementById(statusId);

    setStatus(statusText, checkbox.checked);


    try {

        const res = await postJSON("/api/toggle", {
            feature: feature,
            active: checkbox.checked
        });

        if (!res.ok) {
            checkbox.checked = !checkbox.checked;
            setStatus(statusText, checkbox.checked);
        }

    }

    catch (error) {

        console.error("Failed to update " + feature + " state:", error);

    }

}


// =========================================================
// SAVE SETTINGS
// =========================================================

async function postSettings(data, btn) {

    try {

        const res = await postJSON("/api/update", data);


        if (res.ok) {

            const originalText = btn.innerText;

            btn.innerText = "Settings Saved!";

            btn.style.background = "#1f9d6b";


            setTimeout(() => {

                btn.innerText = originalText;

                btn.style.background = "";

            }, 2000);

        }

    }

    catch (error) {

        console.error("Failed to save settings:", error);

    }

}


async function saveSettings(event) {

    event.preventDefault();

    await postSettings(
        {
            trigger_key: document.getElementById("trigger_key").value,
            target_key: document.getElementById("target_key").value,
            delay_ms: document.getElementById("delay_ms").value
        },
        document.getElementById("saveBtn")
    );

}


async function saveAutoBuild(event) {

    event.preventDefault();

    await postSettings(
        {
            auto_build_key: document.getElementById("auto_build_key").value,
            auto_build_delay_ms: document.getElementById("auto_build_delay_ms").value
        },
        document.getElementById("autoBuildSaveBtn")
    );

}


// =========================================================
// LOGOUT
// =========================================================

async function logout() {

    try {

        await postJSON("/api/logout");

    }

    catch (error) {}


    window.location.href = "/";

}


</script>
"""


# =========================================================
# ADMIN PANEL (only rendered for admin accounts)
# =========================================================

ADMIN_NAV = """
        <a
            class="nav-item"
            onclick="switchView('admin', this); loadAdmin();"
        >

            <svg width="20" height="20">
                <use href="#icon-shield"></use>
            </svg>

            <span>Admin Panel</span>

        </a>
"""


ADMIN_VIEW = """
        <!-- ADMIN PANEL -->

        <div
            id="view-admin"
            class="view"
        >

            <div class="card admin-card">


                <div class="card-header">

                    <h2>
                        Admin Panel
                    </h2>

                    <button class="btn-sm" onclick="loadAdmin()">
                        Refresh
                    </button>

                </div>


                <div class="admin-stats" id="adminStats"></div>


                <!-- USERS -->

                <div class="admin-section-title">

                    <h3>Users</h3>

                    <div class="admin-tools">

                        <input
                            class="form-input"
                            type="text"
                            id="userSearch"
                            placeholder="Search username / HWID"
                            oninput="renderUsers()"
                        >

                    </div>

                </div>


                <div class="table-wrap">

                    <table class="admin-table">

                        <thead>
                            <tr>
                                <th>User</th>
                                <th>Time Left</th>
                                <th>HWID</th>
                                <th>Last Login</th>
                                <th>Keys</th>
                                <th>Time (days)</th>
                                <th>Account</th>
                            </tr>
                        </thead>

                        <tbody id="usersBody"></tbody>

                    </table>

                </div>


                <!-- KEYS -->

                <div class="admin-section-title">

                    <h3>License Keys</h3>

                    <div class="admin-tools">

                        <select class="form-input" id="genType">
                            <option value="day">Day</option>
                            <option value="week">Week</option>
                            <option value="month">Month</option>
                        </select>

                        <input
                            class="form-input"
                            type="number"
                            id="genCount"
                            value="5"
                            min="1"
                            max="100"
                            style="width: 80px"
                        >

                        <button class="btn-sm primary" onclick="generateKeys()">
                            Generate
                        </button>

                        <select class="form-input" id="keyFilter" onchange="renderKeys()">
                            <option value="all">All keys</option>
                            <option value="unused">Unused</option>
                            <option value="used">Used</option>
                        </select>

                    </div>

                </div>


                <textarea
                    class="new-keys"
                    id="newKeys"
                    readonly
                    style="display: none"
                ></textarea>


                <div class="table-wrap">

                    <table class="admin-table">

                        <thead>
                            <tr>
                                <th>Key</th>
                                <th>Type</th>
                                <th>Created</th>
                                <th>Redeemed By</th>
                                <th>Redeemed At</th>
                                <th></th>
                            </tr>
                        </thead>

                        <tbody id="keysBody"></tbody>

                    </table>

                </div>


                <div class="form-msg" id="adminMsg"></div>


            </div>

        </div>
"""


ADMIN_JS = """
<script>


let adminData = null;


function el(tag, attrs, children) {

    const node = document.createElement(tag);

    Object.entries(attrs || {}).forEach(([k, v]) => {

        if (k === "text") node.textContent = v;
        else if (k === "onclick") node.addEventListener("click", v);
        else node.setAttribute(k, v);

    });

    (children || []).forEach(c => node.appendChild(c));

    return node;

}


function fmtDate(ts) {

    return ts
        ? new Date(ts * 1000).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })
        : "-";

}


function adminMsg(text, ok) {

    showMsg(document.getElementById("adminMsg"), text, ok);

}


async function adminCall(action, data) {

    const res = await postJSON("/api/admin/" + action, data);

    if (!res.ok) {
        adminMsg(res.body.error || "Admin request failed.", false);
    }

    return res;

}


async function loadAdmin() {

    const res = await adminCall("overview", {});

    if (!res.ok) return;

    adminData = res.body;

    renderStats();
    renderUsers();
    renderKeys();

}


function renderStats() {

    const s = adminData.stats;

    const tiles = [
        ["Users", s.users, ""],
        ["Active Licenses", s.active_licenses, ""],
        ["Banned", s.banned, ""],
        ["Keys", s.keys_total,
            "unused: " + s.keys_unused.day + "d / " + s.keys_unused.week + "w / " + s.keys_unused.month + "m"],
    ];

    const box = document.getElementById("adminStats");

    box.replaceChildren(...tiles.map(([label, value, sub]) =>
        el("div", { class: "stat-tile" }, [
            el("div", { class: "license-label", text: label }),
            el("div", { class: "stat-value", text: String(value) }),
            el("div", { class: "stat-sub", text: sub }),
        ])
    ));

}


function renderUsers() {

    const body = document.getElementById("usersBody");

    const q = document.getElementById("userSearch").value.trim().toLowerCase();

    const users = adminData.users.filter(u =>
        !q ||
        u.username.toLowerCase().includes(q) ||
        (u.hwid || "").toLowerCase().includes(q)
    );


    if (!users.length) {

        body.replaceChildren(
            el("tr", { class: "empty-row" }, [el("td", { colspan: "7", text: "No users found." })])
        );

        return;

    }


    body.replaceChildren(...users.map(u => {

        const badges = [];

        if (u.is_admin) badges.push(el("span", { class: "badge admin", text: "Admin" }));

        if (u.banned) badges.push(el("span", { class: "badge banned", text: "Banned" }));
        else if (u.remaining_seconds > 0) badges.push(el("span", { class: "badge active", text: "Active" }));
        else badges.push(el("span", { class: "badge expired", text: "Expired" }));


        const days = el("input", {
            class: "form-input",
            type: "number",
            step: "any",
            value: "1",
            title: "Days (decimals allowed, e.g. 0.5)"
        });

        const timeActions = el("div", { class: "row-actions" }, [
            days,
            el("button", { class: "btn-sm", text: "Add",
                onclick: () => changeTime(u.username, "addtime", Number(days.value)) }),
            el("button", { class: "btn-sm", text: "Take",
                onclick: () => changeTime(u.username, "addtime", -Number(days.value)) }),
            el("button", { class: "btn-sm", text: "Set",
                onclick: () => changeTime(u.username, "settime", Number(days.value)) }),
        ]);


        const banBtn = el("button", {
            class: "btn-sm danger",
            text: u.banned ? "Unban" : "Ban",
            onclick: () => setBan(u.username, !u.banned)
        });

        if (u.is_admin) banBtn.disabled = true;


        const accountActions = el("div", { class: "row-actions" }, [
            banBtn,
            el("button", { class: "btn-sm", text: "Reset HWID",
                onclick: () => resetHwid(u.username) }),
        ]);


        return el("tr", {}, [
            el("td", { title: "Joined " + fmtDate(u.created_at) }, [
                el("span", { class: "online-dot" + (u.online ? " on" : ""),
                    title: u.online ? "Has an active session" : "No active session" }),
                el("span", { class: "user-name", text: u.username }),
                ...badges,
            ]),
            el("td", { class: "mono", text: formatRemaining(u.remaining_seconds) }),
            el("td", { class: "mono muted hwid-cell", title: u.hwid || "", text: u.hwid || "-" }),
            el("td", { class: "muted", text: fmtDate(u.last_login) }),
            el("td", { text: String(u.keys_redeemed) }),
            el("td", {}, [timeActions]),
            el("td", {}, [accountActions]),
        ]);

    }));

}


function renderKeys() {

    const body = document.getElementById("keysBody");

    const filter = document.getElementById("keyFilter").value;

    const keys = adminData.keys.filter(k =>
        filter === "all" ||
        (filter === "unused" && !k.redeemed_by) ||
        (filter === "used" && k.redeemed_by)
    );


    if (!keys.length) {

        body.replaceChildren(
            el("tr", { class: "empty-row" }, [el("td", { colspan: "6", text: "No keys." })])
        );

        return;

    }


    body.replaceChildren(...keys.map(k => {

        const actions = [];

        if (!k.redeemed_by) {

            actions.push(el("button", { class: "btn-sm", text: "Copy",
                onclick: () => navigator.clipboard.writeText(k.key).then(() => adminMsg("Copied " + k.key, true)) }));

            actions.push(el("button", { class: "btn-sm danger", text: "Delete",
                onclick: () => deleteKey(k.key) }));

        }


        return el("tr", {}, [
            el("td", { class: "mono", text: k.key }),
            el("td", { text: k.key_type + " (" + k.duration_days + "d)" }),
            el("td", { class: "muted", text: fmtDate(k.created_at) }),
            el("td", { text: k.redeemed_by || "-" }),
            el("td", { class: "muted", text: fmtDate(k.redeemed_at) }),
            el("td", {}, [el("div", { class: "row-actions" }, actions)]),
        ]);

    }));

}


async function changeTime(username, action, days) {

    if (!isFinite(days)) {
        adminMsg("Enter a number of days.", false);
        return;
    }

    const res = await adminCall(action, { username: username, days: days });

    if (res.ok) {
        adminMsg(username + " now has " + formatRemaining(res.body.remaining_seconds) + ".", true);
        loadAdmin();
        syncLicense();
    }

}


async function setBan(username, banned) {

    if (banned && !confirm("Ban " + username + "? They will be logged out and locked out.")) return;

    const res = await adminCall("ban", { username: username, banned: banned });

    if (res.ok) {
        adminMsg(username + (banned ? " banned." : " unbanned."), true);
        loadAdmin();
    }

}


async function resetHwid(username) {

    if (!confirm("Reset HWID for " + username + "? Their next login will lock to a new PC.")) return;

    const res = await adminCall("resethwid", { username: username });

    if (res.ok) {
        adminMsg("HWID reset for " + username + ".", true);
        loadAdmin();
    }

}


async function generateKeys() {

    const res = await adminCall("genkeys", {
        key_type: document.getElementById("genType").value,
        count: Number(document.getElementById("genCount").value)
    });

    if (!res.ok) return;


    const box = document.getElementById("newKeys");

    box.value = res.body.keys.join("\\n");

    box.style.display = "block";

    box.select();


    adminMsg("Generated " + res.body.keys.length + " key(s). They're selected above, ready to copy.", true);

    loadAdmin();

}


async function deleteKey(key) {

    if (!confirm("Delete unused key " + key + "?")) return;

    const res = await adminCall("deletekey", { key: key });

    if (res.ok) {
        adminMsg("Deleted " + key + ".", true);
        loadAdmin();
    }

}


</script>
"""


ADMIN_ACTIONS = {
    "overview", "addtime", "settime", "ban", "resethwid", "genkeys", "deletekey",
}


# =========================================================
# PAGES
# =========================================================

def render_login():

    message = check_integrity()

    banner = (
        f'<div class="integrity-banner" id="integrityMsg">{html_escape(message)}</div>'
        if message else ""
    )

    return (
        LOGIN_PAGE
        .replace("__COMMON_CSS__", COMMON_CSS)
        .replace("__COMMON_JS__", COMMON_JS)
        .replace("__INTEGRITY__", banner)
        .replace("__HWID__", html_escape(cached_hwid()))
    )


def toggle_html(input_id, status_id, feature, active):

    checked = "checked" if active else ""

    status_text = "Enabled" if active else "Disabled"

    status_class = "enabled" if active else "disabled"


    return f"""
                    <div class="card-toggle">

                        <label class="switch">

                            <input
                                type="checkbox"
                                id="{input_id}"
                                {checked}
                                onchange="toggleFeature(this, '{feature}', '{status_id}')"
                            >

                            <span class="slider"></span>

                        </label>


                        <span
                            class="status-text {status_class}"
                            id="{status_id}"
                        >
                            {status_text}
                        </span>

                    </div>
    """


@app.route("/")
def home():

    if not logged_in():
        return render_login()


    sys_os = f"{platform.system()} {platform.release()}"

    sys_node = platform.node()

    sys_processor = platform.processor() or "Unknown"

    public_ip = get_public_ip()

    hwid = cached_hwid()


    macro_toggle = toggle_html(
        "macroToggle", "macroStatus", "macro", config["active"]
    )

    auto_build_toggle = toggle_html(
        "autoBuildToggle", "autoBuildStatus", "auto_build", config["auto_build_active"]
    )


    username = html_escape(license_state["username"] or "")

    remaining = int(remaining_seconds())

    locked = "" if remaining > 0 else "locked"


    is_admin = license_state["is_admin"]

    admin_nav = ADMIN_NAV if is_admin else ""

    admin_view = ADMIN_VIEW if is_admin else ""

    admin_js = ADMIN_JS if is_admin else ""


    return f"""
<!DOCTYPE html>

<html lang="en">

<head>

    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <title>Yakuza Solutions</title>

    {COMMON_CSS}

</head>


<body>


<!-- =====================================================
     SIDEBAR
     ===================================================== -->

<nav class="sidebar" id="sidebar">

    <div class="sidebar-header">

        <a href="#" class="sidebar-logo">

            <svg width="28" height="28">
                <use href="#icon-zap"></use>
            </svg>

            <span>Yakuza Solutions</span>

        </a>

    </div>


    <div class="sidebar-nav">

        <a
            class="nav-item active"
            onclick="switchView('dashboard', this)"
        >

            <svg width="20" height="20">
                <use href="#icon-home"></use>
            </svg>

            <span>Dashboard</span>

        </a>


        {admin_nav}


        <a
            class="nav-item"
            onclick="switchView('settings', this)"
        >

            <svg width="20" height="20">
                <use href="#icon-settings"></use>
            </svg>

            <span>Hardware Info</span>

        </a>


        <a
            class="nav-item logout-btn"
            onclick="logout()"
        >

            <svg width="20" height="20">
                <use href="#icon-logout"></use>
            </svg>

            <span>Logout</span>

        </a>


        <a
            class="nav-item logout-btn exit-btn"
            onclick="exitApp()"
        >

            <svg width="20" height="20">
                <use href="#icon-power"></use>
            </svg>

            <span>Exit</span>

        </a>

    </div>

</nav>


<!-- =====================================================
     MAIN
     ===================================================== -->

<main class="main-wrapper">


    <!-- HEADER -->

    <header class="topbar">

        <div class="topbar-left">


            <!-- MENU -->

            <button
                class="menu-toggle"
                onclick="toggleSidebar()"
            >

                <svg width="24" height="24">
                    <use href="#icon-menu"></use>
                </svg>

            </button>


            <!-- BRAND -->

            <div class="brand-title">
                Yakuza Solutions
            </div>


        </div>

    </header>


    <!-- =================================================
         VIEWS
         ================================================= -->

    <div class="view-container">


        <!-- DASHBOARD -->

        <div
            id="view-dashboard"
            class="view active"
        >

            <div class="dashboard-grid">


                <!-- LICENSE -->

                <div class="card license-card">


                    <div class="card-header">

                        <h2>
                            License
                        </h2>

                        <span class="license-user">
                            {username}
                        </span>

                    </div>


                    <div class="license-row">


                        <div>

                            <div class="license-label">
                                Time Remaining
                            </div>

                            <div
                                class="license-time"
                                id="licenseTime"
                                data-remaining="{remaining}"
                            >
                                --
                            </div>

                        </div>


                        <form
                            class="redeem-form"
                            onsubmit="redeemKey(event)"
                        >

                            <input
                                class="form-input"
                                type="text"
                                id="license_key"
                                placeholder="Enter day / week / month key"
                                required
                            >

                            <button
                                type="submit"
                                class="btn-primary"
                                id="redeemBtn"
                            >
                                Redeem
                            </button>

                        </form>


                    </div>


                    <div class="form-msg" id="redeemMsg"></div>


                </div>


                <!-- HOTKEY -->

                <div class="card lockable {locked}">


                    <div class="card-header">

                        <h2>
                            Hotkey Configuration
                        </h2>

                        {macro_toggle}

                    </div>


                    <form
                        id="configForm"
                        onsubmit="saveSettings(event)"
                    >


                        <label>
                            Trigger Key:
                        </label>

                        <input
                            class="form-input"
                            type="text"
                            id="trigger_key"
                            value="{html_escape(config['trigger_key'])}"
                            maxlength="1"
                            required
                        >


                        <label>
                            Target Key:
                        </label>

                        <input
                            class="form-input"
                            type="text"
                            id="target_key"
                            value="{html_escape(config['target_key'])}"
                            maxlength="1"
                            required
                        >


                        <label>
                            Delay (ms):
                        </label>

                        <input
                            class="form-input"
                            type="number"
                            id="delay_ms"
                            value="{config['delay_ms']}"
                            min="0"
                            required
                        >


                        <button
                            type="submit"
                            class="btn-primary"
                            id="saveBtn"
                        >
                            Save Settings
                        </button>


                    </form>


                </div>


                <!-- AUTO BUILD -->

                <div class="card lockable {locked}">


                    <div class="card-header">

                        <h2>
                            Auto Build
                        </h2>

                        {auto_build_toggle}

                    </div>


                    <form
                        id="autoBuildForm"
                        onsubmit="saveAutoBuild(event)"
                    >


                        <label>
                            Keybind:
                        </label>

                        <input
                            class="form-input"
                            type="text"
                            id="auto_build_key"
                            value="{html_escape(config['auto_build_key'])}"
                            maxlength="1"
                            required
                        >


                        <label>
                            Delay (ms):
                        </label>

                        <input
                            class="form-input"
                            type="number"
                            id="auto_build_delay_ms"
                            value="{config['auto_build_delay_ms']}"
                            min="1"
                            required
                        >


                        <button
                            type="submit"
                            class="btn-primary"
                            id="autoBuildSaveBtn"
                        >
                            Save Settings
                        </button>


                    </form>


                </div>


            </div>

        </div>


        {admin_view}


        <!-- HARDWARE INFO -->

        <div
            id="view-settings"
            class="view"
        >

            <div class="card">


                <h2>
                    System Information
                </h2>


                <label>
                    Public IPv4 Address
                </label>

                <div class="info-box">
                    {html_escape(public_ip)}
                </div>


                <label>
                    Hardware ID (HWID)
                </label>

                <div class="info-box">
                    {html_escape(hwid)}
                </div>


                <label>
                    Operating System
                </label>

                <div class="info-box">
                    {html_escape(sys_os)}
                </div>


                <label>
                    Hostname
                </label>

                <div class="info-box">
                    {html_escape(sys_node)}
                </div>


                <label>
                    Processor
                </label>

                <div class="info-box">
                    {html_escape(sys_processor)}
                </div>


            </div>

        </div>


    </div>

</main>


{COMMON_JS}

{DASHBOARD_JS}

{admin_js}


</body>

</html>
"""


# =========================================================
# API - ACCOUNT / LICENSE
# =========================================================

def account_request(path):

    data = request.get_json(silent=True) or {}

    username = str(data.get("username", "")).strip()

    password = str(data.get("password", ""))


    if not username or not password:
        return jsonify({"error": "Enter a username and password."}), 400


    result, err, status = license_request(
        path, {"username": username, "password": password}
    )

    if result is None:
        return jsonify({"error": err}), status or 502


    apply_license(result, token=result["token"])

    return jsonify({"status": "success"})


@app.route("/api/login", methods=["POST"])
def account_login():

    return account_request("/api/login")


@app.route("/api/register", methods=["POST"])
def account_register():

    return account_request("/api/register")


@app.route("/api/license", methods=["POST"])
def license_status():

    if not logged_in():
        return jsonify({"logged_in": False}), 401


    return jsonify({
        "logged_in": True,
        "username": license_state["username"],
        "remaining_seconds": remaining_seconds(),
    })


@app.route("/api/logout", methods=["POST"])
def account_logout():

    token = license_state["token"]

    clear_license()


    # Also end the session on the license server. The local
    # logout already happened, so a failure here is ignored.
    if token:
        license_request("/api/logout", {"token": token})


    return jsonify({"status": "success"})


@app.route("/api/admin/<action>", methods=["POST"])
def admin_action(action):

    # Forwards admin requests to the license server, which checks
    # that this session really belongs to an admin.
    if action not in ADMIN_ACTIONS:
        return jsonify({"error": "Unknown admin action."}), 404

    if not (logged_in() and license_state["is_admin"]):
        return jsonify({"error": "Admin access required."}), 403


    data = request.get_json(silent=True) or {}

    result, err, status = license_request(
        "/api/admin/" + action, {**data, "token": license_state["token"]}
    )

    if result is None:
        return jsonify({"error": err}), status or 502


    # If the admin changed their own time, refresh the local
    # license right away instead of waiting for the next sync.
    if str(data.get("username", "")).lower() == (license_state["username"] or "").lower():

        own, _, _ = license_request(
            "/api/status", {"token": license_state["token"]}
        )

        if own:
            apply_license(own)


    return jsonify(result)


@app.route("/api/redeem", methods=["POST"])
def redeem_key():

    if not logged_in():
        return jsonify({"error": "Please log in first."}), 401


    data = request.get_json(silent=True) or {}

    key = str(data.get("key", "")).strip()

    if not key:
        return jsonify({"error": "Enter a license key."}), 400


    result, err, status = license_request(
        "/api/redeem", {"token": license_state["token"], "key": key}
    )

    if result is None:

        if status in (401, 403):
            clear_license()

        return jsonify({"error": err}), status or 502


    apply_license(result)

    return jsonify({
        "status": "success",
        "added_days": result.get("added_days", 0),
        "remaining_seconds": remaining_seconds(),
    })


# =========================================================
# API - UPDATE CONFIG
# =========================================================

@app.route("/api/update", methods=["POST"])
def update_config():

    if not license_active():
        return jsonify({
            "error": "No license time remaining."
        }), 403


    data = request.json

    if not data:
        return jsonify({
            "error": "Invalid JSON"
        }), 400


    config["trigger_key"] = (
        str(
            data.get(
                "trigger_key",
                config["trigger_key"]
            )
        )
        .lower()
    )


    config["target_key"] = (
        str(
            data.get(
                "target_key",
                config["target_key"]
            )
        )
        .lower()
    )


    try:

        config["delay_ms"] = float(
            data.get(
                "delay_ms",
                config["delay_ms"]
            )
        )

    except (ValueError, TypeError):

        pass


    config["auto_build_key"] = (
        str(
            data.get(
                "auto_build_key",
                config["auto_build_key"]
            )
        )
        .lower()
    )


    try:

        config["auto_build_delay_ms"] = max(
            1.0,
            float(
                data.get(
                    "auto_build_delay_ms",
                    config["auto_build_delay_ms"]
                )
            )
        )

    except (ValueError, TypeError):

        pass


    return jsonify({
        "status": "success"
    })


# =========================================================
# API - TOGGLE
# =========================================================

@app.route("/api/toggle", methods=["POST"])
def toggle_macro():

    data = request.json

    feature_keys = {
        "macro": "active",
        "auto_build": "auto_build_active",
    }

    key = feature_keys.get(
        (data or {}).get("feature", "macro")
    )

    if key is None:
        return jsonify({
            "error": "Unknown feature"
        }), 400


    if "active" in data:

        if data["active"] and not license_active():
            return jsonify({
                "error": "No license time remaining."
            }), 403


        config[key] = bool(
            data["active"]
        )


    return jsonify({
        "status": "success",

        "active":
            config[key]
    })


# =========================================================
# API - SHUTDOWN
# =========================================================

@app.route("/api/shutdown", methods=["POST"])
def shutdown():

    # End the license session too, so it isn't left open.
    token = license_state["token"]

    clear_license()

    if token:
        license_request("/api/logout", {"token": token})


    def close_server():

        time.sleep(0.5)

        os._exit(0)


    threading.Thread(
        target=close_server
    ).start()


    return jsonify({
        "status": "shutting down"
    })


# =========================================================
# SERVER
# =========================================================

def run_server():

    import logging

    log = logging.getLogger("werkzeug")

    log.setLevel(logging.ERROR)


    app.run(
        host="127.0.0.1",
        port=APP_PORT,
        debug=False,
        use_reloader=False
    )


# =========================================================
# KEYBOARD LISTENER
# =========================================================

def auto_build_loop():

    # While auto build is enabled, press the
    # keybind every auto_build_delay_ms.
    while True:

        if not (config["auto_build_active"] and license_active()):

            time.sleep(0.05)

            continue


        key = config["auto_build_key"]

        try:

            controller.press(key)

            controller.release(key)

        except Exception:

            pass


        time.sleep(
            config["auto_build_delay_ms"] / 1000.0
        )


def on_press(key):

    global is_pressed


    if not (config["active"] and license_active()):
        return


    char = getattr(key, "char", None)

    if char is None:
        return


    if char == config["trigger_key"] and not is_pressed:

        is_pressed = True


        time.sleep(
            config["delay_ms"] / 1000.0
        )


        # Make sure the macro wasn't disabled (or the
        # license didn't run out) during the delay.
        if config["active"] and license_active():

            controller.press(
                config["target_key"]
            )


def on_release(key):

    global is_pressed


    char = getattr(key, "char", None)

    if char is None:
        return


    if char == config["trigger_key"] and is_pressed:

        is_pressed = False

        controller.release(
            config["target_key"]
        )


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    # Print this build's hash for approvebuild on the license server.
    if "--hash" in sys.argv:

        print(app_hash())

        sys.exit(0)


    relaunch_without_console()

    redirect_output_to_log()


    # Opening the app again while it's already running just
    # brings up the dashboard instead of starting a second copy.
    if app_already_running():

        webbrowser.open(APP_URL)

        sys.exit(0)


    print(
        "Starting Yakuza Solutions control server "
        f"at {APP_URL}"
    )


    server_thread = threading.Thread(
        target=run_server,
        daemon=True
    )

    server_thread.start()


    threading.Thread(
        target=auto_build_loop,
        daemon=True
    ).start()


    threading.Thread(
        target=license_sync_loop,
        daemon=True
    ).start()


    time.sleep(1)


    webbrowser.open(APP_URL)


    with keyboard.Listener(
        on_press=on_press,
        on_release=on_release
    ) as listener:

        listener.join()

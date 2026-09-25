import threading
import time
import webbrowser
import platform
import subprocess
import uuid
import urllib.request
import urllib.error
import json
import os

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
}

license_lock = threading.Lock()


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


_hwid_cache = None


def cached_hwid():

    global _hwid_cache

    if _hwid_cache is None:
        _hwid_cache = get_hwid()

    return _hwid_cache


# =========================================================
# LICENSE CLIENT
# =========================================================

def license_request(path, payload):

    # Returns (response_json, error_message, http_status).
    body = json.dumps(
        {**payload, "hwid": cached_hwid()}
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
            message = json.loads(e.read().decode("utf8")).get("error")
        except Exception:
            message = None

        return None, message or f"License server error ({e.code}).", e.code

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


def clear_license():

    with license_lock:

        license_state["token"] = None
        license_state["username"] = None
        license_state["remaining"] = 0.0


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
        margin-bottom: 16px;

        color: #c46a76;
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


    .auth-hwid {
        margin-top: 18px;

        font-family: var(--font-mono);
        font-size: 0.72rem;
        color: var(--text-muted);

        word-break: break-all;
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


            </div>

        </div>

    </div>

</main>


__COMMON_JS__


<script>

let mode = "login";


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
# PAGES
# =========================================================

def render_login():

    return (
        LOGIN_PAGE
        .replace("__COMMON_CSS__", COMMON_CSS)
        .replace("__COMMON_JS__", COMMON_JS)
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
        port=5000,
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

    print(
        "Starting Yakuza Solutions control server "
        "at http://127.0.0.1:5000"
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


    webbrowser.open(
        "http://127.0.0.1:5000"
    )


    with keyboard.Listener(
        on_press=on_press,
        on_release=on_release
    ) as listener:

        listener.join()

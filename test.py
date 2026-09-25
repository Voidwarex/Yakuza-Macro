import threading
import time
import webbrowser
import platform
import subprocess
import uuid
import urllib.request
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
}


controller = keyboard.Controller()
is_pressed = False


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


# =========================================================
# CSS
# =========================================================

COMMON_CSS = """
<style>

    :root {
        --bg: #09090b;
        --card-bg: #18181b;
        --card-border: #27272a;

        --text-primary: #f4f4f5;
        --text-muted: #a1a1aa;

        --accent-green: #22c55e;
        --accent-green-hover: #16a34a;

        --accent-red: #7f1d1d;
        --accent-red-text: #991b1b;

        --sidebar-width: 260px;
        --sidebar-collapsed-width: 72px;
    }


    * {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }


    body {
        font-family:
            -apple-system,
            BlinkMacSystemFont,
            "Segoe UI",
            Roboto,
            "Helvetica Neue",
            Arial,
            sans-serif;

        background: var(--bg);
        color: var(--text-primary);

        display: flex;

        height: 100vh;

        overflow: hidden;
    }


    /* =====================================================
       SIDEBAR
       ===================================================== */

    .sidebar {
        width: var(--sidebar-width);

        background: var(--card-bg);

        border-right: 1px solid var(--card-border);

        transition:
            width 0.3s cubic-bezier(0.4, 0, 0.2, 1);

        display: flex;
        flex-direction: column;

        z-index: 10;
    }


    .sidebar.collapsed {
        width: var(--sidebar-collapsed-width);
    }


    .sidebar-header {
        height: 72px;

        display: flex;
        align-items: center;

        padding: 0 24px;

        border-bottom: 1px solid var(--card-border);

        overflow: hidden;
        white-space: nowrap;
    }


    .sidebar-logo {
        display: flex;
        align-items: center;

        gap: 12px;

        font-weight: 700;
        font-size: 1.2rem;

        color: var(--text-primary);

        text-decoration: none;
    }


    .sidebar-logo svg {
        flex-shrink: 0;

        color: var(--accent-green);
    }


    .sidebar-nav {
        flex: 1;

        padding: 24px 12px;

        display: flex;
        flex-direction: column;

        gap: 8px;
    }


    .nav-item {
        display: flex;
        align-items: center;

        gap: 16px;

        padding: 12px;

        border-radius: 8px;

        color: var(--text-muted);

        text-decoration: none;

        font-weight: 500;

        transition: all 0.2s;

        cursor: pointer;

        overflow: hidden;
        white-space: nowrap;
    }


    .nav-item:hover {
        background: rgba(255, 255, 255, 0.05);

        color: var(--text-primary);
    }


    .nav-item.active {
        background: rgba(34, 197, 94, 0.1);

        color: var(--accent-green);
    }


    .nav-item svg {
        flex-shrink: 0;
    }


    .logout-btn {
        margin-top: auto;

        color: #ef4444;

        margin-bottom: 16px;
    }


    .logout-btn:hover {
        background: rgba(239, 68, 68, 0.1);

        color: #dc2626;
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

        background-image:
            radial-gradient(
                circle at 50% 35%,
                rgba(34, 197, 94, 0.08) 0%,
                rgba(9, 9, 11, 1) 70%
            );

        position: relative;
    }


    /* =====================================================
       TOPBAR
       ===================================================== */

    .topbar {
        height: 72px;

        display: flex;
        align-items: center;

        padding: 0 32px;

        border-bottom: 1px solid rgba(39, 39, 42, 0.5);
    }


    .topbar-left {
        display: flex;

        align-items: center;

        gap: 18px;
    }


    .menu-toggle {
        background: none;

        border: none;

        color: var(--text-primary);

        cursor: pointer;

        padding: 8px;

        border-radius: 6px;

        display: flex;

        align-items: center;

        transition: background 0.2s;
    }


    .menu-toggle:hover {
        background: rgba(255,255,255,0.05);
    }


    .brand-title {
        font-size: 1.25rem;

        font-weight: 700;

        letter-spacing: -0.02em;

        white-space: nowrap;
    }


    /* =====================================================
       HEADER STATUS
       ===================================================== */

    .header-status {
        display: flex;

        align-items: center;

        gap: 10px;

        margin-left: 4px;

        padding-left: 14px;

        border-left: 1px solid var(--card-border);

        height: 32px;
    }


    .header-status .switch {
        flex-shrink: 0;
    }


    .status-text {
        font-size: 0.82rem;

        font-weight: 700;

        white-space: nowrap;

        transition:
            color 0.3s ease,
            text-shadow 0.3s ease;
    }


    /* ENABLED */

    .status-text.enabled {
        color: var(--accent-green);

        text-shadow:
            0 0 6px rgba(34, 197, 94, 0.8),
            0 0 14px rgba(34, 197, 94, 0.5);

        animation: statusPulse 1.8s ease-in-out infinite;
    }


    /* DISABLED */

    .status-text.disabled {
        color: var(--accent-red-text);

        text-shadow:
            0 0 5px rgba(127, 29, 29, 0.35);
    }


    @keyframes statusPulse {

        0%,
        100% {
            opacity: 1;

            text-shadow:
                0 0 6px rgba(34, 197, 94, 0.8),
                0 0 14px rgba(34, 197, 94, 0.5);
        }

        50% {
            opacity: 0.72;

            text-shadow:
                0 0 3px rgba(34, 197, 94, 0.5),
                0 0 8px rgba(34, 197, 94, 0.25);
        }
    }


    /* =====================================================
       TOGGLE SWITCH
       ===================================================== */

    .switch {
        position: relative;

        display: inline-block;

        width: 44px;
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

        top: 0;
        left: 0;
        right: 0;
        bottom: 0;

        background-color: #27272a;

        transition: 0.3s;

        border-radius: 34px;
    }


    .slider:before {
        position: absolute;

        content: "";

        height: 16px;
        width: 16px;

        left: 4px;
        bottom: 4px;

        background-color: white;

        transition: 0.3s;

        border-radius: 50%;

        box-shadow:
            0 2px 4px rgba(0,0,0,0.3);
    }


    /* ON */

    input:checked + .slider {
        background-color: var(--accent-green);

        box-shadow:
            0 0 8px rgba(34,197,94,0.35);
    }


    input:checked + .slider:before {
        transform: translateX(20px);
    }


    /* OFF */

    input:not(:checked) + .slider {
        background-color: #450a0a;

        box-shadow:
            0 0 6px rgba(127,29,29,0.25);
    }


    input:not(:checked) + .slider:before {
        background-color: #d4d4d8;
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
    }


    .view {
        display: none;

        width: 100%;

        justify-content: center;
    }


    .view.active {
        display: flex;

        animation: fadeIn 0.4s ease forwards;
    }


    @keyframes fadeIn {

        from {
            opacity: 0;

            transform: translateY(10px);
        }

        to {
            opacity: 1;

            transform: translateY(0);
        }
    }


    /* =====================================================
       CARD
       ===================================================== */

    .card {
        background: var(--card-bg);

        padding: 32px;

        border-radius: 12px;

        max-width: 420px;

        width: 100%;

        border: 1px solid var(--card-border);

        box-shadow:
            0 20px 25px -5px rgba(0, 0, 0, 0.5),
            0 8px 10px -6px rgba(0, 0, 0, 0.5);

        transition:
            transform 0.25s ease,
            border-color 0.25s ease,
            box-shadow 0.25s ease;
    }


    .card:hover {
        border-color: rgba(34, 197, 94, 0.4);

        box-shadow:
            0 25px 30px -5px rgba(0, 0, 0, 0.7),
            0 0 20px rgba(34, 197, 94, 0.12);
    }


    h2 {
        margin: 0 0 20px 0;

        font-size: 1.4rem;

        font-weight: 700;

        letter-spacing: -0.02em;

        border-bottom: 1px solid var(--card-border);

        padding-bottom: 16px;

        display: flex;

        align-items: center;

        justify-content: space-between;
    }


    label {
        display: block;

        margin-top: 18px;

        font-weight: 500;

        font-size: 0.85rem;

        color: var(--text-muted);
    }


    input.form-input {
        width: 100%;

        padding: 10px 14px;

        margin-top: 8px;

        background: #09090b;

        color: var(--text-primary);

        border: 1px solid var(--card-border);

        border-radius: 8px;

        font-size: 0.95rem;

        outline: none;

        transition: all 0.2s ease;
    }


    input.form-input:focus {
        border-color: var(--accent-green);

        box-shadow:
            0 0 0 3px rgba(34, 197, 94, 0.2);
    }


    button.btn-primary {
        margin-top: 26px;

        width: 100%;

        padding: 12px;

        background: var(--accent-green);

        color: #09090b;

        border: none;

        border-radius: 8px;

        cursor: pointer;

        font-weight: 700;

        font-size: 0.95rem;

        transition: all 0.2s ease;

        box-shadow:
            0 4px 14px rgba(34, 197, 94, 0.3);
    }


    button.btn-primary:hover {
        background: var(--accent-green-hover);

        box-shadow:
            0 6px 20px rgba(34, 197, 94, 0.45);
    }


    button.btn-primary:active {
        transform: scale(0.98);
    }


    .info-box {
        background: #09090b;

        padding: 10px 14px;

        margin-top: 8px;

        border-radius: 8px;

        border: 1px solid var(--card-border);

        font-family:
            ui-monospace,
            SFMono-Regular,
            monospace;

        font-size: 0.85rem;

        color: var(--accent-green);

        word-break: break-all;
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


@app.route("/")
def home():

    sys_os = f"{platform.system()} {platform.release()}"

    sys_node = platform.node()

    sys_processor = platform.processor() or "Unknown"

    public_ip = get_public_ip()

    hwid = get_hwid()


    is_active_checked = "checked" if config["active"] else ""

    status_text = "Enabled" if config["active"] else "Disabled"

    status_class = "enabled" if config["active"] else "disabled"


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


            <!-- STATUS ATTACHED TO HEADER -->

            <div class="header-status">


                <label class="switch">

                    <input
                        type="checkbox"
                        id="macroToggle"
                        {is_active_checked}
                        onchange="toggleMacro(this)"
                    >

                    <span class="slider"></span>

                </label>


                <span
                    class="status-text {status_class}"
                    id="macroStatus"
                >
                    {status_text}
                </span>


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

            <div class="card">


                <h2>
                    Hotkey Configuration
                </h2>


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
                        value="{config['trigger_key']}"
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
                        value="{config['target_key']}"
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
                    {public_ip}
                </div>


                <label>
                    Hardware ID (HWID)
                </label>

                <div class="info-box">
                    {hwid}
                </div>


                <label>
                    Operating System
                </label>

                <div class="info-box">
                    {sys_os}
                </div>


                <label>
                    Hostname
                </label>

                <div class="info-box">
                    {sys_node}
                </div>


                <label>
                    Processor
                </label>

                <div class="info-box">
                    {sys_processor}
                </div>


            </div>

        </div>


    </div>

</main>


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
// TOGGLE MACRO
// =========================================================

async function toggleMacro(checkbox) {

    const statusText =
        document.getElementById("macroStatus");


    if (checkbox.checked) {

        statusText.innerText = "Enabled";

        statusText.classList.remove("disabled");

        statusText.classList.add("enabled");

    }

    else {

        statusText.innerText = "Disabled";

        statusText.classList.remove("enabled");

        statusText.classList.add("disabled");

    }


    try {

        await fetch(
            "/api/toggle",
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    active: checkbox.checked
                })
            }
        );

    }

    catch (error) {

        console.error(
            "Failed to update macro state:",
            error
        );

    }

}


// =========================================================
// SAVE SETTINGS
// =========================================================

async function saveSettings(event) {

    event.preventDefault();


    const btn =
        document.getElementById("saveBtn");


    const data = {

        trigger_key:
            document
                .getElementById("trigger_key")
                .value,

        target_key:
            document
                .getElementById("target_key")
                .value,

        delay_ms:
            document
                .getElementById("delay_ms")
                .value

    };


    try {

        const res = await fetch(
            "/api/update",
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify(data)
            }
        );


        if (res.ok) {

            const originalText =
                btn.innerText;


            btn.innerText =
                "Settings Saved!";


            btn.style.background =
                "#16a34a";


            setTimeout(() => {

                btn.innerText =
                    originalText;

                btn.style.background =
                    "";

            }, 2000);

        }

    }

    catch (error) {

        console.error(
            "Failed to save settings:",
            error
        );

    }

}


// =========================================================
// LOGOUT
// =========================================================

async function logout() {

    document.body.innerHTML = `

        <div
            style="
                display:flex;
                height:100vh;
                width:100vw;
                justify-content:center;
                align-items:center;
                background:#09090b;
                color:#22c55e;
                font-size:1.5rem;
                font-weight:bold;
            "
        >
            Application Closed.
            You can close this window.
        </div>

    `;


    await fetch(
        "/api/shutdown",
        {
            method: "POST"
        }
    );

}


</script>


</body>

</html>
"""


# =========================================================
# API - UPDATE CONFIG
# =========================================================

@app.route("/api/update", methods=["POST"])
def update_config():

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


    return jsonify({
        "status": "success"
    })


# =========================================================
# API - TOGGLE
# =========================================================

@app.route("/api/toggle", methods=["POST"])
def toggle_macro():

    data = request.json

    if data and "active" in data:

        config["active"] = bool(
            data["active"]
        )


    return jsonify({
        "status": "success",

        "active":
            config["active"]
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

def on_press(key):

    global is_pressed


    if not config["active"]:
        return


    try:

        if (
            key.char == config["trigger_key"]
            and not is_pressed
        ):

            is_pressed = True


            time.sleep(
                config["delay_ms"] / 1000.0
            )


            # Make sure the macro wasn't
            # disabled during the delay.
            if config["active"]:

                controller.press(
                    config["target_key"]
                )

    except AttributeError:

        pass


def on_release(key):

    global is_pressed


    try:

        if key.char == config["trigger_key"]:

            is_pressed = False

            controller.release(
                config["target_key"]
            )

    except AttributeError:

        pass


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


    time.sleep(1)


    webbrowser.open(
        "http://127.0.0.1:5000"
    )


    with keyboard.Listener(
        on_press=on_press,
        on_release=on_release
    ) as listener:

        listener.join()

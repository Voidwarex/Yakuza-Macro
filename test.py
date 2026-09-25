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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link
    href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@500;600;700&family=JetBrains+Mono:wght@400;600&display=swap"
    rel="stylesheet"
>

<style>

    :root {
        --bg: #05020c;
        --bg-deep: #020106;
        --panel: rgba(14, 8, 28, 0.78);
        --panel-solid: #0c0718;
        --panel-border: rgba(0, 240, 255, 0.18);

        --text-primary: #eafcff;
        --text-muted: #8a86a8;

        --neon-cyan: #00f0ff;
        --neon-magenta: #ff2bd6;
        --neon-purple: #9d4dff;
        --neon-green: #39ff88;
        --neon-red: #ff2d55;

        --glow-cyan:
            0 0 6px rgba(0, 240, 255, 0.9),
            0 0 18px rgba(0, 240, 255, 0.45);
        --glow-magenta:
            0 0 6px rgba(255, 43, 214, 0.9),
            0 0 18px rgba(255, 43, 214, 0.45);

        --font-display: "Orbitron", "Segoe UI", sans-serif;
        --font-body: "Rajdhani", "Segoe UI", Roboto, sans-serif;
        --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace;

        --cut: 14px;

        --sidebar-width: 260px;
        --sidebar-collapsed-width: 76px;
    }


    * {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }


    ::selection {
        background: var(--neon-magenta);
        color: var(--bg);
    }


    ::-webkit-scrollbar {
        width: 8px;
    }

    ::-webkit-scrollbar-track {
        background: var(--bg-deep);
    }

    ::-webkit-scrollbar-thumb {
        background: linear-gradient(var(--neon-cyan), var(--neon-magenta));
        border-radius: 4px;
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


    /* Scanlines overlay */

    body::after {
        content: "";

        position: fixed;
        inset: 0;

        pointer-events: none;
        z-index: 100;

        background: repeating-linear-gradient(
            to bottom,
            rgba(255, 255, 255, 0.025) 0px,
            rgba(255, 255, 255, 0.025) 1px,
            transparent 1px,
            transparent 3px
        );

        mix-blend-mode: overlay;
    }


    /* =====================================================
       SIDEBAR
       ===================================================== */

    .sidebar {
        width: var(--sidebar-width);

        background:
            linear-gradient(180deg, rgba(157, 77, 255, 0.08), transparent 40%),
            var(--panel-solid);

        border-right: 1px solid var(--panel-border);

        box-shadow:
            1px 0 0 rgba(255, 43, 214, 0.15),
            8px 0 30px rgba(0, 0, 0, 0.6);

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
        font-weight: 900;
        font-size: 1rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;

        color: var(--text-primary);
        text-decoration: none;
    }


    .sidebar-logo svg {
        flex-shrink: 0;

        color: var(--neon-cyan);

        filter:
            drop-shadow(0 0 4px var(--neon-cyan))
            drop-shadow(0 0 10px rgba(0, 240, 255, 0.6));

        animation: flicker 4s infinite;
    }


    .sidebar-nav {
        flex: 1;

        padding: 24px 12px;

        display: flex;
        flex-direction: column;
        gap: 8px;
    }


    .nav-item {
        position: relative;

        display: flex;
        align-items: center;
        gap: 16px;

        padding: 12px 14px;

        color: var(--text-muted);
        text-decoration: none;

        font-weight: 600;
        font-size: 1.02rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;

        border: 1px solid transparent;

        clip-path: polygon(
            0 0,
            calc(100% - 10px) 0,
            100% 10px,
            100% 100%,
            10px 100%,
            0 calc(100% - 10px)
        );

        transition: all 0.2s ease;

        cursor: pointer;
        overflow: hidden;
        white-space: nowrap;
    }


    .nav-item::before {
        content: "";

        position: absolute;
        left: 0;
        top: 20%;
        bottom: 20%;

        width: 3px;

        background: var(--neon-cyan);
        box-shadow: var(--glow-cyan);

        transform: scaleY(0);
        transition: transform 0.2s ease;
    }


    .nav-item:hover {
        background: rgba(0, 240, 255, 0.06);
        color: var(--text-primary);
    }


    .nav-item:hover::before {
        transform: scaleY(0.6);
    }


    .nav-item.active {
        background: linear-gradient(90deg, rgba(0, 240, 255, 0.16), rgba(157, 77, 255, 0.06));
        border-color: rgba(0, 240, 255, 0.3);

        color: var(--neon-cyan);
        text-shadow: 0 0 8px rgba(0, 240, 255, 0.7);
    }


    .nav-item.active::before {
        transform: scaleY(1);
    }


    .nav-item.active svg {
        filter: drop-shadow(0 0 5px var(--neon-cyan));
    }


    .nav-item svg {
        flex-shrink: 0;
    }


    .logout-btn {
        margin-top: auto;
        margin-bottom: 16px;

        color: var(--neon-red);
    }


    .logout-btn::before {
        background: var(--neon-red);
        box-shadow: 0 0 8px var(--neon-red);
    }


    .logout-btn:hover {
        background: rgba(255, 45, 85, 0.1);
        color: #ff6b88;
        text-shadow: 0 0 8px rgba(255, 45, 85, 0.8);
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
            radial-gradient(ellipse at 20% 0%, rgba(157, 77, 255, 0.22), transparent 55%),
            radial-gradient(ellipse at 90% 100%, rgba(255, 43, 214, 0.16), transparent 55%),
            radial-gradient(circle at 50% 45%, rgba(0, 240, 255, 0.08), transparent 60%),
            var(--bg);
    }


    /* Perspective grid floor */

    .main-wrapper::before {
        content: "";

        position: absolute;
        left: -50%;
        right: -50%;
        bottom: -10%;
        height: 60%;

        background-image:
            linear-gradient(rgba(0, 240, 255, 0.18) 1px, transparent 1px),
            linear-gradient(90deg, rgba(0, 240, 255, 0.18) 1px, transparent 1px);
        background-size: 48px 48px;

        transform: perspective(500px) rotateX(62deg);
        transform-origin: center top;

        mask-image: linear-gradient(to bottom, transparent, black 30%, black 70%, transparent);
        -webkit-mask-image: linear-gradient(to bottom, transparent, black 30%, black 70%, transparent);

        animation: gridScroll 6s linear infinite;

        pointer-events: none;
        z-index: 0;
    }


    @keyframes gridScroll {
        from { background-position: 0 0; }
        to   { background-position: 0 48px; }
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

        background: rgba(5, 2, 12, 0.55);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
    }


    .topbar::after {
        content: "";

        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        height: 1px;

        background: linear-gradient(
            90deg,
            transparent,
            var(--neon-cyan) 20%,
            var(--neon-magenta) 80%,
            transparent
        );

        box-shadow: 0 0 10px rgba(0, 240, 255, 0.6);
    }


    .topbar-left {
        display: flex;
        align-items: center;
        gap: 18px;
    }


    .menu-toggle {
        background: rgba(0, 240, 255, 0.05);
        border: 1px solid var(--panel-border);

        color: var(--neon-cyan);

        cursor: pointer;
        padding: 8px;
        border-radius: 4px;

        display: flex;
        align-items: center;

        transition: all 0.2s;
    }


    .menu-toggle:hover {
        background: rgba(0, 240, 255, 0.14);
        border-color: var(--neon-cyan);
        box-shadow: var(--glow-cyan);
    }


    .brand-title {
        font-family: var(--font-display);
        font-size: 1.3rem;
        font-weight: 900;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        white-space: nowrap;

        background: linear-gradient(90deg, var(--neon-cyan), var(--neon-purple) 50%, var(--neon-magenta));
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;

        filter: drop-shadow(0 0 8px rgba(0, 240, 255, 0.45));
    }


    /* =====================================================
       HEADER STATUS
       ===================================================== */

    .header-status {
        display: flex;
        align-items: center;
        gap: 12px;

        margin-left: 6px;
        padding: 0 14px;

        height: 36px;

        border: 1px solid var(--panel-border);
        border-radius: 4px;
        background: rgba(0, 0, 0, 0.35);
    }


    .header-status .switch {
        flex-shrink: 0;
    }


    .status-text {
        font-family: var(--font-display);
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        white-space: nowrap;

        transition:
            color 0.3s ease,
            text-shadow 0.3s ease;
    }


    /* ENABLED */

    .status-text.enabled {
        color: var(--neon-green);

        text-shadow:
            0 0 6px rgba(57, 255, 136, 0.9),
            0 0 16px rgba(57, 255, 136, 0.5);

        animation: statusPulse 1.8s ease-in-out infinite;
    }


    /* DISABLED */

    .status-text.disabled {
        color: var(--neon-red);

        text-shadow: 0 0 6px rgba(255, 45, 85, 0.6);
    }


    @keyframes statusPulse {

        0%,
        100% {
            opacity: 1;

            text-shadow:
                0 0 6px rgba(57, 255, 136, 0.9),
                0 0 16px rgba(57, 255, 136, 0.5);
        }

        50% {
            opacity: 0.7;

            text-shadow:
                0 0 3px rgba(57, 255, 136, 0.5),
                0 0 8px rgba(57, 255, 136, 0.25);
        }
    }


    @keyframes flicker {
        0%, 92%, 100% { opacity: 1; }
        93% { opacity: 0.4; }
        94% { opacity: 1; }
        96% { opacity: 0.6; }
        97% { opacity: 1; }
    }


    /* =====================================================
       TOGGLE SWITCH
       ===================================================== */

    .switch {
        position: relative;
        display: inline-block;
        margin-top: 0;

        width: 48px;
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

        background-color: #1a0f2a;
        border: 1px solid rgba(255, 255, 255, 0.12);
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

        background-color: #fff;
        border-radius: 50%;

        transition: 0.3s;
    }


    /* ON */

    input:checked + .slider {
        background-color: rgba(57, 255, 136, 0.18);
        border-color: var(--neon-green);

        box-shadow:
            0 0 10px rgba(57, 255, 136, 0.55),
            inset 0 0 8px rgba(57, 255, 136, 0.35);
    }


    input:checked + .slider:before {
        transform: translateX(24px);

        background-color: var(--neon-green);
        box-shadow: 0 0 10px var(--neon-green);
    }


    /* OFF */

    input:not(:checked) + .slider {
        background-color: rgba(255, 45, 85, 0.12);
        border-color: rgba(255, 45, 85, 0.6);

        box-shadow: 0 0 8px rgba(255, 45, 85, 0.3);
    }


    input:not(:checked) + .slider:before {
        background-color: var(--neon-red);
        box-shadow: 0 0 8px rgba(255, 45, 85, 0.7);
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
            linear-gradient(160deg, rgba(0, 240, 255, 0.06), transparent 35%),
            var(--panel);

        backdrop-filter: blur(14px);
        -webkit-backdrop-filter: blur(14px);

        padding: 34px;

        max-width: 440px;
        width: 100%;

        border: 1px solid var(--panel-border);

        clip-path: polygon(
            0 0,
            calc(100% - var(--cut)) 0,
            100% var(--cut),
            100% 100%,
            var(--cut) 100%,
            0 calc(100% - var(--cut))
        );

        box-shadow:
            inset 0 0 0 1px rgba(255, 43, 214, 0.06),
            inset 0 0 40px rgba(0, 240, 255, 0.05);

        transition:
            border-color 0.25s ease,
            box-shadow 0.25s ease;
    }


    /* Neon corner accents */

    .card::before,
    .card::after {
        content: "";

        position: absolute;

        width: 60px;
        height: 60px;

        pointer-events: none;
    }


    .card::before {
        top: 0;
        left: 0;

        border-top: 2px solid var(--neon-cyan);
        border-left: 2px solid var(--neon-cyan);

        filter: drop-shadow(0 0 4px var(--neon-cyan));
    }


    .card::after {
        bottom: 0;
        right: 0;

        border-bottom: 2px solid var(--neon-magenta);
        border-right: 2px solid var(--neon-magenta);

        filter: drop-shadow(0 0 4px var(--neon-magenta));
    }


    .card:hover {
        border-color: rgba(0, 240, 255, 0.4);

        box-shadow:
            inset 0 0 0 1px rgba(255, 43, 214, 0.15),
            inset 0 0 60px rgba(0, 240, 255, 0.1);
    }


    h2 {
        margin: 0 0 20px 0;

        font-family: var(--font-display);
        font-size: 1.05rem;
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;

        color: var(--neon-cyan);
        text-shadow: 0 0 10px rgba(0, 240, 255, 0.55);

        padding-bottom: 16px;

        border-bottom: 1px solid transparent;
        border-image: linear-gradient(90deg, var(--neon-cyan), var(--neon-magenta) 60%, transparent) 1;

        display: flex;
        align-items: center;
        gap: 10px;
    }


    h2::before {
        content: "";

        width: 8px;
        height: 8px;

        background: var(--neon-magenta);
        box-shadow: var(--glow-magenta);

        transform: rotate(45deg);
        flex-shrink: 0;
    }


    label {
        display: block;

        margin-top: 18px;

        font-weight: 600;
        font-size: 0.8rem;
        letter-spacing: 0.14em;
        text-transform: uppercase;

        color: var(--text-muted);
    }


    input.form-input {
        width: 100%;

        padding: 11px 14px;
        margin-top: 8px;

        background: rgba(2, 1, 6, 0.8);
        color: var(--text-primary);

        border: 1px solid rgba(157, 77, 255, 0.35);
        border-radius: 3px;

        font-family: var(--font-mono);
        font-size: 0.95rem;

        outline: none;
        caret-color: var(--neon-magenta);

        transition: all 0.2s ease;
    }


    input.form-input:hover {
        border-color: rgba(0, 240, 255, 0.5);
    }


    input.form-input:focus {
        border-color: var(--neon-cyan);

        box-shadow:
            0 0 0 1px var(--neon-cyan),
            0 0 16px rgba(0, 240, 255, 0.35),
            inset 0 0 10px rgba(0, 240, 255, 0.12);
    }


    button.btn-primary {
        position: relative;

        margin-top: 28px;
        width: 100%;
        padding: 14px;

        background: linear-gradient(90deg, var(--neon-cyan), var(--neon-purple) 55%, var(--neon-magenta));
        background-size: 200% 100%;
        background-position: 0% 0;

        color: #05020c;
        border: none;

        clip-path: polygon(
            12px 0,
            100% 0,
            100% calc(100% - 12px),
            calc(100% - 12px) 100%,
            0 100%,
            0 12px
        );

        cursor: pointer;

        font-family: var(--font-display);
        font-weight: 900;
        font-size: 0.85rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;

        transition:
            background-position 0.4s ease,
            filter 0.2s ease,
            transform 0.1s ease;

        filter: drop-shadow(0 0 10px rgba(0, 240, 255, 0.45));
    }


    button.btn-primary:hover {
        background-position: 100% 0;

        filter:
            drop-shadow(0 0 12px rgba(255, 43, 214, 0.6))
            brightness(1.1);
    }


    button.btn-primary:active {
        transform: scale(0.98);
    }


    .info-box {
        position: relative;

        background: rgba(2, 1, 6, 0.8);

        padding: 11px 14px 11px 18px;
        margin-top: 8px;

        border: 1px solid rgba(0, 240, 255, 0.18);
        border-radius: 3px;

        font-family: var(--font-mono);
        font-size: 0.85rem;

        color: var(--neon-green);
        text-shadow: 0 0 6px rgba(57, 255, 136, 0.5);

        word-break: break-all;
    }


    .info-box::before {
        content: "";

        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;

        width: 3px;

        background: var(--neon-green);
        box-shadow: 0 0 8px var(--neon-green);
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

function toggleSidebar() {{

    document
        .getElementById("sidebar")
        .classList
        .toggle("collapsed");

}}


// =========================================================
// VIEW SWITCHING
// =========================================================

function switchView(viewName, element) {{

    document
        .querySelectorAll(".nav-item")
        .forEach(el => {{
            el.classList.remove("active");
        }});


    element.classList.add("active");


    document
        .querySelectorAll(".view")
        .forEach(el => {{
            el.classList.remove("active");
        }});


    document
        .getElementById("view-" + viewName)
        .classList.add("active");

}}


// =========================================================
// TOGGLE MACRO
// =========================================================

async function toggleMacro(checkbox) {{

    const statusText =
        document.getElementById("macroStatus");


    if (checkbox.checked) {{

        statusText.innerText = "Enabled";

        statusText.classList.remove("disabled");

        statusText.classList.add("enabled");

    }}

    else {{

        statusText.innerText = "Disabled";

        statusText.classList.remove("enabled");

        statusText.classList.add("disabled");

    }}


    try {{

        await fetch(
            "/api/toggle",
            {{
                method: "POST",

                headers: {{
                    "Content-Type": "application/json"
                }},

                body: JSON.stringify({{
                    active: checkbox.checked
                }})
            }}
        );

    }}

    catch (error) {{

        console.error(
            "Failed to update macro state:",
            error
        );

    }}

}}


// =========================================================
// SAVE SETTINGS
// =========================================================

async function saveSettings(event) {{

    event.preventDefault();


    const btn =
        document.getElementById("saveBtn");


    const data = {{

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

    }};


    try {{

        const res = await fetch(
            "/api/update",
            {{
                method: "POST",

                headers: {{
                    "Content-Type": "application/json"
                }},

                body: JSON.stringify(data)
            }}
        );


        if (res.ok) {{

            const originalText =
                btn.innerText;


            btn.innerText =
                "Settings Saved!";


            btn.style.background =
                "#39ff88";


            setTimeout(() => {{

                btn.innerText =
                    originalText;

                btn.style.background =
                    "";

            }}, 2000);

        }}

    }}

    catch (error) {{

        console.error(
            "Failed to save settings:",
            error
        );

    }}

}}


// =========================================================
// LOGOUT
// =========================================================

async function logout() {{

    document.body.innerHTML = `

        <div
            style="
                display:flex;
                height:100vh;
                width:100vw;
                justify-content:center;
                align-items:center;
                background:#05020c;
                color:#00f0ff;
                font-family:Orbitron, sans-serif;
                letter-spacing:0.1em;
                text-shadow:0 0 8px #00f0ff, 0 0 20px rgba(0,240,255,0.5);
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
        {{
            method: "POST"
        }}
    );

}}


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

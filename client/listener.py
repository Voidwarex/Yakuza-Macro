"""
Amos Solutions — PC listener.

Runs on the PC you want to control. It reaches *out* to your relay server
(https://api.amos.fyi by default) on a loop and asks "is there anything for
me to do?". When you press Shut down / Restart / Lock in the web panel, the
next poll picks the command up and the listener carries it out.

Because the listener only makes outbound HTTPS requests, it works from behind
any home router with no port forwarding and no public IP.

Setup
-----
1.  pip install requests
2.  In the web panel, click "Add device", copy the API key it shows once.
3.  Copy config.example.ini to config.ini and fill in:
        server_url = https://api.amos.fyi
        api_key    = <the key from the panel>
        device     = <a name, just for your reference>
4.  python listener.py

To run it automatically and silently at every login (no terminal window),
use the installer for your OS instead of step 4:
    Windows : double-click install-windows.bat   (uninstall-windows.bat removes it)
    macOS   : bash install-macos.sh
    Linux   : bash install-linux.sh
Activity is written to listener.log next to this script.

Safety
------
The listener will power off the machine it runs on. Keep the API key private:
anyone who has it can shut this PC down. To stop a command you already sent,
press "Cancel" in the panel before the next poll, or set confirm_lock /
dry_run below while testing.
"""

import configparser
import logging
import os
import platform
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler

try:
    import requests
except ImportError:
    sys.exit("The 'requests' package is required. Run:  pip install requests")


# --------------------------------------------------------------------------
# Logging — writes to listener.log so it works with no console (pythonw /
# background service), and also to the console when one is attached.
# --------------------------------------------------------------------------

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "listener.log")


def setup_logging():
    logger = logging.getLogger("remote-power")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        fh = RotatingFileHandler(LOG_PATH, maxBytes=512_000, backupCount=2)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass
    if sys.stdout is not None:  # None under pythonw.exe / detached processes
        try:
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(fmt)
            logger.addHandler(ch)
        except Exception:
            pass
    return logger


log = setup_logging()


def fatal(message):
    """Log a fatal error (to the file too) and exit cleanly without a console."""
    log.error(message)
    raise SystemExit(1)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_config():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "config.ini")
    if not os.path.exists(path):
        fatal("config.ini not found. Copy config.example.ini to config.ini "
              "and fill in your API key.")

    parser = configparser.ConfigParser()
    parser.read(path)
    section = parser["listener"] if parser.has_section("listener") else parser["DEFAULT"]

    cfg = {
        "server_url": section.get("server_url", "https://api.amos.fyi").rstrip("/"),
        "api_key": section.get("api_key", "").strip(),
        "device": section.get("device", platform.node() or "PC"),
        "poll_interval": section.getint("poll_interval", 5),
        "dry_run": section.getboolean("dry_run", False),
        "kind": section.get("kind", "auto").strip().lower(),
        "allow_screenshots": section.getboolean("allow_screenshots", False),
    }
    if not cfg["api_key"]:
        fatal("No api_key set in config.ini. Add the key from the web panel.")
    return cfg


# --------------------------------------------------------------------------
# Device type detection (desktop / laptop / server)
# --------------------------------------------------------------------------

def detect_kind():
    """Best-effort guess of what kind of machine this is."""
    system = platform.system()
    try:
        if system == "Linux":
            # DMI chassis type is the most reliable signal when present.
            try:
                with open("/sys/class/dmi/id/chassis_type") as f:
                    ct = int(f.read().strip())
                if ct in (8, 9, 10, 11, 12, 14, 30, 31, 32):
                    return "laptop"
                if ct in (17, 18, 19, 20, 21, 22, 23, 24, 25, 28):
                    return "server"
                if ct in (3, 4, 5, 6, 7, 13, 16):
                    return "desktop"
            except Exception:
                pass
            import glob
            if glob.glob("/sys/class/power_supply/BAT*"):
                return "laptop"
            # Headless Linux (no graphical session) is usually a server.
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                return "server"
            return "desktop"

        if system == "Windows":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\ProductOptions",
                )
                product_type, _ = winreg.QueryValueEx(key, "ProductType")
                if str(product_type) in ("ServerNT", "LanmanNT"):
                    return "server"
            except Exception:
                pass
            # Battery present -> laptop.
            try:
                import ctypes

                class _SPS(ctypes.Structure):
                    _fields_ = [
                        ("ACLineStatus", ctypes.c_byte),
                        ("BatteryFlag", ctypes.c_byte),
                        ("BatteryLifePercent", ctypes.c_byte),
                        ("Reserved1", ctypes.c_byte),
                        ("BatteryLifeTime", ctypes.c_ulong),
                        ("BatteryFullLifeTime", ctypes.c_ulong),
                    ]

                status = _SPS()
                if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                    # 128 = no system battery, 255 = unknown.
                    if status.BatteryFlag not in (128, 255):
                        return "laptop"
            except Exception:
                pass
            return "desktop"

        if system == "Darwin":
            try:
                model = subprocess.check_output(
                    ["sysctl", "-n", "hw.model"]
                ).decode().strip()
                if "Book" in model:   # MacBook / MacBook Pro / Air
                    return "laptop"
            except Exception:
                pass
            return "desktop"
    except Exception:
        pass
    return "desktop"


def resolve_kind(cfg):
    """Honour an explicit kind in config.ini, otherwise auto-detect."""
    choice = cfg.get("kind", "auto")
    if choice in ("server", "laptop", "desktop"):
        return choice
    if choice == "pc":
        return "desktop"
    return detect_kind()


# --------------------------------------------------------------------------
# OS actions
# --------------------------------------------------------------------------

def os_info():
    return f"{platform.system()} {platform.release()}".strip()


# --------------------------------------------------------------------------
# Optional screen preview (opt-in via allow_screenshots). Needs 'mss' and
# 'Pillow'; if either is missing we just skip previews (power control is
# unaffected).  Install with:  pip install mss pillow
# --------------------------------------------------------------------------

_screenshot_warned = False


def capture_screenshot(max_width=900, quality=50):
    """Return a downscaled JPEG of the primary screen, or None if unavailable."""
    global _screenshot_warned
    try:
        import io
        import mss
        from PIL import Image
    except ImportError:
        if not _screenshot_warned:
            log.info("Screen preview is on, but 'mss'/'Pillow' aren't installed. "
                     "Run: pip install mss pillow")
            _screenshot_warned = True
        return None
    try:
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[1])  # primary monitor
        img = Image.frombytes("RGB", raw.size, raw.rgb)
        if img.width > max_width:
            h = int(img.height * max_width / img.width)
            img = img.resize((max_width, h))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
    except Exception as exc:  # no display, locked session, etc.
        log.warning("Could not capture screen: %s", exc)
        return None


def send_screenshot(server_url, headers, cfg):
    if not cfg.get("allow_screenshots"):
        return  # feature off for this device; nothing uploaded
    data = capture_screenshot()
    if not data:
        return
    try:
        requests.post(
            f"{server_url}/api/screenshot",
            data=data,
            headers={**headers, "Content-Type": "image/jpeg"},
            timeout=20,
        )
        log.info("Uploaded screen preview (%d KB)", len(data) // 1024)
    except requests.RequestException as exc:
        log.warning("Screen preview upload failed: %s", exc)


def run_action(action, dry_run):
    """Carry out a power command on this machine."""
    system = platform.system()

    if dry_run:
        log.info("[dry-run] would perform: %s", action)
        return

    if action == "shutdown":
        if system == "Windows":
            subprocess.Popen(["shutdown", "/s", "/t", "0", "/f"])
        elif system == "Darwin":
            subprocess.Popen(["osascript", "-e", 'tell app "System Events" to shut down'])
        else:  # Linux and other POSIX
            subprocess.Popen(["systemctl", "poweroff"])

    elif action == "restart":
        if system == "Windows":
            subprocess.Popen(["shutdown", "/r", "/t", "0", "/f"])
        elif system == "Darwin":
            subprocess.Popen(["osascript", "-e", 'tell app "System Events" to restart'])
        else:
            subprocess.Popen(["systemctl", "reboot"])

    elif action == "lock":
        if system == "Windows":
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif system == "Darwin":
            subprocess.Popen(
                ["/System/Library/CoreServices/Menu Extras/User.menu/Contents/"
                 "Resources/CGSession", "-suspend"]
            )
        else:
            # Try the common Linux screen lockers in turn.
            for cmd in (["loginctl", "lock-session"],
                        ["xdg-screensaver", "lock"],
                        ["gnome-screensaver-command", "-l"]):
                try:
                    subprocess.Popen(cmd)
                    break
                except FileNotFoundError:
                    continue
    else:
        log.warning("Ignoring unknown action: %s", action)


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------

def main():
    cfg = load_config()
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    poll_url = f"{cfg['server_url']}/api/poll"
    ack_url = f"{cfg['server_url']}/api/ack"

    kind = resolve_kind(cfg)

    log.info("Amos Solutions listener — device '%s' (%s)", cfg["device"], kind)
    log.info("Relay: %s  (polling every %ss)", cfg["server_url"], cfg["poll_interval"])
    if cfg["dry_run"]:
        log.info("DRY RUN: commands will be logged but not executed.")
    if cfg["allow_screenshots"]:
        log.info("Screen previews: enabled (panel can request thumbnails).")
    log.info("Running.")

    backoff = cfg["poll_interval"]
    while True:
        try:
            resp = requests.post(
                poll_url,
                json={"os_info": os_info(), "device": cfg["device"], "kind": kind},
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 401:
                fatal("Server rejected the API key (401). Check config.ini.")
            resp.raise_for_status()
            data = resp.json()
            backoff = cfg["poll_interval"]  # reset after a good poll

            action = data.get("action")
            if action:
                command_id = data.get("command_id")
                log.info("Received command: %s", action)
                # Acknowledge first, so the panel shows it was delivered even if
                # the machine powers off a moment later.
                if command_id is not None:
                    try:
                        requests.post(
                            ack_url,
                            json={"command_id": command_id},
                            headers=headers,
                            timeout=15,
                        )
                    except requests.RequestException:
                        pass
                if action == "screenshot":
                    send_screenshot(cfg["server_url"], headers, cfg)
                else:
                    run_action(action, cfg["dry_run"])

        except requests.RequestException as exc:
            # Network hiccup — back off a little, then keep trying.
            log.warning("Connection problem: %s. Retrying in %ss.", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue

        time.sleep(cfg["poll_interval"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Stopped.")

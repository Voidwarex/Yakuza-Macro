"""
Remote Power — PC listener.

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

Leave it running (see the README for how to start it automatically at login).

Safety
------
The listener will power off the machine it runs on. Keep the API key private:
anyone who has it can shut this PC down. To stop a command you already sent,
press "Cancel" in the panel before the next poll, or set confirm_lock /
dry_run below while testing.
"""

import configparser
import os
import platform
import subprocess
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("The 'requests' package is required. Run:  pip install requests")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_config():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "config.ini")
    if not os.path.exists(path):
        sys.exit(
            "config.ini not found.\n"
            "Copy config.example.ini to config.ini and fill in your API key."
        )

    parser = configparser.ConfigParser()
    parser.read(path)
    section = parser["listener"] if parser.has_section("listener") else parser["DEFAULT"]

    cfg = {
        "server_url": section.get("server_url", "https://api.amos.fyi").rstrip("/"),
        "api_key": section.get("api_key", "").strip(),
        "device": section.get("device", platform.node() or "PC"),
        "poll_interval": section.getint("poll_interval", 5),
        "dry_run": section.getboolean("dry_run", False),
    }
    if not cfg["api_key"]:
        sys.exit("No api_key set in config.ini. Add the key from the web panel.")
    return cfg


# --------------------------------------------------------------------------
# OS actions
# --------------------------------------------------------------------------

def os_info():
    return f"{platform.system()} {platform.release()}".strip()


def run_action(action, dry_run):
    """Carry out a power command on this machine."""
    system = platform.system()

    if dry_run:
        print(f"[dry-run] would perform: {action}")
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
        print(f"Ignoring unknown action: {action}")


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------

def main():
    cfg = load_config()
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    poll_url = f"{cfg['server_url']}/api/poll"
    ack_url = f"{cfg['server_url']}/api/ack"

    print(f"Remote Power listener — device '{cfg['device']}'")
    print(f"Relay: {cfg['server_url']}  (polling every {cfg['poll_interval']}s)")
    if cfg["dry_run"]:
        print("DRY RUN: commands will be logged but not executed.")
    print("Running. Press Ctrl+C to stop.\n")

    backoff = cfg["poll_interval"]
    while True:
        try:
            resp = requests.post(
                poll_url,
                json={"os_info": os_info(), "device": cfg["device"]},
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 401:
                sys.exit("Server rejected the API key (401). Check config.ini.")
            resp.raise_for_status()
            data = resp.json()
            backoff = cfg["poll_interval"]  # reset after a good poll

            action = data.get("action")
            if action:
                command_id = data.get("command_id")
                print(f"Received command: {action}")
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
                run_action(action, cfg["dry_run"])

        except requests.RequestException as exc:
            # Network hiccup — back off a little, then keep trying.
            print(f"Connection problem: {exc}. Retrying in {backoff}s.")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue

        time.sleep(cfg["poll_interval"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")

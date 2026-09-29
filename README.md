# Amos Solutions

Keyboard macro app (`test.py`) with a web dashboard, locked behind
accounts and time-based license keys served by `license_server.py`.

## Requirements

```
pip install flask pynput
```

For a controller trigger and target (Windows only), also:

```
pip install vgamepad
```

On Windows this also runs the ViGEmBus driver installer; accept it.

## Controller mode

In the Hotkey card, switch **Trigger** to **Controller**, then use each
**Bind** button and press the controller button you want for the
trigger and for the target. The app reads your controller through
Windows' XInput, so it works while the game has focus. PlayStation
controllers need Steam Input or DS4Windows so they appear as Xbox pads.

The target is pressed on a virtual Xbox 360 controller (vgamepad +
ViGEmBus), because Windows can't fake presses on a real controller. The
game sees it as a second controller alongside yours. The trigger and
target must be different buttons.

## 1. Run the license server (you host this)

```
pip install waitress
python license_server.py serve --host 0.0.0.0 --port 8000
```

`serve` uses the `waitress` production server when it is installed.

Accounts and keys are stored in `licenses.db` next to the script
(override with `AMOS_DB_PATH`; the old `YAKUZA_DB_PATH` also works). Keep this file private and backed up.
In production put the server behind HTTPS (e.g. a reverse proxy).

## 2. Point the app at your server

The app talks to `https://api.amos.fyi`. To use another address, edit
`LICENSE_SERVER` near the top of `test.py` or set the
`AMOS_LICENSE_SERVER` environment variable.

### HTTPS with Cloudflare

1. In Cloudflare DNS, add an `A` record `api` pointing at the server's
   IP, with the proxy (orange cloud) on.
2. In SSL/TLS, set the mode to **Full (strict)**, then create an
   **Origin Certificate** for `amos.fyi` and `*.amos.fyi`. Save the
   certificate as `/etc/ssl/amos/origin.pem` and the key as
   `/etc/ssl/amos/origin.key` on the server.
3. Copy `deploy/nginx-amos-api.conf` to `/etc/nginx/conf.d/`, then run
   `nginx -t && systemctl reload nginx`. Open port 443 in the firewall.
4. Check it: `curl -X POST https://api.amos.fyi/api/integrity -d '{}'`
   should answer with JSON from the license server.

## 3. Sell keys

```
python license_server.py genkeys day 10     # 1 day each
python license_server.py genkeys week 5     # 7 days each
python license_server.py genkeys month 1    # 30 days each
```

Each key works once. Redeeming adds its time on top of any time the
account still has.

## Admin commands

| Command | What it does |
|---|---|
| `listkeys [--unused]` | Show keys and who redeemed them |
| `listusers` | Show accounts, time remaining and HWID |
| `resethwid <username>` | Let an account log in from a new PC |
| `addtime <username> <days>` | Give an account extra days |
| `deleteuser <username>` | Delete an account |
| `ban <username>` / `unban <username>` | Ban or unban an account |
| `createadmin <username>` | Create an admin account (asks for a password) |
| `setadmin <username> [--off]` | Give or remove admin rights |

## Free-time events

Run events like a free weekend from the **Events** section of the Admin
Panel: give it a name, a start time (leave empty to start now) and a
length in hours.

While an event runs:

- everyone who logs in can use the app, including accounts with no key
  or an expired one;
- paid keys are paused, so their time left stays the same the whole way
  through;
- the dashboard shows a banner with the time left in the event, and a
  countdown before an upcoming one starts.

When the event ends (or you press **End Now**) every key resumes with
exactly the time it had when the event started. Keys redeemed and time
added during the event also only start counting down after it. Events
can't overlap. **Cancel** removes an event that hasn't started yet.

From the server:

```
python license_server.py createevent "Free Weekend" 48 --start "2026-10-03 18:00"
python license_server.py listevents
python license_server.py endevent <id>
```

`--start` is in the server's local time; leave it out to start now.

## Build check

The app sends a SHA-256 hash of itself (`test.py`, or the `.exe` if you
package it) with every request to the license server. If the server has
any approved builds, a copy whose hash isn't on the list can't log in or
register, and anyone already logged in is signed out at the next sync.
The login screen shows:

> This copy of the app has been modified or is out of date. Download the
> official version to continue.

**Every time you change `test.py`, approve the new build** or nobody can
log in with it:

```
python license_server.py approvebuild test.py --label v1.2
```

If the server doesn't have your copy of `test.py`, print the hash on
your PC with `python test.py --hash` and approve that instead:

```
python license_server.py approvebuild <hash> --label v1.2
```

| Command | What it does |
|---|---|
| `approvebuild <file or hash> [--label ...]` | Allow a build to log in |
| `listbuilds` | Show approved builds |
| `revokebuild <hash>` | Block a build, e.g. an old version |

With no approved builds the check is off. Old builds keep working until
you revoke them. Line endings don't matter: a `.py` file gives the same
hash whether it's saved with Windows or Linux line endings.

This stops people editing the script and logging in with it. It can't
stop someone determined, because the app itself works out the hash it
sends, so a cracked copy could send an approved hash instead.

## Building the .exe

Customers should get a compiled `AmosSolutions.exe`, not `test.py`.
`build.bat` compiles the app with [Nuitka](https://nuitka.net), which
turns the Python into C and then into a native Windows program, so the
source code isn't inside the file.

On a Windows PC with Python 3.11 or 3.12 installed, in this folder:

```
build.bat
```

The first build asks to download a C compiler (MinGW64); say yes. A
build takes several minutes. It ends by printing the new `.exe`'s
SHA-256, which you then approve on the server:

```
python license_server.py approvebuild <hash> --label v1.0.0
```

Every build has a different hash, so approve each one you hand out.
The build check then covers the `.exe` itself: an edited or patched
copy is refused at sign-in.

The `.exe` isn't code-signed, so Windows SmartScreen shows "Windows
protected your PC" the first time (More info → Run anyway), and some
antivirus programs are wary of new unsigned programs that read the
keyboard. A code-signing certificate removes most of that.

## Admin Panel

Admin accounts see an **Admin Panel** in the app's side menu with every
user (time left, HWID, last login, keys used, online status), all keys,
and buttons to add / take / set time, ban / unban, reset HWIDs, and
generate or delete keys. Every admin action is checked by the server,
so the menu gives no access on its own.

The names `admin`, `administrator`, `root` and `support` can't be
registered from the app. Create your admin account on the server:

```
python license_server.py createadmin admin
```

## How customers use it

1. Run `python test.py`; the dashboard opens in the browser.
2. Register or log in. The account is locked to that PC's hardware ID.
3. Enter a key in the License card. Both macros stay locked while the
   time remaining is 0.

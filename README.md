# Yakuza-Macro

Keyboard macro app (`test.py`) with a web dashboard, locked behind
accounts and time-based license keys served by `license_server.py`.

## Requirements

```
pip install flask pynput
```

## 1. Run the license server (you host this)

```
pip install waitress
python license_server.py serve --host 0.0.0.0 --port 8000
```

`serve` uses the `waitress` production server when it is installed.

Accounts and keys are stored in `licenses.db` next to the script
(override with `YAKUZA_DB_PATH`). Keep this file private and backed up.
In production put the server behind HTTPS (e.g. a reverse proxy).

## 2. Point the app at your server

Edit `LICENSE_SERVER` near the top of `test.py`, or set the
`YAKUZA_LICENSE_SERVER` environment variable, e.g.
`https://license.example.com`.

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

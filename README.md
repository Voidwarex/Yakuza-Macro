# Yakuza-Macro

Keyboard macro app (`test.py`) with a web dashboard, locked behind
accounts and time-based license keys served by `license_server.py`.

## Requirements

```
pip install flask pynput
```

## 1. Run the license server (you host this)

```
python license_server.py serve --host 0.0.0.0 --port 8000
```

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

## How customers use it

1. Run `python test.py`; the dashboard opens in the browser.
2. Register or log in. The account is locked to that PC's hardware ID.
3. Enter a key in the License card. Both macros stay locked while the
   time remaining is 0.

# Remote Power

Turn your PC off (or restart / lock it) from anywhere in the world through a
web page. Built on the same stack as the Amos license server: a small Flask
app with a SQLite database that you host on your own server, behind
Cloudflare + nginx at `api.amos.fyi`.

```
  Web panel  ──►  Relay (api.amos.fyi)  ◄──  PC listener
 (your phone)      Flask + SQLite            (your PC, outbound only)
```

The PC only makes **outbound** HTTPS requests to the relay, so it works from
behind any home router — no port forwarding, no public IP on the PC.

## Parts

| Folder | What it is | Where it runs |
|---|---|---|
| `server/` | The relay: web control panel + JSON API | Your server |
| `client/` | The Python listener | Each PC you want to control |
| `deploy/` | nginx + systemd config | Your server |

## 1. Run the relay (you host this)

```
cd server
pip install -r requirements.txt
export ADMIN_PASSWORD='choose-a-strong-password'
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
python app.py
```

`app.py` uses the `waitress` production server when it is installed, and binds
to `127.0.0.1:8000` by default (so nginx can sit in front). The database is
`power.db` next to the script — override with `DB_PATH`. Keep it private.

See `server/config.example.env` for every setting.

### HTTPS with Cloudflare (same as your Amos setup)

1. In Cloudflare DNS, point `api` at the server's IP with the proxy
   (orange cloud) on.
2. In SSL/TLS, use **Full (strict)** and create an Origin Certificate for
   `amos.fyi` / `*.amos.fyi`, saved to `/etc/ssl/amos/origin.pem` and
   `/etc/ssl/amos/origin.key` (reuses the cert you already have).
3. Copy `deploy/nginx-api.conf` to `/etc/nginx/conf.d/`, then
   `nginx -t && systemctl reload nginx`. Open port 443.
4. To run it as a service, see `deploy/remote-power.service`.
5. Check it: open `https://api.amos.fyi` in a browser — you should get the
   sign-in page.

## 2. Add a device in the panel

1. Browse to `https://api.amos.fyi` and sign in with your `ADMIN_PASSWORD`.
2. Click **Add device**, give it a name, and copy the **API key** it shows.
   The key is shown only once.

## 3. Run the listener on your PC

```
cd client
pip install -r requirements.txt
copy config.example.ini config.ini     # on Windows (use cp on macOS/Linux)
```

Edit `config.ini`:

```
server_url = https://api.amos.fyi
api_key    = <the key from the panel>
device     = Home PC
```

Then:

```
python listener.py
```

Set `dry_run = true` in `config.ini` while testing — commands are logged but
not executed.

### Start it automatically

- **Windows:** put a shortcut to `pythonw listener.py` in
  `shell:startup`, or create a Task Scheduler task "At log on".
- **Linux:** a user `systemd` unit running `python listener.py`.
- **macOS:** a LaunchAgent plist.

## 4. Use it

From the panel you'll see each device with its online status and buttons:

- **Shut down** — powers the PC off.
- **Restart** — reboots it.
- **Lock** — locks the screen.
- **Cancel** — clears a command you queued before the PC picks it up.

Commands are delivered on the listener's next poll (every 5s by default).

## Security

The web panel password is the whole security boundary, so the relay is
hardened accordingly:

- **HTTPS only.** The login cookie is marked `Secure` + `HttpOnly` +
  `SameSite=Lax`, and HSTS is sent. (For local http testing set
  `INSECURE_COOKIES=1`.) Never expose the relay over plain HTTP — the panel
  password and device API keys would travel in clear text.
- **Brute-force lockout.** After 5 failed logins an IP is locked out for 5
  minutes.
- **Constant-time password check** and **session rotation on login** (guards
  against timing attacks and session fixation).
- **CSRF protection** on every state-changing panel request. The listener
  `/api/*` endpoints use Bearer-token auth (no cookie), so they are not
  CSRF-exposed.
- **Strict Content-Security-Policy**, `X-Frame-Options: DENY` (no
  clickjacking), `nosniff`, and a 64 KB request-body cap.
- Device API keys are stored only as **hashes**; the plaintext is shown once
  at enrollment. Anyone with a key can power that PC off — keep `config.ini`
  private, and **Remove** a device in the panel to revoke its key instantly.
- Use a strong `ADMIN_PASSWORD` and set `SECRET_KEY` so logins survive a
  restart.

### Why a domain and not the raw server IP

The listener and panel talk to `https://api.amos.fyi`, not the server's raw
`172.x` IP, on purpose: a hostname lets Cloudflare terminate TLS with a valid
certificate so traffic is encrypted and the origin IP stays hidden behind
Cloudflare. Pointing straight at the IP would mean either no TLS (keys sent in
clear text) or certificate warnings, and would expose the origin to direct
attack. If you ever do need the IP, put it behind HTTPS too.

## Requirements

- Server: Python 3.9+, `flask`, `waitress`.
- Client: Python 3.9+, `requests`.

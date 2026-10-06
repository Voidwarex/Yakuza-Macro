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

## Accounts & plans

Each customer registers their own account and sees only their own devices.
Plans cap how many devices an account can enroll:

| Plan | Devices | Price (placeholder) |
|---|---|---|
| Free | 3 | $0 |
| Pro | 10 | $4.99/mo |
| Business | 50 | $14.99/mo |

Paid plans are sold as **Stripe subscriptions** (see "Billing" below). Edit
prices and device limits in one place: `server/plans.py`. The relay runs fine
with Stripe unconfigured — the upgrade screen just says billing isn't set up,
and you can set plans manually with the admin CLI.

### Scheduled actions (Pro & Business)

Paid accounts can schedule power actions per device — **once** at a date/time,
**daily** at a time, or **weekly** on a chosen day — via the **Schedule** button
on each device card. A background worker in the relay queues the command when a
schedule is due, so the listener runs it on its next poll. Great for "shut down
every night at 11pm" power savings. Free accounts see an upgrade prompt.

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
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
python app.py serve
```

`app.py serve` uses the `waitress` production server when it is installed, and
binds to `127.0.0.1:8000` by default (so nginx can sit in front). The database
is `power.db` next to the script — override with `DB_PATH`. Keep it private.

See `server/config.example.env` for every setting.

### Admin

Make yourself an admin, then an **Admin** link appears in the panel header:

```
python app.py createadmin you@example.com    # make yourself an admin (Business plan)
```

The admin page (`/admin`, admins only) shows platform stats (accounts,
devices, online now, active schedules), a plan breakdown, and a table of every
account with its plan, device count, online devices and join date — plus
inline actions to change a user's plan or delete an account. The same actions
are available from the CLI:

```
python app.py setplan user@example.com pro   # manually set a plan
python app.py listusers                      # list accounts + device usage
```

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

## 2. Create an account & add a device

1. Browse to `https://api.amos.fyi`, click **Create account**, register with an
   email + password. New accounts start on the Free plan (3 devices).
2. Click **Add device**, give it a name, then **⬇ Download config.ini** — this
   is a ready-to-use config with the server URL and API key already filled in.
   (The key is shown only once; you can also **Copy key** to paste manually.
   At your plan's limit you'll be prompted to upgrade instead.)

## 3. Run the listener on your PC

```
cd client
pip install -r requirements.txt
```

Then drop the **config.ini you downloaded** from the panel into this `client/`
folder — that's the whole setup, no editing needed.

<details><summary>Prefer to do it by hand?</summary>

```
copy config.example.ini config.ini     # on Windows (use cp on macOS/Linux)
```

and edit `config.ini`:

```
server_url = https://api.amos.fyi
api_key    = <the key from the panel>
device     = Home PC
```
</details>

Then:

```
python listener.py
```

Set `dry_run = true` in `config.ini` while testing — commands are logged but
not executed.

### Start it automatically (background, no terminal window)

Use the installer for the PC's OS — each one sets the listener to start
silently at every login and keeps it running in the background:

| OS | Install | Uninstall |
|---|---|---|
| Windows | double-click `install-windows.bat` | `uninstall-windows.bat` |
| macOS | `bash install-macos.sh` | `launchctl unload …` (printed by installer) |
| Linux | `bash install-linux.sh` | `systemctl --user disable --now remote-power-listener` |

- **Windows** runs it with `pythonw.exe` from a Startup-folder launcher, so no
  console window ever appears.
- **macOS** installs a LaunchAgent; **Linux** a user `systemd` service.
- Activity is logged to `client/listener.log` (rotating). On Linux you can also
  use `journalctl --user -u remote-power-listener -f`.

Run the installer only after `config.ini` is filled in.

## 4. Use it

From the panel you'll see each device with its online status and buttons:

- **Shut down** — powers the PC off.
- **Restart** — reboots it.
- **Lock** — locks the screen.
- **Cancel** — clears a command you queued before the PC picks it up.

Commands are delivered on the listener's next poll (every 5s by default).

## Screen previews (optional, off by default)

Each expanded device card can show a **thumbnail of that PC's screen**, captured
only when you open the panel. It's **opt-in per device** for privacy:

1. On that PC, install the extras: `pip install mss pillow`.
2. In its `config.ini`, set `allow_screenshots = true` and restart the listener.

When the owner opens the panel, online devices are asked to capture one still
image, which is downscaled to a JPEG and shown in the card (and stored as the
latest preview on the server, one per device). Devices with the option off just
show a placeholder — power control is unaffected either way. Previews are
owner-only (served through an authenticated route) and are never continuous
recording.

## Billing (Stripe subscriptions)

Paid plans use [Stripe Checkout](https://stripe.com) + subscriptions. Without
Stripe configured, everything works except paid upgrades (you can still set
plans with `app.py setplan`).

To enable it:

1. In the Stripe Dashboard, create two **recurring Products/Prices** — one for
   Pro, one for Business — and copy their Price IDs (`price_...`). Set the
   displayed amounts to match `server/plans.py` (or edit `plans.py` to match
   Stripe).
2. Add a **webhook endpoint** pointing at `https://api.amos.fyi/billing/webhook`,
   subscribed to `checkout.session.completed`,
   `customer.subscription.updated` and `customer.subscription.deleted`. Copy
   its signing secret.
3. Put the keys in `/etc/remote-power.env`:
   ```
   STRIPE_SECRET_KEY=sk_live_...
   STRIPE_WEBHOOK_SECRET=whsec_...
   STRIPE_PRICE_PRO=price_...
   STRIPE_PRICE_BUSINESS=price_...
   PUBLIC_URL=https://api.amos.fyi
   ```
4. Restart the relay. The upgrade screen now sends customers to Stripe
   Checkout, and the webhook updates their plan automatically. "Manage billing"
   opens the Stripe customer portal so they can cancel or change card.

Test with Stripe **test mode** keys first (and `stripe listen --forward-to
localhost:8000/billing/webhook` for local webhooks).

## Security

The web panel is account-protected (one login per customer), so the relay is
hardened accordingly:

- **HTTPS only.** The login cookie is marked `Secure` + `HttpOnly` +
  `SameSite=Lax`, and HSTS is sent. (For local http testing set
  `INSECURE_COOKIES=1`.) Never expose the relay over plain HTTP — account
  passwords and device API keys would travel in clear text.
- **Account passwords are hashed** (werkzeug / PBKDF2), never stored in plain
  text, and each account sees only its own devices.
- **Brute-force lockout.** After 5 failed logins an IP is locked out for 5
  minutes, with **session rotation on login** (anti session-fixation).
- **CSRF protection** on every state-changing panel request. The listener
  `/api/*` endpoints use Bearer-token auth (no cookie) and the Stripe webhook
  is verified by signature, so neither is CSRF-exposed.
- **Strict Content-Security-Policy**, `X-Frame-Options: DENY` (no
  clickjacking), `nosniff`, and a 64 KB request-body cap.
- Device API keys are stored only as **hashes**; the plaintext is shown once
  at enrollment. Anyone with a key can power that PC off — keep `config.ini`
  private, and **Remove** a device in the panel to revoke its key instantly.
- Set `SECRET_KEY` so logins survive a restart, and keep `power.db` and
  `/etc/remote-power.env` private.

### Why a domain and not the raw server IP

The listener and panel talk to `https://api.amos.fyi`, not the server's raw
`172.x` IP, on purpose: a hostname lets Cloudflare terminate TLS with a valid
certificate so traffic is encrypted and the origin IP stays hidden behind
Cloudflare. Pointing straight at the IP would mean either no TLS (keys sent in
clear text) or certificate warnings, and would expose the origin to direct
attack. If you ever do need the IP, put it behind HTTPS too.

## Requirements

- Server: Python 3.9+, `flask`, `waitress`, `stripe` (billing optional).
- Client: Python 3.9+, `requests`.

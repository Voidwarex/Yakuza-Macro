# Deploying Remote Power (SSH)

You have two things to put on your server:

| What | Where it goes | Address |
|---|---|---|
| **Website** (`website/index.html`) | static files in `/var/www/amos` | `https://amos.fyi` |
| **Relay** (`server/`) | a running service behind nginx | `https://api.amos.fyi` |

> Why amos.fyi still shows the old macro page: nothing was pushed to your
> server yet — only to GitHub. The steps below copy the new files across.

## First-time deploy

SSH into the server that serves amos.fyi, then:

```bash
# 1. Get the code
git clone https://github.com/Voidwarex/Yakuza-Macro.git ~/remote-power
cd ~/remote-power          # already on main

# 2. Create the secrets file for the relay
sudo cp server/config.example.env /etc/remote-power.env
sudo nano /etc/remote-power.env
#   - set SECRET_KEY: run  python3 -c "import secrets;print(secrets.token_hex(32))"
#   - (optional) add the STRIPE_* keys to enable paid plans — see README "Billing"

# 3. (api.amos.fyi) install the nginx vhost for the relay — reuses your
#    existing Cloudflare Origin cert at /etc/ssl/amos/
sudo cp deploy/nginx-api.conf /etc/nginx/conf.d/remote-power-api.conf
#    Make sure api.amos.fyi has an A record in Cloudflare (proxied) -> server IP.

# 4. Run the deploy script (publishes the site + starts the relay + reloads nginx)
sudo bash deploy/deploy.sh

# 5. Make yourself an admin account (optional, Business plan + admin CLI)
cd /opt/remote-power && sudo -E python3 app.py createadmin you@example.com
```

Then open **https://amos.fyi** (new landing page) and **https://api.amos.fyi**
(click **Create account** to register, or sign in).

## Updating later

```bash
cd ~/remote-power
git pull
sudo bash deploy/deploy.sh
```

## What the script does

- Copies `website/index.html` to `/var/www/amos/index.html` (the amos.fyi page).
- Installs `server/` to `/opt/remote-power`, installs Python deps.
- Installs/starts the `remote-power` systemd service (the relay on 127.0.0.1:8000).
- Reloads nginx.

Paths (`WEB_ROOT`, `APP_DIR`, `RUN_USER`, …) are variables at the top of
`deploy/deploy.sh` — edit them if your server uses different locations.

## Notes

- **Retiring the macro:** your old license server already uses
  `api.amos.fyi` on port 8000, so the new relay replaces it. Stop and disable
  the old service first so the port is free:
  ```bash
  sudo systemctl disable --now <old-license-server-service>
  ```
  (If you'd rather keep both running, give the relay a different `PORT` in
  `/etc/remote-power.env`, point it at a new subdomain, and update
  `deploy/nginx-api.conf` to match.)
- Keep `/etc/remote-power.env` and the relay's `power.db` private.
- If `amos.fyi` caches the old page in your browser, hard-refresh
  (Ctrl/Cmd+Shift+R) — nginx also caches `index.html` for 5 minutes.

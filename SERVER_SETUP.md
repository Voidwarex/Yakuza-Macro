# First-time server setup — copy-paste runbook

Run these on the server that hosts **amos.fyi** (over SSH). Lines in **CAPS**
are placeholders to replace. If a step says "if…", only run it when it applies.

> Assumes a Debian/Ubuntu server with nginx and the Cloudflare Origin cert
> already in place at `/etc/ssl/amos/` (same as your old macro setup).

---

## 0. Connect

```bash
ssh YOURUSER@YOUR_SERVER_IP
```

## 1. Prerequisites (safe to re-run)

```bash
sudo apt update
sudo apt install -y git python3 python3-venv nginx
```

## 2. Free up api.amos.fyi (stop the old macro license server)

The relay uses port 8000 / api.amos.fyi, which your old macro server used. Find
and stop it:

```bash
# See what's on port 8000:
sudo ss -ltnp | grep ':8000' || echo "nothing on 8000"

# If it's a systemd service, find its name:
systemctl list-units --type=service | grep -iE 'license|amos|yakuza' || true

# Stop & disable it (replace SERVICENAME with what you found above):
sudo systemctl disable --now SERVICENAME

# If it was NOT a systemd service (started by hand / screen / tmux):
sudo pkill -f license_server.py || true
```

## 3. Get the code

```bash
git clone https://github.com/Voidwarex/Yakuza-Macro.git ~/remote-power
cd ~/remote-power
```

## 4. Create the secrets file

```bash
sudo cp server/config.example.env /etc/remote-power.env

# Generate and insert a random SECRET_KEY:
SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
sudo sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" /etc/remote-power.env

# Review it — make sure PUBLIC_URL=https://api.amos.fyi, HOST=127.0.0.1, PORT=8000.
# Leave the STRIPE_* lines blank for now (billing is optional).
sudo nano /etc/remote-power.env
```

## 5. Install the nginx site for api.amos.fyi

```bash
sudo cp deploy/nginx-api.conf /etc/nginx/conf.d/remote-power-api.conf
sudo nginx -t
```

- In **Cloudflare DNS**, make sure `api.amos.fyi` has an A record → your
  server's IP, proxied (orange cloud). You likely already have this.
- If your cert isn't at `/etc/ssl/amos/origin.pem` + `origin.key`, edit the
  paths in `/etc/nginx/conf.d/remote-power-api.conf`.

## 6. Deploy (publishes the site + starts the relay + reloads nginx)

```bash
sudo bash deploy/deploy.sh
```

## 7. Create your admin account

```bash
cd /opt/remote-power
sudo -u www-data venv/bin/python app.py createadmin YOUR_EMAIL
# (it prompts for a password; this account is admin + Business plan)
```

## 8. Check it works

```bash
# Relay healthy?
curl -s http://127.0.0.1:8000/healthz ; echo
# Through Cloudflare?
curl -s https://api.amos.fyi/healthz ; echo
# Service status / logs if needed:
systemctl status remote-power --no-pager
journalctl -u remote-power -n 30 --no-pager
```

Then open:
- **https://amos.fyi** — the marketing site
- **https://api.amos.fyi** — the panel (sign in, add a device)

---

## Updating later (after I push changes)

```bash
cd ~/remote-power && git pull && sudo bash deploy/deploy.sh
```

## Turn on analytics (optional, 1 click)

Cloudflare dashboard → **Analytics → Web Analytics** → enable for amos.fyi.
No code needed since the site is already proxied through Cloudflare.

## Connecting a PC afterwards

1. In the panel, **Add device** → copy the one-time API key.
2. On the PC: install Python, then in the `client/` folder:
   `pip install -r requirements.txt`, copy `config.example.ini` to `config.ini`,
   paste the key, and run `python listener.py`.

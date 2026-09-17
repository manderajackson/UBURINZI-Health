# Deploy Uburinzi Health (and put it on your phone)

Three ways up, from fastest to most production-grade. Pick one; the app is identical in all three.

| Option | Time | Cost | Best for |
|---|---|---|---|
| **A. ngrok tunnel** | 2 min | free | Demo today, webhooks reachable from Africa's Talking |
| **B. PaaS (Railway / Fly.io / Render)** | 20 min | $5–10 / month | Get a real HTTPS URL without touching a server |
| **C. Your own VPS** | 45 min | $5–6 / month | Full control, clinic data stays in country, cheapest at scale |

You need **HTTPS** for the voice and WhatsApp webhooks — Africa's Talking fetches your IVR script over
the public internet, and browsers will only install the dashboard as an app over HTTPS.

---

## Option A — ngrok (demo today)

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000   # in one terminal
ngrok http 8000                                             # in another
```
Copy the `https://….ngrok-free.app` URL it prints, paste it into **Channels → Public base URL**, and
copy the six webhook URLs shown there into Africa's Talking. Restarting ngrok changes the URL, so this
is for demos, not production.

---

## Option B — PaaS (Railway / Fly.io / Render)

1. Push the project to a private Git repo (or upload the zip).
2. Create a service from the repo with:
   * **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   * **Environment variables** (see the table below).
3. Add a **persistent disk** mounted at `/app/data` so the SQLite file survives redeploys — or set
   `UBURINZI_DATABASE_URL` to a managed Postgres URL.
4. Open the assigned HTTPS URL, sign in, then set **Channels → Public base URL** to it and copy the
   webhook URLs into Africa's Talking.

Keep `--workers 1`: the built-in scheduler thread must not run twice. If your platform insists on
several workers, set `UBURINZI_SCHEDULER=false` and run `python -m app.cli run-scheduler` as a second
service.

---

## Option C — Your own VPS (recommended for a clinic pilot)

Ubuntu 24.04 on any $5 host (Hetzner, DigitalOcean, Contabo, AWS Lightsail). Everything below is
copy-paste.

### 1. Server basics

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip git
sudo adduser uburinzi --disabled-password --gecos ""     # or use your own user
sudo usermod -aG sudo uburinzi
```

### 2. Get the code

```bash
sudo -iu uburinzi
git clone <your-repo> uburinzi && cd uburinzi      # or: unzip uburinzi-health.zip && cd uburinzi
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.cli reset                            # creates data/uburinzi.db + demo cohort
```

### 3. Environment

```bash
cp .env.example .env
nano .env
```

```bash
UBURINZI_SECRET_KEY=<python3 -c "import secrets;print(secrets.token_hex(32))">
UBURINZI_TIMEZONE=Africa/Kigali
UBURINZI_AUTO_SEED=true                # false once you have real patients
UBURINZI_SMS_DRIVER=africastalking
UBURINZI_WHATSAPP_DRIVER=at_whatsapp
UBURINZI_VOICE_DRIVER=at_voice
AFRICASTALKING_USERNAME=<your-username>
AFRICASTALKING_API_KEY=<atsk_…>
UBURINZI_SMS_SENDER_ID=UBURINZI
UBURINZI_AT_VOICE_NUMBER=+250…
UBURINZI_AT_WHATSAPP_NUMBER=+250…
UBURINZI_PUBLIC_BASE_URL=https://uburinzi.yourdomain.org
```

### 4. Run it as a service

`/etc/systemd/system/uburinzi.service`:

```ini
[Unit]
Description=Uburinzi Health
After=network.target

[Service]
User=uburinzi
WorkingDirectory=/home/uburinzi/uburinzi
Environment="PATH=/home/uburinzi/uburinzi/.venv/bin"
EnvironmentFile=/home/uburinzi/uburinzi/.env
ExecStart=/home/uburinzi/uburinzi/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now uburinzi
sudo systemctl status uburinzi
```

### 5. HTTPS with Caddy (automatic certificates)

```bash
sudo apt install -y caddy
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
uburinzi.yourdomain.org {
    reverse_proxy 127.0.0.1:8000
    encode gzip
}
EOF
sudo systemctl reload caddy
```
Point your domain's **A record** at the server IP first; Caddy obtains and renews the certificate
automatically. That's it — `https://uburinzi.yourdomain.org` is live.

### 6. Backups

```bash
# every night at 02:00 — keeps 14 days of SQLite snapshots
sudo -iu uburinzi
mkdir -p ~/backups
crontab -e
0 2 * * * cd ~/uburinzi && sqlite3 data/uburinzi.db ".backup '/home/uburinzi/backups/uburinzi-$(date +\%F).db'" && find /home/uburinzi/backups -name '*.db' -mtime +14 -delete
```

### 7. Optional: move to Postgres

```bash
sudo apt install -y postgresql
sudo -u postgres createuser uburinzi --pwprompt
sudo -u postgres createdb uburinzi -O uburinzi
# in .env:
UBURINZI_DATABASE_URL=postgresql+psycopg://uburinzi:<password>@localhost:5432/uburinzi
```
(Add `psycopg[binary]` to `requirements.txt`.) Nothing else changes — the models are portable.

---

## Environment variable reference

| Variable | Purpose |
|---|---|
| `UBURINZI_SECRET_KEY` | Signs sessions and encrypts stored credentials — **change it** |
| `UBURINZI_TIMEZONE` | Clinic timezone (`Africa/Kigali`) |
| `UBURINZI_DATABASE_URL` | SQLite by default; Postgres for scale |
| `UBURINZI_AUTO_SEED` | Load the demo cohort on an empty DB (set `false` for real use) |
| `UBURINZI_SMS_DRIVER` / `_WHATSAPP_` / `_VOICE_` | `simulator` · `africastalking` · `at_whatsapp` · `at_voice` |
| `AFRICASTALKING_USERNAME` / `AFRICASTALKING_API_KEY` | Live credentials (`sandbox` + sandbox key for testing) |
| `UBURINZI_SMS_SENDER_ID` | Approved sender ID or short code |
| `UBURINZI_AT_VOICE_NUMBER` / `UBURINZI_AT_WHATSAPP_NUMBER` | Numbers provisioned on AT |
| `UBURINZI_PUBLIC_BASE_URL` | Used to build the webhook URLs |
| `UBURINZI_SEND_WINDOW_START` / `_END` | Quiet hours (default 08:00–18:00) |
| `UBURINZI_DAILY_SMS_CAP` | Hard daily spend guard (default 500) |
| `UBURINZI_SMS_COST_RWF` / `_WHATSAPP_` / `_VOICE_` | Cost model for the dashboard |

---

## Post-deploy checklist

- [ ] `https://your-domain/health` returns `{"ok": true}`
- [ ] Sign in, change the default password (`/settings` → Users)
- [ ] **Channels → Public base URL** set to the HTTPS domain
- [ ] Six webhook URLs pasted into Africa's Talking (SMS in/out, WhatsApp, voice answer/dtmf/event)
- [ ] **Check balance** succeeds → credentials are valid
- [ ] **Test SMS**, **Test WhatsApp**, **Test call** all succeed to your own phone
- [ ] Escalation policy reviewed (24 h → WhatsApp, 48 h → voice, caps)
- [ ] `UBURINZI_AUTO_SEED=false` before enrolling real patients
- [ ] Nightly backup job confirmed (restore one backup to prove it works)

## Monitoring

| Check | How |
|---|---|
| Is it up? | `curl https://your-domain/health` (or a free UptimeRobot ping) |
| Logs | `sudo journalctl -u uburinzi -f` |
| Failed SMS | `/messages?status=failed` |
| Unanswered patients | `/alerts` (rule `silent_patient`) |
| Spend | Dashboard → *SMS sent* KPI, or AT dashboard billing |

## Indicative running cost (50–200 patients)

| Item | Monthly |
|---|---|
| VPS (2 vCPU / 2 GB) | $5–6 |
| Domain | $1 |
| Africa's Talking credit (200 patients ≈ 4,000 SMS) | ~$75 |
| Voice calls (say 60 minutes) | ~$2 |
| **Total** | **≈ $85 / month** — about **$0.40 per patient** |

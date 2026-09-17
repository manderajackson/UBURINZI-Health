# Deploying Uburinzi Health to Vercel

Vercel runs the site; **Vercel Cron** replaces the background worker; **Postgres** replaces the
SQLite file. That is the whole adaptation, and it is already in the repo (`vercel.json`,
`api/index.py`, `/api/cron/scheduler`).

> Two things about serverless that shape this: the filesystem is **read-only and ephemeral** (a
> SQLite database would vanish between requests), and there is **no background thread**. Hence
> Postgres + cron.

---

## 1. Create a Postgres database (2 minutes)

Use [Neon](https://neon.tech) (free tier, no card) or Vercel Postgres:

1. Create a database in the **same region** as your Vercel deployment.
2. Copy the connection string and convert the scheme:
   ```
   postgresql://user:pass@host/db?sslmode=require
   → postgresql+psycopg://user:pass@host/db?sslmode=require
   ```
   (The app reads `DATABASE_URL`, or `UBURINZI_DATABASE_URL`.)

## 2. Push the project to GitHub

```bash
cd ~/uburinzi
git init && git add . && git commit -m "Uburinzi Health"
gh repo create uburinzi-health --private --push   # or create it in the GitHub UI
```

`.env` is git-ignored, so no credential ever reaches GitHub.

## 3. Import into Vercel

1. **vercel.com → Add New → Project** → import the repo.
2. Framework preset: **Other** (leave `framework: null` — `vercel.json` handles it).
3. **Environment Variables** — add these:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://…` (required) |
| `SECRET_KEY` | long random string — encrypts stored provider credentials |
| `AFRICASTALKING_USERNAME` | `Uburinzi` |
| `AFRICASTALKING_API_KEY` | your `atsk_…` key |
| `AFRICASTALKING_SANDBOX` | `false` |
| `UBURINZI_SMS_SENDER_ID` | `UBURINZI` once approved (leave empty until then) |
| `UBURINZI_PUBLIC_BASE_URL` | `https://your-app.vercel.app` (makes webhook URLs correct) |
| `UBURINZI_DAILY_SMS_CAP` | spend guard, e.g. `200` |
| `UBURINZI_REPLY_CHANNEL` | `ussd` once your USSD code is live |
| `UBURINZI_USSD_CODE` | e.g. `384*96#` |
| `UBURINZI_PLAY_SHA256` | Play signing fingerprint (see play-store.md) |
| `CRON_SECRET` | random string — protects `/api/cron/scheduler` |

4. **Deploy.** The first build installs `requirements.txt` (including `psycopg[binary]`).

## 4. What happens on Vercel automatically

* `api/index.py` exposes the FastAPI app as an ASGI function.
* The background scheduler thread **does not start** — `app/config.py` disables it when the `VERCEL`
  env var is present, because a serverless process freezes between requests.
* `vercel.json` registers four cron calls: 06:00 (daily sweep + sends) and 09:00 / 13:00 / 16:00
  (send due check-ins + escalation sweep) — aligned to the 08:00–18:00 sending window.
  *On the Hobby plan Vercel allows cron jobs once per day; keep the 06:00 entry and drop the others,
  or use a free external scheduler (cron-job.org) to hit `/api/cron/scheduler` more often.*
* `/download` builds its zip into the temp directory when the project directory is read-only.
* Postgres is created on first boot (`init_db`) and seeded with the demo cohort if empty — so your
  first deploy shows a working dashboard straight away.

## 5. Point Africa's Talking at Vercel

With `UBURINZI_PUBLIC_BASE_URL` set, `python -m app.cli channels` prints the exact URLs. Paste them
into the AT dashboard:

| Purpose | URL |
|---|---|
| USSD callback | `/api/webhooks/ussd` |
| Inbound SMS (short code) | `/api/webhooks/sms/inbound` |
| Delivery reports | `/api/webhooks/sms/delivery` |
| WhatsApp | `/api/webhooks/whatsapp` |
| Voice (not available in Rwanda) | `/api/webhooks/voice/answer` |

## 6. Verify the deployment

- [ ] `https://your-app.vercel.app/health` returns `{"ok": true}`
- [ ] `/login` → `manderajackson99@gmail.com` / `uburinzi2026` → **change this password immediately**
- [ ] The login page no longer pre-fills anything: `DEMO_MODE` switches itself off when the `VERCEL`
      env var is present, so the demo accounts and password are never printed on a public page
- [ ] `/api/channels/balance` shows your Africa's Talking balance
- [ ] `curl -H "Authorization: Bearer $CRON_SECRET" https://your-app.vercel.app/api/cron/scheduler?daily=1` returns `ok`
- [ ] `/.well-known/assetlinks.json` returns JSON (needed for the Play Store app)
- [ ] `/privacy` renders
- [ ] On a phone: install from the browser and confirm no address bar

## 7. Keeping it running

* **Costs:** Vercel Hobby is free for non-commercial use; Neon free tier covers the pilot.
  Commercial use needs Vercel Pro (~$20/mo) plus SMS credit (~12 RWF per message).
* **Backups:** Neon keeps point-in-time restore; also export CSVs from `/api/export/*` weekly.
* **Logs:** Vercel → your project → **Logs**; cron runs appear there too.
* **Rollback:** Vercel keeps every deployment — promote a previous one instantly.

## 8. Local development is unchanged

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

SQLite, the background thread and the simulator all still work locally. Only the deployed
environment switches to Postgres + cron.

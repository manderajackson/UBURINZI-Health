# Uburinzi Health — project dossier

The memory of this project. Everything needed to understand it, run it, redeploy it, or restore it,
written so that it survives independently of any sandbox, laptop or conversation.

*Last updated: 18 September 2026.*

---

## 1. What we're building

Chronic-disease patient monitoring **between clinic visits**, for a private clinic with a
14-service outpatient department. A patient with diabetes, hypertension, HIV, TB, asthma, epilepsy,
heart failure or an antenatal pregnancy gets an ordinary SMS on the day their medication is due,
answers `1 = yes I took it`, `2 = no`, `3 = I'm not well`, and the clinic sees who is slipping
**before** the next appointment rather than after it.

**The constraint that drives every decision:** the patient installs nothing and needs no data. A 2G
feature phone is enough. WhatsApp and voice are escalations for people who have them, never a
requirement.

Original MVP checklist (all delivered): patient database · SMS engine · condition-specific templates
in Kinyarwanda and English (plus French and Swahili) · response tracker · rule-based alerts · clinic
dashboard · 20+ enrolled patients (53 seeded).

Business model: B2B SaaS — clinic subscription, insurer or donor pays; free for patients.

---

## 2. Where everything lives

| What | Where | Durable? |
|---|---|---|
| Source code (canonical) | `/home/user/uburinzi/` | sandbox |
| Git repo, ready to push | `/home/user/github-upload/` (91 files, auto-committed) | sandbox |
| Source zip | `/home/user/uburinzi/dist/uburinzi-health.zip` | sandbox |
| GitHub zip (flat) | `/home/user/uburinzi/dist/uburinzi-health-github.zip` | sandbox |
| **Public repo** | `github.com/manderajackson/UBURINZI-Health` | ✅ permanent |
| **Live site** | `uburinzi.vercel.app` | ✅ (running old code, see §6) |
| **Backup: full repo + history** | `/home/user/backups/UBURINZI-Health-2026-09-18.bundle` | sandbox |
| **Backup: workspace + database** | `/home/user/backups/uburinzi-workspace-2026-09-18.zip` | sandbox |
| Africa's Talking account | AT dashboard, app `UBURINZI` | ✅ permanent |
| Database (patients, settings) | `uburinzi/data/uburinzi.db` | sandbox + zip backup |

⚠️ The sandbox is **ephemeral** — installed packages and `/tmp` are cleared between sessions. Code
under `/home/user` persists, but only **GitHub and Vercel are truly permanent**. Getting the code
pushed is therefore the single most important durability step.

---

## 3. How to restore from a backup

**The GitHub repo, from the bundle** (complete history, all 4 original commits, all 213 files):

```bash
git clone /home/user/backups/UBURINZI-Health-2026-09-18.bundle restored
cd restored && git log --oneline       # all four commits are there
```

**The workspace, from the zip** (includes the patient database):

```bash
unzip /home/user/backups/uburinzi-workspace-2026-09-18.zip
cd uburinzi && pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Any deleted file, from git history** — nothing is ever really gone:

```bash
git checkout 2f683a9 -- uburinzi/     # restore the old snapshot by commit
git log --diff-filter=D --name-only   # find deleted files and when
```

---

## 4. Accounts

| Email | Password | Role | Name |
|---|---|---|---|
| `manderajackson99@gmail.com` | `uburinzi2026` | admin | Mandera Jackson |
| `yahshuamediasite@gmail.com` | `uburinzi2026` | clinician | UWASE Aline |

Retired: `founder@uburinzi.rw`, `nurse@uburinzi.rw`. API header: `X-API-Key: demo-api-key`.
**Change both passwords on the public site** — they're written into the repository.

---

## 5. Live services

| Service | State |
|---|---|
| Africa's Talking app | **UBURINZI**, username `Uburinzi`, sandbox **off**, live |
| Wallet | **RWF 91.74** (≈8 SMS) — top up before the pilot |
| SMS | 🟢 live driver; 4 real messages accepted with message IDs |
| Measured price | **10–12 RWF per SMS** (varies by network) |
| WhatsApp | ⏸ simulator — AT has no WhatsApp product in Rwanda |
| Voice | ⏸ unavailable — AT lists only SMS + USSD for Rwanda |
| USSD | 🟢 built, switched off until AT issues a real code |
| Sender ID | not yet registered — messages arrive as `AFRICASTKNG` |

Credentials live in `uburinzi/.env` (git-ignored, never bundled) and encrypted in the database.

---

## 6. Deployment state

**Vercel (`uburinzi.vercel.app`) is running an old build and cannot sign in.**

Diagnosis, from `curl https://uburinzi.vercel.app/health`:

- `/health` returns only `{"ok":true,...,"driver":"simulator"}` — the old format, so the deployed
  code predates the diagnostics work.
- `POST /login` → **500**. A SQLite file cannot be created on Vercel's read-only filesystem, and no
  `DATABASE_URL` was ever set.
- The login page still shows `founder@uburinzi.rw`, `nurse@uburinzi.rw` and the accelerator footer.

Root cause of the staleness: the GitHub repo holds **three nested snapshots** and Vercel was
building one of the old ones:

```
uburinzi/                56 files   oldest — founder@ ×8,  no vercel.json
workspace-01/uburinzi/   71 files   older  — founder@ ×10
workspace-02/uburinzi/   85 files   newest — manderajackson99 ×11, has vercel.json
github-upload.md                    stray doc
```

**The fix** is in [WHAT-YOU-NEED-TO-DO.md](WHAT-YOU-NEED-TO-DO.md): flatten the repo to one project
at the root, clear Vercel's Root Directory, add Postgres, set the environment variables, redeploy.

---

## 7. Environment variables (Vercel)

Every variable except `CRON_SECRET` is prefixed `UBURINZI_`. The app also accepts unprefixed
`DATABASE_URL` / `SECRET_KEY`, and rewrites `postgres://` → `postgresql+psycopg://` (adding
`sslmode=require`) automatically, because Neon's copy-paste string is incompatible with the psycopg 3
driver we install.

| Variable | Value |
|---|---|
| `UBURINZI_DATABASE_URL` | Neon connection string, pasted as-is — **required** |
| `UBURINZI_SECRET_KEY` | long random string |
| `CRON_SECRET` | long random string — **no prefix** |
| `AFRICASTALKING_USERNAME` | `Uburinzi` |
| `AFRICASTALKING_API_KEY` | `atsk_…` from the AT dashboard |
| `AFRICASTALKING_SANDBOX` | `false` |
| `UBURINZI_PUBLIC_BASE_URL` | `https://uburinzi.vercel.app` |
| `UBURINZI_DAILY_SMS_CAP` | `200` |
| `UBURINZI_SMS_COST_RWF` | `12` |

Vercel env vars only apply to **new** deployments — always Redeploy after changing them.

---

## 8. Design decisions worth remembering

| Decision | Why |
|---|---|
| SMS-first, USSD for replies | **Rwanda cannot receive replies to A2P SMS** (carrier-level, MTN + Airtel). Voice isn't sold by AT here either, so the 48-hour escalation rung becomes a "phone this patient" task. |
| SQLite locally, Postgres on Vercel | SQLite gives a zero-config pilot; serverless filesystems are ephemeral, so `DATABASE_URL` swaps in Postgres with no code change. |
| Server-rendered Jinja2 dashboard, not React | Guarantees a runnable MVP; the PWA wraps it for install and offline use. |
| Templates as database rows | Nurses edit Kinyarwanda/English wording in **Protocols** without a developer. |
| Sending window 08:00–18:00, hard daily cap | Anti-harassment and cost control; `force` bypasses the window but never the cap. |
| Timezone default `Africa/Kigali` | Suits the pilot; set `UBURINZI_TIMEZONE` to the clinic's own zone elsewhere. Product copy is deliberately country-neutral. |

---

## 9. Commands

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000   # run (dies when the sandbox sleeps)
python -m app.cli seed | reset | stats                      # demo data, impact report
python -m app.cli send-due | daily-jobs | run-scheduler     # drive the engine by hand
python -m app.cli import-csv data/clinic.csv                # real patients
python -m app.cli use-live --from-env --test-to 0784852344  # connect Africa's Talking
python -m app.cli channels                                  # balance + webhook URLs
python -m app.cli bundle                                    # refresh ~/github-upload + zips
python -m app.cli push --repo <url> [--clean] [--dry-run]   # push to GitHub (branch-aware)
python -m pytest tests -q                                   # 73 tests
```

Webhooks: `/api/webhooks/sms/inbound`, `/api/webhooks/sms/delivery`, `/api/webhooks/ussd`,
`/api/webhooks/whatsapp`, `/api/webhooks/voice/answer`, `/api/webhooks/voice/dtmf`,
`/api/webhooks/voice/event`, `/api/cron/scheduler`.

---

## 10. Build log

1. **Core platform** — domain model, protocol engine, four languages, reply parsing, rule-based
   alerts, dashboard, 52-patient cohort, CSV import/export, 30-day impact report, PWA.
2. **Live channels** — Africa's Talking SMS proven with real sends; WhatsApp and voice drivers built.
3. **Live account** — created app `UBURINZI`, went live, measured 10–12 RWF/SMS, corrected the cost
   model (it had been a 27 RWF guess).
4. **Rwanda reply path** — discovered the two-way A2P and Voice restrictions; built USSD,
   self-rewriting check-ins, graceful voice degradation.
5. **Deploy + store** — Vercel adaptation, Play Store TWA package, asset links, privacy policy,
   screenshots.
6. **Identity** — accounts renamed to Mandera Jackson and UWASE Aline; Kigali removed from product
   copy; accelerator branding purged; `app.cli bundle` regenerates the GitHub folder after changes.
7. **Diagnostics** — `/health` now reports database reachability, drivers and serverless mode.
8. **Push tooling** — `app.cli push` clones, flattens and pushes; detects repeated zip-upload
   snapshots by shape, not by name.
9. **Deployment-var correctness** — found and fixed wrong variable names in our own guides, and made
   Postgres URLs self-normalising.

Five production bugs found and fixed along the way: drivers receiving the encrypted key blob;
`/channels/test` crashing on a second test number; voice dedupe keys colliding on a patient's second
weekly call; `force` bypassing the daily spend cap; and AT's `"RWF 12.0000"` cost string being
mis-parsed so every message logged the old estimate.

---

## 11. Open items

| Item | Owner | Notes |
|---|---|---|
| Push the rebuild to GitHub | waiting on token write permission | 223 changes staged |
| Neon Postgres | user | the one thing blocking sign-in |
| Clear Vercel Root Directory | user | otherwise the build fails after the push |
| Set env vars, redeploy | user | env vars need a new deployment |
| Change default passwords | user | they're in the public repo |
| Register sender ID `UBURINZI` | user, ~3 weeks | needs AT + carrier approval |
| Request a USSD code | user | then enable it in Channels |
| Play Store listing | later | $25 Play Console fee |
| Top up AT credit | ongoing | keep above ~RWF 5,000 |
| Rotate the AT API key | recommended | it has been pasted into this conversation |

---

## 12. Verification checklist for a healthy deployment

```bash
curl https://uburinzi.vercel.app/health
```

```json
{"ok":true,"serverless":true,
 "database":{"dialect":"postgresql","reachable":true},
 "channels":{"sms":"africastalking","whatsapp":"simulator","voice":"simulator","reply":"sms"},
 "at_username":"Uburinzi"}
```

`dialect: postgresql` + `reachable: true` + **no `warning`** = healthy. If `dialect` is `sqlite`, or a
`warning` appears, that deployment cannot sign in.

Then: log in → dashboard loads → **Channels** shows a balance → send a test SMS → it arrives.

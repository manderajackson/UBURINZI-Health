# Uburinzi Health

**Chronic patient monitoring between clinic visits — SMS-first, Africa-ready, built for African clinics.**

> Clinic management systems manage patients *during* visits. Uburinzi manages them *between* visits —
> on the basic phone the patient already owns, with no app, no smartphone and no internet.

---

## 1. The gap this closes

| Number | Reality |
|---|---|
| < 50 % | Medication adherence for chronic conditions (WHO) |
| > 30 % | Follow-up appointment no-show rate |
| 36 % | Share of all deaths in Rwanda caused by NCDs |
| 1 : 10,000 | Doctor-to-patient ratio in Rwanda |

A patient is diagnosed, treated, given 30 days of medication… and then disappears until they come back
sicker. Uburinzi keeps the clinic connected to that patient automatically, and only escalates to a human
when something is wrong — which is how one nurse can monitor 500 patients instead of 50.

---

## 2. Quick start (60 seconds)

```bash
cd uburinzi
pip install -r requirements.txt
python -m app.cli reset          # creates the DB and loads a 52-patient demo cohort
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** and sign in:

| Email | Password | Role |
|---|---|---|
| `manderajackson99@gmail.com` | `uburinzi2026` | admin |
| `yahshuamediasite@gmail.com` | `uburinzi2026` | clinician |

That's it. No SMS gateway account, no API keys, no cloud. The built-in **SMS simulator** stands in for
the mobile network: it receives every message and answers as the patient would, so the whole loop —
check-in → reply → risk score → alert → dashboard — is live and measurable in your browser.

### Run the tests

```bash
python -m pytest tests -q      # 39 tests: scheduling, parsing, alerts, SMS/WhatsApp/voice, escalation, API
```

---

## 3. Live demo script (3 minutes — this is your application video)

1. **Dashboard** — adherence, response rate, open alerts, cost per patient, and the WHO-baseline
   comparison. All numbers recompute from real message data.
2. **SMS Simulator → "Generate realistic replies"** — watch the dashboard move as patients answer.
3. **Patients → open a red patient** — see the conversation thread in Kinyarwanda, the missed-dose
   streak, and the alert the rule engine raised.
4. **Alerts** — the nurse's worklist. Acknowledge one, resolve one. Show the rule table underneath.
5. **Patients → Add patient** — enrol in 10 seconds; welcome SMS goes out immediately.
6. **Messages** — full auditable log with delivery status, cost per SMS and the matched reply.
7. **Protocols** — edit the Kinyarwanda copy in the browser, no code deploy.
8. **`/api/impact-report`** — the JSON that feeds the application form and donor reports.

---

## 4. Screens

| Dashboard | Alert queue |
| --- | --- |
| ![Dashboard](docs/screenshots/dashboard.png) | ![Alerts](docs/screenshots/alerts.png) |

| Patient list (traffic-light triage) | Patient thread (Kinyarwanda SMS) |
| --- | --- |
| ![Patients](docs/screenshots/patients.png) | ![Patient thread](docs/screenshots/patient-thread.png) |

| Channels & escalation | Alert queue |
| --- | --- |
| ![Channels](docs/screenshots/channels.png) | ![Alerts](docs/screenshots/alerts.png) |

---

## 5. What is actually built

| MVP component (from the application plan) | Status | Where it lives |
|---|---|---|
| Patient database (names, phone, conditions, medication) | ✅ Built | `app/models.py` — `Patient`, `Enrollment`, `Clinic` |
| SMS engine with automated scheduling | ✅ Built | `app/engine.py` (scheduler) + `app/messaging/` (drivers) |
| Condition-specific templates in Kinyarwanda + English | ✅ Built | `app/protocols.py`, editable in the UI at `/protocols` |
| Response tracker (1 = Yes, 2 = No, 3 = Not well) | ✅ Built | `POST /api/webhooks/sms/inbound` + `parse_reply()` |
| Alert system that flags at-risk patients | ✅ Built | `app/engine.py` → `evaluate_patient()` |
| Clinic dashboard (green / amber / red) | ✅ Built | `GET /` + `app/charts.py` (dependency-free SVG) |
| Enrolled patients receiving messages | ✅ Built | 52 demo patients with 75 days of history; real enrolment at `/patients/new` |
| Africa's Talking integration | ✅ Built | `app/messaging/drivers.py` — swap one env var |
| Clinic system integration | ✅ Built | CSV import + `POST /api/integrations/patients` |
| Multi-language (FR, SW added) | ✅ Built | `rw / en / fr / sw` throughout |
| Auth, roles, audit log | ✅ Built | `app/security.py`, `AuditLog` |
| Impact metrics / donor reporting | ✅ Built | `app/metrics.py`, `/api/impact-report` |

**Also built (ahead of the MVP plan):** WhatsApp, voice calls and the SMS → WhatsApp → voice
escalation ladder — see §5b.

**Deliberately not built yet:** live ClinicPlus API adapter (CSV export is enough), multi-clinic
tenancy, ML models.

---

## 5b. Three channels, one escalation ladder

| Channel | Driver options | Typical unit cost |
|---|---|---|
| **SMS** — works on any phone, 2G, no data | simulator · Africa's Talking · console logger | ~27 RWF / segment |
| **WhatsApp** — richer, free-form inside the 24 h session, template outside it | simulator · Africa's Talking WhatsApp | ~12 RWF / message |
| **Voice** — automated IVR call, patient presses 1/2/3 | simulator · Africa's Talking Voice | ~60 RWF / minute |

The ladder (configurable on `/channels`):

```
1. SMS check-in on the condition cadence
2. no reply for 24 h  →  WhatsApp retry (template message if the 24 h session has closed)
3. no reply for 48 h  →  automated voice call (amber/red patients only, max 2/week)
4. still nothing      →  the alert stays on the nurse's worklist for a human call
```

Voice flow: the call is initiated via `POST https://voice.africastalking.com/call`; when the patient
answers, Africa's Talking fetches `/api/webhooks/voice/answer` and plays the IVR script we return
(`<Say>` / `<Play>` + `<GetDigits>`); the keypress lands on `/api/webhooks/voice/dtmf` and is treated
exactly like an `1`/`2`/`3` SMS reply.

> Kinyarwanda text-to-speech is not available from AT. Record a 10-second greeting with a local
> speaker, host the MP3, and paste its URL into **Channels → Recorded prompt URL**; the IVR plays
> that instead of TTS.

**To wire your real account:** open `/channels`, paste the credentials (encrypted at rest), pick the
live driver per channel, and press **Test SMS / Test WhatsApp / Test call**. Full walkthrough with
screenshots of every dashboard step: [`docs/live-setup.md`](docs/live-setup.md).

---

## 6. How the loop works

```
┌──────────────┐   protocol cadence    ┌──────────────┐   Africa's Talking
│  Scheduler   │ ────────────────────► │  Outbound    │ ──────────────────►  Patient's phone
│ (every 60 s) │   diabetes 3d, TB 2d  │  message     │                     (2G / basic phone)
└──────────────┘                       └──────────────┘
                                                                                    │ 1 / 2 / 3
                                                                                    ▼
┌──────────────┐   traffic light      ┌──────────────┐   webhook            ┌──────────────┐
│  Dashboard   │ ◄─────────────────── │ Alert engine │ ◄─────────────────── │   Inbound    │
│  + Alerts    │   green/amber/red    │ (rule-based) │                      │   message    │
└──────────────┘                      └──────────────┘                      └──────────────┘
```

### Alert rules (all auditable, no black box)

| Rule | Fires when | Severity |
|---|---|---|
| `medication_nonadherence` | 2 (amber) or 3 (red) consecutive "2 = No" replies | amber → red |
| `reported_unwell` | Patient replies "3 = Not feeling well" | red |
| `silent_patient` | 3+ check-ins with no reply at all | amber |
| `missed_appointment` | Appointment passes unattended; 2+ in a row escalates | amber → red |
| `appointment_confirm` | Visit in ≤ 3 days, patient hasn't confirmed | info |

Alerts auto-resolve when the patient recovers (e.g. reports taking medication again), so the queue
always reflects *right now* rather than history.

---

## 7. Project layout

```
uburinzi/
├── app/
│   ├── main.py           FastAPI app, background scheduler thread
│   ├── engine.py         scheduling, reply parsing, alert rules, daily sweep
│   ├── protocols.py      programmes, cadences and all patient-facing copy (rw/en/fr/sw)
│   ├── metrics.py        adherence, response rate, no-show rate, cost, impact report
│   ├── models.py         SQLAlchemy domain model
│   ├── seed.py           52-patient demo cohort with 75 days of history
│   ├── cli.py            init-db / seed / reset / send-due / import-csv / use-live / channels
│   ├── ussd.py           USSD reply channel (the two-way path where SMS cannot be answered)
│   ├── charts.py         dependency-free SVG charts (no CDN, works offline)
│   ├── package.py        builds the downloadable zip (no database, no secrets)
│   ├── routes_ui.py      dashboard, patients, alerts, messages, protocols, settings, /privacy
│   ├── routes_api.py     webhooks (SMS/USSD/WhatsApp/voice), cron, JSON API, CSV export
│   └── messaging/
│       ├── gateway.py    queue → send → cost → simulated reply
│       └── drivers.py    simulator | africastalking | log
├── api/index.py          Vercel serverless entry point (ASGI)
├── vercel.json           Python runtime, routes and cron schedule
├── twa-manifest.json     Play Store (Trusted Web Activity) build config
├── templates/            Jinja2 server-rendered UI (no build step)
├── static/styles.css     hand-written CSS, no framework
├── static/sw.js          service worker: network-first pages, offline fallback
├── static/manifest.webmanifest  PWA manifest (also what Bubblewrap reads)
├── tests/                53 pytest tests (SMS, USSD, WhatsApp, voice, escalation, deploy)
└── data/                 SQLite database + sample ClinicPlus CSV
```

---

## 8. Put it on a phone (PWA) and download it

**Patients install nothing.** They get an ordinary SMS — WhatsApp or a voice call only if they stop
replying. That is the whole point: no app store, no smartphone, no data bundle.

**Clinic staff do get an app.** The dashboard is a Progressive Web App, so it installs on any phone:

* **Android** — open the site in Chrome → ⋮ → **Install app** (or tap the “⬇ Install on this phone”
  button that appears in the menu).
* **iPhone** — open in Safari → Share → **Add to Home Screen**.

Pages you have already opened (alert queue, patient list, dashboard) still load with no connection —
verified: offline reloads served 21 alerts and 53 patients from cache. Walkthrough: **`/install`**.

![Install on a phone](docs/screenshots/install.png)

**Download the source**: **`/download`** (or click below) gives you a zip with no database and no
secrets — unzip, `pip install -r requirements.txt`, `python -m app.cli reset`, and it runs.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.cli reset
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### On the Google Play Store

The same PWA is published as a real Android app through a Trusted Web Activity — a thin native shell
that opens the dashboard full-screen, with no browser bar. Full walkthrough:
**[docs/play-store.md](docs/play-store.md)**.

* `twa-manifest.json` — ready for `bubblewrap init --manifest ./twa-manifest.json` (`rw.uburinzi.health`)
* `/.well-known/assetlinks.json` — served automatically from your Play signing fingerprint
* `/privacy` — the privacy policy Play requires
* `docs/store/*.png` — 1080×1920 phone screenshots for the listing

---

## 9. Going live

Step-by-step app creation: **[docs/create-live-app.md](docs/create-live-app.md)** — create the live
Africa's Talking app, generate the key, add credit, request the `UBURINZI` sender ID, then switch the
platform over with one command:

```bash
python -m app.cli use-live --username YOUR_USERNAME --key atsk_... --test-to 0784852344
python -m app.cli channels      # show live channels, balance and webhook URLs
```

Then: **[docs/live-setup.md](docs/live-setup.md)** (webhooks, WhatsApp, voice) and
**[docs/launch-checklist.md](docs/launch-checklist.md)** (consent and first patients).

### 9c. Deploying to Vercel

**[docs/deploy-vercel.md](docs/deploy-vercel.md)** — the repo is already adapted: `vercel.json`
declares the Python runtime and the cron schedule, `api/index.py` exposes the ASGI app, and
`/api/cron/scheduler` (protected by `CRON_SECRET`) replaces the background thread, which cannot
survive on a serverless platform. Two consequences: use **Postgres** (`DATABASE_URL`), because a
SQLite file would disappear between invocations, and let cron drive the scheduler instead of the
in-process worker — the app detects `VERCEL` and disables the thread by itself.

| Where | Database | Scheduler |
|---|---|---|
| Laptop / VPS | SQLite (default) | background thread |
| **Vercel** | Postgres (required) | Vercel Cron → `/api/cron/scheduler` |

### 9b. Channel reality in Rwanda

### Switch to live Africa's Talking

Everything is done from **Channels (`/channels`)** — paste credentials, pick a driver per channel,
press Test. Env vars are the production-grade alternative (`cp .env.example .env`):

```bash
UBURINZI_SMS_DRIVER=africastalking
UBURINZI_WHATSAPP_DRIVER=at_whatsapp
UBURINZI_VOICE_DRIVER=at_voice
AFRICASTALKING_USERNAME=your-username
AFRICASTALKING_API_KEY=atsk_xxxxxxxx
UBURINZI_SMS_SENDER_ID=UBURINZI
UBURINZI_PUBLIC_BASE_URL=https://uburinzi.example.com
```

Step-by-step setup (sender IDs, voice numbers, WhatsApp templates, ngrok, troubleshooting):
**[`docs/live-setup.md`](docs/live-setup.md)**.
Deployment (PaaS or your own VPS with Caddy + systemd, backups, Postgres, monitoring):
**[`docs/deploy.md`](docs/deploy.md)**.
From demo to real patients (consent, clinical sign-off, first 20 patients, metrics):
**[`docs/launch-checklist.md`](docs/launch-checklist.md)**.

**No account yet?** Press **“Use AT sandbox (free testing)”** on the Channels page: it points all
three channels at the Africa's Talking sandbox. Paste your *sandbox* API key (username is literally
`sandbox`), send test messages to your own number for free, then switch drivers to live when your
sender ID and voice number are approved. **“Back to simulator”** undoes it in one click.

Point Africa's Talking at the webhooks (no code changes):

| Purpose | URL |
|---|---|
| Inbound SMS | `POST /api/webhooks/sms/inbound` |
| SMS delivery report | `POST /api/webhooks/sms/delivery` |
| WhatsApp inbound | `POST /api/webhooks/whatsapp` |
| Voice answer (IVR script) | `POST /api/webhooks/voice/answer` |
| Voice keypress (DTMF) | `POST /api/webhooks/voice/dtmf` |
| Voice events (no-answer, cost) | `POST /api/webhooks/voice/event` |

### Pull patients in from the clinic system

```bash
python -m app.cli export-sample                       # ClinicPlus-shaped CSV template
python -m app.cli import-csv data/patients.csv        # bulk enrolment (consent OFF by default)
```
or push them live from OpenMRS / Bahmni / DHIS2:
```bash
curl -X POST https://YOUR-DOMAIN/api/integrations/patients \
  -H "X-API-Key: $UBURINZI_API_KEY" -H "Content-Type: application/json" \
  -d '{"first_name":"Marie","last_name":"Uwimana","phone":"+250788123456","program":"diabetes"}'
```

### Move to Postgres

```bash
export UBURINZI_DATABASE_URL=postgresql://user:pass@host:5432/uburinzi
```
Plain SQLAlchemy models, no SQLite-specific types — nothing else changes.

### Deploy

Any box that runs Python 3.11+ (Railway, Fly.io, a ₹5 VPS, or the clinic's own server):

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```
Keep `--workers 1` (single scheduler) or run `python -m app.cli run-scheduler` as a separate process
with `UBURINZI_SCHEDULER=false` on the web workers.

---

## 10. Command reference

| Command | What it does |
|---|---|
| `python -m app.cli init-db` | create tables |
| `python -m app.cli seed` | load the demo cohort |
| `python -m app.cli reset` | wipe and reseed |
| `python -m app.cli send-due` | queue + send every due protocol message now |
| `python -m app.cli daily-jobs` | run the daily sweep (missed appointments, risk refresh, metrics) |
| `python -m app.cli run-scheduler` | foreground scheduler loop (production worker) |
| `python -m app.cli import-csv FILE` | bulk patient import |
| `python -m app.cli export-sample` | write `data/sample_clinicplus_export.csv` |
| `python -m app.cli stats` | print the 30-day impact report |
| `python -c "from app.package import build_zip; print(build_zip())"` | build the downloadable zip |
| `python -m pytest tests -q` | run the test suite |

---

## 11. Governance, consent and data protection

* **Consent first.** Imported patients are created with `consent_sms = false`. Nothing is sent until
  consent is captured in the UI, and every change is written to the audit log. Patients can reply
  `STOP` at any time; the platform honours it immediately and confirms.
* **SMS content.** Copy is short, in the patient's own language, identifies the clinic, and never
  discloses a diagnosis to anyone else.
* **Clinical review required.** Cadences and thresholds model Rwanda's NCD and HIV/TB guidelines but
  must be signed off by the clinic's clinical advisor before a real cohort is enrolled.
* **Data minimisation.** Only name, phone, programme, medication and appointment dates are stored —
  no lab values, no full clinical record.
* **Hosting.** Runs entirely on your own infrastructure; SQLite by default, Postgres for scale.

---

## 12. Roadmap

| When | Milestone |
|---|---|
| **Now** | Working MVP: scheduler, SMS loop, alerts, dashboard, impact report (this repo) |
| **Month 1** | 20 real patients enrolled in the pilot clinic, Africa's Talking live, first adherence data |
| **Month 2** | 50 patients, clinical advisor sign-off, Kinyarwanda copy validated by patients, 2-minute demo video |
| **Month 3** | Cohort 2 application with live MVP + real impact data; second clinic onboarded |
| **Later** | WhatsApp + voice, live ClinicPlus/OpenMRS adapters, multi-clinic tenancy, predictive risk model trained on the adherence history, insurance (RSSB/Mutuelle) billing integration |

---

## 13. Why this is Pan-African by design

* **SMS works on every mobile network in every African country** — 2G, no smartphone, no data.
* **Adapter architecture** — any clinic management system connects via CSV or a ~2-day API adapter.
* **Language-agnostic message engine** — adding a language is a dictionary entry, not a rewrite.
* **Configurable protocols** — cadences follow each country's national treatment guidelines.
* **Payer-agnostic business model** — clinic subscription, insurance PMPM, or donor programme funding.

---

Built for clinics anywhere — one deployment, any country, any language.
`Uburinzi` means *protection* in Kinyarwanda — that is exactly what this does for a patient on the
60 days between appointments.

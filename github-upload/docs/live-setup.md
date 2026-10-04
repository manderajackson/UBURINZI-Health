# Going live with Africa's Talking (SMS + WhatsApp + Voice)

Everything below is done from the browser — no code changes. The platform already speaks all three
channels; you are only flipping drivers and pasting credentials.

> **Starting from nothing?** Follow [create-live-app.md](create-live-app.md) first — it walks you
> through creating the live app, generating the key, buying credit and requesting the sender ID.
>
> **Rwanda constraint, read before designing anything:** standard A2P SMS in Rwanda **cannot receive
> replies** (MTN Rwanda and Airtel Rwanda), and Africa's Talking publishes **no Voice product** for
> Rwanda — only SMS (Bulk & Short Code) and USSD. Replies must come over a **short code or USSD**,
> and the voice rung of the escalation ladder degrades to a clinic callback task. Details and sources
> in [create-live-app.md § Part 6](create-live-app.md).

---

## 0. What you need before you start

| Item | Where | Cost |
|---|---|---|
| Africa's Talking account | [account.africastalking.com](https://account.africastalking.com) | free |
| API key | Dashboard → Settings → API key | free |
| SMS sender ID (e.g. `UBURINZI`) | Dashboard → SMS → Sender IDs | free–$10 one-off |
| Voice number | Dashboard → Voice → Numbers | ~$2–5 / month |
| WhatsApp sender + approved template | Dashboard → WhatsApp (request access) | per conversation |
| Airtime/credit top-up | Dashboard → Billing | from ~$10 |
| Public HTTPS URL for webhooks | your server or `ngrok http 8000` | — |

Rwanda notes: alphanumeric sender IDs are supported on MTN and Airtel Rwanda. Buy credit in RWF —
SMS to Rwandan numbers is roughly **27 RWF** per segment.

---

## 1. Get your credentials

1. Log in → **Settings → API Key** → generate a key (starts `atsk_…`).
2. Copy your **username** (shown as “Your username” — *not* your login email). On the live
   environment it is the app username; `sandbox` only works with the sandbox key.
3. **Wait ~3 minutes.** A freshly generated key is not accepted immediately — AT returns
   `The supplied authentication is invalid` until it propagates.

### Sandbox vs live — what actually works

The sandbox app (orange **Go To Sandbox App** button) is free and is where this project is
configured right now. Its behaviour differs from live in three ways that matter:

| | Sandbox | Live |
|---|---|---|
| Username | always literally `sandbox` | your app username |
| API host | `api.sandbox.africastalking.com` | `api.africastalking.com` |
| SMS | accepted to **any** number (`statusCode 101`), never delivered to a real handset | real delivery |
| Voice | simulated | real calls |
| **WhatsApp** | **not supported at all** — AT's SDK states “Sandbox is currently not available for the Whatsapp service” | supported once your number is provisioned |
| Credit | free test units (top up free, any amount) | real money |

So in sandbox: SMS looks real end-to-end (balance drops, message IDs come back), but the phone never
rings and WhatsApp must stay on the simulator driver until you have a live app.

### Troubleshooting: `The supplied authentication is invalid`

That error has **three** different causes, and only one of them is a wrong key:

1. **Key not propagated yet** — wait 3 minutes after generating it.
2. **Wrong username for the key** — a sandbox key needs `sandbox`; a live key needs the app username.
   A key from one app never works on another.
3. **Rate limiting** — AT throttles bursts and answers a throttled call with the *same* 401 message.
   `app/messaging/drivers.py::_post` retries a 401 twice (4 s, then 8 s) so a scheduled batch of
   check-ins is not lost; a genuinely bad key simply fails after the last attempt.

## 2. Configure SMS

1. **SMS → Sender IDs** → request `UBURINZI` (approval can take a day; you can send with the
   default `AFRICASTKNG` meanwhile).
2. **SMS → Callback URLs** → set:
   * Incoming messages: `https://YOUR-DOMAIN/api/webhooks/sms/inbound`
   * Delivery reports: `https://YOUR-DOMAIN/api/webhooks/sms/delivery`

## 3. Configure Voice

1. **Voice → Numbers** → get a number (this is the caller ID patients see).
2. **Voice → Callback URL** → `https://YOUR-DOMAIN/api/webhooks/voice/answer`
   (this is the URL AT fetches the moment the patient picks up — it must be public).
3. Kinyarwanda text-to-speech is **not** available from AT's TTS. Record a ~10-second greeting with
   a Kinyarwanda speaker, host the MP3 anywhere public, and paste the URL into
   **Channels → Recorded prompt URL**. The IVR then plays your recording and falls back to
   English/French/Swahili TTS only if no URL is set.

## 3b. Configure USSD (the reply path in Rwanda)

Rwanda cannot receive replies to an A2P SMS, so USSD carries the patient's answer.

1. **Requests → USSD** → ask AT for a code (shared `*384*XXXX#` codes are free to set up).
2. Set the channel's callback URL to `https://YOUR-DOMAIN/api/webhooks/ussd`.
3. **Channels → How patients answer** → set **Reply channel = USSD** and paste the code.
4. Check-in messages then end with the dial instruction instead of "Reply 1=Yes, 2=No".

The menu is served in the patient's language (rw/en/fr/sw); a `3` (not well) opens a red alert on the
nurse queue immediately, and no acknowledgement SMS is sent, so one check-in costs one USSD session
only.

## 4. Configure WhatsApp

1. Request WhatsApp access on the AT dashboard and get a provisioned `waNumber`.
2. Create a **UTILITY** template named `uburinzi_checkin` with two body variables, e.g.
   `Hello {{1}}, this is {{2}} checking on your medication. Reply 1=yes, 2=no, 3=unwell.`
3. Set the webhook: `https://YOUR-DOMAIN/api/webhooks/whatsapp`
   (Meta-style verification is supported: the verify token is `uburinzi-verify` by default and can be
   changed on the Channels page).
4. Session rule: free-form WhatsApp messages are only allowed within **24 hours of the patient's
   last reply**. Outside that window Uburinzi automatically falls back to the approved template —
   which is why the template name is a setting.

## 5. Paste the credentials into Uburinzi

**Channels page (`/channels`)** → fill Username, API key, Sender ID, Voice number, WhatsApp number →
**Save credentials**. The key is encrypted before it is written to the database.

Or, preferably for production, put them in `.env` and restart — then nothing is stored in the DB:

```bash
UBURINZI_SMS_DRIVER=africastalking
UBURINZI_WHATSAPP_DRIVER=at_whatsapp
UBURINZI_VOICE_DRIVER=at_voice
AFRICASTALKING_USERNAME=your-username
AFRICASTALKING_API_KEY=atsk_xxxxxxxx
UBURINZI_SMS_SENDER_ID=UBURINZI
UBURINZI_PUBLIC_BASE_URL=https://uburinzi.example.com
```

## 6. Flip the drivers

**Channels → Channel routing**: pick *Africa's Talking (live)* per channel and save.
You can go live on SMS while WhatsApp and voice stay in the simulator — they are independent.

## 7. Prove it

On the Channels page:

| Button | What it does |
|---|---|
| **Check balance** | Calls `GET /version1/user` — confirms the key works before you send anything |
| **Test SMS / Test WhatsApp / Test call** | Sends a real message (or places a real call) to the number you type |
| **Run escalation now** | Runs the SMS → WhatsApp → voice ladder immediately |

Then watch **Channels → Recent calls** for call status (`ringing`, `completed`, `no-answer`) and the
key the patient pressed, and **Messages** for delivery status and cost per message.

## 8. Local testing with ngrok

```bash
ngrok http 8000                      # copy the https URL it prints
# Channels page → Public base URL → https://abc123.ngrok-free.app
```
All six webhook URLs shown on the Channels page update to use it. Paste them into AT.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `HTTP 401` / `ApiKey is invalid` | Key and username from different environments | Regenerate both in the *live* dashboard |
| SMS sent but arrives as `AFRICASTKNG` | Sender ID not approved yet | Wait for approval or leave the field blank |
| Voice callback never fires | URL not publicly reachable | Use ngrok; check **Voice → Callback URL** |
| IVR speaks English in a Kinyarwanda cohort | No TTS for `rw` | Add a recorded prompt URL on the Channels page |
| WhatsApp rejected outside 24 h | Session window closed | Approve the `uburinzi_checkin` template (the app uses it automatically) |
| Calls fail with “insufficient balance” | Credit too low | Top up; calls bill per minute |
| Duplicate messages | Webhook retried by AT | Inbound is idempotent on `provider_id`; outbound is idempotent on the dedupe key |

## Cost planning

| Channel | Unit | Indicative cost |
|---|---|---|
| SMS | per segment (160 chars) | ~27 RWF |
| WhatsApp | per message / conversation | ~12 RWF |
| Voice | per minute | ~60 RWF |

For one patient on the diabetes protocol (2 check-ins/week + 1 tip/fortnight + 1 appointment
reminder/month) that is roughly **230–300 RWF per patient per month** — under $0.25.
The dashboard shows the live figure for your cohort under *SMS sent* / *cost per patient*.

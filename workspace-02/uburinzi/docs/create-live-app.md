# Creating the live "Uburinzi" app on Africa's Talking

Do these steps in your browser; when you get to **Part 5** the switchover is one command.

---

## Why we need a live app at all

On the sandbox app, Africa's Talking **accepts and bills** messages but never hands them to a mobile
network — we proved this: four messages to `+250733087430` / `+250784852344` came back with real
message IDs (`ATXid_5a7126fe…`) and your phone stayed silent. Only a **live** app delivers.

---

## Part 1 — Create the app (~5 minutes)

1. Log in at [account.africastalking.com](https://account.africastalking.com).
2. Leave the orange **Sandbox** app and switch to **Live** (app switcher, top-left).
3. Create a **Team** — call it `Uburinzi` — or use the default one.
4. Inside the team, **Create App**:
   * **Name:** `Uburinzi`
   * **Country:** Rwanda
   * **Currency:** RWF
5. Open the app and copy the **username** AT shows for it. This is the value I need — it is *not*
   your login email, and it is not `sandbox`.

## Part 2 — Generate the API key (~1 minute + 3 minutes' wait)

> **Does regenerating a key break anything?** No. A key is only a credential — nothing in Uburinzi
> changes when you generate a new one: patients, message history, protocols, alerts and settings are
> untouched, because they live in the database, not on Africa's Talking. The old key simply stops
> working, and we point the app at the new one with the Part 5 command. Regenerating is also good
> hygiene if a key has ever been pasted somewhere public (a chat, a screenshot).

1. In the app: **Settings → API Key**.
2. Enter your account password → **Generate** → copy the `atsk_…` key.
3. **Wait 3 minutes** before testing it — AT rejects a brand-new key until it propagates.

## Part 3 — Add credit

**Billing → Top up.** SMS to Rwanda costs **12 RWF** per segment — measured, not guessed (our first live send moved the
wallet from RWF 113.7351 to RWF 101.7351). Start with **5,000 RWF** ≈ 415 messages: a full pilot week.

| Volume | Cost |
|---|---|
| 1 patient, 1 month (≈17 check-ins) | ~205 RWF |
| 20 patients, 1 month | ~4,100 RWF (~$3) |
| 52 patients, 1 month (≈880 messages) | ~10,600 RWF (~$8) |

## Part 4 — Request the sender ID

**SMS → Sender IDs → request `UBURINZI`.**

Rwanda has real rules here, and they favour us:

* Alphanumeric sender IDs **must be pre-registered** with the operators — allow about **3 weeks** [5](https://www.twilio.com/en-us/guidelines/rw/sms).
* **MTN Rwanda only accepts pre-registered alphanumeric IDs**; dynamic/generic IDs (`INFO`,
  `Verify`, `Notify`, `InfoSMS`) get blocked [5](https://www.twilio.com/en-us/guidelines/rw/sms).
* **Numeric international sender IDs fail on MTN and get altered on Airtel** — so always send with
  an alphanumeric ID [5](https://www.twilio.com/en-us/guidelines/rw/sms).
* Promotional content cannot be registered — ours is clinical follow-up, which is the right category.

Until `UBURINZI` is approved, leave the sender ID blank and AT sends as its default. Patients
still get the message; only the "from" label differs.

## Part 5 — Switch the platform over

**Option A — keep the key out of chat (recommended).** Open `~/uburinzi/.env`, put the key after the
`=` on the `AFRICASTALKING_API_KEY=` line (no quotes, no spaces), save, then run:

```bash
python -m app.cli use-live --from-env --test-to 0784852344
```

**Option B — pass it on the command line:**

```bash
python -m app.cli use-live \
  --username Uburinzi \
  --key atsk_your_key_here \
  --test-to 0784852344
```

Either way, add `--sender-id UBURINZI` later once the sender ID is approved.

That command: writes the credentials to `.env` (git-ignored, never zipped), stores them **encrypted**
in the database, flips **SMS → live**, leaves **WhatsApp and voice on the simulator** (as you asked —
voice and chats come later), checks the balance, sends a verification SMS to your number, and prints
the webhook URLs. If it prints a balance, you are live.

Check the current state any time with `python -m app.cli channels`.

## Part 6 — ⚠️ Read this before enrolling real patients

**Rwanda does not support inbound replies on standard A2P SMS.** Twilio's country guidelines list
"Two-way SMS supported: **No**", and the 2026 compliance surveys say it plainly: standard A2P SMS
cannot receive replies on MTN Rwanda and Airtel Rwanda, and this is a carrier-level restriction, not
a quirk of one provider [1](https://www.telerivet.com/blog/sms-compliance-by-country-global-guide)
[5](https://www.twilio.com/en-us/guidelines/rw/sms).

Our whole product is a **reply loop** (`1=Yes / 2=No / 3=Not well`). So the response channel has to be
chosen deliberately. Africa's Talking's own country list says Rwanda offers **SMS (Bulk & Short
Code), USSD** [1](https://help.africastalking.com/en/articles/2727792-which-countries-are-africa-s-talking-products-in)
— and AT's Two-Way SMS product runs on short codes (5-digit, dedicated or shared with a keyword)
[4](https://africastalking.com/sms/twowaysms):

| Reply channel | Works on a 2G phone | Two-way | AT in Rwanda | Verdict |
|---|---|---|---|---|
| **AT short code** (dedicated, or shared + keyword) | ✅ | ✅ | ✅ offered | **The real fix.** Patients reply to the number that messaged them |
| **USSD** (`*XXX#` menu) | ✅ | ✅ | ✅ offered | Excellent 2G fallback: the SMS says "dial `*123#` to answer" |
| **WhatsApp** | ❌ needs data | ✅ | not in AT's Rwanda list | Smartphone patients only, later |
| **Voice IVR (DTMF)** | ✅ | ✅ | ❌ **not offered in Rwanda** | Our ladder now raises a callback task instead |
| **Staff phone call** | ✅ | ✅ | — | Fallback, now generated automatically |

What I have already changed in the code for this:

* The escalation ladder checks whether voice is actually available. If it is not, it **raises a red
  "please phone this patient" task** on the nurse queue instead of failing silently — because AT
  publishes no Voice product for Rwanda. (`voice_enabled` on the Channels page; new `callback_tasks`
  counter in the escalation result; covered by a test.)
* Inbound replies arrive at `/api/webhooks/sms/inbound` whatever their source, so a short code needs
  no new plumbing — it just posts to the same URL.

**My recommendation:** request a **USSD code** first (fastest to provision, works on every phone and
costs the patient nothing), add a **short code** if you want plain replies later, and keep WhatsApp
for smartphone patients.

**USSD is already built.** The platform ships a working USSD channel:

* Webhook **`POST /api/webhooks/ussd`** — AT posts `sessionId`, `serviceCode`, `phoneNumber`, `text`;
  we answer `CON …` / `END …`. Verified against a live session:

  ```
  CON Muraho Rosette. Hitamo:
  1=Nafashe imiti
  2=Sinfashe imiti
  3=Sindashize neza

  → "1"  END Murakoze! Twanditse ko wafashe imiti yawe.
  → "3"  END Murakoze. Umuforomo wawe arabimenyeshwa vuba.
         + RED alert: "Rosette Mutoni reported not feeling well by USSD. Call back today."
  ```

* Menus and confirmations in **Kinyarwanda, English, French and Swahili**, chosen from the patient's
  own language record.
* Answers flow into the same reply tracker as SMS: adherence, streaks, risk score and alerts all
  update exactly as if an SMS had arrived (recorded with `channel = ussd`).
* **Check-in messages rewrite themselves.** With USSD selected, the dead-end
  *"Subiza: 1=Yego, 2=Oya…"* tail is replaced by the dial instruction, in the patient's language,
  always inside one SMS segment:

  ```
  Muraho Rosette, ni Ivuriro binyuze kuri Uburinzi Health. Ese wafashe imiti ya
  diyabete yawe uyu munsi? Subiza ukanda *384*96# hanyuma uhitemo 1, 2 cyangwa 3.   (157 chars)
  ```

* No acknowledgement SMS is sent after a USSD answer — the closing screen *is* the confirmation, so
  you never pay twice for one check-in.

To switch it on: **Channels → How patients answer → Reply channel = USSD**, paste the code AT gives
you (e.g. `384*96#`), and save. Nothing else changes.

## Part 7 — Webhooks (needs a public HTTPS URL)

For now, set the two that matter:

| Purpose | URL |
|---|---|
| **USSD callback** (the reply path) | `https://YOUR-DOMAIN/api/webhooks/ussd` |
| Incoming messages (short code replies) | `https://YOUR-DOMAIN/api/webhooks/sms/inbound` |
| Delivery reports | `https://YOUR-DOMAIN/api/webhooks/sms/delivery` |

Ask AT to provision a USSD code (Dashboard → **Requests** → USSD channel; shared codes are free to
set up and billed per session), then paste the callback above into the channel's settings.

For a test URL in two minutes: `ngrok http 8000`, then paste the https address it prints into
Settings → `public_base_url` (the app then prints ready-made URLs). For real use, follow
`docs/deploy.md`.

## Part 8 — Verify before a single real patient

- [ ] `python -m app.cli channels` shows a balance and `sms → africastalking (live)`
- [ ] A test SMS physically arrives on **0784852344** and **0733087430**
- [ ] Delivery reports appear in **Messages** (green ticks)
- [ ] A reply from the short code shows up in **Messages** and updates the patient's status
- [ ] **Alerts** shows a callback task, not a failed call, for a silent red patient

## Part 9 — Compliance in Rwanda

Health messages are sensitive, so before the first real patient:

* **Explicit, documented consent per patient.** Rwanda requires opt-in consent with records of when
  and how it was given [3](https://www.sent.dm/resources/rw-sms-guidance). Uburinzi stores
  `consent_sms` per patient and never messages anyone without it.
* **`STOP` / `HELP` must work, in English *and* Kinyarwanda**, and opt-outs must be honoured within
  24 hours [3](https://www.sent.dm/resources/rw-sms-guidance). Rwanda has no central Do-Not-Call
  registry, so the suppression list is ours to keep.
* **Sending hours 08:00–18:00** — already enforced in the app, and matches local guidance to respect
  daytime hours [3](https://www.sent.dm/resources/rw-sms-guidance).
* **Rwanda's data protection law** applies to patient data held here. I am not a lawyer — get local
  sign-off on the consent script in `docs/launch-checklist.md` before go-live.

---

## Summary of what I need from you

1. The **username** AT shows for your live `Uburinzi` app.
2. The **`atsk_…` key** generated on that app.
3. A decision on the reply channel: **short code** (recommended), **USSD**, or both.

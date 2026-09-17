# Launch checklist: demo → real patients

Work through this in order. Nothing here is optional before the first real patient receives a message.

## Phase 0 — Before the first real SMS

- [ ] **Clinical sign-off.** A clinician at the clinic reviews `app/protocols.py` (cadences, thresholds)
      and every Kinyarwanda message. Record the review date and the reviewer's name.
- [ ] **Consent script** agreed and printed (see below).
- [ ] **Data minimisation confirmed**: name, phone, programme, medication, appointment dates only.
- [ ] **Hosting decided**: who owns the server, who has access, where the backups live.
- [ ] Default password changed; every staff member has their own login (`/settings` → Users).

### Consent script (read aloud, tick the box after they agree)

> “We would like to send you a free text message to remind you about your medicine and your
> appointment. The message will never say what your illness is. You can reply STOP at any time and we
> will stop. Is that alright?”

Tick **Patient consented** on the patient's record *after* they say yes. Imported patients always
start with consent **off** and receive nothing until you switch it on.

## Phase 1 — Technical readiness (live channels)

- [ ] Deployed with HTTPS (`docs/deploy.md`)
- [ ] Africa's Talking credentials saved and **Check balance** succeeds
- [ ] Test SMS / WhatsApp / call received on a staff phone
- [ ] Voice prompt recorded in Kinyarwanda and its URL set (AT has no `rw` text-to-speech)
- [ ] Sending window and daily cap configured
- [ ] `UBURINZI_AUTO_SEED=false` — the demo cohort must never be confused with real patients

## Phase 2 — First 20 patients (Month 1)

- [ ] Export 20–30 chronic patients from ClinicPlus (diabetes / hypertension / HIV / TB)
- [ ] Import them via `/import` (consent starts OFF)
- [ ] Capture consent for each patient, tick the box, send the welcome SMS
- [ ] Confirm each patient received the welcome message (call two of them and ask)
- [ ] Baseline: record the cohort's adherence *before* Uburinzi if you have historical data
- [ ] Daily: open `/alerts`, clear the red queue
- [ ] Weekly: export `/api/export/messages.csv` and note failed numbers (wrong or switched-off phones)

## Phase 3 — Prove it (Month 2)

- [ ] Scale to 50 patients
- [ ] 4 weeks of data → `/api/impact-report` gives adherence, response rate, no-show rate, cost/patient
- [ ] Compare against your pre-Uburinzi baseline — this is the number investors will ask for
- [ ] Ask 10 patients what they think of the messages; adjust the copy in `/protocols`
- [ ] Record the 2-minute demo video (`docs/demo-script.md`)
- [ ] Second clinic identified for onboarding

## Phase 4 — Apply (Month 3)

- [ ] Cohort 2 application submitted with live numbers and the demo video
- [ ] Co-founder or advisory team in place (`docs/team.md`)
- [ ] One-page impact summary generated from `/api/impact-report`
- [ ] Reference clinician willing to take a call from the selection committee

## Routine once live

| When | Task |
|---|---|
| Every morning | Open `/alerts`, clear red → call those patients |
| Every Monday | Check failed messages, fix phone numbers |
| Every month | Export the impact report; review cost per patient |
| Every quarter | Re-run clinical review of protocols and message copy |

## Things that will go wrong (and the fix)

| Problem | Fix |
|---|---|
| Patient says they never got the message | Check `/messages` status; confirm the number is correct and the handset is on |
| Wrong person answers | Verify the phone at enrolment; add the patient's preferred contact name |
| Patient replies STOP by accident | Switch consent back on after a verbal confirmation, log why |
| Nurse ignores alerts | Keep the queue honest: resolve only after the call is made |
| Costs creeping up | Lower the daily cap, lengthen cadences, or move stable patients to weekly check-ins |

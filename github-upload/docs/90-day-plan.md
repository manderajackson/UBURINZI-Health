# 90-day MVP sprint

How the plan maps onto the code in this repository. Check items off as you complete them.

## Month 1 — Build the core SMS engine

- [x] **Patient database** — `app/models.py` (`Patient`, `Enrollment`, `Clinic`)
- [x] **SMS engine** — `app/engine.py` scheduler + `app/messaging/drivers.py`
- [x] **Message templates (Kinyarwanda + English)** — `app/protocols.py`
- [x] **Response tracker** — `POST /api/webhooks/sms/inbound`, `parse_reply()`
- [x] **Channel layer** — SMS + WhatsApp + Voice drivers, per-channel routing, `/channels` page
- [x] **Escalation ladder** — SMS → WhatsApp (24 h) → voice call (48 h), with caps and quiet hours
- [ ] **Wire Africa's Talking** — credentials on `/channels`, then Test SMS / WhatsApp / call
      (walkthrough: `docs/live-setup.md`)
- [ ] **Record the Kinyarwanda voice prompt** — AT has no `rw` TTS; host an MP3 and set its URL
- [ ] **Enrol 20 real patients** from the pilot clinic (consent first!)
- [ ] **Clinical advisor sign-off** on cadences and Kinyarwanda copy

## Month 2 — Intelligence and dashboard

- [x] **Alert engine** — `evaluate_patient()` with 5 auditable rules
- [x] **Clinic dashboard** — `/`, `/patients`, `/alerts`, `/messages`
- [x] **Impact metrics** — `app/metrics.py`, `/api/impact-report`
- [x] **Scale to 50 patients** — cohort size is a config value (`UBURINZI_SEED_PATIENTS` for demos)
- [ ] **Collect real baseline data** — 4 weeks of adherence before/after comparison
- [ ] **Recruit co-founder or advisors** (see `docs/team.md`)

## Month 3 — Prove results and apply

- [x] **Exportable impact data** — CSV + JSON endpoints
- [ ] **Record the 2-minute demo video** — script in `docs/demo-script.md`
- [ ] **Write the application narrative** using `/api/impact-report` numbers
- [ ] **Submit Cohort 2 application** (~Oct–Nov 2026 window)
- [ ] **Prepare for interview** — rehearse the "why you" section

## Evidence pack to attach to the application

1. `GET /api/impact-report` — adherence, response rate, no-show rate, cost per patient
2. `/api/export/patients.csv` + `/api/export/messages.csv` — raw evidence (anonymise MRNs first)
3. Screenshots of Dashboard, Alerts and a patient thread
4. This repository (public or a read-only link) — shows the MVP is real, not a slide
5. `docs/demo-script.md` — the 2-minute video, recorded

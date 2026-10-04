"""Demo/pilot seed data.

Everything here is synthetic — no real patient data. It exists so the platform
can be demonstrated end-to-end (charts, alerts, impact report) before a single
real patient is enrolled. Run `python -m app.cli reset` to wipe and reseed.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import SEED_HISTORY_DAYS, SEED_PATIENTS, SMS_COST_RWF
from app.models import (
    Appointment,
    Clinic,
    CohortMetric,
    Enrollment,
    InboundMessage,
    MessageKind,
    MessageStatus,
    OutboundMessage,
    Patient,
    Setting,
    User,
)
from app.protocols import EDUCATION, PROGRAMS, PROGRAM_KEYS, seed_templates
from app.security import hash_password
from app.timeutils import now

FIRST_NAMES = [
    "Alice", "Jean", "Marie", "Eric", "Grace", "Patrick", "Claudine", "Emmanuel", "Josiane", "Olivier",
    "Aline", "Theogene", "Beatha", "Innocent", "Chantal", "Fabrice", "Solange", "Dieudonne", "Ange", "Yvonne",
    "Maurice", "Sandrine", "Bosco", "Clarisse", "Habimana", "Denise", "Samuel", "Francine", "Vincent", "Esperance",
    "Laurent", "Diane", "Gilbert", "Immaculee", "Prosper", "Bernadette", "Pascal", "Rosette", "Nadine", "Sylvestre",
    "Lea", "Janvier", "Mediatrice", "Faustin", "Carine", "Alexis", "Mukamana", "Nyirahabimana", "Uwimana", "Byiringiro",
]
LAST_NAMES = [
    "Nkurunziza", "Uwimana", "Mukamana", "Byiringiro", "Niyonzima", "Habimana", "Nsengimana", "Twagirayezu",
    "Kamanzi", "Mutoni", "Ndayisaba", "Rukundo", "Bagirishya", "Sibomana", "Nzeyimana", "Iradukunda",
    "Mugisha", "Uwineza", "Ndahiro", "Karangwa", "Mukandayisenga", "Tuyishime", "Nshimiyimana", "Gasore",
    "Mukeshimana", "Hakizimana", "Ntakirutimana", "Bizimana", "Niyibizi", "Dusabe",
]
VILLAGES = ["Gatenga", "Kagarama", "Niboye", "Kicukiro", "Gikondo", "Kanombe", "Nyarugunga", "Masaka", "Rwampara", "Gahanga"]

PROGRAM_WEIGHTS = ["diabetes", "diabetes", "hypertension", "hypertension", "hypertension", "hiv", "hiv", "tb", "anc"]
LANGUAGE_WEIGHTS = ["rw", "rw", "rw", "rw", "rw", "rw", "en", "fr", "sw"]


def _phone(rng: random.Random, i: int) -> str:
    prefix = rng.choice(["78", "79", "72", "73"])
    return f"+250{prefix}{rng.randint(1000000, 9999999)}"


def seed_clinic(session) -> Clinic:
    clinic = session.execute(select(Clinic).limit(1)).scalar_one_or_none()
    if clinic is None:
        clinic = Clinic(
            name="Uburinzi Pilot Clinic",
            district="Kicukiro",
            country="Rwanda",
            phone="+250788123456",
        )
        session.add(clinic)
        session.flush()
    return clinic


def seed_users(session, clinic: Clinic) -> None:
    if session.execute(select(User).limit(1)).scalar_one_or_none():
        return
    users = [
        User(
            clinic_id=clinic.id,
            name="Mandera Jackson",
            email="manderajackson99@gmail.com",
            password_hash=hash_password("uburinzi2026"),
            role="admin",
        ),
        User(
            clinic_id=clinic.id,
            name="UWASE Aline",
            email="yahshuamediasite@gmail.com",
            password_hash=hash_password("uburinzi2026"),
            role="clinician",
        ),
    ]
    session.add_all(users)


def seed_settings(session) -> None:
    defaults = {
        "clinic_escalation_phone": "+250788123456",
        "nurse_in_charge": "UWASE Aline",
        "pilot_start": "2026-06-01",
        "review_cadence": "weekly",
        "consent_script": "Do you agree to receive free SMS reminders about your medication and appointments?",
    }
    existing = {s.key for s in session.execute(select(Setting)).scalars().all()}
    for key, value in defaults.items():
        if key not in existing:
            session.add(Setting(key=key, value=value))


def seed_patients(session, clinic: Clinic, count: int = SEED_PATIENTS, days: int = SEED_HISTORY_DAYS) -> None:
    if session.execute(select(Patient).limit(1)).scalar_one_or_none():
        return

    rng = random.Random(20260916)
    today = now()
    start = today - timedelta(days=days)

    daily_totals: dict = {}
    metrics: dict[tuple, CohortMetric] = {}

    def metric_row(day, program):
        key = (day, program)
        if key not in metrics:
            row = CohortMetric(
                day=day,
                program=program,
                active_patients=0,
                checkins_sent=0,
                replies=0,
                yes=0,
                no=0,
                unwell=0,
            )
            session.add(row)
            metrics[key] = row
        return metrics[key]

    for i in range(count):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        language = rng.choice(LANGUAGE_WEIGHTS)
        program = rng.choice(PROGRAM_WEIGHTS)
        enrolled_days_ago = rng.randint(int(days * 0.35), days - 2)
        enrolled_at = today - timedelta(days=enrolled_days_ago)

        base_adherence = min(0.97, max(0.35, rng.gauss(0.58, 0.13)))
        reply_rate = min(1.0, max(0.55, rng.gauss(0.88, 0.08)))

        patient = Patient(
            clinic_id=clinic.id,
            mrn=f"UB-{2026}-{i+1:04d}",
            first_name=first,
            last_name=last,
            phone=_phone(rng, i),
            language=language,
            sex=rng.choice(["female", "male", "female", "male", "unknown"]),
            birth_year=rng.randint(1948, 2005),
            village=rng.choice(VILLAGES),
            consent_sms=True,
            active=True,
            enrolled_at=enrolled_at,
            sim_adherence=round(min(0.97, base_adherence + 0.22), 2),
            sim_reply_rate=round(reply_rate, 2),
        )
        session.add(patient)
        session.flush()

        spec = PROGRAMS[program]
        enr = Enrollment(
            patient_id=patient.id,
            program=program,
            medication=spec["default_medication"],
            started_at=enrolled_at,
            active=True,
        )
        session.add(enr)
        session.flush()

        # a second condition for ~18% of patients
        if rng.random() < 0.18:
            other = rng.choice([p for p in PROGRAM_KEYS if p != program])
            session.add(
                Enrollment(
                    patient_id=patient.id,
                    program=other,
                    medication=PROGRAMS[other]["default_medication"],
                    started_at=enrolled_at + timedelta(days=7),
                    active=True,
                )
            )
            session.flush()

        # ---------------------------------------------------------- history loop
        day = enrolled_at.date()
        doses_taken = doses_missed = 0
        checkin_no = 0
        while day <= today.date():
            days_in = (day - enrolled_at.date()).days
            progress = min(1.0, days_in / max(days, 1))
            adherence_today = min(0.98, base_adherence + 0.24 * progress)

            if days_in % spec["cadence_days"] == 0 and days_in > 0:
                checkin_no += 1
                sent_at = datetime(day.year, day.month, day.day, rng.randint(9, 16), rng.randint(0, 59))
                if sent_at > today:
                    day += timedelta(days=1)
                    continue
                body = _checkin_body(session, patient.language, program, first, clinic)
                msg = OutboundMessage(
                    patient_id=patient.id,
                    enrollment_id=enr.id,
                    clinic_id=clinic.id,
                    phone=patient.phone,
                    body=body,
                    language=language,
                    program=program,
                    kind=MessageKind.CHECKIN.value,
                    status=MessageStatus.DELIVERED.value,
                    provider="simulator" if True else "simulator",
                    provider_id=f"SEED-{patient.id}-{checkin_no}",
                    cost_rwf=SMS_COST_RWF,
                    created_at=sent_at,
                    scheduled_at=sent_at,
                    sent_at=sent_at,
                    delivered_at=sent_at + timedelta(seconds=12),
                    dedupe_key=f"seed:checkin:{enr.id}:{day.isoformat()}",
                )
                session.add(msg)
                session.flush()
                enr.last_checkin_at = sent_at
                daily_totals[day] = daily_totals.get(day, 0) + 1

                m_all = metric_row(day, "all")
                m_all.checkins_sent += 1
                m_prog = metric_row(day, program)
                m_prog.checkins_sent += 1

                if rng.random() < reply_rate:
                    roll = rng.random()
                    if roll < adherence_today:
                        choice = "yes"
                        doses_taken += 1
                        patient.missed_streak = 0
                    elif roll < adherence_today + (1 - adherence_today) * 0.85:
                        choice = "no"
                        doses_missed += 1
                        patient.missed_streak = (patient.missed_streak or 0) + 1
                    else:
                        choice = "unwell"
                        doses_missed += 1
                        patient.missed_streak = (patient.missed_streak or 0) + 1
                    session.add(
                        InboundMessage(
                            patient_id=patient.id,
                            phone=patient.phone,
                            body={"yes": "1", "no": "2", "unwell": "3"}[choice],
                            received_at=sent_at + timedelta(minutes=rng.randint(4, 300)),
                            choice=choice,
                            provider_id=f"SEEDREPLY-{patient.id}-{checkin_no}",
                            simulated=True,
                        )
                    )
                    patient.last_contact_at = sent_at + timedelta(hours=2)
                    m_all.replies += 1
                    setattr(m_all, choice, getattr(m_all, choice) + 1)
                    m_prog.replies += 1
                else:
                    patient.no_reply_streak = (patient.no_reply_streak or 0) + 1

            # education tips
            if days_in > 0 and days_in % spec["education_every_days"] == 0:
                tips = EDUCATION.get(program, {}).get(language) or EDUCATION.get(program, {}).get("en", [])
                if tips:
                    sent_at = datetime(day.year, day.month, day.day, 10, rng.randint(0, 59))
                    if sent_at <= today:
                        session.add(
                            OutboundMessage(
                                patient_id=patient.id,
                                enrollment_id=enr.id,
                                clinic_id=clinic.id,
                                phone=patient.phone,
                                body=tips[(days_in // spec["education_every_days"]) % len(tips)],
                                language=language,
                                program=program,
                                kind=MessageKind.EDUCATION.value,
                                status=MessageStatus.DELIVERED.value,
                                provider="simulator",
                                provider_id=f"SEED-EDU-{patient.id}-{days_in}",
                                cost_rwf=SMS_COST_RWF,
                                created_at=sent_at,
                                scheduled_at=sent_at,
                                sent_at=sent_at,
                                delivered_at=sent_at,
                                dedupe_key=f"seed:edu:{enr.id}:{day.isoformat()}",
                            )
                        )
                        enr.last_education_at = sent_at

            day += timedelta(days=1)

        enr.education_index = max(1, (enrolled_days_ago // spec["education_every_days"]) % 4)
        session.add(enr)

        # ---------------------------------------------------------- appointments
        appt_offsets = [-60, -30, -7, 14, 28, 45]
        for idx, offset in enumerate(appt_offsets):
            due = today + timedelta(days=offset)
            if due < enrolled_at:
                continue
            if offset < 0:
                status = "missed" if (doses_missed > doses_taken and idx % 2 == 0) else "completed"
            else:
                status = "upcoming"
            session.add(
                Appointment(
                    patient_id=patient.id,
                    due_at=due,
                    reason="Routine follow-up" if idx % 2 else "Refill & review",
                    status=status,
                    confirmed=(status == "completed") or (status == "upcoming" and rng.random() < 0.25),
                )
            )

        session.add(patient)

    session.commit()

    # fill active_patients per day (patients enrolled on or before that day)
    enrolled_dates = [
        value.date() for value in session.execute(select(Patient.enrolled_at)).scalars().all()
    ]
    for (day, _program), row in metrics.items():
        row.active_patients = sum(1 for d in enrolled_dates if d <= day)
    session.commit()


def _checkin_body(session, language: str, program: str, first_name: str, clinic: Clinic) -> str:
    from app.messaging.render import render_template

    return render_template(
        session,
        program,
        "checkin",
        language,
        ctx={
            "first_name": first_name,
            "clinic": clinic.name,
            "phone": clinic.phone,
            "condition": PROGRAMS[program]["label"],
            "medication": PROGRAMS[program]["default_medication"],
        },
    )


def seed_all(session, patients: int = SEED_PATIENTS, days: int = SEED_HISTORY_DAYS) -> dict:
    seed_templates(session)
    clinic = seed_clinic(session)
    seed_users(session, clinic)
    seed_settings(session)
    session.commit()
    seed_patients(session, clinic, patients, days)
    return {"patients": patients, "history_days": days}

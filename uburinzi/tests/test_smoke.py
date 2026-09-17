"""Smoke tests for the Uburinzi engine.

Run with:  python -m pytest tests -q
These cover the loop that matters: schedule → send → reply → risk → alert.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import DBSession, init_db
from app.engine import (
    build_due_messages,
    evaluate_patient,
    normalize_phone,
    parse_reply,
    process_inbound,
    run_daily_jobs,
    run_scheduler,
)
from app.metrics import adherence_stats
from app.models import (
    Appointment,
    Clinic,
    Enrollment,
    InboundMessage,
    MessageKind,
    OutboundMessage,
    Patient,
    ReplyChoice,
    User,
)
from app.protocols import PROGRAMS
from app.security import hash_password
from app.timeutils import now


@pytest.fixture(autouse=True)
def fresh_db():
    from app.protocols import seed_templates

    init_db()
    with DBSession() as db:
        seed_templates(db)
        db.commit()
    with DBSession() as db:
        db.query(InboundMessage).delete()
        db.query(OutboundMessage).delete()
        db.query(Appointment).delete()
        db.query(Enrollment).delete()
        db.query(Patient).delete()
        db.query(Clinic).delete()
        db.query(User).delete()
    yield


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def make_patient(db, first_name="Marie", program="diabetes", phone="+250788000001", started_days_ago=5, **kwargs):
    clinic = db.query(Clinic).first()
    if clinic is None:
        clinic = Clinic(name="Test Clinic", phone="+250788000000")
        db.add(clinic)
        db.flush()
    patient = Patient(
        clinic_id=clinic.id,
        mrn=f"T-{phone[-4:]}",
        first_name=first_name,
        last_name="Uwimana",
        phone=phone,
        language="rw",
        consent_sms=True,
        active=True,
        **kwargs,
    )
    db.add(patient)
    db.flush()
    from datetime import timedelta as _td

    db.add(
        Enrollment(
            patient_id=patient.id,
            program=program,
            medication=PROGRAMS[program]["default_medication"],
            active=True,
            started_at=now() - _td(days=started_days_ago),
        )
    )
    db.commit()
    return patient


# ------------------------------------------------------------------- parsing
@pytest.mark.parametrize(
    "text,expected",
    [
        ("1", ReplyChoice.YES),
        ("Yego", ReplyChoice.YES),
        ("yes", ReplyChoice.YES),
        ("2", ReplyChoice.NO),
        ("oya", ReplyChoice.NO),
        ("3", ReplyChoice.UNWELL),
        ("sindashize neza", ReplyChoice.UNWELL),
        ("STOP", "stop"),
        ("nobody knows", None),
    ],
)
def test_parse_reply(text, expected):
    assert parse_reply(text) == expected


def test_normalize_phone():
    assert normalize_phone("0788123456") == "+250788123456"
    assert normalize_phone("+254712345678") == "+254712345678"
    assert normalize_phone(" 788 123 456 ") == "+250788123456"


# ---------------------------------------------------------------- core loop
def test_checkin_is_scheduled_and_sent():
    with DBSession() as db:
        patient = make_patient(db)
        result = run_scheduler(db, force=True)
        assert result["sent"] >= 1

        checkin = (
            db.query(OutboundMessage)
            .filter(
                OutboundMessage.patient_id == patient.id,
                OutboundMessage.kind == MessageKind.CHECKIN.value,
            )
            .first()
        )
        assert checkin is not None
        assert checkin.status in ("sent", "delivered")
        assert "Muraho Marie" in checkin.body
        assert checkin.cost_rwf > 0


def test_missed_doses_raise_then_clear_alerts():
    with DBSession() as db:
        patient = make_patient(db)
        run_scheduler(db, force=True)

        # three consecutive "no" replies → amber then red
        for _ in range(3):
            process_inbound(db, patient.phone, "2", provider_id=f"t-{_}")

        db.refresh(patient)
        assert patient.missed_streak == 3
        assert patient.status in ("amber", "red")
        rules = {a.rule for a in patient.alerts if a.state != "resolved"}
        assert "medication_nonadherence:diabetes" in rules

        # a "yes" reply resets the streak and auto-resolves the alert
        process_inbound(db, patient.phone, "1", provider_id="t-yes")
        db.refresh(patient)
        assert patient.missed_streak == 0
        open_alerts = [a for a in patient.alerts if a.state != "resolved"]
        assert not any(a.rule.startswith("medication_nonadherence") for a in open_alerts)


def test_unwell_reply_raises_red_alert():
    with DBSession() as db:
        patient = make_patient(db)
        process_inbound(db, patient.phone, "3", provider_id="t-unwell")
        db.refresh(patient)
        assert patient.status == "red"
        assert any(a.rule == "reported_unwell" for a in patient.alerts)


def test_stop_opt_out():
    with DBSession() as db:
        patient = make_patient(db)
        result = process_inbound(db, patient.phone, "STOP", provider_id="t-stop")
        assert result["status"] == "opted_out"
        db.refresh(patient)
        assert patient.consent_sms is False
        # opted-out patients receive no further protocol messages
        due = build_due_messages(db)
        assert all(m.patient_id != patient.id for m in due)


def test_appointment_reminder_goes_out():
    from datetime import timedelta

    with DBSession() as db:
        patient = make_patient(db)
        db.add(
            Appointment(
                patient_id=patient.id,
                due_at=now() + timedelta(days=2),
                status="upcoming",
            )
        )
        db.commit()
        run_scheduler(db, force=True)
        reminder = (
            db.query(OutboundMessage)
            .filter(
                OutboundMessage.patient_id == patient.id,
                OutboundMessage.kind == MessageKind.APPOINTMENT.value,
            )
            .first()
        )
        assert reminder is not None
        assert "1=Nzaza" in reminder.body or "1=I will attend" in reminder.body


def test_adherence_stats_and_metrics():
    with DBSession() as db:
        patient = make_patient(db)
        run_scheduler(db, force=True)
        process_inbound(db, patient.phone, "1", provider_id="m1")
        stats = adherence_stats(db, days=7)
        assert stats["checkins_sent"] >= 1
        assert stats["yes"] == 1
        assert stats["adherence_rate"] == 1.0


def test_daily_jobs_mark_missed_appointments():
    from datetime import timedelta

    with DBSession() as db:
        patient = make_patient(db)
        db.add(
            Appointment(
                patient_id=patient.id,
                due_at=now() - timedelta(days=3),
                status="upcoming",
            )
        )
        db.commit()
        result = run_daily_jobs(db)
        assert result["appointments_marked_missed"] == 1
        assert any(a.rule == "missed_appointment" for a in patient.alerts)


# ---------------------------------------------------------------- web layer
def test_login_required(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303, 307)
    assert resp.headers["location"] == "/login"


def test_dashboard_renders_after_login(client):
    with DBSession() as db:
        make_patient(db)
        db.add(
            User(
                clinic_id=1,
                name="Tester",
                email="tester@uburinzi.rw",
                password_hash=hash_password("password123"),
                role="admin",
            )
        )
    resp = client.post(
        "/login",
        data={"email": "tester@uburinzi.rw", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/"
    page = client.get("/")
    assert page.status_code == 200
    assert "Adherence" in page.text


def test_inbound_webhook_accepts_africastalking_form(client):
    with DBSession() as db:
        patient = make_patient(db, phone="+250788000999")
        patient_id = patient.id
    resp = client.post(
        "/api/webhooks/sms/inbound",
        data={"from": "+250788000999", "text": "1", "id": "ATX-1", "date": "2026-09-16 10:00:00"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "yes"
    assert body["patient_id"] == patient_id


def test_integration_api_requires_key(client):
    resp = client.post(
        "/api/integrations/patients",
        json={"first_name": "No", "last_name": "Key", "phone": "+250788111222", "program": "hiv"},
    )
    assert resp.status_code == 401

    resp = client.post(
        "/api/integrations/patients",
        json={"first_name": "With", "last_name": "Key", "phone": "+250788111222", "program": "hiv"},
        headers={"X-API-Key": config.API_KEY},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1


def test_health_endpoint(client):
    assert client.get("/health").json()["ok"] is True

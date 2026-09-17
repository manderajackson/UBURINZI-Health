"""Tests for WhatsApp, voice and the SMS → WhatsApp → voice escalation ladder."""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import settings_store
from app.crypto import decrypt, encrypt
from sqlalchemy import select

from app.db import DBSession
from app.engine import place_voice_call, process_inbound, run_escalations, run_scheduler
from app.models import (
    Alert,
    AlertSeverity,
    Channel,
    InboundMessage,
    MessageKind,
    OutboundMessage,
    Patient,
    User,
    VoiceCall,
)
from app.security import hash_password
from app.timeutils import now
from app.voice import ack_for, checkin_call_xml, prompts_for

from tests.test_smoke import make_patient  # reuse the fixture helpers


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def logged_in(client):
    """Sign in with the account the app bootstraps on an empty database."""
    resp = client.post(
        "/login",
        data={"email": "founder@uburinzi.rw", "password": "uburinzi2026"},
        follow_redirects=False,
    )
    assert resp.headers.get("location") == "/", resp.text[:400]
    return client


# ------------------------------------------------------------------ encryption
def test_credentials_are_encrypted_at_rest():
    token = encrypt("atsk_secret_value")
    assert "secret_value" not in token
    assert decrypt(token) == "atsk_secret_value"
    assert decrypt("plaintext-legacy") == "plaintext-legacy"


def test_settings_store_roundtrip():
    from app.models import Setting

    with DBSession() as db:
        settings_store.set_value(db, "at_api_key", "atsk_1234567890")
        stored = db.execute(select(Setting).where(Setting.key == "at_api_key")).scalar_one()
        assert "atsk_1234567890" not in (stored.value or "")
        assert stored.value.startswith("enc1:")
        assert settings_store.get_secret(db, "at_api_key") == "atsk_1234567890"
        settings_store.set_value(db, "at_api_key", "")


# ----------------------------------------------------------------------- voice
def test_voice_xml_has_ivr_flow():
    xml = checkin_call_xml(
        greeting="Hello Marie",
        digits_prompt="Press 1 for yes",
        callback_url="https://example.org/api/webhooks/voice/dtmf",
        goodbye="Goodbye",
        language="en",
    )
    assert xml.startswith("<?xml")
    assert "<GetDigits" in xml
    assert 'callbackUrl="https://example.org/api/webhooks/voice/dtmf"' in xml
    assert xml.count("<Say") == 3
    assert "Hello Marie" in xml


def test_voice_prompts_are_localised():
    greeting, digits, goodbye = prompts_for("rw", "Marie", "Uburinzi Clinic")
    assert "Marie" in greeting and "Uburinzi Clinic" in greeting
    assert "Kanda 1" in digits
    assert ack_for("en", "yes") and ack_for("rw", "unwell")


def test_place_voice_call_creates_call_record():
    with DBSession() as db:
        patient = make_patient(db, phone="+250788000777")
        call = place_voice_call(db, patient, purpose="test")
        assert call.status in ("ringing", "failed")
        assert call.phone == patient.phone
        assert call.outbound_id is not None
        msg = db.get(OutboundMessage, call.outbound_id)
        assert msg.channel == Channel.VOICE.value


def test_voice_dtmf_webhook_records_the_keypress(client):
    with DBSession() as db:
        patient = make_patient(db, phone="+250788000888")
        place_voice_call(db, patient)
        pid = patient.id

    resp = client.post(
        "/api/webhooks/voice/dtmf",
        data={"dtmfDigits": "3", "sessionId": "SID-1", "callerNumber": "+250788000888"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "<Response>" in resp.text

    with DBSession() as db:
        stored = db.query(VoiceCall).order_by(VoiceCall.id.desc()).first()
        assert stored.dtmf_digits == "3"
        assert stored.status == "completed"
        inbound = (
            db.query(InboundMessage)
            .filter(InboundMessage.patient_id == pid, InboundMessage.channel == Channel.VOICE.value)
            .first()
        )
        assert inbound is not None and inbound.choice == "unwell"


def test_voice_answer_webhook_returns_ivr(client):
    with DBSession() as db:
        patient = make_patient(db, phone="+250788000889")
        place_voice_call(db, patient)
    resp = client.post(
        "/api/webhooks/voice/answer",
        data={"sessionId": "SID-2", "callerNumber": "+250788000889", "callSessionState": "Answered"},
    )
    assert resp.status_code == 200
    assert "<GetDigits" in resp.text


def test_voice_event_webhook_updates_status(client):
    with DBSession() as db:
        patient = make_patient(db, phone="+250788000890")
        call = place_voice_call(db, patient)
        call_id = call.id
    resp = client.post(
        "/api/webhooks/voice/event",
        data={"sessionId": "", "callerNumber": "+250788000890",
              "callSessionState": "NoAnswer", "durationInSeconds": "0"},
    )
    assert resp.json()["ok"] is True
    with DBSession() as db:
        assert db.get(VoiceCall, call_id).status == "no-answer"


# -------------------------------------------------------------------- whatsapp
def test_whatsapp_webhook_accepts_meta_payload(client):
    with DBSession() as db:
        patient = make_patient(db, phone="+250788000555")
        pid = patient.id
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": "250788000555", "id": "wamid.123", "type": "text",
                                 "text": {"body": "1"}}
                            ]
                        }
                    }
                ]
            }
        ]
    }
    resp = client.post("/api/webhooks/whatsapp", json=payload)
    assert resp.status_code == 200
    assert resp.json()["processed"] == 1
    with DBSession() as db:
        inbound = (
            db.query(InboundMessage)
            .filter(InboundMessage.patient_id == pid, InboundMessage.channel == Channel.WHATSAPP.value)
            .first()
        )
        assert inbound is not None and inbound.choice == "yes"


def test_whatsapp_webhook_accepts_simple_payload(client):
    with DBSession() as db:
        patient = make_patient(db, phone="+250788000556")
        pid = patient.id
    resp = client.post(
        "/api/webhooks/whatsapp",
        json={"from": "+250788000556", "text": "2", "id": "simple-1"},
    )
    assert resp.json()["processed"] == 1
    with DBSession() as db:
        assert (
            db.query(InboundMessage)
            .filter(InboundMessage.patient_id == pid, InboundMessage.choice == "no")
            .count()
            == 1
        )


def test_whatsapp_verification_handshake(client):
    resp = client.get(
        "/api/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "uburinzi-verify", "hub.challenge": "12345"},
    )
    assert resp.status_code == 200
    assert resp.text == "12345"
    assert client.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "wrong"}).status_code == 403


# ----------------------------------------------------------------- escalation
def test_escalation_ladder_sms_to_whatsapp_to_voice():
    with DBSession() as db:
        patient = make_patient(db, phone="+250788000999")
        run_scheduler(db, force=True)

        checkin = (
            db.query(OutboundMessage)
            .filter(
                OutboundMessage.patient_id == patient.id,
                OutboundMessage.kind == MessageKind.CHECKIN.value,
            )
            .order_by(OutboundMessage.id.desc())
            .first()
        )
        # pretend the check-in went out three days ago and was never answered
        checkin.sent_at = now() - timedelta(hours=72)
        db.add(checkin)
        # and the patient is flagged red
        db.add(
            Alert(
                patient_id=patient.id,
                rule="medication_nonadherence:diabetes",
                severity=AlertSeverity.RED.value,
                message="test fixture",
            )
        )
        patient.status = "red"
        db.add(patient)
        db.commit()

        result = run_escalations(db)
        assert result.get("whatsapp_sent", 0) >= 1 or result.get("voice_calls", 0) >= 1

        wa = (
            db.query(OutboundMessage)
            .filter(OutboundMessage.patient_id == patient.id, OutboundMessage.channel == Channel.WHATSAPP.value)
            .first()
        )
        call = (
            db.query(VoiceCall)
            .filter(VoiceCall.patient_id == patient.id)
            .first()
        )
        assert wa is not None, "expected a WhatsApp retry"
        assert call is not None, "expected a voice call escalation"

        # running again must not duplicate (idempotent by dedupe key)
        before = db.query(OutboundMessage).filter(
            OutboundMessage.patient_id == patient.id, OutboundMessage.channel == Channel.WHATSAPP.value
        ).count()
        run_escalations(db)
        after = db.query(OutboundMessage).filter(
            OutboundMessage.patient_id == patient.id, OutboundMessage.channel == Channel.WHATSAPP.value
        ).count()
        assert after == before


def test_escalation_skips_stable_patients():
    with DBSession() as db:
        patient = make_patient(db, phone="+250788000998")
        run_scheduler(db, force=True)
        checkin = (
            db.query(OutboundMessage)
            .filter(OutboundMessage.patient_id == patient.id, OutboundMessage.kind == MessageKind.CHECKIN.value)
            .order_by(OutboundMessage.id.desc())
            .first()
        )
        checkin.sent_at = now() - timedelta(hours=96)
        db.add(checkin)
        patient.status = "green"
        db.add(patient)
        db.commit()

        run_escalations(db)
        assert (
            db.query(OutboundMessage)
            .filter(OutboundMessage.patient_id == patient.id, OutboundMessage.channel == Channel.WHATSAPP.value)
            .count()
            == 0
        )


def test_escalation_can_be_disabled():
    with DBSession() as db:
        settings_store.set_value(db, "escalation_enabled", "false")
        result = run_escalations(db)
        assert result.get("skipped") is True
        settings_store.set_value(db, "escalation_enabled", "true")


# ------------------------------------------------------------------------ UI
def test_channels_page_renders(logged_in):
    page = logged_in.get("/channels")
    assert page.status_code == 200
    assert "Africa's Talking credentials" in page.text
    assert "/api/webhooks/voice/answer" in page.text


def test_channel_test_endpoint_requires_a_number(logged_in):
    resp = logged_in.post("/api/channels/test", json={"channel": "sms", "phone": ""})
    assert resp.status_code == 400


def test_channel_test_sends_via_simulator(logged_in):
    resp = logged_in.post("/api/channels/test", json={"channel": "sms", "phone": "+250788000321"})
    assert resp.status_code == 200
    assert resp.json()["status"] in ("delivered", "sent")

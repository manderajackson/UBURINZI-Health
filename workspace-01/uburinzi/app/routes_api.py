"""JSON API + Africa's Talking webhooks + EMR integration endpoints."""
from __future__ import annotations

import csv
import io
import random
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.deps import login_required
from app.engine import (
    evaluate_all,
    normalize_phone,
    process_inbound,
    place_voice_call,
    run_daily_jobs,
    run_escalations,
    run_scheduler,
)
from app.messaging.gateway import queue_message, send_message
from app.messaging.render import render_template
from app import settings_store
from app.metrics import dashboard_stats, impact_report
from app.models import (
    Alert,
    Appointment,
    AuditLog,
    Channel,
    Clinic,
    Enrollment,
    InboundMessage,
    MessageKind,
    MessageStatus,
    OutboundMessage,
    Patient,
    User,
    VoiceCall,
)
from app.protocols import PROGRAMS
from app.timeutils import now
from app.voice import ack_for, checkin_call_xml, dtmf_response_xml, goodbye_xml, prompts_for

router = APIRouter()


def _check_api_key(x_api_key: str | None) -> bool:
    expected = getattr(config, "API_KEY", "demo-api-key")
    return bool(x_api_key) and x_api_key == expected


# ------------------------------------------------------------------ webhooks
@router.post("/api/webhooks/sms/inbound")
async def sms_inbound(request: Request, db: Session = Depends(get_db)):
    """Africa's Talking posts form-encoded `from`, `to`, `text`, `date`, `id`."""
    if request.headers.get("content-type", "").startswith("application/json"):
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    phone = payload.get("from") or payload.get("sender") or payload.get("phone") or ""
    text = payload.get("text") or payload.get("message") or ""
    provider_id = payload.get("id") or payload.get("messageId") or ""
    result = process_inbound(db, phone, text, provider_id=provider_id)
    return {"ok": True, **result}


@router.post("/api/webhooks/sms/delivery")
async def sms_delivery(request: Request, db: Session = Depends(get_db)):
    if request.headers.get("content-type", "").startswith("application/json"):
        payload = await request.json()
    else:
        payload = dict(await request.form())
    provider_id = str(payload.get("id") or payload.get("messageId") or "")
    status = str(payload.get("status") or "").lower()
    msg = db.execute(
        select(OutboundMessage).where(OutboundMessage.provider_id == provider_id)
    ).scalar_one_or_none()
    if not msg:
        return {"ok": False, "reason": "unknown message"}
    if status in ("delivered", "success", "sent"):
        msg.status = "delivered"
        msg.delivered_at = now()
    elif status in ("failed", "rejected", "undelivered"):
        msg.status = "failed"
        msg.error = status
    db.add(msg)
    db.commit()
    return {"ok": True, "status": msg.status}


# ----------------------------------------------------------------- scheduler
@router.post("/api/scheduler/run")
def scheduler_run(force: bool = True, db: Session = Depends(get_db), user: User = Depends(login_required)):
    result = run_scheduler(db, force=force)
    return {"ok": True, **result}


@router.post("/api/jobs/daily")
def jobs_daily(db: Session = Depends(get_db), user: User = Depends(login_required)):
    return {"ok": True, **run_daily_jobs(db)}


@router.post("/api/alerts/sweep")
def alerts_sweep(db: Session = Depends(get_db), user: User = Depends(login_required)):
    count = evaluate_all(db)
    return {"ok": True, "patients_evaluated": count}


# ----------------------------------------------------------------- simulator
@router.post("/api/simulator/reply")
async def simulator_reply(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    form = await request.form()
    patient_id = int(form.get("patient_id") or 0)
    text = str(form.get("text") or "")
    patient = db.get(Patient, patient_id)
    if not patient:
        return RedirectResponse("/simulator?msg=Patient+not+found&cat=error", status_code=303)
    channel = str(form.get("channel") or "sms").strip()
    if channel not in ("sms", "whatsapp", "voice"):
        channel = "sms"
    result = process_inbound(
        db, patient.phone, text,
        provider_id=f"UI-{patient.id}-{now().timestamp()}",
        simulated=True, channel=channel,
    )
    return RedirectResponse(
        f"/simulator?patient_id={patient_id}&msg=Reply+%22{text}%22+processed+%28{result.get('status')}%29&cat=ok",
        status_code=303,
    )


@router.post("/api/simulator/auto")
def simulator_auto(count: int = 12, db: Session = Depends(get_db), user: User = Depends(login_required)):
    """Generate realistic replies for the most recent unanswered check-ins."""
    recent = (
        db.execute(
            select(OutboundMessage)
            .where(
                OutboundMessage.kind == MessageKind.CHECKIN.value,
                OutboundMessage.sent_at.isnot(None),
            )
            .order_by(OutboundMessage.sent_at.desc())
            .limit(400)
        )
        .scalars()
        .all()
    )
    made = 0
    rng = random.Random()
    for msg in recent:
        if made >= count:
            break
        patient = msg.patient
        if not patient or not patient.active:
            continue
        already = db.execute(
            select(func.count(InboundMessage.id)).where(
                InboundMessage.patient_id == patient.id,
                InboundMessage.received_at >= msg.sent_at,
            )
        ).scalar()
        if already:
            continue
        roll = rng.random()
        adherence = patient.sim_adherence or 0.8
        if roll < adherence:
            text = "1"
        elif roll < adherence + (1 - adherence) * 0.85:
            text = "2"
        else:
            text = "3"
        process_inbound(
            db,
            patient.phone,
            text,
            provider_id=f"AUTO-{msg.id}",
            simulated=True,
            received_at=min(now(), msg.sent_at + timedelta(minutes=rng.randint(5, 240))),
        )
        made += 1
    return RedirectResponse(f"/simulator?msg=Generated+{made}+replies&cat=ok", status_code=303)


# ---------------------------------------------------------------- data / API
@router.get("/api/stats")
def api_stats(days: int = 30, db: Session = Depends(get_db), user: User = Depends(login_required)):
    return dashboard_stats(db, days=days)


@router.get("/api/impact-report")
def api_impact(days: int = 30, db: Session = Depends(get_db), user: User = Depends(login_required)):
    return impact_report(db, days=days)


@router.get("/api/patients")
def api_patients(q: str = "", limit: int = 100, db: Session = Depends(get_db), user: User = Depends(login_required)):
    stmt = select(Patient).limit(limit)
    if q:
        stmt = stmt.where(Patient.phone.ilike(f"%{q}%") | Patient.last_name.ilike(f"%{q}%"))
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": p.id,
            "mrn": p.mrn,
            "name": p.full_name,
            "phone": p.phone,
            "language": p.language,
            "status": p.status,
            "missed_streak": p.missed_streak,
            "programs": [e.program for e in p.enrollments if e.active],
        }
        for p in rows
    ]


class PatientIn(BaseModel):
    mrn: str | None = None
    first_name: str
    last_name: str = ""
    phone: str
    language: str = "rw"
    program: str = "diabetes"
    medication: str = ""
    birth_year: int | None = None
    village: str = ""
    sex: str = "unknown"


@router.post("/api/integrations/patients")
async def integration_patients(request: Request, x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """EMR adapter endpoint: upsert a patient from ClinicPlus / OpenMRS / DHIS2."""
    if not _check_api_key(x_api_key):
        raise HTTPException(401, "Invalid API key")
    payload = await request.json()
    data = PatientIn(**payload) if not isinstance(payload, list) else None
    rows = payload if isinstance(payload, list) else [payload]

    created = updated = 0
    for row in rows:
        model = PatientIn(**row)
        phone = normalize_phone(model.phone)
        patient = db.execute(select(Patient).where(Patient.phone == phone)).scalar_one_or_none()
        if patient is None:
            clinic = db.execute(select(Clinic).limit(1)).scalar_one_or_none()
            patient = Patient(
                clinic_id=clinic.id if clinic else 1,
                mrn=model.mrn or f"API-{phone[-6:]}",
                first_name=model.first_name,
                last_name=model.last_name,
                phone=phone,
                language=model.language,
                birth_year=model.birth_year,
                village=model.village,
                sex=model.sex,
                consent_sms=False,
            )
            db.add(patient)
            db.flush()
            created += 1
        else:
            updated += 1
        if model.program in PROGRAMS:
            enr = db.execute(
                select(Enrollment).where(
                    Enrollment.patient_id == patient.id, Enrollment.program == model.program
                )
            ).scalar_one_or_none()
            if enr is None:
                db.add(
                    Enrollment(
                        patient_id=patient.id,
                        program=model.program,
                        medication=model.medication or PROGRAMS[model.program]["default_medication"],
                    )
                )
    db.commit()
    return {"ok": True, "created": created, "updated": updated}


class LabResultIn(BaseModel):
    phone: str
    test_name: str = "lab result"
    message: str | None = None


@router.post("/api/integrations/lab-results")
async def integration_lab_results(request: Request, x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Trigger an SMS when a diagnostic result lands in the LIS/EMR."""
    if not _check_api_key(x_api_key):
        raise HTTPException(401, "Invalid API key")
    payload = await request.json()
    model = LabResultIn(**payload)
    patient = db.execute(
        select(Patient).where(Patient.phone == normalize_phone(model.phone))
    ).scalar_one_or_none()
    if not patient:
        raise HTTPException(404, "Unknown patient")
    clinic = db.execute(select(Clinic).limit(1)).scalar_one_or_none()
    body = model.message or render_template(
        db,
        "common",
        "lab_result",
        patient.language,
        ctx={
            "first_name": patient.first_name,
            "clinic": clinic.name if clinic else "the clinic",
            "phone": clinic.phone if clinic else "",
        },
    )
    msg = queue_message(db, patient=patient, body=body, kind=MessageKind.LAB_RESULT.value, program="common")
    send_message(db, msg)
    db.commit()
    return {"ok": True, "message_id": msg.id, "status": msg.status, "body": body}


# --------------------------------------------------------- WhatsApp webhook
@router.get("/api/webhooks/whatsapp")
def whatsapp_verify(
    request: Request,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    db: Session = Depends(get_db),
):
    """Meta-style handshake. Africa's Talking users can skip this."""
    expected = settings_store.get(db, "whatsapp_verify_token", "uburinzi-verify")
    if hub_mode == "subscribe" and hub_verify_token == expected:
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(403, "Verification token mismatch")


def _extract_whatsapp_messages(payload: dict) -> list[dict]:
    """Handle Meta Cloud API payloads and simple {from, text} payloads."""
    out: list[dict] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for message in value.get("messages", []) or []:
                if message.get("type") not in (None, "text"):
                    continue
                out.append(
                    {
                        "from": message.get("from") or "",
                        "text": (message.get("text") or {}).get("body", "")
                        or (message.get("button") or {}).get("text", ""),
                        "id": message.get("id") or "",
                    }
                )
    if not out and payload.get("from"):
        out.append(
            {
                "from": payload.get("from") or payload.get("phoneNumber") or "",
                "text": payload.get("text") or payload.get("message") or "",
                "id": payload.get("id") or payload.get("messageId") or "",
            }
        )
    return out


@router.post("/api/webhooks/whatsapp")
async def whatsapp_inbound(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = dict(await request.form())

    results = []
    for item in _extract_whatsapp_messages(payload):
        if not item["from"]:
            continue
        results.append(
            process_inbound(
                db,
                phone=item["from"],
                text=item["text"],
                provider_id=item["id"] or f"WA-{abs(hash((item['from'], item['text']))) % 10**12}",
                channel=Channel.WHATSAPP.value,
            )
        )
    return {"ok": True, "processed": len(results), "results": results}


# ------------------------------------------------------------ Voice webhooks
def _public_base_url(request: Request, db: Session) -> str:
    configured = settings_store.get(db, "public_base_url", "")
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def _find_pending_call(db: Session, phone: str, session_id: str = ""):
    stmt = select(VoiceCall).where(VoiceCall.phone == normalize_phone(phone))
    if session_id:
        row = db.execute(stmt.where(VoiceCall.session_id == session_id)).scalars().first()
        if row:
            return row
    return (
        db.execute(
            stmt.where(VoiceCall.status.in_(["queued", "ringing"]))
            .order_by(VoiceCall.created_at.desc())
        )
        .scalars()
        .first()
    )


@router.post("/api/webhooks/voice/answer")
async def voice_answer(request: Request, db: Session = Depends(get_db)):
    """Africa's Talking calls this when the patient picks up. Return the IVR XML."""
    from fastapi.responses import Response as RawResponse

    form = dict(await request.form())
    if not form:
        try:
            form = await request.json()
        except Exception:
            form = {}
    phone = form.get("callerNumber") or form.get("destinationNumber") or ""
    session_id = form.get("sessionId", "")
    base = _public_base_url(request, db)

    call = _find_pending_call(db, phone, session_id)
    patient = db.get(Patient, call.patient_id) if call else None
    if call:
        call.session_id = call.session_id or session_id
        call.status = "answered"
        call.answered_at = now()
        db.add(call)
        db.commit()

    if not patient:
        return RawResponse(
            goodbye_xml("Sorry, we could not find your record. Please call the clinic."),
            media_type="application/xml",
        )

    clinic = patient.clinic
    greeting, digits_prompt, goodbye = prompts_for(
        patient.language, patient.first_name, clinic.name if clinic else "the clinic"
    )
    play_url = settings_store.get(db, "voice_prompt_url", "") or None
    xml = checkin_call_xml(
        greeting=greeting,
        digits_prompt=digits_prompt,
        callback_url=f"{base}/api/webhooks/voice/dtmf",
        goodbye=goodbye,
        language=patient.language,
        play_url=play_url,
    )
    return RawResponse(xml, media_type="application/xml")


@router.post("/api/webhooks/voice/dtmf")
async def voice_dtmf(request: Request, db: Session = Depends(get_db)):
    """The patient pressed a key: 1 = took it, 2 = missed, 3 = unwell."""
    from fastapi.responses import Response as RawResponse

    form = dict(await request.form())
    if not form:
        try:
            form = await request.json()
        except Exception:
            form = {}
    digits = str(form.get("dtmfDigits") or "").strip()
    phone = form.get("callerNumber") or form.get("destinationNumber") or ""
    session_id = form.get("sessionId", "")

    call = _find_pending_call(db, phone, session_id)
    patient = db.get(Patient, call.patient_id) if call else None

    if call:
        call.dtmf_digits = digits
        call.status = "completed"
        call.ended_at = now()
        if call.answered_at:
            call.duration_seconds = int((call.ended_at - call.answered_at).total_seconds())
            call.cost_rwf = round(max(call.duration_seconds, 1) / 60.0 * 60.0, 2)
        db.add(call)

    result = {"status": "unknown_number"}
    language = "en"
    if patient:
        language = patient.language
        result = process_inbound(
            db,
            phone=patient.phone,
            text=digits or "0",
            provider_id=f"DTMF-{call.id if call else 'x'}-{session_id}",
            channel=Channel.VOICE.value,
        )
    db.commit()

    parsed = result.get("choice") or result.get("status")
    return RawResponse(
        dtmf_response_xml(thanks=ack_for(language, parsed if parsed in ("yes", "no", "unwell") else None), language=language),
        media_type="application/xml",
    )


@router.post("/api/webhooks/voice/event")
async def voice_event(request: Request, db: Session = Depends(get_db)):
    """Call progress / completion events (no-answer, busy, cost, duration)."""
    form = dict(await request.form())
    if not form:
        try:
            form = await request.json()
        except Exception:
            form = {}

    state = (form.get("callSessionState") or form.get("status") or "").strip()
    phone = form.get("callerNumber") or form.get("destinationNumber") or ""
    call = _find_pending_call(db, phone, form.get("sessionId", ""))
    if not call:
        return {"ok": False, "reason": "no matching call"}

    mapping = {
        "Answered": "answered",
        "Completed": "completed",
        "NoAnswer": "no-answer",
        "Busy": "busy",
        "Failed": "failed",
        "Ringing": "ringing",
    }
    call.status = mapping.get(state, call.status)
    if form.get("durationInSeconds"):
        try:
            call.duration_seconds = int(float(form["durationInSeconds"]))
        except (TypeError, ValueError):
            pass
    if form.get("amount"):
        try:
            call.cost_rwf = float(form["amount"])
        except (TypeError, ValueError):
            pass
    if state in ("Answered",) and not call.answered_at:
        call.answered_at = now()
    if state in ("Completed", "NoAnswer", "Busy", "Failed") and not call.ended_at:
        call.ended_at = now()
    db.add(call)
    db.commit()
    return {"ok": True, "status": call.status}


# -------------------------------------------------------- channel management
@router.get("/api/channels")
def api_channels(db: Session = Depends(get_db), user: User = Depends(login_required)):
    from app.messaging.gateway import channel_summary

    return {"channels": channel_summary(db)}


@router.post("/api/channels/test")
async def api_channel_test(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    """Send a live test message/call through the configured driver."""
    try:
        payload = await request.json()
    except Exception:
        payload = dict(await request.form())
    channel = (payload.get("channel") or "sms").strip()
    phone = normalize_phone(str(payload.get("phone") or ""))
    if not phone:
        raise HTTPException(400, "A phone number in international format is required")

    from app.messaging.gateway import queue_message as _queue

    patient = db.execute(select(Patient).where(Patient.phone == phone)).scalar_one_or_none()
    if patient is None:
        # Reuse the single scratch "TEST" record so repeated tests to different
        # numbers cannot trip the (clinic_id, mrn) unique constraint.
        clinic = db.execute(select(Clinic).limit(1)).scalar_one_or_none()
        patient = db.execute(
            select(Patient).where(Patient.mrn == "TEST", Patient.clinic_id == (clinic.id if clinic else 1))
        ).scalar_one_or_none()
        if patient is not None:
            patient.phone = phone
        else:
            patient = Patient(
                clinic_id=clinic.id if clinic else 1,
                mrn="TEST",
                first_name="Test",
                last_name="Number",
                phone=phone,
                language="en",
                consent_sms=True,
                active=False,  # a test number is never monitored automatically
            )
        db.add(patient)
        db.flush()

    body = "Uburinzi Health: this is a test message from your clinic. Ignore it, no reply needed."
    if channel == Channel.VOICE.value:
        try:
            call = place_voice_call(db, patient, purpose="test")
            return {
                "ok": call.status != "failed",
                "channel": "voice",
                "status": call.status,
                "error": call.error,
                "driver": call.provider,
                "call_id": call.id,
            }
        except Exception as exc:
            db.rollback()
            return {"ok": False, "channel": "voice", "error": str(exc)[:200]}

    msg = _queue(
        db,
        patient=patient,
        body=body,
        kind=MessageKind.MANUAL.value,
        channel=channel,
        language=patient.language or "en",
    )
    send_message(db, msg)
    db.commit()
    return {
        "ok": msg.status != MessageStatus.FAILED.value,
        "channel": channel,
        "status": msg.status,
        "error": msg.error,
        "driver": msg.provider,
        "body": body,
    }


@router.get("/api/channels/balance")
def api_balance(db: Session = Depends(get_db), user: User = Depends(login_required)):
    from app.messaging.drivers import check_balance

    return check_balance(settings_store.get_all(db, include_secrets=True))


@router.post("/api/escalations/run")
def api_escalations(db: Session = Depends(get_db), user: User = Depends(login_required)):
    return {"ok": True, **run_escalations(db)}


# ------------------------------------------------------------------- exports
def _csv_response(filename: str, headers: list[str], rows) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/export/patients.csv")
def export_patients(db: Session = Depends(get_db), user: User = Depends(login_required)):
    rows = []
    for p in db.execute(select(Patient).order_by(Patient.id)).scalars():
        rows.append([
            p.mrn, p.full_name, p.phone, p.language, p.sex, p.birth_year or "", p.village,
            p.status, p.missed_streak, p.no_reply_streak,
            ", ".join(e.program for e in p.enrollments if e.active),
            "yes" if p.consent_sms else "no",
        ])
    return _csv_response(
        "uburinzi_patients.csv",
        ["mrn", "name", "phone", "language", "sex", "birth_year", "village",
         "status", "missed_streak", "no_reply_streak", "programs", "consent"],
        rows,
    )


@router.get("/api/export/messages.csv")
def export_messages(db: Session = Depends(get_db), user: User = Depends(login_required)):
    rows = []
    for m in db.execute(select(OutboundMessage).order_by(OutboundMessage.id.desc()).limit(20000)).scalars():
        rows.append([
            m.id, m.sent_at or m.created_at, m.patient.full_name if m.patient else "", m.phone,
            m.program, m.kind, m.language, m.status, m.provider, m.segments, m.cost_rwf, m.body,
        ])
    return _csv_response(
        "uburinzi_messages.csv",
        ["id", "sent_at", "patient", "phone", "program", "kind", "language", "status",
         "provider", "segments", "cost_rwf", "body"],
        rows,
    )


@router.get("/api/export/alerts.csv")
def export_alerts(db: Session = Depends(get_db), user: User = Depends(login_required)):
    rows = [
        [a.id, a.created_at, a.patient.full_name if a.patient else "", a.rule, a.severity, a.state, a.message]
        for a in db.execute(select(Alert).order_by(Alert.id.desc())).scalars()
    ]
    return _csv_response(
        "uburinzi_alerts.csv",
        ["id", "created_at", "patient", "rule", "severity", "state", "message"], rows
    )


@router.get("/api/export/sample-import.csv")
def export_sample_import(db: Session = Depends(get_db), user: User = Depends(login_required)):
    rows = []
    for p in db.execute(select(Patient).limit(25)).scalars():
        program = p.enrollments[0].program if p.enrollments else "diabetes"
        med = p.enrollments[0].medication if p.enrollments else ""
        rows.append([p.mrn, p.first_name, p.last_name, p.phone, p.language, p.sex, p.birth_year or "", p.village, program, med])
    return _csv_response(
        "sample_clinicplus_export.csv",
        ["mrn", "first_name", "last_name", "phone", "language", "sex", "birth_year", "village", "program", "medication"],
        rows,
    )


@router.get("/api/docs")
def api_docs():
    return RedirectResponse("/docs")

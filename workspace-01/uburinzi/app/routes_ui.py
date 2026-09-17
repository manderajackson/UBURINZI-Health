"""Web dashboard routes (server-rendered, no build step)."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.charts import bar_chart, donut, line_chart
from app.db import get_db
from app.deps import flash_redirect, login_required, logout_response, render
from app.engine import (
    enroll_patient,
    evaluate_all,
    evaluate_patient,
    normalize_phone,
    process_inbound,
    place_voice_call,
    run_daily_jobs,
    run_scheduler,
    send_manual_message,
)
from app.messaging.drivers import CHANNEL_DRIVER_OPTIONS
from app.messaging.gateway import channel_summary, queue_message, resolve_driver_name, send_message
from app.metrics import dashboard_stats, impact_report
from app.models import (
    Channel,
    Alert,
    AlertState,
    Appointment,
    AuditLog,
    Clinic,
    Enrollment,
    InboundMessage,
    MessageStatus,
    MessageTemplate,
    OutboundMessage,
    Patient,
    User,
    VoiceCall,
)
from app import config, settings_store
from app.crypto import mask
from app.protocols import PROGRAMS
from app.security import create_session_token, hash_password, verify_password
from app.timeutils import now

router = APIRouter()


# --------------------------------------------------------------------- auth
@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    return render(request, db, "login.html", active="login", error=None)


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return render(request, db, "login.html", active="login", error="Wrong email or password.")
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        "uburinzi_session",
        create_session_token(user.id, user.role, user.name),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    db.add(AuditLog(actor=user.email, action="login"))
    db.commit()
    return resp


@router.get("/logout")
def logout():
    return logout_response()


# ---------------------------------------------------------------- dashboard
@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    stats = dashboard_stats(db, days=30)
    series = stats["series"]

    adherence_values = [round((row["adherence"] or 0) * 100, 1) if row["replies"] else None for row in series]
    volume_pairs = [(row["day"].strftime("%d %b"), row["sent"]) for row in series]

    from datetime import timedelta as _td

    start30 = now() - _td(days=30)
    channel_counts = {
        row[0]: row[1]
        for row in db.execute(
            select(OutboundMessage.channel, func.count(OutboundMessage.id))
            .where(OutboundMessage.sent_at.isnot(None), OutboundMessage.sent_at >= start30)
            .group_by(OutboundMessage.channel)
        ).all()
    }
    recent_calls = (
        db.execute(select(VoiceCall).order_by(VoiceCall.created_at.desc()).limit(5)).scalars().all()
    )
    escalated = (
        db.execute(
            select(func.count(func.distinct(OutboundMessage.patient_id))).where(
                OutboundMessage.channel.in_([Channel.WHATSAPP.value, Channel.VOICE.value]),
                OutboundMessage.sent_at.isnot(None),
                OutboundMessage.sent_at >= start30,
            )
        ).scalar()
        or 0
    )

    from app.charts import bar_chart as _bar

    charts = {
        "channels": _bar(
            [
                ("SMS", channel_counts.get("sms", 0)),
                ("WhatsApp", channel_counts.get("whatsapp", 0)),
                ("Voice", channel_counts.get("voice", 0)),
            ],
            color="#0f766e",
        ),
        "adherence": line_chart(adherence_values, max_value=100, color="#0f766e", fill="#0f766e22"),
        "volume": bar_chart(volume_pairs, color="#2563eb"),
        "status_donut": donut(
            [
                ("Stable", stats["status_counts"]["green"], "#16a34a"),
                ("At risk", stats["status_counts"]["amber"], "#d97706"),
                ("Urgent", stats["status_counts"]["red"], "#dc2626"),
            ],
            center_value=str(stats["active_patients"]),
            center_label="patients",
        ),
    }

    urgent = (
        db.execute(
            select(Alert)
            .where(
                Alert.state != AlertState.RESOLVED.value,
                Alert.severity.in_(["red", "amber"]),
            )
            .order_by(Alert.created_at.desc())
            .limit(6)
        )
        .scalars()
        .all()
    )

    return render(
        request, db, "dashboard.html", active="dashboard", stats=stats, charts=charts, urgent=urgent,
        channel_counts=channel_counts, recent_calls=recent_calls, escalated=escalated,
        store=settings_store.get_all(db),
    )


# ----------------------------------------------------------------- patients
@router.get("/patients")
def patients(
    request: Request,
    q: str = "",
    program: str = "",
    status: str = "",
    language: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    stmt = select(Patient).order_by(Patient.status.desc(), Patient.last_name)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Patient.first_name.ilike(pattern),
                Patient.last_name.ilike(pattern),
                Patient.phone.ilike(pattern),
                Patient.mrn.ilike(pattern),
            )
        )
    if status:
        stmt = stmt.where(Patient.status == status)
    if language:
        stmt = stmt.where(Patient.language == language)
    if program:
        stmt = stmt.join(Enrollment).where(Enrollment.program == program, Enrollment.active.is_(True))

    rows = db.execute(stmt).scalars().unique().all()
    return render(
        request, db, "patients.html", active="patients", patients=rows,
        filters={"q": q, "program": program, "status": status, "language": language},
    )


@router.get("/patients/new")
def new_patient(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    return render(request, db, "patient_new.html", active="patients")


@router.post("/patients/new")
def create_patient(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(""),
    phone: str = Form(...),
    mrn: str = Form(""),
    language: str = Form("rw"),
    birth_year: str = Form(""),
    sex: str = Form("unknown"),
    village: str = Form(""),
    program: str = Form("diabetes"),
    medication: str = Form(""),
    consent_sms: str = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    clinic = db.execute(select(Clinic).limit(1)).scalar_one()
    patient = Patient(
        clinic_id=clinic.id,
        mrn=mrn.strip() or f"UB-{now().year}-{now().strftime('%H%M%S')}",
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        phone=normalize_phone(phone),
        language=language,
        sex=sex,
        birth_year=int(birth_year) if birth_year.strip().isdigit() else None,
        village=village.strip(),
        consent_sms=bool(consent_sms),
        active=True,
        sim_adherence=0.82,
        sim_reply_rate=0.92,
    )
    db.add(patient)
    db.flush()

    enr = enroll_patient(db, patient, program, medication) if patient.consent_sms else Enrollment(
        patient_id=patient.id, program=program, medication=medication, active=True
    )
    db.add(enr)
    db.add(
        AuditLog(
            actor=user.email,
            action="patient.created",
            entity="patient",
            entity_id=str(patient.id),
            detail=f"{patient.full_name} enrolled in {program}. Consent: {bool(consent_sms)}",
        )
    )
    db.commit()
    return flash_redirect(f"/patients/{patient.id}", f"{patient.full_name} enrolled.", "ok")


@router.get("/patients/{patient_id}")
def patient_detail(
    request: Request,
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")

    since = now() - timedelta(days=30)
    out = (
        db.execute(
            select(OutboundMessage)
            .where(OutboundMessage.patient_id == patient_id, OutboundMessage.sent_at.isnot(None))
            .order_by(OutboundMessage.sent_at.desc())
            .limit(60)
        )
        .scalars()
        .all()
    )
    inb = (
        db.execute(
            select(InboundMessage)
            .where(InboundMessage.patient_id == patient_id)
            .order_by(InboundMessage.received_at.desc())
            .limit(60)
        )
        .scalars()
        .all()
    )
    timeline = [
        {"direction": "out", "at": m.sent_at or m.created_at, "body": m.body, "kind": m.kind,
         "status": m.status, "cost_rwf": m.cost_rwf, "simulated": m.provider == "simulator",
         "channel": m.channel}
        for m in out
    ] + [
        {"direction": "in", "at": m.received_at, "body": m.body, "choice": m.choice,
         "simulated": m.simulated, "channel": m.channel}
        for m in inb
    ]
    timeline.sort(key=lambda x: x["at"], reverse=True)
    timeline = timeline[:60]

    from app.metrics import adherence_stats

    adh = {"adherence": 0, "yes": 0, "no": 0, "unwell": 0}
    replies_yes = sum(1 for m in inb if m.choice == "yes")
    replies_no = sum(1 for m in inb if m.choice == "no")
    replies_unwell = sum(1 for m in inb if m.choice == "unwell")
    total_choice = replies_yes + replies_no + replies_unwell
    adh = {
        "adherence": (replies_yes / total_choice) if total_choice else 0,
        "yes": replies_yes,
        "no": replies_no,
        "unwell": replies_unwell,
    }

    open_alerts = (
        db.execute(
            select(Alert)
            .where(Alert.patient_id == patient_id, Alert.state != AlertState.RESOLVED.value)
            .order_by(Alert.created_at.desc())
        )
        .scalars()
        .all()
    )
    appointments = (
        db.execute(
            select(Appointment)
            .where(Appointment.patient_id == patient_id)
            .order_by(Appointment.due_at.desc())
        )
        .scalars()
        .all()
    )

    return render(
        request, db, "patient_detail.html", active="patients",
        patient=patient, timeline=timeline, stats=adh,
        open_alerts=open_alerts, appointments=appointments,
    )


@router.post("/patients/{patient_id}/send")
def patient_send(
    patient_id: int,
    body: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404)
    send_manual_message(db, patient, body.strip())
    db.add(AuditLog(actor=user.email, action="message.sent", entity="patient", entity_id=str(patient_id), detail=body[:120]))
    db.commit()
    return flash_redirect(f"/patients/{patient_id}", "Message sent.", "ok")


@router.post("/patients/{patient_id}/enroll")
def patient_enroll(
    patient_id: int,
    program: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404)
    enroll_patient(db, patient, program)
    db.add(AuditLog(actor=user.email, action="enrollment.created", entity="patient", entity_id=str(patient_id), detail=program))
    db.commit()
    return flash_redirect(f"/patients/{patient_id}", f"Enrolled in {PROGRAMS.get(program, {}).get('label', program)}.", "ok")


@router.post("/patients/{patient_id}/appointment")
def patient_appointment(
    patient_id: int,
    due_date: str = Form(...),
    reason: str = Form("Routine follow-up"),
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404)
    try:
        day = datetime.strptime(due_date, "%Y-%m-%d")
    except ValueError:
        return flash_redirect(f"/patients/{patient_id}", "Invalid date.", "error")
    db.add(
        Appointment(
            patient_id=patient.id,
            due_at=day.replace(hour=9, minute=0),
            reason=reason or "Routine follow-up",
            status="upcoming",
        )
    )
    db.commit()
    return flash_redirect(f"/patients/{patient_id}", "Appointment added — reminder goes out 3 days before.", "ok")


@router.post("/patients/{patient_id}/consent")
def patient_consent(
    patient_id: int,
    consent_sms: str = Form(None),
    active: str = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404)
    patient.consent_sms = bool(consent_sms)
    patient.active = bool(active)
    db.add(patient)
    db.add(
        AuditLog(
            actor=user.email,
            action="consent.updated",
            entity="patient",
            entity_id=str(patient_id),
            detail=f"consent={bool(consent_sms)} active={bool(active)}",
        )
    )
    db.commit()
    return flash_redirect(f"/patients/{patient_id}", "Record updated.", "ok")


# ------------------------------------------------------------------- alerts
@router.get("/alerts")
def alerts(
    request: Request,
    state: str = "open",
    severity: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    stmt = select(Alert).order_by(
        Alert.severity.asc(), Alert.created_at.desc()
    )
    if state:
        stmt = stmt.where(Alert.state == state)
    if severity:
        stmt = stmt.where(Alert.severity == severity)

    counts = {}
    for value in ("open", "acknowledged", "resolved"):
        counts[value] = db.execute(
            select(func.count(Alert.id)).where(Alert.state == value)
        ).scalar() or 0

    rows = db.execute(stmt.limit(300)).scalars().all()
    return render(
        request, db, "alerts.html", active="alerts", alerts=rows, counts=counts,
        filters={"state": state, "severity": severity},
    )


@router.post("/alerts/{alert_id}/ack")
def alert_ack(alert_id: int, db: Session = Depends(get_db), user: User = Depends(login_required)):
    alert = db.get(Alert, alert_id)
    if alert:
        alert.state = "acknowledged"
        alert.acknowledged_at = now()
        alert.handled_by = user.name
        db.add(alert)
        db.commit()
    return RedirectResponse("/alerts?state=open", status_code=303)


@router.post("/alerts/{alert_id}/resolve")
def alert_resolve(alert_id: int, db: Session = Depends(get_db), user: User = Depends(login_required)):
    alert = db.get(Alert, alert_id)
    if alert:
        alert.state = AlertState.RESOLVED.value
        alert.resolved_at = now()
        alert.handled_by = user.name
        db.add(alert)
        db.add(AuditLog(actor=user.email, action="alert.resolved", entity="alert", entity_id=str(alert_id)))
        db.commit()
    return RedirectResponse("/alerts?state=open", status_code=303)


# ----------------------------------------------------------------- messages
@router.get("/messages")
def messages(
    request: Request,
    kind: str = "",
    status: str = "",
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    stmt = select(OutboundMessage).order_by(func.coalesce(OutboundMessage.sent_at, OutboundMessage.created_at).desc())
    if kind:
        stmt = stmt.where(OutboundMessage.kind == kind)
    if status:
        stmt = stmt.where(OutboundMessage.status == status)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(OutboundMessage.body.ilike(pattern), OutboundMessage.phone.ilike(pattern)))

    rows = db.execute(stmt.limit(200)).scalars().all()

    replies = {}
    for m in rows:
        if m.patient_id and m.sent_at:
            reply = db.execute(
                select(InboundMessage)
                .where(
                    InboundMessage.patient_id == m.patient_id,
                    InboundMessage.received_at >= m.sent_at,
                    InboundMessage.received_at <= m.sent_at + timedelta(days=2),
                )
                .order_by(InboundMessage.received_at.asc())
                .limit(1)
            ).scalar_one_or_none()
            if reply:
                replies[m.id] = reply

    month_start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spend = db.execute(
        select(func.coalesce(func.sum(OutboundMessage.cost_rwf), 0.0)).where(
            OutboundMessage.sent_at.isnot(None), OutboundMessage.sent_at >= month_start
        )
    ).scalar() or 0.0
    total = db.execute(select(func.count(OutboundMessage.id))).scalar() or 0

    return render(
        request, db, "messages.html", active="messages", messages=rows, replies=replies,
        filters={"kind": kind, "status": status, "q": q}, spend=float(spend), total=total,
    )


# ---------------------------------------------------------------- protocols
@router.get("/protocols")
def protocols(
    request: Request,
    program: str = "diabetes",
    language: str = "rw",
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    rows = (
        db.execute(
            select(MessageTemplate)
            .where(MessageTemplate.program == program, MessageTemplate.language == language)
            .order_by(MessageTemplate.kind, MessageTemplate.variant)
        )
        .scalars()
        .all()
    )
    grouped: dict[str, dict] = {}
    for t in rows:
        grouped.setdefault(t.kind, {"kind": t.kind, "templates": []})
        grouped[t.kind]["templates"].append(t)

    return render(
        request, db, "protocols.html", active="protocols", grouped=grouped,
        selected={"program": program, "language": language},
    )


@router.post("/protocols/templates/{template_id}")
def update_template(
    template_id: int,
    body: str = Form(...),
    program: str = Query("diabetes"),
    language: str = Query("rw"),
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    tpl = db.get(MessageTemplate, template_id)
    if tpl:
        tpl.body = body.strip()
        tpl.updated_at = now()
        db.add(tpl)
        db.add(AuditLog(actor=user.email, action="template.updated", entity="template", entity_id=str(template_id)))
        db.commit()
    return flash_redirect(f"/protocols?program={program}&language={language}", "Template saved.", "ok")


# ---------------------------------------------------------------- simulator
@router.get("/simulator")
def simulator(
    request: Request,
    patient_id: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    patients = (
        db.execute(select(Patient).where(Patient.active.is_(True)).order_by(Patient.first_name))
        .scalars()
        .all()
    )
    recent = (
        db.execute(select(InboundMessage).order_by(InboundMessage.received_at.desc()).limit(25))
        .scalars()
        .all()
    )
    return render(
        request, db, "simulator.html", active="simulator", patients=patients,
        recent=recent, selected_id=patient_id, auto_count=12,
    )


# ------------------------------------------------------------ import/export
@router.get("/import")
def import_page(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    return render(request, db, "import.html", active="import")


@router.post("/import")
def import_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    content = file.file.read().decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    created = skipped = 0
    for row in reader:
        phone = normalize_phone(row.get("phone", ""))
        if not phone:
            skipped += 1
            continue
        exists = db.execute(select(Patient).where(Patient.phone == phone)).scalar_one_or_none()
        if exists:
            skipped += 1
            continue
        patient = Patient(
            mrn=(row.get("mrn") or "").strip(),
            first_name=(row.get("first_name") or "Unknown").strip(),
            last_name=(row.get("last_name") or "").strip(),
            phone=phone,
            language=(row.get("language") or "rw").strip()[:8],
            sex=(row.get("sex") or "unknown").strip(),
            birth_year=int(row["birth_year"]) if str(row.get("birth_year", "")).strip().isdigit() else None,
            village=(row.get("village") or "").strip(),
            consent_sms=False,
            active=True,
        )
        db.add(patient)
        db.flush()
        program = (row.get("program") or "diabetes").strip().lower()
        if program in PROGRAMS:
            db.add(
                Enrollment(
                    patient_id=patient.id, program=program,
                    medication=row.get("medication", "") or PROGRAMS[program]["default_medication"],
                )
            )
        created += 1
    db.add(AuditLog(actor=user.email, action="import.csv", detail=f"{created} created / {skipped} skipped from {file.filename}"))
    db.commit()
    return flash_redirect("/import", f"Imported {created} patients ({skipped} skipped). Consent is OFF until you enable it.", "ok")


# ------------------------------------------------------------ install / PWA
@router.get("/sw.js")
def service_worker():
    """Service worker must be served from the root to control the whole app."""
    from fastapi.responses import FileResponse

    return FileResponse(
        config.BASE_DIR / "static" / "sw.js",
        media_type="text/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@router.get("/offline")
def offline_page(request: Request):
    """Service-worker fallback shown when there is no connection."""
    from app.deps import templates

    return templates.TemplateResponse(request, "offline.html", {"request": request})


@router.get("/install")
def install_page(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    return render(request, db, "install.html", active="install")


@router.get("/download")
def download_source(db: Session = Depends(get_db), user: User = Depends(login_required)):
    """Download the whole project as a zip (no database, no .env)."""
    from fastapi.responses import FileResponse

    from app.package import build_zip

    path = build_zip()
    db.add(AuditLog(actor=user.email, action="package.downloaded"))
    db.commit()
    return FileResponse(path, filename="uburinzi-health.zip", media_type="application/zip")


# ------------------------------------------------------------------ channels
@router.get("/channels")
def channels_page(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    store = settings_store.get_all(db)
    drivers = {
        channel: {
            "name": resolve_driver_name(db, channel),
            "options": CHANNEL_DRIVER_OPTIONS[channel],
            "label": next((lbl for val, lbl in CHANNEL_DRIVER_OPTIONS[channel] if val == resolve_driver_name(db, channel)), ""),
            "live": False,
        }
        for channel in ("sms", "whatsapp", "voice")
    }
    summary = channel_summary(db)
    for channel in summary:
        drivers[channel]["live"] = summary[channel]["live"]

    calls = db.execute(select(VoiceCall).order_by(VoiceCall.created_at.desc()).limit(25)).scalars().all()
    base = (settings_store.get(db, "public_base_url") or str(request.base_url).rstrip("/")).rstrip("/")
    webhooks = {
        "sms_inbound": f"{base}/api/webhooks/sms/inbound",
        "sms_delivery": f"{base}/api/webhooks/sms/delivery",
        "whatsapp": f"{base}/api/webhooks/whatsapp",
        "voice_answer": f"{base}/api/webhooks/voice/answer",
        "voice_dtmf": f"{base}/api/webhooks/voice/dtmf",
        "voice_event": f"{base}/api/webhooks/voice/event",
    }
    return render(
        request, db, "channels.html", active="channels",
        store=store,
        api_key_masked=mask(store.get("at_api_key", "")),
        drivers=drivers,
        calls=calls,
        webhooks=webhooks,
        base_url=base,
    )


@router.post("/channels/credentials")
async def channels_credentials(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    form = await request.form()
    for key in ("at_username", "at_sender_id", "at_voice_number", "at_whatsapp_number"):
        if key in form:
            settings_store.set_value(db, key, str(form.get(key) or "").strip())
    api_key = str(form.get("at_api_key") or "").strip()
    if api_key:
        settings_store.set_value(db, "at_api_key", api_key)
    settings_store.set_value(db, "at_sandbox", "true" if form.get("at_sandbox") else "false")
    settings_store.set_value(db, "whatsapp_template", str(form.get("whatsapp_template") or "uburinzi_checkin").strip())
    settings_store.set_value(db, "voice_language", str(form.get("voice_language") or "en-US").strip())
    settings_store.set_value(db, "voice_prompt_url", str(form.get("voice_prompt_url") or "").strip())
    settings_store.set_value(db, "public_base_url", str(form.get("public_base_url") or "").strip())
    db.add(AuditLog(actor=user.email, action="channels.credentials", detail="Africa's Talking credentials updated"))
    db.commit()
    return flash_redirect("/channels", "Credentials saved (API key is encrypted at rest).", "ok")


@router.post("/channels/drivers")
async def channels_drivers(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    form = await request.form()
    for channel, key in (("sms", "sms_driver"), ("whatsapp", "whatsapp_driver"), ("voice", "voice_driver")):
        value = str(form.get(key) or "").strip()
        allowed = {v for v, _ in CHANNEL_DRIVER_OPTIONS[channel]}
        if value in allowed:
            settings_store.set_value(db, key, value)
    db.add(AuditLog(actor=user.email, action="channels.drivers", detail="channel routing updated"))
    db.commit()
    return flash_redirect("/channels", "Channel routing updated.", "ok")


@router.post("/channels/sandbox")
def channels_sandbox(
    enable: str = "true",
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    """One click: point every channel at the Africa's Talking sandbox.

    Sandbox traffic is free and carries no real SMS — paste your *sandbox* API key
    on the Channels page first (username is literally `sandbox`).
    """
    on = str(enable).strip().lower() in {"1", "true", "yes"}
    if on:
        settings_store.set_value(db, "at_sandbox", "true")
        settings_store.set_value(db, "at_username", settings_store.get(db, "at_username") or "sandbox")
        settings_store.set_value(db, "sms_driver", "africastalking")
        settings_store.set_value(db, "whatsapp_driver", "at_whatsapp")
        settings_store.set_value(db, "voice_driver", "at_voice")
        msg = "All channels switched to the Africa's Talking sandbox (free, no real SMS)."
    else:
        settings_store.set_value(db, "at_sandbox", "false")
        for key in ("sms_driver", "whatsapp_driver", "voice_driver"):
            settings_store.set_value(db, key, "simulator")
        msg = "Back to the local simulator."
    db.add(AuditLog(actor=user.email, action="channels.sandbox", detail=f"sandbox={on}"))
    db.commit()
    return flash_redirect("/channels", msg, "ok")


@router.post("/channels/policy")
async def channels_policy(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    form = await request.form()
    settings_store.set_value(db, "escalation_enabled", "true" if form.get("escalation_enabled") else "false")
    for key in ("escalate_whatsapp_after_hours", "escalate_voice_after_hours", "voice_max_per_week", "voice_max_calls_per_run"):
        value = str(form.get(key) or "").strip()
        if value.isdigit():
            settings_store.set_value(db, key, value)
    settings_store.set_value(db, "escalate_min_status", str(form.get("escalate_min_status") or "amber"))
    db.commit()
    return flash_redirect("/channels", "Escalation policy saved.", "ok")


@router.post("/patients/{patient_id}/call")
def patient_call(patient_id: int, purpose: str = "manual", db: Session = Depends(get_db), user: User = Depends(login_required)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404)
    call = place_voice_call(db, patient, purpose=purpose or "manual")
    db.add(AuditLog(actor=user.email, action="call.initiated", entity="patient", entity_id=str(patient_id)))
    db.commit()
    status = "Call queued" if call.status in ("ringing", "queued") else f"Call failed: {call.error}"
    return flash_redirect(f"/patients/{patient_id}", status, "ok" if call.status == "ringing" else "error")


# ------------------------------------------------------------------ settings
@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(login_required)):
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return render(request, db, "settings.html", active="settings", users=users)


@router.post("/settings/clinic")
def settings_clinic(
    name: str = Form(...),
    district: str = Form(""),
    country: str = Form(""),
    phone: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    clinic = db.execute(select(Clinic).limit(1)).scalar_one()
    clinic.name = name.strip()
    clinic.district = district.strip()
    clinic.country = country.strip()
    clinic.phone = phone.strip()
    db.add(clinic)
    db.commit()
    return flash_redirect("/settings", "Clinic profile saved.", "ok")


@router.post("/settings/users")
def settings_users(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("clinician"),
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
):
    if len(password) < 8:
        return flash_redirect("/settings", "Password must be at least 8 characters.", "error")
    exists = db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
    if exists:
        return flash_redirect("/settings", "That email already exists.", "error")
    db.add(
        User(
            name=name.strip(),
            email=email.strip().lower(),
            password_hash=hash_password(password),
            role=role,
        )
    )
    db.commit()
    return flash_redirect("/settings", f"User {name} added.", "ok")


@router.post("/settings/reset")
def settings_reset(db: Session = Depends(get_db), user: User = Depends(login_required)):
    from app.seed import seed_all

    db.query(InboundMessage).delete()
    db.query(OutboundMessage).delete()
    db.query(Alert).delete()
    db.query(Appointment).delete()
    db.query(Enrollment).delete()
    db.query(Patient).delete()
    db.commit()
    seed_all(db)
    db.commit()
    evaluate_all(db)
    return flash_redirect("/", "Demo data rebuilt.", "ok")

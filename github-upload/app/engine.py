"""The brain: scheduling, inbound reply handling, alert rules and daily jobs.

Everything here is rule-based and auditable — no black box. When the pilot has
enough labelled data these rules become the training set for the predictive
layer described in the roadmap (README §12).
"""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import (
    DAILY_SMS_CAP,
    SEND_WINDOW_END,
    SEND_WINDOW_START,
)
from app.messaging.gateway import get_driver, queue_message, resolve_driver_name, send_message
from app.messaging.render import render_template
from app.models import (
    Channel,
    Alert,
    AuditLog,
    AlertSeverity,
    AlertState,
    Appointment,
    Enrollment,
    InboundMessage,
    MessageKind,
    MessageStatus,
    OutboundMessage,
    Patient,
    ReplyChoice,
    VoiceCall,
)
from app import settings_store
from app.ussd import instruction as ussd_instruction
from app.messaging.drivers import get_driver as _get_channel_driver
from app.protocols import EDUCATION, PROGRAMS
from app.voice import ack_for, prompts_for
from app.timeutils import now

log = logging.getLogger("uburinzi.engine")

# ---------------------------------------------------------------- reply parsing
YES_WORDS = {"1", "yego", "y", "yes", "yeah", "oui", "ndio", "ndiyo", "ok", "okay", "yeh"}
NO_WORDS = {"2", "oya", "n", "no", "non", "hapana", "siza", "ntibishoboka"}
UNWELL_WORDS = {"3", "sindashize", "sindashize neza", "unwell", "sick", "malade", "sijisikii", "mgonjwa", "ndwaye"}
STOP_WORDS = {"stop", "hagarara", "unsubscribe", "quit", "exit", "acha", "arret", "arreter"}


def normalize_phone(raw: str, default_country: str = "250") -> str:
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("+"):
        return digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("0") and len(digits) >= 9:
        return f"+{default_country}{digits[1:]}"
    if len(digits) == 9:
        return f"+{default_country}{digits}"
    return ("+" + digits) if digits else ""


def parse_reply(text: str) -> ReplyChoice | None | str:
    """Return a ReplyChoice, the literal 'stop', or None when unrecognised."""
    cleaned = (text or "").strip().lower()
    cleaned = re.sub(r"[^\w\s\+]", "", cleaned).strip()
    if not cleaned:
        return None
    if cleaned in STOP_WORDS:
        return "stop"
    if cleaned in UNWELL_WORDS or cleaned.startswith("3"):
        return ReplyChoice.UNWELL
    if cleaned in NO_WORDS or cleaned.startswith("2"):
        return ReplyChoice.NO
    if cleaned in YES_WORDS or cleaned.startswith("1"):
        return ReplyChoice.YES
    if any(w in cleaned for w in ("sindashize", "unwell", "malade", "sijisikii", "ndwaye")):
        return ReplyChoice.UNWELL
    if any(w in cleaned for w in ("oya", "hapana", "non ", "no ")):
        return ReplyChoice.NO
    if any(w in cleaned for w in ("yego", "yes", "oui", "ndio", "ndiyo")):
        return ReplyChoice.YES
    return None


# ------------------------------------------------------------------- inbound
def _auto_ack(session, patient, choice, channel: str = "sms") -> None:
    """Send the right follow-up for a parsed reply, on the same channel it arrived on.

    Voice needs no acknowledgement — the IVR says it out loud instead.
    """
    if channel == Channel.VOICE.value:
        return
    kind = {
        ReplyChoice.YES: "ack_yes",
        ReplyChoice.NO: "ack_no",
        ReplyChoice.UNWELL: "ack_unwell",
    }.get(choice, "unknown")

    clinic = patient.clinic
    ctx = {
        "first_name": patient.first_name,
        "clinic": clinic.name if clinic else "the clinic",
        "phone": clinic.phone if clinic else "",
    }
    body = render_template(session, "common", kind, patient.language, ctx=ctx)
    msg = queue_message(
        session, patient=patient, body=body, kind=MessageKind.MANUAL.value,
        program="common", language=patient.language, channel=channel,
    )
    send_message(session, msg)


def process_inbound(
    session,
    phone: str,
    text: str,
    provider_id: str = "",
    simulated: bool = False,
    received_at: datetime | None = None,
    channel: str = Channel.SMS.value,
) -> dict:
    """Handle one incoming SMS. Idempotent on provider_id."""
    phone = normalize_phone(phone)
    if provider_id:
        dupe = session.execute(
            select(InboundMessage).where(InboundMessage.provider_id == provider_id)
        ).scalar_one_or_none()
        if dupe:
            return {"status": "duplicate", "patient_id": dupe.patient_id}

    patient = session.execute(
        select(Patient).where(Patient.phone == phone)
    ).scalar_one_or_none()

    parsed = parse_reply(text)
    inbound = InboundMessage(
        patient_id=patient.id if patient else None,
        phone=phone,
        body=(text or "")[:500],
        received_at=received_at or now(),
        choice=parsed.value if isinstance(parsed, ReplyChoice) else None,
        provider_id=provider_id or f"IN-{abs(hash((phone, text, now()))) % 10**12}",
        simulated=simulated,
        channel=channel,
    )
    session.add(inbound)
    session.flush()

    if not patient:
        log.info("inbound from unknown number %s", phone)
        return {"status": "unknown_number", "phone": phone}

    if parsed == "stop":
        patient.consent_sms = False
        patient.active = False
        body = render_template(
            session, "common", "stop", patient.language,
            ctx={"first_name": patient.first_name, "clinic": patient.clinic.name, "phone": patient.clinic.phone},
        )
        msg = queue_message(session, patient=patient, body=body, kind=MessageKind.MANUAL.value)
        send_message(session, msg)
        session.add(patient)
        return {"status": "opted_out", "patient_id": patient.id}

    updated_status = "unrecognised"
    if isinstance(parsed, ReplyChoice):
        if parsed is ReplyChoice.YES:
            patient.missed_streak = 0
            patient.no_reply_streak = 0
            updated_status = "yes"
        elif parsed is ReplyChoice.NO:
            patient.missed_streak = (patient.missed_streak or 0) + 1
            patient.no_reply_streak = 0
            updated_status = "no"
        elif parsed is ReplyChoice.UNWELL:
            patient.missed_streak = (patient.missed_streak or 0) + 1
            patient.no_reply_streak = 0
            updated_status = "unwell"
            open_alert(
                session,
                patient,
                rule="reported_unwell",
                severity=AlertSeverity.RED,
                message=f"{patient.full_name} reported not feeling well by {channel.upper()}. Call back today.",
            )
        patient.last_contact_at = inbound.received_at
        # A USSD session already ends with its own confirmation screen, so no
        # acknowledgement is sent back over a billable channel.
        if channel != Channel.USSD.value:
            _auto_ack(session, patient, parsed, channel)
    else:
        if channel != Channel.USSD.value:
            _auto_ack(session, patient, None, channel)

    session.add(patient)
    evaluate_patient(session, patient)
    session.commit()
    return {"status": updated_status, "patient_id": patient.id, "choice": getattr(parsed, "value", parsed)}


# --------------------------------------------------------------------- alerts
def open_alert(session, patient, rule: str, severity: AlertSeverity, message: str) -> Alert:
    existing = session.execute(
        select(Alert).where(
            Alert.patient_id == patient.id,
            Alert.rule == rule,
            Alert.state != AlertState.RESOLVED.value,
        )
    ).scalar_one_or_none()
    if existing:
        existing.message = message
        existing.severity = severity.value
        session.add(existing)
        return existing
    alert = Alert(
        patient_id=patient.id,
        rule=rule,
        severity=severity.value,
        state=AlertState.OPEN.value,
        message=message,
    )
    session.add(alert)
    session.flush()
    return alert


def _consecutive_unanswered_checkins(session, patient) -> int:
    """Count trailing check-in SMS that never received any reply."""
    recent = (
        session.execute(
            select(OutboundMessage)
            .where(
                OutboundMessage.patient_id == patient.id,
                OutboundMessage.kind == MessageKind.CHECKIN.value,
                OutboundMessage.sent_at.isnot(None),
            )
            .order_by(OutboundMessage.sent_at.desc())
            .limit(6)
        )
        .scalars()
        .all()
    )
    streak = 0
    for msg in recent:
        replied = session.execute(
            select(func.count(InboundMessage.id)).where(
                InboundMessage.patient_id == patient.id,
                InboundMessage.received_at >= msg.sent_at,
            )
        ).scalar()
        if replied:
            break
        streak += 1
    return streak


def evaluate_patient(session, patient) -> str:
    """Apply every rule, reconcile open alerts, and cache the traffic-light status."""
    rules: list[tuple[str, str, str]] = []  # (rule, severity, message)

    for enr in patient.enrollments:
        if not enr.active:
            continue
        spec = PROGRAMS.get(enr.program, {})
        missed = patient.missed_streak or 0
        label = spec.get("short", enr.program)

        if missed >= spec.get("missed_dose_red", 3):
            rules.append((
                f"medication_nonadherence:{enr.program}",
                AlertSeverity.RED.value,
                f"{label}: {missed} consecutive missed doses reported. Needs same-day follow-up call.",
            ))
        elif missed >= spec.get("missed_dose_amber", 2):
            rules.append((
                f"medication_nonadherence:{enr.program}",
                AlertSeverity.AMBER.value,
                f"{label}: {missed} missed doses reported. Schedule a counselling call.",
            ))
        else:
            # streak cleared → auto-resolve the matching alert
            open_alert_row = session.execute(
                select(Alert).where(
                    Alert.patient_id == patient.id,
                    Alert.rule == f"medication_nonadherence:{enr.program}",
                    Alert.state != AlertState.RESOLVED.value,
                )
            ).scalar_one_or_none()
            if open_alert_row:
                open_alert_row.state = AlertState.RESOLVED.value
                open_alert_row.resolved_at = now()
                open_alert_row.note = "Auto-resolved: patient reported taking medication."
                session.add(open_alert_row)

    # silence detection
    unanswered = _consecutive_unanswered_checkins(session, patient)
    patient.no_reply_streak = unanswered
    if unanswered >= 3:
        rules.append((
            "silent_patient",
            AlertSeverity.AMBER.value,
            f"No reply to the last {unanswered} check-ins. Confirm the phone number still works.",
        ))

    # appointments
    missed_appts = [
        a for a in patient.appointments if a.status == "missed"
    ]
    if missed_appts:
        severity = AlertSeverity.RED.value if len(missed_appts) >= 2 else AlertSeverity.AMBER.value
        rules.append((
            "missed_appointment",
            severity,
            f"{len(missed_appts)} missed appointment(s). Rebook and confirm by SMS.",
        ))

    upcoming = [
        a for a in patient.appointments
        if a.status == "upcoming" and not a.confirmed and a.due_at <= now() + timedelta(days=3)
    ]
    if upcoming:
        rules.append((
            "appointment_confirm",
            AlertSeverity.INFO.value,
            f"Appointment on {upcoming[0].due_at.strftime('%d %b')} is unconfirmed.",
        ))

    for rule, severity, message in rules:
        open_alert(session, patient, rule,
                   AlertSeverity(severity), message)

    # resolve stale rules that no longer fire
    firing = {r for r, _, _ in rules}
    for alert in patient.alerts:
        if alert.state == AlertState.RESOLVED.value:
            continue
        if alert.rule in ("silent_patient", "missed_appointment", "appointment_confirm") and alert.rule not in firing:
            alert.state = AlertState.RESOLVED.value
            alert.resolved_at = now()
            alert.note = "Auto-resolved by daily sweep."
            session.add(alert)

    # cached traffic light
    live = [a for a in patient.alerts if a.state != AlertState.RESOLVED.value]
    if any(a.severity == AlertSeverity.RED.value for a in live):
        patient.status = "red"
    elif live:
        patient.status = "amber"
    else:
        patient.status = "green"
    session.add(patient)
    return patient.status


def evaluate_all(session) -> int:
    patients = session.execute(select(Patient).where(Patient.active.is_(True))).scalars().all()
    for p in patients:
        evaluate_patient(session, p)
    session.commit()
    return len(patients)


# ------------------------------------------------------------------ scheduling
def _within_window(dt: datetime) -> bool:
    return SEND_WINDOW_START <= dt.hour < SEND_WINDOW_END


def _sent_today(session) -> int:
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    return session.execute(
        select(func.count(OutboundMessage.id)).where(
            OutboundMessage.sent_at.isnot(None),
            OutboundMessage.sent_at >= start,
        )
    ).scalar() or 0


def _already_queued(session, dedupe_key: str) -> bool:
    return session.execute(
        select(func.count(OutboundMessage.id)).where(OutboundMessage.dedupe_key == dedupe_key)
    ).scalar() > 0


_REPLY_ASK_RE = re.compile(
    r"\s*(?:Subiza|Reply|Répondez|Repondez|Jibu)\b[^.]*\.?\s*$", re.IGNORECASE
)


def _append_reply_instruction(session, body: str, patient) -> str:
    """Tell the patient how to answer.

    In Rwanda (and Uganda, Bangladesh, Thailand, Vietnam, Japan) an A2P SMS
    cannot be replied to, so "Subiza: 1=Yego..." is a dead end. When USSD is the
    configured reply path we swap in the dial instruction instead -- but only if
    it keeps the message inside one 160-character segment.
    """
    if settings_store.get(session, "reply_channel", "sms") != "ussd":
        return body
    if not ussd_instruction(session, patient):
        return body

    # Drop the "Reply 1=Yes, 2=No…" tail first: in a market without inbound A2P
    # it is a dead end, and removing it usually keeps us inside one segment.
    stripped = _REPLY_ASK_RE.sub("", body).rstrip()
    for candidate in (
        f"{stripped} {ussd_instruction(session, patient)}",
        f"{stripped} {ussd_instruction(session, patient, short=True)}",
        f"{body} {ussd_instruction(session, patient, short=True)}",
    ):
        if len(candidate) <= 160:
            return candidate
    return body


def build_due_messages(session, at: datetime | None = None) -> list[OutboundMessage]:
    """Work out which protocol messages are due right now and queue them."""
    at = at or now()
    created: list[OutboundMessage] = []

    enrollments = (
        session.execute(
            select(Enrollment).where(Enrollment.active.is_(True))
        )
        .scalars()
        .all()
    )

    for enr in enrollments:
        patient = enr.patient
        if not patient or not patient.active or not patient.consent_sms:
            continue
        spec = PROGRAMS.get(enr.program)
        if not spec:
            continue
        clinic = patient.clinic
        ctx = {
            "first_name": patient.first_name,
            "clinic": clinic.name if clinic else "the clinic",
            "phone": clinic.phone if clinic else "",
            "condition": spec.get("label", enr.program),
            "medication": enr.medication or spec.get("default_medication", ""),
        }

        # --- medication check-in ------------------------------------------------
        # First check-in lands one day after enrolment (confirm the patient started
        # the regimen), then the programme cadence takes over.
        if enr.last_checkin_at is None:
            checkin_due = at >= enr.started_at + timedelta(days=1)
        else:
            checkin_due = at - enr.last_checkin_at >= timedelta(days=spec["cadence_days"])
        if checkin_due:
            key = f"checkin:{enr.id}:{at.date().isoformat()}"
            if not _already_queued(session, key):
                body = render_template(session, enr.program, "checkin", patient.language, ctx=ctx)
                body = _append_reply_instruction(session, body, patient)
                msg = queue_message(
                    session, patient=patient, body=body,
                    kind=MessageKind.CHECKIN.value, program=enr.program,
                    language=patient.language, enrollment=enr, dedupe_key=key,
                )
                enr.last_checkin_at = at
                session.add(enr)
                created.append(msg)

        # --- education / lifestyle tip ------------------------------------------
        last_edu = enr.last_education_at or enr.started_at
        if at - last_edu >= timedelta(days=spec["education_every_days"]):
            key = f"edu:{enr.id}:{at.date().isoformat()}"
            if not _already_queued(session, key):
                tips = EDUCATION.get(enr.program, {}).get(patient.language) or EDUCATION.get(enr.program, {}).get("en", [])
                index = (enr.education_index or 0) % max(len(tips), 1)
                variant = f"tip{index + 1}"
                body = render_template(session, enr.program, "education", patient.language, variant=variant, ctx=ctx)
                if tips and body.strip() and body not in [m.body for m in created]:
                    msg = queue_message(
                        session, patient=patient, body=body,
                        kind=MessageKind.EDUCATION.value, program=enr.program,
                        language=patient.language, enrollment=enr, dedupe_key=key,
                    )
                    enr.education_index = (enr.education_index or 0) + 1
                    enr.last_education_at = at
                    session.add(enr)
                    created.append(msg)

    # --- appointment reminders ---------------------------------------------------
    reminders = (
        session.execute(
            select(Appointment).where(
                Appointment.status == "upcoming",
                Appointment.reminder_sent_at.is_(None),
                Appointment.due_at <= at + timedelta(days=3),
            )
        )
        .scalars()
        .all()
    )
    for appt in reminders:
        patient = appt.patient
        if not patient or not patient.active or not patient.consent_sms:
            continue
        key = f"appt:{appt.id}"
        if _already_queued(session, key):
            continue
        clinic = patient.clinic
        ctx = {
            "first_name": patient.first_name,
            "clinic": clinic.name if clinic else "the clinic",
            "phone": clinic.phone if clinic else "",
            "date": appt.due_at.strftime("%d/%m/%Y"),
            "time": appt.due_at.strftime("%H:%M"),
        }
        body = render_template(session, "common", "appointment", patient.language, ctx=ctx)
        msg = queue_message(
            session, patient=patient, body=body,
            kind=MessageKind.APPOINTMENT.value, program="common",
            language=patient.language, dedupe_key=key,
        )
        appt.reminder_sent_at = now()
        session.add(appt)
        created.append(msg)

    session.commit()
    return created


def run_scheduler(session, at: datetime | None = None, force: bool = False) -> dict:
    """Queue due protocol messages, then send what is inside the sending window."""
    at = at or now()
    due = build_due_messages(session, at=at)

    sent = failed = skipped = 0
    if force or _within_window(at):
        # `force` overrides the quiet-hours window only -- never the daily spend
        # cap, which is the guard that stops a manual run from draining credit.
        remaining = DAILY_SMS_CAP - _sent_today(session)
        for msg in due:
            if remaining <= 0:
                skipped += 1
                continue
            try:
                send_message(session, msg)
                if msg.status in (MessageStatus.SENT.value, MessageStatus.DELIVERED.value):
                    sent += 1
                    remaining -= 1
                else:
                    failed += 1
            except IntegrityError:  # another worker already sent this dedupe key
                session.rollback()
                continue
        session.commit()
    else:
        skipped = len(due)

    process_due_simulated_replies(session)
    return {"queued": len(due), "sent": sent, "failed": failed, "window_skipped": skipped}


def process_due_simulated_replies(session) -> int:
    """Simulator only: turn queued synthetic replies into real inbound traffic."""
    sim_channels = [
        channel
        for channel in (Channel.SMS.value, Channel.WHATSAPP.value, Channel.VOICE.value)
        if resolve_driver_name(session, channel) == "simulator"
    ]
    if not sim_channels:
        return 0
    due = (
        session.execute(
            select(OutboundMessage).where(
                OutboundMessage.sim_reply_due_at.isnot(None),
                OutboundMessage.sim_reply_processed.is_(False),
                OutboundMessage.sim_reply_due_at <= now(),
                OutboundMessage.channel.in_(sim_channels),
            )
        )
        .scalars()
        .all()
    )
    import random

    count = 0
    for msg in due:
        msg.sim_reply_processed = True
        session.add(msg)
        patient = msg.patient
        if not patient:
            continue
        roll = random.random()
        adherence = patient.sim_adherence or 0.8
        if roll < adherence:
            text = "1"
        elif roll < adherence + (1 - adherence) * 0.85:
            text = "2"
        else:
            text = "3"

        if msg.channel == Channel.VOICE.value:
            _complete_simulated_call(session, msg, text)
        else:
            process_inbound(
                session,
                phone=patient.phone,
                text=text,
                provider_id=f"SIMREPLY-{msg.id}",
                simulated=True,
                received_at=msg.sim_reply_due_at,
                channel=msg.channel,
            )
        count += 1
    session.commit()
    return count


def _complete_simulated_call(session, msg: OutboundMessage, digit: str) -> None:
    """Simulator: the patient answered and pressed a key."""
    call = (
        session.execute(
            select(VoiceCall).where(VoiceCall.outbound_id == msg.id)
        )
        .scalar_one_or_none()
    )
    answered_at = msg.sim_reply_due_at or now()
    if call:
        call.status = "completed"
        call.answered_at = answered_at
        call.ended_at = answered_at + timedelta(seconds=random.randint(12, 45))
        call.duration_seconds = int((call.ended_at - answered_at).total_seconds())
        call.dtmf_digits = digit
        call.cost_rwf = round(call.duration_seconds / 60.0 * 60.0, 2)
        session.add(call)
    process_inbound(
        session,
        phone=msg.phone,
        text=digit,
        provider_id=f"SIMDTMF-{msg.id}",
        simulated=True,
        received_at=answered_at,
        channel=Channel.VOICE.value,
    )


# --------------------------------------------------------------------- voice
def place_voice_call(session, patient, purpose: str = "checkin", program: str = "common") -> VoiceCall:
    """Initiate an IVR check-in call. The script itself is served by the webhook."""
    from app.messaging.gateway import queue_message as _queue

    clinic = patient.clinic
    greeting, digits_prompt, goodbye = prompts_for(
        patient.language, patient.first_name, (clinic.name if clinic else "the clinic")
    )
    # A patient may be called more than once a week (voice_max_per_week can be > 1),
    # so the dedupe key carries the attempt number -- otherwise the second call of
    # the week collides on outbound_messages.dedupe_key and 500s.
    week_ago = now() - timedelta(days=7)
    prior = session.execute(
        select(func.count(VoiceCall.id)).where(
            VoiceCall.patient_id == patient.id, VoiceCall.created_at >= week_ago
        )
    ).scalar() or 0
    attempt_no = int(prior) + 1
    msg = _queue(
        session,
        patient=patient,
        body=" ".join([greeting, digits_prompt]),
        kind=MessageKind.CHECKIN.value,
        program=program,
        language=patient.language,
        channel=Channel.VOICE.value,
        dedupe_key=f"voice:{patient.id}:{now().date().isoformat()}:{purpose}:{attempt_no}",
    )
    call = VoiceCall(
        patient_id=patient.id,
        outbound_id=msg.id,
        phone=patient.phone,
        purpose=purpose,
        status="queued",
        provider=resolve_driver_name(session, Channel.VOICE.value),
        simulated=resolve_driver_name(session, Channel.VOICE.value) == "simulator",
        attempt_no=attempt_no,
    )
    session.add(call)
    session.flush()

    send_message(session, msg)
    call.provider = msg.provider
    call.session_id = msg.provider_id
    call.status = "ringing" if msg.status in (MessageStatus.SENT.value, MessageStatus.DELIVERED.value) else "failed"
    call.error = msg.error
    session.add(call)
    session.commit()
    return call


def _last_reply_at(session, patient) -> datetime | None:
    row = (
        session.execute(
            select(InboundMessage.received_at)
            .where(InboundMessage.patient_id == patient.id)
            .order_by(InboundMessage.received_at.desc())
            .limit(1)
        )
        .scalar_one_or_none()
    )
    return row


def _pending_checkins(session, patient, older_than_hours: float) -> list[OutboundMessage]:
    """Check-ins sent more than N hours ago that never got any reply."""
    cutoff = now() - timedelta(hours=older_than_hours)
    msgs = (
        session.execute(
            select(OutboundMessage)
            .where(
                OutboundMessage.patient_id == patient.id,
                OutboundMessage.kind == MessageKind.CHECKIN.value,
                OutboundMessage.sent_at.isnot(None),
                OutboundMessage.sent_at <= cutoff,
            )
            .order_by(OutboundMessage.sent_at.desc())
            .limit(3)
        )
        .scalars()
        .all()
    )
    unanswered = []
    for m in msgs:
        replied = session.execute(
            select(func.count(InboundMessage.id)).where(
                InboundMessage.patient_id == patient.id,
                InboundMessage.received_at >= m.sent_at,
            )
        ).scalar()
        if not replied:
            unanswered.append(m)
    return unanswered


def _already_escalated(session, dedupe_key: str) -> bool:
    sent = (
        session.execute(
            select(func.count(OutboundMessage.id)).where(OutboundMessage.dedupe_key == dedupe_key)
        ).scalar()
        or 0
    )
    if sent:
        return True
    # Steps that produce no outbound message (e.g. a manual callback task)
    # record their dedupe key in the audit log instead.
    logged = (
        session.execute(
            select(func.count(AuditLog.id)).where(AuditLog.action == "escalation", AuditLog.detail == dedupe_key)
        ).scalar()
        or 0
    )
    return bool(logged)


def _mark_escalated(session, dedupe_key: str, note: str = "") -> None:
    """Record that a non-message escalation step happened, so it is not repeated."""
    session.add(AuditLog(action="escalation", entity="patient", detail=dedupe_key + (f" | {note}" if note else "")))


def _voice_available(session) -> bool:
    """True when this deployment can actually place automated calls.

    Africa's Talking publishes no Voice product for Rwanda (only SMS and USSD),
    so the ladder must degrade to a human callback there instead of failing.
    """
    if resolve_driver_name(session, Channel.VOICE.value) == "simulator":
        return False
    return settings_store.get_bool(session, "voice_enabled")


def run_escalations(session) -> dict:
    """SMS → WhatsApp → voice escalation for at-risk patients who go silent.

    Safety rails: only patients flagged amber/red, quiet hours respected, a
    weekly cap on calls, and one attempt per unanswered check-in.
    """
    from app.messaging.gateway import queue_message as _queue

    if not settings_store.get_bool(session, "escalation_enabled"):
        return {"skipped": True, "reason": "disabled"}

    if not _within_window(now()):
        return {"skipped": True, "reason": "outside sending window"}

    wa_after = settings_store.get_int(session, "escalate_whatsapp_after_hours") or 24
    voice_after = settings_store.get_int(session, "escalate_voice_after_hours") or 48
    min_status = settings_store.get(session, "escalate_min_status", "amber") or "amber"
    weekly_cap = settings_store.get_int(session, "voice_max_per_week") or 2
    max_calls = settings_store.get_int(session, "voice_max_calls_per_run") or 5

    # Escalate flagged patients *and* patients who have gone quiet on us.
    candidates = (
        session.execute(select(Patient).where(Patient.active.is_(True), Patient.consent_sms.is_(True)))
        .scalars()
        .all()
    )
    status_ok = ["red"] if min_status == "red" else ["amber", "red"]
    patients = [
        p
        for p in candidates
        if p.status in status_ok or (p.no_reply_streak or 0) >= 2 or (p.missed_streak or 0) >= 1
    ]

    whatsapp_sent = calls_placed = callbacks_created = 0
    for patient in patients:
        # ---- WhatsApp nudge ---------------------------------------------------
        pending = _pending_checkins(session, patient, wa_after)
        for msg in pending[:1]:
            key = f"esc:wa:{msg.id}"
            if _already_escalated(session, key):
                continue
            body = render_template(
                session, msg.program, "checkin", patient.language,
                ctx={
                    "first_name": patient.first_name,
                    "clinic": patient.clinic.name if patient.clinic else "the clinic",
                    "phone": patient.clinic.phone if patient.clinic else "",
                    "condition": PROGRAMS.get(msg.program, {}).get("label", msg.program),
                    "medication": msg.body[:0] or PROGRAMS.get(msg.program, {}).get("default_medication", ""),
                },
            )
            nudge = _queue(
                session,
                patient=patient,
                body=body,
                kind=MessageKind.CHECKIN.value,
                program=msg.program,
                language=patient.language,
                channel=Channel.WHATSAPP.value,
                dedupe_key=key,
                template_hint=_template_hint_for(session, patient, msg),
            )
            send_message(session, nudge)
            if nudge.status != MessageStatus.FAILED.value:
                whatsapp_sent += 1

        # ---- Voice call -------------------------------------------------------
        if calls_placed >= max_calls:
            continue
        pending_voice = _pending_checkins(session, patient, voice_after)
        if not pending_voice:
            continue
        if patient.status != "red" and (patient.missed_streak or 0) < 1 and (patient.no_reply_streak or 0) < 2:
            continue
        msg = pending_voice[0]
        key = f"esc:voice:{msg.id}"
        if _already_escalated(session, key):
            continue

        # Some markets have no automated voice at all -- AT lists Rwanda as
        # "SMS (Bulk & Short Code), USSD", with no Voice product. Rather than
        # failing silently, hand the patient to the clinic as a callback task.
        if not _voice_available(session):
            task = Alert(
                patient_id=patient.id,
                rule="callback",
                severity=AlertSeverity.RED.value,
                message=(
                    f"No automated voice in this market — please phone {patient.first_name} "
                    f"{patient.last_name} on {patient.phone} directly (no reply for "
                    f"{voice_after}h)."
                ),
            )
            session.add(task)
            session.flush()
            callbacks_created += 1
            _mark_escalated(session, key)
            continue
        week_ago = now() - timedelta(days=7)
        calls_this_week = (
            session.execute(
                select(func.count(VoiceCall.id)).where(
                    VoiceCall.patient_id == patient.id, VoiceCall.created_at >= week_ago
                )
            ).scalar()
            or 0
        )
        if calls_this_week >= weekly_cap:
            continue
        call = VoiceCall(
            patient_id=patient.id,
            phone=patient.phone,
            purpose="escalation",
            status="queued",
            provider=resolve_driver_name(session, Channel.VOICE.value),
            simulated=resolve_driver_name(session, Channel.VOICE.value) == "simulator",
        )
        session.add(call)
        session.flush()
        escalated = _queue(
            session,
            patient=patient,
            body=" ".join(prompts_for(patient.language, patient.first_name,
                                      patient.clinic.name if patient.clinic else "the clinic")[:2]),
            kind=MessageKind.CHECKIN.value,
            program=msg.program,
            language=patient.language,
            channel=Channel.VOICE.value,
            dedupe_key=key,
        )
        send_message(session, escalated)
        call.outbound_id = escalated.id
        call.provider = escalated.provider
        call.session_id = escalated.provider_id
        call.status = "ringing" if escalated.status != MessageStatus.FAILED.value else "failed"
        call.error = escalated.error
        session.add(call)
        if call.status == "ringing":
            calls_placed += 1

    session.commit()
    return {
        "whatsapp_sent": whatsapp_sent,
        "voice_calls": calls_placed,
        "callback_tasks": callbacks_created,
        "patients_considered": len(patients),
    }


def _template_hint_for(session, patient, msg) -> dict | None:
    """WhatsApp requires an approved template outside the 24-hour session window."""
    last_reply = _last_reply_at(session, patient)
    window_open = bool(last_reply and (now() - last_reply) < timedelta(hours=24))
    if window_open:
        return None
    template = settings_store.get(session, "whatsapp_template", "uburinzi_checkin") or "uburinzi_checkin"
    return {
        "name": template,
        "language": "en",
        "category": "UTILITY",
        "components": {
            "body": {
                "type": "BODY",
                "text": "Hello {{1}}, this is {{2}} checking on your medication. Reply 1=yes, 2=no, 3=unwell.",
                "example": {"body_text": [patient.first_name, patient.clinic.name if patient.clinic else "the clinic"]},
            }
        },
    }


# ------------------------------------------------------------------ daily jobs
def run_daily_jobs(session) -> dict:
    """Sweep that runs once a day: close out appointments, refresh risk, roll up metrics."""
    at = now()
    missed = 0
    stale = (
        session.execute(
            select(Appointment).where(
                Appointment.status == "upcoming",
                Appointment.due_at < at - timedelta(days=1),
            )
        )
        .scalars()
        .all()
    )
    for appt in stale:
        appt.status = "missed"
        session.add(appt)
        missed += 1
    session.commit()

    from app.metrics import rollup_day

    evaluated = evaluate_all(session)
    rollup_day(session, at.date())
    escalations = run_escalations(session)
    return {
        "appointments_marked_missed": missed,
        "patients_evaluated": evaluated,
        **{f"escalation_{k}": v for k, v in escalations.items()},
    }


def send_manual_message(session, patient, body: str) -> OutboundMessage:
    msg = queue_message(
        session, patient=patient, body=body, kind=MessageKind.MANUAL.value,
        program="common", language=patient.language,
    )
    session.commit()
    return send_message(session, msg)


def enroll_patient(session, patient, program: str, medication: str = "") -> Enrollment:
    """Start (or restart) a programme, send the welcome SMS and first check-in."""
    enr = session.execute(
        select(Enrollment).where(
            Enrollment.patient_id == patient.id, Enrollment.program == program
        )
    ).scalar_one_or_none()
    if enr is None:
        enr = Enrollment(patient_id=patient.id, program=program)
    enr.active = True
    enr.medication = medication or PROGRAMS.get(program, {}).get("default_medication", "")
    enr.started_at = now()
    enr.last_checkin_at = None
    session.add(enr)
    session.flush()

    clinic = patient.clinic
    ctx = {
        "first_name": patient.first_name,
        "clinic": clinic.name if clinic else "the clinic",
        "phone": clinic.phone if clinic else "",
        "condition": PROGRAMS.get(program, {}).get("label", program),
        "medication": enr.medication,
    }
    welcome = render_template(session, "common", "welcome", patient.language, ctx=ctx)
    msg = queue_message(
        session, patient=patient, body=welcome, kind=MessageKind.WELCOME.value,
        program=program, language=patient.language,
    )
    send_message(session, msg)
    session.commit()
    return enr

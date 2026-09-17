"""Numbers that matter to a clinician, a clinic manager and an investor."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from app.config import SMS_COST_RWF
from app.models import (
    Alert,
    AlertState,
    Appointment,
    CohortMetric,
    Enrollment,
    InboundMessage,
    MessageKind,
    OutboundMessage,
    Patient,
)
from app.protocols import PROGRAMS, PROGRAM_KEYS
from app.timeutils import now

WHO_BASELINE_ADHERENCE = 0.50  # WHO: chronic-disease adherence in LMICs sits below 50%
BASELINE_NO_SHOW = 0.30        # typical follow-up no-show rate quoted in the application


def _window_start(days: int):
    return now() - timedelta(days=days)


def _checkins_in(session, start, end=None):
    rows = (
        session.execute(
            select(OutboundMessage).where(
                OutboundMessage.kind == MessageKind.CHECKIN.value,
                OutboundMessage.sent_at.isnot(None),
                OutboundMessage.sent_at >= start,
            )
        )
        .scalars()
        .all()
    )
    if end:
        rows = [r for r in rows if r.sent_at <= end]
    return rows


def adherence_stats(session, days: int = 30) -> dict:
    start = _window_start(days)
    checkins = _checkins_in(session, start)
    sent = len(checkins)
    by_patient: dict[int, list] = {}
    for c in checkins:
        by_patient.setdefault(c.patient_id, []).append(c)

    replies = yes = no = unwell = 0
    for pid, msgs in by_patient.items():
        for m in msgs:
            reply = (
                session.execute(
                    select(InboundMessage)
                    .where(
                        InboundMessage.patient_id == pid,
                        InboundMessage.received_at >= m.sent_at,
                        InboundMessage.received_at <= m.sent_at + timedelta(days=2),
                    )
                    .order_by(InboundMessage.received_at.asc())
                    .limit(1)
                )
                .scalar_one_or_none()
            )
            if not reply or not reply.choice:
                continue
            replies += 1
            if reply.choice == "yes":
                yes += 1
            elif reply.choice == "no":
                no += 1
            else:
                unwell += 1

    adherence = (yes / replies) if replies else 0.0
    response_rate = (replies / sent) if sent else 0.0
    return {
        "checkins_sent": sent,
        "replies": replies,
        "yes": yes,
        "no": no,
        "unwell": unwell,
        "response_rate": response_rate,
        "adherence_rate": adherence,
        "patients_reached": len(by_patient),
    }


def daily_series(session, days: int = 30) -> list[dict]:
    start = _window_start(days).date()
    checkins = _checkins_in(session, _window_start(days))
    per_day: dict[date, dict] = {}
    for i in range(days):
        d = start + timedelta(days=i)
        per_day[d] = {"day": d, "sent": 0, "replies": 0, "yes": 0, "adherence": None}

    for c in checkins:
        d = c.sent_at.date()
        if d in per_day:
            per_day[d]["sent"] += 1
            reply = (
                session.execute(
                    select(InboundMessage)
                    .where(
                        InboundMessage.patient_id == c.patient_id,
                        InboundMessage.received_at >= c.sent_at,
                        InboundMessage.received_at <= c.sent_at + timedelta(days=2),
                    )
                    .order_by(InboundMessage.received_at.asc())
                    .limit(1)
                )
                .scalar_one_or_none()
            )
            if reply and reply.choice:
                per_day[d]["replies"] += 1
                if reply.choice == "yes":
                    per_day[d]["yes"] += 1

    out = []
    for d in sorted(per_day):
        row = per_day[d]
        row["adherence"] = (row["yes"] / row["replies"]) if row["replies"] else None
        out.append(row)
    return out


def program_breakdown(session, days: int = 30) -> list[dict]:
    start = _window_start(days)
    rows = []
    for key in PROGRAM_KEYS:
        spec = PROGRAMS[key]
        patients = (
            session.execute(
                select(func.count(Enrollment.id)).where(
                    Enrollment.program == key, Enrollment.active.is_(True)
                )
            ).scalar()
            or 0
        )
        sent = (
            session.execute(
                select(func.count(OutboundMessage.id)).where(
                    OutboundMessage.program == key,
                    OutboundMessage.sent_at.isnot(None),
                    OutboundMessage.sent_at >= start,
                )
            ).scalar()
            or 0
        )
        rows.append(
            {
                "key": key,
                "label": spec["label"],
                "short": spec["short"],
                "color": spec["color"],
                "patients": patients,
                "messages": sent,
                "cadence": spec["cadence_days"],
            }
        )
    return rows


def dashboard_stats(session, days: int = 30) -> dict:
    active_patients = (
        session.execute(select(func.count(Patient.id)).where(Patient.active.is_(True))).scalar() or 0
    )
    total_patients = session.execute(select(func.count(Patient.id))).scalar() or 0
    status_counts = {"red": 0, "amber": 0, "green": 0}
    for value, count in session.execute(
        select(Patient.status, func.count(Patient.id)).where(Patient.active.is_(True)).group_by(Patient.status)
    ):
        status_counts[value] = count

    open_alerts = (
        session.execute(
            select(func.count(Alert.id)).where(Alert.state != AlertState.RESOLVED.value)
        ).scalar()
        or 0
    )
    alert_mix = {"red": 0, "amber": 0, "info": 0}
    for value, count in session.execute(
        select(Alert.severity, func.count(Alert.id))
        .where(Alert.state != AlertState.RESOLVED.value)
        .group_by(Alert.severity)
    ):
        alert_mix[value] = count

    start = _window_start(days)
    messages_30 = (
        session.execute(
            select(func.count(OutboundMessage.id)).where(
                OutboundMessage.sent_at.isnot(None), OutboundMessage.sent_at >= start
            )
        ).scalar()
        or 0
    )
    cost = (
        session.execute(
            select(func.coalesce(func.sum(OutboundMessage.cost_rwf), 0.0)).where(
                OutboundMessage.sent_at.isnot(None), OutboundMessage.sent_at >= start
            )
        ).scalar()
        or 0.0
    )

    appts_upcoming = (
        session.execute(
            select(func.count(Appointment.id)).where(
                Appointment.status == "upcoming", Appointment.due_at >= now()
            )
        ).scalar()
        or 0
    )
    appts_missed = (
        session.execute(
            select(func.count(Appointment.id)).where(
                Appointment.status == "missed", Appointment.due_at >= start
            )
        ).scalar()
        or 0
    )
    appts_total = (
        session.execute(
            select(func.count(Appointment.id)).where(Appointment.due_at >= start)
        ).scalar()
        or 0
    )
    no_show_rate = (appts_missed / appts_total) if appts_total else 0.0

    adh = adherence_stats(session, days)
    uplift = adh["adherence_rate"] - WHO_BASELINE_ADHERENCE

    return {
        "days": days,
        "total_patients": total_patients,
        "active_patients": active_patients,
        "status_counts": status_counts,
        "open_alerts": open_alerts,
        "alert_mix": alert_mix,
        "messages_sent": messages_30,
        "cost_rwf": round(float(cost), 2),
        "cost_per_patient": round(float(cost) / active_patients, 2) if active_patients else 0.0,
        "appointments_upcoming": appts_upcoming,
        "appointments_missed": appts_missed,
        "no_show_rate": no_show_rate,
        "baseline_no_show": BASELINE_NO_SHOW,
        "adherence": adh,
        "baseline_adherence": WHO_BASELINE_ADHERENCE,
        "adherence_uplift": uplift,
        "series": daily_series(session, days),
        "programs": program_breakdown(session, days),
    }


def rollup_day(session, day: date) -> None:
    """Persist a daily cohort row (used by the impact report / CSV export)."""
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    checkins = [c for c in _checkins_in(session, start) if c.sent_at < end]
    replies = yes = no = unwell = 0
    for c in checkins:
        reply = (
            session.execute(
                select(InboundMessage)
                .where(
                    InboundMessage.patient_id == c.patient_id,
                    InboundMessage.received_at >= c.sent_at,
                    InboundMessage.received_at <= c.sent_at + timedelta(days=2),
                )
                .order_by(InboundMessage.received_at.asc())
                .limit(1)
            )
            .scalar_one_or_none()
        )
        if reply and reply.choice:
            replies += 1
            yes += reply.choice == "yes"
            no += reply.choice == "no"
            unwell += reply.choice == "unwell"

    active = session.execute(
        select(func.count(Patient.id)).where(Patient.active.is_(True))
    ).scalar() or 0

    def upsert(program: str, sent_count: int, r: int, y: int, n: int, u: int) -> None:
        row = session.execute(
            select(CohortMetric).where(CohortMetric.day == day, CohortMetric.program == program)
        ).scalar_one_or_none()
        if row is None:
            row = CohortMetric(day=day, program=program)
            session.add(row)
        row.active_patients = active
        row.checkins_sent = sent_count
        row.replies = r
        row.yes = y
        row.no = n
        row.unwell = u

    upsert("all", len(checkins), replies, yes, no, unwell)
    for key in PROGRAM_KEYS:
        sub = [c for c in checkins if c.program == key]
        upsert(key, len(sub), 0, 0, 0, 0)
    session.commit()


def impact_report(session, days: int = 30) -> dict:
    """The numbers that go into the timbuktoo application and donor reports."""
    stats = dashboard_stats(session, days)
    adh = stats["adherence"]
    doses_taken = adh["yes"]
    episodes_flagged = stats["alert_mix"]["red"] + stats["alert_mix"]["amber"]
    return {
        "period_days": days,
        "patients_monitored": stats["active_patients"],
        "checkins_sent": adh["checkins_sent"],
        "patient_replies": adh["replies"],
        "response_rate": adh["response_rate"],
        "adherence_rate": adh["adherence_rate"],
        "baseline_adherence": WHO_BASELINE_ADHERENCE,
        "adherence_uplift_pp": round((adh["adherence_rate"] - WHO_BASELINE_ADHERENCE) * 100, 1),
        "doses_confirmed": doses_taken,
        "risk_episodes_flagged": episodes_flagged,
        "no_show_rate": stats["no_show_rate"],
        "cost_rwf": stats["cost_rwf"],
        "cost_per_patient_rwf": stats["cost_per_patient"],
        "annualised_cost_per_patient_rwf": round(stats["cost_per_patient"] * 12, 2),
        "sms_unit_cost_rwf": SMS_COST_RWF,
    }

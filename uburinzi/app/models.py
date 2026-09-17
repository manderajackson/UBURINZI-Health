"""Domain model for Uburinzi Health.

Design notes
------------
* Timestamps are stored as **naive local (clinic) time** — the pilot runs in a
  single country (Africa/Kigali). `app.timeutils.now()` is the single source of
  truth for "now", so swapping to UTC later is a one-file change.
* A patient can be enrolled in several programmes at once (e.g. HIV + TB), so
  programmes live in their own table rather than as a column on Patient.
"""
from __future__ import annotations

import enum
from datetime import date, datetime

from app.timeutils import now

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# --------------------------------------------------------------------- enums
class Channel(str, enum.Enum):
    SMS = "sms"
    WHATSAPP = "whatsapp"
    VOICE = "voice"


class MessageStatus(str, enum.Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class MessageKind(str, enum.Enum):
    CHECKIN = "checkin"
    EDUCATION = "education"
    APPOINTMENT = "appointment"
    LAB_RESULT = "lab_result"
    WELCOME = "welcome"
    MANUAL = "manual"


class ReplyChoice(str, enum.Enum):
    YES = "yes"        # 1 — took medication / will attend
    NO = "no"          # 2 — missed medication / cannot attend
    UNWELL = "unwell"  # 3 — not feeling well, needs human follow-up


class AlertSeverity(str, enum.Enum):
    RED = "red"
    AMBER = "amber"
    INFO = "info"


class AlertState(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    CLINICIAN = "clinician"
    FRONTDESK = "frontdesk"


# ------------------------------------------------------------------- tables
class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Uburinzi Pilot Clinic")
    district: Mapped[str] = mapped_column(String(80), default="Kicukiro")
    country: Mapped[str] = mapped_column(String(80), default="Rwanda")
    phone: Mapped[str] = mapped_column(String(40), default="+250788000000")

    patients: Mapped[list["Patient"]] = relationship(back_populates="clinic")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Clinic {self.name}>"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"), default=1)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.CLINICIAN.value)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    def has_role(self, *roles: str) -> bool:
        return self.role in roles


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("clinic_id", "mrn", name="uq_patient_mrn"),
        Index("ix_patients_phone", "phone"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"), default=1)
    mrn: Mapped[str] = mapped_column(String(40))             # clinic file number
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(8), default="rw")
    sex: Mapped[str] = mapped_column(String(12), default="unknown")
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    village: Mapped[str] = mapped_column(String(120), default="")
    consent_sms: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    # Risk state is derived by the alert engine and cached for fast listing.
    status: Mapped[str] = mapped_column(String(10), default="green")  # green|amber|red
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    missed_streak: Mapped[int] = mapped_column(Integer, default=0)
    no_reply_streak: Mapped[int] = mapped_column(Integer, default=0)

    # Simulator-only persona knobs (used when SMS_DRIVER=simulator).
    sim_adherence: Mapped[float] = mapped_column(Float, default=0.8)
    sim_reply_rate: Mapped[float] = mapped_column(Float, default=0.9)

    clinic: Mapped["Clinic"] = relationship(back_populates="patients")
    enrollments: Mapped[list["Enrollment"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    outbox: Mapped[list["OutboundMessage"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    inbox: Mapped[list["InboundMessage"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def age(self) -> int | None:
        if not self.birth_year:
            return None
        from app.timeutils import now

        return now().year - self.birth_year


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("patient_id", "program", name="uq_enrollment_program"),
        Index("ix_enrollments_program", "program"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    program: Mapped[str] = mapped_column(String(30))           # diabetes|hiv|...
    medication: Mapped[str] = mapped_column(String(120), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    last_checkin_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_education_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    education_index: Mapped[int] = mapped_column(Integer, default=0)
    last_sweep_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="enrollments")


class MessageTemplate(Base):
    """Editable SMS copy. Seeded from app/protocols.py, editable in the UI."""

    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint("program", "kind", "language", "variant", name="uq_template"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    program: Mapped[str] = mapped_column(String(30))          # or "common"
    kind: Mapped[str] = mapped_column(String(20))             # checkin|education|...
    language: Mapped[str] = mapped_column(String(8))
    variant: Mapped[str] = mapped_column(String(40), default="default")
    body: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbound_dedupe"),
        Index("ix_outbound_scheduled", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), nullable=True)
    enrollment_id: Mapped[int | None] = mapped_column(ForeignKey("enrollments.id"), nullable=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"), default=1)

    phone: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="rw")
    program: Mapped[str] = mapped_column(String(30), default="common")
    kind: Mapped[str] = mapped_column(String(20), default=MessageKind.MANUAL.value)
    channel: Mapped[str] = mapped_column(String(12), default=Channel.SMS.value)

    status: Mapped[str] = mapped_column(String(12), default=MessageStatus.QUEUED.value)
    provider: Mapped[str] = mapped_column(String(30), default="simulator")
    provider_id: Mapped[str] = mapped_column(String(80), default="")
    cost_rwf: Mapped[float] = mapped_column(Float, default=0.0)
    segments: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")

    dedupe_key: Mapped[str | None] = mapped_column(String(160), nullable=True, default=None)
    # Simulator: when a synthetic reply from this patient should land.
    sim_reply_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sim_reply_processed: Mapped[bool] = mapped_column(Boolean, default=False)

    patient: Mapped["Patient"] = relationship(back_populates="outbox")


class InboundMessage(Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (Index("ix_inbound_received", "received_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), nullable=True)
    phone: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    channel: Mapped[str] = mapped_column(String(12), default=Channel.SMS.value)
    choice: Mapped[str | None] = mapped_column(String(12), nullable=True)
    provider_id: Mapped[str] = mapped_column(String(80), default="")
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    in_reply_to: Mapped[int | None] = mapped_column(Integer, nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="inbox")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_state", "state"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    rule: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), default=AlertSeverity.AMBER.value)
    state: Mapped[str] = mapped_column(String(16), default=AlertState.OPEN.value)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handled_by: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[Text | None] = mapped_column(Text, nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="alerts")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (Index("ix_appointments_due", "due_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    due_at: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str] = mapped_column(String(140), default="Routine follow-up")
    status: Mapped[str] = mapped_column(String(16), default="upcoming")  # upcoming|completed|missed
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    patient: Mapped["Patient"] = relationship(back_populates="appointments")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=now)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60), default="")
    entity_id: Mapped[str] = mapped_column(String(40), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("key", name="uq_settings_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(Text, default="")


class VoiceCall(Base):
    """One call attempt (outbound IVR check-in or an inbound call from a patient)."""

    __tablename__ = "voice_calls"
    __table_args__ = (Index("ix_voice_calls_status", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), nullable=True)
    outbound_id: Mapped[int | None] = mapped_column(ForeignKey("outbound_messages.id"), nullable=True)

    phone: Mapped[str] = mapped_column(String(40))
    direction: Mapped[str] = mapped_column(String(10), default="outbound")
    purpose: Mapped[str] = mapped_column(String(30), default="checkin")
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|ringing|answered|completed|no-answer|busy|failed
    provider: Mapped[str] = mapped_column(String(30), default="simulator")
    session_id: Mapped[str] = mapped_column(String(80), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    cost_rwf: Mapped[float] = mapped_column(Float, default=0.0)
    dtmf_digits: Mapped[str] = mapped_column(String(20), default="")
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str] = mapped_column(Text, default="")
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)

    patient: Mapped["Patient"] = relationship()


class CohortMetric(Base):
    """Daily rollup used by the dashboard charts and the impact report."""

    __tablename__ = "cohort_metrics"
    __table_args__ = (UniqueConstraint("day", "program", name="uq_metric_day_program"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    program: Mapped[str] = mapped_column(String(30), default="all")
    active_patients: Mapped[int] = mapped_column(Integer, default=0)
    checkins_sent: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    yes: Mapped[int] = mapped_column(Integer, default=0)
    no: Mapped[int] = mapped_column(Integer, default=0)
    unwell: Mapped[int] = mapped_column(Integer, default=0)
    alerts_opened: Mapped[int] = mapped_column(Integer, default=0)

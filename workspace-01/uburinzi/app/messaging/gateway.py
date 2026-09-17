"""Single place where an outbound message touches the network (any channel)."""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from app import config
from app.models import Channel, MessageStatus, OutboundMessage
from app.timeutils import now
from app.messaging.drivers import DRIVERS, CHANNEL_DRIVER_OPTIONS, get_driver
from app.messaging.render import sms_segments
from app import settings_store

log = logging.getLogger("uburinzi.sms")

# Channel → cost model (RWF). Voice is billed per minute, rounded up.
VOICE_COST_PER_MINUTE_RWF = float(getattr(config, "VOICE_COST_PER_MINUTE_RWF", 60.0))
WHATSAPP_COST_RWF = float(getattr(config, "WHATSAPP_COST_RWF", 12.0))


def resolve_driver_name(session, channel: str) -> str:
    key = {"sms": "sms_driver", "whatsapp": "whatsapp_driver", "voice": "voice_driver"}[channel]
    return settings_store.get(session, key, "simulator")


def resolve_driver(session, channel: str):
    return get_driver(channel, resolve_driver_name(session, channel))


def driver_label(session, channel: str) -> str:
    name = resolve_driver_name(session, channel)
    for value, label in CHANNEL_DRIVER_OPTIONS[channel]:
        if value == name:
            return label
    return name


def queue_message(
    session,
    *,
    patient,
    body: str,
    kind: str = "manual",
    program: str = "common",
    language: str | None = None,
    scheduled_at=None,
    enrollment=None,
    dedupe_key: str | None = None,
    channel: str = Channel.SMS.value,
    template_hint: dict | None = None,
) -> OutboundMessage:
    """Create a queued outbound message (does not touch the network)."""
    is_voice = channel == Channel.VOICE.value
    msg = OutboundMessage(
        patient_id=patient.id if patient else None,
        enrollment_id=enrollment.id if enrollment else None,
        clinic_id=getattr(patient, "clinic_id", 1),
        phone=patient.phone if patient else "",
        body=body,
        language=language or getattr(patient, "language", "en"),
        program=program,
        kind=kind,
        channel=channel,
        status=MessageStatus.QUEUED.value,
        provider=resolve_driver_name(session, channel),
        scheduled_at=scheduled_at or now(),
        segments=1 if is_voice else sms_segments(body),
        dedupe_key=dedupe_key or f"adhoc:{uuid.uuid4().hex}",
    )
    session.add(msg)
    session.flush()
    msg.template_hint = template_hint
    return msg


def _cost_for(msg: OutboundMessage) -> float:
    if msg.channel == Channel.VOICE.value:
        return VOICE_COST_PER_MINUTE_RWF
    if msg.channel == Channel.WHATSAPP.value:
        return WHATSAPP_COST_RWF
    return config.SMS_COST_RWF * msg.segments


def send_message(session, msg: OutboundMessage) -> OutboundMessage:
    """Send one queued message through the channel's configured driver."""
    if msg.status in (MessageStatus.SENT.value, MessageStatus.DELIVERED.value):
        return msg

    driver = get_driver(msg.channel, msg.provider or "simulator")
    msg._settings = settings_store.get_all(session, include_secrets=True)
    result = driver.send(msg)
    msg.provider = driver.name
    msg.segments = 1 if msg.channel == Channel.VOICE.value else sms_segments(msg.body)

    if result.ok:
        msg.status = MessageStatus.SENT.value
        msg.sent_at = now()
        msg.provider_id = result.provider_id
        msg.error = ""
        msg.cost_rwf = result.cost_hint if result.cost_hint is not None else _cost_for(msg)
        if driver.name == "simulator":
            msg.delivered_at = now()
            msg.status = MessageStatus.DELIVERED.value
            if config.SIM_AUTO_REPLY and msg.kind in ("checkin", "appointment"):
                _schedule_simulated_reply(msg)
        log.info("sent %s (%s) to %s via %s", msg.id, msg.channel, msg.phone, driver.name)
    else:
        msg.status = MessageStatus.FAILED.value
        msg.error = result.error
        msg.cost_rwf = 0.0
        log.warning("failed %s (%s) to %s: %s", msg.id, msg.channel, msg.phone, result.error)

    session.add(msg)
    return msg


def _schedule_simulated_reply(msg: OutboundMessage) -> None:
    """Queue the patient's synthetic answer a little while after delivery."""
    import random

    if not msg.patient or not msg.patient.consent_sms or not msg.patient.active:
        return
    if random.random() > msg.patient.sim_reply_rate:
        return
    delay = timedelta(minutes=random.randint(2, 120))
    msg.sim_reply_due_at = now() + delay
    msg.sim_reply_processed = False


def estimate_cost(count: int, segments: int = 1) -> float:
    return round(count * segments * config.SMS_COST_RWF, 2)


def channel_summary(session) -> dict:
    return {
        channel: {
            "driver": resolve_driver_name(session, channel),
            "label": driver_label(session, channel),
            "live": get_driver(channel, resolve_driver_name(session, channel)).live,
        }
        for channel in (Channel.SMS.value, Channel.WHATSAPP.value, Channel.VOICE.value)
    }


__all__ = [
    "queue_message",
    "send_message",
    "resolve_driver",
    "resolve_driver_name",
    "driver_label",
    "estimate_cost",
    "channel_summary",
    "get_driver",
    "DRIVERS",
    "CHANNEL_DRIVER_OPTIONS",
]

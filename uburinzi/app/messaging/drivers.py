"""Channel drivers: SMS, WhatsApp and Voice — simulator or Africa's Talking.

Every driver implements the same contract:

    driver.send(msg) -> SendResult

where `msg` is an `OutboundMessage` (so the driver can read the patient's
language, the channel and the provider-specific fields).

Live endpoints (verified against Africa's Talking's Python SDK):
  SMS       POST https://api.africastalking.com/version1/messaging
  WhatsApp  POST https://chat.africastalking.com/whatsapp/message/send
  Voice     POST https://voice.africastalking.com/call
  Balance   GET  https://api.africastalking.com/version1/user?username=...
"""
from __future__ import annotations

import json
import logging
import uuid

import httpx

from app.models import Channel

log = logging.getLogger("uburinzi.drivers")

AT_PROD = "africastalking.com"
AT_SANDBOX = "sandbox.africastalking.com"


class SendResult:
    def __init__(self, ok: bool, provider_id: str = "", status: str = "sent",
                 error: str = "", cost_hint: float | None = None):
        self.ok = ok
        self.provider_id = provider_id
        self.status = status
        self.error = error
        self.cost_hint = cost_hint


class BaseDriver:
    name = "base"
    channel = Channel.SMS.value
    live = False

    def send(self, msg) -> SendResult:
        raise NotImplementedError

    def describe(self) -> str:
        return self.name


# --------------------------------------------------------------------- helpers
def _at_host(settings: dict) -> str:
    return AT_SANDBOX if str(settings.get("at_sandbox", "false")).lower() in {"1", "true", "yes"} else AT_PROD


def _at_headers(settings: dict) -> dict:
    return {"apiKey": settings.get("at_api_key", ""), "Accept": "application/json"}


def _require_credentials(settings: dict) -> str | None:
    if not settings.get("at_api_key") or not settings.get("at_username"):
        return "Africa's Talking credentials are missing — add them on the Channels page"
    if settings.get("at_username") == "sandbox" and not settings.get("at_api_key"):
        return "Sandbox username needs the matching sandbox API key"
    return None


def check_balance(settings: dict, timeout: float = 15.0) -> dict:
    """GET the account balance — used by the 'Test connection' button."""
    error = _require_credentials(settings)
    if error:
        return {"ok": False, "error": error}
    url = f"https://api.{_at_host(settings)}/version1/user?username={settings.get('at_username')}"
    try:
        resp = httpx.get(url, headers=_at_headers(settings), timeout=timeout)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code >= 400:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        return {"ok": True, "balance": (data.get("UserData") or {}).get("balance", "unknown")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _post(url: str, *, settings: dict, data: dict | None = None, json_body: dict | None = None,
          timeout: float = 20.0) -> tuple[int, dict, str]:
    headers = _at_headers(settings)
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        resp = httpx.post(url, headers=headers, json=json_body, timeout=timeout)
    else:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        resp = httpx.post(url, headers=headers, data=data, timeout=timeout)
    try:
        payload = resp.json()
    except Exception:
        payload = {}
    return resp.status_code, payload, resp.text


# --------------------------------------------------------------- simulators
class SimulatorDriver(BaseDriver):
    """Pretend network: records the message, then 'replies' from the patient."""

    name = "simulator"
    channel = Channel.SMS.value

    def send(self, msg) -> SendResult:
        return SendResult(True, provider_id=f"SIM-{uuid.uuid4().hex[:12]}", status="sent")


class SimulatorWhatsAppDriver(BaseDriver):
    name = "simulator"
    channel = Channel.WHATSAPP.value

    def send(self, msg) -> SendResult:
        return SendResult(True, provider_id=f"SIMWA-{uuid.uuid4().hex[:12]}", status="sent")


class SimulatorVoiceDriver(BaseDriver):
    """Queues a synthetic answered call; the engine generates the keypress."""

    name = "simulator"
    channel = Channel.VOICE.value

    def send(self, msg) -> SendResult:
        return SendResult(True, provider_id=f"SIMCALL-{uuid.uuid4().hex[:12]}", status="sent")


class LogDriver(BaseDriver):
    name = "log"
    channel = Channel.SMS.value

    def send(self, msg) -> SendResult:
        print(f"[{msg.channel.upper()}→{msg.phone}] {msg.body}")
        return SendResult(True, provider_id=f"LOG-{uuid.uuid4().hex[:8]}", status="sent")


# ------------------------------------------------------------ live: SMS (AT)
class AfricaTalkingSmsDriver(BaseDriver):
    name = "africastalking"
    channel = Channel.SMS.value
    live = True

    def send(self, msg) -> SendResult:
        settings = msg._settings or {}
        error = _require_credentials(settings)
        if error:
            return SendResult(False, status="failed", error=error)

        host = _at_host(settings)
        url = f"https://api.{host}/version1/messaging"
        data = {
            "username": settings.get("at_username"),
            "to": msg.phone,
            "message": msg.body,
        }
        if settings.get("at_sender_id"):
            data["from"] = settings["at_sender_id"]

        try:
            code, payload, text = _post(url, settings=settings, data=data)
            recipients = (payload.get("SMSMessageData") or {}).get("Recipients") or []
            if code >= 400 or not recipients:
                return SendResult(False, status="failed", error=f"HTTP {code}: {text[:200]}")
            first = recipients[0]
            if str(first.get("statusCode")) not in ("100", "101", "102"):
                return SendResult(False, status="failed", error=str(first.get("status", "rejected")))
            cost = None
            try:
                cost = float(str(first.get("cost", "")).split()[0])
            except (ValueError, IndexError, AttributeError):
                cost = None
            return SendResult(
                True,
                provider_id=str(first.get("messageId") or f"AT-{uuid.uuid4().hex[:10]}"),
                status="sent",
                cost_hint=cost,
            )
        except Exception as exc:
            return SendResult(False, status="failed", error=str(exc)[:200])


# ------------------------------------------------------- live: WhatsApp (AT)
class AfricaTalkingWhatsAppDriver(BaseDriver):
    """Africa's Talking WhatsApp Chat API.

    Session messages (within 24 h of the patient's last reply) are free-form.
    Outside that window WhatsApp requires an approved template — the gateway sets
    `msg.template_hint` to request one.
    """

    name = "at_whatsapp"
    channel = Channel.WHATSAPP.value
    live = True

    def send(self, msg) -> SendResult:
        settings = msg._settings or {}
        error = _require_credentials(settings)
        if error:
            return SendResult(False, status="failed", error=error)
        wa_number = settings.get("at_whatsapp_number")
        if not wa_number:
            return SendResult(False, status="failed", error="No WhatsApp sender number configured")

        host = _at_host(settings)
        body: dict = {"message": msg.body}

        if getattr(msg, "template_hint", None):
            url = f"https://chat.{host}/whatsapp/template/send"
            payload = {
                "username": settings.get("at_username"),
                "waNumber": wa_number,
                "name": msg.template_hint.get("name", settings.get("whatsapp_template", "uburinzi_checkin")),
                "language": msg.template_hint.get("language", "en"),
                "category": msg.template_hint.get("category", "UTILITY"),
                "components": msg.template_hint.get("components", {}),
            }
        else:
            url = f"https://chat.{host}/whatsapp/message/send"
            payload = {
                "username": settings.get("at_username"),
                "waNumber": wa_number,
                "phoneNumber": msg.phone,
                "body": body,
            }

        try:
            code, payload_resp, text = _post(url, settings=settings, json_body=payload)
            if code >= 400:
                return SendResult(False, status="failed", error=f"HTTP {code}: {text[:200]}")
            return SendResult(
                True,
                provider_id=str(payload_resp.get("id") or payload_resp.get("messageId") or f"ATWA-{uuid.uuid4().hex[:10]}"),
                status="sent",
            )
        except Exception as exc:
            return SendResult(False, status="failed", error=str(exc)[:200])


# ---------------------------------------------------------- live: Voice (AT)
class AfricaTalkingVoiceDriver(BaseDriver):
    """Africa's Talking Voice API.

    The call is only *initiated* here. When the patient answers, AT posts to
    /api/webhooks/voice/answer and our XML drives the IVR (see app/voice.py).
    """

    name = "at_voice"
    channel = Channel.VOICE.value
    live = True

    def send(self, msg) -> SendResult:
        settings = msg._settings or {}
        error = _require_credentials(settings)
        if error:
            return SendResult(False, status="failed", error=error)
        caller_id = settings.get("at_voice_number")
        if not caller_id:
            return SendResult(False, status="failed", error="No Africa's Talking voice number configured")

        url = f"https://voice.{_at_host(settings)}/call"
        data = {
            "username": settings.get("at_username"),
            "from": caller_id,
            "to": msg.phone,
        }
        try:
            code, payload, text = _post(url, settings=settings, data=data)
            if code >= 400:
                return SendResult(False, status="failed", error=f"HTTP {code}: {text[:200]}")
            entries = payload.get("entries") or []
            status = (entries[0].get("status") if entries else payload.get("status", "")) or "Queued"
            return SendResult(
                True,
                provider_id=str(payload.get("sessionId") or (entries[0].get("sessionId") if entries else "") or f"ATCALL-{uuid.uuid4().hex[:10]}"),
                status="sent",
            )
        except Exception as exc:
            return SendResult(False, status="failed", error=str(exc)[:200])


DRIVERS = {
    ("sms", "simulator"): SimulatorDriver(),
    ("sms", "africastalking"): AfricaTalkingSmsDriver(),
    ("sms", "log"): LogDriver(),
    ("whatsapp", "simulator"): SimulatorWhatsAppDriver(),
    ("whatsapp", "at_whatsapp"): AfricaTalkingWhatsAppDriver(),
    ("voice", "simulator"): SimulatorVoiceDriver(),
    ("voice", "at_voice"): AfricaTalkingVoiceDriver(),
}

CHANNEL_DRIVER_OPTIONS = {
    "sms": [("simulator", "Simulator (no SMS sent)"), ("africastalking", "Africa's Talking (live)"), ("log", "Console logger")],
    "whatsapp": [("simulator", "Simulator (no message sent)"), ("at_whatsapp", "Africa's Talking WhatsApp (live)")],
    "voice": [("simulator", "Simulator (no call placed)"), ("at_voice", "Africa's Talking Voice (live)")],
}


def get_driver(channel: str, name: str) -> BaseDriver:
    return DRIVERS.get((channel, name)) or DRIVERS[(channel, "simulator")]

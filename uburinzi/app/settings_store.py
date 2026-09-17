"""Runtime settings stored in the database (override env defaults, editable in the UI)."""
from __future__ import annotations

from sqlalchemy import select

from app import config
from app.crypto import decrypt, encrypt
from app.models import Setting

# key → (default, is_secret, env_fallback)
DEFAULTS: dict[str, tuple[str, bool, str | None]] = {
    # --- Africa's Talking credentials -------------------------------------
    "at_username": ("", False, "AFRICASTALKING_USERNAME"),
    "at_api_key": ("", True, "AFRICASTALKING_API_KEY"),
    "at_sender_id": ("", False, "UBURINZI_SMS_SENDER_ID"),
    "at_voice_number": ("", False, "UBURINZI_AT_VOICE_NUMBER"),
    "at_whatsapp_number": ("", False, "UBURINZI_AT_WHATSAPP_NUMBER"),
    "at_sandbox": ("false", False, "AFRICASTALKING_SANDBOX"),
    # --- channel drivers ---------------------------------------------------
    "sms_driver": (config.SMS_DRIVER, False, "UBURINZI_SMS_DRIVER"),
    "whatsapp_driver": ("simulator", False, "UBURINZI_WHATSAPP_DRIVER"),
    "voice_driver": ("simulator", False, "UBURINZI_VOICE_DRIVER"),
    "whatsapp_template": ("uburinzi_checkin", False, None),
    "voice_language": ("en-US", False, None),
    "voice_prompt_url": ("", False, None),
    # --- escalation policy -------------------------------------------------
    "escalation_enabled": ("true", False, None),
    "escalate_whatsapp_after_hours": ("24", False, None),
    "escalate_voice_after_hours": ("48", False, None),
    "escalate_min_status": ("amber", False, None),
    "voice_max_per_week": ("2", False, None),
    "voice_max_calls_per_run": ("5", False, None),
    # --- public URLs -------------------------------------------------------
    "public_base_url": ("", False, "UBURINZI_PUBLIC_BASE_URL"),
    "whatsapp_verify_token": ("uburinzi-verify", False, None),
}

SECRET_KEYS = {k for k, (_, secret, _) in DEFAULTS.items() if secret}


def get_all(session) -> dict:
    rows = {s.key: s.value for s in session.execute(select(Setting)).scalars()}
    out: dict[str, str] = {}
    for key, (default, secret, env_key) in DEFAULTS.items():
        raw = rows.get(key)
        if raw is None and env_key:
            import os

            raw = os.environ.get(env_key, "")
        if raw is None:
            raw = default
        out[key] = raw
    return out


def get(session, key: str, default: str = "") -> str:
    row = session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row is not None:
        return decrypt(row.value) if key in SECRET_KEYS else row.value
    if key in DEFAULTS:
        _, _secret, env_key = DEFAULTS[key]
        import os

        if env_key and os.environ.get(env_key):
            return os.environ[env_key]
        return DEFAULTS[key][0]
    return default


def get_secret(session, key: str) -> str:
    row = session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row is not None:
        return decrypt(row.value)
    import os

    env_key = DEFAULTS.get(key, ("", True, None))[2]
    return os.environ.get(env_key, "") if env_key else ""


def get_bool(session, key: str) -> bool:
    return str(get(session, key, "false")).strip().lower() in {"1", "true", "yes", "on"}


def get_int(session, key: str) -> int:
    try:
        return int(str(get(session, key, "0")).strip())
    except ValueError:
        return int(DEFAULTS.get(key, ("0", False, None))[0])


def set_value(session, key: str, value: str) -> None:
    if key in SECRET_KEYS:
        stored = encrypt(value) if value else ""
    else:
        stored = value
    row = session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row is None:
        session.add(Setting(key=key, value=stored))
    else:
        row.value = stored
    session.flush()


CHANNEL_LABELS = {"sms": "SMS", "whatsapp": "WhatsApp", "voice": "Voice call"}

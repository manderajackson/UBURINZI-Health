"""Uburinzi Health — configuration.

All settings can be overridden with environment variables or a .env file so the
same codebase runs on a laptop, inside the clinic, or on a cloud VM.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is optional at runtime
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

if load_dotenv:
    load_dotenv(BASE_DIR / ".env", override=False)


def _env(key: str, default: str | None = None) -> str | None:
    value = os.environ.get(key)
    return value if value not in (None, "") else default


def _env_bool(key: str, default: bool) -> bool:
    value = _env(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    try:
        return int(str(_env(key, default)).strip())
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- app basics
APP_NAME = "Uburinzi Health"
APP_TAGLINE = "Chronic patient monitoring between clinic visits"
SECRET_KEY = _env("UBURINZI_SECRET_KEY", "change-me-in-production-uburinzi-2026")
# Clinic timezone: drives the 08:00-18:00 sending window. This default suits a
# Rwandan pilot; set UBURINZI_TIMEZONE to the clinic's own zone anywhere else.
TIMEZONE = _env("UBURINZI_TIMEZONE", "Africa/Kigali")
DATABASE_URL = _env("UBURINZI_DATABASE_URL", f"sqlite:///{DATA_DIR / 'uburinzi.db'}")

# Demo seed on first boot (set to false once real patients are enrolled).
AUTO_SEED = _env_bool("UBURINZI_AUTO_SEED", True)
SEED_PATIENTS = _env_int("UBURINZI_SEED_PATIENTS", 52)
SEED_HISTORY_DAYS = _env_int("UBURINZI_SEED_HISTORY_DAYS", 75)

# ------------------------------------------------------------------- SMS
# Driver: "simulator" (default — no credentials needed), "africastalking", "log"
SMS_DRIVER = (_env("UBURINZI_SMS_DRIVER", "simulator") or "simulator").lower()
SMS_SENDER_ID = _env("UBURINZI_SMS_SENDER_ID", "Uburinzi")  # AT shortcode/sender id
AT_USERNAME = _env("AFRICASTALKING_USERNAME", "sandbox")
AT_API_KEY = _env("AFRICASTALKING_API_KEY", "")
AT_SANDBOX = _env_bool("AFRICASTALKING_SANDBOX", False)

# Sending rules (clinic-local time)
SEND_WINDOW_START = _env_int("UBURINZI_SEND_WINDOW_START", 8)   # 08:00
SEND_WINDOW_END = _env_int("UBURINZI_SEND_WINDOW_END", 18)      # 18:00
DAILY_SMS_CAP = _env_int("UBURINZI_DAILY_SMS_CAP", 500)
SCHEDULER_INTERVAL_SECONDS = _env_int("UBURINZI_SCHEDULER_INTERVAL", 60)

# Integration API key (X-API-Key header) for EMR/LIS adapters
API_KEY = _env("UBURINZI_API_KEY", "demo-api-key")

# Background scheduler inside the web process (set false if you run the CLI worker)
SCHEDULER_ENABLED = _env_bool("UBURINZI_SCHEDULER", True)

# Serverless platforms (Vercel, Lambda) freeze the process between requests, so a
# background thread is useless there -- Vercel Cron calls /api/cron/scheduler instead.
RUNNING_SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
if RUNNING_SERVERLESS:
    SCHEDULER_ENABLED = False

# Demo mode pre-fills the login form and lists demo accounts. Never on a public
# deployment, where printing the password on the sign-in page would be a hole.
DEMO_MODE = _env_bool("UBURINZI_DEMO_MODE", True) and not RUNNING_SERVERLESS

# Cost model used for the ROI / burn figures shown on the dashboard (RWF)
# Measured on a live AT send to a Rwandan number (was a 27 RWF estimate before)
SMS_COST_RWF = float(_env("UBURINZI_SMS_COST_RWF", "12"))
WHATSAPP_COST_RWF = float(_env("UBURINZI_WHATSAPP_COST_RWF", "12"))
VOICE_COST_PER_MINUTE_RWF = float(_env("UBURINZI_VOICE_COST_PER_MINUTE_RWF", "60"))

# Public base URL used to build webhook URLs for Africa's Talking / Meta
PUBLIC_BASE_URL = _env("UBURINZI_PUBLIC_BASE_URL", "")

# Simulator behaviour
SIM_AUTO_REPLY = _env_bool("UBURINZI_SIM_AUTO_REPLY", True)

LANGUAGES = {
    "rw": "Kinyarwanda",
    "en": "English",
    "fr": "Français",
    "sw": "Kiswahili",
}
DEFAULT_LANGUAGE = _env("UBURINZI_DEFAULT_LANGUAGE", "rw")

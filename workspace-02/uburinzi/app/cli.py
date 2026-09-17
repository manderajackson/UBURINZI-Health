"""Command line entry point: seeding, CSV import/export, scheduler runs."""
from __future__ import annotations

import argparse
import csv
import sys
import time
import uuid
from pathlib import Path

from app.config import DATA_DIR, SCHEDULER_INTERVAL_SECONDS
from app.db import DBSession, init_db
from app.models import Patient
from sqlalchemy import select
from app.timeutils import now

SAMPLE_CSV = DATA_DIR / "sample_clinicplus_export.csv"
EXPORT_FIELDS = ["mrn", "first_name", "last_name", "phone", "language", "sex", "birth_year", "village", "program", "medication"]


def cmd_init(_args) -> int:
    init_db()
    print(f"✅ Database ready at {DATA_DIR / 'uburinzi.db'}")
    return 0


def cmd_seed(args) -> int:
    init_db()
    from app.engine import evaluate_all
    from app.seed import seed_all

    with DBSession() as db:
        info = seed_all(db, patients=args.patients, days=args.days)
        n = evaluate_all(db)
    print(f"✅ Seeded {info['patients']} patients with {info['history_days']} days of history; {n} patients risk-scored.")
    return 0


def cmd_reset(args) -> int:
    db_file = DATA_DIR / "uburinzi.db"
    if db_file.exists():
        db_file.unlink()
    print("🗑️  Database deleted.")
    return cmd_seed(args)


def _write_env(**pairs: str) -> Path:
    """Update .env in place, creating it if needed (never committed, never zipped)."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    out, seen = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in pairs:
            out.append(f"{key}={pairs[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in pairs.items():
        if key not in seen:
            out.append(f"{key}={value}")
    env_file.write_text("\n".join(out) + "\n")
    return env_file


def cmd_use_live(args) -> int:
    """Point the platform at a real Africa's Talking app.

    Writes the credentials to .env (so a `reset` cannot lose them), stores them
    encrypted in the database, flips the drivers and proves it with a balance
    check and an optional real SMS.
    """
    from app import settings_store
    from app.db import DBSession
    from app.engine import normalize_phone
    from app.messaging.drivers import check_balance

    import os

    from app.config import AT_API_KEY, AT_USERNAME

    username = (args.username or "").strip() or os.environ.get("AFRICASTALKING_USERNAME", "") or AT_USERNAME
    key = (args.key or "").strip() or os.environ.get("AFRICASTALKING_API_KEY", "") or AT_API_KEY
    from_env = not (args.key or "").strip()
    sandbox = bool(args.sandbox)
    if not username or not key:
        print("❌ No credentials found. Either pass --username/--key, or put them in .env as")
        print("   AFRICASTALKING_USERNAME / AFRICASTALKING_API_KEY and run: uburinzi use-live --from-env")
        return 1
    if username == "sandbox" and not sandbox:
        print("ℹ️  Username 'sandbox' only works on the sandbox app — adding --sandbox.")
        sandbox = True

    env_file = _write_env(
        AFRICASTALKING_USERNAME=username,
        AFRICASTALKING_API_KEY=key,
        AFRICASTALKING_SANDBOX="true" if sandbox else "false",
        **({"AFRICASTALKING_SENDER_ID": args.sender_id} if args.sender_id else {}),
    )
    source = ".env (nothing was passed on the command line)" if from_env else "the command line"
    print(f"🔐 Credentials read from {source}; stored in {env_file.name} (git-ignored) and encrypted in the database")

    with DBSession() as db:
        settings_store.set_value(db, "at_username", username)
        settings_store.set_value(db, "at_api_key", key)          # encrypted at rest
        settings_store.set_value(db, "at_sandbox", "true" if sandbox else "false")
        # SMS first: voice and WhatsApp stay local until their numbers are provisioned.
        settings_store.set_value(db, "sms_driver", "africastalking" if not args.no_sms else "simulator")
        settings_store.set_value(db, "whatsapp_driver", "simulator")
        settings_store.set_value(db, "voice_driver", "simulator")
        if args.sender_id:
            settings_store.set_value(db, "at_sender_id", args.sender_id)
        settings = settings_store.get_all(db, include_secrets=True)

    mode = "SANDBOX" if sandbox else "LIVE"
    print(f"📡 Mode: {mode}  |  sms=africastalking  whatsapp=simulator  voice=simulator")

    balance = check_balance(settings)
    print("💰 Balance:", balance.get("balance") if balance.get("ok") else f"FAILED — {balance.get('error')}")
    if not balance.get("ok"):
        print("\n   If this is a brand-new key, wait 3 minutes and run the command again.")
        print("   A sandbox key needs --sandbox; a live key must use the live app username.")
        return 1

    if args.test_to:
        from app.messaging.gateway import queue_message, send_message
        from app.models import Patient

        phone = normalize_phone(args.test_to)
        with DBSession() as db:
            patient = db.execute(select(Patient).where(Patient.phone == phone)).scalar_one_or_none()
            if patient is None:
                patient = db.execute(select(Patient).where(Patient.mrn == "TEST")).scalar_one_or_none()
            if patient is None:
                from app.models import Clinic

                clinic = db.execute(select(Clinic).limit(1)).scalar_one_or_none()
                patient = Patient(clinic_id=clinic.id if clinic else 1, mrn="TEST", first_name="Test",
                                  last_name="Number", phone=phone, language="en", consent_sms=True, active=False)
            else:
                patient.phone = phone
            db.add(patient)
            db.flush()
            msg = queue_message(db, patient=patient, body=args.message, kind="test", dedupe_key=f"clitest:{uuid.uuid4().hex}")
            msg = send_message(db, msg)
            print(f"📤 Test SMS to {phone}: {msg.status} {msg.provider_id or ''} {msg.error}".rstrip())

    print("\n🔗 Webhooks to paste into the AT dashboard (needs a public HTTPS URL):")
    base = settings.get("public_base_url") or "https://YOUR-DOMAIN"
    for path in ("/api/webhooks/sms/inbound", "/api/webhooks/sms/delivery", "/api/webhooks/whatsapp",
                 "/api/webhooks/voice/answer", "/api/webhooks/voice/dtmf", "/api/webhooks/voice/event",
                     "/api/webhooks/ussd",
                 "/api/webhooks/ussd"):
        print(f"   {base}{path}")
    if not settings.get("public_base_url"):
        print("   (set public_base_url on /settings, or UBURINZI_PUBLIC_BASE_URL, to print real URLs)")
    return 0


def cmd_channels(_args) -> int:
    """Show which channel is live, the balance and the webhook URLs."""
    from app import settings_store
    from app.db import DBSession
    from app.messaging.drivers import check_balance
    from app.messaging.gateway import channel_summary

    with DBSession() as db:
        settings = settings_store.get_all(db, include_secrets=True)
        print("Channels:", channel_summary(db))
        print("Username:", settings.get("at_username") or "(none)",
              "| sandbox:", settings.get("at_sandbox"),
              "| sender ID:", settings.get("at_sender_id") or "(AT default)")
        print("Balance :", check_balance(settings))
        base = settings.get("public_base_url") or "https://YOUR-DOMAIN"
        for path in ("/api/webhooks/sms/inbound", "/api/webhooks/sms/delivery", "/api/webhooks/whatsapp",
                     "/api/webhooks/voice/answer", "/api/webhooks/voice/dtmf", "/api/webhooks/voice/event",
                     "/api/webhooks/ussd",
                 "/api/webhooks/ussd"):
            print(f"   {base}{path}")
    return 0


def cmd_send_due(_args) -> int:
    from app.engine import run_scheduler

    with DBSession() as db:
        result = run_scheduler(db, force=True)
    print(f"📤 {result}")
    return 0


def cmd_daily(_args) -> int:
    from app.engine import run_daily_jobs

    with DBSession() as db:
        result = run_daily_jobs(db)
    print(f"🧹 {result}")
    return 0


def cmd_run_scheduler(args) -> int:
    from app.engine import run_daily_jobs, run_scheduler

    print(f"⏱️  Scheduler running every {args.interval}s. Ctrl+C to stop.")
    last_daily = None
    try:
        while True:
            with DBSession() as db:
                result = run_scheduler(db)
                today = now().date()
                if last_daily != today and now().hour >= 7:
                    result["daily"] = run_daily_jobs(db)
                    last_daily = today
            if result.get("queued") or result.get("sent") or result.get("daily"):
                print(f"[{now():%Y-%m-%d %H:%M:%S}] {result}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n👋 Scheduler stopped.")
    return 0


def cmd_import(args) -> int:
    from app.engine import enroll_patient, normalize_phone
    from app.protocols import PROGRAMS

    path = Path(args.file)
    if not path.exists():
        print(f"❌ File not found: {path}")
        return 1

    created = skipped = 0
    with DBSession() as db, path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            phone = normalize_phone(row.get("phone", ""))
            if not phone:
                skipped += 1
                continue
            exists = db.query(Patient).filter(Patient.phone == phone).first()
            if exists:
                skipped += 1
                continue
            patient = Patient(
                mrn=(row.get("mrn") or f"IMP-{created+1:04d}").strip(),
                first_name=(row.get("first_name") or "Unknown").strip(),
                last_name=(row.get("last_name") or "").strip(),
                phone=phone,
                language=(row.get("language") or "rw").strip()[:8],
                sex=(row.get("sex") or "unknown").strip(),
                birth_year=int(row["birth_year"]) if str(row.get("birth_year", "")).isdigit() else None,
                village=(row.get("village") or "").strip(),
                consent_sms=False,  # consent must be captured before messaging
                active=True,
            )
            db.add(patient)
            db.flush()
            program = (row.get("program") or "diabetes").strip().lower()
            if program in PROGRAMS:
                enroll_patient(db, patient, program, row.get("medication", ""))
            created += 1
    print(f"📥 Imported {created} patients ({skipped} skipped as duplicates/invalid).")
    print("⚠️  Imported patients are created with consent_sms=False — capture consent before messaging.")
    return 0


def cmd_export_sample(_args) -> int:
    SAMPLE_CSV.parent.mkdir(exist_ok=True)
    with DBSession() as db, SAMPLE_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        for p in db.query(Patient).limit(25).all():
            program = p.enrollments[0].program if p.enrollments else "diabetes"
            med = p.enrollments[0].medication if p.enrollments else ""
            writer.writerow({
                "mrn": p.mrn,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "phone": p.phone,
                "language": p.language,
                "sex": p.sex,
                "birth_year": p.birth_year or "",
                "village": p.village,
                "program": program,
                "medication": med,
            })
    print(f"📤 Wrote {SAMPLE_CSV}")
    return 0


def cmd_stats(_args) -> int:
    from app.metrics import impact_report

    with DBSession() as db:
        rep = impact_report(db, days=30)
    for key, value in rep.items():
        print(f"{key:38s} {value}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="uburinzi", description="Uburinzi Health CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init-db", help="create tables").set_defaults(func=cmd_init)

    p = sub.add_parser("seed", help="load demo data")
    p.add_argument("--patients", type=int, default=52)
    p.add_argument("--days", type=int, default=45)
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("reset", help="delete the database and reseed")
    p.add_argument("--patients", type=int, default=52)
    p.add_argument("--days", type=int, default=45)
    p.set_defaults(func=cmd_reset)

    sub.add_parser("send-due", help="queue and send every due protocol message now").set_defaults(func=cmd_send_due)
    sub.add_parser("daily-jobs", help="run the daily sweep").set_defaults(func=cmd_daily)

    p = sub.add_parser("run-scheduler", help="run the scheduler loop in the foreground")
    p.add_argument("--interval", type=int, default=SCHEDULER_INTERVAL_SECONDS)
    p.set_defaults(func=cmd_run_scheduler)

    p = sub.add_parser("import-csv", help="import patients from a ClinicPlus-style CSV")
    p.add_argument("file")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("use-live", help="point the platform at a real Africa's Talking app")
    p.add_argument("--username", default="", help="AT app username (not your login email)")
    p.add_argument("--key", default="", help="AT API key (atsk_...); omit to read it from .env")
    p.add_argument("--from-env", action="store_true", help="take username and key from .env instead of the command line")
    p.add_argument("--sandbox", action="store_true", help="this is a sandbox app key")
    p.add_argument("--sender-id", default="", help="registered alphanumeric sender ID, e.g. UBURINZI")
    p.add_argument("--test-to", default="", help="phone number to receive a verification SMS")
    p.add_argument("--message", default="Uburinzi Health: your live connection works. No reply needed.",
                   help="verification message body")
    p.add_argument("--no-sms", action="store_true", help="store credentials but leave the SMS driver on simulator")
    p.set_defaults(func=cmd_use_live)

    sub.add_parser("channels", help="show live channels, balance and webhook URLs").set_defaults(func=cmd_channels)

    sub.add_parser("export-sample", help="write data/sample_clinicplus_export.csv").set_defaults(func=cmd_export_sample)
    sub.add_parser("stats", help="print the 30-day impact report").set_defaults(func=cmd_stats)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

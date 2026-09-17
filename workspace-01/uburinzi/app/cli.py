"""Command line entry point: seeding, CSV import/export, scheduler runs."""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from app.config import DATA_DIR, SCHEDULER_INTERVAL_SECONDS
from app.db import DBSession, init_db
from app.models import Patient
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

    sub.add_parser("export-sample", help="write data/sample_clinicplus_export.csv").set_defaults(func=cmd_export_sample)
    sub.add_parser("stats", help="print the 30-day impact report").set_defaults(func=cmd_stats)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

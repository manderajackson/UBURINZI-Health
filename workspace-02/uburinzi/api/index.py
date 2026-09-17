"""Vercel serverless entry point.

Vercel imports this module and serves `app` as an ASGI function. Two things
differ from running locally:

* the in-process scheduler never starts (`app.config` disables it when the
  VERCEL env var is present) — Vercel Cron calls /api/cron/scheduler instead;
* the database MUST be Postgres, because serverless filesystems are ephemeral
  and a SQLite file would vanish between invocations.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Vercel runs this file from the project root; make `import app` work there too.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402  (Vercel looks for this name)

__all__ = ["app"]

if os.environ.get("VERCEL") and not os.environ.get("DATABASE_URL"):
    # Loud rather than silent: without Postgres every write disappears.
    print("⚠️  Uburinzi: DATABASE_URL is not set — set it to your Postgres URL in Vercel → Settings → Environment Variables")

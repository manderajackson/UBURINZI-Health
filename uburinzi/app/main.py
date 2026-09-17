"""Uburinzi Health — chronic patient monitoring platform (FastAPI app factory)."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.deps import bootstrap
from app.db import DBSession, init_db
from app.routes_api import router as api_router
from app.routes_ui import router as ui_router
from app.timeutils import now

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("uburinzi")


def _scheduler_loop() -> None:
    """Background worker: protocol messages, simulated replies and the daily sweep."""
    from app.engine import run_daily_jobs, run_scheduler

    last_daily = None
    while True:
        try:
            with DBSession() as db:
                result = run_scheduler(db)
                today = now().date()
                if last_daily != today and now().hour >= 7:
                    result["daily"] = run_daily_jobs(db)
                    last_daily = today
            if result.get("sent") or result.get("queued") or result.get("daily"):
                log.info("scheduler: %s", result)
        except Exception as exc:  # keep the worker alive
            log.exception("scheduler error: %s", exc)
        time.sleep(config.SCHEDULER_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with DBSession() as db:
        bootstrap(db)

    if config.AUTO_SEED:
        from app.engine import evaluate_all
        from app.models import Patient
        from app.seed import seed_all

        with DBSession() as db:
            count = db.query(Patient).count()
            if count == 0:
                log.info("Seeding demo cohort (%s patients, %s days)…",
                         config.SEED_PATIENTS, config.SEED_HISTORY_DAYS)
                seed_all(db)
                evaluate_all(db)
                log.info("Demo cohort ready.")

    if config.SCHEDULER_ENABLED:
        thread = threading.Thread(target=_scheduler_loop, daemon=True, name="uburinzi-scheduler")
        thread.start()
        log.info("Scheduler thread started (every %ss, window %02d:00–%02d:00).",
                 config.SCHEDULER_INTERVAL_SECONDS, config.SEND_WINDOW_START, config.SEND_WINDOW_END)
    yield
    log.info("Shutting down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Uburinzi Health API",
        version="0.1.0",
        description=(
            "Plug-and-play chronic disease patient monitoring for African clinics. "
            "SMS-first (no smartphone, no app, no internet), integrates with any clinic "
            "management system, and escalates at-risk patients to clinic staff."
        ),
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")
    app.include_router(ui_router)
    app.include_router(api_router)

    @app.exception_handler(HTTPException)
    async def _redirect_on_303(request: Request, exc: HTTPException):
        if exc.status_code in (301, 302, 303, 307) and exc.headers and "Location" in exc.headers:
            return RedirectResponse(exc.headers["Location"], status_code=303)
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.get("/health")
    def health():
        return {"ok": True, "app": config.APP_NAME, "time": now().isoformat(), "driver": config.SMS_DRIVER}

    return app


app = create_app()

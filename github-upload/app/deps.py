"""Shared request helpers: auth guard, template rendering with nav context."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app import config
from app.db import get_db
from app.messaging.gateway import driver_label, get_driver
from app.models import Alert, AlertState, Clinic, Patient, Setting, User
from app.protocols import PROGRAMS
from app.security import SESSION_COOKIE, get_current_user, hash_password
from app.timeutils import now

templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))


def _nav(db) -> dict:
    alerts_open = (
        db.execute(
            select(func.count(Alert.id)).where(Alert.state != AlertState.RESOLVED.value)
        ).scalar()
        or 0
    )
    total_patients = db.execute(select(func.count(Patient.id))).scalar() or 0
    return {
        "alerts_open": alerts_open,
        "total_patients": total_patients,
        "now": now().strftime("%a %d %b %Y, %H:%M"),
    }


def _driver_info(db=None) -> dict:
    from app.messaging.gateway import channel_summary, resolve_driver_name

    summary = channel_summary(db) if db is not None else {}
    sms = summary.get("sms", {})
    return {
        "mode": sms.get("driver", "simulator"),
        "label": sms.get("label", "Simulator (no SMS sent)"),
        "channels": summary,
        "window": f"{config.SEND_WINDOW_START:02d}:00–{config.SEND_WINDOW_END:02d}:00",
        "cap": config.DAILY_SMS_CAP,
        "cost": config.SMS_COST_RWF,
        "timezone": config.TIMEZONE,
        "database": config.DATABASE_URL.split("://")[0],
    }


def flash_redirect(url: str, msg: str, category: str = "ok") -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    return RedirectResponse(
        f"{url}{sep}msg={quote(msg)}&cat={category}", status_code=303
    )


def render(request: Request, db, template: str, **ctx):
    from app.timeutils import ago, human

    user = get_current_user(request, db)
    clinic = db.execute(select(Clinic).limit(1)).scalar_one_or_none()
    if clinic is None:
        clinic = Clinic(name="Uburinzi Pilot Clinic")
        db.add(clinic)
        db.commit()

    base = {
        "request": request,
        "current_user": user,
        "clinic": clinic,
        "nav": _nav(db),
        "driver": _driver_info(db),
        "programs": PROGRAMS,
        "languages": config.LANGUAGES,
        "human": human,
        "ago": ago,
        "active": ctx.pop("active", template.split("/")[0].replace(".html", "")),
    }
    base.update(ctx)
    return templates.TemplateResponse(request, template, base)


def login_required(request: Request, db=Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def bootstrap(session) -> None:
    """Create a default clinic/admin/password on a fresh database."""
    from app.protocols import seed_templates

    seed_templates(session)
    clinic = session.execute(select(Clinic).limit(1)).scalar_one_or_none()
    if clinic is None:
        clinic = Clinic()
        session.add(clinic)
        session.flush()
    if session.execute(select(User).limit(1)).scalar_one_or_none() is None:
        session.add(
            User(
                clinic_id=clinic.id,
                name="Mandera Jackson",
                email="manderajackson99@gmail.com",
                password_hash=hash_password("uburinzi2026"),
                role="admin",
            )
        )
    if session.execute(select(Setting).limit(1)).scalar_one_or_none() is None:
        session.add(Setting(key="onboarding", value="pending"))
    session.commit()


def logout_response() -> RedirectResponse:
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp

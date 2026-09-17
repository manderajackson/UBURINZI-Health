"""Template rendering + GSM segment accounting."""
from __future__ import annotations

import math
import re

from sqlalchemy import select

from app.models import MessageTemplate

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def safe_format(body: str, ctx: dict) -> str:
    def repl(match):
        key = match.group(1)
        return str(ctx.get(key, match.group(0)))

    return PLACEHOLDER.sub(repl, body)


def sms_segments(text: str) -> int:
    length = len(text)
    if length <= 160:
        return 1
    return math.ceil(length / 153)  # multi-part GSM concatenation


def render_template(
    session,
    program: str,
    kind: str,
    language: str,
    variant: str = "default",
    ctx: dict | None = None,
) -> str:
    """Resolve copy with graceful fallbacks: program → common, lang → English."""
    ctx = ctx or {}

    def fetch(prog: str, lang: str, var: str) -> str | None:
        row = session.execute(
            select(MessageTemplate).where(
                MessageTemplate.program == prog,
                MessageTemplate.kind == kind,
                MessageTemplate.language == lang,
                MessageTemplate.variant == var,
            )
        ).scalar_one_or_none()
        return row.body if row else None

    body = None
    for prog in (program, "common"):
        for lang in (language, "en"):
            body = fetch(prog, lang, variant)
            if body:
                break
        if body:
            break

    if body is None:
        body = "Hello {first_name}, this is {clinic}. Reply 1=Yes, 2=No, 3=Not feeling well."
    return safe_format(body, ctx)

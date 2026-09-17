"""Database engine / session plumbing.

SQLite by default (zero-config, perfect for a single-clinic pilot). Set
UBURINZI_DATABASE_URL=postgresql://user:pass@host/db to move to Postgres —
the models are plain SQLAlchemy, no SQLite-specific types are used.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    """FastAPI dependency + plain context-manager friendly session factory."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class DBSession:
    """`with DBSession() as db:` helper for scripts, seeds and the scheduler."""

    def __enter__(self):
        self.db = SessionLocal()
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.db.commit()
            else:
                self.db.rollback()
        finally:
            self.db.close()
        return False


# Columns added after the first release — safe to ADD on an existing database.
MIGRATIONS: list[tuple[str, str, str]] = [
    ("outbound_messages", "channel", "VARCHAR(12) DEFAULT 'sms'"),
    ("inbound_messages", "channel", "VARCHAR(12) DEFAULT 'sms'"),
]


def ensure_schema() -> None:
    """Create missing tables and add missing columns (lightweight migration)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    for table, column, ddl in MIGRATIONS:
        if table not in tables:
            continue
        columns = {c["name"] for c in inspector.get_columns(table)}
        if column not in columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def init_db() -> None:
    from app import models  # noqa: F401  (import registers the metadata)

    Base.metadata.create_all(engine)
    ensure_schema()

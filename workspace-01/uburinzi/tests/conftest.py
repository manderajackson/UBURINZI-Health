import os
import tempfile

TMP_DIR = tempfile.mkdtemp(prefix="uburinzi-test-")

os.environ["UBURINZI_DATABASE_URL"] = f"sqlite:///{TMP_DIR}/test.db"
os.environ["UBURINZI_SMS_DRIVER"] = "log"
os.environ["UBURINZI_AUTO_SEED"] = "false"
os.environ["UBURINZI_SEND_WINDOW_START"] = "0"
os.environ["UBURINZI_SEND_WINDOW_END"] = "24"
os.environ["UBURINZI_SECRET_KEY"] = "test-secret"

import pytest

from app.db import DBSession, init_db


@pytest.fixture(autouse=True)
def _schema_ready():
    """Guarantee tables + message templates exist for every test."""
    from app.protocols import seed_templates

    init_db()
    with DBSession() as db:
        seed_templates(db)
    yield

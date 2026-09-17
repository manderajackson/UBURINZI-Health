"""Bundle the project into a downloadable zip (source, no database, no secrets)."""
from __future__ import annotations

import zipfile
from pathlib import Path

from app import config

EXCLUDE_DIRS = {
    "__pycache__", ".pytest_cache", ".git", ".venv", "venv", "node_modules",
    ".mypy_cache", ".ruff_cache", "dist", ".cache",
}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".db", ".sqlite3", ".log"}
EXCLUDE_FILES = {".env", ".DS_Store"}


def build_zip(dest: Path | None = None) -> Path:
    """Write uburinzi-health.zip and return its path.

    Normally lands in ./dist. On a read-only serverless filesystem it falls back
    to the temp directory, which is the only writable place there.
    """
    if dest is None:
        dest = config.BASE_DIR / "dist" / "uburinzi-health.zip"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb"):
                pass  # probe: is this filesystem writable at all?
        except OSError:
            import tempfile

            dest = Path(tempfile.gettempdir()) / "uburinzi-health.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    root = config.BASE_DIR

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            parts = set(rel.parts)
            if parts & EXCLUDE_DIRS:
                continue
            if path.is_dir():
                continue
            if path.suffix in EXCLUDE_SUFFIX or path.name in EXCLUDE_FILES:
                continue
            if rel.parts[0] == "data" and path.suffix in {".db", ".sqlite3"}:
                continue
            zf.write(path, Path("uburinzi") / rel)

        # friendly README at the root of the zip
        zf.writestr(
            "uburinzi/START-HERE.txt",
            "UBURINZI HEALTH\n"
            "===============\n\n"
            "1. Unzip this folder.\n"
            "2. Open a terminal inside it and run:\n\n"
            "     python3 -m venv .venv\n"
            "     source .venv/bin/activate        (Windows: .venv\\Scripts\\activate)\n"
            "     pip install -r requirements.txt\n"
            "     python -m app.cli reset\n"
            "     python -m uvicorn app.main:app --host 0.0.0.0 --port 8000\n\n"
            "3. Open http://localhost:8000\n"
            "     manderajackson99@gmail.com / uburinzi2026\n\n"
            "Read README.md for the full guide, docs/live-setup.md to connect Africa's Talking,\n"
            "and docs/deploy.md to put it on a real server.\n",
        )
    return dest

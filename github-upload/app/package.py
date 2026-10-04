"""Bundle the project into a downloadable zip (source, no database, no secrets)."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from app import config

EXCLUDE_DIRS = {
    "__pycache__", ".pytest_cache", ".git", ".venv", "venv", "node_modules",
    ".mypy_cache", ".ruff_cache", "dist", ".cache", ".vercel", "github-upload",
}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".db", ".sqlite3", ".log"}
EXCLUDE_FILES = {".env", ".DS_Store"}


def iter_source_files(root: Path | None = None):
    """Every file that belongs in a download, relative to the project root."""
    root = root or config.BASE_DIR
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts and (set(rel.parts) & EXCLUDE_DIRS):
            continue
        if path.is_dir():
            continue
        if path.suffix in EXCLUDE_SUFFIX or path.name in EXCLUDE_FILES:
            continue
        yield path, rel


def build_upload_bundle(dest_dir: Path | None = None) -> Path:
    """Write a ready-to-push copy of the project.

    Unlike build_zip (which nests everything under uburinzi/ for humans), this
    writes the files at the top level exactly as GitHub should receive them, so
    the folder can be dragged into a new repository or pushed as-is. An existing
    .git directory inside `dest_dir` is preserved, so re-running this keeps the
    commit history.
    """
    dest_dir = Path(dest_dir or (config.BASE_DIR.parent / "github-upload"))
    dest_dir.mkdir(parents=True, exist_ok=True)

    # remove last time's files but keep git metadata
    for item in dest_dir.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    copied = 0
    for path, rel in iter_source_files():
        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return dest_dir, copied


def commit_bundle(dest_dir: Path, message: str = "") -> str:
    """Commit the refreshed folder so it is always ready to push.

    A serverless workspace can lose .git/config between runs (identity, remotes),
    so this re-establishes the local identity every time instead of assuming it.
    """
    import os
    from datetime import datetime, timezone

    dest_dir = Path(dest_dir)
    name = os.environ.get("UBURINZI_GIT_NAME", "Mandera Jackson")
    email = os.environ.get("UBURINZI_GIT_EMAIL", "manderajackson99@gmail.com")
    message = message or f"Update Uburinzi Health — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"

    def git(*args: str, check: bool = True):
        return subprocess.run(
            ["git", *args], cwd=dest_dir, check=check,
            capture_output=True, text=True,
        ).stdout.strip()

    if not (dest_dir / ".git").exists():
        git("init", "-q")
        git("config", "init.defaultBranch", "main")
    git("config", "user.name", name)
    git("config", "user.email", email)
    git("branch", "-M", "main", check=False)
    git("add", "-A")
    staged = git("diff", "--cached", "--name-only")
    if not staged:
        return "nothing to commit (already up to date)"
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=dest_dir, check=True,
                   capture_output=True, text=True)
    return f"{len(staged.splitlines())} file(s) committed"


def build_all(dest_dir: Path | None = None) -> dict:
    """Everything a release needs: the flat upload folder + both zips."""
    bundle_dir, count = build_upload_bundle(dest_dir)
    source_zip = build_zip()

    bundle_dir, count = (bundle_dir, count) if isinstance(bundle_dir, Path) else (Path(bundle_dir), count)
    bundle_zip = config.BASE_DIR / "dist" / "uburinzi-health-github.zip"
    try:
        bundle_zip.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        import tempfile

        bundle_zip = Path(tempfile.gettempdir()) / "uburinzi-health-github.zip"
    with zipfile.ZipFile(bundle_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_dir() or ".git" in path.parts:
                continue
            zf.write(path, path.relative_to(bundle_dir))

    return {"bundle_dir": bundle_dir, "files": count, "source_zip": source_zip, "bundle_zip": bundle_zip}


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


def find_stale_copies(root: Path):
    """
    Top-level folders that hold an old snapshot of the project.

    Detects both `uburinzi/` (a nested zip upload) and `workspace-01/uburinzi/`
    (a numbered snapshot folder) by looking for a project inside them, rather
    than hard-coding names.
    """
    shipped = {str(rel.parts[0]) for _, rel in iter_source_files() if len(rel.parts) > 1}
    stale = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in shipped:
            continue
        for candidate in (entry / "app" / "main.py", entry / "uburinzi" / "app" / "main.py"):
            if candidate.exists():
                stale.append(entry.name)
                break
    return stale


# --------------------------------------------------------------------------- #
# Push the project straight to a GitHub repository
# --------------------------------------------------------------------------- #

GIT_NAME = os.environ.get("UBURINZI_GIT_NAME", "Mandera Jackson")
GIT_EMAIL = os.environ.get("UBURINZI_GIT_EMAIL", "manderajackson99@gmail.com")


def _git(args, cwd, check=True, env=None):
    """Run git with an explicit identity so it works in any environment."""
    import subprocess as _sp

    full = [
        "git",
        "-c", f"user.name={GIT_NAME}",
        "-c", f"user.email={GIT_EMAIL}",
        *args,
    ]
    kwargs = {"capture_output": True, "text": True, "check": check}
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    if env is not None:
        kwargs["env"] = env
    return _sp.run(full, **kwargs)


def push_to_remote(repo_url, message=None, clean=False, branch=None, dry_run=False):
    """
    Clone `repo_url` into a temp dir, overlay the current project files, commit, push.

    Works whether the remote repo is brand new/empty or already holds an older copy
    (e.g. one created by dragging an earlier zip), and never rewrites history that
    isn't ours — so a Vercel project already connected to the repo stays connected.

    Returns a dict with keys: ok, remote, branch, commit, changed, message, log.
    """
    import tempfile

    message = message or f"Update Uburinzi Health — {time.strftime('%Y-%m-%d %H:%M')}"
    workdir = Path(tempfile.mkdtemp(prefix="uburinzi-push-"))
    log = []

    try:
        # 1. clone -----------------------------------------------------------
        log.append(f"$ git clone {_redact(repo_url)}")
        proc = _git(["clone", repo_url, str(workdir)], cwd=None, check=False)
        if proc.returncode != 0:
            return {"ok": False, "error": "clone failed", "detail": (proc.stderr or proc.stdout).strip(), "log": log}

        # 2. which branch does the remote actually use? ----------------------
        #    (a bare repo whose HEAD points at an unborn branch would otherwise
        #     make us push a brand-new second branch next to the real one)
        remote_heads = [
            h.strip().removeprefix("origin/")
            for h in _git(["branch", "-r", "--format", "%(refname:short)"], cwd=workdir, check=False).stdout.splitlines()
            if h.strip().startswith("origin/") and "->" not in h
        ]
        if not branch:
            current = _git(["symbolic-ref", "--short", "HEAD"], cwd=workdir, check=False).stdout.strip()
            current = current.removeprefix("origin/")
            if current in remote_heads:
                branch = current
            elif "main" in remote_heads:
                branch = "main"
            elif "master" in remote_heads:
                branch = "master"
            else:
                branch = current or "main"
        if branch in remote_heads:
            _git(["checkout", "-q", branch], cwd=workdir, check=False)
        if _git(["rev-parse", "--verify", "HEAD"], cwd=workdir, check=False).returncode != 0:
            _git(["checkout", "-B", branch], cwd=workdir, check=False)   # first commit
        log.append(f"branch: {branch} (remote has: {', '.join(remote_heads) or 'none yet'})")

        # 3. drop stale nested copies left by earlier zip uploads -----------
        #    (a top-level folder holding its own app/main.py is an old snapshot
        #     of this project, not part of the current tree)
        if clean:
            stale = find_stale_copies(workdir)
            for folder in stale:
                _git(["rm", "-r", "-q", "--ignore-unmatch", folder], cwd=workdir, check=False)
                shutil.rmtree(workdir / folder, ignore_errors=True)
            if stale:
                log.append(f"removed {len(stale)} stale nested cop{'y' if len(stale)==1 else 'ies'}: "
                           + ", ".join(f"{f}/" for f in stale))

        # 4. overlay every current source file ------------------------------
        wanted = set()
        for src, rel in iter_source_files():
            dest = workdir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.read_bytes() != (dest.read_bytes() if dest.exists() else None):
                shutil.copy2(src, dest)
            wanted.add(str(rel))

        # 5. remove tracked files we no longer ship -------------------------
        tracked = _git(["ls-files"], cwd=workdir).stdout.split()
        removed = [f for f in tracked if f not in wanted]
        if removed:
            _git(["rm", "-r", "-q", "--ignore-unmatch", *removed], cwd=workdir, check=False)
            log.append(f"removed {len(removed)} file(s) no longer in the project")

        # 6. stage + report --------------------------------------------------
        _git(["add", "-A"], cwd=workdir)
        status = _git(["status", "--porcelain"], cwd=workdir).stdout
        changed = [line[3:].strip() for line in status.splitlines() if line.strip()]
        if not changed:
            return {"ok": True, "remote": _redact(repo_url), "branch": branch,
                    "changed": 0, "message": "already up to date — nothing to push", "log": log}
        log.append(f"{len(changed)} file(s) changed")

        if dry_run:
            return {"ok": True, "remote": _redact(repo_url), "branch": branch, "changed": len(changed),
                    "files": changed, "message": "dry run — not pushed", "log": log}

        # 7. commit + push ----------------------------------------------------
        _git(["commit", "-m", message], cwd=workdir)
        sha = _git(["rev-parse", "--short", "HEAD"], cwd=workdir).stdout.strip()
        proc = _git(["push", "origin", branch], cwd=workdir, check=False)
        if proc.returncode != 0:
            return {"ok": False, "error": "push failed", "detail": (proc.stderr or proc.stdout).strip(),
                    "remote": _redact(repo_url), "branch": branch, "changed": len(changed), "log": log}
        log.append(f"pushed {sha} → {branch}")
        return {"ok": True, "remote": _redact(repo_url), "branch": branch,
                "commit": sha, "changed": len(changed), "files": changed, "message": message, "log": log}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _redact(url):
    """Hide a personal-access token if one is embedded in the URL."""
    import re as _re
    return _re.sub(r"://[^@/]+@", "://***@", str(url))

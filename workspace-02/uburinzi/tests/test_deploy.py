"""Everything the Vercel deploy and the Play Store listing depend on."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import settings_store
from app.db import DBSession
from app.main import app

client = TestClient(app)

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------- Vercel
def test_vercel_entry_point_exposes_the_asgi_app():
    """Vercel imports api/index.py and looks for `app`."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "api" / "index.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "app"), "Vercel needs a module-level `app`"


def test_vercel_json_declares_crons_and_routes():
    config = json.loads((ROOT / "vercel.json").read_text())
    assert config["routes"], "all traffic must reach the ASGI function"
    paths = [c["path"] for c in config["crons"]]
    assert any("cron/scheduler" in p for p in paths), "serverless needs cron instead of a thread"
    assert config["env"]["UBURINZI_SCHEDULER"] == "false"


def test_serverless_disables_the_background_scheduler(monkeypatch):
    import importlib

    import app.config as config

    monkeypatch.setenv("VERCEL", "1")
    reloaded = importlib.reload(config)
    assert reloaded.RUNNING_SERVERLESS is True
    assert reloaded.SCHEDULER_ENABLED is False
    monkeypatch.delenv("VERCEL")
    importlib.reload(config)


def test_cron_endpoint_runs_the_pipeline():
    response = client.get("/api/cron/scheduler?daily=1")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert "scheduler" in body and "escalations" in body


def test_cron_endpoint_is_locked_when_a_secret_is_set(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    assert client.get("/api/cron/scheduler").status_code == 401
    assert client.get("/api/cron/scheduler", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/cron/scheduler", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    monkeypatch.delenv("CRON_SECRET")


# --------------------------------------------------------------- Play Store
def test_assetlinks_is_served_at_the_well_known_path():
    response = client.get("/.well-known/assetlinks.json")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    body = response.json()
    assert body[0]["target"]["package_name"] == "rw.uburinzi.health"


def test_assetlinks_includes_the_configured_fingerprint():
    with DBSession() as db:
        settings_store.set_value(db, "play_signing_sha256", "AA:BB:CC:DD")
    body = client.get("/.well-known/assetlinks.json").json()
    assert "AA:BB:CC:DD" in body[0]["target"]["sha256_cert_fingerprints"]
    with DBSession() as db:
        settings_store.set_value(db, "play_signing_sha256", "")


def test_privacy_policy_page_is_public():
    response = client.get("/privacy")
    assert response.status_code == 200
    text = response.text.lower()
    for word in ("privacy", "consent", "stop", "delete"):
        assert word in text, f"privacy policy must mention {word}"


def test_manifest_meets_play_store_requirements():
    manifest = json.loads((ROOT / "static" / "manifest.webmanifest").read_text())
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["name"] and manifest["short_name"]
    sizes = {i["sizes"] for i in manifest["icons"]}
    assert "512x512" in sizes, "Play requires a 512x512 icon"
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"])


def test_store_screenshots_exist():
    shots = sorted((ROOT / "docs" / "store").glob("*.png"))
    assert len(shots) >= 2, "Play requires at least two phone screenshots"

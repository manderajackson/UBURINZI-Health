"""UI strings for the web dashboard (separate from patient-facing SMS copy)."""
from __future__ import annotations

from app.config import LANGUAGES

UI = {
    "app_name": {"rw": "Uburinzi Health", "en": "Uburinzi Health", "fr": "Uburinzi Health", "sw": "Uburinzi Health"},
    "dashboard": {"rw": "Imbonerahamwe", "en": "Dashboard", "fr": "Tableau de bord", "sw": "Dashibodi"},
    "patients": {"rw": "Abarwayi", "en": "Patients", "fr": "Patients", "sw": "Wagonjwa"},
    "alerts": {"rw": "Amatangazo", "en": "Alerts", "fr": "Alertes", "sw": "Tahadhari"},
    "messages": {"rw": "Ubutumwa", "en": "Messages", "fr": "Messages", "sw": "Ujumbe"},
    "protocols": {"rw": "Amabwiriza", "en": "Protocols", "fr": "Protocoles", "sw": "Itifaki"},
    "simulator": {"rw": "Igerageza", "en": "SMS Simulator", "fr": "Simulateur SMS", "sw": "Kijaribio SMS"},
    "settings": {"rw": "Igenamiterere", "en": "Settings", "fr": "Parametres", "sw": "Mipangilio"},
    "logout": {"rw": "Sohoka", "en": "Log out", "fr": "Deconnexion", "sw": "Toka"},
}


def t(key: str, lang: str = "en", fallback: str | None = None) -> str:
    bucket = UI.get(key, {})
    return bucket.get(lang) or bucket.get("en") or fallback or key.replace("_", " ").title()


def language_name(code: str) -> str:
    return LANGUAGES.get(code, code)

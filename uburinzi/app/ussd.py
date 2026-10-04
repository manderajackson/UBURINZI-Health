"""USSD check-in channel — the two-way path that works on a basic Rwandan phone.

Rwanda has no inbound A2P SMS: a patient cannot reply to an alphanumeric sender
ID, and the handset itself says so. USSD fills that gap -- it is interactive,
costs nothing to the patient when the clinic pays, and runs on every 2G handset
with no data connection. Africa's Talking lists USSD for Rwanda.

Flow (Africa's Talking posts sessionId / serviceCode / phoneNumber / text):
    text == ""            -> CON menu
    text == "1|2|3"       -> record the answer, END with a confirmation
    anything else         -> END asking them to try again
"""
from __future__ import annotations

from sqlalchemy import select

from app import settings_store
from app.models import Patient
from app.timeutils import now

# Menu and confirmation copy, kept short: a USSD screen holds ~182 characters.
MENU = {
    "rw": "Muraho {name}. Hitamo:\n1=Nafashe imiti\n2=Sinfashe imiti\n3=Sindashize neza",
    "en": "Hello {name}. Choose:\n1=Took my medication\n2=Did not take it\n3=Not feeling well",
    "fr": "Bonjour {name}. Choisissez :\n1=J'ai pris mes medicaments\n2=Je ne les ai pas pris\n3=Je ne me sens pas bien",
    "sw": "Habari {name}. Chagua:\n1=Nimekunywa dawa\n2=Sikunywa\n3=Sijisikii vizuri",
}

THANKS = {
    "1": {
        "rw": "Murakoze! Twanditse ko wafashe imiti yawe.",
        "en": "Thank you. We recorded that you took your medication.",
        "fr": "Merci. Nous avons note que vous avez pris vos medicaments.",
        "sw": "Asante. Tumerekodi kuwa umekunywa dawa.",
    },
    "2": {
        "rw": "Murakoze. Umuforomo wawe arabimenyeshwa kugirango agufashe.",
        "en": "Thank you. Your nurse has been notified so they can help.",
        "fr": "Merci. Votre infirmier est informe et va vous aider.",
        "sw": "Asante. Muuguzi wako amejulishwa ili akusaidie.",
    },
    "3": {
        "rw": "Murakoze. Umuforomo wawe arabimenyeshwa vuba.",
        "en": "Thank you. Your nurse has been notified and will follow up.",
        "fr": "Merci. Votre infirmier est informe et vous suivra.",
        "sw": "Asante. Muuguzi wako amejulishwa na atafuatilia.",
    },
}

RETRY = {
    "rw": "Ntabwo twumvise. Kanda *{code}# hanyuma uhitemo 1, 2 cyangwa 3.",
    "en": "Sorry, we did not understand. Dial *{code}# and choose 1, 2 or 3.",
    "fr": "Desole, nous n'avons pas compris. Composez *{code} et choisissez 1, 2 ou 3.",
    "sw": "Samahani, hatukuelewa. Piga *{code}# kisha chagua 1, 2 au 3.",
}

UNKNOWN = {
    "rw": "Ntimubaruwe kuri iyi serivisi. Mubaze ivuriro ryanyu.",
    "en": "This number is not enrolled yet. Please ask your clinic to register you.",
    "fr": "Ce numero n'est pas encore inscrit. Demandez a votre clinique de vous inscrire.",
    "sw": "Namba hii haijasajiliwa. Tafadhali muulize kliniki yako ikusajili.",
}


def _lang(patient: Patient | None, session) -> str:
    language = (getattr(patient, "language", "") if patient else "") or "en"
    return language if language in MENU else "en"


def ussd_code(session) -> str:
    """The dial string patients use, e.g. `384*96#` (AT sends the * for us)."""
    return (settings_store.get(session, "ussd_code", "") or "").strip().strip("*#")


SHORT = {
    "rw": "Kanda *{code}#.",
    "en": "Dial *{code}#.",
    "fr": "Composez *{code}#.",
    "sw": "Piga *{code}#.",
}


def instruction(session, patient=None, short: bool = False) -> str:
    """Line that tells the patient how to answer, when USSD carries the reply.

    `short=True` is the fallback used when the full sentence would push the
    message over one 160-character SMS segment.
    """
    code = ussd_code(session)
    if not code:
        return ""
    lang = _lang(patient, session)
    if short:
        return SHORT.get(lang, SHORT["en"]).format(code=code)
    if lang == "rw":
        return f"Subiza ukanda *{code}# hanyuma uhitemo 1, 2 cyangwa 3."
    if lang == "fr":
        return f"Repondez en composant *{code}# puis choisissez 1, 2 ou 3."
    if lang == "sw":
        return f"Jibu kwa kupiga *{code}# kisha chagua 1, 2 au 3."
    return f"Reply by dialling *{code}# and choosing 1, 2 or 3."


def handle_ussd(session, *, session_id: str, phone: str, text: str, service_code: str = "") -> str:
    """Return the raw `CON …` / `END …` body Africa's Talking expects."""
    from app.engine import normalize_phone, process_inbound

    digits = (text or "").strip().strip("*#")
    # a nested menu selection arrives as "1*2"; we only need the last choice
    if "*" in digits:
        digits = digits.split("*")[-1]

    phone = normalize_phone(phone)
    patient = session.execute(select(Patient).where(Patient.phone == phone)).scalar_one_or_none()
    lang = _lang(patient, session)
    code = ussd_code(session) or "XXX"

    if not digits:
        if patient is None:
            return "END " + UNKNOWN.get(lang, UNKNOWN["en"])
        return "CON " + MENU.get(lang, MENU["en"]).format(name=patient.first_name)

    if patient is None:
        return "END " + UNKNOWN.get(lang, UNKNOWN["en"])

    if digits not in THANKS:
        return "END " + RETRY.get(lang, RETRY["en"]).format(code=code)

    process_inbound(
        session,
        phone,
        digits,
        provider_id=f"ussd:{session_id}" if session_id else "",
        received_at=now(),
        channel="ussd",
    )
    session.commit()
    return "END " + THANKS[digits].get(lang, THANKS[digits]["en"])

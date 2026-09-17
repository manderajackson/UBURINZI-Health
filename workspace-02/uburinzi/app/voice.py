"""Africa's Talking Voice XML builders for the Uburinzi IVR.

Flow for an automated check-in call:

    <Response>
      <Play url="…"/>            ← optional pre-recorded Kinyarwanda prompt
      <Say …>Hello Marie, this is Uburinzi Health…</Say>
      <GetDigits numDigits="1" timeout="8" finishOnKey="#" callbackUrl="…/dtmf">
        <Say>Press 1 …</Say>
      </GetDigits>
      <Say>We did not get your answer. A nurse will call you. Goodbye.</Say>
    </Response>

AT's text-to-speech does not yet support Kinyarwanda, so for Kinyarwanda cohorts
we recommend a pre-recorded prompt URL (recorded with a local speaker) via
`voice_prompt_url` on the Channels page; `<Play>` takes precedence over `<Say>`.
"""
from __future__ import annotations

from html import escape
from xml.etree import ElementTree as ET

# AT TTS languages we can rely on.
TTS_LANGUAGES = {
    "en": "en-US",
    "sw": "sw-KE",
    "fr": "fr-FR",
    "rw": "en-US",  # fallback: Kinyarwanda needs a recorded prompt
}


def _say(parent: ET.Element, text: str, language: str = "en-US", voice: str = "woman") -> None:
    ET.SubElement(
        parent,
        "Say",
        {"voice": voice, "language": TTS_LANGUAGES.get(language, language) or "en-US", "playBeep": "false"},
    ).text = escape(text)


def response_xml(root: ET.Element) -> str:
    return b'<?xml version="1.0" encoding="UTF-8"?>\n'.decode() + ET.tostring(root, encoding="unicode")


def checkin_call_xml(
    *,
    greeting: str,
    digits_prompt: str,
    callback_url: str,
    goodbye: str,
    language: str = "en-US",
    play_url: str | None = None,
    timeout: int = 8,
) -> str:
    """Full IVR script: greet → ask for 1/2/3 → thank (or fall through)."""
    root = ET.Element("Response")

    if play_url:
        ET.SubElement(root, "Play", {"url": play_url})
    else:
        _say(root, greeting, language)

    get_digits = ET.SubElement(
        root,
        "GetDigits",
        {"numDigits": "1", "timeout": str(timeout), "finishOnKey": "#", "callbackUrl": callback_url},
    )
    if play_url:
        ET.SubElement(get_digits, "Play", {"url": play_url})
    else:
        _say(get_digits, digits_prompt, language)

    _say(root, goodbye, language)
    return response_xml(root)


def dtmf_response_xml(*, thanks: str, language: str = "en-US") -> str:
    """What the patient hears after pressing a key (call ends right after)."""
    root = ET.Element("Response")
    _say(root, thanks, language)
    return response_xml(root)


def goodbye_xml(text: str, language: str = "en-US") -> str:
    root = ET.Element("Response")
    _say(root, text, language)
    return response_xml(root)


# --------------------------------------------------------------- prompt copy
PROMPTS = {
    "en": (
        "Hello {first_name}, this is {clinic} calling with your medication reminder.",
        "Press 1 if you took your medicine today. Press 2 if you missed it. Press 3 if you are not feeling well.",
        "Thank you. Take care and see you at your next appointment. Goodbye.",
    ),
    "rw": (
        # Read by a recorded human voice (AT TTS fallback is English).
        "Muraho {first_name}, ni {clinic} irakwibutsa gufata imiti yawe.",
        "Kanda 1 niba wafashe imiti uyu munsi. Kanda 2 niba utayifashe. Kanda 3 niba utameze neza.",
        "Murakoze. Murabeho, tuzongera kukwibutsa.",
    ),
    "fr": (
        "Bonjour {first_name}, ici {clinic}, rappel pour vos medicaments.",
        "Appuyez sur 1 si vous avez pris vos medicaments. Sur 2 si vous les avez oublies. Sur 3 si vous ne vous sentez pas bien.",
        "Merci, bonne journee.",
    ),
    "sw": (
        "Habari {first_name}, hapa ni {clinic} kukukumbusha dawa zako.",
        "Bonyeza 1 ikiwa umekunywa dawa leo. Bonyeza 2 ikiwa hukunywa. Bonyeza 3 ikiwa hujisikii vizuri.",
        "Asante, kwaheri.",
    ),
}

ACK = {
    "en": {"yes": "Thank you. Well done.", "no": "Thank you. Please take your dose now if your clinician told you to.", "unwell": "We are sorry. A nurse from the clinic will call you back today.", None: "Sorry, we did not understand. A nurse will call you."},
    "rw": {"yes": "Murakoze cyane.", "no": "Murakoze. Fata ikinini cyawe ubu niba muganga yarabikubwiye.", "unwell": "Mwihangane, umuforomo wa kliniki azaguhamagara uyu munsi.", None: "Sinabyumvise, umuforomo azaguhamagara."},
    "fr": {"yes": "Merci beaucoup.", "no": "Merci. Prenez votre dose maintenant.", "unwell": "Un infirmier vous rappellera aujourd'hui.", None: "Desole, je n'ai pas compris."},
    "sw": {"yes": "Asante sana.", "no": "Asante. Kunywa dawa sasa.", "unwell": "Muuguzi atakupigia simu leo.", None: "Samahani, sikuelewa."},
}


def prompts_for(language: str, first_name: str, clinic: str) -> tuple[str, str, str]:
    template = PROMPTS.get(language, PROMPTS["en"])
    return tuple(text.format(first_name=first_name, clinic=clinic) for text in template)


def ack_for(language: str, choice: str | None) -> str:
    return ACK.get(language, ACK["en"]).get(choice, ACK["en"][None])

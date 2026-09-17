"""Clinical programmes, monitoring cadences and default message copy.

Every protocol is data, not code: adding a country or a new chronic condition
is a dictionary entry. Cadences follow the *spirit* of Rwanda's national NCD
and HIV/TB guidelines but MUST be signed off by the clinic's clinical advisor
before a real cohort is enrolled (see README → Clinical governance).
"""
from __future__ import annotations

PROGRAMS: dict[str, dict] = {
    "diabetes": {
        "label": "Diabetes (Type 1 & 2)",
        "short": "Diabetes",
        "color": "#2563eb",
        "cadence_days": 3,
        "education_every_days": 7,
        "checkins_per_week": 2,
        "missed_dose_red": 3,
        "missed_dose_amber": 2,
        "no_reply_amber": 3,
        "default_medication": "Metformin / Insulin",
    },
    "hypertension": {
        "label": "Hypertension",
        "short": "HTN",
        "color": "#7c3aed",
        "cadence_days": 7,
        "education_every_days": 14,
        "checkins_per_week": 1,
        "missed_dose_red": 2,
        "missed_dose_amber": 1,
        "no_reply_amber": 2,
        "default_medication": "Amlodipine / Hydrochlorothiazide",
    },
    "hiv": {
        "label": "HIV / ART adherence",
        "short": "HIV",
        "color": "#db2777",
        "cadence_days": 7,
        "education_every_days": 14,
        "checkins_per_week": 1,
        "missed_dose_red": 2,
        "missed_dose_amber": 1,
        "no_reply_amber": 2,
        "default_medication": "ARV (TLD)",
    },
    "tb": {
        "label": "TB treatment support",
        "short": "TB",
        "color": "#ea580c",
        "cadence_days": 2,
        "education_every_days": 10,
        "checkins_per_week": 3,
        "missed_dose_red": 3,
        "missed_dose_amber": 2,
        "no_reply_amber": 2,
        "default_medication": "RHZE (4-month / 6-month regimen)",
    },
    "anc": {
        "label": "Antenatal care (ANC)",
        "short": "ANC",
        "color": "#0d9488",
        "cadence_days": 14,
        "education_every_days": 14,
        "checkins_per_week": 0.5,
        "missed_dose_red": 2,
        "missed_dose_amber": 1,
        "no_reply_amber": 2,
        "default_medication": "Iron + Folic acid",
    },
}

PROGRAM_KEYS = list(PROGRAMS)

# ---------------------------------------------------------------- default copy
# placeholders: {first_name} {clinic} {condition} {medication} {date} {time}
CHECKIN: dict[str, dict[str, str]] = {
    "diabetes": {
        "rw": "Muraho {first_name}, ni {clinic} binyuze kuri Uburinzi Health. Ese wafashe imiti ya diyabete yawe uyu munsi? Subiza: 1=Yego, 2=Oya, 3=Sindashize neza.",
        "en": "Hello {first_name}, this is {clinic} via Uburinzi Health. Did you take your diabetes medication today? Reply 1=Yes, 2=No, 3=Not feeling well.",
        "fr": "Bonjour {first_name}, ici {clinic} via Uburinzi Health. Avez-vous pris vos medicaments contre le diabete aujourd'hui? Repondez: 1=Oui, 2=Non, 3=Je ne me sens pas bien.",
        "sw": "Habari {first_name}, hapa ni {clinic} kupitia Uburinzi Health. Umekunywa dawa yako ya kisukari leo? Jibu: 1=Ndio, 2=Hapana, 3=Sijisikii vizuri.",
    },
    "hypertension": {
        "rw": "Muraho {first_name}, ni {clinic}. Ese wafashe imiti y'umuvuduko w'amaraso uyu munsi? Subiza: 1=Yego, 2=Oya, 3=Sindashize neza.",
        "en": "Hello {first_name}, this is {clinic}. Did you take your blood pressure medication today? Reply 1=Yes, 2=No, 3=Not feeling well.",
        "fr": "Bonjour {first_name}, ici {clinic}. Avez-vous pris votre medicament contre l'hypertension aujourd'hui? Repondez: 1=Oui, 2=Non, 3=Je ne me sens pas bien.",
        "sw": "Habari {first_name}, hapa ni {clinic}. Umekunywa dawa yako ya shinikizo la damu leo? Jibu: 1=Ndio, 2=Hapana, 3=Sijisikii vizuri.",
    },
    "hiv": {
        "rw": "Muraho {first_name}, ni {clinic}. Ese wafashe ARV zawe uyu munsi nk'uko bisanzwe? Subiza: 1=Yego, 2=Oya, 3=Sindashize neza.",
        "en": "Hello {first_name}, this is {clinic}. Did you take your ARV dose today as prescribed? Reply 1=Yes, 2=No, 3=Not feeling well.",
        "fr": "Bonjour {first_name}, ici {clinic}. Avez-vous pris vos ARV aujourd'hui comme prescrit? Repondez: 1=Oui, 2=Non, 3=Je ne me sens pas bien.",
        "sw": "Habari {first_name}, hapa ni {clinic}. Umekunywa dawa zako za ARV leo kama ulivyoagizwa? Jibu: 1=Ndio, 2=Hapana, 3=Sijisikii vizuri.",
    },
    "tb": {
        "rw": "Muraho {first_name}, ni {clinic}. Ese wafashe imiti ya TB yawe uyu munsi? Ntugasibe imiti. Subiza: 1=Yego, 2=Oya, 3=Sindashize neza.",
        "en": "Hello {first_name}, this is {clinic}. Did you take your TB medication today? Please do not skip doses. Reply 1=Yes, 2=No, 3=Not feeling well.",
        "fr": "Bonjour {first_name}, ici {clinic}. Avez-vous pris vos medicaments contre la tuberculose aujourd'hui? Repondez: 1=Oui, 2=Non, 3=Je ne me sens pas bien.",
        "sw": "Habari {first_name}, hapa ni {clinic}. Umekunywa dawa yako ya TB leo? Jibu: 1=Ndio, 2=Hapana, 3=Sijisikii vizuri.",
    },
    "anc": {
        "rw": "Muraho {first_name}, ni {clinic}. Ese wafashe intungamubiri (iron/folic acid) zawe kandi wumva umeze neza? Subiza: 1=Yego, 2=Oya, 3=Sindashize neza.",
        "en": "Hello {first_name}, this is {clinic}. Did you take your iron/folic acid today, and are you feeling well? Reply 1=Yes, 2=No, 3=Not feeling well.",
        "fr": "Bonjour {first_name}, ici {clinic}. Avez-vous pris votre fer/acide folique aujourd'hui et vous sentez-vous bien? Repondez: 1=Oui, 2=Non, 3=Je ne me sens pas bien.",
        "sw": "Habari {first_name}, hapa ni {clinic}. Umekunywa dawa ya iron/folic acid leo na unajisikia vizuri? Jibu: 1=Ndio, 2=Hapana, 3=Sijisikii vizuri.",
    },
}

WELCOME = {
    "rw": "Muraho {first_name}, ikaze kuri Uburinzi Health bya {clinic}. Tuzakoherereza ubutumwa bugufi bwo kukwibutsa imiti na gahunda zawe zo kwivuza. Ntugomba kwishyura ubu butumwa. Subiza STOP niba udashaka kubona ubutumwa.",
    "en": "Welcome {first_name}, you are now enrolled in Uburinzi Health with {clinic}. We will send you short reminders about your medication and appointments. This service is free for you. Reply STOP to opt out.",
    "fr": "Bienvenue {first_name}, vous etes inscrit a Uburinzi Health avec {clinic}. Nous vous enverrons de courts rappels sur vos medicaments et rendez-vous. Repondez STOP pour vous desabonner.",
    "sw": "Karibu {first_name}, umesajiliwa katika Uburinzi Health na {clinic}. Tutakutumia ujumbe mfupi wa kukumbusha dawa na miadi yako. Jibu STOP kuacha.",
}

APPOINTMENT_REMINDER = {
    "rw": "Muraho {first_name}, turakwibutsa ko ufite gahunda yo kwivuza kuri {clinic} tariki {date} saa {time}. Subiza: 1=Nzaza, 2=Sinzabasha.",
    "en": "Hello {first_name}, reminder: your appointment at {clinic} is on {date} at {time}. Reply 1=I will attend, 2=I cannot make it.",
    "fr": "Bonjour {first_name}, rappel: votre rendez-vous a {clinic} est le {date} a {time}. Repondez: 1=Je viendrai, 2=Je ne pourrai pas.",
    "sw": "Habari {first_name}, ukumbusho: miadi yako ya {clinic} ni tarehe {date} saa {time}. Jibu: 1=Nitahudhuria, 2=Sitaweza.",
}

LAB_RESULT = {
    "rw": "Muraho {first_name}, ibisubizo byawe bya laboratwari byageze kuri {clinic}. Nyamuneka hamagara ivuriro kuri {phone} cyangwa uze ku gahunda yawe kugira ngo musuzume ibisubizo hamwe.",
    "en": "Hello {first_name}, your lab results have arrived at {clinic}. Please call the clinic on {phone} or attend your next appointment to review them together.",
    "fr": "Bonjour {first_name}, vos resultats de laboratoire sont arrives a {clinic}. Appelez la clinique au {phone} ou venez a votre rendez-vous pour les examiner.",
    "sw": "Habari {first_name}, majibu yako ya maabara yamefika {clinic}. Piga simu {phone} au hudhuria miadi yako ili kuyapitia.",
}

THANK_YES = {
    "rw": "Murakoze {first_name}! Twishimiye ko wafashe imiti yawe. Tuzongera kukwibutsa ubutaha.",
    "en": "Thank you {first_name}! Great job taking your medication. We will check in again soon.",
    "fr": "Merci {first_name}! Continuez ainsi. Nous vous recontacterons bientot.",
    "sw": "Asante {first_name}! Tutaendelea kukukumbusha.",
}

THANK_NO = {
    "rw": "Murakoze kubisubiza {first_name}. Niba wibagiwe, fata ikinini ubu niba muganga yarakubwiye kubikora. Niba ufite ikibazo, hamagara {clinic} kuri {phone}.",
    "en": "Thanks for replying {first_name}. If you forgot, please take your dose now unless your clinician told you otherwise. If you have a problem, call {clinic} on {phone}.",
    "fr": "Merci d'avoir repondu {first_name}. Si vous avez oublie, prenez votre dose maintenant. En cas de probleme, appelez {clinic} au {phone}.",
    "sw": "Asante kwa kujibu {first_name}. Umesahau, kunywa dawa sasa. Ukiwa na shida, piga {clinic} {phone}.",
}

UNWELL = {
    "rw": "Twumvise ko utameze neza, {first_name}. Ubu butumwa bwoherejwe kuri muganga wawe kuri {clinic}. Niba wumva bikabije, hamagara {phone} cyangwa ujye ku ivuriro rya bugufi ubu ngubu.",
    "en": "We are sorry you are not feeling well, {first_name}. Your clinician at {clinic} has been alerted. If symptoms are severe, call {phone} or go to the nearest health facility now.",
    "fr": "Nous sommes desoles que vous ne vous sentiez pas bien, {first_name}. Votre clinicien a {clinic} a ete alerte. Si les symptomes sont graves, appelez le {phone}.",
    "sw": "Pole kwa kutojisikia vizuri {first_name}. Daktari wako wa {clinic} amearifiwa. Ukiwa na dalili kali, piga {phone}.",
}

STOP_REPLY = {
    "rw": "Ubwisungane bwawe bwo kubona ubutumwa bwahagaritswe kuri {clinic}. Niba wifuza kongera kubona ubutumwa, hamagara {phone}. Murabeho!",
    "en": "You have been unsubscribed from {clinic} messages. To rejoin, call {phone}. Take care!",
    "fr": "Vous etes desabonne des messages de {clinic}. Pour vous reabonner, appelez le {phone}.",
    "sw": "Umeacha kupokea ujumbe wa {clinic}. Kujiunga tena, piga {phone}.",
}

UNKNOWN_REPLY = {
    "rw": "Sinabyumvise neza. Subiza 1=Yego, 2=Oya, cyangwa 3=Sindashize neza. Murakoze.",
    "en": "Sorry, I did not understand. Please reply 1=Yes, 2=No, or 3=Not feeling well. Thank you.",
    "fr": "Desole, je n'ai pas compris. Repondez 1=Oui, 2=Non, ou 3=Je ne me sens pas bien. Merci.",
    "sw": "Samahani, sikuelewa. Jibu 1=Ndio, 2=Hapana, au 3=Sijisikii vizuri.",
}

EDUCATION: dict[str, dict[str, list[str]]] = {
    "diabetes": {
        "rw": [
            "Inama: Rya imboga nyinshi n'imbuto, ugabanye isukari n'ibinyamavuta. Bifasha isukari yo mu maraso kuguma ku rugero.",
            "Inama: Kugenda n'amaguru iminota 30 buri munsi bituma umubiri ukoresha isukari neza.",
            "Inama: Suzuma ibirenge buri munsi; niba hari igikomere, bimenyeshe muganga vuba.",
            "Inama: Kunywa amazi ahagije no kwirinda inzoga nyinshi birinda diyabete kwiyongera.",
        ],
        "en": [
            "Tip: Fill half your plate with vegetables. Cutting sugar and oil keeps your blood glucose steady.",
            "Tip: A 30-minute walk most days helps your body use insulin better.",
            "Tip: Check your feet daily. Report any wound to your clinician quickly.",
            "Tip: Drink enough water and limit alcohol to protect your kidneys.",
        ],
        "fr": [
            "Conseil: Mangez beaucoup de legumes et reduisez le sucre et l'huile.",
            "Conseil: Marchez 30 minutes par jour pour mieux utiliser l'insuline.",
            "Conseil: Examinez vos pieds chaque jour; signalez toute plaie au medecin.",
            "Conseil: Buvez assez d'eau et limitez l'alcool pour proteger vos reins.",
        ],
        "sw": [
            "Kidokezo: Kula mboga nyingi, punguza sukari na mafuta.",
            "Kidokezo: Tembea dakika 30 kila siku ili mwili utumie sukari vizuri.",
            "Kidokezo: Kagua miguu yako kila siku; ripoti kidonda kwa daktari.",
            "Kidokezo: Kunywa maji ya kutosha na punguza pombe.",
        ],
    },
    "hypertension": {
        "rw": [
            "Inama: Gabanya umunyu mu biryo. Gukoresha umunyu muke bigabanya umuvuduko w'amaraso.",
            "Inama: Irinde stress, ruhuka bihagije kandi wirinde itabi.",
            "Inama: Fata imiti yawe buri munsi nubwo wumva umeze neza.",
        ],
        "en": [
            "Tip: Cut down on salt — less than one teaspoon a day lowers blood pressure.",
            "Tip: Manage stress, rest well, and avoid tobacco.",
            "Tip: Take your medicine every day even when you feel fine.",
        ],
        "fr": [
            "Conseil: Reduisez le sel — moins d'une cuillere a cafe par jour.",
            "Conseil: Gerez le stress, reposez-vous et evitez le tabac.",
            "Conseil: Prenez vos medicaments chaque jour meme si vous vous sentez bien.",
        ],
        "sw": [
            "Kidokezo: Punguza chumvi kwenye chakula chako.",
            "Kidokezo: Epuka msongo wa mawazo, pumzika na acha tumbaku.",
            "Kidokezo: Kunywa dawa kila siku hata ukiwa mzima.",
        ],
    },
    "hiv": {
        "rw": [
            "Inama: Gufata ARV buri munsi ku gihe kimwe bituma virusi igabanuka bikarinda ubuzima bwawe.",
            "Inama: Niba wibagiwe gufata ARV, fata ikinini ako kanya nk'uko muganga yabigusobanuriye.",
            "Inama: Kwisuzumisha viral load buri gihe byerekana ko imiti ikora neza.",
        ],
        "en": [
            "Tip: Taking ARVs at the same time every day keeps the virus suppressed.",
            "Tip: If you miss a dose, take it as soon as you remember as your clinician advised.",
            "Tip: Regular viral load tests show that your treatment is working.",
        ],
        "fr": [
            "Conseil: Prenez vos ARV a la meme heure chaque jour pour garder la charge virale basse.",
            "Conseil: Si vous oubliez une dose, prenez-la des que vous vous en souvenez.",
            "Conseil: Les tests de charge virale reguliers montrent que le traitement fonctionne.",
        ],
        "sw": [
            "Kidokezo: Kunywa ARV kila siku saa moja hudhibiti virusi.",
            "Kidokezo: Ukipitisha dozi, inywe mara unapokumbuka.",
            "Kidokezo: Pima viral load mara kwa mara kuona dawa inafanya kazi.",
        ],
    },
    "tb": {
        "rw": [
            "Inama: Kurangiza imiti ya TB yose nubwo wumva umeze neza; gusiba imiti bishobora gutuma indwara yongera kugaruka ikomeye.",
            "Inama: Fata imiti yawe buri munsi ku gihe kimwe, kandi wirinde kunywa inzoga.",
            "Inama: Fungura inzu yinjizemo umwuka mwiza kandi utwikire umunwa iyo ukorora.",
        ],
        "en": [
            "Tip: Finish all your TB medicine even when you feel better; stopping early can make TB come back stronger.",
            "Tip: Take your dose at the same time every day and avoid alcohol.",
            "Tip: Ventilate your room and cover your mouth when you cough.",
        ],
        "fr": [
            "Conseil: Terminez tous vos medicaments contre la tuberculose meme si vous vous sentez mieux.",
            "Conseil: Prenez vos doses a heure fixe et evitez l'alcool.",
            "Conseil: Aerez votre chambre et couvrez-vous la bouche quand vous toussez.",
        ],
        "sw": [
            "Kidokezo: Maliza dawa zote za TB hata ukiwa mzima.",
            "Kidokezo: Kunywa dawa kwa wakati mmoja kila siku na epuka pombe.",
            "Kidokezo: Ingiza hewa safi chumbani na funika mdomo unapokohoa.",
        ],
    },
    "anc": {
        "rw": [
            "Inama: Fata intungamubiri (iron/folic acid) buri munsi kandi witabire gahunda zose za ANC.",
            "Inama: Rya indyo yuzuye, unywe amazi ahagije kandi uruhuke bihagije.",
            "Inama: Niba ufite kuva amaraso, umutwe ukabije cyangwa ukubyimbirwa amaguru, hamagara ivuriro ako kanya.",
        ],
        "en": [
            "Tip: Take iron/folic acid daily and attend every ANC visit.",
            "Tip: Eat a balanced diet, drink enough water and rest well.",
            "Tip: Bleeding, severe headache or swollen legs? Call the clinic immediately.",
        ],
        "fr": [
            "Conseil: Prenez le fer/acide folique chaque jour et assistez a chaque consultation prenatale.",
            "Conseil: Mangez equilibre, buvez assez d'eau et reposez-vous.",
            "Conseil: Saignements, maux de tete violents ou jambes gonflees? Appelez la clinique.",
        ],
        "sw": [
            "Kidokezo: Kunywa iron/folic acid kila siku na hudhuria kliniki zote za ujauzito.",
            "Kidokezo: Kula chakula bora, kunywa maji na pumzika.",
            "Kidokezo: Kutoka damu, kuumwa sana kichwa au miguu kuvimba? Piga kliniki haraka.",
        ],
    },
}


def seed_templates(session) -> int:
    """Insert the default copy into message_templates (idempotent)."""
    from app.models import MessageTemplate

    existing = {
        (t.program, t.kind, t.language, t.variant)
        for t in session.query(MessageTemplate).all()
    }
    rows: list[MessageTemplate] = []

    def add(program, kind, lang, body, variant="default"):
        key = (program, kind, lang, variant)
        if key not in existing and body:
            rows.append(
                MessageTemplate(
                    program=program, kind=kind, language=lang, variant=variant, body=body
                )
            )

    for program, per_lang in CHECKIN.items():
        for lang, body in per_lang.items():
            add(program, "checkin", lang, body)

    for program, per_lang in EDUCATION.items():
        for lang, tips in per_lang.items():
            for i, tip in enumerate(tips):
                add(program, "education", lang, tip, variant=f"tip{i+1}")

    for lang, body in WELCOME.items():
        add("common", "welcome", lang, body)
    for lang, body in APPOINTMENT_REMINDER.items():
        add("common", "appointment", lang, body)
    for lang, body in LAB_RESULT.items():
        add("common", "lab_result", lang, body)
    for lang, body in THANK_YES.items():
        add("common", "ack_yes", lang, body)
    for lang, body in THANK_NO.items():
        add("common", "ack_no", lang, body)
    for lang, body in UNWELL.items():
        add("common", "ack_unwell", lang, body)
    for lang, body in STOP_REPLY.items():
        add("common", "stop", lang, body)
    for lang, body in UNKNOWN_REPLY.items():
        add("common", "unknown", lang, body)

    session.add_all(rows)
    return len(rows)

"""
Generate a synthetic corpus of Dutch (Flemish) BPMN files with injected PII.

Every text-bearing element (a `name` attribute, a <bpmn:documentation> or the
<bpmn:text> of a text annotation) is recorded in ground_truth.json together
with the exact character spans of the PII it contains, so detection output can
be scored. All people, numbers and addresses are fictitious.

Usage: python generate_bpmn.py [--out data/synthetic] [--seed 42] [--rounds 2]
"""

import argparse
import itertools
import json
import random
import re
import string
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def q(tag: str) -> str:
    return f"{{{NS['bpmn']}}}{tag}"


########################################################################
# Fake data
########################################################################

FIRST_NAMES = [
    "Jan", "Annelies", "Lotte", "Wout", "Sofie", "Pieter", "Els", "Koen",
    "Lieve", "Bart", "Nathalie", "Tom", "Hanne", "Jef", "Marleen", "Ruben",
    "Elke", "Dirk", "Inge", "Stijn", "Fien", "Mohamed", "Fatima", "Yusuf",
    "Ann-Sophie", "Jean-Pierre", "Griet", "Lander", "Nele", "Kristof",
]
LAST_NAMES = [
    "Peeters", "Janssens", "Maes", "Jacobs", "Mertens", "Willems", "Claes",
    "Goossens", "Wouters", "De Smet", "Vermeulen", "Van den Broeck",
    "De Clercq", "Lambrecht", "Vandenberghe", "Verhaeghe", "Coppens",
    "Van Damme", "D'Hondt", "Desmet", "Van de Velde", "El Amrani", "Yilmaz",
    "Vercammen", "De Backer", "Lemmens", "Huysmans", "Van Acker",
]
MUNICIPALITIES = [
    ("Poperinge", "8970", "057"), ("Aalter", "9880", "09"), ("Gent", "9000", "09"),
    ("Leuven", "3000", "016"), ("Hasselt", "3500", "011"), ("Mechelen", "2800", "015"),
    ("Brugge", "8000", "050"), ("Kortrijk", "8500", "056"), ("Genk", "3600", "089"),
    ("Aalst", "9300", "053"), ("Sint-Niklaas", "9100", "03"), ("Turnhout", "2300", "014"),
    ("Roeselare", "8800", "051"), ("Lier", "2500", "03"), ("Tienen", "3300", "016"),
]
STREETS = [
    "Kerkstraat", "Stationsstraat", "Dorpsstraat", "Molenstraat", "Nieuwstraat",
    "Schoolstraat", "Kapelstraat", "Grote Markt", "Veldstraat", "Sint-Jansstraat",
    "Leopoldlaan", "Ieperstraat", "Brugsesteenweg", "Koning Albertlaan", "Hoogstraat",
]
MONTHS = [
    "januari", "februari", "maart", "april", "mei", "juni", "juli",
    "augustus", "september", "oktober", "november", "december",
]
MAIL_DOMAINS = ["gmail.com", "telenet.be", "hotmail.com", "skynet.be", "outlook.be"]
ROLES = [
    "Burgemeester", "Schepen van Jeugd", "Diensthoofd Burgerzaken",
    "Algemeen directeur", "Financieel directeur", "Jeugdconsulent",
    "Omgevingsambtenaar", "Ambtenaar van de burgerlijke stand", "Mobiliteitsambtenaar",
]


def ascii_slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", text.lower())


def mod97_check(number: int) -> int:
    check = 97 - (number % 97)
    return check


class Faker:
    """Small deterministic generator for Belgian/Flemish PII values."""

    def __init__(self, rng: random.Random):
        self.rng = rng

    def person(self, municipality) -> dict:
        r = self.rng
        first, last = r.choice(FIRST_NAMES), r.choice(LAST_NAMES)
        year, month, day = r.randint(1945, 2006), r.randint(1, 12), r.randint(1, 28)
        return {
            "first": first,
            "last": last,
            "name": f"{first} {last}",
            "email": self.email(first, last, municipality),
            "phone": self.phone(municipality),
            "rrn": self.rrn(year, month, day),
            "dob": self.dob(year, month, day),
            "address": self.address(),
            "iban": self.iban(),
            "plate": self.plate(),
        }

    def email(self, first, last, municipality) -> str:
        r = self.rng
        local = r.choice([
            f"{ascii_slug(first)}.{ascii_slug(last)}",
            f"{ascii_slug(first)}{ascii_slug(last)}",
            f"{ascii_slug(first)[0]}{ascii_slug(last)}",
            f"{ascii_slug(first)}.{ascii_slug(last)}{r.randint(1, 99)}",
        ])
        domain = r.choice(MAIL_DOMAINS + [f"{ascii_slug(municipality[0])}.be"] * 3)
        return f"{local}@{domain}"

    def phone(self, municipality) -> str:
        r = self.rng
        if r.random() < 0.6:  # mobile
            p = f"4{r.randint(60, 99)}"
            a, b, c = r.randint(10, 99), r.randint(10, 99), r.randint(10, 99)
            return r.choice([
                f"0{p} {a} {b} {c}", f"0{p}/{a}.{b}.{c}", f"+32 {p} {a} {b} {c}",
                f"0{p}{a}{b}{c}", f"+32{p}{a}{b}{c}",
            ])
        zone = municipality[2]
        if len(zone) == 2:  # 02, 03, 09: 3-2-2 subscriber number
            a, b, c = r.randint(200, 999), r.randint(10, 99), r.randint(10, 99)
        else:  # 0xx: 2-2-2 subscriber number
            a, b, c = r.randint(20, 99), r.randint(10, 99), r.randint(10, 99)
        return r.choice([
            f"{zone} {a} {b} {c}", f"{zone}/{a}.{b}.{c}", f"+32 {zone[1:]} {a} {b} {c}",
        ])

    def rrn(self, year, month, day) -> str:
        r = self.rng
        seq = r.randint(1, 997)
        base = int(f"{year % 100:02d}{month:02d}{day:02d}{seq:03d}")
        check = mod97_check(base + (2_000_000_000 if year >= 2000 else 0))
        digits = f"{year % 100:02d}{month:02d}{day:02d}{seq:03d}{check:02d}"
        yy, mm, dd, sss, cc = digits[:2], digits[2:4], digits[4:6], digits[6:9], digits[9:]
        return r.choice([
            f"{yy}.{mm}.{dd}-{sss}.{cc}",  # official notation
            digits,
            f"{yy}{mm}{dd} {sss} {cc}",
            f"{yy}{mm}{dd}-{sss}-{cc}",
        ])

    def dob(self, year, month, day) -> str:
        return self.rng.choice([
            f"{day:02d}/{month:02d}/{year}",
            f"{day:02d}-{month:02d}-{year}",
            f"{day} {MONTHS[month - 1]} {year}",
        ])

    def address(self) -> str:
        r = self.rng
        name, postcode, _ = r.choice(MUNICIPALITIES)
        number = str(r.randint(1, 180)) + r.choice(["", "", "", "A", " bus 2"])
        return f"{r.choice(STREETS)} {number}, {postcode} {name}"

    def iban(self) -> str:
        r = self.rng
        bank, account = r.randint(1, 999), r.randint(0, 9_999_999)
        first10 = int(f"{bank:03d}{account:07d}")
        acc_check = first10 % 97 or 97
        bban = f"{first10:010d}{acc_check:02d}"
        # Belgium = B(11) E(14); check digits from BBAN + "111400"
        iban_check = 98 - int(bban + "111400") % 97
        iban = f"BE{iban_check:02d}{bban}"
        return " ".join(iban[i:i + 4] for i in range(0, 16, 4))

    def plate(self) -> str:
        r = self.rng
        letters = "".join(r.choice(string.ascii_uppercase) for _ in range(3))
        return f"{r.randint(1, 2)}-{letters}-{r.randint(0, 999):03d}"

    def kbo(self) -> str:
        base = self.rng.randint(2_000_000, 9_999_999)  # 0 + 7 digits
        check = mod97_check(base)
        digits = f"0{base:07d}{check:02d}"
        return f"{digits[:4]}.{digits[4:7]}.{digits[7:]}"

    def casenr(self) -> str:
        r = self.rng
        return r.choice([
            f"{r.randint(2022, 2025)}{r.randint(1, 12):02d}{r.randint(1, 28):02d}{r.randint(1, 999):03d}",
            f"OMV_{r.randint(2022, 2025)}{r.randint(1, 999_999):06d}",
        ])


########################################################################
# Templates
########################################################################

# placeholder -> entity label (None = filled in, but not PII)
PLACEHOLDERS = {
    "name": "PERSON", "name2": "PERSON", "first": "PERSON", "last": "PERSON",
    "email": "EMAIL", "phone": "PHONE", "rrn": "RRN", "iban": "IBAN",
    "address": "ADDRESS", "dob": "DATE_OF_BIRTH", "plate": "LICENSE_PLATE",
    "kbo": "KBO",
    "municipality": None, "role": None, "casenr": None,
}

# Short labels for `name` attributes of tasks, data objects, flows, ...
NAME_PII = [
    "Doorsturen naar {name}",
    "Advies vragen aan {name}",
    "Bellen naar {phone}",
    "Mail naar {email}",
    "Contact {first} ({phone})",
    "Controle RRN {rrn}",
    "Terugbetaling op {iban}",
    "Plaatsbezoek {address}",
    "Nummerplaat {plate} registreren",
    "Facturatie KBO {kbo}",
    "Dossier {name} (°{dob})",
    "Aanvraagformulier {name}",
    "Goedkeuring door dhr. {last}",
    "Rijksregister {rrn} opvragen",
    "Bevestiging naar {email} sturen",
]
NAME_CLEAN = [
    "Advies {role}", "Beslissing college van burgemeester en schepenen",
    "Uiterlijk 31 augustus", "Binnen 30 dagen", "Registreren in Mercurius",
    "Opmaak besluit", "Doorsturen naar Stad {municipality}",
    "Dossiernummer {casenr} aanmaken", "Agenderen gemeenteraad",
    "Betaling ontvangen", "Archiveren dossier",
]
# OPH jargon: system names, acronyms, CamelCase and single words that recur across
# real diagrams and that NER tends to flag as PERSON / LOCATION / ORGANIZATION.
NAME_JARGON = [
    "DOSIS", "ADM", "ICM", "FOX", "eID", "BOSA", "VDAB", "OCMW", "CSAM", "MAGDA",
    "GaNaar", "NaKijken", "Afgerond", "Herinnering", "Authentication", "Moraliteitsonderzoek",
    "Mercurius", "Burgerprofiel", "eBox", "SharePoint",
    "Registratie in DOSIS", "ICM-ticket aanmaken", "Check KBO", "Afgerond?",
    "Herinnering versturen", "Moraliteitsonderzoek aanvragen", "Inbox ADM", "GaNaar loket",
    "Upload in FOX", "Aanmelden via eID", "Melding aan VDAB", "Doorverwijzen naar OCMW",
    "Nazicht BOSA", "Authentication via CSAM", "Opvragen in MAGDA", "Bericht in eBox",
]
# Lanes and participants named after a person (happens in practice)
LANE_PII = ["{name}", "{first} - Burgerzaken", "{name} (dossierbeheerder)"]

DOC_PII = [
    "Contactpersoon: {name} ({email}, {phone}).",
    "Bij afwezigheid van {name} neemt {name2} het dossier over.",
    "Aanvrager {name}, wonende te {address}, geboren op {dob}, rijksregisternummer {rrn}.",
    "Terugbetaling van de waarborg gebeurt op rekening {iban} op naam van {name}.",
    "Voertuig met nummerplaat {plate} krijgt een bewonerskaart voor zone Centrum.",
    "Organisator: vzw Jeugdhuis De Kroeg, ondernemingsnummer {kbo}, verantwoordelijke {name} ({phone}).",
    "Vragen? Mail {email} of bel {phone} tijdens de kantooruren.",
    "Opgelet: {first} controleert enkel dossiers die voor 12u binnenkomen.",
    "Zie mail van dhr. {last} van 3 maart over de ontbrekende stukken.",
    "Testdossier: INSZ {rrn}, adres {address}.",
    "Het {role} ondertekent; bij twijfel eerst overleggen met {name}.",
]
DOC_CLEAN = [
    "Volgens het Decreet van 22 december 2017 over het lokaal bestuur beslist het college binnen 30 dagen.",
    "M 12 = met begeleiders categorie B",
    "De aanvraag wordt behandeld door de dienst Burgerzaken van Gemeente {municipality}.",
    "Termijn: 30 kalenderdagen na ontvangst van het volledige dossier.",
    "Dossiernummer {casenr} wordt automatisch toegekend door het zaaksysteem.",
    "Raadpleeg https://www.vlaanderen.be/rijbewijs voor de geldende wetgeving.",
    "Het {role} ondertekent het besluit.",
    "Aanvragen die na 1 september binnenkomen, worden pas in het volgende werkjaar behandeld.",
]

ANNOT_PII = [
    "Navragen bij {first}",
    "Telefoon {name}: {phone}",
    "TODO: {name} nog bevestigen",
    "Rekeningnummer {iban}",
    "INSZ {rrn}",
    "Adres: {address}",
    "Back-up: {email}",
]
ANNOT_CLEAN = [
    "Geen meting in FOX",
    "Manueel proces",
    "Te bespreken met {role}",
    "Zie KB van 23 maart 1998",
    "Digitaal via e-loket",
    "Ref. {casenr}",
]


def fill(template: str, persona: dict, persona2: dict, extra: dict):
    """Fill placeholders; return (text, spans) with spans on the filled text."""
    text, spans, pos = "", [], 0
    for m in re.finditer(r"\{(\w+)\}", template):
        text += template[pos:m.start()]
        key = m.group(1)
        if key == "name2":
            value = persona2["name"]
        elif key in persona:
            value = persona[key]
        else:
            value = extra[key]
        entity = PLACEHOLDERS[key]
        if entity:
            spans.append({"start": len(text), "end": len(text) + len(value),
                          "entity": entity, "value": value})
        text += value
        pos = m.end()
    text += template[pos:]
    assert text == text.strip()
    return text, spans


class Cycler:
    """Hand out templates in shuffled rounds so each one is used about equally."""

    def __init__(self, items, rng):
        self.items, self.rng, self.queue = list(items), rng, []

    def next(self):
        if not self.queue:
            self.queue = self.items[:]
            self.rng.shuffle(self.queue)
        return self.queue.pop()


########################################################################
# Process skeletons
########################################################################

PROCESSES = [
    {
        "slug": "aanvraag-rijbewijs", "title": "Aanvraag rijbewijs",
        "lanes": ["Burger", "Dienst Burgerzaken", "FOD Mobiliteit"],
        "start": "Burger meldt zich aan het loket",
        "tasks": ["Identiteit controleren", "Attest rijschool nakijken", "Pasfoto inscannen",
                  "Aanvraag registreren in Mercurius", "Betaling innen", "Rijbewijs afleveren"],
        "gateway": "Attest geldig?", "end": "Rijbewijs afgeleverd",
        "data": ["Voorlopig rijbewijs", "Attest rijschool"],
    },
    {
        "slug": "fuifkwaliteitslabel", "title": "Jeugd - Fuifkwaliteitslabel aanvraag",
        "lanes": ["Organisator", "Jeugddienst", "Schepencollege", "Financiële dienst"],
        "start": "1 maand voor de fuif",
        "tasks": ["Invullen aanvraagformulier", "Evaluatie aanvraag", "Invullen evaluatieformulier",
                  "Beslissing college", "Uitbetaling premie"],
        "gateway": "Aanvraag volledig?", "end": "Label toegekend",
        "data": ["Aanvraagformulier", "Evaluatieformulier"],
    },
    {
        "slug": "omgevingsvergunning", "title": "Omgevingsvergunning - gewone procedure",
        "lanes": ["Aanvrager", "Dienst Omgeving", "Gemeentelijke omgevingsambtenaar", "College"],
        "start": "Aanvraag ingediend via omgevingsloket",
        "tasks": ["Ontvankelijkheid onderzoeken", "Openbaar onderzoek organiseren",
                  "Adviezen opvragen", "Verslag opmaken", "Beslissing nemen", "Beslissing bekendmaken"],
        "gateway": "Ontvankelijk en volledig?", "end": "Vergunning verleend",
        "data": ["Bouwplannen", "Adviezen"],
    },
    {
        "slug": "adreswijziging", "title": "Adreswijziging",
        "lanes": ["Inwoner", "Dienst Bevolking", "Wijkagent"],
        "start": "Aangifte adreswijziging",
        "tasks": ["Aangifte registreren", "Woonstvaststelling aanvragen", "Woonstvaststelling uitvoeren",
                  "Inschrijving in bevolkingsregister", "Adres op eID aanpassen"],
        "gateway": "Positieve woonstvaststelling?", "end": "Adres gewijzigd",
        "data": ["Verslag wijkagent", "Aangifteformulier"],
    },
    {
        "slug": "huwelijk", "title": "Aangifte huwelijk",
        "lanes": ["Toekomstige echtgenoten", "Dienst Burgerlijke Stand", "Parket"],
        "start": "Aangifte van huwelijk",
        "tasks": ["Documenten nakijken", "Akte van aangifte opmaken", "Advies parket vragen",
                  "Datum huwelijk vastleggen", "Huwelijk voltrekken", "Huwelijksboekje afleveren"],
        "gateway": "Vermoeden schijnhuwelijk?", "end": "Huwelijk voltrokken",
        "data": ["Akte van aangifte", "Huwelijksboekje"],
    },
    {
        "slug": "bewonerskaart", "title": "Aanvraag bewonerskaart parkeren",
        "lanes": ["Bewoner", "Parkeerbedrijf", "Dienst Mobiliteit"],
        "start": "Aanvraag via e-loket",
        "tasks": ["Inschrijving in zone controleren", "Inschrijvingsbewijs voertuig nakijken",
                  "Retributie aanrekenen", "Bewonerskaart digitaal activeren"],
        "gateway": "Gedomicilieerd in de zone?", "end": "Bewonerskaart actief",
        "data": ["Inschrijvingsbewijs voertuig"],
    },
    {
        "slug": "subsidie-vereniging", "title": "Werkingssubsidie verenigingen",
        "lanes": ["Vereniging", "Dienst Vrije Tijd", "Adviesraad", "Financiële dienst"],
        "start": "Oproep werkingssubsidie gepubliceerd",
        "tasks": ["Subsidiedossier indienen", "Ontvankelijkheid toetsen", "Advies adviesraad",
                  "Puntentoekenning", "Goedkeuring college", "Subsidie uitbetalen"],
        "gateway": "Erkende vereniging?", "end": "Subsidie uitbetaald",
        "data": ["Jaarverslag", "Financieel verslag"],
    },
    {
        "slug": "evenementenvergunning", "title": "Evenementenvergunning",
        "lanes": ["Organisator", "Evenementenloket", "Politie", "Brandweer", "Burgemeester"],
        "start": "Aanvraag evenement minstens 3 maanden vooraf",
        "tasks": ["Aanvraag screenen", "Veiligheidsoverleg plannen", "Advies politie",
                  "Advies brandweer", "Vergunning opmaken", "Vergunning ondertekenen"],
        "gateway": "Risicovol evenement?", "end": "Vergunning afgeleverd",
        "data": ["Veiligheidsplan", "Inplantingsplan"],
    },
    {
        "slug": "leefloon", "title": "Aanvraag leefloon",
        "lanes": ["Aanvrager", "Maatschappelijk werker", "Bijzonder comité sociale dienst"],
        "start": "Hulpvraag aan het onthaal",
        "tasks": ["Sociaal onderzoek voeren", "Bestaansmiddelen nagaan", "Verslag opmaken",
                  "Beslissing comité", "Beslissing betekenen", "Leefloon uitbetalen"],
        "gateway": "Voldoet aan voorwaarden?", "end": "Leefloon toegekend",
        "data": ["Sociaal verslag", "Rekeninguittreksels"],
    },
    {
        "slug": "melding-openbaar-domein", "title": "Melding schade openbaar domein",
        "lanes": ["Melder", "Meldpunt", "Technische dienst"],
        "start": "Melding via app of telefoon",
        "tasks": ["Melding registreren", "Prioriteit bepalen", "Herstelling inplannen",
                  "Herstelling uitvoeren", "Melder informeren"],
        "gateway": "Dringend?", "end": "Melding afgesloten",
        "data": ["Foto's schade"],
    },
]


########################################################################
# Building one BPMN file
########################################################################

class Builder:
    def __init__(self, rng: random.Random, faker: Faker, cyclers: dict, municipality):
        self.rng, self.faker, self.cyclers = rng, faker, cyclers
        self.municipality = municipality
        # A file has a few recurring people, like real process documentation
        self.people = [faker.person(municipality) for _ in range(3)]
        self.records = []
        self.used_ids = set()

    def new_id(self, prefix: str) -> str:
        while True:
            suffix = "".join(self.rng.choice(string.ascii_lowercase + string.digits) for _ in range(7))
            if f"{prefix}_{suffix}" not in self.used_ids:
                self.used_ids.add(f"{prefix}_{suffix}")
                return f"{prefix}_{suffix}"

    def text(self, template: str):
        persona, persona2 = self.rng.sample(self.people, 2)
        extra = {
            "municipality": self.municipality[0],
            "role": self.rng.choice(ROLES),
            "casenr": self.faker.casenr(),
            "kbo": self.faker.kbo(),
        }
        return fill(template, persona, persona2, extra)

    def pick(self, pii_pool: str, clean_pool: str, p_pii: float):
        pool = pii_pool if self.rng.random() < p_pii else clean_pool
        return self.text(self.cyclers[pool].next())

    def record(self, element_id, element_type, location, text, spans):
        self.records.append({
            "element_id": element_id, "element_type": element_type,
            "location": location, "text": text, "spans": spans,
        })

    def named(self, parent, tag, prefix, name_and_spans=None, **attrs):
        el = ET.SubElement(parent, q(tag), {"id": self.new_id(prefix), **attrs})
        if name_and_spans is not None:
            name, spans = name_and_spans
            el.set("name", name)
            self.record(el.get("id"), tag, "name", name, spans)
        return el

    def documentation(self, el, p_pii=0.6):
        text, spans = self.pick("DOC_PII", "DOC_CLEAN", p_pii)
        doc = ET.Element(q("documentation"))
        doc.text = text
        el.insert(0, doc)  # documentation comes first in BPMN
        self.record(el.get("id"), el.tag.split("}")[1], "documentation", text, spans)

    def build(self, proc: dict) -> ET.Element:
        r = self.rng
        defs = ET.Element(q("definitions"), {
            "id": self.new_id("Definitions"),
            "targetNamespace": "http://bpmn.io/schema/bpmn",
            "exporter": "Camunda Modeler", "exporterVersion": "5.14.0",
        })
        process_id = self.new_id("Process")

        collab = self.named(defs, "collaboration", "Collaboration")
        title = f"{proc['title']} {self.municipality[0]}"
        main = self.named(collab, "participant", "Participant", (title, []), processRef=process_id)
        if r.random() < 0.5:
            self.documentation(main, p_pii=0.5)
        # External black-box pool, sometimes named after a person
        ext_name = self.text("{name}") if r.random() < 0.4 else (proc["lanes"][0], [])
        ext = self.named(collab, "participant", "Participant", ext_name)

        process = ET.SubElement(defs, q("process"), {"id": process_id, "isExecutable": "false"})
        lane_set = ET.SubElement(process, q("laneSet"), {"id": self.new_id("LaneSet")})
        lanes = []
        for lane_name in proc["lanes"]:
            if r.random() < 0.2:
                lane_name, spans = self.text(r.choice(LANE_PII))
            else:
                spans = []
            lanes.append(self.named(lane_set, "lane", "Lane", (lane_name, spans)))

        # Flow nodes: start -> tasks (with a gateway after the first) -> end
        nodes = []
        start = self.named(process, "startEvent", "StartEvent", (proc["start"], []))
        nodes.append(start)
        tasks = []
        for i, task_name in enumerate(proc["tasks"]):
            roll = r.random()
            if roll < 0.35:
                label = self.text(self.cyclers["NAME_PII"].next())
            elif roll < 0.5:
                label = self.text(self.cyclers["NAME_CLEAN"].next())
            elif roll < 0.75:
                label = self.text(self.cyclers["NAME_JARGON"].next())
            else:
                label = (task_name, [])
            tag = r.choice(["task", "userTask", "userTask", "manualTask", "serviceTask"])
            task = self.named(process, tag, "Activity", label)
            if r.random() < 0.35:
                self.documentation(task)
            tasks.append(task)
            nodes.append(task)
            if i == 0:
                gateway = self.named(process, "exclusiveGateway", "Gateway", (proc["gateway"], []))
                nodes.append(gateway)
        end_label = self.text(self.cyclers["NAME_JARGON"].next()) if r.random() < 0.5 else (proc["end"], [])
        end_ok = self.named(process, "endEvent", "Event", end_label)
        end_nok = self.named(process, "endEvent", "Event", ("Aanvraag geweigerd", []))
        nodes.append(end_ok)

        # Sequence flows (gateway branches labelled Ja / Nee)
        flows = []
        for src, tgt in zip(nodes, nodes[1:]):
            label = ("Ja", []) if src is gateway else None
            flows.append(self.named(process, "sequenceFlow", "Flow", label,
                                    sourceRef=src.get("id"), targetRef=tgt.get("id")))
        flows.append(self.named(process, "sequenceFlow", "Flow", ("Nee", []),
                                sourceRef=gateway.get("id"), targetRef=end_nok.get("id")))
        for node in nodes + [end_nok]:
            for flow in flows:
                if flow.get("sourceRef") == node.get("id"):
                    ET.SubElement(node, q("outgoing")).text = flow.get("id")
                if flow.get("targetRef") == node.get("id"):
                    ET.SubElement(node, q("incoming")).text = flow.get("id")

        # Spread flow nodes over the lanes
        for i, node in enumerate(nodes + [end_nok]):
            ET.SubElement(lanes[i % len(lanes)], q("flowNodeRef")).text = node.get("id")

        # Data objects (some named after the system they live in), sometimes with a person in the name
        jargon_data = [self.cyclers["NAME_JARGON"].next() for _ in range(r.randint(1, 3))]
        for data_name in proc["data"] + jargon_data:
            data_obj_id = self.new_id("DataObject")
            if r.random() < 0.3:
                label = self.text(self.cyclers["NAME_PII"].next())
            else:
                label = (data_name, [])
            self.named(process, "dataObjectReference", "DataObjectReference", label,
                       dataObjectRef=data_obj_id)
            ET.SubElement(process, q("dataObject"), {"id": data_obj_id})

        # Text annotations attached to random tasks
        for _ in range(r.randint(2, 4)):
            text, spans = self.pick("ANNOT_PII", "ANNOT_CLEAN", 0.55)
            ann = ET.SubElement(process, q("textAnnotation"), {"id": self.new_id("TextAnnotation")})
            ET.SubElement(ann, q("text")).text = text
            self.record(ann.get("id"), "textAnnotation", "text", text, spans)
            ET.SubElement(process, q("association"), {
                "id": self.new_id("Association"),
                "sourceRef": r.choice(tasks).get("id"), "targetRef": ann.get("id"),
            })

        # Message flow between the external pool and the process
        msg_label = self.text(self.cyclers["NAME_PII"].next()) if r.random() < 0.4 else ("Aanvraag", [])
        self.named(collab, "messageFlow", "Flow", msg_label,
                   sourceRef=ext.get("id"), targetRef=start.get("id"))
        return defs


########################################################################
# Main
########################################################################

def validate(path: Path, records: list):
    root = ET.parse(path).getroot()
    for rec in records:
        el = root.find(f".//*[@id='{rec['element_id']}']")
        assert el is not None, rec
        if rec["location"] == "name":
            actual = el.get("name")
        elif rec["location"] == "documentation":
            actual = el.find("bpmn:documentation", NS).text
        else:
            actual = el.find("bpmn:text", NS).text
        assert actual == rec["text"], (actual, rec)
        for span in rec["spans"]:
            assert actual[span["start"]:span["end"]] == span["value"], (actual, span)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/synthetic")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rounds", type=int, default=2,
                        help="number of files per process skeleton (each in another municipality)")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    faker = Faker(rng)
    cyclers = {name: Cycler(globals()[name], rng) for name in
               ["NAME_PII", "NAME_CLEAN", "NAME_JARGON", "DOC_PII", "DOC_CLEAN", "ANNOT_PII", "ANNOT_CLEAN"]}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.bpmn"):
        old.unlink()

    ground_truth = []
    municipalities = itertools.cycle(rng.sample(MUNICIPALITIES, len(MUNICIPALITIES)))
    for proc in PROCESSES * args.rounds:
        municipality = next(municipalities)
        builder = Builder(rng, faker, cyclers, municipality)
        root = builder.build(proc)
        ET.indent(root, space="  ")
        filename = f"{proc['slug']}-{ascii_slug(municipality[0])}.bpmn"
        path = out / filename
        path.write_bytes(ET.tostring(root, encoding="UTF-8", xml_declaration=True) + b"\n")
        validate(path, builder.records)
        for rec in builder.records:
            ground_truth.append({"file": filename, **rec})

    (out / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2, ensure_ascii=False) + "\n")

    n_spans = sum(len(r["spans"]) for r in ground_truth)
    print(f"{len(PROCESSES) * args.rounds} files, {len(ground_truth)} text elements, {n_spans} PII spans -> {out}")


if __name__ == "__main__":
    main()

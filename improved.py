"""
Configurable version of the PII pipeline, to switch improvements on one by one.

With the default PipelineConfig() the detections are identical to
baseline_service (checked in 01_improvements.ipynb); every field switches one
improvement on top of that.
"""

import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
from functools import cache
from io import StringIO
from pathlib import Path

import regex
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider, SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import PhoneRecognizer

from baseline_service.anonymization import mask_spans

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

# Entity types that are actually relevant for BPMN content
RELEVANT_ENTITIES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IBAN_CODE",
    "CREDIT_CARD",
    "BELGIAN_NATIONAL_REGISTRY",
    "PERSON",
    "LOCATION",
]
# Added by the Belgian recognizers
BELGIAN_ENTITIES = [
    "BE_ENTERPRISE_NUMBER",
    "BE_LICENSE_PLATE",
    "BE_ADDRESS",
    "DATE_OF_BIRTH",
]


@dataclass(frozen=True)
class PipelineConfig:
    name: str = "baseline"
    entities: tuple | None = None  # None = every entity Presidio knows
    default_threshold: float = 0.6
    thresholds: dict = field(
        default_factory=dict
    )  # per entity, overrides default_threshold
    allow_list: tuple | None = None  # exact, case-insensitive
    rrn_checksum: bool = False  # validate the mod-97 check digits
    acronym_gate: bool = False  # no PERSON/LOCATION on short all-caps tokens
    dedup: bool = False  # review unique values; mask every occurrence
    scan_text_elements: bool = False  # also <documentation> and <textAnnotation><text>
    belgian_recognizers: bool = (
        False  # BE phone, KBO, plates, addresses, DOB, RRN with spaces
    )
    extend_names: bool = False  # grow PERSON matches over surname particles
    mask_name_parts: bool = False  # with dedup: also mask the parts of approved names
    whole_document: bool = False  # analyze one text per diagram instead of per element
    # with whole_document: "lines" (XML order), "typed" (+ element type per line),
    # "flow" (typed, in process-flow order) or "story" (flow order, framed as sentences)
    document_layout: str = "lines"
    ner_model: str = (
        "md"  # "md" (the service's model), "lg" or "transformer", see NER_MODELS
    )

    def __hash__(self):
        return hash(repr(self))


def load_allow_list(path="allow_list.txt") -> tuple:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return tuple(l.strip() for l in lines if l.strip() and not l.startswith("#"))


########################################################################
# Recognizers
########################################################################

# Same as baseline_service/identification.py
RRN_REGEX = r"\b\d{2}[.\-]?\d{2}[.\-]?\d{2}[.\-]?\d{3}[.\-]?\d{2}\b"
# Also allows spaces as separator ("850730 033 61")
RRN_REGEX_SPACES = r"\b\d{2}[.\- ]?\d{2}[.\- ]?\d{2}[.\- ]?\d{3}[.\- ]?\d{2}\b"
RRN_CONTEXT = ["rijksregisternummer", "INSZ", "NISS"]


def rrn_is_valid(number: str) -> bool:
    """Belgian national registry number: 97 - (first 9 digits mod 97), with a '2' prefix for births from 2000."""
    digits = re.sub(r"\D", "", number)
    if len(digits) != 11:
        return False
    base, check = int(digits[:9]), int(digits[9:])
    return check in (97 - base % 97, 97 - (2_000_000_000 + base) % 97)


def kbo_is_valid(number: str) -> bool:
    """Belgian enterprise number: last 2 digits = 97 - (first 8 digits mod 97)."""
    digits = re.sub(r"\D", "", number)
    if len(digits) == 9:
        digits = "0" + digits
    return len(digits) == 10 and int(digits[8:]) == 97 - int(digits[:8]) % 97


class ChecksumPatternRecognizer(PatternRecognizer):
    """
    PatternRecognizer whose matches are dropped when the checksum fails.

    Without a validator it behaves exactly like a plain PatternRecognizer
    (validate_result returning None means "not validated" to Presidio).
    """

    def __init__(self, validator: Callable[[str], bool] | None, **kwargs):
        self.validator = validator
        super().__init__(**kwargs)

    def validate_result(self, pattern_text: str) -> bool | None:
        return self.validator(pattern_text) if self.validator else None


def rrn_recognizer(checksum: bool, spaces: bool) -> PatternRecognizer:
    return ChecksumPatternRecognizer(
        rrn_is_valid if checksum else None,
        supported_entity="BELGIAN_NATIONAL_REGISTRY",
        supported_language="nl",
        patterns=[
            Pattern(
                "BELGIAN_RRN_PATTERN", RRN_REGEX_SPACES if spaces else RRN_REGEX, 0.85
            )
        ],
        context=RRN_CONTEXT,
    )


CASE_SENSITIVE = regex.M | regex.S  # PatternRecognizer default also has regex.I

STREET_SUFFIX = r"(?:straat|laan|steenweg|weg|plein|markt|dreef|lei|kaai|singel|baan|pad|hof|ring|vest)"
STREET_PREFIX = r"(?:(?:Koning|Koningin|Prins|Sint|Onze|Lange|Korte|Oude|Nieuwe|Grote|Kleine|Hoge) )"
STREET = rf"{STREET_PREFIX}?[A-Z][\w'-]*?{STREET_SUFFIX}|Grote Markt"
HOUSE_NR = r"\d{1,4}[A-Za-z]?(?: bus \d+)?"
POSTCODE_CITY = r"[1-9]\d{3} [A-Z][\w'-]+(?: [A-Z][\w'-]+)?"
DATE = r"(?:\d{1,2}[/-]\d{1,2}[/-](?:19|20)\d{2}|\d{1,2} (?:januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december) (?:19|20)\d{2})"


def belgian_recognizers() -> list:
    return [
        PhoneRecognizer(
            supported_language="nl",
            supported_regions=("BE",),
            context=["tel", "telefoon", "gsm", "bel", "bellen", "contact", "nummer"],
        ),
        ChecksumPatternRecognizer(
            kbo_is_valid,
            supported_entity="BE_ENTERPRISE_NUMBER",
            supported_language="nl",
            patterns=[
                Pattern("KBO", r"\b(?:BE ?)?[01]\d{3}[. ]?\d{3}[. ]?\d{3}\b", 0.6)
            ],
            context=["ondernemingsnummer", "KBO", "btw", "btw-nummer"],
        ),
        PatternRecognizer(
            supported_entity="BE_LICENSE_PLATE",
            supported_language="nl",
            patterns=[Pattern("BE_PLATE", r"\b[1-9]-[A-Z]{3}-\d{3}\b", 0.6)],
            context=["nummerplaat", "kenteken", "voertuig", "wagen"],
            global_regex_flags=CASE_SENSITIVE,
        ),
        PatternRecognizer(
            supported_entity="BE_ADDRESS",
            supported_language="nl",
            patterns=[
                # street + number + postcode + municipality: must beat a LOCATION hit on the municipality alone
                Pattern(
                    "BE_ADDRESS_FULL",
                    rf"\b(?:{STREET}) {HOUSE_NR},? {POSTCODE_CITY}",
                    0.9,
                ),
                Pattern("BE_ADDRESS_STREET", rf"\b(?:{STREET}) {HOUSE_NR}\b", 0.6),
            ],
            context=["adres", "wonende", "woonplaats", "plaatsbezoek"],
            global_regex_flags=CASE_SENSITIVE,
        ),
        PatternRecognizer(
            supported_entity="DATE_OF_BIRTH",
            supported_language="nl",
            patterns=[
                Pattern("DOB_MARKED", rf"(?<=°\s?){DATE}", 0.85),
                Pattern("DOB_CONTEXT", rf"(?<=geboren (?:op )?){DATE}", 0.85),
            ],
            context=["geboren", "geboortedatum"],
        ),
    ]


########################################################################
# Analyzer
########################################################################


# NER models (notebook 03). "md" is the configuration of baseline_service/identification.py.
TRANSFORMER_NER = (
    "wietsedv/bert-base-dutch-cased-finetuned-conll2002-ner"  # BERTje, CoNLL-2002
)
NER_MODELS = {
    "md": {
        "nlp_engine_name": "spacy",
        "models": [
            {"lang_code": "nl", "model_name": "nl_core_news_md"},
            {"lang_code": "en", "model_name": "en_core_web_md"},
        ],
    },
    "lg": {
        "nlp_engine_name": "spacy",
        "models": [
            {"lang_code": "nl", "model_name": "nl_core_news_lg"},
            {"lang_code": "en", "model_name": "en_core_web_md"},
        ],
    },
    "transformer": {
        "nlp_engine_name": "transformers",
        "models": [
            {
                "lang_code": "nl",
                # spaCy only tokenizes here; the transformer does the NER
                "model_name": {
                    "spacy": "nl_core_news_md",
                    "transformers": TRANSFORMER_NER,
                },
            }
        ],
        "ner_model_configuration": {
            "labels_to_ignore": ["O"],
            # "first": a word gets the label of its first word piece. Presidio's default "max"
            # loses the last part of names that BERTje splits ("Huys" + "##mans"), see notebook 03.
            "aggregation_strategy": "first",
            "alignment_mode": "expand",
            # BERTje's CoNLL-2002 labels, lower- and uppercase
            "model_to_presidio_entity_mapping": {
                label: entity
                for short, entity in [
                    ("per", "PERSON"),
                    ("loc", "LOCATION"),
                    ("org", "ORGANIZATION"),
                    ("misc", "MISC"),
                ]
                for label in (short, short.upper())
            },
        },
    },
}


@cache
def nlp_engine(model: str = "md"):
    """The Presidio NLP engine for a model in NER_MODELS; built once per model."""
    return NlpEngineProvider(nlp_configuration=NER_MODELS[model]).create_engine()


def spacy_model(language: str = "nl", model: str = "md"):
    """The spaCy pipeline that Presidio uses for a language and model (for inspecting NER output)."""
    engine = nlp_engine(model)
    assert isinstance(engine, SpacyNlpEngine) and engine.nlp is not None
    return engine.nlp[language]


def ner_entities(doc) -> list:
    """(text, label) of the NER entities in a doc from spacy_model(): doc.ents for spaCy models,
    the span group of the transformer pipeline otherwise."""
    spans = doc.spans.get("bert-base-ner", doc.ents)
    return [(span.text, span.label_, span.start_char, span.end_char) for span in spans]


@cache
def build_analyzer(cfg: PipelineConfig) -> AnalyzerEngine:
    languages = [m["lang_code"] for m in NER_MODELS[cfg.ner_model]["models"]]
    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine(cfg.ner_model), supported_languages=languages
    )
    analyzer.registry.add_recognizer(
        rrn_recognizer(cfg.rrn_checksum, spaces=cfg.belgian_recognizers)
    )
    if cfg.belgian_recognizers:
        analyzer.registry.remove_recognizer("PhoneRecognizer", language="nl")
        for rec in belgian_recognizers():
            analyzer.registry.add_recognizer(rec)
    return analyzer


def filter_overlaps(spans: list) -> list:
    """Copy of baseline_service.identification.filter_overlaps (that module loads models on import)."""
    sorted_spans = sorted(spans, key=lambda r: r["score"], reverse=True)
    kept = []
    for span in sorted_spans:
        if not any(span["start"] < k["end"] and k["start"] < span["end"] for k in kept):
            kept.append(span)
    return sorted(kept, key=lambda r: r["start"])


ACRONYM = re.compile(r"^[A-Z0-9]{2,6}$")

# Surname particles (Dutch, French, Arabic, ...); matched case-insensitively
NAME_PARTICLES = (
    "van", "de", "der", "den", "het", "ter", "ten", "te", "vanden", "vander",
    "el", "al", "le", "la", "du", "da", "di", "dos", "von",
)  # fmt: skip
_PARTICLE = "(?i:" + "|".join(NAME_PARTICLES) + ")"
_CAP_WORD = r"[A-ZÀ-Ý][\w'’-]*"
_NAME_WORD = rf"(?!{_PARTICLE}\b){_CAP_WORD}"  # capitalized, but not a particle
# Spaces only (no newlines), so a name never grows into the next element
NAME_RIGHT = re.compile(rf"((?: {_PARTICLE}\b)*) {_NAME_WORD}")
NAME_LEFT = re.compile(rf"(?<![\w'’-])((?:{_NAME_WORD} )?)((?:{_PARTICLE} )*)$")

# Counters for the notebook (analyze calls, detections crossing element boundaries)
STATS: Counter = Counter()


def _is_particle(word: str) -> bool:
    return word.lower() in NAME_PARTICLES


def extend_name(text: str, start: int, end: int) -> tuple[int, int]:
    """
    Grow a PERSON span over surname particles, e.g. "Yusuf El" -> "Yusuf El Amrani",
    "Velde" -> "Elke Van de Velde". Only where particles are involved, so
    "Contact Koen" stays "Koen".
    """
    words = text[start:end].split()
    if not words:
        return start, end
    right = NAME_RIGHT.match(text, end)
    if right and (right.group(1) or _is_particle(words[-1])):
        end = right.end()
    left = NAME_LEFT.search(text, 0, start)
    if left and (left.group(2) or _is_particle(words[0])) and left.group(0):
        start = left.start()
    return start, end


def detect_text(text: str, cfg: PipelineConfig) -> list:
    """detect_pii from the service, plus the switched-on improvements."""
    analyzer = build_analyzer(cfg)
    entities = list(cfg.entities) if cfg.entities else None
    # Anchored regexes: a term only suppresses a detection that is exactly that term.
    # Presidio's default regex_flags for the allow-list already ignore case.
    allow_list = (
        [rf"\A{re.escape(term)}\Z" for term in cfg.allow_list]
        if cfg.allow_list
        else None
    )

    def analyze(language: str):
        return analyzer.analyze(
            text=text,
            language=language,
            entities=entities,
            allow_list=allow_list,
            allow_list_match="regex",
        )

    STATS["analyze_calls"] += 1
    try:
        raw = analyze("nl")
    except ValueError:
        raw = analyze("en")
    # Presidio orders equal-score results of the same span via a set, which changes from
    # run to run (hash seed); break such ties by entity type so results are reproducible.
    raw = sorted(
        raw, key=lambda r: (-r.score, r.start, -(r.end - r.start), r.entity_type)
    )

    results = []
    for r in raw:
        if cfg.extend_names and r.entity_type == "PERSON":
            r.start, r.end = extend_name(text, r.start, r.end)
        match = text[r.start : r.end]
        if r.score < cfg.thresholds.get(r.entity_type, cfg.default_threshold):
            continue
        if (
            cfg.acronym_gate
            and r.entity_type in ("PERSON", "LOCATION")
            and ACRONYM.match(match)
        ):
            continue
        results.append(
            {
                "start": r.start,
                "end": r.end,
                "entity": r.entity_type,
                "score": round(float(r.score), 3),
                "match": match,
            }
        )
    return filter_overlaps(results)


########################################################################
# BPMN
########################################################################


def _q(tag):
    return f"{{{BPMN_NS}}}{tag}"


def text_elements(root: ET.Element, cfg: PipelineConfig) -> list:
    """(element, element_id, location, stripped text) for every text that gets scanned."""
    out = []
    for el in root.iter():
        if "name" in el.attrib:  # same as baseline_service.bpmn.extract_elem_from_bpmn
            out.append((el, el.attrib.get("id", ""), "name", el.attrib["name"].strip()))
    if cfg.scan_text_elements:
        for el in root.iter():
            doc = el.find(_q("documentation"))
            if doc is not None and doc.text and doc.text.strip():
                out.append((doc, el.get("id", ""), "documentation", doc.text.strip()))
            if el.tag == _q("textAnnotation"):
                txt = el.find(_q("text"))
                if txt is not None and txt.text and txt.text.strip():
                    out.append((txt, el.get("id", ""), "text", txt.text.strip()))
    return out


# Line prefixes for the "typed" and "flow" layouts
ELEMENT_LABELS = {
    "participant": "Pool", "lane": "Lane",
    "task": "Taak", "userTask": "Taak", "manualTask": "Taak", "serviceTask": "Taak",
    "startEvent": "Start", "endEvent": "Einde", "exclusiveGateway": "Beslissing",
    "sequenceFlow": "Pijl", "messageFlow": "Bericht", "dataObjectReference": "Gegevens",
    "documentation": "Documentatie", "text": "Notitie",
}  # fmt: skip

TASKS = {
    "task", "userTask", "manualTask", "serviceTask", "sendTask", "receiveTask",
    "scriptTask", "businessRuleTask", "callActivity", "subProcess",
}  # fmt: skip
GATEWAYS = {
    "exclusiveGateway",
    "inclusiveGateway",
    "parallelGateway",
    "eventBasedGateway",
    "complexGateway",
}
EVENTS = {"intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"}
LOCATION_ORDER = {"name": 0, "documentation": 1, "text": 2}


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _kind(item: tuple) -> str:
    """Element type of a text element: the tag for a name, else 'documentation' / 'text'."""
    el, _, location, _ = item
    return _local(el.tag) if location == "name" else location


def bpmn_document(xml: str, cfg: PipelineConfig) -> tuple[str, list[dict]]:
    """
    All scanned text of a diagram as one document, for a single analyze call.

    Layouts (cfg.document_layout):
    - "lines": one element per line in document order (a name, then its documentation)
    - "typed": the same, each line prefixed with the element type ("Taak: ...")
    - "flow":  typed lines, ordered along the process flow
    - "story": flow order, each element framed as a Dutch sentence
    Lines without closing punctuation get a "." so the NLP model sees sentence boundaries.

    Returns (text, segments); each segment maps text[start:end] back to
    (element_id, location) and equals that element's stripped text.
    """
    root = ET.fromstring(xml)
    items = text_elements(root, cfg)
    layout = cfg.document_layout
    if layout in ("lines", "typed"):
        order = {el: i for i, el in enumerate(root.iter())}
        items = sorted(items, key=lambda t: order[t[0]])
    elif layout in ("flow", "story"):
        items = _flow_order(root, items)
    else:
        raise ValueError(f"unknown document_layout {layout!r}")

    if layout == "story":
        pieces = _story_frames(root, items)
    elif layout == "lines":
        pieces = [("", item, "") for item in items]
    else:
        pieces = [(f"{ELEMENT_LABELS.get(_kind(t), _kind(t))}: ", t, "") for t in items]
    return _write_document(pieces)


def _write_document(pieces: list) -> tuple[str, list[dict]]:
    """(frame before, text element, frame after) per line -> (text, segments)."""
    lines, segments, pos = [], [], 0
    for before, (_, element_id, location, text), after in pieces:
        end = after or ("" if text[-1] in ".!?:" else ".")
        line = before + text + end + "\n"
        start = pos + len(before)
        segments.append(
            {
                "start": start,
                "end": start + len(text),
                "element_id": element_id,
                "location": location,
            }
        )
        lines.append(line)
        pos += len(line)
    return "".join(lines), segments


def _flow_order(root: ET.Element, items: list) -> list:
    """
    Text elements ordered along the process: pools and lanes first, then per process the
    flow nodes depth-first from the start events (each followed by its documentation, its
    labelled outgoing flows and the annotations attached to it), then the remaining
    elements of the process (data objects, ...), then message flows and anything left.
    Every text element appears exactly once.
    """
    parent = {child: p for p in root.iter() for child in p}
    owner = {id(t): t[0] if t[2] == "name" else parent[t[0]] for t in items}
    by_owner: dict = {}
    for t in sorted(items, key=lambda t: LOCATION_ORDER[t[2]]):
        by_owner.setdefault(owner[id(t)], []).append(t)
    doc_order = {el: i for i, el in enumerate(root.iter())}
    by_id = {el.get("id"): el for el in root.iter() if el.get("id")}

    ordered, done = [], set()

    def emit(el):
        if el is not None and el not in done:
            done.add(el)
            ordered.extend(by_owner.get(el, []))

    def visit(node, outgoing: dict, attached: dict):
        """A flow node, its annotations, then each outgoing flow and its target (depth-first)."""
        if node is None or node in done:
            return
        emit(node)
        for annotation in attached.get(node.get("id"), []):
            emit(annotation)
        for f in outgoing.get(node.get("id"), []):
            emit(f)
            visit(by_id.get(f.get("targetRef")), outgoing, attached)

    for tag in ("participant", "lane"):
        for el in root.iter(_q(tag)):
            emit(el)

    for process in root.iter(_q("process")):
        children = list(process)
        flows = [c for c in children if _local(c.tag) == "sequenceFlow"]
        outgoing: dict = {}
        for f in flows:
            outgoing.setdefault(f.get("sourceRef"), []).append(f)
        attached: dict = {}  # node id -> text annotations connected to it
        for a in (c for c in children if _local(c.tag) == "association"):
            src, tgt = by_id.get(a.get("sourceRef")), by_id.get(a.get("targetRef"))
            for node, other in ((src, tgt), (tgt, src)):
                if (
                    node is not None
                    and other is not None
                    and _local(other.tag) == "textAnnotation"
                ):
                    attached.setdefault(node.get("id"), []).append(other)

        for start in (c for c in children if _local(c.tag) == "startEvent"):
            visit(start, outgoing, attached)
        for c in children:  # unreached nodes, data objects, loose annotations, ...
            visit(c, outgoing, attached)

    for el in sorted(
        by_owner, key=lambda el: doc_order[el]
    ):  # message flows and the rest
        emit(el)
    assert len(ordered) == len(items)
    return ordered


def _story_frames(root: ET.Element, items: list) -> list:
    """Frame each text element (in flow order) as a Dutch sentence: (before, item, after)."""
    by_id = {el.get("id"): el for el in root.iter() if el.get("id")}
    step: dict = {}  # task id -> step number, in story order
    for el, element_id, location, _ in items:
        if location == "name" and _local(el.tag) in TASKS and element_id not in step:
            step[element_id] = len(step) + 1

    def where_to(flow_id):
        # an element without children is falsy, so test for None explicitly
        flow = by_id.get(flow_id)
        target = by_id.get(flow.get("targetRef")) if flow is not None else None
        kind = _local(target.tag) if target is not None else ""
        if kind in TASKS and target is not None and target.get("id") in step:
            return f" gaat het verder met stap {step[target.get('id')]}."
        if kind == "endEvent":
            return " gaat het verder naar het einde."
        if kind in GATEWAYS:
            return " volgt een nieuwe beslissing."
        return " gaat het proces verder."

    pieces = []
    for item in items:
        el, element_id, location, _ = item
        kind = _kind(item)
        after = ""
        if kind == "documentation":
            before = "Toelichting: "
        elif kind == "text":
            before = "Opmerking: "
        elif kind == "participant":
            before = "Dit proces heet: " if el.get("processRef") else "Externe partij: "
        elif kind == "lane":
            before = "Betrokken in dit proces: "
        elif kind == "startEvent":
            before = "Het proces begint met: "
        elif kind in TASKS:
            before = f"Stap {step.get(element_id, '')}: "
        elif kind in GATEWAYS:
            before = "Daarna volgt de beslissing: "
        elif kind == "sequenceFlow":
            before, after = "Bij antwoord ", where_to(element_id)
        elif kind in EVENTS:
            before = "Daarna gebeurt: "
        elif kind == "endEvent":
            before = "Het proces eindigt met: "
        elif kind in ("dataObjectReference", "dataStoreReference"):
            before = "Gebruikt document: "
        elif kind == "messageFlow":
            before = "Bericht van de externe partij: "
        else:
            before = f"{kind}: "
        pieces.append((before, item, after))
    return pieces


def detect_bpmn(xml: str, cfg: PipelineConfig) -> list:
    if cfg.whole_document:
        return _detect_document(xml, cfg)
    root = ET.fromstring(xml)
    detections = []
    for _, element_id, location, text in text_elements(root, cfg):
        for d in detect_text(text, cfg):
            detections.append({"element_id": element_id, "location": location, **d})
    return detections


def _detect_document(xml: str, cfg: PipelineConfig) -> list:
    """One analyze call for the whole diagram; detections mapped back to the elements."""
    text, segments = bpmn_document(xml, cfg)
    detections = []
    for d in detect_text(text, cfg):
        hits = [g for g in segments if d["start"] < g["end"] and g["start"] < d["end"]]
        if len(hits) > 1:
            STATS["crossing_boundary"] += 1
        if not hits:
            STATS["outside_elements"] += 1  # e.g. only on a line prefix
        for g in hits:
            start, end = max(d["start"], g["start"]), min(d["end"], g["end"])
            detections.append({
                "element_id": g["element_id"],
                "location": g["location"],
                "start": start - g["start"],
                "end": end - g["start"],
                "entity": d["entity"],
                "score": d["score"],
                "match": text[start:end],
            })  # fmt: skip
    return detections


def review_list(detections: list, cfg: PipelineConfig) -> list:
    """What a reviewer gets to see: every detection, or each (entity, value) once with dedup."""
    if not cfg.dedup:
        return detections
    seen = {}
    for d in detections:
        seen.setdefault((d["entity"], d["match"].strip().lower()), d)
    return list(seen.values())


def _register_namespaces(xml: str):
    for _, (prefix, uri) in ET.iterparse(StringIO(xml), events=["start-ns"]):
        ET.register_namespace(prefix, uri)


def anonymize_bpmn(xml: str, approved: list, cfg: PipelineConfig) -> str:
    """
    Mask approved detections with *****, keeping the namespace prefixes.

    Without dedup only the approved spans are masked; with dedup every
    occurrence of an approved value is masked in all scanned text.
    """
    _register_namespaces(xml)
    root = ET.fromstring(xml)
    by_key = {}
    for d in approved:
        by_key.setdefault((d["element_id"], d["location"]), []).append(d)
    values = (
        {d["match"] for d in approved if d["match"].strip()} if cfg.dedup else set()
    )
    # Parts of approved names, masked as whole words ("Lander" of "Lander Lambrecht")
    allowed = {t.lower() for t in cfg.allow_list or ()}
    name_parts = {
        part
        for d in approved
        if d["entity"] == "PERSON"
        for part in re.findall(r"[\w'’-]+", d["match"])
        if len(part) >= 3 and not _is_particle(part) and part.lower() not in allowed
    } if cfg.dedup and cfg.mask_name_parts else set()  # fmt: skip

    for el, element_id, location, text in text_elements(root, cfg):
        spans = list(by_key.get((element_id, location), []))
        for value in values:
            spans += [
                {"start": m.start(), "end": m.end()}
                for m in re.finditer(re.escape(value), text)
            ]
        for part in name_parts:
            spans += [
                {"start": m.start(), "end": m.end()}
                for m in re.finditer(rf"(?<!\w){re.escape(part)}(?!\w)", text)
            ]
        if not spans:
            continue
        masked = mask_spans(text, spans)
        if location == "name":
            el.set("name", masked)
        else:
            el.text = masked
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


########################################################################
# The cumulative improvement steps (notebook 01) and input formats (notebook 02)
########################################################################

# Step 2: NER results always score 0.85, so only the pattern-based bars really change
THRESHOLDS = {
    "PERSON": 0.85,
    "LOCATION": 0.85,
    "EMAIL_ADDRESS": 0.5,
    "IBAN_CODE": 0.5,
    "CREDIT_CARD": 0.5,
    "BELGIAN_NATIONAL_REGISTRY": 0.5,
    "PHONE_NUMBER": 0.4,
}


def cumulative_steps(allow_list_path="allow_list.txt") -> dict[str, PipelineConfig]:
    """Steps 0-11: the baseline, then one improvement at a time on top of the previous step."""
    steps = {}
    cfg = PipelineConfig(name="0 baseline")
    steps[cfg.name] = cfg

    def add(name: str, **changes):
        nonlocal cfg
        cfg = replace(cfg, name=name, **changes)
        steps[name] = cfg

    all_entities = RELEVANT_ENTITIES + BELGIAN_ENTITIES
    add("1 entity filter", entities=tuple(RELEVANT_ENTITIES))
    add("2 thresholds", thresholds=THRESHOLDS)
    add("3 allow-list", allow_list=load_allow_list(allow_list_path))
    add("4 RRN checksum", rrn_checksum=True)
    add("5 acronym gate", acronym_gate=True)
    add("6 dedup", dedup=True)
    add("7 documentation + annotations", scan_text_elements=True)
    add("8 Belgian recognizers", belgian_recognizers=True, entities=tuple(all_entities))
    add("9 no LOCATION", entities=tuple(e for e in all_entities if e != "LOCATION"))
    add("10 name particles", extend_names=True)
    add("11 name parts", mask_name_parts=True)
    return steps


def changed_settings(prev: PipelineConfig, cfg: PipelineConfig) -> dict:
    """{setting: (old, new)} for every setting that differs, apart from the name."""
    return {
        f.name: (getattr(prev, f.name), getattr(cfg, f.name))
        for f in fields(cfg)
        if f.name != "name" and getattr(prev, f.name) != getattr(cfg, f.name)
    }


# How the text of a diagram is given to the detector (notebook 02): name -> settings
INPUT_FORMATS = {
    "per element": {},
    "one text": {"whole_document": True, "document_layout": "lines"},
    "one text + type": {"whole_document": True, "document_layout": "typed"},
    "flow order": {"whole_document": True, "document_layout": "flow"},
    "story": {"whole_document": True, "document_layout": "story"},
}

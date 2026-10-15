from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider

# Engine
nlp_configuration = {
    "nlp_engine_name": "spacy",
    "models": [
        {"lang_code": "nl", "model_name": "nl_core_news_md"},
        {"lang_code": "en", "model_name": "en_core_web_md"},
    ],
}
provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
nlp_engine = provider.create_engine()

# Recognizer (Belgian national registration number)
rrn_pattern = Pattern(
    name="BELGIAN_RRN_PATTERN",
    regex=r"\b\d{2}[.\-]?\d{2}[.\-]?\d{2}[.\-]?\d{3}[.\-]?\d{2}\b",
    score=0.85,
)
rrn_recognizer = PatternRecognizer(
    supported_entity="BELGIAN_NATIONAL_REGISTRY",
    supported_language="nl",
    patterns=[rrn_pattern],
    context=["rijksregisternummer", "INSZ", "NISS"],
)

# Analyzer
analyzer = AnalyzerEngine(
    nlp_engine=nlp_engine,
    supported_languages=["nl", "en"],
)
analyzer.registry.add_recognizer(rrn_recognizer)


def filter_overlaps(spans: list) -> list:
    sorted_spans = sorted(spans, key=lambda r: r["score"], reverse=True)
    kept = []
    for span in sorted_spans:
        if not any(
            span["start"] < kept_span["end"] and kept_span["start"] < span["end"]
            for kept_span in kept
        ):
            kept.append(span)

    return sorted(kept, key=lambda r: r["start"])


def detect_pii(text: str, min_score: float = 0.6) -> list:
    try:
        raw_results = analyzer.analyze(text=text, language="nl")
    except ValueError:
        raw_results = analyzer.analyze(text=text, language="en")

    results = [
        {
            "start": r.start,
            "end": r.end,
            "entity": r.entity_type,
            "score": round(r.score, 3),
            "match": text[r.start : r.end],
        }
        for r in raw_results
        if r.score >= min_score
    ]

    return filter_overlaps(results)

"""The BPMN endpoints of the service's web.py, without Flask. Logic unchanged."""

import io

from .anonymization import mask_spans
from .bpmn import deserialize_bpmn, extract_elem_from_bpmn, get_element_name, serialize_bpmn, set_element_name
from .identification import detect_pii


class _Upload(io.BytesIO):
    """Stand-in for a Flask FileStorage."""

    filename = "upload.bpmn"


def identify_bpmn(xml: str) -> dict:
    """web.process_bpmn_file (POST /bpmn/identify)."""
    extracted_elements = extract_elem_from_bpmn(xml)
    pii_results = []
    for elem in extracted_elements:
        pii_result = detect_pii(elem["name"])
        for key in pii_result:
            key["id"] = elem["id"]
            pii_results.append(key)

    return {
        "extracted_elements": extracted_elements,
        "pii_results": pii_results,
        "total_pii_found": len(pii_results),
    }


def anonymize_bpmn(xml: str, pointers: list) -> str:
    """web.anonymize_bpmn (POST /bpmn/anonymize), pointers as a parsed list."""
    bpmn = deserialize_bpmn(_Upload(xml.encode("utf-8")))

    groups = {}
    for p in pointers:
        groups.setdefault(p["id"], []).append(p)

    for element_id, spans in groups.items():
        original = get_element_name(bpmn, element_id)
        masked = mask_spans(original, spans)
        set_element_name(bpmn, element_id, masked)

    return serialize_bpmn(bpmn)

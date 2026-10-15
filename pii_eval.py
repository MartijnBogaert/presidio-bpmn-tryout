"""
Load the synthetic BPMN corpus and score PII detections against its ground truth.

A detection is a dict with at least: file, element_id, location
("name" | "documentation" | "text"), start, end, entity. Offsets are on the
stripped element text, as in ground_truth.json.
"""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

BPMN_NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}

# Presidio entity type -> ground-truth label
ENTITY_MAP = {
    "PERSON": "PERSON",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "BELGIAN_NATIONAL_REGISTRY": "RRN",
    "IBAN_CODE": "IBAN",
    "LOCATION": "ADDRESS",
    "DATE_TIME": "DATE_OF_BIRTH",
    "DATE_OF_BIRTH": "DATE_OF_BIRTH",
    "BE_ADDRESS": "ADDRESS",
    "BE_ENTERPRISE_NUMBER": "KBO",
    "BE_LICENSE_PLATE": "LICENSE_PLATE",
}

KEY = ["file", "element_id", "location"]


def load_corpus(corpus_dir="data/synthetic"):
    """Return (files, elements, spans): {filename: xml}, one row per text element, one row per PII span."""
    corpus_dir = Path(corpus_dir)
    files = {
        p.name: p.read_text(encoding="utf-8") for p in sorted(corpus_dir.glob("*.bpmn"))
    }
    records = json.loads((corpus_dir / "ground_truth.json").read_text(encoding="utf-8"))
    elements = pd.DataFrame(
        [
            {k: v for k, v in r.items() if k != "spans"} | {"n_pii": len(r["spans"])}
            for r in records
        ]
    )
    spans = pd.DataFrame(
        [
            {**{k: r[k] for k in KEY + ["element_type", "text"]}, **s}
            for r in records
            for s in r["spans"]
        ]
    )
    return files, elements, spans


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _covered(start, end, intervals):
    """True if [start, end) is fully covered by the union of intervals."""
    pos = start
    for s, e in sorted(intervals):
        if s > pos:
            break
        pos = max(pos, e)
        if pos >= end:
            return True
    return pos >= end


def match(spans: pd.DataFrame, detections: pd.DataFrame):
    """
    Return (spans, detections) annotated with match flags.

    spans gets:      hit (any overlapping detection), hit_typed (overlapping detection
                     of the right type), full (span chars fully covered by detections)
    detections gets: tp (overlaps a ground-truth span), tp_typed, gt_entity
    """
    det = detections.copy()
    if det.empty:
        det = pd.DataFrame(columns=KEY + ["start", "end", "entity"])
    det["mapped"] = det["entity"].map(lambda e: ENTITY_MAP.get(e, e))
    det_by_key = {k: g for k, g in det.groupby(KEY)}
    gt_by_key = {k: g for k, g in spans.groupby(KEY)}

    hit, hit_typed, full = [], [], []
    for row in spans.itertuples():
        d = det_by_key.get((row.file, row.element_id, row.location))
        if d is None:
            hit.append(False), hit_typed.append(False), full.append(False)
            continue
        over = d[[_overlaps(row.start, row.end, s, e) for s, e in zip(d.start, d.end)]]
        hit.append(len(over) > 0)
        hit_typed.append(bool((over.mapped == row.entity).any()))
        full.append(_covered(row.start, row.end, list(zip(over.start, over.end))))
    spans = spans.assign(hit=hit, hit_typed=hit_typed, full=full)

    tp, tp_typed, gt_entity = [], [], []
    for row in det.itertuples():
        g = gt_by_key.get((row.file, row.element_id, row.location))
        over = (
            g[[_overlaps(row.start, row.end, s, e) for s, e in zip(g.start, g.end)]]
            if g is not None
            else []
        )
        tp.append(len(over) > 0)
        tp_typed.append(bool(len(over) and (over.entity == row.mapped).any()))
        gt_entity.append(", ".join(sorted(set(over.entity))) if len(over) else None)
    det = det.assign(tp=tp, tp_typed=tp_typed, gt_entity=gt_entity)
    return spans, det


def _prf(tp_det, n_det, hits, n_gt):
    p = tp_det / n_det if n_det else float("nan")
    r = hits / n_gt if n_gt else float("nan")
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def summarize(spans: pd.DataFrame, det: pd.DataFrame, by=None) -> pd.DataFrame:
    """
    Metrics table, overall (by=None) or grouped by a span column ("entity" / "location").

    recall        = share of PII spans touched by a detection
    recall_full   = share of PII spans completely covered (what masking needs)
    recall_typed  = share touched by a detection of the right type
    precision     = share of detections that touch real PII (only overall / per location,
                    false positives have no ground-truth entity)
    """
    groups = (
        [("all", spans, det)]
        if by is None
        else [
            (k, g, det[det[by] == k] if by in det.columns else det.iloc[0:0])
            for k, g in spans.groupby(by)
        ]
    )
    rows = []
    for name, s, d in groups:
        p, r, f = _prf(d.tp.sum(), len(d), s.hit.sum(), len(s))
        rows.append(
            {
                (by or "scope"): name,
                "n_pii": len(s),
                "n_detections": len(d),
                "false_positives": int((~d.tp).sum()),
                "precision": p,
                "recall": r,
                "recall_full": s.full.mean(),
                "recall_typed": s.hit_typed.mean(),
                "f1": f,
            }
        )
    out = pd.DataFrame(rows).set_index(by or "scope")
    if by == "entity":  # precision per entity is not well-defined without typed FPs
        out = out.drop(columns=["n_detections", "false_positives", "precision", "f1"])
    return out.round(3)


def element_text(root: ET.Element, element_id: str, location: str):
    el = root.find(f".//*[@id='{element_id}']")
    if el is None:
        return None
    if location == "name":
        return (el.get("name") or "").strip()
    child = el.find(f"bpmn:{location}", BPMN_NS)
    return (child.text or "").strip() if child is not None else None


def residual_pii(spans: pd.DataFrame, anonymized: dict) -> pd.DataFrame:
    """
    For each PII span, look at the anonymized element text:
    leaked_intact  - the full value is still present
    leaked         - at least one word/number of the value is still present
                     (e.g. "Lander *****" or "050407 ***** 39")
    """
    roots = {f: ET.fromstring(xml) for f, xml in anonymized.items()}
    intact, partial = [], []
    for row in spans.itertuples():
        text = element_text(roots[row.file], row.element_id, row.location) or ""
        intact.append(row.value in text)
        tokens = [t for t in re.findall(r"\w+", row.value) if len(t) >= 2]
        partial.append(
            any(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text) for t in tokens)
        )
    return spans.assign(leaked_intact=intact, leaked=partial)


def evaluate(
    step: str,
    spans: pd.DataFrame,
    detections: pd.DataFrame,
    n_review_items: int,
    anonymized: dict,
):
    """
    One metrics row for a pipeline step, plus the scored spans/detections for drilling down.

    n_review_items is the length of the list a reviewer has to go through (all files together).
    """
    scored_spans, scored_det = match(spans, detections)
    residual = residual_pii(spans, anonymized)
    overall = summarize(scored_spans, scored_det).iloc[0]
    row = {
        "step": step,
        **overall.to_dict(),
        "review_items": n_review_items,
        "residual_pii": round(residual.leaked.mean(), 3),
    }
    return row, scored_spans.assign(leaked=residual.leaked), scored_det


DET_KEY = KEY + ["start", "end", "entity"]


def diff_steps(prev: tuple, cur: tuple) -> dict:
    """
    What changed between two steps, given (scored_spans, scored_det) of each.

    Returns DataFrames: pii_gained / pii_lost (spans newly touched / no longer touched),
    fp_removed / fp_added (false-positive detections that disappeared / appeared).
    """
    (prev_spans, prev_det), (cur_spans, cur_det) = prev, cur
    cols = ["file", "location", "entity", "value", "text"]
    fp_prev, fp_cur = prev_det[~prev_det.tp], cur_det[~cur_det.tp]
    merged = fp_prev.merge(fp_cur[DET_KEY], on=DET_KEY, how="outer", indicator=True)
    added = fp_cur.merge(fp_prev[DET_KEY], on=DET_KEY, how="left", indicator=True)
    return {
        "pii_gained": cur_spans[~prev_spans.hit & cur_spans.hit][cols],
        "pii_lost": cur_spans[prev_spans.hit & ~cur_spans.hit][cols],
        "fp_removed": merged[merged._merge == "left_only"][
            ["location", "entity", "match"]
        ],
        "fp_added": added[added._merge == "left_only"][["location", "entity", "match"]],
    }

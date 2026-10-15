"""
Run one pipeline configuration on the corpus and score it.

Shared by 01_improvements.ipynb and 02_input_formats.ipynb, so both
notebooks measure their steps in exactly the same way.
"""

import time
from dataclasses import dataclass

import pandas as pd

import improved
import pii_eval
from improved import PipelineConfig

# Columns of the long-format results CSVs
SUMMARY_COLUMNS = [
    "approach",
    "scope",
    "n_pii",
    "n_detections",
    "false_positives",
    "precision",
    "recall",
    "recall_full",
    "recall_typed",
    "f1",
    "group",
    "residual_pii",
]


@dataclass
class StepResult:
    row: dict  # overall metrics, see pii_eval.evaluate, plus cost counters
    spans: pd.DataFrame  # ground-truth spans with hit/full/leaked flags
    detections: pd.DataFrame  # detections with tp flags
    summary: pd.DataFrame  # long format: overall, per location, per entity


def run_step(cfg: PipelineConfig, files: dict, spans: pd.DataFrame) -> StepResult:
    """
    Detect, build the review list, anonymize (approving everything on the list) and score.

    Besides the quality metrics, the row holds the cost of detection: the number of
    analyzer calls and the detection time for all files (models already loaded).
    """
    improved.build_analyzer(cfg)  # build (and cache) the analyzer outside the timing
    improved.STATS.clear()
    t0 = time.perf_counter()
    found = {f: improved.detect_bpmn(xml, cfg) for f, xml in files.items()}
    detect_seconds = time.perf_counter() - t0
    stats = dict(improved.STATS)

    det_rows, review_rows, anonymized = [], [], {}
    for f, xml in files.items():
        review = improved.review_list(found[f], cfg)
        anonymized[f] = improved.anonymize_bpmn(xml, review, cfg)
        det_rows += [{"file": f, **d} for d in found[f]]
        review_rows += [{"file": f, **d} for d in review]
    detections = pd.DataFrame(det_rows)
    row, s, d = pii_eval.evaluate(
        cfg.name, spans, detections, len(review_rows), anonymized
    )

    # how many items on the review list are not PII
    review_tp = (
        pd.DataFrame(review_rows)[pii_eval.DET_KEY]
        .merge(d[[*pii_eval.DET_KEY, "tp"]], on=pii_eval.DET_KEY)
        .tp
    )
    row["review_false_positives"] = int((~review_tp).sum())
    row["analyze_calls"] = stats.get("analyze_calls", 0)
    row["crossing_boundary"] = stats.get("crossing_boundary", 0)
    row["detect_seconds"] = round(detect_seconds, 2)

    tables = []
    for by in [None, "location", "entity"]:
        t = pii_eval.summarize(s, d, by=by).rename_axis("scope").reset_index()
        leaked = (
            {"all": s.leaked.mean()}
            if by is None
            else s.groupby(by).leaked.mean().to_dict()
        )
        t["residual_pii"] = pd.Series(
            [leaked[k] for k in t["scope"]], index=t.index
        ).round(3)
        tables.append(t.assign(approach=cfg.name, group=by or "overall"))
    summary = pd.concat(tables).loc[:, SUMMARY_COLUMNS]
    return StepResult(row, s, d, summary)

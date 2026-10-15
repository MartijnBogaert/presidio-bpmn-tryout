# presidio-bpmn-tryout

Experiments to improve PII detection in BPMN files with Presidio, starting from the code of
[lblod/pii-identification-anonymization-service](https://github.com/lblod/pii-identification-anonymization-service).

## Setup

```bash
bash setup.sh                         # .venv + dependencies + spaCy models + Jupyter kernel
.venv/bin/python generate_bpmn.py     # (re)generate data/synthetic, deterministic
```

Open a notebook and select the kernel *Python (presidio-bpmn-tryout)*, or run it headless:

```bash
.venv/bin/jupyter nbconvert --to notebook --execute --inplace 01_baseline.ipynb
.venv/bin/jupyter nbconvert --to notebook --execute --inplace 02_improvements.ipynb
```

## Contents

| Path | |
|---|---|
| `baseline_service/` | Copy of the service's detection, anonymization and BPMN code (commit `d01e7ee`, MIT), plus `endpoints.py` with the `/bpmn/identify` and `/bpmn/anonymize` logic from `web.py` |
| `generate_bpmn.py` | Generates synthetic Dutch BPMN files with fictitious PII, OPH jargon, and a `ground_truth.json` |
| `pii_eval.py` | Loads the corpus and scores detections (precision, recall, residual PII after anonymization, step diffs) |
| `improved.py` | Configurable pipeline: every improvement is a switch on `PipelineConfig` (all off = baseline) |
| `allow_list.txt` | Domain terms that are never PII (used from step 3) |
| `01_baseline.ipynb` | Baseline: the unchanged service code on the synthetic corpus |
| `02_improvements.ipynb` | The improvements switched on one by one, with a comparison and leave-one-out analysis |
| `results/` | Metrics per notebook, for comparison |

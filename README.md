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
```

## Contents

| Path | |
|---|---|
| `baseline_service/` | Copy of the service's detection, anonymization and BPMN code (commit `d01e7ee`, MIT), plus `endpoints.py` with the `/bpmn/identify` and `/bpmn/anonymize` logic from `web.py` |
| `generate_bpmn.py` | Generates synthetic Dutch BPMN files with fictitious PII and a `ground_truth.json` |
| `pii_eval.py` | Loads the corpus and scores detections (precision, recall, residual PII after anonymization) |
| `01_baseline.ipynb` | Baseline: the unchanged service code on the synthetic corpus |
| `results/` | Metrics per notebook, for comparison |

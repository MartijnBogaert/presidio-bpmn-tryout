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
.venv/bin/jupyter nbconvert --to notebook --execute --inplace 03_one_text_per_diagram.ipynb  # after 02
.venv/bin/jupyter nbconvert --to notebook --execute --inplace 04_story.ipynb  # after 02 and 03
```

## Contents

| Path | |
|---|---|
| `baseline_service/` | Copy of the service's detection, anonymization and BPMN code (commit `d01e7ee`, MIT), plus `endpoints.py` with the `/bpmn/identify` and `/bpmn/anonymize` logic from `web.py` |
| `generate_bpmn.py` | Generates synthetic Dutch BPMN files with fictitious PII, OPH jargon, and a `ground_truth.json` |
| `pii_eval.py` | Loads the corpus and scores detections (precision, recall, residual PII after anonymization, step diffs) |
| `improved.py` | Configurable pipeline: every improvement is a switch on `PipelineConfig` (all off = baseline); `cumulative_steps()` defines steps 0–11 |
| `experiment.py` | Runs and scores one configuration on the corpus (shared by notebooks 02 and 03) |
| `allow_list.txt` | Domain terms that are never PII (used from step 3) |
| `01_baseline.ipynb` | Baseline: the unchanged service code on the synthetic corpus |
| `02_improvements.ipynb` | The improvements switched on one by one (per element), with a comparison and leave-one-out analysis |
| `03_one_text_per_diagram.ipynb` | The same steps on one text per diagram instead of per element, compared with notebook 02 |
| `04_story.ipynb` | One text per diagram in process-flow order and as a framed "story", compared with notebooks 02 and 03 |
| `results/` | Metrics per notebook, for comparison |

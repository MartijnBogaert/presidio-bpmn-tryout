# presidio-bpmn-tryout

Experiments to improve PII detection in BPMN files with Presidio, starting from the code of
[lblod/pii-identification-anonymization-service](https://github.com/lblod/pii-identification-anonymization-service).

## Notebooks

Start with `04_overview.ipynb` for the results; the other notebooks hold the details.

| Notebook | Question | Writes |
|---|---|---|
| `00_baseline.ipynb` | How good is the current service? | `results/baseline.csv` |
| `01_improvements.ipynb` | **What** to detect and filter: improvement steps 0–11, each element analyzed on its own | `results/steps.csv` |
| `02_input_formats.ipynb` | **How** to give the text to the detector: per element, one text per diagram, flow order, story (same steps 0–11) | `results/input_formats.csv` |
| `03_models.ipynb` | **Which** NER model: spaCy md (current) vs. spaCy lg vs. a Dutch transformer (BERTje), on the same steps and input formats | `results/models.csv` |
| `04_overview.ipynb` | What came out? Summary of the results files | – |

## Setup

```bash
bash setup.sh                         # .venv + dependencies + spaCy models + Jupyter kernel (~2 GB, incl. CPU torch)
.venv/bin/python generate_bpmn.py     # (re)generate data/synthetic, deterministic
```

Open a notebook and select the kernel *Python (presidio-bpmn-tryout)*, or run them headless, in this order:

```bash
for nb in 00_baseline 01_improvements 02_input_formats 03_models 04_overview; do
  .venv/bin/jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 $nb.ipynb
done
```

Notebook 03 needs the extra models from `setup.sh` (`nl_core_news_lg`, torch, transformers); the BERTje NER model
(~0.4 GB) downloads from Hugging Face on first use. On CPU it takes several minutes.

## Code

| Path | |
|---|---|
| `baseline_service/` | Copy of the service's detection, anonymization and BPMN code (commit `d01e7ee`, MIT), plus `endpoints.py` with the `/bpmn/identify` and `/bpmn/anonymize` logic from `web.py` |
| `generate_bpmn.py` | Generates synthetic Dutch BPMN files with fictitious PII, OPH jargon, and a `ground_truth.json` |
| `improved.py` | Configurable pipeline: every improvement is a switch on `PipelineConfig` (all off = baseline); `cumulative_steps()` defines steps 0–11, `INPUT_FORMATS` the input formats, `NER_MODELS` the NER models |
| `experiment.py` | Runs and scores one configuration on the corpus (used by notebooks 01–03) |
| `pii_eval.py` | Loads the corpus and scores detections (precision, recall, residual PII after anonymization, step diffs) |
| `allow_list.txt` | Domain terms that are never PII (used from step 3) |
| `results/` | Metrics written by notebooks 00–03 |

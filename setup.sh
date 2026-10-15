#!/usr/bin/env bash
# Create the local virtualenv, install dependencies and spaCy models,
# and register a Jupyter kernel for the notebooks.
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Same models as the service's Dockerfile
.venv/bin/python -m spacy download nl_core_news_md
.venv/bin/python -m spacy download en_core_web_md

.venv/bin/python -m ipykernel install --user --name presidio-bpmn-tryout \
  --display-name "Python (presidio-bpmn-tryout)"

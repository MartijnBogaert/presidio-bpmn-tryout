"""
Verbatim copy of the detection/anonymization code of
https://github.com/lblod/pii-identification-anonymization-service (MIT, see LICENSE)
at commit d01e7ee (2025-07-30), used as the baseline for the experiments.

identification.py, anonymization.py and bpmn.py are unchanged. web.py is not
copied (it needs the Flask app injected by mu-python-template); its BPMN
endpoint logic lives in endpoints.py.
"""

SOURCE_REPO = "https://github.com/lblod/pii-identification-anonymization-service"
SOURCE_COMMIT = "d01e7ee"

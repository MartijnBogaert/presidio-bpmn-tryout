"""
Small client for the DAPAS API (Data Beschermings API), used as an external PII detector.

Configuration and secrets come from `.env` (git-ignored) at runtime:
DAPAS_API_BASE_URL, ACM_IDM_IDP_BASE_URL, DAPAS_API_CLIENT_CLIENT_ID,
DAPAS_API_CLIENT_CLIENT_SECRET, DAPAS_API_SERVICE_CLIENT_ID.
Secrets and tokens are never printed, logged or written to disk; errors only
report the HTTP status and the API's `detail` field.

Only detection is used: `analyze()` calls POST /v1/text/mask with
include_analysis=true and returns the detections (type, start, end, score).
Masking itself is done by improved.anonymize_bpmn, like for every other detector.
"""

import os
import time
import uuid
from functools import cache

import httpx
from dotenv import load_dotenv

ENV_VARS = (
    "DAPAS_API_BASE_URL",
    "ACM_IDM_IDP_BASE_URL",
    "DAPAS_API_CLIENT_CLIENT_ID",
    "DAPAS_API_CLIENT_CLIENT_SECRET",
    "DAPAS_API_SERVICE_CLIENT_ID",
)
TIMEOUT = httpx.Timeout(
    300, connect=15
)  # the model behind the API may need a while to wake up
CORRELATION_ID = str(
    uuid.uuid4()
)  # groups all calls of one run in the API's audit trail


class DapasError(RuntimeError):
    pass


def _env() -> dict:
    load_dotenv(".env")
    missing = [k for k in ENV_VARS if not os.environ.get(k)]
    if missing:
        raise DapasError(f"missing settings in .env: {', '.join(missing)}")
    return {k: os.environ[k] for k in ENV_VARS}


_token: dict = {}


def _access_token(refresh: bool = False) -> str:
    """Client-credentials token, cached in memory until shortly before it expires."""
    if not refresh and _token and _token["expires"] > time.time() + 60:
        return _token["value"]
    env = _env()
    response = httpx.post(
        env["ACM_IDM_IDP_BASE_URL"].rstrip("/") + "/v1/token",
        data={
            "grant_type": "client_credentials",
            "client_id": env["DAPAS_API_CLIENT_CLIENT_ID"],
            "client_secret": env["DAPAS_API_CLIENT_CLIENT_SECRET"],
            "scope": "datins_consumer_access",
            "audience": env["DAPAS_API_SERVICE_CLIENT_ID"],
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise DapasError(f"token request failed: HTTP {response.status_code}")
    body = response.json()
    _token.update(
        value=body["access_token"], expires=time.time() + body.get("expires_in", 3600)
    )
    return _token["value"]


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", ""))[:300]
    except ValueError:
        return ""


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    """Authenticated call; fetches a new token once on 401."""
    url = _env()["DAPAS_API_BASE_URL"].rstrip("/") + path

    def send(refresh: bool) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {_access_token(refresh=refresh)}",
            "x-correlation-id": CORRELATION_ID,
        }
        return httpx.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)

    response = send(refresh=False)
    if response.status_code == 401:
        response = send(refresh=True)
    if response.status_code != 200:
        raise DapasError(
            f"{method} {path}: HTTP {response.status_code} {_detail(response)}"
        )
    return response


def available() -> tuple[bool, str]:
    """(True, "") if the API can be used, else (False, reason). Never raises."""
    try:
        _env()
        healthz = httpx.get(
            _env()["DAPAS_API_BASE_URL"].rstrip("/") + "/healthz", timeout=30
        )
        if healthz.status_code != 200:
            return False, f"/healthz: HTTP {healthz.status_code}"
        _access_token()
        return True, ""
    except (DapasError, httpx.HTTPError) as e:
        return False, f"{type(e).__name__}: {e}"


@cache
def entities() -> dict:
    """{"entities": [...all types], "default": [...default subset]} from the live API."""
    return _request("GET", "/v1/info/entities").json()


def analyze(text: str, options: dict) -> list[dict]:
    """Detections in `text` for the given DAPAS options (see the API's §3 options)."""
    body = {"texts": [text], **options, "include_analysis": True}
    row = _request("POST", "/v1/text/mask", json=body).json()[0]
    return [
        {
            "start": d["start"],
            "end": d["end"],
            "entity": d["entity_type"],
            "score": float(d.get("score") or 0),
        }
        for d in row.get("detections", [])
    ]

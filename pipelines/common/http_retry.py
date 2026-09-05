"""Synchronous retry policy for ATS adapters, ported from jseek's own
`src/shared/http_retry.py` (MIT) — real, hard-won retry semantics
(retryable statuses, backoff shape) reused rather than reinvented, per
research.md §9's "adapt jseek's code, don't reimplement from scratch"
decision. This is a synchronous (`requests`-based) adaptation of their
async httpx implementation — same policy, simpler runtime, since dlt
resources are plain sync generators.
"""

import random
import time

import requests

# 408 (timeout), 425 (too early), 429 (rate-limited), plus all 5xx —
# exactly jseek's own _RETRYABLE_STATUSES.
_EXTRA_RETRYABLE_STATUSES = frozenset({408, 425, 429})


class BoardGoneError(Exception):
    """The employer's board itself is gone (404) — a structural signal
    distinct from a transient failure (jseek's own BoardGoneError)."""


class PaginationFetchError(Exception):
    """Retries exhausted without a usable response."""


def _is_retryable_status(status: int) -> bool:
    return status in _EXTRA_RETRYABLE_STATUSES or 500 <= status < 600


def fetch_json_with_retry(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: object | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
    retries: int = 3,
    base_delay: float = 0.5,
    raise_on_404: bool = True,
) -> dict | list:
    """GET/POST with jseek's retry policy: retryable statuses get
    exponential backoff with jitter (base_delay * 2**attempt, +/- 50%
    jitter — matching their own "1-2s, 2-4s for 3 attempts" shape); a
    404 raises BoardGoneError immediately (never retried — the board is
    gone, not transiently failing); other non-2xx statuses fail fast.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.request(
                method, url, params=params, json=json_body, headers=headers, timeout=timeout
            )
        except requests.RequestException as exc:
            last_exc = exc
        else:
            if resp.status_code == 404 and raise_on_404:
                raise BoardGoneError(f"{url} returned 404")
            if resp.ok:
                return resp.json()
            if not _is_retryable_status(resp.status_code):
                resp.raise_for_status()
            last_exc = requests.HTTPError(f"{resp.status_code} for {url}")

        if attempt < retries - 1:
            delay = base_delay * (2**attempt) * random.uniform(0.75, 1.25)
            time.sleep(delay)

    raise PaginationFetchError(f"fetch failed for {url} after {retries} attempts: {last_exc}")

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


class AntiBotBlockedError(Exception):
    """A 403 from a public, unauthenticated ATS endpoint (confirmed
    live: lam-research's Eightfold-hosted career site returns a
    CloudFront/WAF-style block page under sustained request volume).
    Every endpoint this project talks to is a public careers page with
    no auth, so a 403 is itself a reliable anti-bot signal, not an
    ordinary permission error - raised with a clear, greppable message
    so `employers.last_error ILIKE '%anti-bot%'` is a standing query for
    which employers are hard to collect from, for case-by-case review
    (2026-09-06 decision: chase the ~95% that work cleanly, don't spend
    effort defeating anti-bot measures on the remainder)."""


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
    retryable_403: bool = False,
) -> dict | list:
    """GET/POST with jseek's retry policy: retryable statuses get
    exponential backoff with jitter (base_delay * 2**attempt, +/- 50%
    jitter — matching their own "1-2s, 2-4s for 3 attempts" shape); a
    404 raises BoardGoneError immediately (never retried — the board is
    gone, not transiently failing); other non-2xx statuses fail fast.

    A 403 raises AntiBotBlockedError immediately by default (confirmed
    live: lam-research/Eightfold). Oracle HCM is a documented exception
    — jseek's own postmortem (Albertsons #6394) confirms Oracle's shared
    multi-tenant infrastructure produces transient Akamai 403s that
    succeed on an identical retry, unlike a sustained WAF block. Pass
    `retryable_403=True` to retry a 403 like any other transient status
    instead of failing immediately, only raising AntiBotBlockedError
    once retries are exhausted.
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
            if resp.status_code == 403 and not retryable_403:
                raise AntiBotBlockedError(
                    f"anti-bot block (403) for {url} — every ATS endpoint "
                    "this project calls is public/unauthenticated, so a "
                    "403 here means bot-detection, not a real permission error"
                )
            if resp.ok:
                return resp.json()
            if resp.status_code != 403 and not _is_retryable_status(resp.status_code):
                resp.raise_for_status()
            last_exc = requests.HTTPError(f"{resp.status_code} for {url}")

        if attempt < retries - 1:
            delay = base_delay * (2**attempt) * random.uniform(0.75, 1.25)
            time.sleep(delay)

    if retryable_403 and last_exc is not None and "403" in str(last_exc):
        raise AntiBotBlockedError(
            f"anti-bot block (403, persisted after {retries} retries) for {url}"
        )
    raise PaginationFetchError(f"fetch failed for {url} after {retries} attempts: {last_exc}")

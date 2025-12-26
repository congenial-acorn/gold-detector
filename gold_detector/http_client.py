import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("gold.http")

# Seconds to wait between ANY two outbound HTTP calls (min spacing)
_RATE_LIMIT_SECONDS = float(os.getenv("GOLD_HTTP_COOLDOWN", "1.0"))

# Optional absolute timeout per request (seconds)
_HTTP_TIMEOUT = float(os.getenv("GOLD_HTTP_TIMEOUT", "15"))

# Max extra backoff after 429 (seconds)
_MAX_BACKOFF = float(os.getenv("GOLD_HTTP_MAX_BACKOFF", "60"))

# Shared session & throttle state
_SESSION = requests.Session()
_DEFAULT_HEADERS: Dict[str, str] = {"User-Agent": "Mozilla/5.0 (inaragold/1.0)"}
_last_http_call = 0.0
_rl_lock = threading.Lock()


def http_get(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
):
    """
    Throttled GET with global rate limiting and 429 backoff.
    Enforces at least _RATE_LIMIT_SECONDS spacing between ALL HTTP calls.
    """
    global _last_http_call

    # Enforce global cooldown between calls
    with _rl_lock:
        now = time.monotonic()
        wait = max(0.0, (_last_http_call + _RATE_LIMIT_SECONDS) - now)
    if wait > 0:
        logger.debug("Throttling HTTP request for %.2fs", wait)
        time.sleep(wait)

    merged_headers = dict(_DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    backoff = 2.0
    timeout = _HTTP_TIMEOUT if timeout is None else timeout

    while True:
        try:
            logger.debug("HTTP GET: %s", url)
            resp = _SESSION.get(url, headers=merged_headers, timeout=timeout)
            with _rl_lock:
                _last_http_call = time.monotonic()

            logger.debug("HTTP %s from %s", resp.status_code, url)

            if resp.status_code == 200 and "Access Temporarily Restricted" in resp.text:
                logger.error("IP BLOCKED by %s", url.split("/")[2])
                logger.error("Response preview: %s", resp.text[:500])
                raise requests.exceptions.HTTPError(
                    f"IP address blocked by {url.split('/')[2]}. "
                    "Check logs for contact information.",
                    response=resp,
                )

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after is not None else backoff
                except ValueError:
                    delay = backoff
                delay = min(delay, _MAX_BACKOFF)
                logger.warning(
                    "HTTP 429 (rate limited) from %s, retrying in %.1fs", url, delay
                )
                time.sleep(delay)
                backoff = min(backoff * 2.0, _MAX_BACKOFF)
                continue

            resp.raise_for_status()
            return resp

        except requests.exceptions.Timeout as exc:
            logger.error("HTTP timeout for %s: %s", url, exc)
            raise
        except requests.exceptions.ConnectionError as exc:
            logger.error("HTTP connection error for %s: %s", url, exc)
            raise
        except requests.exceptions.HTTPError as exc:
            logger.error("HTTP error for %s: %s", url, exc)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Unexpected error during HTTP GET %s: %s", url, exc, exc_info=True
            )
            raise

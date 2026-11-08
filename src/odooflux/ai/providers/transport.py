"""Stdlib transport and bounded retries (REQ-AI-005, FR-012, ADR-002).

Nothing here logs. Request bodies, headers (which carry credentials) and response bodies are never written to a
log, an exception message or a file by this module.
"""

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from odooflux.ai.providers.types import RETRYABLE_KINDS

MAX_RESPONSE_BYTES = 8_000_000
MAX_BACKOFF_S = 30.0


@dataclass(frozen=True)
class TransportResult:
    status: int  # HTTP status, or 0 when no HTTP response arrived
    body: bytes = b""
    error: str = ""  # "" | timeout | connection | invalid_url


def kind_for_status(status: int) -> str:
    """Map an HTTP status (0 = no response) to a contract ``error_kind``."""
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    if status in (0, 408, 409, 425) or status >= 500:
        return "transient"
    if 400 <= status < 500:
        return "invalid_request"
    return "unknown"


class UrllibTransport:
    """The default transport. Tests replace it with a recording or raising double."""

    def post(self, url: str, headers: dict, body: bytes, timeout: float) -> TransportResult:
        if urlparse(url).scheme not in ("http", "https"):
            return TransportResult(0, b"", "invalid_url")
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (scheme checked)
                return TransportResult(response.status, response.read(MAX_RESPONSE_BYTES))
        except urllib.error.HTTPError as exc:
            try:
                payload = exc.read(65536)
            except Exception:  # noqa: BLE001
                payload = b""
            return TransportResult(exc.code, payload)
        except TimeoutError:
            return TransportResult(0, b"", "timeout")
        except (urllib.error.URLError, OSError):
            return TransportResult(0, b"", "connection")


def call_with_retries(attempt, *, max_retries: int, sleep=time.sleep, on_attempt=None, before_retry=None,
                      base_delay: float = 1.0):
    """Call ``attempt()`` once, then retry only ``rate_limit``/``transient`` errors, at most ``max_retries`` times.

    ``on_attempt(response)`` sees every attempt (usage and budgets count each one); ``before_retry()`` returning
    False stops the loop (budget or kill switch). Backoff doubles from ``base_delay``, capped.
    """
    retries = 0
    while True:
        response = attempt()
        if on_attempt is not None:
            on_attempt(response)
        retryable = response.stop_reason == "error" and response.error_kind in RETRYABLE_KINDS
        if not retryable or retries >= max_retries:
            return response
        if before_retry is not None and not before_retry():
            return response
        sleep(min(base_delay * (2 ** retries), MAX_BACKOFF_S))
        retries += 1

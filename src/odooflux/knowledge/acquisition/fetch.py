"""Explicit network retrieval (REQ-KAP-001, REQ-KAP-009; source-adapter contract, rules 3 and 9 and Errors).

This is the only module of the knowledge pipeline that may use the network. Rules, all enforced here:
- refuses unless `allow_network=True` (the CLI maps `--allow-network` to it); the default is off;
- the URL must be a remote https URL under an allow-listed prefix (fail closed); redirects are re-checked;
- the body is capped at `MAX_BYTES`; the sha256 is verified against `expected_sha256` before anything is stored;
- the bytes go to the blob store only; nothing else is written and no credentials are sent.
Tests use an injected opener and never reach the network. Live retrieval is opt-in and lives outside default runs.
"""

import hashlib
import urllib.request
from datetime import datetime, timezone

from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.acquisition.sources import load_allow_list, require_allowed

__all__ = ["fetch", "AllowListRedirect", "FETCH_TIMEOUT", "MAX_BYTES"]

FETCH_TIMEOUT = 60  # seconds
MAX_BYTES = 512 * 1024 * 1024


class AllowListRedirect(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only when the target is still under the allow-list (fail closed)."""

    def __init__(self, allow_list, source_id):
        super().__init__()
        self._allow = list(allow_list)
        self._source_id = source_id

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_allowed(newurl, self._allow, self._source_id)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(spec: dict, store: BlobStore, *, allow_network: bool = False, expected_sha256=None, opener=None,
          allow_list=None) -> dict:
    """Retrieve the spec's remote URL and store the bytes. Returns `{url, sha256, size, retrieved_at}`.

    Raises SourceError: NETWORK_DISABLED without the flag, NOT_ALLOWLISTED for any URL off the list,
    IO_ERROR on transport failure or an oversize body, CHECKSUM_MISMATCH when `expected_sha256` differs
    (nothing is stored in that case).
    """
    source_id, url = spec["source_id"], spec["url"]
    if not allow_network:
        raise SourceError("NETWORK_DISABLED", source_id, "network access needs an explicit --allow-network")
    if url.startswith("local:"):
        raise SourceError("IO_ERROR", source_id, "fetch takes remote URLs only; local sources are read directly")
    allow = load_allow_list() if allow_list is None else list(allow_list)
    require_allowed(url, allow, source_id)
    if opener is None:
        opener = urllib.request.build_opener(AllowListRedirect(allow, source_id))
    try:
        with opener.open(url, timeout=FETCH_TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
    except SourceError:
        raise
    except OSError as exc:
        raise SourceError("IO_ERROR", source_id, f"retrieval failed: {exc}") from exc
    if len(body) > MAX_BYTES:
        raise SourceError("IO_ERROR", source_id, f"response exceeds {MAX_BYTES} bytes")
    digest = hashlib.sha256(body).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise SourceError("CHECKSUM_MISMATCH", source_id,
                          f"expected sha256 {expected_sha256}, retrieved bytes hash to {digest}")
    store.put(body)
    return {
        "url": url,
        "sha256": digest,
        "size": len(body),
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

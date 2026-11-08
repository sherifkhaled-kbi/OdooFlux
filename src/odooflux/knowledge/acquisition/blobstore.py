"""Content-addressed blob store with verify-on-read (REQ-KAP-010, source-adapter contract rule 6).

Layout: `<root>/objects/sha256/<aa>/<hex>`. A blob is written once (dedupe: an existing blob is never rewritten)
and every read recomputes its sha256. A mismatch raises `SourceError(SNAPSHOT_CORRUPT)`; the blob is reported,
never silently repaired.
"""

import hashlib
import re
from pathlib import Path

from odooflux.utils.atomic import atomic_write_bytes

_DIGEST = re.compile(r"^[0-9a-f]{64}$")

# Error codes from source-adapter.md. Defined here because T033 runs before T032 (sources.py); T032 imports it.
SOURCE_ERROR_CODES = (
    "OFFICIAL_IDENTITY_UNVERIFIED",
    "REVISION_UNAVAILABLE",
    "NOT_ALLOWLISTED",
    "AUTH_REQUIRED",
    "CHECKSUM_MISMATCH",
    "SNAPSHOT_CORRUPT",
    "IO_ERROR",
    "NETWORK_DISABLED",
)


class SourceError(Exception):
    """Acquisition failure with a closed code (`SOURCE_ERROR_CODES`)."""

    def __init__(self, code: str, source_id, message: str):
        if code not in SOURCE_ERROR_CODES:
            raise ValueError(f"unknown SourceError code {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.source_id = source_id
        self.message = message


class BlobStore:
    def __init__(self, root):
        self.root = Path(root)

    def _check(self, digest: str) -> None:
        if not isinstance(digest, str) or not _DIGEST.match(digest):
            raise ValueError(f"not a lowercase sha256 hex digest: {digest!r}")

    def path_for(self, digest: str) -> Path:
        self._check(digest)
        return self.root / "objects" / "sha256" / digest[:2] / digest[2:]

    def has(self, digest: str) -> bool:
        return self.path_for(digest).is_file()

    def put(self, data: bytes) -> str:
        """Store *data* and return its sha256 hex. An existing blob with the same digest is left untouched."""
        digest = hashlib.sha256(data).hexdigest()
        path = self.path_for(digest)
        if path.is_file():
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, data)
        return digest

    def get(self, digest: str) -> bytes:
        """Return the blob bytes after verifying their sha256. Raises `SourceError(SNAPSHOT_CORRUPT)` on
        a missing blob or a hash mismatch."""
        path = self.path_for(digest)
        if not path.is_file():
            raise SourceError("SNAPSHOT_CORRUPT", None, f"blob {digest} is missing from the store")
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise SourceError("SNAPSHOT_CORRUPT", None,
                              f"blob {digest} hashes to {actual}; the stored bytes were altered")
        return data

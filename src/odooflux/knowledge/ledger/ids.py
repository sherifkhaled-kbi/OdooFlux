"""Change ids (REQ-KAP-014; research R2).

`CH-` + the first 16 hex digits of sha256 over `"{from_digest}|{to_digest}|{domain}|{kind}|{subject_key}"`, where the
digests are the `snapshot_digest` values of the two snapshots. Stable across reruns; independent of order and time.
"""

import hashlib

__all__ = ["change_id", "CHANGE_ID_PATTERN"]

CHANGE_ID_PATTERN = r"^CH-[0-9a-f]{16}$"


def change_id(from_digest: str, to_digest: str, domain: str, kind: str, subject_key: str) -> str:
    raw = f"{from_digest}|{to_digest}|{domain}|{kind}|{subject_key}".encode("utf-8")
    return "CH-" + hashlib.sha256(raw).hexdigest()[:16]

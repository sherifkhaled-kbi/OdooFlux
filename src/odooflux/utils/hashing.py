"""SHA-256 helpers and stable finding identifiers (R-08)."""

import hashlib
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def digest_tree(root: Path) -> list:
    """Sorted (relative POSIX path, SHA-256) pairs for every regular file under *root*."""
    root = Path(root)
    return [(p.relative_to(root).as_posix(), sha256_file(p))
            for p in sorted(root.rglob("*")) if p.is_file()]


def finding_id(*parts) -> str:
    """Stable 16-hex identifier: SHA-256 over the joined parts (R-08)."""
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]

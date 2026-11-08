"""Order-independent content digest of a directory tree (REQ-TST-001)."""

import hashlib
from pathlib import Path


def tree_digest(path) -> list:
    """Sorted (relative POSIX path, SHA-256) pairs for every file under *path*."""
    root = Path(path)
    return [(p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(root.rglob("*")) if p.is_file()]


def digest_hex(path) -> str:
    """One SHA-256 over the whole tree listing (names and file digests)."""
    h = hashlib.sha256()
    for name, digest in tree_digest(path):
        h.update(f"{name}\0{digest}\n".encode("utf-8"))
    return h.hexdigest()

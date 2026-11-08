"""Verified-result cache (contracts/budget-and-cache.md, REQ-AI-007).

Entries hold only the replacement text, a digest, the prompt version and a timestamp: no credential, no request
header, no prompt. Every read checks the digest; a mismatch (tampering or corruption) deletes the entry.
"""

import datetime
import hashlib
import json
import shutil
from pathlib import Path


def cache_key(region_text, rule_id, provider, model, template_version, evidence_ids, target_step) -> str:
    region_sha = hashlib.sha256(region_text.encode("utf-8", errors="surrogateescape")).hexdigest()
    payload = json.dumps([region_sha, rule_id, provider, model, template_version, sorted(evidence_ids), target_step],
                         sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _digest(key: str, replacement: str) -> str:
    return hashlib.sha256((key + "\n" + replacement).encode("utf-8", errors="surrogateescape")).hexdigest()


class ResultCache:
    """``root`` is ``<state-dir>/ai-cache``: outside every scanned path (REQ-SEC-003)."""

    def __init__(self, root, *, enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled
        self.stats = {"hits": 0, "misses": 0, "tampered": 0, "revalidation_failed": 0, "writes": 0}

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str):
        """The cached replacement, or None (miss, disabled, unreadable or tampered; the entry is deleted)."""
        if not self.enabled:
            return None
        path = self._path(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            replacement = data["replacement"]
            ok = isinstance(replacement, str) and data.get("validation_digest") == _digest(key, replacement)
        except FileNotFoundError:
            self.stats["misses"] += 1
            return None
        except (OSError, ValueError, KeyError, TypeError):
            ok = False
        if not ok:
            self.stats["tampered"] += 1
            self.delete(key)
            return None
        self.stats["hits"] += 1
        return replacement

    def put(self, key: str, replacement: str, prompt_version: str) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"replacement": replacement, "validation_digest": _digest(key, replacement),
                 "prompt_version": prompt_version,
                 "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        self.stats["writes"] += 1

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except OSError:
            pass

    def revalidation_failed(self, key: str) -> None:
        self.stats["revalidation_failed"] += 1
        self.delete(key)

    def clear(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

"""Manual rule verbs (contract manual-rule-cli, feature 011, REQ-KAP-019, REQ-KAP-021).

Each mutating verb runs inside `_transact`: the change is written, the whole working tree is validated (schema,
checks, authoring A-codes), and every file touched is restored if a NEW error appears. Errors that already existed
before the verb do not block it. FIX_ENABLED is never set by any verb here; promotion is `promote` (T025).
Rules created by a verb have their creator fixed in the history sidecar; every later verb appends to it.
"""

import hashlib
import json
import getpass
import os
from datetime import datetime, timezone
from pathlib import Path

from odooflux.knowledge.authoring import history as h
from odooflux.knowledge.authoring.rule_store import RuleStoreError, update_rule_file
from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import load_knowledge
from odooflux.knowledge.release.canonical import digest_obj
from odooflux.utils.atomic import atomic_write_bytes

ORIGIN_MANUAL = "MANUAL"
ORIGIN_GENERATED = "GENERATED"
CREATABLE_ORIGINS = (ORIGIN_MANUAL, ORIGIN_GENERATED)
CREATE_MATURITIES = ("DRAFT", "DETECT_ONLY")
EDIT_MATURITIES = ("DRAFT", "DETECT_ONLY")
PROTECTED_FIELDS = ("id", "origin", "rev", "step")
TEST_KINDS = ("positive", "negative", "idempotence")
DEFAULT_MATURITY = "DETECT_ONLY"


class OpsError(ValueError):
    """The verb was refused or failed validation; nothing was written."""


class _Txn:
    """Remembers the prior bytes of every file and the directories created, so a failed verb can be undone."""

    def __init__(self):
        self._files = {}
        self._dirs = []

    def save(self, path) -> None:
        path = Path(path)
        if path not in self._files:
            self._files[path] = path.read_bytes() if path.is_file() else None

    def mkdir(self, path) -> None:
        path = Path(path)
        missing = []
        while not path.exists():
            missing.append(path)
            path = path.parent
        for directory in reversed(missing):
            directory.mkdir()
            self._dirs.append(directory)

    def rollback(self) -> None:
        for path, data in reversed(list(self._files.items())):
            if data is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, data)
        for directory in reversed(self._dirs):
            try:
                directory.rmdir()
            except OSError:
                pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_author(author=None) -> str:
    """`--author`, else `$GIT_AUTHOR_NAME`, else the OS login name, else 'unknown'. Reads only the environment: no
    subprocess, no network. The value is recorded history metadata, not an authenticated identity (FE-1)."""
    if author:
        return author
    name = os.environ.get("GIT_AUTHOR_NAME", "").strip()
    if not name:
        try:
            name = getpass.getuser()
        except Exception:  # no login name available (no controlling user)
            name = ""
    return name or "unknown"


def _target_file(tree: Path, rule_id: str) -> Path:
    step = rule_id.split(".")[0]
    name = "shared.rules.json" if step == "*" else f"{step}.rules.json"
    return tree / "compatibility" / name


def _all_hits(tree: Path, rule_id: str) -> list:
    """(path, row) for every row with this id across the compatibility rule files."""
    hits = []
    compat = tree / "compatibility"
    for path in sorted(compat.glob("*.rules.json")) if compat.is_dir() else []:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise OpsError(f"{path.name} is not valid JSON: {exc}") from None
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("id") == rule_id:
                hits.append((path, row))
    return hits


def _find(tree: Path, rule_id: str):
    """(path, row) of the single rule with this id. Raises OpsError if missing or defined twice."""
    hits = _all_hits(tree, rule_id)
    if not hits:
        raise OpsError(f"no rule {rule_id}")
    if len(hits) > 1:
        raise OpsError(f"rule {rule_id} is defined {len(hits)} times")
    return hits[0]


def _history(tree: Path, rule_id: str) -> dict:
    try:
        return h.load_history(tree, rule_id)
    except h.HistoryError as exc:
        raise OpsError(str(exc)) from None


def _errors(tree: Path) -> list:
    kb = load_knowledge(tree)
    return [f for f in validate_knowledge(kb, strict_builtin=True) if f.severity == "ERROR"]


def _transact(tree: Path, apply) -> None:
    baseline = {f.line() for f in _errors(tree)}
    txn = _Txn()
    try:
        apply(txn)
        fresh = [f for f in _errors(tree) if f.line() not in baseline]
        if fresh:
            raise OpsError("validation failed, nothing was written: " + "; ".join(f.line() for f in fresh))
    except Exception as exc:
        txn.rollback()
        if isinstance(exc, OpsError):
            raise
        if isinstance(exc, (RuleStoreError, h.HistoryError, ValueError, OSError)):
            raise OpsError(str(exc)) from exc
        raise


def _revise(tree: Path, rule_id: str, *, action: str, change, summary: str, author, at,
            files=()) -> dict:
    """Apply `change(row, doc) -> (new_row, provenance)` as a new revision of an existing rule."""
    author = resolve_author(author)
    at = at or _now()
    path, row = _find(tree, rule_id)
    doc = _history(tree, rule_id)
    new, provenance = change(dict(row), doc)
    new["rev"] = doc["entries"][-1]["rev"] + 1
    sidecar = h.history_path(tree, rule_id)

    def apply(txn):
        txn.save(path)
        txn.save(sidecar)
        for target, data in files:
            txn.save(target)
            txn.mkdir(target.parent)
            atomic_write_bytes(target, data)
        update_rule_file(path, replace={rule_id: new})
        h.append_entry(tree, rule_id, actor=author, at=at, action=action, rule_sha256=digest_obj(new),
                       summary=summary, provenance=provenance)

    _transact(tree, apply)
    return new


def create_rule(tree, row: dict, *, evidence=(), author=None, at=None, origin=ORIGIN_MANUAL,
                source_candidate=None, detectors_verified=False) -> dict:
    """Create one rule. `origin` is MANUAL (default) or GENERATED; GENERATED needs the candidate id it came from,
    recorded with the origin in the history `create` entry, and `detectors_verified=True` (its detector refs were
    resolved against the explicit detector table). The flag defaults to False, so no route into a generated rule skips
    template verification, whichever entry point is used. Every other check is the same for both origins."""
    tree = Path(tree)
    author = resolve_author(author)
    at = at or _now()
    rule_id = row.get("id")
    if origin not in CREATABLE_ORIGINS:
        raise OpsError(f"created rules have origin {' or '.join(CREATABLE_ORIGINS)}, not {origin!r}")
    if origin == ORIGIN_GENERATED and not source_candidate:
        raise OpsError("a GENERATED rule needs the source candidate id")
    if origin == ORIGIN_GENERATED and detectors_verified is not True:
        raise OpsError("detectors_unverified: a GENERATED rule needs detectors verified against the detector table")
    try:
        h.history_path(tree, rule_id)
    except h.HistoryError as exc:
        raise OpsError(str(exc)) from None
    if _all_hits(tree, rule_id):
        raise OpsError(f"duplicate rule id {rule_id}")
    new = dict(row)
    if rule_id.split(".")[0] != new.get("step"):
        raise OpsError("step must equal the step prefix of the rule id")
    if new.get("origin", origin) != origin:
        raise OpsError(f"created rules have origin {origin}")
    new["origin"] = origin
    new.setdefault("maturity", DEFAULT_MATURITY)
    if new["maturity"] not in CREATE_MATURITIES:
        raise OpsError(f"a new rule starts as one of {CREATE_MATURITIES}, not {new['maturity']}")
    if evidence:
        new["evidence"] = list(evidence)
    new.setdefault("evidence", [])
    new.setdefault("tests", [])
    new["rev"] = 1
    target = _target_file(tree, rule_id)

    def apply(txn):
        txn.save(target)
        txn.mkdir(target.parent)
        if not target.exists():
            atomic_write_bytes(target, b"[]\n")
        txn.save(h.history_path(tree, rule_id))
        txn.mkdir(h.history_path(tree, rule_id).parent)
        provenance = {"origin": origin, "source_candidate": source_candidate} if origin == ORIGIN_GENERATED else None
        h.create_history(tree, rule_id, actor=author, at=at, rule_sha256=digest_obj(new), summary="created",
                         validation_status="NOT_RUN", provenance=provenance)
        update_rule_file(target, append=[new])

    _transact(tree, apply)
    return new


def edit_rule(tree, rule_id: str, changes: dict, *, author=None, at=None) -> dict:
    tree = Path(tree)
    banned = sorted(set(changes) & set(PROTECTED_FIELDS))
    if banned:
        raise OpsError(f"fields cannot be edited: {', '.join(banned)}")
    if "maturity" in changes and changes["maturity"] not in EDIT_MATURITIES:
        raise OpsError(f"edit sets maturity only to {EDIT_MATURITIES}; use promote, disable or retire")

    def change(row, doc):
        return {**row, **changes}, {"changed": sorted(changes)}

    summary = "edited " + ", ".join(sorted(changes)) if changes else "edited (no field changes)"
    return _revise(tree, rule_id, action="edit", change=change, summary=summary, author=author, at=at)


def disable_rule(tree, rule_id: str, *, reason: str, author=None, at=None) -> dict:
    if not reason:
        raise OpsError("disable needs a reason")
    _, row = _find(Path(tree), rule_id)
    if row.get("maturity") == "RETIRED":
        raise OpsError("a retired rule cannot be disabled")

    def change(new, doc):
        previous = new.get("maturity", DEFAULT_MATURITY)
        new["maturity"] = "DRAFT"
        return new, {"previous_maturity": previous}

    return _revise(Path(tree), rule_id, action="disable", change=change, summary=f"disabled: {reason}",
                   author=author, at=at)


def _last_toggle(doc: dict):
    for entry in reversed(doc["entries"]):
        if entry["action"] in ("disable", "enable"):
            return entry
    return None


def enable_rule(tree, rule_id: str, *, author=None, at=None) -> dict:
    tree = Path(tree)
    _, row = _find(tree, rule_id)
    doc = _history(tree, rule_id)
    last = _last_toggle(doc)
    if row.get("maturity") != "DRAFT" or last is None or last["action"] != "disable":
        raise OpsError("rule is not disabled")

    def change(new, _doc):
        restored = last.get("provenance", {}).get("previous_maturity", DEFAULT_MATURITY)
        if restored not in CREATE_MATURITIES:
            restored = DEFAULT_MATURITY  # enable never restores FIX_ENABLED or RETIRED
        new["maturity"] = restored
        return new, {"restored_maturity": restored}

    return _revise(tree, rule_id, action="enable", change=change, summary="enabled", author=author, at=at)


def retire_rule(tree, rule_id: str, *, reason: str, author=None, at=None, superseded_by=None) -> dict:
    if not reason:
        raise OpsError("retire needs a reason")

    def change(new, _doc):
        new["maturity"] = "RETIRED"
        new["retired_reason"] = reason
        provenance = {"superseded_by": superseded_by} if superseded_by else {}
        return new, provenance

    return _revise(Path(tree), rule_id, action="retire", change=change, summary=f"retired: {reason}",
                   author=author, at=at)


def link_evidence(tree, rule_id: str, evidence_id: str, *, author=None, at=None, record=None) -> dict:
    """Cite evidence `evidence_id` from an existing rule, as one history revision. Without `record` the evidence file
    must already be in the tree. With `record` (its evidence dict, whose id is `evidence_id`) the file is written in the
    same transaction, so a refused revision leaves no file behind; an identical file already there is reused, a
    different one is refused (ids are never reused). The rule's other fields are untouched."""
    tree = Path(tree)
    files = ()
    if record is None:
        if evidence_id not in load_knowledge(tree).evidence:
            raise OpsError(f"unknown evidence {evidence_id}")
    else:
        if not isinstance(record, dict) or record.get("id") != evidence_id:
            raise OpsError(f"the evidence record must carry the id {evidence_id}")
        target = tree / "evidence" / f"{evidence_id}.json"
        if target.exists():
            if json.loads(target.read_text(encoding="utf-8")) != record:
                raise OpsError(f"evidence {evidence_id} already exists with different content; ids are never reused")
        else:
            files = [(target, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))]
    _, row = _find(tree, rule_id)
    if evidence_id in row.get("evidence", []):
        raise OpsError(f"{evidence_id} is already linked to {rule_id}")

    def change(new, _doc):
        new["evidence"] = list(new.get("evidence", [])) + [evidence_id]
        return new, {"evidence": evidence_id}

    return _revise(tree, rule_id, action="link_evidence", change=change,
                   summary=f"linked {evidence_id}", author=author, at=at, files=files)


def add_test(tree, rule_id: str, *, kind: str, fixture, author=None, at=None) -> dict:
    tree = Path(tree)
    if kind not in TEST_KINDS:
        raise OpsError(f"test kind must be one of {TEST_KINDS}")
    source = Path(fixture)
    if not source.is_file():
        raise OpsError(f"fixture {source} is not a file")
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    rel = f"fixtures/{rule_id}/{kind}-{source.name}"
    destination = tree / rel
    if destination.exists():
        raise OpsError(f"fixture {rel} already exists")
    _, row = _find(tree, rule_id)
    existing = row.get("tests", [])
    if isinstance(existing, list) and existing:
        raise OpsError("rule uses the legacy list form of tests; edit it by hand")

    def change(new, _doc):
        tests = dict(existing) if isinstance(existing, dict) else {}
        tests[kind] = rel
        new["tests"] = tests
        return new, {"test_kind": kind, "fixture": rel, "fixture_sha256": digest}

    return _revise(tree, rule_id, action="add_test", change=change, summary=f"added {kind} test",
                   author=author, at=at, files=[(destination, data)])


def validate_tree(tree) -> list:
    """Findings for the whole tree with the authoring checks on (strict)."""
    return validate_knowledge(load_knowledge(Path(tree)), strict_builtin=True)


def history_rule(tree, rule_id: str) -> dict:
    """The verified history document (raises OpsError if the chain or schema is broken)."""
    return _history(Path(tree), rule_id)


def inspect_rule(tree, rule_id: str) -> dict:
    tree = Path(tree)
    path, row = _find(tree, rule_id)
    kb = load_knowledge(tree)
    evidence = {ref: (kb.evidence.get(ref) or {}).get("status", "MISSING") for ref in row.get("evidence", [])}
    head = None
    history_problem = None
    try:
        last = h.load_history(tree, rule_id)["entries"][-1]
        head = {k: last[k] for k in ("rev", "action", "at", "actor", "summary")}
    except h.HistoryError as exc:
        history_problem = str(exc)
    problems = [f.line() for f in validate_tree(tree) if f.pointer == rule_id]
    return {
        "rule": row,
        "file": path.relative_to(tree).as_posix(),
        "evidence": evidence,
        "history_head": head,
        "history_problem": history_problem,
        "validation": problems,
    }

"""Automatic activation decision and activation recording (feature 012, plan section 5 and addendum C3).

`evaluate(prev_dir, new_dir, ...)` returns an `ActivationDecision`. It is pure with respect to the kb-home: it reads both
release trees and never writes. Blocking codes are stable strings (see the constants below). PARTIAL is allowed only
when no blocking code applies (D4). FAILED completeness is never allowed.

`activate_release(home, release_id, ...)` swaps the active pointer through `cli.kap_release.activate` (the one atomic
pointer swap; it is not reimplemented here) and records the outcome in `UpdateHistory`. It never raises past its
pointer check: any failure is recorded as ROLLED_BACK (the pointer still names the previous release) or FAILED.

`block(history, decision, ...)` appends a BLOCKED record for a decision that does not allow activation.

Trust for FIX_ENABLED rows uses the loader's own predicate, `safety.fix_row_trusted`: a byte-identical shipped row is
trusted by `safety.is_shipped_builtin_rule`; every other row must pass gates 1 to 5 and, when a certification record governs
it, that record (feature 012, Wave 3c). A FIX_ENABLED row that is new, or that changed from a previous FIX_ENABLED row, must
pass the same test. Trust is never granted by a row's own `origin` claim.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from odooflux.knowledge.loader import load_knowledge
from odooflux.knowledge.release.coverage_check import COMPLETE, PARTIAL
from odooflux.knowledge.release.manifest import verify_release_tree
from odooflux.knowledge.release.model import LOADABLE_STATES
from odooflux.knowledge.release import safety
from odooflux.knowledge.release.safety import fix_row_trusted, is_shipped_builtin_rule, load_provenance_index, \
    rule_gate_context
from odooflux.knowledge.release.store import read_active, read_release_state
from odooflux.knowledge.update.capability import (DETECT_ONLY, FIX_ENABLED, CapabilityError, capabilities,
                                                   diff_capabilities)
from odooflux.knowledge.update.history import HistoryError
from odooflux.utils.redaction import redact_text

# Stable blocking codes.
COMPLETENESS_FAILED = "COMPLETENESS_FAILED"
CAPABILITY_LOST = "CAPABILITY_LOST"
CAPABILITY_DOWNGRADED = "CAPABILITY_DOWNGRADED"
FIX_NOT_TRUSTED = "FIX_NOT_TRUSTED"
ENTERPRISE_COMPAT = "ENTERPRISE_COMPAT"
INTEGRITY = "INTEGRITY"
BLOCKING_CODES = (COMPLETENESS_FAILED, CAPABILITY_LOST, CAPABILITY_DOWNGRADED, FIX_NOT_TRUSTED, ENTERPRISE_COMPAT,
                  INTEGRITY)

PARTIAL_WARNING = "PARTIAL: incomplete coverage; unsupported transitions remain"
ALLOWED_COMPLETENESS = (COMPLETE, PARTIAL)


@dataclass(frozen=True)
class ActivationDecision:
    allowed: bool
    blocking: tuple = ()      # tuple of {"code", "detail"} dicts
    warnings: tuple = ()      # tuple of strings
    diff: Optional[dict] = None  # CapabilityDiff.to_dict(), or None when the capability comparison could not run

    @property
    def codes(self) -> tuple:
        return tuple(entry["code"] for entry in self.blocking)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "blocking": [dict(entry) for entry in self.blocking],
                "warnings": list(self.warnings), "diff": self.diff}


def _prior_verified(prev_dir, rid: str, row: dict, tree: Path) -> bool:
    """True when the previous installed release (this KB's own provenance) already carries the same row and the same
    confirmation and certification bytes, so the rule arrived through a build that was verified before."""
    if prev_dir is None:
        return False
    prev_tree = Path(prev_dir) / "knowledge"
    try:
        prev_kb = load_knowledge(prev_tree)
    except Exception:
        return False
    prev_row = next((r for r in prev_kb.rules if isinstance(r, dict) and r.get("id") == rid), None)
    if prev_row is None or safety._row_bytes(prev_row) != safety._row_bytes(row):
        return False
    for locate in (safety.confirmation_path, safety.certification_path):
        new_path, prev_path = locate(tree, rid), locate(prev_tree, rid)
        if new_path is None or prev_path is None or new_path.is_file() != prev_path.is_file():
            return False
        if new_path.is_file() and new_path.read_bytes() != prev_path.read_bytes():
            return False
    return True


def _fix_rule_problems(new_dir: Path, fix_ids: set, blob_root=None, prev_dir=None) -> list:
    """(rule_id, reason) for every FIX_ENABLED rule of the new release that is not trusted.

    Byte-identical shipped rows are trusted by `is_shipped_builtin_rule`. Every other FIX_ENABLED row, including a CHANGED
    row carried from a previous FIX_ENABLED row, must pass `fix_row_trusted`: gates 1 to 5, and its certification record
    when one governs the row. A trusted row that has a machine confirmation or a certified fixer also passes L2 (the
    retained blobs), or is refused when no blob store exists. A check that cannot run fails closed: every FIX_ENABLED row
    is reported."""
    tree = new_dir / "knowledge"
    try:
        kb = load_knowledge(tree)
        rows = {row["id"]: row for row in kb.rules if isinstance(row, dict) and "id" in row}
        shipped = {rid for rid in fix_ids if rid in rows and is_shipped_builtin_rule(rows[rid])}
        candidates = sorted(set(fix_ids) - shipped)
        index = load_provenance_index(tree) if candidates else None
        snapshot_dir = tree.resolve().parent / "snapshots"
        context = rule_gate_context(kb) if candidates else None
    except Exception as exc:  # fail closed: an unrunnable check trusts nothing it did not check
        return [(rid, f"gate check failed ({type(exc).__name__})") for rid in sorted(fix_ids)]
    problems = []
    for rid in candidates:
        row = rows.get(rid)
        if row is None:
            problems.append((rid, "rule row not found"))
            continue
        evidence_rows = [kb.evidence[eid] for eid in row.get("evidence") or []
                         if isinstance(eid, str) and eid in kb.evidence]
        try:
            trusted, found = fix_row_trusted(row, tree, evidence_rows, index, kb=kb, snapshot_dir=snapshot_dir,
                                             context=context)
        except Exception as exc:  # fail closed for this row only
            problems.append((rid, f"trust check failed ({type(exc).__name__})"))
            continue
        if not trusted:
            reasons = sorted(f"gate {finding['gate']} {finding['code']}" for finding in found)
            problems.append((rid, "; ".join(reasons) or "not trusted"))
            continue
        if safety.l2_required(row, tree):
            # L2 (addendum F2): the retained blobs of a confirmed or certified rule re-prove to the same witness before
            # activation, whatever its origin or approval (review item 3). Without a blob store L2 cannot run: the rule
            # is accepted only when this KB's installed previous release already activated the same row and artifacts.
            if blob_root is None:
                if not _prior_verified(prev_dir, rid, row, tree):
                    problems.append((rid, "confirmation-l2-unavailable: no blob store to re-prove the machine "
                                          "confirmation and no prior verified build; checked at L1 only, refused"))
                continue
            for code, detail in safety.source_problems(tree, rid, blob_root):
                problems.append((rid, f"{code}: {detail}"))
    return problems


def evaluate(prev_dir, new_dir, *, completeness, supersede=(), carried_inventory_findings=(),
             kb_home=None, blob_root=None) -> ActivationDecision:
    """Decide whether `new_dir` may replace `prev_dir` as the active release. `prev_dir` None means no previous release.

    `supersede` lists rule ids whose LOST or DOWNGRADED capability is accepted deliberately; it lets only those ids
    pass. `carried_inventory_findings` is the output of `inventory.carry_forward_compat`. When `kb_home` is given the
    new release must also be an installed (INSTALLED or ACTIVE) release recorded under it."""
    blocking, warnings = [], []

    def block(code, detail):
        blocking.append({"code": code, "detail": detail})

    superseded = frozenset(str(rid) for rid in (supersede or ()))
    if completeness not in ALLOWED_COMPLETENESS:
        block(COMPLETENESS_FAILED, f"completeness is {completeness!r}; activation requires COMPLETE or PARTIAL")
    elif completeness == PARTIAL:
        warnings.append(PARTIAL_WARNING)

    new_dir = Path(new_dir)
    problems = verify_release_tree(new_dir)
    if problems:
        block(INTEGRITY, "; ".join(problems))
    if kb_home is not None:
        try:
            state = read_release_state(new_dir)
        except Exception as exc:  # fail closed
            block(INTEGRITY, f"release state unreadable ({type(exc).__name__})")
        else:
            if state not in LOADABLE_STATES:
                block(INTEGRITY, f"release state is {state.value}, not installed")
    if carried_inventory_findings:
        modules = sorted({str(f.get("module")) for f in carried_inventory_findings})
        block(ENTERPRISE_COMPAT, f"carried Enterprise module(s) lost a dependency: {', '.join(modules)}")

    diff = None
    new_caps = {}
    try:
        new_caps = capabilities(new_dir)
        old_caps = {} if prev_dir is None else capabilities(prev_dir)
        result = diff_capabilities(old_caps, new_caps)
        diff = result.to_dict()
    except CapabilityError as exc:
        block(INTEGRITY, f"capability comparison failed ({exc.code})")

    if diff is not None:
        for rid in diff["lost"]:
            if rid in superseded:
                warnings.append(f"CAPABILITY_LOST accepted by supersede: {rid}")
            else:
                block(CAPABILITY_LOST, f"{rid} is no longer in the release (or explicitly retired)")
        for entry in diff["downgraded"]:
            rid = entry["id"]
            if rid in superseded:
                warnings.append(f"CAPABILITY_DOWNGRADED accepted by supersede: {rid}")
            else:
                block(CAPABILITY_DOWNGRADED, f"{rid} maturity {entry['from']} -> {entry['to']}")
        for entry in diff["changed"]:
            rid = entry["id"]
            if rid in new_caps and new_caps[rid].maturity == DETECT_ONLY:
                warnings.append(f"executable fields changed on DETECT_ONLY rule {rid}: "
                                f"{', '.join(entry['fields'])}")

    fix_ids = {rid for rid, cap in new_caps.items() if cap.maturity == FIX_ENABLED}
    for rid, reason in _fix_rule_problems(new_dir, fix_ids, blob_root, prev_dir) if fix_ids else []:
        block(FIX_NOT_TRUSTED, f"{rid}: {reason}")

    return ActivationDecision(allowed=not blocking and completeness in ALLOWED_COMPLETENESS,
                              blocking=tuple(blocking), warnings=tuple(warnings), diff=diff)


def _record(history, record: dict) -> Optional[str]:
    """Append to the history. Returns None on success, or the HistoryError code (never raises)."""
    if history is None:
        return None
    try:
        history.append(record)
    except HistoryError as exc:
        return exc.code
    return None


def block(history, decision: ActivationDecision, *, previous_release, new_release, fingerprint=None,
          source_revisions=None) -> dict:
    """Append a BLOCKED record naming the blocking codes. Raises ValueError for an allowed decision."""
    if decision.allowed:
        raise ValueError("block() needs a decision that is not allowed")
    codes = list(decision.codes)
    return history.append({
        "outcome": "BLOCKED",
        "fingerprint": fingerprint,
        "previous_release": previous_release,
        "new_release": new_release,
        "source_revisions": dict(source_revisions or {}),
        "reason": "BLOCKED: " + ", ".join(codes),
        "details": {"blocking": [dict(entry) for entry in decision.blocking], "warnings": list(decision.warnings)},
    })


def activate_release(home, release_id, *, history=None, previous_release=None, fingerprint=None,
                     source_revisions=None, build_inputs=None, now=None, fault_at=None) -> dict:
    """Activate `release_id` through `cli.kap_release.activate` and record the outcome.

    Returns {"state": "ACTIVE" | "ROLLED_BACK" | "FAILED", "release_id", "previous_release", "reason", "history_error"}.
    Never raises. On failure the active pointer is checked: still naming `previous_release` means ROLLED_BACK, anything
    else (including an unreadable pointer) means FAILED."""
    # Lazy import: cli.kap_release pulls in the release pipeline, which must not be imported by this module at load.
    from odooflux.cli import kap_release

    revisions = dict(source_revisions or {})
    try:
        kap_release.activate(home, release_id, fault_at=fault_at, now=now)
    except Exception as exc:  # any failure: the pointer check below decides ROLLED_BACK or FAILED
        reason = redact_text(f"{type(exc).__name__}: {exc}")
        try:
            current = read_active(home)
            still_previous = (current["release_id"] if current else None) == previous_release
        except Exception:
            still_previous = False
        state = "ROLLED_BACK" if still_previous else "FAILED"
        error = _record(history, {"outcome": state, "fingerprint": fingerprint, "previous_release": previous_release,
                                  "new_release": release_id, "source_revisions": revisions, "reason": reason})
        return {"state": state, "release_id": release_id, "previous_release": previous_release,
                "reason": reason, "history_error": error}

    error = _record(history, {"outcome": "ACTIVE", "fingerprint": fingerprint, "previous_release": previous_release,
                              "new_release": release_id, "source_revisions": revisions, "reason": None,
                              "details": {"build_inputs": build_inputs}})
    return {"state": "ACTIVE", "release_id": release_id, "previous_release": previous_release, "reason": None,
            "history_error": error}

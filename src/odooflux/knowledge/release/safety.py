"""Promotion gates 1 to 5 for FIX_ENABLED rules over a knowledge tree (REQ-KAP-018, REQ-KAP-027, REQ-KAP-039;
contracts/manual-rule-cli.md "Promotion gates", contracts/release-lifecycle.md "Rule execution").

`fix_gate_findings(tree_root)` is pure: it reads the tree through `knowledge.loader.load_knowledge` and returns a list of
findings `{rule_id, gate, code, detail}`. An empty list means every checked rule passes gates 1 to 5. Gate 6 (approval)
belongs to `promote` and is not evaluated here.

Scope: only FIX_ENABLED rules are gated. A rule with no `origin` (or `origin` BUILTIN) is a grandfathered built-in rule
(plan.md) and is skipped unless `include_builtin=True`.

Gate 1 provenance: a record's own `official: true` is a claim, not evidence. The claim is supported only when the record
has a `source_id` that resolves in the release provenance (`provenance/sources.json`, a list of
`{source_id, revision, snapshot_digest, official, status}`; optional `url`, `origin_url`, `snapshot_id` and `kind`) to an
entry that is official, has a usable status, is pinned to a 40-hex git SHA or a `sha256:<64hex>` digest, and is on the
official allow-list: its `url` is an allow-listed https URL, or it is a local clone whose `origin_url` is a verified origin
(`sources.official_origin`, the same contract the git-local adapter uses). A `local:` url with no verified `origin_url` is
never official evidence (`OFFICIAL_IDENTITY_UNVERIFIED`). A local-origin entry is also bound to its snapshot: the snapshot
file `<tree>/../snapshots/<snapshot_id>.json` must exist, its revision, origin and recomputed digest must equal the
entry's. The record must not be AI-originated and at least one location must carry `content_sha256`.
Provenance is `provenance` when given, else `<tree_root>/../provenance/sources.json`; when neither is readable the
provenance is unknown and every official claim is unsupported (fail closed).

Gate 4 runs the A001..A006 authoring checks (authoring/checks.py) on the loaded tree: an ERROR involving the rule (by id,
in its finding pointer or message) blocks it, as does a `conflicts_with` target that is FIX_ENABLED.

Fail closed: an absent `review_required` counts as not false.
"""

import functools
import json
import re
from pathlib import Path

from odooflux.knowledge.acquisition.sources import FORCED_UNOFFICIAL, load_allow_list, official_origin
from odooflux.knowledge.authoring.checks import check_authoring
from odooflux.knowledge.loader import load_knowledge
from odooflux.knowledge.release.canonical import digest_obj

FIX_ENABLED = "FIX_ENABLED"
BUILTIN_ORIGINS = (None, "BUILTIN")  # what a rule row CLAIMS; never used to skip a gate (see is_shipped_builtin_rule)


def _row_bytes(rule: dict) -> str:
    return json.dumps(rule, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@functools.lru_cache(maxsize=1)
def _shipped_rule_rows() -> dict:
    """id -> serialized row of every rule in the knowledge tree shipped with the package (read once per process)."""
    return {rule["id"]: _row_bytes(rule) for rule in load_knowledge().rules
            if isinstance(rule, dict) and isinstance(rule.get("id"), str)}


def is_shipped_builtin_rule(rule: dict) -> bool:
    """True only when `rule` is byte-for-byte the row shipped in the built-in tree. "Built-in rules are grandfathered"
    (migration-integration contract) means the shipped rows, not any row that claims `origin` BUILTIN or omits it: a
    release is not trusted to describe itself (REQ-KAP-027), so an origin-less FIX_ENABLED row that is new or altered goes
    through gates 1 to 5 like any other."""
    shipped = _shipped_rule_rows().get(rule.get("id"))
    return shipped is not None and shipped == _row_bytes(rule)
AI_ORIGIN = "AI_PROPOSED"
BLOCKING_STATUSES = frozenset({"UNVERIFIED", "CONFLICTING"})
TEST_KINDS = ("positive", "negative", "idempotence")
USABLE_SOURCE_STATUSES = ("VERIFIED",)
PINNED_REVISION = re.compile(r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
PROVENANCE_RELPATH = ("provenance", "sources.json")
SNAPSHOT_ID = re.compile(r"^ss-[0-9a-f]{12}$")
IDENTITY_CODE = "OFFICIAL_IDENTITY_UNVERIFIED"


def _finding(rule_id: str, gate: int, code: str, detail: str) -> dict:
    return {"rule_id": rule_id, "gate": gate, "code": code, "detail": detail}


def load_provenance_index(tree_root, provenance=None):
    """Map source_id -> entry, or None when provenance is unknown. Duplicated source_ids are ambiguous and dropped."""
    if provenance is None:
        path = Path(tree_root).resolve().parent.joinpath(*PROVENANCE_RELPATH)
        if not path.is_file():
            return None
        try:
            provenance = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    if isinstance(provenance, dict):
        provenance = provenance.get("sources")
    if not isinstance(provenance, list):
        return None
    seen, index = {}, {}
    for entry in provenance:
        if isinstance(entry, dict) and isinstance(entry.get("source_id"), str):
            seen[entry["source_id"]] = seen.get(entry["source_id"], 0) + 1
            index[entry["source_id"]] = entry
    return {sid: entry for sid, entry in index.items() if seen[sid] == 1}


def _snapshot_binding(entry: dict, origin: str, snapshot_dir):
    """None when the provenance revision, origin and digest equal the recomputed snapshot, else the reason."""
    snapshot_id = entry.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not SNAPSHOT_ID.match(snapshot_id) or snapshot_dir is None:
        return "snapshot_id is missing, digest is unverifiable"
    try:
        snap = json.loads((Path(snapshot_dir) / f"{snapshot_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "snapshot file is unavailable, digest is unverifiable"
    if not isinstance(snap, dict) or snap.get("source_id") != entry.get("source_id"):
        return "snapshot does not belong to the source"
    if snap.get("revision") != entry.get("revision") or snap.get("origin_url") != origin:
        return "provenance revision or origin does not match the snapshot"
    recorded = str(entry.get("snapshot_digest") or "")
    recorded = recorded[len("sha256:"):] if recorded.startswith("sha256:") else recorded
    recomputed = digest_obj({"source_id": snap["source_id"], "revision": snap["revision"],
                             "entries": snap.get("entries")})
    if not (recorded == recomputed == snap.get("snapshot_digest")):
        return "provenance digest does not match the recomputed snapshot digest"
    return None


def _official_problem(record: dict, index, allow_list: list, snapshot_dir=None):
    """None when the record's official claim is supported by provenance, else the reason it is not."""
    if record.get("origin") == AI_ORIGIN:
        return "record origin is AI"
    source_id = record.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        return "record has no source_id"
    if index is None:
        return "provenance is unknown"
    entry = index.get(source_id)
    if entry is None:
        return f"source_id {source_id} is not in the provenance"
    if entry.get("official") is not True:
        return f"source {source_id} is not official"
    if entry.get("kind") in FORCED_UNOFFICIAL:
        return f"source {source_id} is an unofficial kind ({entry.get('kind')})"
    if entry.get("status") not in USABLE_SOURCE_STATUSES:
        return f"source {source_id} status {entry.get('status')} is not usable"
    url, origin_url = entry.get("url"), entry.get("origin_url")
    local = isinstance(url, str) and url.startswith("local:")
    if local or origin_url is not None:
        origin = origin_url if isinstance(origin_url, str) else None
        if origin is None or official_origin(entry.get("kind"), origin, allow_list) != origin:
            return f"local source without verified origin ({IDENTITY_CODE})"
    else:
        if not isinstance(url, str) or not url:
            return f"source {source_id} has no url"
        if not any(url.startswith(prefix) for prefix in allow_list):
            return f"source {source_id} url is not on the official allow-list"
    revision = entry.get("revision")
    if not isinstance(revision, str) or not PINNED_REVISION.match(revision):
        return f"source {source_id} revision is not pinned"
    if local or origin_url is not None:
        binding = _snapshot_binding(entry, origin_url, snapshot_dir)
        if binding is not None:
            return f"{binding} ({IDENTITY_CODE})"
    locations = record.get("locations") or []
    if not any(isinstance(loc, dict) and isinstance(loc.get("content_sha256"), str)
               and SHA256_HEX.match(loc["content_sha256"]) for loc in locations):
        return "no location carries content_sha256"
    return None


def _gate1(rule_id, ids, records, kb_evidence, index, allow_list, snapshot_dir=None) -> list:
    out = []
    if not ids:
        out.append(_finding(rule_id, 1, "no-linked-evidence", "rule links no evidence"))
    for eid in ids:
        if eid not in kb_evidence:
            out.append(_finding(rule_id, 1, "evidence-missing", f"linked evidence {eid} does not exist"))
    for eid, record in records:
        if record.get("status") in BLOCKING_STATUSES:
            out.append(_finding(rule_id, 1, "evidence-unverified-or-conflicting",
                                f"{eid} has status {record.get('status')}"))
    supported = False
    for eid, record in records:
        if record.get("official") is not True:
            continue
        reason = _official_problem(record, index, allow_list, snapshot_dir)
        if reason is None:
            supported = True
        else:
            out.append(_finding(rule_id, 1, "official-claim-unsupported", f"{eid} claims official but {reason}"))
    if ids and not supported:
        out.append(_finding(rule_id, 1, "no-official-evidence",
                            "no linked record is officially supported and non-AI (AI or unofficial evidence alone is "
                            "refused)"))
    return out


def _gate2(rule, rule_id, records) -> list:
    out = []
    step = rule.get("step")
    if not isinstance(step, str) or not step:
        out.append(_finding(rule_id, 2, "step-missing", "rule has no step"))
    for eid, record in records:
        source = record.get("source_applicability")
        target = record.get("target_applicability")
        ok_source = isinstance(source, dict) and all(isinstance(source.get(k), str) and source.get(k)
                                                     for k in ("from", "to"))
        ok_target = isinstance(target, dict) and isinstance(target.get("from"), str) and bool(target.get("from"))
        if not (ok_source and ok_target):
            out.append(_finding(rule_id, 2, "applicability-missing",
                                f"{eid} lacks source or target version applicability"))
    return out


def _gate3(rule, rule_id) -> list:
    tests = rule.get("tests")
    if not isinstance(tests, dict) or any(not isinstance(tests.get(kind), str) or not tests.get(kind)
                                          for kind in TEST_KINDS):
        return [_finding(rule_id, 3, "tests-not-registered",
                         "positive, negative and idempotence tests must all be registered")]
    return []


def _involves(finding, rule_id: str) -> bool:
    if finding.pointer == rule_id:
        return True
    return re.search(r"(?<![\w.\-])" + re.escape(rule_id) + r"(?![\w.\-])", finding.message) is not None


def _gate4(rule, rule_id, fix_ids, authoring_errors) -> list:
    out = [_finding(rule_id, 4, "conflict-with-fix-enabled", f"conflicts_with {target} is FIX_ENABLED")
           for target in rule.get("conflicts_with") or [] if target in fix_ids]
    out += [_finding(rule_id, 4, finding.code, finding.message)
            for finding in authoring_errors if _involves(finding, rule_id)]
    return out


def _gate5(rule, rule_id) -> list:
    out = []
    fixer = rule.get("fixer_ref")
    if not isinstance(fixer, str) or not fixer:
        out.append(_finding(rule_id, 5, "fixer-ref-missing", "FIX_ENABLED rule has no fixer_ref"))
    if rule.get("review_required") is not False:
        out.append(_finding(rule_id, 5, "review-required", "review_required must be false for a FIX_ENABLED rule"))
    return out


def gate_findings(kb, index, *, include_builtin: bool = False, snapshot_dir=None) -> list:
    """Gates 1 to 5 for every FIX_ENABLED rule of a loaded KnowledgeBase (`index` from load_provenance_index)."""
    fix_ids = {rule.get("id") for rule in kb.rules if rule.get("maturity") == FIX_ENABLED}
    allow_list = load_allow_list()
    authoring_errors = [f for f in check_authoring(kb) if f.severity == "ERROR"]
    findings = []
    for rule in kb.rules:
        if rule.get("maturity") != FIX_ENABLED:
            continue
        if not include_builtin and is_shipped_builtin_rule(rule):
            continue
        rule_id = str(rule.get("id", "?"))
        ids = [eid for eid in rule.get("evidence") or [] if isinstance(eid, str)]
        records = [(eid, kb.evidence[eid]) for eid in ids if eid in kb.evidence]
        findings += _gate1(rule_id, ids, records, kb.evidence, index, allow_list, snapshot_dir)
        findings += _gate2(rule, rule_id, records)
        findings += _gate3(rule, rule_id)
        findings += _gate4(rule, rule_id, fix_ids, authoring_errors)
        findings += _gate5(rule, rule_id)
    return findings


def fix_gate_findings(tree_root, *, include_builtin: bool = False, provenance=None, snapshot_dir=None) -> list:
    """Gates 1 to 5. Snapshots for local-origin claims are read from `snapshot_dir`, default `<tree>/../snapshots`."""
    kb = load_knowledge(tree_root)
    if snapshot_dir is None:
        snapshot_dir = Path(tree_root).resolve().parent / "snapshots"
    return gate_findings(kb, load_provenance_index(tree_root, provenance), include_builtin=include_builtin,
                         snapshot_dir=snapshot_dir)

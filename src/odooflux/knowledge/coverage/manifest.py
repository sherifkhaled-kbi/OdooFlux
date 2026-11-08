"""Coverage manifest builder and consistency check (REQ-KAP-035, REQ-KAP-034; coverage-and-gates contract; data-model
CoverageManifest).

`build_coverage_manifest(data, ...)` computes the core parts (declared scope, inventory, per-pair file summary,
metrics, cross-checks), then the gates and the completeness decision, then the digest over the canonical body.

`check_consistency(manifest, data)` recomputes every part from the ledger and accounting in `data` and reports each
difference: stored versus recomputed core parts, the manifest digest, the schema, and the gates and completeness.
Empty list means consistent. The release build fails when this list is not empty (G-MANIFEST at release time).

`release_fields(manifest)` gives the two values the release manifest copies (`coverage_manifest_digest`,
`completeness`). The digest is an input of the release digest, and the coverage file is part of the release tree.
"""

import json

from odooflux.knowledge import validator as v
from odooflux.knowledge.coverage.crosscheck import run_crosschecks
from odooflux.knowledge.coverage.gates import decide, evaluate_gates
from odooflux.knowledge.coverage.metrics import compute_metrics
from odooflux.knowledge.extract.accounting import STATES
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.canonical import digest_obj

__all__ = ["ManifestError", "build_coverage_manifest", "check_consistency", "release_fields", "COVERAGE_FILE"]

COVERAGE_FILE = ("coverage", "coverage-manifest.json")
_SCHEMA_PATH = KNOWLEDGE_ROOT / "schemas" / "coverage_manifest.schema.json"
_SCHEMA_CACHE: dict = {}
CORE_KEYS = ("declared_scope", "inventory", "file_accounting_summary", "crosschecks")
_INPUT_KEYS = ("declared_scope", "inventory", "accounting", "changes", "sources")


class ManifestError(ValueError):
    """The coverage manifest could not be built (missing input, or the result breaks the schema)."""


def _schema() -> dict:
    if "coverage_manifest" not in _SCHEMA_CACHE:
        _SCHEMA_CACHE["coverage_manifest"] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE["coverage_manifest"]


def _prepare(data: dict) -> dict:
    """A copy of `data` with the derived keys the metric and gate functions read. Missing inputs are refused."""
    missing = [key for key in _INPUT_KEYS if data.get(key) is None]
    if missing:
        raise ManifestError(f"coverage manifest needs inputs {missing}")
    prepared = dict(data)
    index = data.get("evidence_index") or {}
    prepared["valid_evidence_ids"] = sorted(eid for eid, rec in index.items() if rec.get("valid"))
    if "manifest" not in data:
        changes = data["changes"]
        prepared["manifest"] = {
            "unresolved_change_ids": sorted(c["change_id"] for c in changes if c["disposition"] == "UNRESOLVED"),
            "change_count": len(changes),
        }
    return prepared


def _summary(accounting: list) -> list:
    rows = []
    for doc in accounting:
        counts = {state: 0 for state in STATES}
        for item in doc["files"]:
            counts[item["state"]] += 1
        rows.append({"step": doc["pair"]["step"], "from_snapshot": doc["pair"]["from_snapshot"],
                     "to_snapshot": doc["pair"]["to_snapshot"], "totals": counts,
                     "independent_count": doc["independent_count"]})
    return rows


def _core(prepared: dict) -> dict:
    return {
        "declared_scope": prepared["declared_scope"],
        "inventory": prepared["inventory"],
        "file_accounting_summary": _summary(prepared["accounting"]),
        "metrics": compute_metrics(prepared),
        "crosschecks": run_crosschecks(prepared),
    }


def _gates(prepared: dict, core: dict, findings: list, checked_at: str, strict: bool) -> list:
    data = dict(prepared)
    data["crosschecks"] = core["crosschecks"]
    data["consistency_findings"] = list(findings)
    return evaluate_gates(data, checked_at=checked_at, strict_xcheck=strict)


def build_coverage_manifest(data: dict, *, checked_at: str, tool_version: str, schema_versions: dict,
                            strict_xcheck: bool = False, limits=()) -> dict:
    """Build the manifest from ledger and accounting data. `checked_at` is a UTC `Z` timestamp from the caller.

    Raises ManifestError when an input is missing or the result does not match the schema. The result's
    completeness comes from `gates.decide`; `limits` must name every partial gate (checked by `decide`)."""
    prepared = _prepare(data)
    core = _core(prepared)
    # The build compares nothing against stored values; the cross-artifact comparison is check_consistency.
    gates = _gates(prepared, core, [], checked_at, strict_xcheck)
    decision = decide(gates, limits)
    body = {**core, "gates": gates, "limits": list(limits), "completeness": decision["completeness"],
            "tool": {"version": tool_version, "schema_versions": dict(schema_versions)}}
    manifest = {**body, "manifest_digest": digest_obj(body)}
    problems = v.check(manifest, _schema())
    if problems:
        raise ManifestError(f"coverage manifest does not match the schema: {problems[:3]}")
    return manifest


def release_fields(manifest: dict) -> dict:
    """The values the release manifest copies from the coverage manifest."""
    return {"coverage_manifest_digest": manifest["manifest_digest"], "completeness": manifest["completeness"]}


def _frac(item) -> str:
    if not item:
        return "missing"
    return f"{item.get('numerator')}/{item.get('denominator')}"


def _core_findings(stored: dict, recomputed: dict) -> list:
    out = []
    for key in CORE_KEYS:
        if stored.get(key) != recomputed[key]:
            out.append(f"{key} differs from recomputation")
    stored_metrics = {item.get("id"): item for item in stored.get("metrics") or []}
    for item in recomputed["metrics"]:
        if stored_metrics.get(item["id"]) != item:
            out.append(f"{item['id']} differs: stored {_frac(stored_metrics.get(item['id']))} "
                       f"recomputed {_frac(item)}")
    return out


def check_consistency(manifest: dict, data: dict) -> list:
    """Every difference between the stored manifest and a recomputation from `data` (empty when consistent)."""
    findings = []
    body = {k: val for k, val in manifest.items() if k != "manifest_digest"}
    if manifest.get("manifest_digest") != digest_obj(body):
        findings.append("manifest_digest does not match the manifest content")
    for pointer, message in v.check(manifest, _schema()):
        findings.append(f"schema {pointer or '/'}: {message}")
    try:
        prepared = _prepare(data)
    except ManifestError as exc:
        return findings + [str(exc)]
    core = _core(prepared)
    findings += _core_findings(manifest, core)
    stored_gates = manifest.get("gates") or []
    if not stored_gates:
        return findings + ["no gates stored"]
    xcheck = [g for g in stored_gates if g.get("gate_id") == "G-XCHECK"]
    strict = bool(xcheck and xcheck[0].get("blocking"))
    recomputed = _gates(prepared, core, _core_findings(manifest, core), stored_gates[0]["checked_at"], strict)
    stored_by_id = {g.get("gate_id"): g for g in stored_gates}
    for gate in recomputed:
        if stored_by_id.get(gate["gate_id"]) != gate:
            stored_status = (stored_by_id.get(gate["gate_id"]) or {}).get("status", "missing")
            findings.append(f"{gate['gate_id']} differs: stored {stored_status} recomputed {gate['status']}")
    decision = decide(recomputed, manifest.get("limits") or [])
    if decision["completeness"] != manifest.get("completeness"):
        findings.append(f"completeness stored {manifest.get('completeness')} recomputed "
                        f"{decision['completeness']}")
    return findings

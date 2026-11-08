"""Release gates and the completeness decision (REQ-KAP-034; coverage-and-gates contract, gates and completeness
sections).

`evaluate_gates(data, checked_at=..., strict_xcheck=...)` returns one ReleaseGateResult per gate, in contract order.
Each gate reads only its own input key. A missing input key gives NOT_RUN. `decide(gates, limits)` gives COMPLETE,
PARTIAL or FAILED:

- any blocking gate not PASS and not partial-able gives FAILED (NOT_RUN counts as not PASS);
- otherwise any partial-able failure gives PARTIAL, but only with limits that name each failing gate;
- otherwise COMPLETE.

Partial-able reason codes: G-SRC `OPTIONAL_SOURCE_NOT_VERIFIED`; G-FILES `FILES_FAILED`, `FILES_UNSUPPORTED`;
G-DISP `DISP_UNRESOLVED`. A required source is never partial-able. Offenders are identifiers only (paths, ids),
never file contents; they are sorted and capped at OFFENDER_CAP, with the full count in `offenders_total`.

Data keys read by `evaluate_gates` (all optional, missing means NOT_RUN for that gate):
sources, accounting, changes, evidence_index, release_rules, manifest, consistency_findings, rule_findings,
safety_findings, redaction_findings, crosschecks.
"""

__all__ = ["evaluate_gates", "decide", "GATE_IDS", "PARTIAL_ALLOWED", "OFFENDER_CAP"]

GATE_IDS = ("G-SRC", "G-FILES", "G-CLASS", "G-DISP", "G-EVID", "G-MANIFEST", "G-RULES", "G-SAFE", "G-XCHECK",
            "G-SECRETS")
GATE_NAMES = {
    "G-SRC": "required sources verified",
    "G-FILES": "changed files accounted and analyzed",
    "G-CLASS": "no hidden classification failure",
    "G-DISP": "no unresolved change omitted from the manifest",
    "G-EVID": "required evidence present and official for FIX_ENABLED",
    "G-MANIFEST": "digests, counts and step lists consistent",
    "G-RULES": "rules pass schema, authoring and test gates",
    "G-SAFE": "FIX_ENABLED rules pass safety gates (INV-5)",
    "G-XCHECK": "cross-checks pass (warning unless strict)",
    "G-SECRETS": "redaction scan clean",
}
NON_BLOCKING = frozenset({"G-XCHECK"})
PARTIAL_ALLOWED = {
    "G-SRC": frozenset({"OPTIONAL_SOURCE_NOT_VERIFIED"}),
    "G-FILES": frozenset({"FILES_FAILED", "FILES_UNSUPPORTED"}),
    "G-DISP": frozenset({"DISP_UNRESOLVED"}),
}
OFFENDER_CAP = 20
EVIDENCE_DISPOSITIONS = ("RULE_CREATED", "EXISTING_RULE_LINKED", "DETECTION_ONLY")
BUILTIN_ORIGINS = (None, "BUILTIN")
FIX_ENABLED = "FIX_ENABLED"
AI_ORIGIN = "AI_PROPOSED"


def _result(gate_id: str, reasons, offenders, checked_at: str, *, status=None, blocking=None) -> dict:
    reason_codes = sorted(set(reasons))
    unique = sorted(set(offenders))
    if status is None:
        status = "FAIL" if reason_codes else "PASS"
    if blocking is None:
        blocking = gate_id not in NON_BLOCKING
    return {"gate_id": gate_id, "name": GATE_NAMES[gate_id], "blocking": blocking, "status": status,
            "reason_codes": reason_codes, "offenders": unique[:OFFENDER_CAP], "offenders_total": len(unique),
            "checked_at": checked_at}


def _not_run(gate_id: str, checked_at: str) -> dict:
    return _result(gate_id, [], [], checked_at, status="NOT_RUN")


def _g_src(data, at):
    if data.get("sources") is None:
        return _not_run("G-SRC", at)
    reasons, offenders = [], []
    for source in data["sources"]:
        if source.get("status") == "VERIFIED":
            continue
        if source.get("required"):
            reasons.append("SOURCE_REQUIRED_NOT_VERIFIED")
        else:
            reasons.append("OPTIONAL_SOURCE_NOT_VERIFIED")
        offenders.append(source["source_id"])
    return _result("G-SRC", reasons, offenders, at)


def _g_files(data, at):
    if data.get("accounting") is None:
        return _not_run("G-FILES", at)
    reasons, offenders = [], []
    for doc in data["accounting"]:
        step = doc["pair"]["step"]
        files = doc["files"]
        counts = {}
        for item in files:
            counts[item["state"]] = counts.get(item["state"], 0) + 1
        if counts.get("PENDING"):
            reasons.append("FILES_PENDING")
            offenders.append(f"{step}:pending={counts['PENDING']}")
        if len(files) != doc["independent_count"] or sum(doc["totals"].values()) != len(files):
            reasons.append("FILES_INV3")
            offenders.append(f"{step}:files={len(files)} independent={doc['independent_count']}")
        if counts.get("FAILED"):
            reasons.append("FILES_FAILED")
            offenders += [f"{step}:{item['path']}" for item in files if item["state"] == "FAILED"]
        if counts.get("UNSUPPORTED"):
            reasons.append("FILES_UNSUPPORTED")
            offenders += [f"{step}:{item['path']}" for item in files if item["state"] == "UNSUPPORTED"]
    return _result("G-FILES", reasons, offenders, at)


def _g_class(data, at):
    if data.get("accounting") is None or data.get("changes") is None:
        return _not_run("G-CLASS", at)
    visible = set()
    for change in data["changes"]:
        if change.get("class") == "UNKNOWN" or change.get("disposition") == "UNRESOLVED":
            visible.update(loc["path"] for loc in change.get("locations", []))
    offenders = []
    for doc in data["accounting"]:
        offenders += [item["path"] for item in doc["files"]
                      if item["state"] == "FAILED" and item["path"] not in visible]
    return _result("G-CLASS", ["CLASS_FAILURE_HIDDEN"] if offenders else [], offenders, at)


def _g_disp(data, at):
    if data.get("changes") is None or data.get("manifest") is None:
        return _not_run("G-DISP", at)
    manifest = data["manifest"]
    unresolved = [c["change_id"] for c in data["changes"] if c["disposition"] == "UNRESOLVED"]
    listed = set(manifest.get("unresolved_change_ids", []))
    reasons, offenders = [], list(unresolved)
    if [cid for cid in unresolved if cid not in listed]:
        reasons.append("DISP_UNRESOLVED_NOT_IN_MANIFEST")
    if manifest.get("change_count") != len(data["changes"]):
        reasons.append("DISP_COUNT_MISMATCH")
    if unresolved:
        reasons.append("DISP_UNRESOLVED")
    return _result("G-DISP", reasons, offenders, at)


def _valid_evidence(index: dict, eid: str) -> dict:
    record = index.get(eid)
    return record if record and record.get("valid") else {}


def _g_evid(data, at):
    if data.get("changes") is None or data.get("evidence_index") is None or data.get("release_rules") is None:
        return _not_run("G-EVID", at)
    index = data["evidence_index"]
    reasons, offenders = [], []
    for change in data["changes"]:
        if change["disposition"] not in EVIDENCE_DISPOSITIONS:
            continue
        cited = change.get("disposition_data", {}).get("evidence_ids", [])
        if not any(_valid_evidence(index, eid) for eid in cited):
            reasons.append("EVIDENCE_MISSING")
            offenders.append(change["change_id"])
    for rule in data["release_rules"]:
        if rule.get("maturity") != FIX_ENABLED or rule.get("origin") in BUILTIN_ORIGINS:
            continue
        supported = [eid for eid in rule.get("evidence_ids", [])
                     if _valid_evidence(index, eid).get("official") is True
                     and _valid_evidence(index, eid).get("origin") != AI_ORIGIN]
        if not supported:
            reasons.append("FIX_EVIDENCE_NOT_OFFICIAL")
            offenders.append(rule["id"])
    return _result("G-EVID", reasons, offenders, at)


def _g_manifest(data, at):
    findings = data.get("consistency_findings")
    if findings is None:
        return _not_run("G-MANIFEST", at)
    return _result("G-MANIFEST", ["MANIFEST_INCONSISTENT"] if findings else [], findings, at)


def _g_rules(data, at):
    if data.get("release_rules") is None or data.get("rule_findings") is None:
        return _not_run("G-RULES", at)
    reasons, offenders = [], []
    for rule in data["release_rules"]:
        if rule.get("in_release_delta") and not rule.get("validation_passed"):
            reasons.append("RULES_VALIDATION_FAILED")
            offenders.append(rule["id"])
    for finding in data["rule_findings"]:
        reasons.append("RULES_FINDINGS")
        offenders.append(finding["rule_id"])
    return _result("G-RULES", reasons, offenders, at)


def _g_safe(data, at):
    if data.get("safety_findings") is None or data.get("release_rules") is None:
        return _not_run("G-SAFE", at)
    reasons, offenders = [], []
    for finding in data["safety_findings"]:
        reasons.append("SAFETY_FINDINGS")
        offenders.append(finding["rule_id"])
    for rule in data["release_rules"]:
        if rule.get("maturity") == FIX_ENABLED and rule.get("origin") not in BUILTIN_ORIGINS \
                and not rule.get("safety_passed"):
            reasons.append("SAFETY_NOT_VERIFIED")
            offenders.append(rule["id"])
    return _result("G-SAFE", reasons, offenders, at)


def _g_xcheck(data, at, strict: bool):
    items = data.get("crosschecks")
    if items is None:
        return _not_run("G-XCHECK", at)
    failed = [item["id"] for item in items if item["status"] == "FAIL"]
    not_run = [item["id"] for item in items if item["status"] in ("NOT_RUN", "NOT_MEASURED")]
    reasons = []
    if failed:
        reasons.append("XCHECK_FAILED")
    if not_run:
        reasons.append("XCHECK_NOT_RUN")
    if failed:
        status = "FAIL" if strict else "WARN"
    else:
        status = "WARN" if not_run else "PASS"
    return _result("G-XCHECK", reasons, failed + not_run, at, status=status, blocking=strict)


def _g_secrets(data, at):
    findings = data.get("redaction_findings")
    if findings is None:
        return _not_run("G-SECRETS", at)
    return _result("G-SECRETS", ["SECRET_PATTERN"] if findings else [], findings, at)


def evaluate_gates(data: dict, *, checked_at: str, strict_xcheck: bool = False) -> list:
    """All ten gates in contract order. `checked_at` is a UTC `Z` timestamp supplied by the caller."""
    return [
        _g_src(data, checked_at),
        _g_files(data, checked_at),
        _g_class(data, checked_at),
        _g_disp(data, checked_at),
        _g_evid(data, checked_at),
        _g_manifest(data, checked_at),
        _g_rules(data, checked_at),
        _g_safe(data, checked_at),
        _g_xcheck(data, checked_at, strict_xcheck),
        _g_secrets(data, checked_at),
    ]


def decide(gates: list, limits=()) -> dict:
    """Completeness decision. Returns `{completeness, reasons, partial_gates}`."""
    hard, partial, not_run = [], [], []
    for gate in gates:
        if not gate["blocking"] or gate["status"] == "PASS":
            continue
        if gate["status"] == "NOT_RUN":
            not_run.append(gate["gate_id"])
        elif gate["status"] == "FAIL" and gate["reason_codes"] \
                and set(gate["reason_codes"]) <= PARTIAL_ALLOWED.get(gate["gate_id"], frozenset()):
            partial.append(gate["gate_id"])
        else:
            hard.append(gate["gate_id"])
    if hard or not_run:
        names = [f"{gid} FAIL" for gid in hard] + [f"{gid} NOT_RUN" for gid in not_run]
        return {"completeness": "FAILED", "reasons": names, "partial_gates": []}
    if not partial:
        return {"completeness": "COMPLETE", "reasons": [], "partial_gates": []}
    named = [str(text).strip() for text in limits if str(text).strip()]
    if not named:
        return {"completeness": "FAILED", "reasons": ["PARTIAL_WITHOUT_LIMITS"], "partial_gates": []}
    unnamed = [gid for gid in partial if not any(gid in text for text in named)]
    if unnamed:
        return {"completeness": "FAILED", "reasons": [f"LIMITS_DO_NOT_NAME {gid}" for gid in unnamed],
                "partial_gates": []}
    return {"completeness": "PARTIAL", "reasons": [f"{gid} FAIL (allowed partial)" for gid in sorted(partial)],
            "partial_gates": sorted(partial)}

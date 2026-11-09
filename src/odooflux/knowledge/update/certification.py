"""Automated certification record ``odooflux.fix-certification/1`` (Feature 012, plan section 4, addendum A4, Wave 3c).

Core half. This module holds the record schema, canonical digests, evidence checks, the stored-versus-recomputed
comparison, the reference string and ``issue``/``verify``. It never imports the transformers or parsers (REQ-ARC-001:
knowledge is core). The execution side (fix templates, real primitives through the engine) lives in
``odooflux.transformers.certify_exec.FixCertifier``.

Authority: the executor is process-wide and single-assignment. The composition root calls ``attach_executor`` once
(``builtins.build_context``); ``issue`` and ``verify`` read it through ``trusted_executor``. No caller can supply an
executor, and a second, different executor is refused. Without an attached executor ``verify`` returns the
``CERT_EXECUTOR_MISSING`` finding and ``issue`` raises it (fail closed).

Source classification: ``source_confidentiality_from_index`` derives the mapping ``source_id -> public|enterprise`` from
the verified provenance index. The trust function (``release/safety.fix_row_trusted``) always computes it that way.

``verify`` recomputes everything from scratch and compares every stored field. No pass flag is read or trusted, and
check results are stored only as digests.

Rule digest: the canonical digest of the whole rule row EXCEPT ``maturity``, ``review_required`` and ``approval``. A
maturity change therefore does not invalidate a record. ``approval`` is a label, not content: a record cannot contain
the reference that points at it. Every other field of the row, including params, fixer_ref and evidence, does.

Change class: the rule row and evidence rows carry no ledger class, so the class is an input bound into the record. The
caller must supply the CONFIRMED class (from a verified machine confirmation); the record's own class is only compared.
A GENERATED row is refused unless the caller states `confirmation_verified=True` (feature 012, Addendum F2/F3).

A record is not a human approval: its reference is ``auto-cert:<policy>:<record_digest>``.
"""

from odooflux.knowledge.acquisition.sources import is_enterprise_kind
from odooflux.knowledge.release.canonical import CanonicalError, digest_obj

POLICY_VERSION = "1"
RECORD_SCHEMA = "odooflux.fix-certification/1"
CONFIDENTIALITY = ("public", "enterprise")  # one unified knowledge base: sources are classified, not split by line
PROBE_RULE_ID = "auto-cert.conflict-probe"  # second, different rule id used by the executor's conflict check
REFERENCE_PREFIX = "auto-cert"
RULE_DIGEST_EXCLUDED = ("maturity", "review_required", "approval")
CHECK_NAMES = ("positive", "negative", "idempotence", "conflict", "regression")
RECORD_KEYS = ("schema", "policy_version", "evidence_sources", "rule_id", "rule_digest", "change_class", "template_id",
               "template_version", "transformer", "evidence", "fixtures", "outputs", "checks", "record_digest")
GENERATED_ORIGIN = "GENERATED"  # a generated row is certifiable only with a verified machine confirmation
EXECUTOR_MISSING = "CERT_EXECUTOR_MISSING"
EXECUTOR_CONFLICT = "CERT_EXECUTOR_CONFLICT"

_FIELD_CODES = {
    "schema": "schema_mismatch", "policy_version": "policy_version_mismatch", "evidence_sources": "source_confidentiality_changed",
    "rule_id": "rule_id_mismatch", "rule_digest": "rule_changed", "change_class": "change_class_mismatch",
    "template_id": "template_mismatch", "template_version": "template_version_mismatch",
    "evidence": "evidence_changed", "fixtures": "fixture_mismatch", "outputs": "output_mismatch",
    "checks": "check_mismatch", "record_digest": "record_digest_mismatch",
}

_EXECUTOR = None  # process-wide, single assignment: the composition root's executor (see attach_executor)


class CertificationError(ValueError):
    """Issue refused, or an executor step failed. ``code`` is machine-readable, ``detail`` is for humans."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def attach_executor(executor) -> None:
    """Attach the process-wide certification executor. Re-attaching the identical object is a no-op; attaching a
    different object once one is attached raises ``CertificationError(CERT_EXECUTOR_CONFLICT)``."""
    global _EXECUTOR
    if executor is None:
        raise CertificationError(EXECUTOR_MISSING, "refusing to attach None as the fix executor")
    if _EXECUTOR is None:
        _EXECUTOR = executor
    elif _EXECUTOR is not executor:
        raise CertificationError(EXECUTOR_CONFLICT, "a different fix executor is already attached in this process")


def trusted_executor():
    """The attached executor, or ``CertificationError(CERT_EXECUTOR_MISSING)`` when none is attached."""
    if _EXECUTOR is None:
        raise CertificationError(EXECUTOR_MISSING, "no fix executor is attached (composition root, builtins.build_context)")
    return _EXECUTOR


def _reset_for_tests() -> None:
    """TEST ONLY: detach the executor so that tests can exercise the fail-closed path. Production code never calls it."""
    global _EXECUTOR
    _EXECUTOR = None


def source_confidentiality_from_index(index) -> dict:
    """``source_id -> "public" | "enterprise"`` from a verified provenance index (``load_provenance_index``).

    A source is enterprise iff its kind is an Enterprise kind (``sources.is_enterprise_kind``). ``None`` (provenance
    unknown) yields an empty mapping, so every evidence source is then unclassified and refused."""
    if not isinstance(index, dict):
        return {}
    out = {}
    for source_id, entry in index.items():
        if isinstance(source_id, str) and isinstance(entry, dict):
            out[source_id] = "enterprise" if is_enterprise_kind(entry.get("kind")) else "public"
    return out


def rule_digest(rule_row: dict) -> str:
    """Canonical digest of the rule row without ``maturity``, ``review_required`` and ``approval``."""
    try:
        return digest_obj({k: v for k, v in rule_row.items() if k not in RULE_DIGEST_EXCLUDED})
    except CanonicalError as exc:
        raise CertificationError("rule_not_canonical", str(exc)) from None


def _evidence_problems(rule_row: dict, rows) -> list:
    if not isinstance(rows, (list, tuple)) or not rows:
        return [("evidence_missing", "no evidence rows supplied")]
    problems, seen = [], []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            problems.append(("evidence_invalid", "evidence row without a string id"))
            continue
        seen.append(row["id"])
    if len(seen) != len(set(seen)):
        problems.append(("evidence_invalid", "duplicate evidence id"))
    wanted = rule_row.get("evidence")
    wanted = set(wanted) if isinstance(wanted, list) else set()
    for missing in sorted(wanted - set(seen)):
        problems.append(("evidence_missing", f"rule evidence {missing} was not supplied"))
    for extra in sorted(set(seen) - wanted):
        problems.append(("evidence_unexpected", f"evidence {extra} is not listed by the rule"))
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        if row.get("official") is not True:
            problems.append(("evidence_not_official", f"evidence {row['id']} is not official"))
        rule_ids = row.get("rule_ids")
        if not isinstance(rule_ids, list) or rule_row.get("id") not in rule_ids:
            problems.append(("evidence_rule_mismatch", f"evidence {row['id']} does not name the rule"))
    return problems


def _source_problems(evidence_rows, source_confidentiality):
    """``(problems, evidence_sources)``. Each evidence row's source must be classified by the caller's mapping
    (the verified provenance index). A source missing from the mapping is a problem and is never defaulted."""
    mapping = source_confidentiality if isinstance(source_confidentiality, dict) else {}
    problems, bindings = [], {}
    for row in evidence_rows if isinstance(evidence_rows, (list, tuple)) else ():
        if not isinstance(row, dict):
            continue
        sid = row.get("source_id")
        if not isinstance(sid, str) or not sid:
            problems.append(("source_missing", f"evidence {row.get('id')} names no source_id"))
        elif sid not in mapping:
            problems.append(("source_unclassified", f"source {sid} has no confidentiality in the provenance index"))
        elif mapping[sid] not in CONFIDENTIALITY:
            problems.append(("source_confidentiality_invalid",
                             f"source {sid} confidentiality must be one of {', '.join(CONFIDENTIALITY)}"))
        else:
            bindings[sid] = mapping[sid]
    return problems, [{"source_id": sid, "confidentiality": bindings[sid]} for sid in sorted(bindings)]


def _eligible(executor, rule_row, change_class, confirmation_verified):
    """The executor's eligibility. Only a GENERATED row carries the confirmation flag (the only origin it gates), so
    every other row is asked exactly as before."""
    if rule_row.get("origin") == GENERATED_ORIGIN:
        return executor.eligible(rule_row, change_class, confirmation_verified=confirmation_verified is True)
    return executor.eligible(rule_row, change_class)


def _build(rule_row, evidence_rows, *, source_confidentiality, change_class, confirmation_verified=False):
    """Recompute the whole record. Returns ``(record or None, problems)``; ``problems`` is ``[(code, detail)]``.
    Raises ``CertificationError(CERT_EXECUTOR_MISSING)`` first when no executor is attached."""
    executor = trusted_executor()  # fail closed first: nothing is recomputed without the executed checks
    problems = []
    if not isinstance(rule_row, dict) or not isinstance(rule_row.get("id"), str) or not rule_row.get("id"):
        return None, problems + [("not_eligible", "rule row has no string id")]
    if rule_row.get("origin") == GENERATED_ORIGIN and confirmation_verified is not True:
        return None, problems + [("not_eligible", "a GENERATED rule needs a verified machine confirmation "
                                                  "(confirmation_verified)")]
    template_id, reason = _eligible(executor, rule_row, change_class, confirmation_verified)
    if template_id is None:
        return None, problems + [("not_eligible", reason)]
    problems += _evidence_problems(rule_row, evidence_rows)
    source_problems, evidence_sources = _source_problems(evidence_rows, source_confidentiality)
    problems += source_problems
    try:
        rd = rule_digest(rule_row)
        transformer = executor.transformer_identity(template_id)
    except CertificationError as exc:
        return None, problems + [(exc.code, exc.detail)]
    run = executor.exercise(rule_row, template_id, rule_row["params"])
    problems += run["problems"]
    if run["fixtures"] is None:
        return None, problems
    try:
        evidence = sorted(({"id": row["id"], "digest": digest_obj(row)}
                           for row in evidence_rows if isinstance(row, dict) and isinstance(row.get("id"), str)),
                          key=lambda item: item["id"]) if isinstance(evidence_rows, (list, tuple)) else []
        body = {"schema": RECORD_SCHEMA, "policy_version": POLICY_VERSION, "evidence_sources": evidence_sources,
                "rule_id": rule_row["id"], "rule_digest": rd, "change_class": change_class,
                "template_id": template_id, "template_version": run["template_version"],
                "transformer": transformer, "evidence": evidence, "fixtures": run["fixtures"],
                "outputs": run["outputs"], "checks": run["checks"]}
        record = dict(body, record_digest=digest_obj(body))
    except CanonicalError as exc:
        return None, problems + [("record_not_canonical", str(exc))]
    return record, problems


def issue(rule_row: dict, evidence_rows, *, source_confidentiality: dict = None, change_class: str = None,
          confirmation_verified: bool = False) -> dict:
    """Return a certification record, or raise ``CertificationError(code, detail)`` for the first problem found.

    ``source_confidentiality`` maps each evidence ``source_id`` to ``public`` or ``enterprise`` (the trust path passes
    ``source_confidentiality_from_index``). ``change_class`` is the confirmed class. The executor is the attached one;
    there is no other source of it."""
    record, problems = _build(rule_row, evidence_rows, source_confidentiality=source_confidentiality,
                              change_class=change_class, confirmation_verified=confirmation_verified)
    if problems:
        code, detail = problems[0]
        raise CertificationError(code, detail)
    return record


def reference(record: dict) -> str:
    """Approval reference, labelled automated: ``auto-cert:<policy>:<record_digest>``."""
    return f"{REFERENCE_PREFIX}:{record['policy_version']}:{record['record_digest']}"


def _diff_paths(stored, fresh, prefix="") -> list:
    """Dotted paths where ``stored`` and ``fresh`` differ. Dicts are compared key by key; other values whole."""
    if isinstance(stored, dict) and isinstance(fresh, dict):
        paths = []
        for key in sorted(set(stored) | set(fresh), key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in stored or key not in fresh:
                paths.append(child)
            else:
                paths.extend(_diff_paths(stored[key], fresh[key], child))
        return paths
    return [] if stored == fresh else [prefix]


def _code_for(path: str) -> str:
    top = path.split(".")[0]
    if top == "transformer":
        return "transformer_source_changed" if path == "transformer.source_digest" else "transformer_mismatch"
    return _FIELD_CODES.get(top, "field_mismatch")


def _finding(code: str, field: str, detail: str) -> dict:
    return {"code": code, "field": field, "detail": detail}


def verify(rule_row: dict, evidence_rows, record, *, source_confidentiality: dict = None,
           change_class: str = None, confirmation_verified: bool = False) -> list:
    """Recompute from scratch and compare everything. Returns a list of findings; ``[]`` only when valid.

    Without an attached executor the result is a single ``CERT_EXECUTOR_MISSING`` finding."""
    try:
        trusted_executor()
    except CertificationError as exc:
        return [_finding(exc.code, "", exc.detail)]
    if not isinstance(record, dict):
        return [_finding("record_not_mapping", "", "stored record is not a mapping")]
    findings = []
    for key in sorted(set(record) - set(RECORD_KEYS), key=str):
        findings.append(_finding("extra_key", str(key), "record has a key that is not part of the schema"))
    for key in RECORD_KEYS:
        if key not in record:
            findings.append(_finding("missing_key", key, "record is missing a schema key"))
    if record.get("schema") != RECORD_SCHEMA:
        findings.append(_finding("schema_mismatch", "schema", "record schema string is not fix-certification/1"))
    try:
        stored_body = {k: v for k, v in record.items() if k != "record_digest"}
        if digest_obj(stored_body) != record.get("record_digest"):
            findings.append(_finding("record_digest_mismatch", "record_digest",
                                     "record_digest does not match the record body"))
    except CanonicalError as exc:
        findings.append(_finding("record_not_canonical", "", str(exc)))

    fresh, problems = _build(rule_row, evidence_rows, source_confidentiality=source_confidentiality,
                             change_class=change_class, confirmation_verified=confirmation_verified)
    findings += [_finding(code, "", detail) for code, detail in problems]
    if fresh is None:
        return findings
    for path in _diff_paths(record, fresh):
        top = path.split(".")[0]
        if top not in RECORD_KEYS or top not in record:
            continue  # extra and missing keys are reported above
        findings.append(_finding(_code_for(path), path, f"stored {path} differs from the recomputation"))
    return findings

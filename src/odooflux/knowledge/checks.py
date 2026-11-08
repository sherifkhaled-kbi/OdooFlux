"""Validation of the knowledge base (contracts/knowledge-cli.md codes). Pure: KnowledgeBase -> findings."""

import re
from collections import defaultdict

from odooflux.knowledge import validator
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, Finding, KnowledgeBase

SCHEMA_DIR_NAME = "schemas"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
MATURITY_CAPPED = ("UNVERIFIED", "CONFLICTING")
RESEARCH_STATUSES = ("NOT_ASSESSED", "RESEARCH_SEEDED", "RESEARCHED", "RULES_DRAFTED", "RULES_TESTED",
                     "RUNTIME_VALIDATED")


def _schema(kb: KnowledgeBase, name: str) -> dict:
    """Schemas ship with the package (knowledge/schemas), not with each knowledge tree."""
    import json
    return json.loads((KNOWLEDGE_ROOT / SCHEMA_DIR_NAME / f"{name}.schema.json").read_text(encoding="utf-8"))


def _schema_findings(file: str, data, schema: dict) -> list:
    return [Finding("E001", file, ptr, msg) for ptr, msg in validator.check(data, schema)]


def _revision_problem(kb: KnowledgeBase, revision: str):
    if HEX40.match(revision):
        if revision in kb.revision_shas:
            return None
        return "revision is a commit SHA not in the revision catalogue"
    if revision in kb.tags:
        return None
    return "revision must be a commit SHA or catalogued tag"


def _allowed(kb: KnowledgeBase, url: str) -> bool:
    return any(url.startswith(prefix) for prefix in kb.allow_list)


def check_evidence(kb: KnowledgeBase) -> list:
    out = []
    schema = _schema(kb, "evidence")
    ids_seen = defaultdict(list)
    for file, record in kb.evidence_entries:
        out += _schema_findings(file, record, schema)
        stem = file.rsplit("/", 1)[-1][:-5]
        if record.get("id") != stem:
            out.append(Finding("E001", file, "/id", f"file name must equal the id ({stem})"))
        ids_seen[record.get("id", stem)].append(file)
    for key, record in kb.evidence.items():
        file = kb.evidence_files[key]
        if record.get("url") and not _allowed(kb, record["url"]):
            out.append(Finding("E002", file, "/url", "url not in allow-list"))
        if record.get("revision"):
            problem = _revision_problem(kb, record["revision"])
            if problem:
                out.append(Finding("E003", file, "/revision", problem))
        for index, loc in enumerate(record.get("locations", [])):
            if isinstance(loc, dict) and loc.get("revision"):
                problem = _revision_problem(kb, loc["revision"])
                if problem:
                    out.append(Finding("E003", file, f"/locations/{index}/revision", problem))
            if isinstance(loc, dict) and loc.get("kind") == "absent":
                if loc.get("line") is not None or not loc.get("search_scope"):
                    out.append(Finding("E001", file, f"/locations/{index}",
                                       "an absent location needs line null and a search_scope"))
        src, tgt = record.get("source_applicability", {}), record.get("target_applicability", {})
        if src and tgt and src.get("from") and src.get("to") and _ver(src["from"]) > _ver(src["to"]):
            out.append(Finding("E001", file, "/source_applicability", "from must not exceed to"))
        if record.get("status") == "VERIFIED" and not record.get("runtime_test_ref"):
            out.append(Finding("E001", file, "/runtime_test_ref", "required when status is VERIFIED"))
    for ident, files in ids_seen.items():
        if len(files) > 1:
            out.append(Finding("E004", files[0], "/id", f"duplicate id {ident} in {', '.join(files)}"))
    # W002: identical claim and location set appears twice
    signature = defaultdict(list)
    for key, record in kb.evidence.items():
        locs = tuple(sorted((str(l.get("branch")), str(l.get("path")), str(l.get("line")))
                            for l in record.get("locations", []) if isinstance(l, dict)))
        signature[(record.get("description"), locs)].append(kb.evidence_files[key])
    for (_desc, _locs), files in signature.items():
        if len(files) > 1:
            out.append(Finding("W002", files[0], "", f"identical claim duplicated in {', '.join(files)}",
                               severity="WARNING"))
    return out


def _ver(text: str):
    return tuple(int(p) for p in text.split("."))


def check_registry(kb: KnowledgeBase) -> list:
    out = []
    schema = _schema(kb, "version")
    file = "compatibility/versions.json"
    majors = []
    for index, record in enumerate(kb.versions):
        out += _schema_findings(file, record, schema)
        if isinstance(record, dict) and "id" in record:
            majors.append((int(record["id"].split(".")[0]), index))
            for ref in record.get("evidence", []):
                if ref not in kb.evidence:
                    out.append(Finding("E006", file, f"/{index}/evidence", f"unknown evidence id {ref}"))
    if [m for m, _ in majors] != sorted({m for m, _ in majors}):
        out.append(Finding("E007", file, "", "versions must be unique and strictly increasing by major"))
    # SUPPORTED requires every inbound step RULES_TESTED and the version RUNTIME_VALIDATED (data-model.md).
    inbound = {t["target"]: [] for t in kb.transitions}
    for t in kb.transitions:
        inbound[t["target"]].append(t["research_status"])
    for index, record in enumerate(kb.versions):
        if isinstance(record, dict) and record.get("support_status") == "SUPPORTED":
            steps_ok = all(s == "RULES_TESTED" or s == "RUNTIME_VALIDATED" for s in inbound.get(record["id"], []))
            if not steps_ok or not inbound.get(record["id"]):
                out.append(Finding("E007", file, f"/{index}/support_status",
                                   f"{record['id']} is SUPPORTED but inbound steps are not RULES_TESTED"))
    for step, record in kb.research.items():
        for ref in [e for c in record.get("categories", {}).values() for e in c.get("evidence", [])]:
            if ref not in kb.evidence:
                out.append(Finding("E006", kb.research_files[step], "/categories", f"unknown evidence id {ref}"))
    # Transition status must equal the step research status (single source per step).
    for transition in kb.transitions:
        step = f"{transition['source'].split('.')[0]}-{transition['target'].split('.')[0]}"
        research = kb.research.get(step)
        if research and research.get("research_status") != transition.get("research_status"):
            out.append(Finding("E008", file, "/transitions",
                               f"{step} research_status disagrees with {kb.research_files[step]}"))
    return out


def check_gaps(kb: KnowledgeBase) -> list:
    out = []
    schema = _schema(kb, "gap")
    out += _schema_findings("gaps.json", kb.gaps, schema)
    for index, gap in enumerate(kb.gaps):
        for ref in gap.get("resolved_by", []) if isinstance(gap, dict) else []:
            if ref not in kb.evidence:
                out.append(Finding("E006", "gaps.json", f"/{index}/resolved_by", f"unknown evidence id {ref}"))
    return out


def rule_maturity(rule: dict, evidence: dict):
    """Effective maturity and whether it was capped (FR-004). Shared hygiene rules are exempt
    from evidence checks only when marked NOT_APPLICABLE with a reason."""
    maturity = rule.get("maturity", "DRAFT")
    statuses = [evidence[e]["status"] for e in rule.get("evidence", []) if e in evidence and "status" in evidence[e]]
    capped = (maturity == "FIX_ENABLED" and bool(statuses)
              and all(s in MATURITY_CAPPED for s in statuses))
    return ("DETECT_ONLY" if capped else maturity), capped


def check_rules(kb: KnowledgeBase) -> list:
    out = []
    schema = _schema(kb, "rule_metadata")
    out += _schema_findings("compatibility/*.rules.json", kb.rules, schema)
    out += _schema_findings("compatibility/rule_candidates.json", kb.rule_candidates,
                            _schema(kb, "rule_candidates"))
    for rule in kb.rules:
        if not isinstance(rule, dict):
            continue
        rid = rule.get("id", "?")
        refs = rule.get("evidence", [])
        if not refs and not (rule.get("step") == "*" and rule.get("not_applicable_reason")):
            out.append(Finding("E005", "compatibility/*.rules.json", rid, f"rule {rid}: missing evidence"))
        for ref in refs:
            if ref not in kb.evidence:
                out.append(Finding("E006", "compatibility/*.rules.json", rid, f"rule {rid}: unknown evidence {ref}"))
        effective, capped = rule_maturity(rule, kb.evidence)
        if capped:
            out.append(Finding("W001", "compatibility/*.rules.json", rid,
                               f"rule {rid}: maturity capped to {effective} (evidence not verified)",
                               severity="WARNING"))
    return out


def check_runtime_patterns(kb: KnowledgeBase) -> list:
    """Runtime log patterns (G-R-22): schema, compilable regexes, known evidence, ordered version ranges."""
    out = []
    file = "compatibility/runtime_log_patterns.json"
    if not kb.runtime_patterns:
        return out
    out += _schema_findings(file, kb.runtime_patterns, _schema(kb, "runtime_log_patterns"))
    seen = set()
    for index, pattern in enumerate(kb.runtime_patterns.get("patterns", [])):
        if not isinstance(pattern, dict):
            continue
        pid = pattern.get("id", "?")
        if pid in seen:
            out.append(Finding("E001", file, f"/patterns/{index}/id", f"duplicate pattern id {pid}"))
        seen.add(pid)
        for key in ("pattern", "context"):
            if key in pattern:
                try:
                    re.compile(pattern[key])
                except re.error as exc:
                    out.append(Finding("E001", file, f"/patterns/{index}/{key}", f"invalid regex: {exc}"))
        for ref in pattern.get("evidence", []):
            if ref not in kb.evidence:
                out.append(Finding("E006", file, f"/patterns/{index}/evidence", f"unknown evidence id {ref}"))
        rng = pattern.get("version_range", {})
        if isinstance(rng, dict) and rng.get("from") and rng.get("to") and _ver(rng["from"]) > _ver(rng["to"]):
            out.append(Finding("E001", file, f"/patterns/{index}/version_range", "from must not exceed to"))
    return out


def _replaced_by_findings(kb: KnowledgeBase, core_file: str, index: int, record: dict) -> list:
    """FR-020: each ``replaced_by`` entry names a module this version drops, successors it ships, known evidence."""
    out = []
    replaced = record.get("replaced_by")
    if not isinstance(replaced, dict):
        return out
    versions = kb.core_modules.get("versions", [])
    previous = versions[index - 1].get("modules", []) if index > 0 and isinstance(versions[index - 1], dict) else None
    modules = record.get("modules", [])
    for name, entry in replaced.items():
        pointer = f"/versions/{index}/replaced_by/{name}"
        if not isinstance(entry, dict):
            continue
        if name in modules or (previous is not None and name not in previous):
            out.append(Finding("E001", core_file, pointer, "replaced_by key must be a module removed in this version"))
        for successor in entry.get("successors", []):
            if successor not in modules:
                out.append(Finding("E001", core_file, pointer, f"successor {successor} is not in this version's list"))
        for ref in entry.get("evidence", []):
            if ref not in kb.evidence:
                out.append(Finding("E006", core_file, pointer, f"unknown evidence id {ref}"))
    return out


def check_compat_data(kb: KnowledgeBase) -> list:
    """Core module lists (L3) and RNG view schema map (L2): schema, catalogued revisions, known evidence."""
    out = []
    core_file = "compatibility/core_modules.json"
    if kb.core_modules:
        out += _schema_findings(core_file, kb.core_modules, _schema(kb, "core_modules"))
        for index, record in enumerate(kb.core_modules.get("versions", [])):
            if not isinstance(record, dict):
                continue
            if record.get("evidence") and record["evidence"] not in kb.evidence:
                out.append(Finding("E006", core_file, f"/versions/{index}/evidence",
                                   f"unknown evidence id {record['evidence']}"))
            if record.get("revision") and _revision_problem(kb, record["revision"]):
                out.append(Finding("E003", core_file, f"/versions/{index}/revision",
                                   _revision_problem(kb, record["revision"])))
            out += _replaced_by_findings(kb, core_file, index, record)
    rng_file = "compatibility/rng_schemas.json"
    if kb.rng_schemas:
        out += _schema_findings(rng_file, kb.rng_schemas, _schema(kb, "rng_schemas"))
        for index, record in enumerate(kb.rng_schemas.get("versions", [])):
            if not isinstance(record, dict):
                continue
            for ref in record.get("evidence", []):
                if ref not in kb.evidence:
                    out.append(Finding("E006", rng_file, f"/versions/{index}/evidence",
                                       f"unknown evidence id {ref}"))
            for view, name in (record.get("views") or {}).items():
                if not isinstance(name, str) or not name.endswith(".rng") or "/" in name:
                    out.append(Finding("E001", rng_file, f"/versions/{index}/views/{view}",
                                       "an RNG entry must be a bare *.rng file name"))
    return out


def check_runtime_runs(kb: KnowledgeBase) -> list:
    from odooflux.knowledge import runtime_runs
    return [Finding("E001", runtime_runs.FILE, ptr, msg) for ptr, msg in runtime_runs.file_problems(kb)]


def validate_knowledge(kb: KnowledgeBase) -> list:
    """All findings, sorted by file, pointer and code (deterministic output)."""
    findings = list(kb.load_findings)
    findings += check_evidence(kb) + check_registry(kb) + check_gaps(kb) + check_rules(kb)
    findings += check_runtime_patterns(kb)
    findings += check_compat_data(kb)
    findings += check_runtime_runs(kb)
    return sorted(findings, key=lambda f: (f.file, f.pointer, f.code, f.message))

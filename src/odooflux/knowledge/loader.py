"""Load the knowledge tree into a KnowledgeBase. Reads JSON only; never executes data (FR-019)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

KNOWLEDGE_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Finding:
    code: str
    file: str
    pointer: str
    message: str
    severity: str = "ERROR"  # ERROR for E codes, WARNING for W codes

    def line(self) -> str:
        return f"{self.file}:{self.pointer or '/'}: {self.code}: {self.message}"


@dataclass
class KnowledgeBase:
    root: Path
    allow_list: list = field(default_factory=list)          # URL prefixes
    revisions: list = field(default_factory=list)           # catalogue entries
    evidence: dict = field(default_factory=dict)            # id -> record
    evidence_files: dict = field(default_factory=dict)      # id -> relative file path
    evidence_entries: list = field(default_factory=list)    # (relative file, record): every file, duplicates included
    versions: list = field(default_factory=list)            # version records (compatibility/versions.json)
    transitions: list = field(default_factory=list)         # {source,target,research_status}
    research: dict = field(default_factory=dict)            # step -> step research record
    research_files: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)
    rules: list = field(default_factory=list)                # rule metadata entries
    rule_candidates: list = field(default_factory=list)      # seed rule catalogue (candidates)
    runtime_patterns: dict = field(default_factory=dict)     # install/upgrade log patterns (G-R-22)
    core_modules: dict = field(default_factory=dict)         # core addon names per target (L3 integrity)
    rng_schemas: dict = field(default_factory=dict)          # view type -> RNG file per version (L2 RNG)
    runtime_runs: dict = field(default_factory=dict)         # recorded runtime runs (008 T029-gen)
    load_findings: list = field(default_factory=list)

    @property
    def revision_shas(self) -> set:
        return {r["revision"] for r in self.revisions}

    @property
    def tags(self) -> set:
        return {t for r in self.revisions for t in r.get("tags", [])}


def _read(kb: KnowledgeBase, path: Path):
    rel = path.relative_to(kb.root).as_posix()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        kb.load_findings.append(Finding("E001", rel, "", f"cannot read JSON: {exc}"))
        return None


def is_builtin_path(path) -> bool:
    """True when `path` is the shipped knowledge tree or inside it. The one place that answers "is this the built-in
    tree?", so CLI verbs that must refuse to write into it need not reference KNOWLEDGE_ROOT themselves."""
    resolved = Path(path).resolve()
    root = KNOWLEDGE_ROOT.resolve()
    return resolved == root or root in resolved.parents


def load_knowledge(root=KNOWLEDGE_ROOT) -> KnowledgeBase:
    root = Path(root)
    kb = KnowledgeBase(root=root)
    data = _read(kb, root / "official_sources" / "allow_list.json") if (root / "official_sources/allow_list.json").exists() else None
    kb.allow_list = [e["prefix"] for e in (data or []) if isinstance(e, dict) and "prefix" in e]
    data = _read(kb, root / "official_sources" / "revisions.json") if (root / "official_sources/revisions.json").exists() else None
    kb.revisions = [e for e in (data or []) if isinstance(e, dict)]
    for path in sorted((root / "evidence").glob("*.json")) if (root / "evidence").is_dir() else []:
        record = _read(kb, path)
        if isinstance(record, dict):
            key = record.get("id") or path.stem
            rel = path.relative_to(root).as_posix()
            kb.evidence_entries.append((rel, record))
            kb.evidence.setdefault(key, record)
            kb.evidence_files.setdefault(key, rel)
    versions = root / "compatibility" / "versions.json"
    if versions.exists():
        data = _read(kb, versions) or {}
        kb.versions = list(data.get("versions", []))
        kb.transitions = list(data.get("transitions", []))
    for path in sorted((root / "compatibility").glob("*.research.json")) if (root / "compatibility").is_dir() else []:
        record = _read(kb, path)
        if isinstance(record, dict):
            kb.research[record.get("step", path.stem)] = record
            kb.research_files[record.get("step", path.stem)] = path.relative_to(root).as_posix()
    gaps = root / "gaps.json"
    kb.gaps = list((_read(kb, gaps) or []) if gaps.exists() else [])
    for path in sorted((root / "compatibility").glob("*.rules.json")) if (root / "compatibility").is_dir() else []:
        kb.rules.extend(_read(kb, path) or [])
    candidates = root / "compatibility" / "rule_candidates.json"
    kb.rule_candidates = list((_read(kb, candidates) or []) if candidates.exists() else [])
    patterns = root / "compatibility" / "runtime_log_patterns.json"
    kb.runtime_patterns = (_read(kb, patterns) or {}) if patterns.exists() else {}
    core = root / "compatibility" / "core_modules.json"
    kb.core_modules = (_read(kb, core) or {}) if core.exists() else {}
    rng = root / "compatibility" / "rng_schemas.json"
    kb.rng_schemas = (_read(kb, rng) or {}) if rng.exists() else {}
    runs = root / "compatibility" / "runtime_runs.json"
    data = _read(kb, runs) if runs.exists() else None
    kb.runtime_runs = data if isinstance(data, dict) else {}
    return kb


RELEASE_TREE = "knowledge"  # an installed release keeps its complete knowledge tree in <release>/knowledge/
KAP_FIX_CAPPED = "KAP_FIX_CAPPED"


def load_active_knowledge(handle) -> KnowledgeBase:
    """Load the knowledge tree of a resolved `KnowledgeHandle` (contracts/migration-integration.md "Loader").

    The built-in handle loads exactly what `load_knowledge(handle.root)` loads. Any other handle loads
    `<handle.root>/knowledge`; a missing tree raises `KnowledgeReleaseError` and never falls back to the built-in tree.
    FIX_ENABLED rules of a non-built-in release that fail promotion gates 1 to 5 are capped to DETECT_ONLY with a
    `KAP_FIX_CAPPED` warning (REQ-KAP-039). Built-in rules are grandfathered and never capped here. A non-built-in FIX_ENABLED
    row stays FIX_ENABLED only when `safety.fix_row_trusted` says so (gates 1 to 5, plus its certification record when
    certification governs the row). A record that exists but fails verification is named in the finding.
    """
    if handle.builtin:
        return load_knowledge(handle.root)
    from odooflux.knowledge.release.model import KnowledgeReleaseError  # lazy: release modules import this module
    from odooflux.knowledge.release.safety import fix_row_trusted, is_shipped_builtin_rule, load_provenance_index, \
        rule_gate_context

    tree = Path(handle.root) / RELEASE_TREE
    if not tree.is_dir():
        raise KnowledgeReleaseError(f"release {handle.release_id}: knowledge tree is missing ({tree})")
    kb = load_knowledge(tree)
    index = load_provenance_index(tree)
    snapshot_dir = tree.resolve().parent / "snapshots"
    context = rule_gate_context(kb)
    failing = {}
    for rule in kb.rules:
        if not isinstance(rule, dict) or rule.get("maturity") != "FIX_ENABLED" or is_shipped_builtin_rule(rule):
            continue
        evidence_rows = [kb.evidence[eid] for eid in rule.get("evidence") or []
                         if isinstance(eid, str) and eid in kb.evidence]
        trusted, found = fix_row_trusted(rule, tree, evidence_rows, index, kb=kb, snapshot_dir=snapshot_dir,
                                         context=context)
        if not trusted and found:
            failing[str(rule.get("id", "?"))] = found[-1]
    for rule in kb.rules:
        if isinstance(rule, dict) and rule.get("id") in failing and rule.get("maturity") == "FIX_ENABLED":
            finding = failing[rule["id"]]
            rule["maturity"] = "DETECT_ONLY"
            if finding["code"] == "cert-verify-failed":
                reason = f"certification record fails verification ({finding['detail']})"
            else:
                reason = f"gate {finding['gate']} {finding['code']}"
            kb.load_findings.append(Finding(
                KAP_FIX_CAPPED, "compatibility/*.rules.json", str(rule["id"]),
                f"FIX_ENABLED capped to DETECT_ONLY: {reason}", severity="WARNING"))
    return kb

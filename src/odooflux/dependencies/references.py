"""Reference index and ``*.refs.dangling-reference`` (REQ-DEP-003, REQ-VAL-003).

The index (XML IDs, models, fields among the scanned modules) and the reference walk are the L3 integrity
checker's (``validation.dependency.integrity``); this module reports its broken references under the one rule id
and lists references it cannot decide, which point into modules that are not scanned (core or Enterprise), as
"unverified (core)". Files are parsed only; nothing is executed.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.core.contracts.records import Finding
from odooflux.validation.dependency import integrity

RULE_ID = "*.refs.dangling-reference"
_KINDS = {"dangling_xml_id": "XML ID", "missing_group": "group XML ID", "dangling_model": "model",
          "dangling_field": "field"}


@dataclass
class ReferenceReport:
    findings: list = field(default_factory=list)
    unverified: list = field(default_factory=list)   # "unverified (core): <kind> (<count>)"


class _Collector(integrity._Checker):
    def finding(self, kind, path, line, matched, message, severity=None):
        if kind not in _KINDS:
            return
        self.findings.append(Finding(
            rule_id=RULE_ID, path=path, line=line, severity="CRITICAL",
            message=f"dangling {_KINDS[kind]} reference: {message}",
            suggestion="Define the target in a scanned module or correct the reference.", matched=matched))


def scan_references(module_paths) -> ReferenceReport:
    """Dangling references among the given module directories."""
    modules, notes = [], []
    for raw in module_paths:
        module, module_notes = integrity._load_module(Path(raw))
        notes += module_notes
        if module is not None:
            modules.append(module)
    checker = _Collector(modules, frozenset())
    checker.index()
    for module in modules:
        checker.check_python_refs(module)
        checker.check_xml(module)
        checker.check_csv(module)
    outside = Counter({k: n for k, n in checker.undecided.items() if "outside" in k or "not scanned" in k})
    return ReferenceReport(
        findings=sorted(checker.findings, key=lambda f: (f.path, f.line, f.matched)),
        unverified=[f"unverified (core): {kind} ({count})" for kind, count in sorted(outside.items())])

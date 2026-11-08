"""Pipeline glue for the dependency scanner (FR-020, REQ-DEP-001): one scan per run over every module.

The scanned set is all modules of the run, so a dependency on a sibling is not reported. The source and
target core lists and the per-module ``replaced_by`` data come from the shipped, evidence-pinned
``core_modules.json``; a missing target list yields an INFO gap instead of silence.
"""

from odooflux.dependencies.core_modules import check_unknown_dependencies, core_list, load_replaced_by


def scan_run_dependencies(module_paths, from_version: int, to_version: int) -> tuple:
    """(``{manifest path: [Finding]}``, ``[INFO gap text]``)."""
    target, source = f"{to_version}.0", f"{from_version}.0"
    target_core = core_list(target)
    if target_core is None:
        return {}, [f"INFO: dependency scan skipped: no core module list for {target} "
                    "(unknown dependencies are not decidable)"]
    findings = check_unknown_dependencies(module_paths, source_core=core_list(source), target_core=target_core,
                                          replaced_by=load_replaced_by(target))
    grouped: dict = {}
    for finding in findings:
        grouped.setdefault(finding.path, []).append(finding)
    return grouped, []

"""L4 install/upgrade and L5 behaviour pipeline over a RuntimeEnvironment (REQ-VAL-004, REQ-VAL-005, FR-004, FR-008).

Order for every layer: Enterprise dependency check (no container, SKIPPED), image mapping (UNAVAILABLE
``image_unavailable``), adapter availability (UNAVAILABLE ``docker_unavailable``), then prepare, the steps, and
teardown in a ``finally`` on every exit path. Reasons are exact codes where the contract names them; the detail is
carried in ``RuntimeOutcome.notes``.

Customer code is never imported here: manifests are read with ``ast`` and test output is read as text.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from odooflux.core.contracts.records import ValidationResult
from odooflux.discovery.manifest import MANIFEST_NAMES, read_manifest
from odooflux.validation.behavioral import compare
from odooflux.validation.dependency.integrity import load_enterprise_modules
from odooflux.validation.runtime import docker_env as de
from odooflux.validation.runtime.log_classifier import ClassifiedError


@dataclass
class RuntimeOutcome:
    result: ValidationResult
    errors: list = field(default_factory=list)       # ClassifiedError from every step
    runs: list = field(default_factory=list)         # RuntimeRun records
    sub_results: dict = field(default_factory=dict)  # 'install' / 'upgrade' -> ValidationResult (layer 4)
    notes: list = field(default_factory=list)        # details behind a reason code
    warnings: list = field(default_factory=list)     # teardown and tool warnings
    classifications: dict = field(default_factory=dict)  # L5: test ids per classification (when a baseline ran)


def _split(reason: str):
    code, _, detail = reason.partition(": ")
    return code, detail


def _manifest_depends(module_dir: Path) -> tuple:
    manifest_file = next((module_dir / n for n in MANIFEST_NAMES if (module_dir / n).is_file()), None)
    if manifest_file is None:
        return ()
    manifest, error = read_manifest(manifest_file)
    if error or not manifest:
        return ()
    return tuple(d for d in (manifest.get("depends") or []) if isinstance(d, str))


def enterprise_dependencies(module_dirs: Sequence) -> list:
    """(module, Enterprise dependency) pairs. Read from manifests with ast; nothing is executed."""
    enterprise = load_enterprise_modules()
    found = []
    for raw in module_dirs:
        path = Path(raw)
        for dep in _manifest_depends(path):
            if dep in enterprise:
                found.append((path.name, dep))
    return found


def _names(module_dirs: Sequence) -> list:
    return [Path(d).name for d in module_dirs]


def _preflight(module_dirs: Sequence, version: str, env, layer: int) -> Optional[RuntimeOutcome]:
    dependencies = enterprise_dependencies(module_dirs)
    if dependencies:
        notes = [f"module {m!r} depends on Enterprise module {dep!r} (D-05: not accessible)"
                 for m, dep in dependencies]
        return RuntimeOutcome(result=ValidationResult(layer=layer, outcome="SKIPPED", reason="enterprise_dependency"),
                              notes=notes)
    if de.image_for_version(version) is None:
        return RuntimeOutcome(result=ValidationResult(layer=layer, outcome="UNAVAILABLE", reason="image_unavailable"),
                              notes=[f"no runtime image is mapped for {version} (EV-359)"])
    available, reason = env.available()
    if not available:
        code, detail = _split(reason)
        return RuntimeOutcome(result=ValidationResult(layer=layer, outcome="UNAVAILABLE", reason=code),
                              notes=[detail] if detail else [])
    return None


def _primary(errors: list) -> Optional[ClassifiedError]:
    named = [e for e in errors if e.error_class != "unknown"]
    if named:
        return named[0]
    return errors[0] if errors else None


def _step_failure(step: str, errors: list, exit_code: int) -> str:
    primary = _primary(errors)
    text = f"{step} failed: {primary.error_class}"
    if primary.file:
        text += f" in {primary.file}"
    if primary.xml_id:
        text += f" ({primary.xml_id})"
    if primary.error_class == "unknown" and primary.message:
        text += f": {primary.message}"
    return f"{text}; exit {exit_code}"


def _adapter_failure(outcome: RuntimeOutcome, exc: de.EnvironmentUnavailable, layer: int) -> RuntimeOutcome:
    outcome.result = ValidationResult(layer=layer, outcome="UNAVAILABLE", reason=exc.code)
    if exc.detail:
        outcome.notes.append(exc.detail)
    return outcome


def run_install(module_dirs: Sequence, target_version: str, env, limits: de.Limits, state_dir,
                *, upgrade: bool = False) -> RuntimeOutcome:
    """L4: install every module in one database (Odoo resolves dependency order); with ``upgrade``, then run
    ``-u`` on the same database. The layer is PASS only when every requested step is clean."""
    outcome = _preflight(module_dirs, target_version, env, layer=4)
    if outcome is not None:
        return outcome
    outcome = RuntimeOutcome(result=ValidationResult(layer=4, outcome="PASS"))
    try:
        handle = env.prepare(target_version, [Path(d) for d in module_dirs], limits, state_dir=state_dir)
    except de.EnvironmentUnavailable as exc:
        return _adapter_failure(outcome, exc, layer=4)
    names = _names(module_dirs)
    try:
        install = env.install(handle, names)
        outcome.runs.append(install)
        outcome.errors.extend(install.errors)
        install_result = _step_result(install, "install")
        outcome.sub_results["install"] = install_result
        final = install_result
        if install_result.outcome == "PASS" and upgrade:
            upgrade_run = env.upgrade(handle, names)
            outcome.runs.append(upgrade_run)
            outcome.errors.extend(upgrade_run.errors)
            outcome.sub_results["upgrade"] = _step_result(upgrade_run, "upgrade")
            final = outcome.sub_results["upgrade"]
        outcome.result = ValidationResult(layer=4, outcome=final.outcome, reason=final.reason)
    finally:
        outcome.warnings.extend(env.teardown(handle))
    return outcome


def _step_result(run: de.RuntimeRun, step: str) -> ValidationResult:
    if run.errors:
        return ValidationResult(layer=4, outcome="FAIL", reason=_step_failure(step, run.errors, run.exit_code))
    return ValidationResult(layer=4, outcome="PASS")


def run_behavior(module_dirs: Sequence, module: str, target_version: str, env, limits: de.Limits, state_dir,
                 *, source_version: Optional[str] = None, source_env=None, source_module_dirs=None,
                 tags: Optional[str] = None) -> RuntimeOutcome:
    """L5: run ``module``'s tests on the target (after install) and, when ``source_version`` is given, on the
    source as the baseline. The judgement is ``compare.judge``. A source that cannot run gives coverage partial."""
    tags = tags or f"/{module}"
    outcome = _preflight(module_dirs, target_version, env, layer=5)
    if outcome is not None:
        return outcome
    outcome = RuntimeOutcome(result=ValidationResult(layer=5, outcome="SKIPPED", reason="no_tests"))
    target, target_failure = _tests_on(env, target_version, module_dirs, module, tags, limits, state_dir, outcome)
    if target is None:
        code, detail = target_failure
        if code in ("image_unavailable", "docker_unavailable", "database_not_ready"):
            outcome.result = ValidationResult(layer=5, outcome="UNAVAILABLE", reason=code)
        elif code in ("timeout", "oom"):
            outcome.result = ValidationResult(layer=5, outcome="FAIL", reason=code, coverage="partial")
        else:
            outcome.result = ValidationResult(layer=5, outcome="SKIPPED", reason="install_failed")
        if detail:
            outcome.notes.append(detail)
        return outcome
    source, source_reason = None, "not requested"
    if source_version:
        source_outcome = _preflight(source_module_dirs or module_dirs, source_version, source_env or env, layer=5)
        if source_outcome is not None:
            source_reason = source_outcome.result.reason
            outcome.notes.append(f"source baseline unavailable: {source_reason}")
            outcome.notes.extend(source_outcome.notes)
        else:
            source, failure = _tests_on(source_env or env, source_version, source_module_dirs or module_dirs,
                                        module, tags, limits, state_dir, outcome)
            if source is None:
                source_reason = failure[0]
                outcome.notes.append(f"source run: {failure[1]}" if failure[1] else "source run failed")
    outcome.result = compare.judge(target, source, source_reason=source_reason)
    if source is not None:
        outcome.classifications = compare.classification_counts(compare.compare(source.outcomes, target.outcomes))
    return outcome


def _tests_on(env, version: str, module_dirs: Sequence, module: str, tags: str, limits: de.Limits, state_dir,
              outcome: RuntimeOutcome):
    """(ParsedTests, None) on success, or (None, (code, detail)) when the tests could not be run."""
    try:
        handle = env.prepare(version, [Path(d) for d in module_dirs], limits, state_dir=state_dir)
    except de.EnvironmentUnavailable as exc:
        return None, (exc.code, exc.detail)
    try:
        install = env.install(handle, _names(module_dirs))
        outcome.runs.append(install)
        outcome.errors.extend(install.errors)
        if install.errors:
            return None, ("install_failed", _step_failure("install", install.errors, install.exit_code))
        run = env.run_tests(handle, _names(module_dirs), tags)
        outcome.runs.append(run)
        if run.killed_reason:
            outcome.errors.extend(run.errors)
            return None, (run.killed_reason, f"tests were stopped: {run.killed_reason}")
        universe = compare.scan_static_universe(_module_dir(module_dirs, module), module)
        text = Path(run.log_path).read_text(encoding="utf-8", errors="replace") if run.log_path else ""
        return compare.parse_test_output(text, module, universe), None
    finally:
        outcome.warnings.extend(env.teardown(handle))


def _module_dir(module_dirs: Sequence, module: str):
    return next((Path(d) for d in module_dirs if Path(d).name == module), Path(""))

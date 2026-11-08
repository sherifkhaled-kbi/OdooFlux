"""Shared helpers for the feature 010 hardening tests: a small generated corpus and in-process runs."""

import json
import tempfile
from pathlib import Path

from tests.unit import _setup  # noqa: F401  (src/ first on sys.path)

from tests.benchmarks import corpus_gen
from odooflux.builtins import build_context
from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.orchestrator.plan import build_plan
from odooflux.core.orchestrator.run import (
    RunOptions, new_state, reports_from_state, run_pipeline)
from odooflux.discovery.modules import module_ref
from odooflux.reporting.model.model import build_report

_CORPUS_CACHE: dict = {}


def small_corpus(modules: int = 8, seed: int = 1) -> Path:
    """A generated corpus shared by the tests of one process. Tests must not modify it; use ``copy_corpus``."""
    key = (modules, seed)
    if key not in _CORPUS_CACHE:
        root = Path(tempfile.mkdtemp(prefix="odooflux-corpus-"))
        corpus_gen.generate(root, modules=modules, seed=seed)
        _CORPUS_CACHE[key] = root
    return _CORPUS_CACHE[key]


def copy_corpus(modules: int = 4, seed: int = 1) -> Path:
    root = Path(tempfile.mkdtemp(prefix="odooflux-corpus-"))
    corpus_gen.generate(root, modules=modules, seed=seed)
    return root


def module_paths(corpus: Path) -> list:
    return sorted(p for p in Path(corpus).iterdir() if p.is_dir())


def run_analysis(corpus, state_dir, *, mode="analyze", jobs=1, incremental=None, from_v=14, to_v=19, hook=None,
                 on_module=None, modules=None):
    """Run the pipeline in-process. Returns ``(run, state)``."""
    ctx = build_context()
    paths = module_paths(corpus) if modules is None else [Path(m) for m in modules]
    refs = [module_ref(p, i) for i, p in enumerate(paths)]
    plan = build_plan(ctx.graph(), f"{from_v}.0", f"{to_v}.0", refs)
    options = RunOptions(from_version=from_v, to_version=to_v, mode=mode, backup=True,
                         module_paths=[str(p) for p in paths])
    run = RunDir.create(Path(state_dir), reversible=True, with_backup=(mode == "fix"))
    state = new_state(run, plan, options, plan.modules)
    run.write_state(state)
    extra = {}
    if jobs != 1:
        extra["jobs"] = jobs
    if incremental is not None:
        extra["incremental"] = incremental
    run_pipeline(run, state, ctx.registries, layer3=ctx.layer3, hook=hook, on_module=on_module, **extra)
    return run, state


def normalised_json(state, roots=()) -> str:
    """The v1 report of *state* with run identity removed, as canonical JSON text."""
    report = build_report(state, reports_from_state(state), run_log_path="")
    text = json.dumps(report, sort_keys=True)
    for root in roots:
        text = text.replace(str(root), "<ROOT>")
    data = json.loads(text)
    for section in ("run", "recovery"):
        for key in ("run_id", "rollback_cmd", "run_log"):
            data.get(section, {}).pop(key, None)
    return json.dumps(data, sort_keys=True)

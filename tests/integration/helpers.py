"""Shared helpers: start a run through the core API (so a test can interrupt it), and normalise reports."""

import json
import shutil
import tempfile
from pathlib import Path

from odooflux.builtins import build_context
from odooflux.core.contracts.records import ModuleRef  # noqa: F401
from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.orchestrator.plan import build_plan
from odooflux.core.orchestrator.run import RunOptions, new_state, run_pipeline
from odooflux.discovery.modules import module_ref
from odooflux.reporting.model.model import build_report
from odooflux.core.orchestrator.run import reports_from_state
from odooflux.utils.hashing import digest_tree

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parents[1] / "golden_fixtures" / "p0_kbi_demo_v14"


def make_module(root: Path, name: str, source=FIXTURE) -> Path:
    target = root / name
    shutil.copytree(source, target)
    return target


def start_run(state_dir: Path, modules, *, mode="fix", backup=True, hook=None, from_v=14, to_v=19, provisional=None):
    """Run the pipeline in-process. *hook(name)* runs after each module's checkpoint (may raise)."""
    ctx = build_context()
    refs = [module_ref(Path(m), i) for i, m in enumerate(modules)]
    plan = build_plan(ctx.graph(), f"{from_v}.0", f"{to_v}.0", refs)
    options = RunOptions(from_version=from_v, to_version=to_v, mode=mode, backup=backup,
                         module_paths=[str(m) for m in modules])
    run = RunDir.create(state_dir, reversible=backup, with_backup=(mode == "fix"))
    state = new_state(run, plan, options, plan.modules)
    if provisional:
        state["provisional"] = provisional
    run.write_state(state)
    run_pipeline(run, state, ctx.registries, hook=hook, layer3=ctx.layer3)
    return run.run_id, state


def normalised_report(state_dir: Path, run_id: str, roots) -> dict:
    """The v1 report with run identity and absolute roots removed, so two runs compare equal."""
    run = RunDir.open(state_dir, run_id)
    state = run.read_state()
    report = build_report(state, reports_from_state(state), run_log_path="")
    text = json.dumps(report, sort_keys=True)
    for root in roots:
        text = text.replace(str(root), "<ROOT>")
    data = json.loads(text)
    for key in ("run_id", "rollback_cmd", "run_log"):
        data["run"].pop(key, None)
        data["recovery"].pop(key, None)
    data["run"].pop("run_id", None)
    return data


def tree(path: Path):
    return digest_tree(Path(path))


def new_tmp() -> Path:
    return Path(tempfile.mkdtemp())


def run_cli_main(args):
    """Run the CLI in-process and return (exit_code, stdout)."""
    import contextlib
    import io

    from odooflux.builtins import main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main([str(a) for a in args])
    return code, buf.getvalue()

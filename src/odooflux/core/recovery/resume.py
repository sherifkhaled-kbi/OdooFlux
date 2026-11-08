"""Resume an interrupted run (FR-014, REQ-SAF-009)."""

from pathlib import Path

from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.orchestrator.run import run_pipeline


def resume(state_dir, run_id: str, registries, *, api_key=None, validate_text=None, hook=None, on_module=None,
           layer3=None) -> dict:
    run = RunDir.open(Path(state_dir), run_id)
    state = run.read_state()
    if state["status"] == "ROLLED_BACK":
        raise RuntimeError("run was rolled back; start a new run")
    return run_pipeline(run, state, registries, api_key=api_key, validate_text=validate_text, hook=hook,
                        on_module=on_module, layer3=layer3)

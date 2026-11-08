"""Isolated workspace copy of a module (R-05). Symlinks are copied as links, never followed."""

import shutil
from pathlib import Path


def make_workspace(run, module_name: str, module_path) -> Path:
    target = run.work_dir / module_name
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path(module_path), target, symlinks=True)
    audit = getattr(run, "audit", None)
    if audit is not None:
        audit.append("workspace_created", module_name)
    return target

"""Synthetic release-gate repositories for the T003/T004 tests."""

import tempfile
from pathlib import Path

RTM_HEAD = "# RTM\n\n## Matrix\n\n| REQ | OBJ | Phase | Spec FRs | Tasks | Tests | Verify | Gap |\n|---|---|---|---|---|---|---|---|\n"
BACKLOG = ("# Backlog\n\n| ID | Origin | Item | Needs | Priority |\n|---|---|---|---|---|\n"
           "| KB-X-1 | t | item | n | P-high |\n| KB-X-2 | t | item | n | P-med |\n")


def make_repo(reqs, tasks, tests=None, gate="", records="", backlog=BACKLOG):
    """*reqs*: ids. *tasks*: lines for ``specs/001-x/tasks.md``. *tests*: {relative file: text}."""
    root = Path(tempfile.mkdtemp())
    (root / "docs/planning").mkdir(parents=True)
    rows = "".join(f"| {r} | OBJ-001 | P0 | 001:FR-001 | 001:T001 | TST-001-001 | UT | OK |\n" for r in reqs)
    text = RTM_HEAD + rows
    if gate:
        text += "\n## Release gate data\n\n| REQ | Gate status | KB backlog IDs | Basis |\n|---|---|---|---|\n" + gate
    if records:
        text += "\n## Verification records\n\n| REQ | Record | Anchor |\n|---|---|---|\n" + records
    (root / "docs/planning/REQUIREMENTS_TRACEABILITY_MATRIX.md").write_text(text, encoding="utf-8")
    (root / "docs/planning/KNOWLEDGE_BASE_BACKLOG.md").write_text(backlog, encoding="utf-8")
    (root / "specs/001-x").mkdir(parents=True)
    (root / "specs/001-x/tasks.md").write_text("\n".join(tasks) + "\n", encoding="utf-8")
    for rel, body in (tests or {}).items():
        target = root / "tests" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root

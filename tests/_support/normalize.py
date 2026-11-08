"""Normalise a legacy-format report so two runs from different temp dirs compare equal (REQ-TST-004)."""

import copy


def _relative(file, root) -> str:
    text = str(file)
    prefix = str(root).rstrip("/") + "/"
    return text[len(prefix):] if text.startswith(prefix) else text


def normalize_report(report: dict, module_path) -> dict:
    """Copy of *report*: ``module_path`` -> ``<MODULE>``, issue files relative, timestamp -> ``<TS>``,
    ``summary.elapsed_seconds`` -> 0, issues sorted by (file, line, category, message)."""
    out = copy.deepcopy(report)
    if "module_path" in out:
        out["module_path"] = "<MODULE>"
    if "timestamp" in out:
        out["timestamp"] = "<TS>"
    if isinstance(out.get("summary"), dict) and "elapsed_seconds" in out["summary"]:
        out["summary"]["elapsed_seconds"] = 0
    issues = out.get("issues", [])
    for issue in issues:
        if "file" in issue:
            issue["file"] = _relative(issue["file"], module_path)
    issues.sort(key=lambda i: (i.get("file", ""), i.get("line", 0), i.get("category", ""), i.get("message", "")))
    return out

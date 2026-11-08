"""Unified-diff export of the kept edits plus a hunk index (FR-005, REQ-REP-004, contracts/sarif-and-diff.md).

Headers are ``a/<module>/<relpath>`` and ``b/<module>/<relpath>`` so the patch applies with ``patch -p1`` from the
parent of the modules. Original bytes come from a caller-supplied reader (a pre-run backup, or the untouched module in a
run that did not write); nothing is guessed. A rename (``__openerp__.py`` to ``__manifest__.py``) is a delete plus a
create, which plain ``patch`` applies without git extensions. Lines are split on ``\\n`` only, so CRLF content and a
missing final newline survive byte for byte (``\\ No newline at end of file``).

Only kept edits are exported. A module with rejected edits or a blocked module is excluded as a whole (promotion is all or
nothing per module) and listed in the index with its reasons."""

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
NO_NEWLINE = "\n\\ No newline at end of file\n"


class OriginalUnavailableError(RuntimeError):
    """The original bytes of an edited file cannot be read, so no faithful diff can be produced."""


@dataclass
class DiffExport:
    patch: str
    index: dict

    def index_json(self) -> str:
        return json.dumps(self.index, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def backup_reader(backup_dir):
    """Reader for a write-mode run: originals live in ``<backup_dir>/<module>/<relative path>``."""
    backup_dir = Path(backup_dir)

    def read(module: dict, path: str) -> bytes:
        rel = Path(path).relative_to(module["path"])
        try:
            return (backup_dir / module["name"] / rel).read_bytes()
        except OSError as exc:
            raise OriginalUnavailableError(f"no backup copy of {rel} for module {module['name']}: {exc}") from exc
    return read


def module_reader():
    """Reader for a run that did not write: the module on disk is still the original."""
    def read(module: dict, path: str) -> bytes:
        try:
            return Path(path).read_bytes()
        except OSError as exc:
            raise OriginalUnavailableError(f"cannot read {path}: {exc}") from exc
    return read


def _lines(text: str) -> list:
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _apply(text: str, spans: list) -> str:
    for s in sorted(spans, key=lambda s: s["start"], reverse=True):
        if text[s["start"]:s["end"]] != s["before"]:
            raise OriginalUnavailableError("the original file differs from the text the edit was computed on")
        text = text[:s["start"]] + s["after"] + text[s["end"]:]
    return text


def _unified(old_name, new_name, old_text, new_text) -> list:
    """Return (body lines with marker lines, hunk headers). Headers use /dev/null for a missing side."""
    old_label = "/dev/null" if old_name is None else f"a/{old_name}"
    new_label = "/dev/null" if new_name is None else f"b/{new_name}"
    produced = list(difflib.unified_diff(_lines(old_text), _lines(new_text), old_label, new_label, n=3, lineterm="\n"))
    out = []
    for i, line in enumerate(produced):
        out.append(line)
        if i >= 2 and line[:1] in (" ", "-", "+") and not line.endswith("\n"):
            out.append(NO_NEWLINE)
    return out


def _hunks(lines: list) -> list:
    """Split diff output into [(header, old_start, old_len)] with the hunk's own lines."""
    hunks = []
    for line in lines:
        m = _HUNK.match(line)
        if m:
            hunks.append({"header": line.rstrip("\n"), "old_start": int(m.group(1)),
                          "old_lines": 1 if m.group(2) is None else int(m.group(2)),
                          "new_start": int(m.group(3)),
                          "new_lines": 1 if m.group(4) is None else int(m.group(4))})
    return hunks


def export_diff(report: dict, read_original) -> DiffExport:
    patch_parts: list = []
    files: list = []
    excluded: list = []
    counter = 0
    for module in report["modules"]:
        edits = module.get("edits") or []
        if not edits:
            continue
        if module.get("rejections") or module.get("blocked"):
            reasons = [r if isinstance(r, str) else str(r) for r in module.get("rejections", [])]
            if module.get("blocked"):
                reasons.insert(0, module.get("block_reason") or "blocked")
            excluded.append({"module": module["name"], "reasons": reasons})
            continue
        root = Path(module["path"])
        for edit in sorted(edits, key=lambda e: e["path"]):
            spans = sorted(edit["spans"], key=lambda s: s["start"])
            try:
                raw = read_original(module, edit["path"])
            except OSError as exc:
                raise OriginalUnavailableError(f"cannot read the original of {edit['path']}: {exc}") from exc
            old_text = raw.decode("utf-8")
            new_text = _apply(old_text, spans)
            rel_old = Path(edit["path"]).relative_to(root).as_posix()
            rel_new = Path(edit["dest"]).relative_to(root).as_posix()
            ids = []
            for s in spans:
                counter += 1
                ids.append((f"e-{counter:04d}", old_text.count("\n", 0, s["start"]) + 1,
                            old_text.count("\n", 0, s["end"]) + 1))
            if old_text == new_text and rel_old == rel_new:
                continue
            name_old, name_new = f"{module['name']}/{rel_old}", f"{module['name']}/{rel_new}"
            if rel_old == rel_new:
                pieces = [(name_old, name_new, old_text, new_text, rel_old, None)]
            else:  # rename: delete the old path, create the new one
                pieces = [(name_old, None, old_text, "", rel_old, name_new),
                          (None, name_new, "", new_text, rel_old, name_old)]
            for old_name, new_name, a, b, finding_path, counterpart in pieces:
                lines = _unified(old_name, new_name, a, b)
                if not lines:
                    continue
                patch_parts.append("".join(lines))
                hunks = []
                for h in _hunks(lines):
                    lo, hi = h["old_start"], h["old_start"] + max(h["old_lines"], 1) - 1
                    hunks.append(dict(h, edit_ids=[i for i, first, last in ids if first <= hi and last >= lo],
                                      rule_ids=sorted({f["rule_id"] for f in module["findings"]
                                                       if f["path"] == finding_path and f["status"] != "REJECTED"
                                                       and lo <= f["line"] <= hi})))
                entry = {"module": module["name"], "path": new_name or old_name, "hunks": hunks}
                if new_name is None:
                    entry["change"] = "delete"
                    entry["renamed_to"] = counterpart
                elif old_name is None:
                    entry["change"] = "create"
                    entry["renamed_from"] = counterpart
                else:
                    entry["change"] = "modify"
                files.append(entry)
    return DiffExport("".join(patch_parts), {"files": files, "excluded_modules": excluded})


class _DiffBase:
    contract_version = 1

    def _export(self, report: dict, read_original=None, backup_dir=None) -> DiffExport:
        """*backup_dir* (write-mode run) or *read_original* supplies the original bytes; with neither, the module on disk
        is read (a run that did not write)."""
        if read_original is None:
            read_original = backup_reader(backup_dir) if backup_dir is not None else module_reader()
        return export_diff(report, read_original)


class DiffRenderer(_DiffBase):
    """Registry key ``diff``: the unified patch text."""

    key = "diff"

    def render(self, report: dict, read_original=None, backup_dir=None, **options) -> str:
        return self._export(report, read_original, backup_dir).patch


class DiffIndexRenderer(_DiffBase):
    """Registry key ``diff-index``: the hunk index (JSON) that accompanies the patch."""

    key = "diff-index"

    def render(self, report: dict, read_original=None, backup_dir=None, **options) -> str:
        return self._export(report, read_original, backup_dir).index_json()

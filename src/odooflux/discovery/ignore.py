"""``.gitignore`` matching with negation, anchors, and directory-only patterns (fixes F-WALK-1)."""

import fnmatch


class IgnoreRules:
    def __init__(self, lines=()):
        self._rules = []  # (negated, anchored, dir_only, pattern)
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = "/" in line
            line = line.lstrip("/")
            if line:
                self._rules.append((negated, anchored, dir_only, line))

    def _decides(self, rel: str, is_dir: bool):
        """Last matching rule wins; None when no rule matches *rel*."""
        decision = None
        parts = rel.split("/")
        for negated, anchored, dir_only, pattern in self._rules:
            for depth in range(1, len(parts) + 1):
                candidate = "/".join(parts[:depth])
                is_candidate_dir = depth < len(parts) or is_dir
                if dir_only and not is_candidate_dir:
                    continue
                target = candidate if anchored else parts[depth - 1]
                if fnmatch.fnmatchcase(target, pattern):
                    decision = not negated
                    break
        return decision

    def ignored(self, rel_posix: str, is_dir: bool = False) -> bool:
        return bool(self._decides(rel_posix, is_dir))

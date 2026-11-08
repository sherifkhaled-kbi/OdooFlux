"""Incremental index (T013; REQ-PRF-002, FR-004).

A module whose key is unchanged is not analysed again: its stored result entry is replayed. The key covers

* the content of every file of the module (SHA-256 per file, not mtime),
* the rule-set digest (selected knowledge rules with maturity, parameters and evidence, plus the registered engine
  rules, validators and parsers),
* the tool digest (``odooflux.__version__`` plus the content of the package's own sources and data),
* the run options that change analysis (versions, mode, skip-independent flags) and the run-level inputs that reach
  the module (dependency findings and input gaps).

Only read-only modes (analyze, dry run) use the index; a fix run never reads or writes it. A corrupt or foreign index
file is ignored. The index lives under the state directory (never inside a scanned path)."""

import hashlib
import json
import os
from pathlib import Path

import odooflux
from odooflux.utils.atomic import atomic_write_bytes

SCHEMA = "odooflux.incremental/1"
_PACKAGE = Path(odooflux.__file__).resolve().parent
_TOOL_MEMO: dict = {}


def index_path(state_dir) -> Path:
    return Path(state_dir) / "incremental" / "index.json"


def tool_digest(version: str = None) -> str:
    """Digest of the tool version and of the package sources and data it ships."""
    version = odooflux.__version__ if version is None else version
    if version not in _TOOL_MEMO:
        outer = hashlib.sha256(f"version:{version}\n".encode("utf-8"))
        for path in sorted(_PACKAGE.rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json") and "__pycache__" not in path.parts:
                outer.update(f"{path.relative_to(_PACKAGE).as_posix()}\0".encode("utf-8"))
                outer.update(hashlib.sha256(path.read_bytes()).digest())
        _TOOL_MEMO[version] = outer.hexdigest()
    return _TOOL_MEMO[version]


def _rule_facts(rule) -> list:
    params = getattr(rule, "params", None)
    if params is None:
        bound = getattr(rule, "_bound", None)
        params = {"detect": getattr(bound, "detector_params", {}), "fix": getattr(bound, "fixer_params", {})}
    return [getattr(rule, "key", ""), getattr(rule, "step", ""), getattr(rule, "maturity", ""),
            bool(getattr(rule, "review_required", False)), bool(getattr(rule, "fixes", False)),
            list(getattr(rule, "evidence", ()) or ()), params]


def ruleset_digest(knowledge, run_rules, registries) -> str:
    """Digest of the rules that will run: knowledge rules, opted-in run-input rules, registered engine entries."""
    facts = {
        "knowledge": sorted((_rule_facts(r) for r in knowledge), key=lambda f: f[0]),
        "run_rules": sorted((_rule_facts(r) for r in run_rules), key=lambda f: f[0]),
        "registered": {kind: sorted(getattr(e, "key", "") for e in getattr(registries, kind).all())
                       for kind in ("rules", "validators", "parsers")} if registries is not None else {},
    }
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def tree_digest(root) -> str:
    """SHA-256 over sorted ``relative path, content hash`` of every regular file under *root* (os.walk: this runs for
    every module of every incremental run)."""
    root = str(root)
    items = []
    for base, dirs, names in os.walk(root):
        dirs.sort()
        for name in names:
            path = os.path.join(base, name)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    items.append((os.path.relpath(path, root).replace(os.sep, "/"), hashlib.sha256(fh.read()).digest()))
    items.sort()
    outer = hashlib.sha256()
    for rel, digest in items:
        outer.update(rel.encode("utf-8", "surrogateescape") + b"\0" + digest)
    return outer.hexdigest()


def _context_projection(entry: dict, run_ctx) -> list:
    path = Path(entry["path"])
    if run_ctx is None:
        return []
    deps = [[f.path, f.line, f.severity, f.rule_id, f.message, f.suggestion, list(f.evidence)]
            for manifest, items in sorted(run_ctx.dependency_findings.items()) if Path(manifest).parent == path
            for f in items]
    return [deps, list(run_ctx.gaps)]


class IncrementalIndex:
    def __init__(self, path: Path, *, tool_version: str = None, ruleset_override: str = None):
        self.path = Path(path)
        self.tool_version = tool_version
        self.ruleset_override = ruleset_override
        self.stats = {"analyzed": 0, "skipped": 0}
        self.parsed = 0  # file parses done by the analysed modules (workers included)
        self._entries: dict = {}
        self._ruleset: str = ""
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict) and data.get("schema") == SCHEMA and isinstance(data.get("entries"), dict):
            self._entries = data["entries"]

    def prepare(self, run_ctx, registries) -> None:
        """Compute the run-wide digests once."""
        self._ruleset = self.ruleset_override or ruleset_digest(
            getattr(run_ctx, "knowledge", ()), getattr(run_ctx, "rules", ()), registries)
        self._tool = tool_digest(self.tool_version)

    def key(self, entry: dict, options, run_ctx) -> str:
        facts = {
            "module": entry["path"],
            "files": tree_digest(entry["path"]),
            "ruleset": self._ruleset, "tool": self._tool,
            "options": [options.from_version, options.to_version, options.mode, options.allow_unverified,
                        sorted(options.enable_rules)],
            "context": _context_projection(entry, run_ctx),
        }
        return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def lookup(self, entry: dict, key: str):
        stored = self._entries.get(entry["path"])
        if stored and stored.get("key") == key:
            self.stats["skipped"] += 1
            return stored["payload"]
        return None

    def store(self, entry: dict, key: str, payload: dict) -> None:
        self.stats["analyzed"] += 1
        self._entries[entry["path"]] = {"key": key, "payload": payload}

    def save(self) -> None:
        """Write the index when this run changed it."""
        if not self.stats["analyzed"] and self.path.is_file():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({"schema": SCHEMA, "entries": self._entries}, sort_keys=True, separators=(",", ":"))
        atomic_write_bytes(self.path, data.encode("utf-8"))


def open_index(state_dir, *, tool_version: str = None, ruleset_digest: str = None) -> IncrementalIndex:
    """The index under *state_dir*. ``tool_version`` and ``ruleset_digest`` override the computed digests (tests)."""
    return IncrementalIndex(index_path(state_dir), tool_version=tool_version, ruleset_override=ruleset_digest)

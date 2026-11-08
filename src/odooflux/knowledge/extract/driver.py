"""Extract driver: one snapshot pair in, change drafts and a finalized file accounting out (T047; REQ-KAP-011,
REQ-KAP-013, REQ-KAP-004; diff-extractor contract, Pipeline per pair).

Pipeline: changed files from blob sha256 (`accounting.changed_paths`); scope and size exclusions with a reason; an
extractor per file from the registry (none: UNSUPPORTED NO_PARSER, or NO_JS_ADAPTER for `.js`); facts for each side
through the domain extractors; `classify.classify_pair`; `rename.refine_candidates`; `FileAccounting.finalize`.

A file whose extraction fails on either side ends FAILED with a closed reason and its facts are dropped from both
sides, so no guessed ADDED or REMOVED appears for it; the failure reaches the drafts as UNKNOWN. The run continues.
Nothing executes target code: extractors read blob text and parse it with `ast` or `expat` only.

Content an extractor does not model raises `Unsupported` (file UNSUPPORTED, change reported UNKNOWN).
A changed file that no extractor claims is UNSUPPORTED (NO_PARSER, or NO_JS_ADAPTER for `.js`) and gets one
UNKNOWN draft for the file, with the reason code and the side(s) changed; unchanged files never get a record.

Extractor protocol (duck-typed): `domain`, optional `parser`, `handles(path, toolkit) -> bool`,
`facts(text, path, toolkit) -> list` (each fact has `subject_key`, `kind`, `attrs`, `body_digest`, `line`; the driver
adds `domain`, `path`, `sha256`), optional `hints(text, path, toolkit) -> list` of `{from, to, source}`. `toolkit` is
the `parsers.extract_toolkit.ExtractToolkit` injected by the composition root, or None when none is attached; an
extractor that needs an adapter it cannot get then declines the path (`handles` False, NO_PARSER or NO_JS_ADAPTER).
Raise `ParseFailure(code, detail)` for a parse error.
"""

import fnmatch
import json
from dataclasses import dataclass

from odooflux.knowledge.extract import accounting as acc
from odooflux.knowledge.extract import classify as c
from odooflux.knowledge.extract import rename as rn

__all__ = ["ParseFailure", "Unsupported", "ExtractResult", "extract_pair", "default_registry", "require_toolkit"]

FACT_KEYS = ("subject_key", "kind", "attrs", "body_digest", "line")


class ParseFailure(Exception):
    """An extractor could not read one file version. `code` is a reason code (unknown codes become OTHER)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class Unsupported(Exception):
    """An extractor met content it does not model (for example a record of an unknown model). The file ends
    UNSUPPORTED with NO_PARSER, and the change is still reported as UNKNOWN, never dropped."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class ExtractResult:
    drafts: list
    accounting: dict


def require_toolkit(toolkit):
    """The attached document toolkit, or Unsupported NO_PARSER when the run has none (never a crash or a skip)."""
    if toolkit is None:
        raise Unsupported("NO_PARSER: no document adapters are attached to this extract run")
    return toolkit


def default_registry() -> list:
    """Every domain extractor shipped with feature 011. A new domain module with an `EXTRACTORS` tuple is added
    here; the test suite fails if one is left out."""
    from odooflux.knowledge.extract.domains import (assets, data, js_owl, manifest, migration_scripts, python_orm,
                                                    reports_controllers, security, xml_views)
    found = []
    for module in (assets, data, js_owl, manifest, migration_scripts, python_orm, reports_controllers, security,
                   xml_views):
        found.extend(module.EXTRACTORS)
    return sorted(found, key=lambda e: (e.domain, type(e).__name__))


# Domain for an unsupported file that no extractor claims: the JavaScript extractor when only the adapter is missing,
# otherwise the catch-all "other" (not "docs", which would mislabel a non-documentation file).
_UNCLAIMED_DOMAIN = {"NO_JS_ADAPTER": "js_owl"}
_CATCH_ALL_DOMAIN = "other"


def _unclaimed_draft(path: str, code: str, from_entry, to_entry, from_id: str, to_id: str) -> dict:
    """UNKNOWN draft for a changed file no extractor handles: the file is the subject, the reason code and the
    side(s) changed travel in the detail, and it stays UNRESOLVED in the ledger (never dropped)."""
    present = [(side, entry, snap) for side, entry, snap in (("from", from_entry, from_id), ("to", to_entry, to_id))
               if entry is not None]
    sides = [side for side, _, _ in present]
    locations = [{"snapshot_id": snap, "path": path, "line": None, "sha256": entry["sha256"]}
                 for _, entry, snap in present]
    return {"domain": _UNCLAIMED_DOMAIN.get(code, _CATCH_ALL_DOMAIN), "kind": "file", "subject_key": path, "class": "UNKNOWN",
            "detail": {"reason": "UNSUPPORTED", "detail": f"{code}; changed on: {','.join(sides)}"},
            "locations": sorted(locations, key=lambda loc: (loc["snapshot_id"], loc["path"], loc["line"] or 0)),
            "proposed_by": "DETERMINISTIC"}


def _reason(code: str) -> str:
    return code if code in acc.REASON_CODES else "OTHER"


def _enrich(fact, domain: str, path: str, sha256: str) -> dict:
    if not isinstance(fact, dict) or any(k not in fact for k in FACT_KEYS):
        raise ParseFailure("OTHER", f"extractor {domain} returned a malformed fact")
    return {**fact, "domain": domain, "path": path, "sha256": sha256}


def _unique_hints(hints: list) -> list:
    seen = {}
    for hint in hints:
        seen[json.dumps(hint, sort_keys=True)] = hint
    return [seen[key] for key in sorted(seen)]


def extract_pair(from_snap: dict, to_snap: dict, scope, registry, *, store, step: str, limits=None,
                 toolkit=None) -> ExtractResult:
    """Drafts (for `Ledger.create`) and the finalized file-accounting document for one from/to snapshot pair.

    `scope` is a list of fnmatch globs on the relative POSIX path (empty or None means everything is in scope).
    `limits` is the `extract/config.json` mapping (defaults to the packaged file). `toolkit` is the injected
    document-adapter toolkit (None means no adapters: parser-bound files are UNSUPPORTED)."""
    config = limits or c.load_config()
    accounting = acc.FileAccounting.for_pair(step, from_snap, to_snap)
    from_entries = {e["path"]: e for e in from_snap["entries"]}
    to_entries = {e["path"]: e for e in to_snap["entries"]}
    registry = sorted(registry, key=lambda e: (e.domain, type(e).__name__))

    per_path = {}      # path -> {"from": [facts], "to": [facts]} for files that analysed cleanly
    failures = []      # classify.classify_pair failure records
    unclaimed = []     # changed files no extractor handles: (path, reason code)
    hints = []
    for path in accounting.pending():
        present = [e for e in (from_entries.get(path), to_entries.get(path)) if e is not None]
        if scope and not any(fnmatch.fnmatchcase(path, pattern) for pattern in scope):
            accounting.set_state(path, "EXCLUDED", reason_code="OUT_OF_SCOPE_GLOB")
            continue
        too_large = c.file_reason(max(e["size"] for e in present), config)
        if too_large:
            accounting.set_state(path, "EXCLUDED", reason_code=too_large)
            continue
        chosen = [ex for ex in registry if ex.handles(path, toolkit)]
        if not chosen:
            code = "NO_JS_ADAPTER" if path.endswith(".js") else "NO_PARSER"
            accounting.set_state(path, "UNSUPPORTED", reason_code=code)
            unclaimed.append((path, code))
            continue

        domains = sorted({ex.domain for ex in chosen})
        parsers = sorted({getattr(ex, "parser", ex.domain) for ex in chosen})
        side_facts = {"from": [], "to": []}
        side_hints = []
        path_failures = []

        def record(domain, side, entry, code, detail, state="FAILED"):
            path_failures.append({"domain": domain, "path": path, "sha256": entry["sha256"],
                                  "detail": detail or code, "side": side, "reason": _reason(code), "state": state})

        for side, entry in (("from", from_entries.get(path)), ("to", to_entries.get(path))):
            if entry is None:
                continue
            try:
                text = store.get(entry["sha256"]).decode("utf-8")
            except UnicodeDecodeError as exc:
                record(chosen[0].domain, side, entry, "ENCODING_ERROR", str(exc))
                continue
            except Exception as exc:  # a corrupt or missing blob is a failure, never a skip
                record(chosen[0].domain, side, entry, "OTHER", f"{type(exc).__name__}: {exc}")
                continue
            for ex in chosen:
                try:
                    facts = [_enrich(f, ex.domain, path, entry["sha256"]) for f in ex.facts(text, path, toolkit)]
                except Unsupported as exc:
                    record(ex.domain, side, entry, "NO_PARSER", exc.detail, state="UNSUPPORTED")
                    continue
                except ParseFailure as exc:
                    record(ex.domain, side, entry, exc.code, exc.detail)
                    continue
                except Exception as exc:  # any extractor error is a recorded failure for this file
                    record(ex.domain, side, entry, "OTHER", f"{type(exc).__name__}: {exc}")
                    continue
                side_facts[side].extend(facts)
                if side == "to" and hasattr(ex, "hints"):
                    side_hints.extend(ex.hints(text, path, toolkit))

        if path_failures:
            # a FAILED side outranks an UNSUPPORTED one; both reach the drafts as UNKNOWN
            first = next((f for f in path_failures if f["state"] == "FAILED"), path_failures[0])
            accounting.set_state(path, first["state"], reason_code=first["reason"], domain=first["domain"],
                                 parser=",".join(parsers), error=first["detail"])
            failures.extend(path_failures)
        else:
            per_path[path] = side_facts
            hints.extend(side_hints)
            accounting.set_state(path, "ANALYZED", domain=domains[0], parser=",".join(parsers))

    before = [f for p in sorted(per_path) for f in per_path[p]["from"]]
    after = [f for p in sorted(per_path) for f in per_path[p]["to"]]
    drafts = c.classify_pair(before, after, from_snapshot_id=from_snap["snapshot_id"],
                             to_snapshot_id=to_snap["snapshot_id"], failures=failures, config=config)
    for path, code in unclaimed:
        drafts.append(_unclaimed_draft(path, code, from_entries.get(path), to_entries.get(path),
                                       from_snap["snapshot_id"], to_snap["snapshot_id"]))
    drafts.sort(key=lambda draft: (draft["domain"], draft["kind"], draft["subject_key"]))
    drafts = rn.refine_candidates(drafts, before, after, config=config, hints=_unique_hints(hints))
    return ExtractResult(drafts=drafts, accounting=accounting.finalize())

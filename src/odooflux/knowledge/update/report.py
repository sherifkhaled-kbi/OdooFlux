"""Pure renderers and JSON payload builders for `odooflux knowledge update|status|history` (feature 012, Wave 3c).

No I/O, no network, no clock: every function is deterministic for its arguments. The CLI (cli/kap_update.py) gathers the
facts and passes them here; the tests validate the JSON against the shipped schemas.

JSON contracts
- update: `UpdateResult.to_dict()`, schema `odooflux.knowledge-update/1`, shipped as schemas/update_report.schema.json.
- status: `odooflux.knowledge-status/1` (built by `status_payload`), shipped as schemas/knowledge_status.schema.json.
- history: `odooflux.knowledge-history/1` (built by `history_payload`). Shape: {"schema", "chain" (always "verified",
  because the CLI refuses to print an unverified chain), "entries": [row, ...]} with newest rows first. A row has
  seq, timestamp, outcome, previous_release, new_release, source_revisions, changes (dict or null, from details),
  activation (dict or null, from details), failure_reason (the record reason for BLOCKED, FAILED and ROLLED_BACK,
  otherwise null).

Human update report. Every number comes from the UpdateResult fields. The knowledge change lines map UpdateResult.changes
keys as follows (a missing key counts 0). changes None means no build ran, so the counts are not computed and say so:
  new detection rules = rules_added; updated rules = rules_changed; new verified fixes = fix_enabled_added;
  removed/superseded rules = rules_lost + rules_superseded; unverified fixes = rules_downgraded.
A comparison that did not run (result.check None, or its statuses contain CHECK_UNAVAILABLE) prints "comparison
unavailable" and never a zero, so "no change" and "not compared" stay distinct.
"""

from odooflux.knowledge.update.model import CERTIFICATION_STATEMENT

STATUS_SCHEMA = "odooflux.knowledge-status/1"
HISTORY_SCHEMA = "odooflux.knowledge-history/1"
UPDATE_HEADER = "OdooFlux Knowledge Update"
STATUS_HEADER = "OdooFlux Knowledge Status"
HISTORY_HEADER = "OdooFlux Knowledge History"
UNAVAILABLE = "comparison unavailable"
CHECK_UNAVAILABLE = "CHECK_UNAVAILABLE"
FAILURE_OUTCOMES = ("BLOCKED", "FAILED", "ROLLED_BACK")
CHANGE_LINES = (
    ("new detection rules", ("rules_added",)),
    ("updated rules", ("rules_changed",)),
    ("new verified fixes", ("fix_enabled_added",)),
    ("removed/superseded rules", ("rules_lost", "rules_superseded")),
    ("unverified fixes", ("rules_downgraded",)),
)


def _count(changes: dict, keys) -> int:
    return sum(int(changes.get(key) or 0) for key in keys)


def _suffix(names) -> str:
    names = [str(name) for name in names if name]
    return f" ({', '.join(names)})" if names else ""


def _comparison(result):
    """The check dict when the comparison ran, else None."""
    check = result.check
    if not isinstance(check, dict) or CHECK_UNAVAILABLE in (check.get("statuses") or ()):
        return None
    return check


def render_update(result) -> str:
    """Human report for one UpdateResult (plan Addendum E shape). Deterministic; ends with a newline."""
    check = _comparison(result)
    lines = [UPDATE_HEADER, f"outcome: {result.outcome}"]
    lines.extend(f"reason: {reason}" for reason in result.reasons)
    mode = "dry run" if result.dry_run else "apply"
    lines.append(f"mode: {mode}, " + ("offline, no remote contacted" if result.offline else "online"))
    if isinstance(result.check, dict):
        statuses = result.check.get("statuses") or ()
        lines.append("check status: " + (", ".join(statuses) if statuses else "no conclusive status"))

    if check is None:
        lines.append(f"sources checked: {UNAVAILABLE}")
        lines.append(f"new versions: {UNAVAILABLE}")
        lines.append(f"updated versions: {UNAVAILABLE}")
    else:
        sources = list(check.get("sources") or [])
        compared = [s for s in sources if s.get("status") == "OK"]
        updated = [s for s in sources if s.get("remote_sha") and s.get("remote_sha") != s.get("installed_sha")]
        new_versions = list(check.get("new_versions") or [])
        lines.append(f"sources checked: {len(sources)} (compared {len(compared)})")
        lines.append(f"new versions: {len(new_versions)}" + _suffix(nv.get("version") for nv in new_versions))
        lines.append(f"updated versions: {len(updated)}" + _suffix(s.get("version") for s in updated))

    lines.append("knowledge changes:")
    if result.changes is None:
        lines.append("  not computed (no build ran)")
    else:
        for label, keys in CHANGE_LINES:
            lines.append(f"  {label}: {_count(result.changes, keys)}")

    activation = result.activation.get("state") if isinstance(result.activation, dict) else None
    active = result.new_release if result.outcome == "ACTIVE" else result.previous_release
    lines.append("release:")
    lines.append(f"  integrity digest: {result.release_digest or 'not computed'}")
    lines.append(f"  activation: {activation or 'not attempted'}")
    lines.append(f"  completeness: {result.completeness or 'not computed'}")
    lines.append(f"  active release id: {active or 'none (built-in knowledge only)'}")

    enterprise = result.enterprise if isinstance(result.enterprise, dict) else {}
    freshness = enterprise.get("freshness") or (check or {}).get("enterprise_freshness") or "UNKNOWN"
    lines.append(f"enterprise: {enterprise.get('status') or 'not checked'}, freshness {freshness}")

    lines.append("limitations:")
    if result.limitations:
        lines.extend(f"  - {item}" for item in result.limitations)
    else:
        lines.append("  none recorded")

    lines.append("support dimensions:")
    for key, text in CERTIFICATION_STATEMENT.items():
        lines.append(f"  {key.replace('_', ' ')}: {text}")
    return "\n".join(lines) + "\n"


def status_limitations(completeness, registry_bound=0) -> list:
    """The known limitations of the installed knowledge, always in this order. `registry_bound` is the number of
    DETECT_ONLY rows counted as FIX_ENABLED at read time because a registry fixer binds (stored rows are unchanged)."""
    items = []
    if completeness == "PARTIAL":
        items.append("knowledge completeness is PARTIAL: some pipeline steps are not covered by the active release")
    items.append("migration support not established")
    items.append("production certification not granted")
    items.append("Enterprise freshness unknown without a check")
    if registry_bound:
        items.append(f"fix-enabled count includes {registry_bound} DETECT_ONLY rule(s) bound to an experimental "
                     "registry fixer (effective maturity at read time; stored maturity unchanged)")
    return items


def status_payload(*, release_id, digest, completeness, steps, revisions, rules_by_maturity, certification_governed,
                   last_successful, registry_bound=0) -> dict:
    """`odooflux.knowledge-status/1`. `release_id` None means built-in knowledge only. `rules_by_maturity` must already
    use each row's effective maturity (a capped row counts as DETECT_ONLY; see `knowledge_rules.effective_maturity`).
    `registry_bound` counts the rows promoted that way. `last_successful` is a dict or None."""
    by_maturity = {str(k): int(v) for k, v in sorted(rules_by_maturity.items())}
    return {
        "schema": STATUS_SCHEMA,
        "kind": "built-in" if release_id is None else "external",
        "release_id": release_id,
        "digest": digest,
        "completeness": completeness,
        "steps_covered": {str(k): str(steps[k]) for k in sorted(steps)},
        "installed_sources": {str(k): str(revisions[k]) for k in sorted(revisions)},
        "rules": {"total": sum(by_maturity.values()), "by_maturity": by_maturity,
                  "fix_enabled": by_maturity.get("FIX_ENABLED", 0),
                  "certification_governed": int(certification_governed)},
        "last_successful_update": last_successful,
        "limitations": status_limitations(completeness, registry_bound),
    }


def render_status(payload: dict) -> str:
    """Human status report from a `status_payload` dict. Deterministic; ends with a newline."""
    lines = [STATUS_HEADER, f"knowledge: {payload['kind']}"]
    if payload["release_id"] is None:
        lines.append("active release: none (built-in knowledge only)")
    else:
        lines.append(f"active release: {payload['release_id']}")
    lines.append(f"digest: {payload['digest'] or 'not computed'}")
    lines.append(f"completeness: {payload['completeness'] or 'not recorded'}")
    steps = payload["steps_covered"]
    lines.append("steps covered: " + (", ".join(f"{s} ({c})" for s, c in steps.items()) or "none recorded"))
    revisions = payload["installed_sources"]
    if revisions:
        lines.append("installed sources:")
        lines.extend(f"  {source_id}: {revision}" for source_id, revision in revisions.items())
    else:
        lines.append("installed sources: none recorded")
    rules = payload["rules"]
    by_maturity = ", ".join(f"{k}={v}" for k, v in rules["by_maturity"].items()) or "none"
    lines.append(f"detection rules: {rules['total']} ({by_maturity})")
    lines.append(f"fix-enabled rules: {rules['fix_enabled']}")
    lines.append(f"certification-governed rules: {rules['certification_governed']}")
    last = payload["last_successful_update"]
    if last:
        lines.append(f"last successful update: {last['timestamp']} (release {last['new_release']}, seq {last['seq']})")
    else:
        lines.append("last successful update: none recorded")
    lines.append("limitations:")
    lines.extend(f"  - {item}" for item in payload["limitations"])
    return "\n".join(lines) + "\n"


def history_rows(entries) -> list:
    """Normalised rows for verified history entries (newest first, as `UpdateHistory.read` returns them)."""
    rows = []
    for entry in entries:
        details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
        changes = details.get("changes") if isinstance(details.get("changes"), dict) else None
        activation = details.get("activation") if isinstance(details.get("activation"), dict) else None
        failure = entry.get("reason") if entry["outcome"] in FAILURE_OUTCOMES else None
        rows.append({
            "seq": entry["seq"],
            "timestamp": entry["ts"],
            "outcome": entry["outcome"],
            "previous_release": entry["previous_release"],
            "new_release": entry["new_release"],
            "source_revisions": {str(k): str(v) for k, v in sorted(entry["source_revisions"].items())},
            "changes": changes,
            "activation": activation,
            "failure_reason": failure,
        })
    return rows


def history_payload(rows) -> dict:
    """`odooflux.knowledge-history/1` (see the module docstring for the row shape)."""
    return {"schema": HISTORY_SCHEMA, "chain": "verified", "entries": list(rows)}


def _change_text(changes: dict) -> str:
    parts = []
    for key in sorted(changes):
        value = changes[key]
        parts.append(f"{key}={len(value) if isinstance(value, list) else value}")
    return ", ".join(parts) or "none"


def render_history(rows) -> str:
    """Human history listing (newest first). Deterministic; ends with a newline."""
    lines = [HISTORY_HEADER, "chain: verified"]
    if not rows:
        lines.append("no update history recorded")
        return "\n".join(lines) + "\n"
    for row in rows:
        lines.append(f"#{row['seq']} {row['timestamp']} {row['outcome']}")
        lines.append(f"  release: {row['previous_release'] or 'none'} -> {row['new_release'] or 'none'}")
        revisions = row["source_revisions"]
        lines.append("  sources: " + (", ".join(f"{k}={v}" for k, v in revisions.items()) or "none"))
        if row["changes"] is not None:
            lines.append("  changes: " + _change_text(row["changes"]))
        else:
            lines.append("  changes: not recorded")
        activation = row["activation"]
        lines.append("  activation: " + (str(activation.get("state", "recorded")) if activation else "not recorded"))
        if row["failure_reason"]:
            lines.append(f"  failure reason: {row['failure_reason']}")
    return "\n".join(lines) + "\n"

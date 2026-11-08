"""Runtime run records (008 T029-gen): validation and the only route to ``RUNTIME_VALIDATED`` in the matrix.

A step is runtime validated only when its most recent *valid* record has result PASS. Invalid records (schema or
consistency problems) are ignored by the generator and reported by ``knowledge validate``. A record whose source side
has no usable image never counts as behaviourally verified."""

import json

from odooflux.knowledge import validator
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, KnowledgeBase

FILE = "compatibility/runtime_runs.json"


def _schema() -> dict:
    return json.loads((KNOWLEDGE_ROOT / "schemas" / "runtime_runs.schema.json").read_text(encoding="utf-8"))


def record_problems(record) -> list:
    """Problems of one run record (empty = usable)."""
    problems = [f"{ptr or '/'}: {msg}" for ptr, msg in validator.check(record, _schema()["properties"]["runs"]["items"])]
    if problems:
        return problems
    src, dst = record["source_version"].split(".")[0], record["target_version"].split(".")[0]
    if record["step"] != f"{src}-{dst}":
        problems.append(f"step {record['step']} does not match {record['source_version']} -> {record['target_version']}")
    if record["behavioural"] == "PASS" and (record["result"] != "PASS" or not record["source_image_digest"]):
        problems.append("behavioural PASS needs a passing run and a source-side image digest")
    return problems


def file_problems(kb: KnowledgeBase) -> list:
    """(pointer, message) problems of the whole file: structure, per-record, duplicate ids."""
    data = kb.runtime_runs
    if not data:
        return []
    schema = _schema()
    shell = {**schema, "properties": {**schema["properties"], "runs": {"type": "array"}}}  # records checked below
    out = list(validator.check(data, shell))
    runs = data.get("runs")
    if not isinstance(runs, list):
        return out + [("/runs", "expected an array")]
    seen = set()
    for index, record in enumerate(runs):
        out += [(f"/runs/{index}", m) for m in record_problems(record)]
        ident = record.get("id") if isinstance(record, dict) else None
        if ident in seen:
            out.append((f"/runs/{index}/id", f"duplicate id {ident}"))
        seen.add(ident)
    return out


def valid_runs(kb: KnowledgeBase) -> list:
    runs = (kb.runtime_runs or {}).get("runs")
    if (kb.runtime_runs or {}).get("schema") != "odooflux.runtime-runs/1" or not isinstance(runs, list):
        return []
    return [r for r in runs if isinstance(r, dict) and not record_problems(r)]


def _latest(kb: KnowledgeBase, step: str):
    records = [(r["date"], i, r) for i, r in enumerate(valid_runs(kb)) if r["step"] == step]
    return max(records, key=lambda t: (t[0], t[1]))[2] if records else None


def runtime_status(kb: KnowledgeBase, step: str) -> str:
    """RUNTIME_VALIDATED (latest valid record passes), RUN_FAILED (latest fails) or the unmarked dash."""
    latest = _latest(kb, step)
    if latest is None:
        return "—"
    return "RUNTIME_VALIDATED" if latest["result"] == "PASS" else "RUN_FAILED"


def behavioural_status(kb: KnowledgeBase, step: str) -> str:
    latest = _latest(kb, step)
    if (latest and latest["result"] == "PASS" and latest["behavioural"] == "PASS"
            and latest["source_image_digest"]):
        return "BEHAVIOURAL_VERIFIED"
    return "—"

# Public signatures (addendum F2). Pure; build/verify read proofs.py via live_source_digest only.
# prove(entry: dict, sides: dict, *, rule_id: str, evidence: list, new: str | None = None) -> Attested | Refusal
# build(attested: Attested, *, rule_row: dict) -> dict                # raises ConfirmationError on any mismatch
# verify(record: dict, *, rule_row: dict, evidence_rows: list, ledger_entry: dict | None = None) -> Verdict   # L1
# verify_sources(record: dict, data: dict) -> Verdict        # L2; data = {"from": bytes, "to": bytes}
# derived_class(record: dict, *, rule_row, evidence_rows, ledger_entry=None) -> str | None
# check_witness(witness: dict) -> proofs.Proof | proofs.Refusal       # re-export of proofs.check_witness
# entry_digest(entry: dict) -> str;  live_source_digest() -> str
# Attested(proof, entry, rule_id, sources, evidence);  Verdict(ok, derived_class, problems: [(code, detail)])
# Refusals: proofs.Refusal(code); codes are proofs.REFUSAL_CODES plus ENTRY_*, SIDE_*, SOURCE_*, EVIDENCE_* here.
"""Machine confirmation record `odooflux.machine-confirmation/1` (feature 012, addendum F2).

A machine confirmation is a separate artifact at `<release>/knowledge/confirmations/<rule_id>.json`. It never sets the
ledger `confirmed` flag and is never a MANUAL action. The ledger entry keeps `confirmed:false`; the record names the
derived class that trust uses (`derived_class`), backed by a structural witness from `extract/proofs.py`.

Trust chain: `prove` (pure, ledger + source texts) -> `build` (record, after the fix rule row exists so that
`rule_digest` can be bound) -> written by autofix during a pipeline build. Verification is recomputed, never trusted:
`verify` (L1) needs only the release tree; `verify_sources` (L2) rereads the blobs, reproves and compares the witness
digest byte for byte.

Caller obligations (not checked here, documented for autofix): `sides[side]["verified"|"official"|"pinned"]` come from
gate 1 of the pair; `evidence` rows come from gates 1-2; `new` is the replacement for S1 and S2 and None for S3.

What L1 proves and what it does not. L1 is SELF-CONSISTENCY: the record's digests, its witness, its derived params and its
module must agree with one another and with the release tree (rule row, evidence rows, the module each source path
names, and the side whose file carries the proof). Any forger who can recompute digests can satisfy the parts of L1 that
are internal to the record. L1 is therefore not authenticity. Authenticity rests on the release manifest digest (the
`confirmations/` directory is inside it) and on L2 (`verify_sources`), which re-proves the retained blobs byte for byte
wherever a blob store exists (build step 9, update pre-activation).
"""

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.knowledge import validator as v
from odooflux.knowledge.extract import proofs
from odooflux.knowledge.release.canonical import digest_obj
from odooflux.knowledge.update import certification

__all__ = ["RECORD_SCHEMA", "POLICY_VERSION", "SCHEMA_PATH", "ConfirmationError", "Attested", "Verdict", "prove",
           "build", "verify", "verify_sources", "derived_class", "check_witness", "entry_digest", "live_source_digest"]

RECORD_SCHEMA = "odooflux.machine-confirmation/1"
POLICY_VERSION = "1"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "machine_confirmation.schema.json"
check_witness = proofs.check_witness
_EXPECTED_SIDES = {"REPLACEMENT_CANDIDATE": ("from", "to"), "BEHAVIOUR_CHANGED": ("to",), "DEPRECATED": ("to",),
                   "REMOVED": ("from",)}
_SIDE_FIELDS = ("source_id", "snapshot_id", "revision", "path", "blob_sha256")
_SCHEMA_CACHE: dict = {}


class ConfirmationError(ValueError):
    """`build` refuses inputs that would produce an inconsistent record. `code` is a reason code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class Attested:
    """A proven pair, not yet a record: the proof, the ledger entry (as read), the source identities and evidence."""
    proof: proofs.Proof
    entry: dict
    rule_id: str
    sources: list
    evidence: list = field(default_factory=list)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    derived_class: object   # the confirmed class when ok, else None
    problems: list          # [(code, detail)]


def _schema() -> dict:
    if "schema" not in _SCHEMA_CACHE:
        _SCHEMA_CACHE["schema"] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE["schema"]


def entry_digest(entry: dict) -> str:
    """Digest of a ledger entry without its history (the history grows; the rest is what confirmation binds)."""
    return digest_obj({k: val for k, val in entry.items() if k != "history"})


def live_source_digest() -> str:
    """sha256 of the bytes of extract/proofs.py as loaded now."""
    return hashlib.sha256(Path(proofs.__file__).read_bytes()).hexdigest()


def _tail(name) -> str:
    """The bare symbol of a ledger subject or pair name: the ledger keeps `addon.name` for addon modules, the proof
    works on the bare name (the module is checked separately, by name, from the path)."""
    return str(name or "").rsplit(".", 1)[-1]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prove(entry, sides, *, rule_id, evidence, new=None):
    """Prove one ledger pair. Returns `Attested` or a `proofs.Refusal` with a reason code. Never mutates inputs."""
    if not isinstance(entry, dict) or entry.get("confirmed") is not False:
        return proofs.Refusal("ENTRY_CONFIRMED", "the ledger entry must exist and stay confirmed:false")
    if entry.get("proposed_by") != "DETERMINISTIC":
        return proofs.Refusal("ENTRY_PROPOSER", "only deterministic drafts can be machine-confirmed, never AI proposals")
    cls = entry.get("class")
    if cls not in _EXPECTED_SIDES:
        return proofs.Refusal("ENTRY_CLASS", f"class {cls!r} cannot be machine-confirmed")
    if entry.get("domain") != "python_orm" or entry.get("kind") != "function":
        return proofs.Refusal("ENTRY_SUBJECT", "only python_orm functions are in scope")
    old = str(entry.get("subject_key", "")).rsplit(".", 1)[-1]
    detail = entry.get("detail") if isinstance(entry.get("detail"), dict) else {}
    if cls == "REPLACEMENT_CANDIDATE" and (_tail(detail.get("from")) != old or _tail(detail.get("to")) != new):
        return proofs.Refusal("ENTRY_NAMES", "the ledger pair does not name old and new")
    if not isinstance(sides, dict) or set(sides) != {"from", "to"}:
        return proofs.Refusal("SIDE_MISSING", "both sides are required")
    for side in ("from", "to"):
        s = sides[side]
        if not isinstance(s, dict) or any(not isinstance(s.get(f), str) or not s.get(f) for f in _SIDE_FIELDS):
            return proofs.Refusal("SIDE_MISSING", f"{side} identity is incomplete")
        for flag in ("verified", "official", "pinned"):
            if s.get(flag) is not True:
                return proofs.Refusal("SOURCE_NOT_PINNED", f"{side} is not {flag}")
        if not isinstance(s.get("data"), bytes) or _sha(s["data"]) != s["blob_sha256"]:
            return proofs.Refusal("BLOB_MISMATCH", f"{side} bytes do not rehash to the pinned digest")
    locations = entry.get("locations")
    expected = _EXPECTED_SIDES[cls]
    if not isinstance(locations, list) or len(locations) != len(expected):
        return proofs.Refusal("ENTRY_LOCATIONS", "the entry must hold exactly one location per expected side")
    matched_ids, lines = set(), {}
    for side in expected:
        s = sides[side]
        hits = [i for i, loc in enumerate(locations)
                if isinstance(loc, dict) and loc.get("snapshot_id") == s["snapshot_id"]
                and loc.get("path") == s["path"] and loc.get("sha256") == s["blob_sha256"]]
        if len(hits) != 1:
            return proofs.Refusal("ENTRY_LOCATIONS", f"no single entry location for the {side} side")
        matched_ids.add(hits[0])
        lines[side] = locations[hits[0]].get("line")
    if len(matched_ids) != len(locations):
        return proofs.Refusal("ENTRY_LOCATIONS", "an entry location matches no side")
    rows = evidence if isinstance(evidence, list) else []
    if not rows:
        return proofs.Refusal("EVIDENCE_MISSING", "no evidence rows")
    proof_sha = sides[expected[-1]]["blob_sha256"]
    for row in rows:
        if (not isinstance(row, dict) or row.get("official") is not True
                or rule_id not in (row.get("rule_ids") or []) or not row.get("source_applicability")
                or not row.get("target_applicability")):
            return proofs.Refusal("EVIDENCE_INVALID", "evidence must be official, name the rule and carry applicability")
    if not any(isinstance(loc, dict) and loc.get("content_sha256") == proof_sha
               for row in rows for loc in (row.get("locations") or [])):
        return proofs.Refusal("EVIDENCE_INVALID", "no evidence location carries the proof file digest")
    texts = {}
    for side in ("from", "to"):
        try:
            texts[side] = sides[side]["data"].decode("utf-8")
        except UnicodeDecodeError:
            return proofs.Refusal("PARSE_FAILED", f"{side} is not utf-8")
    result = proofs.prove(ledger_class=cls, source_kind=detail.get("source") if cls == "REPLACEMENT_CANDIDATE" else None,
                          old=old, new=new, from_path=sides["from"]["path"], to_path=sides["to"]["path"],
                          from_text=texts["from"], to_text=texts["to"])
    if isinstance(result, proofs.Refusal):
        return result
    sources = [{"side": side, **{f: sides[side][f] for f in _SIDE_FIELDS}, "line": lines.get(side)}
               for side in ("from", "to")]
    return Attested(proof=result, entry=copy.deepcopy(entry), rule_id=rule_id, sources=sources,
                    evidence=copy.deepcopy(rows))


def build(attested, *, rule_row):
    """The record for a proven pair. `rule_row` is the fix rule row the caller created from the derived params."""
    p = attested.proof
    if not isinstance(rule_row, dict) or rule_row.get("id") != attested.rule_id:
        raise ConfirmationError("rule_mismatch", "the rule row is not the one this proof is for")
    if rule_row.get("params") != p.derived_params:
        raise ConfirmationError("params_mismatch", "rule params differ from the derived params")
    if sorted(rule_row.get("evidence") or []) != sorted(r["id"] for r in attested.evidence):
        raise ConfirmationError("evidence_mismatch", "rule evidence differs from the proof evidence")
    try:
        bound = certification.rule_digest(rule_row)
    except certification.CertificationError as exc:
        raise ConfirmationError("rule_not_canonical", str(exc)) from None
    entry = attested.entry
    body = {
        "schema": RECORD_SCHEMA,
        "policy_version": POLICY_VERSION,
        "rule_id": attested.rule_id,
        "change_id": entry["change_id"],
        "derived_class": p.derived_class,
        "ledger_entry": {"class": entry["class"], "confirmed": False, "entry_digest": entry_digest(entry)},
        "subject": {"domain": entry["domain"], "kind": entry["kind"], "subject_key": entry["subject_key"]},
        "module": p.module,
        "old": p.old,
        "new": p.new,
        "witness": copy.deepcopy(p.witness),
        "witness_digest": p.witness_digest,
        "sources": copy.deepcopy(attested.sources),
        "evidence": [{"id": r["id"], "digest": digest_obj(r)} for r in sorted(attested.evidence, key=lambda r: r["id"])],
        "proof_tool": {"id": proofs.PROOF_TOOL_ID, "source_digest": live_source_digest()},
        "derived_params": copy.deepcopy(p.derived_params),
        "rule_digest": bound,
    }
    body["record_digest"] = digest_obj(body)
    return body


def _module_problems(record, sides) -> list:
    """Each source path must name the record's module (the path is the release's own identity for the file), and a
    replacement pair must name one file on both sides. Without this a module can be forged away from its source."""
    problems = []
    for side in ("from", "to"):
        if proofs.module_name(sides[side]["path"]) != record["module"]:
            problems.append(("module_path", f"{side} source path does not name module {record['module']}"))
    if record["ledger_entry"]["class"] == "REPLACEMENT_CANDIDATE" and sides["from"]["path"] != sides["to"]["path"]:
        problems.append(("module_path", "replacement pair must name the same file on both sides"))
    if record["derived_class"] == "IDENTITY_DECORATOR_REMOVED":
        bound = {"module": record["module"], "name": record["old"]}
    else:
        bound = {"module": record["module"], "old": record["old"], "new": record["new"]}
    if record["derived_params"] != bound:
        problems.append(("params_binding", "derived params are not bound to the record's module, old and new"))
    return problems


def verify(record, *, rule_row, evidence_rows, ledger_entry=None) -> Verdict:
    """L1: every check recomputed from the record and the release tree (rule row, evidence rows, optional ledger entry)."""
    if not isinstance(record, dict):
        return Verdict(False, None, [("record", "not an object")])
    problems = [("schema", f"{pointer}: {message}") for pointer, message in v.check(record, _schema())]
    if problems:
        return Verdict(False, None, problems)
    body = {k: val for k, val in record.items() if k != "record_digest"}
    if digest_obj(body) != record["record_digest"]:
        problems.append(("record_digest", "record digest does not match the record"))
    if record["proof_tool"]["source_digest"] != live_source_digest():
        problems.append(("proof_tool", "proofs.py digest differs from the live code"))
    if digest_obj(record["witness"]) != record["witness_digest"]:
        problems.append(("witness_digest", "witness digest does not match the witness"))
    sides = {}
    for item in record["sources"]:
        sides[item["side"]] = item
    if set(sides) != {"from", "to"} or len(record["sources"]) != 2:
        return Verdict(False, None, [("sources", "both sides must be recorded exactly once")])
    module_problems = _module_problems(record, sides)
    problems += module_problems
    again = proofs.check_witness(record["witness"])
    if isinstance(again, proofs.Refusal):
        problems.append(("witness", again.code))
    else:
        if again.derived_class != record["derived_class"]:
            problems.append(("derived_class", "derived class is not what the witness proves"))
        if again.derived_params != record["derived_params"]:
            problems.append(("derived_params", "derived params are not what the witness proves"))
        if (again.module, again.old, again.new) != (record["module"], record["old"], record["new"]):
            problems.append(("identity", "module, old and new do not match the witness"))
        if record["subject"]["subject_key"].rsplit(".", 1)[-1] != record["old"]:
            problems.append(("identity", "the ledger subject does not name the old symbol"))
        if record["ledger_entry"]["class"] != record["witness"]["ledger_class"]:
            problems.append(("ledger_class", "witness class and ledger class disagree"))
    if not isinstance(rule_row, dict):
        problems.append(("rule_missing", "the fix rule row is required"))
    else:
        if rule_row.get("id") != record["rule_id"]:
            problems.append(("rule_id", "rule row id differs"))
        if rule_row.get("params") != record["derived_params"]:
            problems.append(("rule_params", "rule params differ from the derived params"))
        if sorted(rule_row.get("evidence") or []) != sorted(e["id"] for e in record["evidence"]):
            problems.append(("rule_evidence", "rule evidence differs from the record"))
        try:
            if certification.rule_digest(rule_row) != record["rule_digest"]:
                problems.append(("rule_digest", "rule digest differs from the bound digest"))
        except certification.CertificationError:
            problems.append(("rule_digest", "rule row is not canonical"))
    rows = evidence_rows if isinstance(evidence_rows, list) else []
    by_id = {row["id"]: row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)}
    for ref in record["evidence"]:
        row = by_id.get(ref["id"])
        if row is None:
            problems.append(("evidence_missing", f"evidence {ref['id']} was not supplied"))
        elif digest_obj(row) != ref["digest"]:
            problems.append(("evidence_digest", f"evidence {ref['id']} changed"))
        elif row.get("official") is not True or record["rule_id"] not in (row.get("rule_ids") or []):
            problems.append(("evidence_invalid", f"evidence {ref['id']} is not official for this rule"))
    if set(by_id) - {ref["id"] for ref in record["evidence"]}:
        problems.append(("evidence_unexpected", "evidence not bound by the record"))
    proof_side = record["witness"].get("proof_side")
    proof_digest = sides[proof_side]["blob_sha256"] if proof_side in sides else None
    bound_locations = [loc for ref in record["evidence"] if ref["id"] in by_id
                       for loc in (by_id[ref["id"]].get("locations") or []) if isinstance(loc, dict)]
    if proof_digest is None or not any(loc.get("content_sha256") == proof_digest for loc in bound_locations):
        problems.append(("evidence_side", "no bound evidence location carries the digest of the proof side"))
    if ledger_entry is not None:
        bound = record["ledger_entry"]
        if (ledger_entry.get("change_id") != record["change_id"]
                or ledger_entry.get("subject_key") != record["subject"]["subject_key"]):
            problems.append(("ledger_identity", "ledger entry is another change"))
        if entry_digest(ledger_entry) != bound["entry_digest"] or ledger_entry.get("class") != bound["class"]:
            problems.append(("ledger_entry", "ledger entry differs from the confirmed entry"))
        if ledger_entry.get("confirmed") is not False:
            problems.append(("ledger_entry", "a machine confirmation never confirms the ledger entry"))
    return Verdict(not problems, None if problems else record["derived_class"], problems)


def verify_sources(record, data) -> Verdict:
    """L2: the retained blobs must rehash to the record, reprove to the same witness digest, byte for byte."""
    if not isinstance(record, dict) or not isinstance(record.get("sources"), list):
        return Verdict(False, None, [("record", "not a confirmation record")])
    sources = {s.get("side"): s for s in record["sources"] if isinstance(s, dict)}
    if set(sources) != {"from", "to"}:
        return Verdict(False, None, [("sources", "both sides must be recorded")])
    problems, texts = [], {}
    for side in ("from", "to"):
        raw = data.get(side) if isinstance(data, dict) else None
        if not isinstance(raw, bytes) or _sha(raw) != sources[side]["blob_sha256"]:
            problems.append(("blob", f"{side} blob is missing or does not rehash"))
            continue
        try:
            texts[side] = raw.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(("blob", f"{side} blob is not utf-8"))
    if problems:
        return Verdict(False, None, problems)
    again = proofs.prove(ledger_class=record["ledger_entry"]["class"], source_kind=record["witness"]["source_kind"],
                         old=record["old"], new=record["new"], from_path=sources["from"]["path"],
                         to_path=sources["to"]["path"], from_text=texts["from"], to_text=texts["to"])
    if isinstance(again, proofs.Refusal):
        return Verdict(False, None, [("reprove", again.code)])
    if again.witness_digest != record["witness_digest"]:
        return Verdict(False, None, [("witness_digest", "the sources do not reproduce the witness")])
    return Verdict(True, again.derived_class, [])


def derived_class(record, *, rule_row, evidence_rows, ledger_entry=None):
    """The confirmed class when L1 passes, else None. Trust reads this, never `record["change_class"]`."""
    return verify(record, rule_row=rule_row, evidence_rows=evidence_rows, ledger_entry=ledger_entry).derived_class

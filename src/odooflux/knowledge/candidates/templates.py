"""Extraction templates: data that maps a change to a candidate rule skeleton (REQ-KAP-016, REQ-KAP-015).

A template is JSON in `knowledge/extraction_templates/`. It names the change it matches (`match`: domain, class and
optionally kind), a detector that must exist under `odooflux.rules` (a bindable generic function, never a fixer), and
`params_from`, a map from each detector keyword to a dotted path in the change view (`subject.name` is the last segment
of the subject key). Adding a change shape needs new template data or a new generic detector, never generator code.

Skeletons are DETECT_ONLY, `review_required` true, carry no fixer and are origin GENERATED. A replacement is written
only when the template asks for it (`replacement_suggestion`) and a CONFIRMED ledger entry of class
REPLACEMENT_CANDIDATE supplies it. Nothing is invented. Pure stdlib: no network, no AI, no database.
"""

import hashlib
import inspect
import json
import re
from pathlib import Path

from odooflux.knowledge.extract.classify import load_config
from odooflux.knowledge.release.canonical import canonical_bytes

__all__ = ["TemplateError", "TemplateList", "TEMPLATE_DIR", "FIXER_PREFIXES", "load_templates", "verify_detector_ref",
           "detector_params_problem", "detector_shape_problem", "check_detector_table", "select_template",
           "build_skeleton", "change_view"]

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "extraction_templates"
FIXER_PREFIXES = ("remove_", "rename_", "rewrite_", "migrate_", "fix_")
RISKS = ("LOW", "MEDIUM", "HIGH")
CONFIDENCES = ("HIGH", "MEDIUM", "LOW")
TEMPLATE_KEYS = ("template_id", "description", "match", "rule", "confidence", "tests", "replacement_suggestion")
MATCH_KEYS = ("domain", "class", "kind")
RULE_KEYS = ("category", "detector_ref", "fixer_ref", "params_from", "risk", "review_required")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_CATEGORY = re.compile(r"^[a-z_]+$")


class TemplateError(ValueError):
    """A template, detector reference, or skeleton request that is not allowed."""


class TemplateList(list):
    """Checked templates. `detectors_verified` is True only when every `detector_ref` was resolved against the
    bindable detector table; False only for an explicit `verify=False` (tests)."""

    detectors_verified = False


def _need_detectors(known_detectors) -> None:
    if known_detectors is None:
        raise TemplateError("detector_ref verification needs known_detectors (the bindable detector table, as "
                            "parsers.extract_toolkit.ExtractToolkit.detectors); verify=False is for tests only")


def detector_shape_problem(ref: str, func) -> str | None:
    """T056 signature rule: the first two parameters are the frame, every later one is keyword-only."""
    params = list(inspect.signature(func).parameters.values())[2:]
    if any(p.kind != p.KEYWORD_ONLY for p in params):
        return f"detector {ref!r} takes positional parameters and cannot be bound by keyword"
    return None


def check_detector_table(table) -> None:
    """Validate the bindable detector table: detector ref (`module:function`) -> bindable module object. Raises
    TemplateError naming the offending ref. Run at composition time, so a malformed table never reaches a template."""
    if not isinstance(table, dict):
        raise TemplateError("the bindable detector table must be a mapping of detector ref to module")
    for ref, module in table.items():
        if not isinstance(ref, str) or ":" not in ref:
            raise TemplateError(f"detector table entry {ref!r}: the key must look like module:function")
        module_name, _, func_name = ref.partition(":")
        if not inspect.ismodule(module) or module.__name__ != module_name:
            raise TemplateError(f"detector table entry {ref!r}: the value must be the bindable module {module_name}")
        if not func_name or func_name.startswith("_"):
            raise TemplateError(f"detector table entry {ref!r}: not a public function name")
        if func_name.startswith(FIXER_PREFIXES):
            raise TemplateError(f"detector table entry {ref!r}: a fixer is never a detector")
        func = getattr(module, func_name, None)
        if not inspect.isfunction(func) or func.__module__ != module.__name__:
            raise TemplateError(f"detector table entry {ref!r}: not a function defined in {module_name}")
        shape = detector_shape_problem(ref, func)
        if shape:
            raise TemplateError(f"detector table entry {ref!r}: {shape}")


def _config_sets() -> tuple:
    config = load_config()
    classes = set(config["classes_by_stage"]["classify"]) | set(config["classes_by_stage"]["rename"])
    return set(config["domains"]), classes


def _bindable_module(ref: str, known_detectors):
    _need_detectors(known_detectors)
    module_name, _, func_name = ref.partition(":")
    module = known_detectors.get(ref)
    if module is None or not func_name or func_name.startswith("_"):
        raise TemplateError(f"detector_ref {ref!r} does not name a bindable rule module function")
    func = getattr(module, func_name, None)
    if not inspect.isfunction(func) or func.__module__ != module.__name__:
        raise TemplateError(f"detector_ref {ref!r} does not resolve to a function of {module_name}")
    return func


def verify_detector_ref(ref: str, known_detectors):
    """The detector function behind `module:function`, resolved in `known_detectors` (detector ref -> bindable module,
    see `check_detector_table`). Refuses fixers and anything not in the table."""
    if not isinstance(ref, str) or ":" not in ref:
        raise TemplateError(f"detector_ref {ref!r} must look like module:function")
    func = _bindable_module(ref, known_detectors)
    name = ref.partition(":")[2]
    if name.startswith(FIXER_PREFIXES):
        raise TemplateError(f"detector_ref {ref!r} is a fixer; templates name detectors only")
    return func


def detector_params_problem(ref: str, keys, known_detectors) -> str | None:
    """None when `keys` are exactly the keyword parameters the detector requires plus optional ones it accepts."""
    func = verify_detector_ref(ref, known_detectors)
    shape = detector_shape_problem(ref, func)
    if shape:
        return shape
    params = list(inspect.signature(func).parameters.values())[2:]
    accepted = {p.name for p in params}
    required = {p.name for p in params if p.default is p.empty}
    keys = set(keys)
    if keys - accepted:
        return f"detector {ref!r} does not accept {sorted(keys - accepted)}"
    if required - keys:
        return f"detector {ref!r} requires {sorted(required - keys)}"
    return None


def _check(data, where: str, known_detectors, verify: bool = True) -> dict:
    domains, classes = _config_sets()
    if not isinstance(data, dict) or set(data) - set(TEMPLATE_KEYS):
        raise TemplateError(f"{where}: must be an object with keys within {TEMPLATE_KEYS}")
    template_id = data.get("template_id")
    if not isinstance(template_id, str) or not _ID.match(template_id):
        raise TemplateError(f"{where}: template_id must match {_ID.pattern}")
    match = data.get("match")
    if not isinstance(match, dict) or set(match) - set(MATCH_KEYS) or not {"domain", "class"} <= set(match):
        raise TemplateError(f"{where}: match needs domain and class, and only {MATCH_KEYS}")
    if match["domain"] not in domains:
        raise TemplateError(f"{where}: unknown domain {match['domain']!r}")
    if match["class"] not in classes:
        raise TemplateError(f"{where}: unknown class {match['class']!r}")
    if "kind" in match and (not isinstance(match["kind"], str) or not match["kind"]):
        raise TemplateError(f"{where}: kind must be a non-empty string")
    rule = data.get("rule")
    if not isinstance(rule, dict) or set(rule) != set(RULE_KEYS):
        raise TemplateError(f"{where}: rule must have exactly {RULE_KEYS}")
    if rule["fixer_ref"] is not None:
        raise TemplateError(f"{where}: templates never carry a fixer_ref")
    if rule["review_required"] is not True:
        raise TemplateError(f"{where}: review_required must be true")
    if not isinstance(rule["category"], str) or not _CATEGORY.match(rule["category"]):
        raise TemplateError(f"{where}: category must match {_CATEGORY.pattern}")
    if rule["risk"] not in RISKS:
        raise TemplateError(f"{where}: risk must be one of {RISKS}")
    params_from = rule["params_from"]
    if not isinstance(params_from, dict) or not all(isinstance(v, str) and v for v in params_from.values()):
        raise TemplateError(f"{where}: params_from must map detector keywords to dotted change paths")
    if verify:
        problem = detector_params_problem(rule["detector_ref"], params_from, known_detectors)
        if problem:
            raise TemplateError(f"{where}: {problem}")
    if data.get("confidence") not in CONFIDENCES:
        raise TemplateError(f"{where}: confidence must be one of {CONFIDENCES}")
    if data.get("tests") != {"generate_skeleton": True}:
        raise TemplateError(f"{where}: tests must be {{\"generate_skeleton\": true}}")
    if "replacement_suggestion" in data and not isinstance(data["replacement_suggestion"], bool):
        raise TemplateError(f"{where}: replacement_suggestion must be a boolean")
    return data


def load_templates(directory=TEMPLATE_DIR, known_detectors=None, *, verify: bool = True) -> TemplateList:
    """Every template in `directory`, checked, sorted by template_id. Duplicate ids are an error.

    Fails closed: with `verify` (the default) every `detector_ref` must resolve in `known_detectors`, and a missing
    table is an error. Only `verify=False` (tests) skips that check, and the result then has
    `detectors_verified` False."""
    if verify:
        _need_detectors(known_detectors)
    seen = {}
    for path in sorted(Path(directory).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TemplateError(f"{path.name}: cannot read template: {exc}") from None
        template = _check(data, path.name, known_detectors, verify)
        if template["template_id"] in seen:
            raise TemplateError(f"{path.name}: duplicate template_id {template['template_id']}")
        seen[template["template_id"]] = template
    result = TemplateList(seen[key] for key in sorted(seen))
    result.detectors_verified = bool(verify)
    return result


def change_view(change: dict) -> dict:
    """The change plus `subject.key` and `subject.name` (last segment of the subject key)."""
    key = change["subject_key"]
    name = re.split(r"::|\.", key)[-1]
    return {**change, "subject": {"key": key, "name": name}}


def _matches(match: dict, change: dict) -> bool:
    return all(change.get(k) == v for k, v in match.items())


def select_template(change: dict, templates) -> dict | None:
    """The single most specific template for `change` (most match keys). Equally specific hits are an error."""
    hits = [t for t in templates if _matches(t["match"], change)]
    if not hits:
        return None
    best = max(len(t["match"]) for t in hits)
    top = [t for t in hits if len(t["match"]) == best]
    if len(top) > 1:
        raise TemplateError("ambiguous templates for one change: " + ", ".join(t["template_id"] for t in top))
    return top[0]


def _resolve(view: dict, path: str):
    node = view
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise TemplateError(f"change has no value at {path!r}")
        node = node[part]
    if not isinstance(node, str) or not node:
        raise TemplateError(f"value at {path!r} must be a non-empty string")
    return node


def build_skeleton(template: dict, change: dict, *, known_detectors, ledger_entry: dict = None,
                   applicability: dict = None) -> dict:
    """A CandidateRule skeleton: DETECT_ONLY, review_required, no fixer, deterministic ids.

    A replacement is named only when the template sets `replacement_suggestion` and `ledger_entry` is a CONFIRMED
    REPLACEMENT_CANDIDATE whose detail carries `replacement`. Otherwise such a template is refused."""
    _check(template, template.get("template_id", "<template>"), known_detectors)
    view = change_view(change)
    params = {key: _resolve(view, path) for key, path in sorted(template["rule"]["params_from"].items())}
    digest = hashlib.sha256(change["change_id"].encode("utf-8") + template["template_id"].encode("utf-8")
                            + canonical_bytes(params)).hexdigest()
    rule = template["rule"]
    suggestion = (f"Review the candidate {change['class']} change to {change['subject_key']} "
                  f"in {change['step']}; no replacement is proposed.")
    if template.get("replacement_suggestion"):
        if not ledger_entry or ledger_entry.get("confirmed") is not True:
            raise TemplateError("a replacement needs a CONFIRMED ledger entry")
        if ledger_entry.get("class") != "REPLACEMENT_CANDIDATE":
            raise TemplateError("a replacement needs a REPLACEMENT_CANDIDATE ledger entry")
        replacement = (ledger_entry.get("detail") or {}).get("replacement")
        if not isinstance(replacement, str) or not replacement:
            raise TemplateError("the confirmed ledger entry carries no replacement")
        suggestion = (f"Candidate: {change['subject_key']} is replaced by {replacement} "
                      f"(confirmed in {ledger_entry['change_id']}). Review before use.")
    return {
        "candidate_id": "CR-" + digest[:16],
        "change_id": change["change_id"],
        "template_id": template["template_id"],
        "rule": {
            "id": f"{change['step']}.{rule['category']}.cand-{digest[:8]}",
            "step": change["step"],
            "category": rule["category"],
            "severity": "INFO",
            "maturity": "DETECT_ONLY",
            "review_required": True,
            "risk": rule["risk"],
            "origin": "GENERATED",
            "evidence": [],
            "detector_ref": rule["detector_ref"],
            "fixer_ref": None,
            "params": params,
            "tests": {},
            "message": f"Candidate ({change['class']}): {change['subject_key']} changed in {change['step']}.",
            "suggestion": suggestion,
        },
        "applicability": {"source_versions": [], "target_versions": [], "file_kinds": [], "modules_scope": [],
                          **(applicability or {})},
        "confidence": template["confidence"],
        "status": "PROPOSED",
        "origin": "DETERMINISTIC",
        "conflicts": [],
    }

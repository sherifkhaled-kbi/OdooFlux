"""Execution side of automated certification (feature 012, plan section 4, addendum A4 and F3.7).

Non-core. A template that binds a fixer is exercised through the LOADER PATH: ``bind_rule`` binds the fixer and its
detector from the bindable module table, ``KnowledgeRule.fix`` runs the bound fixer, and ``apply_edits`` applies the
edits (the same steps ``fixing_transform`` takes in a real run). The certified code is therefore the executed code. A
template that binds no fixer (the disabled and superseded ones, which can never be issued) runs its primitive directly.

The core record logic in ``odooflux.knowledge.update.certification`` never imports this module. The composition root
attaches one instance through ``certification.attach_executor`` (builtins.build_context): a process-wide,
single-assignment slot, so no caller can supply its own certification authority.
"""

import hashlib
import inspect
import json
import sys
from pathlib import Path

from odooflux.core.contracts.records import SEVERITIES
from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.core.orchestrator.knowledge_rules import KnowledgeRule
from odooflux.knowledge.release.canonical import digest_obj
from odooflux.knowledge.update.certification import PROBE_RULE_ID, CHECK_NAMES, CertificationError
from odooflux.parsers.python import document as pydoc
from odooflux.rules.shared.loader import BindingError, bind_rule
from odooflux.transformers import fix_templates as ft

_DEFAULT_SEVERITY = "WARNING"
_DEFAULT_STEP = "python-fix"


def _text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Modules on the path a certified fix takes when it runs (review item 6): the span parser and document model, the edit
# application, the knowledge rule's fix path and the loader's binding. Their source files are part of the identity, so a
# change anywhere on that path changes what the record certifies.
EXECUTED_MODULES = ("odooflux.parsers.python.spans", "odooflux.parsers.python.document", "odooflux.core.engine.edits",
                    "odooflux.core.orchestrator.knowledge_rules", "odooflux.rules.shared.loader")


def _module_digest(name: str) -> str:
    """sha256 of the source file of a module the certified path has loaded (the file as it is on disk). The modules are
    already imported by this file's own imports; a module that is not loaded is an error, never imported here."""
    module = sys.modules.get(name)
    if module is None or not getattr(module, "__file__", None):
        raise ImportError(f"module {name} is not loaded")
    return hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()


class FixCertifier:
    """The operations core certification needs. ``modules`` is the bindable module table (``BINDABLE_MODULES``), the
    same table the loader binds rules from; the composition root passes it in. Holds no other state."""

    def __init__(self, *, modules):
        self._modules = modules

    def eligible(self, rule_row, change_class=None, *, confirmation_verified=False):
        """``(template_id, reason)``; see ``fix_templates.eligible``."""
        return ft.eligible(rule_row, change_class, confirmation_verified=confirmation_verified)

    def _bound_function(self, ref: str):
        module_name, _, func_name = ref.partition(":")
        func = getattr(self._modules.get(module_name), func_name, None)
        if func is None:
            raise CertificationError("fixer_unbound", f"{ref!r} is not in the bindable module table")
        return func

    def transformer_identity(self, template_id: str) -> dict:
        """Qualified name of the bound fixer (or of the primitive, for a template with no fixer) and a sha256 over the
        sources of the fixer, the primitive, the module that holds the primitive (the resolver), and the modules the
        certified run executes through (``EXECUTED_MODULES``: parser, edits, rule fix path, binding) by file digest."""
        spec = ft.template(template_id)
        primitive = getattr(spec.primitive_module, spec.primitive)
        if spec.fixer_ref is None:
            qualified, parts, owners = f"{spec.primitive_module.__name__}.{spec.primitive}", [primitive], []
        else:
            fixer = self._bound_function(spec.fixer_ref)
            qualified, parts = f"{fixer.__module__}.{fixer.__name__}", [fixer, primitive, spec.primitive_module]
            owners = [fixer.__module__]
        try:
            source = "\n".join(inspect.getsource(part) for part in parts)
        except (OSError, TypeError) as exc:
            raise CertificationError("transformer_source_unavailable", f"{spec.template_id}: {exc}") from None
        names = sorted(set(EXECUTED_MODULES) | set(owners) | {spec.primitive_module.__name__})
        try:
            files = {name: _module_digest(name) for name in names}
        except (OSError, ImportError, AttributeError, TypeError) as exc:
            raise CertificationError("transformer_source_unavailable", f"{spec.template_id}: {exc}") from None
        return {"qualified_name": qualified,
                "source_digest": _text_digest(source + "\n" + json.dumps(files, sort_keys=True))}

    def _rule(self, rule_row: dict, spec, params: dict, rule_id: str) -> KnowledgeRule:
        """The rule as the loader binds it: a FIX_ENABLED metadata row built from the certified row."""
        severity = rule_row.get("severity") if rule_row.get("severity") in SEVERITIES else _DEFAULT_SEVERITY
        step = rule_row.get("step") if isinstance(rule_row.get("step"), str) and rule_row.get("step") else _DEFAULT_STEP
        meta = {"id": rule_id, "maturity": "FIX_ENABLED", "review_required": False, "severity": severity,
                "step": step, "detector_ref": spec.detector_refs[0], "fixer_ref": spec.fixer_ref,
                "params": dict(params), "tests": {"positive": "auto-cert", "negative": "auto-cert",
                                                  "idempotence": "auto-cert"}}
        try:
            bound = bind_rule(meta, self._modules)
        except BindingError as exc:
            raise CertificationError("fixer_unbound", str(exc)) from None
        return KnowledgeRule(bound, meta)

    def _edits(self, rule_row: dict, template_id: str, params: dict, rule_id: str, document: Document) -> list:
        spec = ft.template(template_id)
        if spec.fixer_ref is None:  # disabled or superseded: no bound fixer; such a template can never be issued
            return ft.primitive_edits(template_id, pydoc.parse_document(document), rule_id, params)
        return self._rule(rule_row, spec, params, rule_id).fix(document)

    def _apply(self, rule_row: dict, template_id: str, params: dict, rule_id: str, text: str, path: str):
        document = Document.from_bytes(path, text.encode("utf-8"))
        parsed = pydoc.parse_document(document)
        if parsed.parse_error is not None:
            raise CertificationError("fixture_unparsable", f"{path}: {parsed.parse_error}")
        edits = self._edits(rule_row, template_id, params, rule_id, document)
        return edits, apply_edits(document, edits, precedence=[rule_id])

    def exercise(self, rule_row: dict, template_id: str, params: dict) -> dict:
        """Recompute fixtures, outputs and check digests for one rule. Returns a dict with keys
        ``template_version``, ``fixtures``, ``outputs``, ``checks`` and ``problems`` (a list of ``(code, detail)``).
        ``fixtures``, ``outputs`` and ``checks`` are None when the fixtures could not be run."""
        rid = rule_row["id"]
        result = {"template_version": ft.FIX_TEMPLATES_VERSION, "fixtures": None, "outputs": None,
                  "checks": None, "problems": []}
        before, expected, negative = ft.fixtures(template_id, params)
        try:
            pos_edits, pos = self._apply(rule_row, template_id, params, rid, before, "positive.py")
            neg_edits, neg = self._apply(rule_row, template_id, params, rid, negative, "negative.py")
            second_edits, second = self._apply(rule_row, template_id, params, rid, pos.text, "second.py")
            document = Document.from_bytes("conflict.py", before.encode("utf-8"))
            rule_edits = self._edits(rule_row, template_id, params, rid, document)
            probe_edits = self._edits(rule_row, template_id, params, PROBE_RULE_ID, document)
            combined = apply_edits(document, rule_edits + probe_edits, precedence=[rid, PROBE_RULE_ID])
        except CertificationError as exc:
            result["problems"] = [(exc.code, exc.detail)]
            return result

        fixtures = {"positive_before_digest": _text_digest(before),
                    "positive_expected_digest": _text_digest(expected),
                    "negative_digest": _text_digest(negative)}
        outputs = {"positive_output_digest": _text_digest(pos.text),
                   "negative_output_digest": _text_digest(neg.text),
                   "second_pass_digest": _text_digest(second.text)}

        positive_ok = (pos.text == expected and len(pos.applied) >= 1 and not pos.rejected and pos.preserved_ok)
        negative_ok = (neg.text == negative and not neg_edits and not neg.applied and not neg.rejected)
        idempotent_ok = (not second_edits and second.text == pos.text)
        conflict_ok = (combined.text == pos.text and combined.preserved_ok
                       and len(combined.applied) == len(rule_edits) and len(combined.rejected) == len(probe_edits)
                       and all(e.rule_id == rid for e in combined.applied)
                       and all(e.rule_id == PROBE_RULE_ID for e in combined.rejected))
        regression_ok = positive_ok and negative_ok

        observed = {
            "positive": {"input": _text_digest(before), "output": _text_digest(pos.text),
                         "expected": _text_digest(expected), "applied": len(pos.applied),
                         "rejected": len(pos.rejected)},
            "negative": {"input": _text_digest(negative), "output": _text_digest(neg.text),
                         "applied": len(neg.applied), "rejected": len(neg.rejected)},
            "idempotence": {"output": _text_digest(second.text), "edits": len(second_edits)},
            "conflict": {"single": _text_digest(pos.text), "combined": _text_digest(combined.text),
                         "applied": len(combined.applied), "rejected": len(combined.rejected),
                         "rule_edits": len(rule_edits), "probe_edits": len(probe_edits)},
            "regression": {"template_id": template_id, "template_version": ft.FIX_TEMPLATES_VERSION,
                           "fixtures": fixtures, "outputs": outputs},
        }
        passed = {"positive": positive_ok, "negative": negative_ok, "idempotence": idempotent_ok,
                  "conflict": conflict_ok, "regression": regression_ok}
        result["fixtures"] = fixtures
        result["outputs"] = outputs
        result["checks"] = {name: digest_obj(observed[name]) for name in CHECK_NAMES}
        result["problems"] = [("check_failed", f"{name} check did not pass on recomputation")
                              for name in CHECK_NAMES if not passed[name]]
        return result

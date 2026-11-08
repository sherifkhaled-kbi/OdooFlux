"""L2 RNG view validation (REQ-XML-004, FR-010): modified view archs against the target version's RELAX NG schemas.

lxml is an optional runtime dependency. It is imported inside ``validate_views`` only, never at module import;
when it is missing, or no schema directory is supplied, the result is UNAVAILABLE with a reason. The view type
to RNG file mapping comes from knowledge/compatibility/rng_schemas.json (EV-370). The RNG files are not shipped:
``schema_dir`` is the pinned Odoo source's ``odoo/addons/base/rng`` directory.

Views whose type has no RNG schema for the version (for example ``form``) are not validated and are counted in
the PASS reason. Inherited views (``inherit_id``) are not validated: their architectures are extensions, not
complete views.
"""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from odooflux.core.contracts.records import Finding, ValidationResult
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

RNG_SCHEMAS_FILE = KNOWLEDGE_ROOT / "compatibility" / "rng_schemas.json"
RULE_ID = "rng.view_schema"
_ARCH_MARKER = re.compile(r'name="arch"')


def load_rng_map(target_version: str) -> Optional[dict]:
    """View type -> RNG file name for a version (EV-370), or None when the version has no mapping."""
    if not RNG_SCHEMAS_FILE.is_file():
        return None
    data = json.loads(RNG_SCHEMAS_FILE.read_text(encoding="utf-8"))
    for record in data.get("versions", []):
        if record.get("id") == target_version:
            return dict(record.get("views", {}))
    return None


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def extract_views(document):
    """(view_type, arch_xml, line, inherited) for each ir.ui.view record with an XML arch in one document."""
    text = document.text
    root = ET.fromstring(text.encode("utf-8"))
    arch_lines = [_line_at(text, m.start()) for m in _ARCH_MARKER.finditer(text)]
    out = []
    arch_index = 0
    for record in root.iter("record"):
        fields = {f.get("name"): f for f in record if f.tag == "field"}
        arch = fields.get("arch")
        if arch is None:
            continue
        line = arch_lines[arch_index] if arch_index < len(arch_lines) else 1
        arch_index += 1
        if arch.get("type", "xml") != "xml":
            continue
        inherited = "inherit_id" in fields or record.get("inherit_id") is not None
        child = next((c for c in arch if isinstance(c.tag, str)), None)
        if child is None:
            continue
        out.append((child.tag, ET.tostring(child, encoding="unicode"), line, inherited))
    return out


def available() -> bool:
    """True when the optional lxml extra (``xml``/``rng``) can be imported; lxml is imported lazily here."""
    try:
        import lxml.etree  # noqa: F401
    except ImportError:
        return False
    return True


def _unavailable(reason: str):
    return [], ValidationResult(layer=2, outcome="UNAVAILABLE", reason=reason)


def validate_views(documents, *, target_version: str, schema_dir=None):
    """Return (findings, ValidationResult(layer=2)) for the view archs in *documents* (Document objects)."""
    mapping = load_rng_map(target_version)
    if mapping is None:
        return _unavailable(f"no RNG schema mapping for version {target_version} in rng_schemas.json")
    try:
        from lxml import etree as lxml_etree
    except ImportError:
        return _unavailable("lxml is not installed; RNG view validation is an optional adapter")
    if schema_dir is None:
        return _unavailable("no RNG schema directory supplied (the pinned Odoo source's odoo/addons/base/rng)")

    views, skipped_types, skipped_inherited = [], {}, 0
    for document in documents:
        for view_type, arch, line, inherited in extract_views(document):
            if inherited:
                skipped_inherited += 1
            elif view_type not in mapping:
                skipped_types[view_type] = skipped_types.get(view_type, 0) + 1
            else:
                views.append((document.path, view_type, arch, line))

    validators = {}
    for view_type in sorted({v[1] for v in views}):
        name = mapping[view_type]
        schema_path = Path(schema_dir) / name
        if not schema_path.is_file():
            return _unavailable(f"RNG file {name} not found in schema directory {schema_dir}")
        try:
            validators[view_type] = lxml_etree.RelaxNG(lxml_etree.parse(str(schema_path)))
        except Exception as exc:  # the schema itself does not compile
            return _unavailable(f"cannot compile RNG file {name}: {exc}")

    findings = []
    for path, view_type, arch, line in views:
        rng_name = mapping[view_type]
        try:
            tree = lxml_etree.fromstring(arch.encode("utf-8"))
        except lxml_etree.XMLSyntaxError as exc:
            findings.append(Finding(rule_id=RULE_ID, path=path, line=line, severity="CRITICAL",
                                    message=f"{view_type} view is not well-formed XML: {exc}",
                                    matched=view_type))
            continue
        validator = validators[view_type]
        if not validator.validate(tree):
            errors = "; ".join(entry.message for entry in validator.error_log) or "does not match the schema"
            findings.append(Finding(rule_id=RULE_ID, path=path, line=line, severity="CRITICAL",
                                    message=f"{view_type} view does not match RNG schema {rng_name}: {errors}",
                                    matched=view_type))

    if findings:
        return findings, ValidationResult(layer=2, outcome="FAIL",
                                          reason=f"{len(findings)} view(s) failed RNG validation")
    notes = []
    if skipped_types:
        notes.append("not validated (no RNG schema for these view types): "
                     + ", ".join(f"{t} x{n}" for t, n in sorted(skipped_types.items())))
    if skipped_inherited:
        notes.append(f"inherited views not validated: {skipped_inherited}")
    if not views:
        notes.insert(0, f"no {target_version} tree/list views to validate")
    return [], ValidationResult(layer=2, outcome="PASS", reason="; ".join(notes))

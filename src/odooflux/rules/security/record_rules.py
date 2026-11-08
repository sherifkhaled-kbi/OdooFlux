"""Record rule scanner (REQ-ACL-001, research R-8): ``ir.rule`` records in XML data files.

``scan_record_rules`` extracts each ``ir.rule`` record (XML ID, model reference, ``domain_force`` text, group
references, permission flags). ``flag_unrestricted_global_rules`` is detect-only: a rule without groups whose
domain is empty or ``[(1, '=', 1)]`` grants everything to everyone, which is usually a leftover.
"""

import re
from dataclasses import dataclass

from odooflux.core.engine.documents import Span
from odooflux.parsers.xml import document as xmldoc
from odooflux.rules.shared.emit import finding

_REF = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")
_PERMS = ("perm_read", "perm_write", "perm_create", "perm_unlink")
_UNRESTRICTED = re.compile(r"^\[\s*(\(\s*1\s*,\s*['\"]=['\"]\s*,\s*1\s*\)\s*)?\]$")


@dataclass(frozen=True)
class RecordRule:
    xml_id: str
    span: Span
    model_ref: str
    domain: str
    group_refs: tuple
    perms: dict


def _content(doc, element) -> str:
    if element.end_tag_span is None:
        return ""
    return doc.text[element.start_tag_span.end:element.end_tag_span.start].strip()


def scan_record_rules(document) -> list:
    xdoc = xmldoc.parse(document)
    if xdoc.parse_error is not None:
        return []
    rules = []
    for element in xdoc.elements:
        model = element.get_attr("model")
        if element.tag != "record" or model is None or model.value != "ir.rule":
            continue
        fields = {}
        for index in element.children_index:
            child = xdoc.elements[index]
            name = child.get_attr("name") if child.tag == "field" else None
            if name is not None:
                fields[name.value] = child
        ident = element.get_attr("id")
        model_field = fields.get("model_id")
        ref = model_field.get_attr("ref") if model_field is not None else None
        domain = fields.get("domain_force")
        groups = fields.get("groups")
        eval_attr = groups.get_attr("eval") if groups is not None else None
        perms = {}
        for perm in _PERMS:
            node = fields.get(perm)
            value = node.get_attr("eval") if node is not None else None
            perms[perm] = not (value is not None and value.value.strip() in ("False", "0"))
        rules.append(RecordRule(
            xml_id=ident.value if ident is not None else "",
            span=element.start_tag_span,
            model_ref=ref.value if ref is not None else "",
            domain=_content(xdoc, domain) if domain is not None else "",
            group_refs=tuple(_REF.findall(eval_attr.value)) if eval_attr is not None else (),
            perms=perms))
    return rules


def flag_unrestricted_global_rules(document, ctx):
    """Report global rules (no groups) whose domain is empty or always true."""
    return [finding(document, ctx, rule.span) for rule in scan_record_rules(document)
            if not rule.group_refs and _UNRESTRICTED.match(rule.domain or "[]")]

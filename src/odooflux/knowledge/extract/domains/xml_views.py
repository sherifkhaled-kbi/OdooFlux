"""XML view extractor (T049; REQ-KAP-011; diff-extractor contract, Domains and facts: xml_view).

Handles `.xml` files under a `views/` directory. Each `ir.ui.view` record is one fact keyed by its record id:
`attrs` hold the view's model and inherit_id (signature), and `body_digest` is the canonical digest of the `arch`
subtree (whitespace-insensitive, so reformatting alone is not a change). Element and xpath content is inside that
digest. A top-level element that is not a record, or a record of another model, is `Unsupported`: the file is
UNSUPPORTED and its change reported UNKNOWN, never silently dropped.

Subtrees are read with `parsers/xml` spans and canonicalised with stdlib `ElementTree` (expat); nothing is executed.
"""

import hashlib
import json
import xml.etree.ElementTree as ET

from odooflux.knowledge.extract.driver import ParseFailure, Unsupported, require_toolkit

__all__ = ["XmlViewExtractor", "EXTRACTORS", "canon", "digest", "fragment", "parse_or_fail", "top_level_check",
           "line_of", "child_fields", "field_named", "text_of", "ref_of", "attr_value", "fact", "find"]

TOP_LEVEL_CONTAINERS = ("odoo", "data")


def fact(subject, kind, attrs, body_digest, line):
    return {"subject_key": subject, "kind": kind, "attrs": attrs, "body_digest": body_digest, "line": line}


def fragment(doc, element):
    span = element.span
    try:
        return ET.fromstring(doc.text[span.start:span.end])
    except ET.ParseError as exc:
        raise ParseFailure("PARSE_ERROR", f"element at line {line_of(doc, element)}: {exc}") from exc


def canon(node):
    return [node.tag, sorted(node.attrib.items()), (node.text or "").strip(),
            [canon(child) for child in node], (node.tail or "").strip()]


def digest(node) -> str:
    return hashlib.sha256(json.dumps(canon(node), sort_keys=True).encode("utf-8")).hexdigest()


def find(doc, tag=None, attr=None) -> list:
    """Elements in document order matching `tag` (qualified name) and/or having attribute `attr`."""
    return [e for e in doc.elements if (tag is None or e.tag == tag) and (attr is None or e.get_attr(attr) is not None)]


def parse_or_fail(text: str, path: str, toolkit=None):
    doc = require_toolkit(toolkit).xml_document(text, path=path)
    if doc.parse_error:
        raise ParseFailure("PARSE_ERROR", str(doc.parse_error))
    return doc


def top_level_check(doc) -> None:
    """Every element directly under the root container must be a record; anything else is not modelled."""
    for element in doc.elements:
        if element.parent_index is None:
            continue
        parent = doc.elements[element.parent_index]
        if parent.parent_index is None and parent.tag in TOP_LEVEL_CONTAINERS and element.tag != "record":
            raise Unsupported(f"top-level element <{element.tag}> at line {line_of(doc, element)} is not modelled")


def line_of(doc, element) -> int:
    return doc.text.count("\n", 0, element.span.start) + 1


def attr_value(element, name):
    attr = element.get_attr(name)
    return None if attr is None else attr.value


def child_fields(doc, record) -> list:
    return [e for e in doc.elements if e.parent_index == record.index and e.tag == "field"]


def field_named(doc, record, name):
    for item in child_fields(doc, record):
        if attr_value(item, "name") == name:
            return item
    return None


def text_of(doc, element):
    return (fragment(doc, element).text or "").strip()


def ref_of(element):
    return attr_value(element, "ref")


class XmlViewExtractor:
    domain = "xml_view"
    parser = "xml"

    def handles(self, path: str, toolkit=None) -> bool:
        return toolkit is not None and path.endswith(".xml") and "views" in path.split("/")[:-1]

    def facts(self, text: str, path: str, toolkit=None) -> list:
        doc = parse_or_fail(text, path, toolkit)
        top_level_check(doc)
        out = []
        for record in find(doc, tag="record"):
            if attr_value(record, "model") != "ir.ui.view":
                raise Unsupported(f"record of model {attr_value(record, 'model')} at line {line_of(doc, record)} "
                                  "is not a view")
            record_id = attr_value(record, "id")
            if not record_id:
                raise ParseFailure("PARSE_ERROR", f"view record at line {line_of(doc, record)} has no id")
            arch = field_named(doc, record, "arch")
            if arch is None:
                raise Unsupported(f"view {record_id} has no arch field")
            model = field_named(doc, record, "model")
            inherit = field_named(doc, record, "inherit_id")
            attrs = {"model": text_of(doc, model) if model is not None else None,
                     "inherit_id": ref_of(inherit) if inherit is not None else None}
            out.append(fact(record_id, "view", attrs, digest(fragment(doc, arch)), line_of(doc, record)))
        return out


EXTRACTORS = (XmlViewExtractor(),)

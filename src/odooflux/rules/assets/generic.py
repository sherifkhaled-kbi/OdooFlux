"""Generic asset detectors (REQ-JS-003). Detect-only: the move from XML asset templates (the older series) to manifest
``assets`` bundles is not mechanical (EV-330), so nothing here edits a file.

- ``flag_manifest_key``: a top-level manifest key such as ``qweb`` (read by the older series, EV-124; absent from the newer one, EV-327).
- ``flag_asset_templates``: ``<template inherit_id="<module>.assets_*">`` records that extend a bundle in XML.
"""

import ast
import re

from odooflux.parsers.python import spans as sp
from odooflux.parsers.xml import document as xmldoc
from odooflux.rules.manifest.hygiene import manifest_entries
from odooflux.rules.shared.emit import finding

_BUNDLE = re.compile(r"^[A-Za-z_][\w]*\.assets_[\w]+$")


def flag_manifest_key(document, ctx, *, key):
    """Report the top-level manifest key ``key`` (the key literal is the span)."""
    parsed, entries = manifest_entries(document)
    if entries is None:
        return []
    dict_node = parsed.tree.body[0].value
    return [finding(document, ctx, sp.node_span(parsed, k))
            for k in dict_node.keys if isinstance(k, ast.Constant) and k.value == key]


def flag_asset_templates(document, ctx):
    """Report ``<template>`` elements whose ``inherit_id`` names an asset bundle (``<module>.assets_*``)."""
    xdoc = xmldoc.parse(document)
    if xdoc.parse_error is not None:
        return []
    found = []
    for element in xdoc.elements:
        attr = element.get_attr("inherit_id") if element.tag == "template" else None
        if attr is not None and _BUNDLE.match(attr.value):
            found.append(finding(document, ctx, attr.value_span))
    return found

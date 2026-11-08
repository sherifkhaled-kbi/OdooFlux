"""Generic QWeb rules (REQ-XML-005, REQ-TRF-003).

QWeb templates are XML documents whose directives are ``t-*`` attributes. Detection of a directive uses
``rules.xml.generic.flag_attribute``; this module holds the directive rewrite.
"""

import re

from odooflux.parsers.xml import document as xmldoc
from odooflux.rules.shared.emit import edit

QWEB_VALIDATION = ("xml-wellformed",)
_NAME = re.compile(r"[A-Za-z_][\w.\-]*(:[A-Za-z_][\w.\-]*)?")


def rename_directive(document, ctx, *, old, new):
    """Rename directive attribute ``old`` to ``new``. An element that already carries ``new`` is skipped,
    because renaming would create a duplicate attribute."""
    for name in (old, new):
        if not _NAME.fullmatch(name):
            raise ValueError(f"invalid attribute name {name!r}")
    if old == new:
        return []
    xdoc = xmldoc.parse(document)
    if xdoc.parse_error is not None:
        return []
    return [edit(document, ctx, element.get_attr(old).name_span, new, op="rename_directive",
                 validation=QWEB_VALIDATION)
            for element in xdoc.elements
            if element.get_attr(old) is not None and element.get_attr(new) is None]

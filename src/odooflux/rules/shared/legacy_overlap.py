"""Where a knowledge rule and a legacy table row report the same construct (WS-E, 006 legacy_disposition).

The legacy tables still run unchanged (existing results are kept). A knowledge rule listed here is not
emitted on a file line where one of its legacy categories already reported, so the construct appears once.
Only rows that flag the same construct are listed; ``_cr.execute`` % formatting vs ``env-shortcuts`` and
similar near neighbours are different constructs and stay separate. Every id is checked against the
disposition table in ``tests/unit/test_knowledge_rule_selection.py``. Retiring a legacy row is a separate,
human-reviewed decision (FHR WSE-001); nothing is retired here.
"""

LEGACY_CATEGORIES = {
    "12-13.python.api-multi-removed": ("Deprecated Decorator",),
    "12-13.python.api-one-removed": ("Deprecated Decorator",),
    "18-19.python.api-returns-removed": ("Deprecated Decorator", "Returns Semantics (review)"),
    "12-13.python.sudo-user-argument": ("Sudo API Changed",),
    "18-19.python.osv-deprecated": ("Legacy Import",),
    "16-17.python.message-post-with-template": ("Mail API",),
    "16-17.python.warning-exception": ("Removed Exception: Warning", "Raise Warning"),
    "16-17.xml.attrs-removed": ("Attrs Attribute", "Page Attrs"),
    "16-17.xml.states-attribute-removed": ("States Attribute",),
    "16-17.xml.act-window-tag": ("Shorthand Tag",),
    "17-18.xml.tree-to-list": ("Tree Tag Renamed",),
    "*.manifest.not-installable": ("Not Installable",),
    "16-17.js.odoo-define-legacy-form": ("Legacy JS Module", "Legacy Require"),
    "17-18.js.legacy-widget-removed": ("Legacy Widget",),
    "17-18.js.rpc-service-removed": ("AJAX Call",),
}


# Overlap categories whose legacy rows are disposition-retire (WSE-001). They still report, but they never
# suppress a knowledge rule: the knowledge rule is the better-evidenced finding on that line.
RETIRED_CATEGORIES = frozenset({"Page Attrs"})


def covered(rule_id: str, line: int, legacy_lines: dict) -> bool:
    """True when a legacy category that overlaps ``rule_id`` already reported on ``line``.
    ``legacy_lines`` maps a legacy category to the set of lines it reported in the file.
    Retired categories are not counted."""
    return any(line in legacy_lines.get(category, ())
               for category in LEGACY_CATEGORIES.get(rule_id, ()) if category not in RETIRED_CATEGORIES)

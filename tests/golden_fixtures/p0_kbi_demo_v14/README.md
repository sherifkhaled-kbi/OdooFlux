# Golden fixture: `p0_kbi_demo_v14`

Input-only copy of the reproduction module from
[the audit, Appendix A](../../../docs/reviews/ODOO_MODULE_UPGRADER_AUDIT.md#appendix-a--reproduction-fixture-kbi_demo-v14).
Copy it before use; tests never modify this directory. Module name when copied: `kbi_demo`.

Baseline on the unpatched script (`--from-version 14`): 25 issues, exit 2, and `__manifest__.py`
created in the module (F-SAFE-1).

## Findings each file triggers

| File | Findings |
|---|---|
| `__openerp__.py` | Manifest Version (INFO, WARNING); the module-level `__openerp__.py` → `__manifest__.py` rename (F-SAFE-1, F-SAFE-5) |
| `models/demo.py` | Removed Exception: Warning (F-PY-*, EV-110); Deprecated Attribute `size=`; Deprecated Decorator `@api.one`, `@api.multi`, `@api.returns`; Raise Warning; Sudo API Changed `.sudo(False)` (F-PY-5) |
| `views/demo_views.xml` | Legacy XML Root `<openerp>`; States Attribute `states=` on a button (F-XML-1, F-XML-4); Attrs Attribute ×2 (F-XML-2); Chatter Tag `oe_chatter`; Chatter Field `message_ids`; Tree Tag Renamed `<tree>`; View Arch / Header Buttons (INFO) |
| `static/src/js/demo.js` | Legacy JS Module, Legacy Require ×2, Legacy Widget, AJAX Call, jQuery Event |
| `security/ir.model.access.csv` | none (ACL row is well-formed) |

Not reported by the current rules (known gaps, tracked in later phases): `name_get`, Python
`states=`, the multi-line `size=`, the `qweb` manifest key, the XML asset template, and the bogus
`kbi_nonexistent_dependency`.

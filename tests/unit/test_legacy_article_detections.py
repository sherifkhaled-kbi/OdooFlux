"""Detection rows derived from the community article "Odoo Migration Decoded" (Part 1), verified against official sources.

Detection only: these rows report findings and never edit a file. Each test pins a row to a source snippet and to the
version pairs it applies to (16->17, 17->18, 18->19, 16->19, 17->19). Official evidence is cited in the rule comments in
rules/shared/legacy_rules.py; the article itself could not be retrieved (HTTP 403).
"""

import unittest

from odooflux.rules.shared.legacy_rules import SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING, scan_content

APPLIES = [(16, 17), (17, 18), (18, 19), (16, 19), (17, 19)]


def _found(text: str, name: str, category: str, from_version: int, to_version: int) -> list:
    return [i for i in scan_content(text, name, from_version, to_version) if i.category == category]


class PythonDetections(unittest.TestCase):
    def test_name_get_is_a_17_deprecation(self):
        # verified-official: 17.0 models.py warns "Since 17.0, deprecated method, read display_name instead".
        text = "class A(models.Model):\n    def name_get(self):\n        return []\n"
        for pair in [(16, 17), (16, 19)]:
            (issue,) = _found(text, "m.py", "name_get Deprecated", *pair)
            self.assertEqual(issue.severity, SEVERITY_WARNING)
            self.assertIn("display_name", issue.message)
        self.assertEqual(_found(text, "m.py", "name_get Deprecated", 17, 18), [])
        self.assertEqual(_found(text, "m.py", "name_get Deprecated", 17, 19), [])

    def test_read_group_is_a_19_deprecation_not_17(self):
        # contradicted for 17: 17.0 and 18.0 source define read_group() with no deprecation; verified-official for 19.0
        # (ORM changelog, Odoo Online 18.2 entry).
        text = "rows = self.read_group(domain, fields, ['x'])\n"
        self.assertEqual(_found(text, "m.py", "read_group Deprecated", 16, 17), [])
        self.assertEqual(_found(text, "m.py", "read_group Deprecated", 17, 18), [])
        for pair in [(18, 19), (16, 19), (17, 19)]:
            (issue,) = _found(text, "m.py", "read_group Deprecated", *pair)
            self.assertEqual(issue.severity, SEVERITY_WARNING)

    def test_read_group_private_api_is_not_reported(self):
        self.assertEqual(_found("rows = self._read_group(domain, ['x'], ['y'])\n", "m.py",
                                "read_group Deprecated", 17, 19), [])

    def test_markup_wrapped_body_is_not_reported_and_plain_html_is_reported_for_17_on(self):
        # verified-official: 16.0 message_post passes body through; 17.0 escapes a plain str body (escape(body)).
        html = "self.message_post(body='<p>Hello</p>')\n"
        markup = "self.message_post(body=Markup('<p>Hello</p>'))\n"
        for pair in [(16, 17), (16, 19)]:
            self.assertEqual(len(_found(html, "m.py", "HTML Body Not Markup", *pair)), 1)
            self.assertEqual(_found(markup, "m.py", "HTML Body Not Markup", *pair), [])
        self.assertEqual(_found(html, "m.py", "HTML Body Not Markup", 17, 18), [])
        self.assertEqual(_found(html, "m.py", "HTML Body Not Markup", 17, 19), [])

    def test_command_from_odoo_fields_is_info_for_every_pair(self):
        # contradicted for CRITICAL/17: 17.0 odoo/__init__.py imports Command from odoo.fields; the path still works.
        text = "from odoo.fields import Command\n"
        for pair in APPLIES + [(15, 16)]:
            (issue,) = _found(text, "m.py", "Command Import Path", *pair)
            self.assertEqual(issue.severity, SEVERITY_INFO)

    def test_post_init_hook_cr_registry_is_critical_for_16_to_17_only(self):
        # verified-official: 16.0 loading.py calls post_init_hook(cr, registry); 17.0 loading.py calls post_init_hook(env).
        old = "def post_init_hook(cr, registry):\n    pass\n"
        new = "def post_init_hook(env):\n    pass\n"
        (issue,) = _found(old, "m.py", "post_init_hook Signature", 16, 17)
        self.assertEqual(issue.severity, SEVERITY_CRITICAL)
        self.assertEqual(_found(old, "m.py", "post_init_hook Signature", 17, 18), [])
        self.assertEqual(_found(old, "m.py", "post_init_hook Signature", 17, 19), [])
        self.assertEqual(_found(old, "m.py", "post_init_hook Signature", 16, 19)[0].severity, SEVERITY_CRITICAL)
        self.assertEqual(_found(new, "m.py", "post_init_hook Signature", 16, 17), [])

    def test_distutils_and_utcnow_are_python_facts_for_every_pair(self):
        # verified-official (Python 3.12 what's new): distutils removed (PEP 632); utcnow() deprecated.
        text = "import distutils.core\nstamp = datetime.utcnow()\n"
        for pair in APPLIES:
            (dist,) = _found(text, "m.py", "distutils Removed", *pair)
            (utc,) = _found(text, "m.py", "utcnow Deprecated", *pair)
            self.assertEqual(dist.severity, SEVERITY_WARNING)
            self.assertEqual(utc.severity, SEVERITY_INFO)

    def test_route_type_json_to_jsonrpc_applies_from_18_target(self):
        # verified-official: 19.0 branch upgrade_code/18.1-02-route-jsonrpc.py rewrites type="json" to "jsonrpc".
        text = "@http.route('/x', type='json', auth='user')\ndef f(self):\n    pass\n"
        self.assertEqual(_found(text, "c.py", "Route type json", 16, 17), [])
        for pair in [(17, 18), (18, 19), (17, 19), (16, 19)]:
            self.assertEqual(len(_found(text, "c.py", "Route type json", *pair)), 1)

    def test_invalidate_cache_and_flush_are_deprecated_before_17(self):
        # verified-official: 16.0 models.py defines both with DeprecationWarning; 17.0 models.py defines neither.
        text = "self.invalidate_cache()\nself.flush()\n"
        for category in ("invalidate_cache Renamed", "flush Renamed"):
            (issue,) = _found(text, "m.py", category, 16, 17)
            self.assertEqual(issue.severity, SEVERITY_WARNING)
            self.assertIn("deprecated in Odoo 16.0", issue.message)
            self.assertEqual(len(_found(text, "m.py", category, 16, 19)), 1)
            self.assertEqual(_found(text, "m.py", category, 17, 18), [])
            self.assertEqual(_found(text, "m.py", category, 17, 19), [])

    def test_render_qweb_pdf_is_info_only_for_16_to_17(self):
        # contradicted: 17.0 ir_actions_report.py defines _render_qweb_pdf with no deprecation notice.
        text = "pdf = self._render_qweb_pdf(report_ref, ids)\n"
        (issue,) = _found(text, "m.py", "_render_qweb_pdf Deprecated", 16, 17)
        self.assertEqual(issue.severity, SEVERITY_INFO)
        self.assertEqual(_found(text, "m.py", "_render_qweb_pdf Deprecated", 17, 18), [])


class XmlDetections(unittest.TestCase):
    def test_t_raw_is_deprecated_for_every_pair(self):
        # verified-official: 17.0, 18.0 and 19.0 QWeb docs: "Deprecated since version 15.0". Still works, so WARNING.
        text = '<span t-raw="html"/>\n'
        for pair in APPLIES:
            (issue,) = _found(text, "v.xml", "t-raw Deprecated", *pair)
            self.assertEqual(issue.severity, SEVERITY_WARNING)

    def test_t_esc_is_info_for_the_18_target_only(self):
        # contradicted: 17.0, 18.0 and 19.0 QWeb docs say t-esc is "Not yet formally deprecated".
        text = '<span t-esc="name"/>\n'
        for pair in [(17, 18), (16, 18)]:
            (issue,) = _found(text, "v.xml", "t-esc Deprecated", *pair)
            self.assertEqual(issue.severity, SEVERITY_INFO)
        for pair in [(16, 17), (17, 19), (18, 19), (16, 19)]:
            self.assertEqual(_found(text, "v.xml", "t-esc Deprecated", *pair), [])

    def test_tree_is_reported_for_18_and_19_targets_only(self):
        # verified-official: 18.0 upgrade_code/17.5-01-tree-to-list.py converts <tree> to <list>.
        text = "<tree><field name='a'/></tree>\n"
        self.assertEqual(_found(text, "v.xml", "Tree Tag Renamed", 16, 17), [])
        self.assertEqual(len(_found(text, "v.xml", "Tree Tag Renamed", 17, 18)), 1)
        self.assertEqual(len(_found(text, "v.xml", "Tree Tag Renamed", 16, 19)), 1)
        self.assertEqual(len(_found(text, "v.xml", "Tree Tag Renamed", 17, 19)), 1)
        self.assertEqual(_found(text, "v.xml", "Tree Tag Renamed", 18, 19), [])

    def test_inline_script_is_18_target_only_and_gate_unverified(self):
        # gate unverified: article claim only.
        text = "<data><script>alert(1)</script></data>\n"
        self.assertEqual(_found(text, "v.xml", "Inline Script in QWeb", 16, 17), [])
        (issue,) = _found(text, "v.xml", "Inline Script in QWeb", 17, 18)
        self.assertEqual(issue.severity, SEVERITY_INFO)
        self.assertIn("unverified", issue.message)
        self.assertEqual(_found(text, "v.xml", "Inline Script in QWeb", 17, 19), [])

    def test_inline_script_negative_t_call_assets_is_not_reported(self):
        text = '<t t-call-assets="web.assets_frontend"/>\n'
        self.assertEqual(_found(text, "v.xml", "Inline Script in QWeb", 17, 18), [])
        self.assertEqual(_found(text, "v.xml", "Inline Script in QWeb", 16, 18), [])

    def test_kanban_box_is_18_target_only_verified_deprecation(self):
        # verified-official: 18.0 kanban_arch_parser.js says "kanban-box" is deprecated in favour of a "card" template.
        text = '<t t-name="kanban-box"><div/></t>\n'
        self.assertEqual(_found(text, "v.xml", "kanban-box Template Renamed", 16, 17), [])
        (issue,) = _found(text, "v.xml", "kanban-box Template Renamed", 17, 18)
        self.assertEqual(issue.severity, SEVERITY_WARNING)
        self.assertIn("deprecated in Odoo 18.0", issue.message)
        self.assertNotIn("unverified", issue.message)
        self.assertEqual(_found(text, "v.xml", "kanban-box Template Renamed", 17, 19), [])


class ManifestAndAssetDetections(unittest.TestCase):
    MANIFEST = "{'name': 'x', 'version': '16.0.1.0.0'}\n"

    def test_missing_license_is_info_for_every_pair(self):
        # contradicted: 17.0 manifest docs give 'license' a default of LGPL-3, so a missing key is not an error.
        for pair in APPLIES:
            (issue,) = _found(self.MANIFEST, "__manifest__.py", "License Missing", *pair)
            self.assertEqual(issue.severity, SEVERITY_INFO)

    def test_present_license_is_not_reported(self):
        text = "{'name': 'x', 'license': 'LGPL-3', 'version': '16.0.1.0.0'}\n"
        for pair in APPLIES:
            self.assertEqual(_found(text, "__manifest__.py", "License Missing", *pair), [])

    def test_scss_import_and_division_are_info_for_every_pair(self):
        # contradicted for Odoo 17.0: its assets compile SCSS with libsass; the Dart Sass deprecations remain real.
        text = "@import 'base';\n.a { width: $x / 2; }\n"
        for pair in APPLIES:
            (imp,) = _found(text, "style.scss", "SCSS @import", *pair)
            (div,) = _found(text, "style.scss", "SCSS Division", *pair)
            self.assertEqual(imp.severity, SEVERITY_INFO)
            self.assertEqual(div.severity, SEVERITY_INFO)

    def test_script_injection_is_18_target_only_and_gate_unverified(self):
        # gate unverified: article claim only.
        text = "const s = document.createElement('script');\n"
        self.assertEqual(_found(text, "w.js", "Script Injection (CSP)", 16, 17), [])
        (issue,) = _found(text, "w.js", "Script Injection (CSP)", 17, 18)
        self.assertEqual(issue.severity, SEVERITY_INFO)
        self.assertIn("unverified", issue.message)
        self.assertEqual(_found(text, "w.js", "Script Injection (CSP)", 17, 19), [])


if __name__ == "__main__":
    unittest.main()

"""TST-009-010 (REQ-REP-003, REQ-REP-006, SC-004): the HTML report has every schema section and no external
resource references, no scripts."""

import re
import unittest
from html.parser import HTMLParser

from ._setup import SRC  # noqa: F401
from .helpers import all_goldens, golden

SECTIONS = ("summary", "plan", "modules", "rejected", "scope", "ai", "recovery")


def render(model):
    from odooflux.reporting.html.html import render_html
    return render_html(model)


class _Scan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.ids, self.refs, self.details, self.attrs = [], set(), [], 0, []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend((tag, k, v, "") for k, v in attrs)
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "details":
            self.details += 1
        for key in ("src", "href", "action", "data", "poster", "srcset", "formaction"):
            if key in attrs:
                self.refs.append((tag, key, attrs[key], attrs.get("class", "")))

    def handle_data(self, data):
        self.text.append(data)


def scan(model):
    page = render(model)
    parser = _Scan()
    parser.feed(page)
    return page, parser


class HtmlTests(unittest.TestCase):
    def test_every_section_and_chrome_present(self):
        for name, model in all_goldens().items():
            page, p = scan(model)
            for section in SECTIONS:
                self.assertIn(section, p.ids, f"{name}: section {section}")
            for tag in ("header", "nav", "footer", "style"):
                self.assertIn(tag, p.tags, f"{name}: <{tag}>")
            self.assertIn("schema_version", " ".join(p.text) + page)
            self.assertIn(model["run"]["run_id"], page)

    def test_no_scripts_no_external_resources(self):
        for name, model in all_goldens().items():
            page, p = scan(model)
            self.assertNotIn("script", p.tags, name)
            for forbidden in ("link", "img", "iframe", "object", "embed", "form", "video", "audio", "base", "meta"):
                if forbidden == "meta":
                    continue  # charset meta is allowed, checked below
                self.assertNotIn(forbidden, p.tags, f"{name}: <{forbidden}>")
            self.assertNotRegex(page, r"url\(", name)
            self.assertNotRegex(page, r"@import", name)
            self.assertEqual([k for t, k, v, c in p.attrs if k.lower().startswith("on")], [], name)
            for tag, key, value, cls in p.refs:
                self.assertEqual(tag, "a", f"{name}: {tag} {key}")
                self.assertEqual(key, "href", name)
                if not value.startswith("#"):
                    self.assertIn("evidence", cls.split(), f"{name}: external link without evidence class {value}")
                    self.assertTrue(value.startswith("https://"), value)

    def test_evidence_links_are_plain_anchors_to_model_urls(self):
        _, p = scan(golden("needs_review"))
        links = [v for t, k, v, c in p.refs if "evidence" in c.split()]
        self.assertIn("https://www.odoo.com/documentation/18.0/developer/reference/backend/views.html", links)

    def test_only_https_evidence_urls_linked(self):
        model = golden("needs_review")
        model["modules"][0]["findings"][0]["evidence"] = [{"id": "EV-X", "url": "javascript:alert(1)"},
                                                          {"id": "EV-Y", "url": "http://insecure.example/x"}]
        page, p = scan(model)
        self.assertEqual([v for t, k, v, c in p.refs if not v.startswith("#")], [])
        self.assertIn("EV-X", page)

    def test_collapsing_uses_details_per_module(self):
        _, p = scan(golden("mixed"))
        self.assertGreaterEqual(p.details, 4)

    def test_scope_honesty_unrun_never_pass_and_unavailable_distinct(self):
        page = render(golden("static_validated"))
        self.assertRegex(page, r"(?s)Why not verified.*installation \(L4\).*behaviour \(L5\)")
        self.assertNotRegex(page, r"L4[^<]*PASS")
        mixed = render(golden("mixed"))
        self.assertIn("UNAVAILABLE", mixed)
        self.assertIn('class="outcome unavailable"', mixed)
        self.assertIn('class="outcome fail"', mixed)

    def test_provisional_banner(self):
        self.assertIn('class="provisional"', render(golden("provisional")))
        self.assertIn("PROVISIONAL", render(golden("provisional")))
        self.assertNotIn('class="provisional"', render(golden("static_validated")))

    def test_ai_runtime_recovery_content(self):
        self.assertIn("anthropic/&lt;configured-model&gt;", render(golden("ai_enabled")))
        self.assertIn("odoo:18.0", render(golden("install_verified")))
        self.assertIn("odooflux rollback run-golden", render(golden("install_verified")))
        self.assertIn("nothing was written", render(golden("static_validated")))

    def test_deterministic(self):
        self.assertEqual(render(golden("mixed")), render(golden("mixed")))

    def test_declares_utf8_and_is_self_contained_document(self):
        page = render(golden("mixed"))
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn('<meta charset="utf-8">', page)


if __name__ == "__main__":
    unittest.main()

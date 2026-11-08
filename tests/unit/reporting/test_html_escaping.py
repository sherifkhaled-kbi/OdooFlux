"""TST-009-011 (REQ-REP-003, REQ-SEC-004, FR-008): untrusted text is inert in the HTML report."""

import copy
import re
import unittest
from html.parser import HTMLParser

from ._setup import SRC  # noqa: F401
from .helpers import golden

ALLOWED_TAGS = {"html", "head", "meta", "title", "style", "body", "header", "nav", "main", "section", "footer", "h1",
                "h2", "h3", "p", "div", "span", "a", "ul", "li", "table", "thead", "tbody", "tr", "th", "td",
                "details", "summary", "code", "pre", "strong", "em", "br", "ol"}
PAYLOADS = ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>', "'><svg onload=alert(1)>",
            "</td></tr></table><iframe src=//evil></iframe>", "javascript:alert(1)", "{{7*7}}${7*7}",
            "<!-- comment --><style>*{background:url(//evil)}</style>"]


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.attrs = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)


def hostile_model(payload):
    model = copy.deepcopy(golden("mixed"))
    model["run"]["run_id"] = payload
    model["run"]["source"] = payload
    for m in model["modules"]:
        m["name"] = payload
        m["path"] = payload
        m["status_reasons"] = [payload]
        m["rejections"] = [payload]
        for f in m["findings"]:
            f.update(message=payload, suggestion=payload, rule_id=payload, path=payload,
                     rejection_reason=payload, evidence=[payload, {"id": payload, "url": "https://ok.example/" + payload}])
    model["verification_scope"]["limits"] = [payload]
    model["verification_scope"]["reasons"] = {"L4": payload}
    model["recovery"]["run_log"] = payload
    model["recovery"]["rollback_cmd"] = payload
    model["ai_usage"] = {"enabled": True, "consent": True, "providers": [
        {"name": payload, "model": payload, "requests": 1}], "budget_events": [payload], "totals": {}}
    model["provisional"] = {"active": True, "labels": [payload]}
    model["warnings"] = [payload]
    return model


class HtmlEscapingTests(unittest.TestCase):
    def test_payloads_render_inert(self):
        from odooflux.reporting.html.html import render_html
        for payload in PAYLOADS:
            page = render_html(hostile_model(payload))
            parser = _Tags()
            parser.feed(page)
            self.assertLessEqual(set(parser.tags), ALLOWED_TAGS, payload)
            for key, value in parser.attrs:
                self.assertFalse(key.startswith("on"), (payload, key))
                self.assertFalse((value or "").lower().lstrip().startswith(("javascript:", "data:", "vbscript:")), payload)
            self.assertNotRegex(page, r"(?i)<script|<img|<iframe|<svg|onerror=\"|<!-- comment")
            self.assertNotIn("<style>*{", page)

    def test_escaped_forms_visible(self):
        from odooflux.reporting.html.html import render_html
        page = render_html(hostile_model('<script>alert(1)</script>'))
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_quotes_cannot_break_attributes(self):
        from odooflux.reporting.html.html import render_html
        page = render_html(hostile_model('" onmouseover="alert(1)'))
        parser = _Tags()
        parser.feed(page)
        self.assertFalse([k for k, v in parser.attrs if k.startswith("on")])

    def test_control_characters_neutralised(self):
        from odooflux.reporting.html.html import render_html
        page = render_html(golden("hostile"))
        self.assertIsNone(re.search(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", page))
        self.assertIn("&lt;U+001B&gt;", page)

    def test_json_excerpt_never_unescaped(self):
        from odooflux.reporting.html.html import render_html
        page = render_html(golden("hostile"))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x", page)


if __name__ == "__main__":
    unittest.main()

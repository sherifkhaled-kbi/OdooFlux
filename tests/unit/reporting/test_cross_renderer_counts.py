"""TST-009-002 (REQ-REP-001, REQ-REP-006, SC-002): counts shown by terminal, HTML, JSON and SARIF equal the
model's, which equal an independent recount of the model's findings."""

import json
import re
import unittest
from html.parser import HTMLParser

from ._setup import SRC  # noqa: F401
from .helpers import all_goldens

OPEN = ("OPEN", "NEEDS_REVIEW")


def recount(model):
    """Recount from module findings only (never from model['summary'])."""
    c = {"findings": 0, "fixed": 0, "rejected": 0, "needs_review": 0, "open": 0,
         "critical": 0, "warning": 0, "info": 0, "sarif": 0}
    per_module = {}
    for m in model["modules"]:
        pm = {"c": 0, "w": 0, "i": 0, "fixed": 0, "rejected": 0}
        for f in m["findings"]:
            c["findings"] += 1
            st = f["status"]
            if st == "FIXED":
                c["fixed"] += 1; pm["fixed"] += 1
            elif st == "REJECTED":
                c["rejected"] += 1; pm["rejected"] += 1
            elif st == "NEEDS_REVIEW":
                c["needs_review"] += 1
            if st in OPEN:
                c["open"] += 1
                c[f["severity"].lower()] += 1
                pm[f["severity"][0].lower()] += 1
            if st != "FIXED":
                c["sarif"] += 1
        per_module[m["name"]] = pm
    return c, per_module


class _Metrics(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metrics = {}
        self._key = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-metric" in attrs:
            self._key = attrs["data-metric"]

    def handle_data(self, data):
        if self._key:
            self.metrics[self._key] = int(data.strip())
            self._key = None


def terminal_counts(text):
    m = re.search(r"TOTALS modules=(\d+) findings=(\d+) open=(\d+) \(critical=(\d+) warning=(\d+) info=(\d+)\) "
                  r"fixed=(\d+) rejected=(\d+) needs_review=(\d+)", text)
    assert m, text
    keys = ("modules", "findings", "open", "critical", "warning", "info", "fixed", "rejected", "needs_review")
    return dict(zip(keys, map(int, m.groups())))


class CrossRendererTests(unittest.TestCase):
    def test_model_summary_equals_recount(self):
        for name, model in all_goldens().items():
            c, _ = recount(model)
            s = model["summary"]
            self.assertEqual(s["findings_by_status"]["fixed"], c["fixed"], name)
            self.assertEqual(s["findings_by_status"]["rejected"], c["rejected"], name)
            self.assertEqual(sum(s["findings"].values()), c["findings"], name)
            self.assertEqual(sum(s["open_findings"].values()), c["open"], name)

    def test_terminal_equals_model(self):
        from odooflux.reporting.options import RendererOptions
        from odooflux.reporting.terminal.ansi import render_terminal
        for name, model in all_goldens().items():
            c, per = recount(model)
            for color in ("always", "never"):
                text = render_terminal(model, RendererOptions(color=color, width=120))
                got = terminal_counts(re.sub(r"\x1b\[[0-9;]*m", "", text))
                self.assertEqual((got["findings"], got["open"], got["critical"], got["warning"], got["info"],
                                  got["fixed"], got["rejected"], got["needs_review"], got["modules"]),
                                 (c["findings"], c["open"], c["critical"], c["warning"], c["info"],
                                  c["fixed"], c["rejected"], c["needs_review"], len(model["modules"])), name)
                plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
                for module, pm in per.items():
                    row = re.search(rf"^ *\S+ +{re.escape(module)} +(\d+)/(\d+)/(\d+) +(\d+) +(\d+) ", plain, re.M)
                    self.assertTrue(row, f"{name}: no row for {module}")
                    self.assertEqual(tuple(map(int, row.groups())),
                                     (pm["c"], pm["w"], pm["i"], pm["fixed"], pm["rejected"]), (name, module))

    def test_html_equals_model(self):
        from odooflux.reporting.html.html import render_html
        for name, model in all_goldens().items():
            c, _ = recount(model)
            p = _Metrics()
            p.feed(render_html(model))
            for key, expected in (("findings", c["findings"]), ("open", c["open"]), ("open_critical", c["critical"]),
                                  ("open_warning", c["warning"]), ("open_info", c["info"]),
                                  ("fixed", c["fixed"]), ("rejected", c["rejected"]),
                                  ("needs_review", c["needs_review"]), ("modules", len(model["modules"]))):
                self.assertEqual(p.metrics.get(key), expected, f"{name}:{key}")

    def test_sarif_equals_model(self):
        from odooflux.reporting.exporters.sarif import export_sarif
        for name, model in all_goldens().items():
            c, _ = recount(model)
            doc = json.loads(export_sarif(model))
            results = doc["runs"][0]["results"]
            self.assertEqual(len(results), c["sarif"], name)
            levels = [r["level"] for r in results if r["properties"]["status"] in ("OPEN", "NEEDS_REVIEW")]
            self.assertEqual(levels.count("error"), c["critical"], name)
            self.assertEqual(levels.count("warning"), c["warning"], name)
            self.assertEqual(levels.count("note"), c["info"], name)
            self.assertEqual(sum(1 for r in results if r["properties"]["status"] == "REJECTED"),
                             c["rejected"], name)
            with_fixed = json.loads(export_sarif(model, include_fixed=True))["runs"][0]["results"]
            self.assertEqual(len(with_fixed), c["findings"], name)


if __name__ == "__main__":
    unittest.main()

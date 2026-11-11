"""TST-009-008 (REQ-REP-001, REQ-ARC-004, D-10): legacy JSON from the model matches the characterised legacy
fields (the P1 characterisation, as produced by the existing legacy writer) and announces its deprecation."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ._setup import SRC  # noqa: F401
from . import fixtures
from .helpers import build

VOLATILE = ("timestamp", "elapsed_seconds", "total_elapsed_seconds")


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        items = [_strip(v) for v in obj]
        if items and isinstance(items[0], dict) and "file" in items[0]:  # the model orders findings; legacy did not
            items.sort(key=lambda i: (i["file"], i["line"], i["category"], i["message"]))
        return items
    return obj


def _reference(name):
    """What the existing legacy writer produces for the same run state."""
    from odooflux.core.orchestrator.run import reports_from_state
    from odooflux.reporting.model.legacy_json import save_combined_json_report, save_json_report
    state, _ = fixtures.scenarios()[name]
    reports = reports_from_state(state)
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        out = Path(tmp) / "r.json"
        if len(reports) == 1:  # the CLI passes the run-state record and the run mode (PA-6: reversible per mode)
            save_json_report(reports[0], out, entry=state["modules"][0], mode=state["mode"])
        else:
            save_combined_json_report(reports, out, entries=state["modules"], mode=state["mode"])
        return json.loads(out.read_text(encoding="utf-8"))


class LegacyJsonTests(unittest.TestCase):
    def test_parity_with_legacy_writer_for_every_scenario(self):
        from odooflux.reporting.exporters.legacy_json import export_legacy_json
        for name in fixtures.scenarios():
            got = json.loads(export_legacy_json(build(name)))
            want = _reference(name)
            self.assertEqual(_strip(got), _strip(want), name)

    def test_single_and_combined_shapes(self):
        from odooflux.reporting.exporters.legacy_json import export_legacy_json
        single = json.loads(export_legacy_json(build("failed")))
        self.assertIn("module_path", single)
        self.assertIn("issues", single)
        combined = json.loads(export_legacy_json(build("mixed")))
        self.assertEqual(combined["total_modules"], 4)

    def test_deprecation_notice_defined_and_mentions_window(self):
        from odooflux.reporting.exporters.legacy_json import DEPRECATION_NOTICE
        self.assertIn("deprecated", DEPRECATION_NOTICE.lower())
        self.assertIn("--report-format json", DEPRECATION_NOTICE)

    def test_registry_entry_prints_nothing_but_exposes_notice(self):
        from odooflux.reporting.exporters.legacy_json import LegacyJsonRenderer
        renderer = LegacyJsonRenderer()
        self.assertEqual(renderer.key, "legacy-json")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            renderer.render(build("failed"))
        self.assertEqual(buffer.getvalue(), "")


if __name__ == "__main__":
    unittest.main()

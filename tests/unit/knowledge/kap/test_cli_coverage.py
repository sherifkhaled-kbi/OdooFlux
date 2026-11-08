"""T069 (REQ-KAP-032, REQ-KAP-034, REQ-KAP-035): `odooflux knowledge coverage show|gates`.

The fixtures come from test_coverage_manifest (real ledger and accounting). Each case writes a manifest and its recompute
inputs into a temp directory and runs the CLI through `knowledge.main`, the same entry point the tool uses.
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from odooflux.cli import knowledge
from odooflux.knowledge.release.canonical import canonical_bytes
from tests.unit.knowledge.kap.test_coverage_manifest import _build, _data, _resigned


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = knowledge.main(argv)
        except SystemExit as exc:  # argparse usage errors
            code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue(), err.getvalue()


class CoverageCliCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, manifest, data, name="pkg"):
        root = self.root / name
        (root / "coverage").mkdir(parents=True, exist_ok=True)
        (root / "coverage" / "coverage-manifest.json").write_bytes(canonical_bytes(manifest))
        if data is not None:
            (root / "coverage" / "inputs.json").write_bytes(canonical_bytes(data))
        return str(root)

    def show(self, path, *extra):
        return _run(["coverage", "show", "--path", path, *extra])

    def gates(self, path, *extra):
        return _run(["coverage", "gates", "--path", path, *extra])


class TestShow(CoverageCliCase):
    def test_show_prints_fractions(self):
        data = _data()
        path = self.write(_build(data), data)
        code, out, err = self.show(path)
        self.assertEqual(code, 0, err)
        metric_lines = [line for line in out.splitlines() if re.match(r"^M[1-8] ", line)]
        self.assertEqual(len(metric_lines), 8)
        self.assertTrue(all("/" in line or "n/a" in line for line in metric_lines), metric_lines)
        self.assertIn("M2 file_scan  2/2", out)
        self.assertIn("M5 evidence  1/1", out)
        self.assertIn("completeness COMPLETE", out)

    def test_show_has_no_combined_score(self):
        data = _data()
        code, out, _ = self.show(self.write(_build(data), data))
        self.assertEqual(code, 0)
        self.assertNotIn("score", out.lower())

    def test_zero_denominator_prints_na(self):
        data = _data()
        data["declared_transitions"] = []
        code, out, _ = self.show(self.write(_build(data), data))
        self.assertEqual(code, 0)
        self.assertIn("M8 version_transition  n/a", out)

    def test_show_json_is_canonical(self):
        data = _data()
        code, out, _ = self.show(self.write(_build(data), data), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(out.strip(), canonical_bytes(payload).decode("utf-8"))
        self.assertEqual([m["id"] for m in payload["metrics"]], [f"M{i}" for i in range(1, 9)])

    def test_quiet_prints_nothing(self):
        data = _data()
        code, out, _ = self.show(self.write(_build(data), data), "--quiet")
        self.assertEqual((code, out), (0, ""))


class TestGates(CoverageCliCase):
    def test_gates_lists_every_gate_and_completeness(self):
        data = _data()
        code, out, _ = self.gates(self.write(_build(data), data))
        self.assertEqual(code, 0)
        for gate_id in ("G-SRC", "G-FILES", "G-CLASS", "G-DISP", "G-EVID", "G-MANIFEST", "G-RULES", "G-SAFE",
                        "G-XCHECK", "G-SECRETS"):
            self.assertIn(gate_id, out)
        self.assertIn("completeness COMPLETE (claimed COMPLETE)", out)

    def test_exit1_on_failed(self):
        data = _data()
        data["redaction_findings"] = None  # G-SECRETS cannot run: FAILED
        path = self.write(_build(data), data)
        code, out, _ = self.gates(path)
        self.assertEqual(code, 1)
        self.assertIn("completeness FAILED", out)
        self.assertEqual(self.show(path)[0], 1)

    def test_partial_prints_limits_and_exits_0(self):
        data = _data()
        files = data["accounting"][0]["files"]
        files[0]["state"], files[0]["reason_code"] = "UNSUPPORTED", "NO_PARSER"
        totals = data["accounting"][0]["totals"]
        totals["ANALYZED"], totals["UNSUPPORTED"] = totals["ANALYZED"] - 1, totals["UNSUPPORTED"] + 1
        limit = "G-FILES FAIL: one unsupported file (NO_PARSER) is listed in the manifest"
        path = self.write(_build(data, limits=[limit]), data)
        code, out, err = self.gates(path)
        self.assertEqual(code, 0, err)
        self.assertIn("completeness PARTIAL (claimed PARTIAL)", out)
        self.assertIn(f"limit {limit}", out)

    def test_inconsistent_manifest_exits_1(self):
        data = _data()
        manifest = _build(data)
        for item in manifest["metrics"]:
            if item["id"] == "M2":
                item["numerator"] = 1
        path = self.write(_resigned(manifest), data)
        code, out, _ = self.gates(path)
        self.assertEqual(code, 1)
        self.assertIn("INCONSISTENT M2 differs", out)
        self.assertEqual(self.show(path)[0], 1)

    def test_gates_json_is_canonical(self):
        data = _data()
        code, out, _ = self.gates(self.write(_build(data), data), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(out.strip(), canonical_bytes(payload).decode("utf-8"))
        self.assertEqual(payload["completeness"], "COMPLETE")
        self.assertEqual(payload["consistency_findings"], [])


class TestInputs(CoverageCliCase):
    def test_missing_inputs_is_usage_error(self):
        data = _data()
        path = self.write(_build(data), None)
        code, _, err = self.gates(path)
        self.assertEqual(code, 2)
        self.assertIn("coverage inputs not found", err)

    def test_missing_manifest_is_usage_error(self):
        code, _, err = self.show(str(self.root / "nothing-here"))
        self.assertEqual(code, 2)
        self.assertIn("coverage manifest not found", err)


if __name__ == "__main__":
    unittest.main()

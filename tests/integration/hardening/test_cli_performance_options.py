"""T012/T013 (REQ-PRF-002, REQ-PRF-003): `--jobs N` and `--incremental` through the CLI."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from . import _support as sup
from odooflux.builtins import main


def cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main([str(a) for a in args])
    return code, out.getvalue(), err.getvalue()


def stripped(report_path):
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    text = json.dumps(data, sort_keys=True)
    return text


class CliPerformanceOptionTests(unittest.TestCase):
    def setUp(self):
        self.corpus = sup.copy_corpus(4)
        self.state = Path(tempfile.mkdtemp())

    def args(self, *extra, report=None):
        base = ["--addons-path", self.corpus, "--from-version", "14", "--no-color", "--state-dir", self.state,
                "--fail-on", "none"]
        if report:
            base += ["--report-format", "json", "--report", report]
        return base + list(extra)

    def test_jobs_option_gives_the_same_report_as_serial(self):
        tmp = Path(tempfile.mkdtemp())
        self.assertEqual(cli(*self.args(report=tmp / "a.json"))[0], 0)
        self.assertEqual(cli(*self.args("--jobs", "3", report=tmp / "b.json"))[0], 0)
        a, b = (json.loads((tmp / n).read_text(encoding="utf-8")) for n in ("a.json", "b.json"))
        for report in (a, b):
            report["run"].pop("run_id", None)
            report["recovery"].pop("run_log", None)
            report["recovery"].pop("rollback_cmd", None)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_jobs_zero_means_all_cpus_and_negative_is_a_usage_error(self):
        self.assertEqual(cli(*self.args("--jobs", "0"))[0], 0)
        code, _, err = cli(*self.args("--jobs", "-2"))
        self.assertEqual(code, 2)
        self.assertIn("--jobs", err)

    def test_jobs_with_fix_runs_serially_and_says_so(self):
        code, out, err = cli(*self.args("--fix", "--jobs", "4"))
        self.assertIn(code, (0, 1, 3, 4))
        self.assertIn("serial", out + err)

    def test_incremental_second_run_skips_every_module(self):
        code, out, _ = cli(*self.args("--incremental"))
        self.assertEqual(code, 0)
        self.assertIn("Incremental: 4 analysed, 0 skipped", out)
        code, out, _ = cli(*self.args("--incremental"))
        self.assertIn("Incremental: 0 analysed, 4 skipped", out)


if __name__ == "__main__":
    unittest.main()

"""TST-003-029 (REQ-ARC-004, SC-001): every difference listed in docs/changes/P2_CUTOVER.md is observed."""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from odooflux.core.orchestrator.status import decide_status

from .helpers import FIXTURE, make_module, new_tmp, run_cli_main

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "changes" / "P2_CUTOVER.md"


def _rows():
    text = DOC.read_text(encoding="utf-8")
    block = text[text.index("<!-- differences:start -->"):text.index("<!-- differences:end -->")]
    rows = re.findall(r"^\| (D\d+) \| (.+?) \| (\w+) \|$", block, flags=re.M)
    return [{"id": i, "description": d, "check": c} for i, d, c in rows]


def _check_analyze_creates_state():
    root = new_tmp()
    state = root / "state"
    module = make_module(root, "kbi_demo")
    run_cli_main(["--module", module, "--from-version", "14", "--no-color", "--state-dir", state])
    return (state / "runs").exists() and any((r / "state.json").exists() for r in (state / "runs").iterdir())


def _check_tool_failure_is_blocked():
    status, _ = decide_status({1: "PASS", 2: "PASS"}, tool_ok=False)
    return status == "BLOCKED"


def _check_l3_clean_passes():
    root = new_tmp()
    module = root / "clean"
    module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'clean', 'version': '1.0', 'depends': ['base']}\n", encoding="utf-8")
    (module / "models.py").write_text("x = 1\n", encoding="utf-8")
    report = root / "r.json"
    code, _ = run_cli_main(["--module", module, "--from-version", "14", "--no-color", "--report-format", "json",
                            "--report", report, "--state-dir", root / "state"])
    module_result = json.loads(report.read_text(encoding="utf-8"))["modules"][0]
    return code == 0 and module_result["layers"]["L3"]["outcome"] == "PASS" and module_result["status_row"] != 1


def _check_console_entry_point():
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    return 'odooflux = "odooflux.builtins:main"' in text


def _check_tool_error_exit_4():
    code, _ = run_cli_main(["--module", new_tmp() / "missing", "--from-version", "14", "--no-color"])
    return code == 4


def _check_to_version_not_fixed():
    code, out = _run_subprocess(["migrate", "--help"])
    return code == 0 and "{18,19}" not in out


def _check_usage_error_exit_2():
    code, _ = run_cli_main(["--module", FIXTURE, "--from-version", "19", "--to-version", "14", "--no-color"])
    return code == 2


def _check_api_key_warning():
    root = new_tmp()
    module = make_module(root, "kbi_demo")
    _code, out = run_cli_main(["--module", module, "--from-version", "14", "--no-color",
                               "--api-key", "x", "--state-dir", root / "state"])
    return "deprecated" in out


CHECKS = {f.__name__.replace("_check_", ""): f for f in [
    _check_analyze_creates_state, _check_tool_failure_is_blocked, _check_l3_clean_passes,
    _check_console_entry_point, _check_tool_error_exit_4, _check_to_version_not_fixed,
    _check_usage_error_exit_2, _check_api_key_warning]}


def _run_subprocess(args):
    proc = subprocess.run([sys.executable, str(REPO / "odooflux.py"), *args],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
    return proc.returncode, proc.stdout


class CutoverDifferencesTests(unittest.TestCase):
    def test_every_listed_difference_is_observed(self):
        rows = _rows()
        self.assertEqual([r["id"] for r in rows], [f"D{i}" for i in range(1, len(rows) + 1)])
        failures = []
        for row in rows:
            check = CHECKS.get(row["check"])
            if check is None:
                failures.append(f"{row['id']}: no check named {row['check']}")
            elif not check():
                failures.append(f"{row['id']}: not observed ({row['description']})")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()

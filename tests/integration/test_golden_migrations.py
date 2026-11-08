"""TST-006-006 (REQ-TST-003, FR-014): golden-migration harness.

Layout (data-model.md, Golden fixture layout)::

    tests/golden_fixtures/<source>/<module>/                   source module (e.g. 17.0/kbi_sales)
    tests/golden_fixtures/<source>/<module>/expected/<target>/tree/     expected files after migration
    tests/golden_fixtures/<source>/<module>/expected/<target>/report.json  expected normalised report

``<source>`` and ``<target>`` are ``M.0`` version names. Each case copies the source module (without its
``expected`` directory) into a temporary work area, runs a write-mode migration into a temporary state
directory, and compares the normalised report and the resulting tree with the expected files byte for byte.
With no fixtures the harness runs zero cases and passes; ``test_mismatched_sample_is_reported`` proves that
a mismatch fails.
"""

import json
import re
import shutil
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from odooflux.core.orchestrator.provisional import provisional_for
from .helpers import FIXTURE, normalised_report, start_run

GOLDEN = Path(__file__).resolve().parents[1] / "golden_fixtures"
_VERSION = re.compile(r"^\d+\.0$")


@dataclass(frozen=True)
class GoldenCase:
    source: str
    target: str
    module: Path
    expected: Path  # expected/<target>

    @property
    def name(self) -> str:
        return f"{self.source}/{self.module.name}->{self.target}"


def _version_dirs(parent: Path):
    return sorted(p for p in parent.iterdir() if p.is_dir() and _VERSION.match(p.name)) if parent.is_dir() else []


def discover(root: Path = GOLDEN) -> list:
    """Every ``<source>/<module>/expected/<target>`` directory, in sorted order."""
    cases = []
    for source in _version_dirs(root):
        for module in sorted(p for p in source.iterdir() if p.is_dir()):
            for target in _version_dirs(module / "expected"):
                cases.append(GoldenCase(source.name, target.name, module, target))
    return cases


def _files(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def tree_differences(expected: Path, actual: Path) -> list:
    """Human-readable differences between two directory trees, sorted; empty when byte-identical."""
    want, got = _files(expected), _files(actual)
    problems = [f"missing {p}" for p in sorted(want - got)]
    problems += [f"unexpected {p}" for p in sorted(got - want)]
    problems += [f"content differs {p}" for p in sorted(want & got)
                 if (expected / p).read_bytes() != (actual / p).read_bytes()]
    return problems


def run_case(case: GoldenCase, work: Path):
    """Migrate a copy of the source module in write mode. Returns (normalised report, migrated module)."""
    module = work / "module" / case.module.name
    shutil.copytree(case.module, module, ignore=shutil.ignore_patterns("expected"))
    state = work / "state"
    from_v, to_v = int(case.source.split(".")[0]), int(case.target.split(".")[0])
    # The golden corpus is PROVISIONAL (ADR-019): label the run the way the CLI does for a marked corpus.
    run_id, _ = start_run(state, [module], mode="fix", from_v=from_v, to_v=to_v,
                          provisional=provisional_for([case.module], from_v, to_v))
    return normalised_report(state, run_id, roots=[work]), module


def compare(case: GoldenCase, work: Path) -> list:
    """Every difference between the migration result and the expected files; empty means the case passes."""
    report, module = run_case(case, work)
    expected_report = json.loads((case.expected / "report.json").read_text(encoding="utf-8"))
    problems = [] if report == expected_report else ["report differs from expected/report.json"]
    problems += [f"tree: {p}" for p in tree_differences(case.expected / "tree", module)]
    return problems


class GoldenMigrationTests(unittest.TestCase):
    def test_every_golden_case_matches_expected(self):
        for case in discover():
            with self.subTest(case=case.name), tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(compare(case, Path(tmp)), [])

    def test_module_without_expected_directory_is_not_a_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "17.0" / "kbi_empty").mkdir(parents=True)
            self.assertEqual(discover(Path(tmp)), [])

    def test_mismatched_sample_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "golden"
            module = root / "14.0" / "sample"
            shutil.copytree(FIXTURE, module)
            expected = module / "expected" / "15.0"
            shutil.copytree(FIXTURE, expected / "tree")
            (expected / "tree" / "EXPECTED_ONLY.txt").write_text("not produced\n", encoding="utf-8")
            (expected / "report.json").write_text(json.dumps({"deliberately": "wrong"}), encoding="utf-8")
            (case,) = discover(root)
            with tempfile.TemporaryDirectory() as work:
                problems = compare(case, Path(work))
            self.assertIn("report differs from expected/report.json", problems)
            self.assertIn("tree: missing EXPECTED_ONLY.txt", problems)


if __name__ == "__main__":
    unittest.main()

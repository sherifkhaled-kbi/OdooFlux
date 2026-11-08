"""TST-002-005 (REQ-TST-003): every golden-fixture INDEX entry has the required layout and valid sources.

Scope reconciled by FC-0.1 (specs/002-test-foundation/reconciliation.md): INDEX.json holds the v14 P0 fixture and the
PROVISIONAL 17.0 fixture; v12, v13, v15, v16 and v18 fixtures are DEFERRED_KB (KB-002-FIX).
"""

import ast
import re
import unittest
import xml.etree.ElementTree as ET

from tests._support import fixtures

_MANIFESTS = ("__manifest__.py", "__openerp__.py")
_AUTHORITIES = ("PROVISIONAL", "BASELINE")
_REQUIRED = ("id", "source_version", "module", "path", "targets", "evidence", "findings", "authority")


def _major(version: str) -> int:
    return int(version.split(".")[0])


def problems_for(item: dict) -> list:
    """Every layout or content problem of one INDEX entry; empty means valid."""
    problems = [f"missing field {k}" for k in _REQUIRED if k not in item]
    if problems:
        return problems
    if item["authority"] not in _AUTHORITIES:
        problems.append(f"unknown authority {item['authority']!r}")
    root = fixtures.module_dir(item)
    if not root.is_dir():
        return problems + [f"module directory {item['path']} missing"]
    manifest = next((root / m for m in _MANIFESTS if (root / m).is_file()), None)
    if manifest is None:
        return problems + ["no manifest"]
    try:
        data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
        if not str(data.get("version", "")).startswith(f"{_major(item['source_version'])}."):
            problems.append(f"manifest version {data.get('version')!r} does not start with the source version")
    except (SyntaxError, ValueError) as exc:
        problems.append(f"manifest unreadable: {exc}")
    for path in sorted(root.rglob("*")):
        if "expected" in path.relative_to(root).parts or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            if path.suffix == ".py":
                ast.parse(path.read_text(encoding="utf-8"))
            elif path.suffix == ".xml":
                ET.fromstring(path.read_bytes())
        except (SyntaxError, ET.ParseError) as exc:
            problems.append(f"{rel}: {exc}")
    for target in item["targets"]:
        if not re.fullmatch(r"\d+\.0", target) or _major(target) <= _major(item["source_version"]):
            problems.append(f"target {target} is not greater than the source")
            continue
        expected = root / "expected" / target
        for needed in ("tree", "report.json"):
            if not (expected / needed).exists():
                problems.append(f"expected/{target}/{needed} missing")
    return problems


class FixtureValidityTests(unittest.TestCase):
    def test_index_is_not_empty_and_ids_unique(self):
        index = fixtures.load_index()
        self.assertTrue(index)
        ids = [i["id"] for i in index]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_index_entry_is_valid(self):
        for item in fixtures.load_index():
            with self.subTest(fixture=item["id"]):
                self.assertEqual(problems_for(item), [])

    def test_validator_rejects_bad_entries(self):
        good = dict(fixtures.entry("17.0/kbi_demo"))
        self.assertTrue(problems_for({**good, "targets": ["16.0"]}))
        self.assertTrue(problems_for({**good, "source_version": "16.0"}))
        self.assertTrue(problems_for({**good, "path": "17.0/nope"}))
        bad = {k: v for k, v in good.items() if k != "evidence"}
        self.assertTrue(problems_for(bad))


if __name__ == "__main__":
    unittest.main()

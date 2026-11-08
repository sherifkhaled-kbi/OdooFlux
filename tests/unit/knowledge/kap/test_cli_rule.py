"""TST-011-027 (REQ-KAP-019, REQ-KAP-018, REQ-KAP-021): `odooflux knowledge rule` CLI (T027).

Contract: contracts/manual-rule-cli.md (verbs, promotion gates, preservation) and contracts/cli-surface.md (exit codes
0/1/2). Every test works on a small non-built-in tree built in a temporary directory from the shipped official sources
and one shipped evidence record. The shipped knowledge tree is only read: its byte hash is taken before and after the
module's built-in tests and must not change. Nothing here touches the network or a socket.
"""

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.cli import knowledge as knowledge_cli
from odooflux.knowledge.authoring import conflicts
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.builtins import build_registries  # composition root: the document adapters the KAP tests inject
REGISTRIES = build_registries()
TOOLKIT = REGISTRIES.extract_toolkit

RULE_ID = "12-13.python.manual-probe"
OTHER_ID = "12-13.python.manual-second"
CANDIDATE_ID = "CR-0123456789abcdef"
DETECTOR = "odooflux.rules.python.generic:flag_decorator"
PARAMS = '{"decorator": "api.multi"}'
AUTHOR = "maintainer"
APPROVAL = "APR-2026-001"


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def _snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = knowledge_cli.main(["rule", *argv], registries=REGISTRIES)
    return code, out.getvalue() + err.getvalue()


class _TreeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.tree = self.root / "tree"
        (self.tree / "evidence").mkdir(parents=True)
        (self.tree / "compatibility").mkdir()
        shutil.copytree(KNOWLEDGE_ROOT / "official_sources", self.tree / "official_sources")
        shutil.copy(KNOWLEDGE_ROOT / "evidence" / "EV-001.json", self.tree / "evidence" / "EV-001.json")
        shutil.copy(KNOWLEDGE_ROOT / "evidence" / "EV-002.json", self.tree / "evidence" / "EV-002.json")
        self.fixture = self.root / "positive.py"
        self.fixture.write_text("@api.multi\ndef f(self):\n    pass\n", encoding="utf-8")
        self.build = self.root / "build"

    def create(self, rule_id=RULE_ID):
        return _run("create", "--path", str(self.tree), "--id", rule_id, "--step", "12-13",
                    "--category", "python_orm", "--detector-ref", DETECTOR, "--params", PARAMS,
                    "--evidence", "EV-001", "--file-kinds", "python", "--message", "probe message",
                    "--suggestion", "probe suggestion", "--author", AUTHOR)

    def rules_file(self):
        return self.tree / "compatibility" / "12-13.rules.json"

    def rows(self):
        return json.loads(self.rules_file().read_text(encoding="utf-8"))

    def row(self, rule_id=RULE_ID):
        return next(r for r in self.rows() if r["id"] == rule_id)


class TestCliVerbSmoke(_TreeCase):
    def test_cli_verb_smoke(self):
        """Every verb runs once on the temporary tree in contract order and returns its expected exit code."""
        steps = [
            ("create", lambda: self.create(), 0),
            ("edit", lambda: _run("edit", "--path", str(self.tree), "--id", RULE_ID,
                                  "--set", "message=edited message", "--author", AUTHOR), 0),
            ("disable", lambda: _run("disable", "--path", str(self.tree), "--id", RULE_ID,
                                     "--reason", "probe", "--author", AUTHOR), 0),
            ("enable", lambda: _run("enable", "--path", str(self.tree), "--id", RULE_ID, "--author", AUTHOR), 0),
            ("link-evidence", lambda: _run("link-evidence", "--path", str(self.tree), "--id", RULE_ID,
                                           "--evidence", "EV-002", "--author", AUTHOR), 0),
            ("add-test", lambda: _run("add-test", "--path", str(self.tree), "--id", RULE_ID, "--kind", "positive",
                                      "--fixture", str(self.fixture), "--author", AUTHOR), 0),
            ("inspect", lambda: _run("inspect", "--path", str(self.tree), "--id", RULE_ID, "--json"), 0),
            ("history", lambda: _run("history", "--path", str(self.tree), "--id", RULE_ID, "--json"), 0),
            ("validate", lambda: _run("validate", "--path", str(self.tree)), 0),
            ("promote", lambda: _run("promote", "--path", str(self.tree), "--id", RULE_ID, "--to", "FIX_ENABLED",
                                     "--approval", APPROVAL, "--author", AUTHOR), 1),
            ("resolve", self._resolve, 0),
            ("retire", lambda: _run("retire", "--path", str(self.tree), "--id", RULE_ID,
                                    "--reason", "smoke done", "--author", AUTHOR), 0),
        ]
        for verb, call, expected in steps:
            with self.subTest(verb=verb):
                code, _ = call()
                self.assertEqual(code, expected, verb)
        self.assertEqual(self.row()["maturity"], "RETIRED")
        self.assertEqual(self.row()["retired_reason"], "smoke done")

    def _resolve(self):
        conflicts.write_conflicts(self.build, [{"candidate_id": CANDIDATE_ID, "kind": "A002", "with": RULE_ID,
                                                "keep": "manual", "resolved": False}])
        return _run("resolve", "--path", str(self.tree), "--candidate", CANDIDATE_ID, "--keep", "manual",
                    "--build-dir", str(self.build), "--author", AUTHOR)


class TestManualRuleValidates(_TreeCase):
    def test_manual_rule_passes_knowledge_validate(self):
        """A rule created through the CLI is DETECT_ONLY, MANUAL, has no fixer, and the tree passes validate."""
        code, _ = self.create()
        self.assertEqual(code, 0)
        row = self.row()
        self.assertEqual(row["origin"], "MANUAL")
        self.assertEqual(row["maturity"], "DETECT_ONLY")
        self.assertIsNone(row["fixer_ref"])
        code, text = _run("validate", "--path", str(self.tree))
        self.assertEqual(code, 0, text)
        self.assertEqual(knowledge_cli.main(["validate", "--path", str(self.tree)], registries=REGISTRIES), 0)

    def test_create_unknown_detector_refused(self):
        """A detector_ref that does not resolve to a bindable rule function is refused; nothing is written."""
        before = _snapshot(self.tree)
        code, _ = _run("create", "--path", str(self.tree), "--id", RULE_ID, "--step", "12-13",
                       "--category", "python_orm", "--detector-ref", "odooflux.rules.python.generic:no_such_detector",
                       "--params", "{}", "--evidence", "EV-001", "--author", AUTHOR)
        self.assertEqual(code, 1)
        self.assertEqual(_snapshot(self.tree), before)

    def test_create_wrong_params_refused(self):
        """Parameters that the detector does not accept are refused before anything is written."""
        before = _snapshot(self.tree)
        code, _ = _run("create", "--path", str(self.tree), "--id", RULE_ID, "--step", "12-13",
                       "--category", "python_orm", "--detector-ref", DETECTOR, "--params", '{"method": "x"}',
                       "--evidence", "EV-001", "--author", AUTHOR)
        self.assertEqual(code, 1)
        self.assertEqual(_snapshot(self.tree), before)

    def test_failed_validation_rolls_back(self):
        """An unknown evidence reference (A006) is a new ERROR: the verb fails and every file is restored."""
        before = _snapshot(self.tree)
        code, _ = _run("create", "--path", str(self.tree), "--id", RULE_ID, "--step", "12-13",
                       "--category", "python_orm", "--detector-ref", DETECTOR, "--params", PARAMS,
                       "--evidence", "EV-999", "--author", AUTHOR)
        self.assertEqual(code, 1)
        self.assertEqual(_snapshot(self.tree), before)


class TestNoFixEnabledFromCli(_TreeCase):
    def test_no_verb_sets_fix_enabled(self):
        """FIX_ENABLED cannot be set by create or edit; both are refused and the file is unchanged."""
        self.create()
        before = self.rules_file().read_bytes()
        code, _ = _run("edit", "--path", str(self.tree), "--id", RULE_ID, "--set", "maturity=FIX_ENABLED",
                       "--author", AUTHOR)
        self.assertEqual(code, 1)
        self.assertEqual(self.rules_file().read_bytes(), before)
        code, _ = _run("create", "--path", str(self.tree), "--id", OTHER_ID, "--step", "12-13",
                       "--category", "python_orm", "--detector-ref", DETECTOR, "--params", PARAMS,
                       "--evidence", "EV-001", "--maturity", "FIX_ENABLED", "--author", AUTHOR)
        self.assertEqual(code, 2)
        code, _ = _run("create", "--path", str(self.tree), "--id", OTHER_ID, "--step", "12-13",
                       "--category", "python_orm", "--detector-ref", DETECTOR, "--params", PARAMS,
                       "--evidence", "EV-001", "--fixer-ref", "odooflux.rules.python.generic:remove_decorator",
                       "--author", AUTHOR)
        self.assertEqual(code, 2)
        self.assertEqual(self.rules_file().read_bytes(), before)


class TestPromoteFromCli(_TreeCase):
    def setUp(self):
        super().setUp()
        self.create()

    def test_promote_requires_approval(self):
        code, _ = _run("promote", "--path", str(self.tree), "--id", RULE_ID, "--to", "FIX_ENABLED",
                       "--author", AUTHOR)
        self.assertEqual(code, 2)

    def test_promote_self_approval_refused(self):
        before = self.rules_file().read_bytes()
        code, text = _run("promote", "--path", str(self.tree), "--id", RULE_ID, "--to", "FIX_ENABLED",
                          "--approval", AUTHOR, "--author", AUTHOR)
        self.assertEqual(code, 1, text)
        self.assertIn("self-approval", text)
        self.assertEqual(self.rules_file().read_bytes(), before)

    def test_promote_gate_refusal_writes_nothing(self):
        before = _snapshot(self.tree)
        code, text = _run("promote", "--path", str(self.tree), "--id", RULE_ID, "--to", "FIX_ENABLED",
                          "--approval", APPROVAL, "--author", AUTHOR)
        self.assertEqual(code, 1, text)
        self.assertIn("gate", text)
        self.assertEqual(_snapshot(self.tree), before)


class TestBuiltinTreeProtected(_TreeCase):
    def test_builtin_tree_refused_and_byte_unchanged(self):
        """Write verbs refuse the shipped knowledge tree (exit 2); its bytes are identical before and after."""
        before = _tree_hash(KNOWLEDGE_ROOT)
        writes = [
            ["create", "--path", str(KNOWLEDGE_ROOT), "--id", RULE_ID, "--step", "12-13", "--category", "python_orm",
             "--detector-ref", DETECTOR, "--params", PARAMS, "--evidence", "EV-001"],
            ["edit", "--path", str(KNOWLEDGE_ROOT), "--id", "12-13.python.api-multi-removed", "--set", "message=x"],
            ["disable", "--path", str(KNOWLEDGE_ROOT), "--id", "12-13.python.api-multi-removed", "--reason", "x"],
            ["retire", "--path", str(KNOWLEDGE_ROOT), "--id", "12-13.python.api-multi-removed", "--reason", "x"],
            ["add-test", "--path", str(KNOWLEDGE_ROOT), "--id", "12-13.python.api-multi-removed", "--kind",
             "positive", "--fixture", str(self.fixture)],
        ]
        for argv in writes:
            with self.subTest(verb=argv[0]):
                code, _ = _run(*argv)
                self.assertEqual(code, 2)
        self.assertEqual(_tree_hash(KNOWLEDGE_ROOT), before)

    def test_strict_builtin_validate_is_superset(self):
        """`validate --strict-builtin` on the shipped tree is read-only and reports at least the default findings."""
        before = _tree_hash(KNOWLEDGE_ROOT)
        code, plain = _run("validate", "--path", str(KNOWLEDGE_ROOT))
        self.assertIn(code, (0, 1))
        code, strict = _run("validate", "--path", str(KNOWLEDGE_ROOT), "--strict-builtin")
        self.assertIn(code, (0, 1))
        finding_lines = lambda text: {line for line in text.splitlines() if not line.startswith("records=")}
        self.assertTrue(finding_lines(plain) <= finding_lines(strict))
        self.assertEqual(_tree_hash(KNOWLEDGE_ROOT), before)


if __name__ == "__main__":
    unittest.main()

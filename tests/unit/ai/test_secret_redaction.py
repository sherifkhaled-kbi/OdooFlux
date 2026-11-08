"""TST-007-014 (REQ-AI-008, REQ-SEC-003, FR-010): credentials come from env/secrets file and never reach artefacts."""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ._setup_path import SRC  # noqa: F401
from odooflux.ai.providers.credentials import (
    API_KEY_DEPRECATION, CredentialError, Secret, load_credential, redact_secrets, read_secrets_file)

CANARY = "sk-canary-9f8e7d6c5b4a39281706"


class CredentialTests(unittest.TestCase):
    def test_env_is_read_and_wrapped(self):
        secret = load_credential("MY_KEY", {"MY_KEY": CANARY})
        self.assertIsInstance(secret, Secret)
        self.assertEqual(secret.reveal(), CANARY)
        for rendering in (str(secret), repr(secret), f"{secret}", "%s" % secret, str([secret])):
            self.assertNotIn(CANARY, rendering)

    def test_missing_credential_is_none(self):
        self.assertIsNone(load_credential("NOPE", {}))

    def test_secrets_file_outside_scanned_paths(self):
        tmp = Path(tempfile.mkdtemp())
        f = tmp / "secrets.env"
        f.write_text(f"# comment\nMY_KEY={CANARY}\nOTHER='x y'\n", encoding="utf-8")
        os.chmod(f, 0o600)
        self.assertEqual(read_secrets_file(f, scanned_paths=[tmp / "addons"])["MY_KEY"], CANARY)
        self.assertEqual(load_credential("MY_KEY", {}, secrets_file=f, scanned_paths=[]).reveal(), CANARY)

    def test_environment_wins_over_file(self):
        tmp = Path(tempfile.mkdtemp())
        f = tmp / "s.env"
        f.write_text("MY_KEY=from-file\n")
        self.assertEqual(load_credential("MY_KEY", {"MY_KEY": "from-env"}, secrets_file=f).reveal(), "from-env")

    def test_secrets_file_inside_a_scanned_path_is_refused(self):
        tmp = Path(tempfile.mkdtemp())
        mod = tmp / "addons" / "kbi_x"
        mod.mkdir(parents=True)
        f = mod / "secrets.env"
        f.write_text(f"MY_KEY={CANARY}\n")
        with self.assertRaises(CredentialError) as cm:
            read_secrets_file(f, scanned_paths=[tmp / "addons"])
        self.assertEqual(cm.exception.code, "secrets_file_in_scanned_path")
        self.assertNotIn(CANARY, str(cm.exception))

    def test_group_readable_secrets_file_is_refused_on_posix(self):
        if os.name != "posix":
            self.skipTest("posix permissions")
        tmp = Path(tempfile.mkdtemp())
        f = tmp / "s.env"
        f.write_text(f"MY_KEY={CANARY}\n")
        os.chmod(f, 0o644)
        with self.assertRaises(CredentialError) as cm:
            read_secrets_file(f, scanned_paths=[])
        self.assertEqual(cm.exception.code, "secrets_file_permissions")

    def test_redact_secrets_removes_known_values_and_key_shapes(self):
        text = f"boom {CANARY} and Authorization: Bearer abc123def456ghi789 x-api-key: zzzzzzzzzzzz"
        out = redact_secrets(text, [CANARY])
        self.assertNotIn(CANARY, out)
        self.assertNotIn("abc123def456ghi789", out)
        self.assertNotIn("zzzzzzzzzzzz", out)

    def test_api_key_deprecation_never_echoes_the_value(self):
        self.assertNotIn(CANARY, API_KEY_DEPRECATION)
        self.assertIn("deprecated", API_KEY_DEPRECATION)

    def test_cli_api_key_warning_does_not_echo_value(self):
        import contextlib
        from odooflux.builtins import main
        out, err = io.StringIO(), io.StringIO()
        tmp = Path(tempfile.mkdtemp())
        (tmp / "m").mkdir()
        (tmp / "m" / "__manifest__.py").write_text("{'name': 'x', 'version': '14.0.1.0.0'}")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            main(["--module", str(tmp / "m"), "--from-version", "14", "--to-version", "15", "--api-key", CANARY,
                  "--state-dir", str(tmp / "state")])
        self.assertNotIn(CANARY, out.getvalue() + err.getvalue())
        self.assertIn("deprecated", out.getvalue() + err.getvalue())


class ArtefactScanTests(unittest.TestCase):
    """A canary key present in the environment must be absent from every file a run leaves behind."""

    def test_no_artefact_contains_the_canary(self):
        from tests.unit.ai import _helpers as h
        from odooflux.ai.caching.cache import ResultCache
        from odooflux.ai.escalation import Escalator
        from odooflux.ai.providers.fake import FakeProvider
        from odooflux.ai.providers.types import ModelDescriptor
        from odooflux.ai.usage.usage import UsageLedger
        import json
        state = Path(tempfile.mkdtemp())
        text = "class A:\n    def f_ok(self):\n        return old_api(1)\n"
        script = {"entries": [{"match": {"contains": "def f_ok"}, "response": {
            "replacement": "    def f_ok(self):\n        return new_api(1)\n", "notes": "", "cannot_fix": False,
            "usage": {"input": 5, "output": 5}}}]}
        with mock.patch.dict(os.environ, {"ALPHA_KEY": CANARY}):
            secret = load_credential("ALPHA_KEY", os.environ)
            p = FakeProvider(script, models=[ModelDescriptor("fake", "fake-model")])
            ledger = UsageLedger()
            esc = Escalator(p.complete, provider="fake", model="fake-model", step="s",
                            validate=h.python_validate, rescan=h.toy_rescan, cache=ResultCache(state / "ai-cache"),
                            ledger=ledger)
            esc.escalate_file("mod", "m.py", text, h.toy_findings("m.py", text), h.TOY_METAS)
            (state / "ai-usage.json").write_text(json.dumps(ledger.summary()))
            self.assertNotIn(CANARY, repr(secret))
        blobs = [p.read_text() for p in state.rglob("*") if p.is_file()]
        self.assertTrue(blobs)
        self.assertFalse([b for b in blobs if CANARY in b])


if __name__ == "__main__":
    unittest.main()

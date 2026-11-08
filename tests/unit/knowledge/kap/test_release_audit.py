"""TST-011-008 (REQ-KAP-045, REQ-KAP-046): kb-home audit log wrapper (`audit.jsonl`, release-lifecycle actions)."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.release.audit import AUDIT_NAME, RELEASE_ACTIONS, KbAudit, verify_audit

CANARY = "CANARY-KAP-SECRET-7f3a"


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "kb-home"

    def tearDown(self):
        self._tmp.cleanup()

    def test_chain_verifies(self):
        audit = KbAudit(self.home, "run-1")
        audit.record("release_installed", "kr-0123456789ab", "ok", {"files": 3})
        audit.record("release_activated", "kr-0123456789ab", "ok", {})
        audit.record("release_deactivated", "kr-0123456789ab", "ok", {})
        ok, reason = verify_audit(self.home)
        self.assertTrue(ok, reason)
        lines = (self.home / AUDIT_NAME).read_text(encoding="utf-8").splitlines()
        self.assertEqual(3, len(lines))
        self.assertEqual(["release_installed", "release_activated", "release_deactivated"],
                         [json.loads(line)["action"] for line in lines])

    def test_tamper_detected(self):
        audit = KbAudit(self.home, "run-1")
        audit.record("release_installed", "kr-0123456789ab", "ok", {})
        audit.record("release_activated", "kr-0123456789ab", "ok", {})
        path = self.home / AUDIT_NAME
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace("release_installed", "release_removed")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, reason = verify_audit(self.home)
        self.assertFalse(ok)
        self.assertIn("entry 2", reason)

    def test_redaction_canary(self):
        audit = KbAudit(self.home, "run-1", secrets=[CANARY])
        audit.record("package_rejected", f"pkg-{CANARY}.ofkp", "refused", {"reason": f"token={CANARY}"})
        text = (self.home / AUDIT_NAME).read_text(encoding="utf-8")
        self.assertNotIn(CANARY, text)
        self.assertTrue(verify_audit(self.home)[0])

    def test_rejects_non_release_action(self):
        audit = KbAudit(self.home, "run-1")
        with self.assertRaises(ValueError):
            audit.record("file_written", "x", "ok", {})
        self.assertFalse((self.home / AUDIT_NAME).exists())

    def test_action_set_is_release_lifecycle(self):
        self.assertEqual(12, len(RELEASE_ACTIONS))
        self.assertIn("release_rolled_back", RELEASE_ACTIONS)
        self.assertIn("ai_proposal", RELEASE_ACTIONS)

    def test_no_directory_created_before_first_record(self):
        KbAudit(self.home, "run-1")
        self.assertFalse(self.home.exists())


if __name__ == "__main__":
    unittest.main()

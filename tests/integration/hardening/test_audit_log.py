"""TST-010-007 (T015; REQ-SEC-005, FR-007, contracts/audit-log.md): the append-only audit log has one entry per action
type that occurs in a scenario, a valid hash chain, redaction of secrets, and detects tampering."""

import json
import tempfile
import unittest
from pathlib import Path

from . import _support as sup
from odooflux.core.recovery import audit_log as al
from odooflux.core.recovery.audit_log import ACTIONS, AuditError, AuditLog, verify_chain
from odooflux.core.recovery.rollback import rollback
from odooflux.utils.hashing import digest_tree


def entries(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


class AuditLogUnitTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "audit.jsonl"

    def test_entry_fields_and_monotonic_sequence(self):
        log = AuditLog(self.path, "run-1")
        log.append("plan_created", target="plan", details={"steps": 2})
        log.append("report_written", target="report.json", outcome="ok")
        a, b = entries(self.path)
        self.assertEqual([a["seq"], b["seq"]], [1, 2])
        for e in (a, b):
            self.assertEqual(sorted(e), ["action", "actor", "details", "outcome", "prev_hash", "run_id", "seq", "target",
                                          "ts"])
            self.assertEqual((e["actor"], e["run_id"]), ("tool", "run-1"))
            self.assertRegex(e["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|\+00:00)$")

    def test_chain_links_each_entry_to_the_sha256_of_the_previous_line(self):
        import hashlib
        log = AuditLog(self.path, "r")
        for action in ("config_loaded", "plan_created", "run_finished"):
            log.append(action)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        first, second, third = (json.loads(l) for l in lines)
        self.assertEqual(first["prev_hash"], "0" * 64)
        self.assertEqual(second["prev_hash"], hashlib.sha256(lines[0].encode("utf-8")).hexdigest())
        self.assertEqual(third["prev_hash"], hashlib.sha256(lines[1].encode("utf-8")).hexdigest())
        self.assertEqual(verify_chain(self.path), (True, ""))

    def test_tampering_is_detected(self):
        log = AuditLog(self.path, "r")
        for action in ("config_loaded", "plan_created", "run_finished"):
            log.append(action)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        edited = json.loads(lines[1])
        edited["outcome"] = "failed"
        self.path.write_text("\n".join([lines[0], json.dumps(edited, sort_keys=True), lines[2]]) + "\n", encoding="utf-8")
        ok, reason = verify_chain(self.path)
        self.assertFalse(ok)
        self.assertIn("3", reason)  # the entry after the edited one no longer links

    def test_deleted_and_reordered_entries_are_detected(self):
        log = AuditLog(self.path, "r")
        for action in ("config_loaded", "plan_created", "report_written", "run_finished"):
            log.append(action)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.path.write_text("\n".join([lines[0], lines[2], lines[3]]) + "\n", encoding="utf-8")
        self.assertFalse(verify_chain(self.path)[0])
        self.path.write_text("\n".join([lines[1], lines[0], lines[2], lines[3]]) + "\n", encoding="utf-8")
        self.assertFalse(verify_chain(self.path)[0])

    def test_truncated_final_line_is_reported(self):
        log = AuditLog(self.path, "r")
        log.append("config_loaded")
        log.append("plan_created")
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(text[:-20], encoding="utf-8")
        self.assertFalse(verify_chain(self.path)[0])

    def test_unknown_action_and_outcome_are_refused(self):
        log = AuditLog(self.path, "r")
        with self.assertRaises(AuditError):
            log.append("sudo_make_sandwich")
        with self.assertRaises(AuditError):
            log.append("plan_created", outcome="great")

    def test_reopening_continues_the_chain(self):
        AuditLog(self.path, "r").append("config_loaded")
        AuditLog(self.path, "r").append("plan_created")
        self.assertEqual([e["seq"] for e in entries(self.path)], [1, 2])
        self.assertEqual(verify_chain(self.path), (True, ""))

    def test_secrets_and_credential_shapes_are_redacted(self):
        log = AuditLog(self.path, "r", secrets=["canary-secret-value-123"])
        log.append("config_loaded", target="canary-secret-value-123", details={
            "note": "key is canary-secret-value-123", "api_key": "plain-value", "nested": {"authorization": "Bearer abcdef123456"},
            "shape": "sk-ant-abcdefghijklmnop", "ok": 3})
        text = self.path.read_text(encoding="utf-8")
        for leaked in ("canary-secret-value-123", "plain-value", "abcdef123456", "sk-ant-abcdefghijklmnop"):
            self.assertNotIn(leaked, text)
        entry = entries(self.path)[0]
        self.assertEqual(entry["details"]["ok"], 3)
        self.assertEqual(entry["details"]["api_key"], "***")

    def test_log_inside_a_scanned_path_is_refused(self):
        scanned = Path(tempfile.mkdtemp())
        with self.assertRaises(AuditError):
            AuditLog(scanned / "mod" / "audit.jsonl", "r", scanned_paths=[scanned])

    def test_contract_actions_are_all_known(self):
        for action in ("config_loaded", "plan_created", "workspace_created", "backup_created", "backup_verified",
                       "file_written", "file_promoted", "edit_rejected", "rollback_started", "rollback_completed",
                       "checkpoint_written", "ai_request", "runtime_launched", "runtime_teardown", "report_written",
                       "run_finished"):
            self.assertIn(action, ACTIONS)

    def test_runlog_events_map_to_audit_actions_without_file_contents(self):
        mapped = al.from_runlog("file_written", {"module": "m", "path": "/x/m/a.py", "sha256_before": "1",
                                                 "sha256_after": "2", "rules": ["r"], "module_path": "/x/m"})
        self.assertEqual(mapped[0], "file_promoted")
        self.assertEqual(mapped[1], "m/a.py")
        self.assertNotIn("fixed", json.dumps(mapped))
        self.assertEqual(al.from_runlog("backup_failed", {"module": "m", "reason": "disk"})[2], "failed")
        self.assertEqual(al.from_runlog("edit_rejected", {"module": "m", "path": "/x/m/a.py", "rules": [],
                                                           "reason": "bad"})[2], "refused")
        self.assertIsNone(al.from_runlog("something_else", {}))


class AuditScenarioTests(unittest.TestCase):
    """A write-mode run, a rollback, AI (fake provider) and the runtime adapter, each audited."""

    def test_fix_run_has_one_entry_per_action_type_and_a_valid_chain(self):
        corpus = sup.copy_corpus(2)
        state_dir = Path(tempfile.mkdtemp())
        run, state = sup.run_analysis(corpus, state_dir, mode="fix")
        path = run.log_dir / "audit.jsonl"
        self.assertTrue(path.is_file())
        self.assertEqual(verify_chain(path), (True, ""))
        actions = [e["action"] for e in entries(path)]
        for expected in ("workspace_created", "backup_created", "backup_verified", "file_written", "file_promoted",
                         "checkpoint_written", "run_finished"):
            self.assertIn(expected, actions, expected)
        self.assertEqual(actions[-1], "run_finished")
        self.assertEqual(sorted(set(actions)) , sorted(set(actions) & set(ACTIONS)))
        for e in entries(path):  # every path is relative to a module or the run, never file content
            self.assertNotIn("\n", e["target"])
            self.assertLess(len(json.dumps(e["details"])), 2000)

    def test_analysis_run_logs_only_run_level_actions(self):
        run, _ = sup.run_analysis(sup.copy_corpus(2), tempfile.mkdtemp())
        actions = {e["action"] for e in entries(run.log_dir / "audit.jsonl")}
        self.assertIn("run_finished", actions)
        self.assertFalse(actions & {"backup_created", "file_promoted", "workspace_created"})

    def test_rollback_is_audited_and_continues_the_same_chain(self):
        corpus = sup.copy_corpus(2)
        before = digest_tree(corpus)
        state_dir = Path(tempfile.mkdtemp())
        run, _ = sup.run_analysis(corpus, state_dir, mode="fix")
        rollback(state_dir, run.run_id)
        path = run.log_dir / "audit.jsonl"
        self.assertEqual(verify_chain(path), (True, ""))
        actions = [e["action"] for e in entries(path)]
        self.assertIn("rollback_started", actions)
        self.assertIn("rollback_completed", actions)
        self.assertLess(actions.index("rollback_started"), actions.index("rollback_completed"))
        self.assertEqual(digest_tree(corpus), before)

    def test_runtime_adapter_launch_and_teardown_are_audited(self):
        from odooflux.validation.runtime import docker_env as de
        run, _ = sup.run_analysis(sup.copy_corpus(1), tempfile.mkdtemp())
        env = de.DockerEnvironment(runner=FakeDocker(), readiness_timeout_s=1, sleep=lambda s: None)
        env.audit = run.audit
        handle = env.prepare("19.0", [sup.module_paths(sup.copy_corpus(1))[0]], de.Limits(), state_dir=tempfile.mkdtemp())
        env.teardown(handle)
        actions = [e["action"] for e in entries(run.log_dir / "audit.jsonl")]
        self.assertIn("runtime_launched", actions)
        self.assertIn("runtime_teardown", actions)
        text = (run.log_dir / "audit.jsonl").read_text(encoding="utf-8")
        launched = next(e for e in entries(run.log_dir / "audit.jsonl") if e["action"] == "runtime_launched")
        self.assertEqual(launched["details"]["version"], "19.0")
        self.assertNotIn("password", text.lower())

    def test_ai_requests_are_audited_with_metadata_only(self):
        from .test_secret_scan import run_ai_scenario
        scenario = run_ai_scenario()
        audit = scenario.run.log_dir / "audit.jsonl"
        self.assertEqual(verify_chain(audit), (True, ""))
        ai = [e for e in entries(audit) if e["action"] == "ai_request"]
        self.assertTrue(ai)
        for e in ai:
            self.assertEqual(sorted(e["details"]), ["cache_hit", "input_tokens", "model", "outcome", "output_tokens",
                                                     "provider"])
            self.assertNotIn("old_api", json.dumps(e))  # no prompt text or source content


class FakeDocker:
    """A runner that answers like a quiet Docker daemon (images present, database ready, nothing left over)."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, timeout=None):
        from odooflux.validation.runtime import docker_env as de
        self.calls.append(list(argv))
        out = ""
        if argv[:3] == ["docker", "image", "inspect"]:
            out = json.dumps([f"{argv[-1].split(':')[0]}@sha256:{'a' * 64}"])
        elif argv[:2] == ["docker", "logs"]:
            out = de.READY_MARKER
        return de.CommandResult(0, out, "")


if __name__ == "__main__":
    unittest.main()

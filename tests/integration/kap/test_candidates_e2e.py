"""TST-011-062 (REQ-KAP-016, REQ-KAP-018): the synthetic 16.0 to 17.0 ledger becomes candidates, then accepted rules in a
non-built-in tree. Two runs are byte-identical. AI is off by default (no gateway built, no call). With AI on and a
FakeProvider reply, only the allowed fields are filled and the verified tree is unchanged. Without the
evidence_excerpt grant the request is denied and the category is named. The kill switch blocks transmission. The
resulting tree validates with `knowledge validate --path`. Offline: sockets are patched to fail.

The extraction is the one T054 runs (git-local adapter over the synthetic repository); the ledger is saved once and
copied into each run. Nothing here touches the shipped knowledge tree.
"""

import contextlib
import hashlib
import io
import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.ai.authorization import Authorizer
from odooflux.ai.gateway import GatewayConfig, build_gateway
from odooflux.ai.providers.catalog import load_catalog
from odooflux.builtins import build_registries
from odooflux.cli import knowledge as cli
from odooflux.cli.kap_extract import full_registry
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.extract import driver
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from tests.fixtures.kap.make_synth_repo import build_synth_repo

GIT_AVAILABLE = shutil.which("git") is not None
SOURCE_ID = "odoo-community-17.0"
ALLOW = ["https://github.com/odoo/odoo/"]
CREATED = "2026-11-08T10:00:00Z"
AT = "2026-11-08T11:00:00Z"
STEP = "01-02"
DATA_DIRS = ("evidence", "compatibility", "official_sources")
AI_FIELDS = ["ai_proposed", "candidate_id", "change_id", "origin", "rationale", "template_hint"]


def _spec(url, revision):
    return {
        "source_id": SOURCE_ID, "kind": "GIT_COMMUNITY", "official": False, "url": url,
        "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3", "branch": "17.0", "revision": revision,
        "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }


def _tree_bytes(root: Path, skip=("candidates/ai",)) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(s + "/") for s in skip):
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class _NoSocket:
    def __init__(self, *args, **kwargs):
        raise AssertionError("network access attempted in an offline test")


@unittest.skipUnless(GIT_AVAILABLE, "git is not installed; the git-local adapter needs git")
class CandidatesEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.repo = build_synth_repo(cls.base / "synth")
        cls.store = BlobStore(cls.base / "objects")
        adapter = GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW)
        local = "local:" + cls.repo.path
        from_snap = adapter.snapshot(_spec(local, cls.repo.from_sha), cls.store, created_at=CREATED)
        to_snap = adapter.snapshot(_spec(local, cls.repo.to_sha), cls.store, created_at=CREATED)
        result = driver.extract_pair(from_snap, to_snap, None, full_registry(), store=cls.store, step=STEP,
                                     toolkit=build_registries().extract_toolkit)
        cls.from_snap, cls.to_snap = from_snap, to_snap
        cls.ledger_bytes_path = cls.base / "source-ledger.json"
        Ledger.create(STEP, from_snap, to_snap, result.drafts, clock=lambda: CREATED).save(cls.ledger_bytes_path)
        cls.source_path = cls.base / "source.json"
        cls.source_path.write_text(json.dumps({
            "source_id": SOURCE_ID, "official": False, "branch": "17.0", "revision": cls.repo.to_sha,
            "url": f"https://github.com/odoo/odoo/tree/{cls.repo.to_sha}", "repository": "odoo/odoo"}),
            encoding="utf-8")
        cls._sockets = mock.patch.object(socket, "socket", _NoSocket)
        cls._sockets.start()
        cls._connect = mock.patch.object(socket, "create_connection", _NoSocket)
        cls._connect.start()

    @classmethod
    def tearDownClass(cls):
        cls._connect.stop()
        cls._sockets.stop()
        cls._tmp.cleanup()

    def setUp(self):
        self.registries = build_registries()
        self.gateways = []
        self.registries.ai_gateway_factory = self._factory

    def _factory(self, config):
        """The composition root's factory, here over the packaged fake provider with a scripted reply."""
        script = self.base / f"script-{len(self.gateways)}.json"
        script.write_text(json.dumps({"entries": [{"response": {"raw_text": json.dumps(
            {"rationale": "The removed method may still be called; review the callers.", "template_hint": ""})}}]}),
            encoding="utf-8")
        cfg = GatewayConfig(provider=config["provider"], model=config["model"],
                            grants=dict(config.get("authorizations") or {}),
                            kill_switch=bool(config.get("kill_switch")), fake_script=str(script))
        gateway = build_gateway(cfg, load_catalog(), environ={})
        self.gateways.append(gateway)
        return gateway, Authorizer(config.get("authorizations") or {})

    def _cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), self.registries)
        return code, out.getvalue(), err.getvalue()

    def _fresh_run(self, name):
        run = self.base / name
        tree = run / "tree"
        tree.mkdir(parents=True)
        for d in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / d, tree / d, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", tree / "gaps.json")
        # The synthetic revision is catalogued in this staging copy only (the shipped catalogue is never edited).
        revisions = json.loads((tree / "official_sources" / "revisions.json").read_text(encoding="utf-8"))
        revisions.append({"repository": "odoo/odoo", "branch": "17.0", "revision": self.repo.to_sha,
                          "committed": "2026-11-08", "pinned_on": "2026-11-08", "tags": []})
        (tree / "official_sources" / "revisions.json").write_text(json.dumps(revisions, indent=2) + "\n",
                                                                 encoding="utf-8")
        ledger = run / "ledger.json"
        shutil.copyfile(self.ledger_bytes_path, ledger)
        return tree, ledger

    def _generate(self, tree, ledger):
        return self._cli("candidates", "generate", "--path", str(tree), "--ledger", str(ledger),
                         "--source", str(self.source_path), "--checked-on", "2026-11-08", "--at", CREATED)

    def _accept_all(self, tree, ledger):
        code, out, err = self._cli("candidates", "list", "--path", str(tree), "--json")
        self.assertEqual(code, 0, err)
        rows = json.loads(out)
        self.assertTrue(rows, "the synthetic pair must yield candidates")
        for row in rows:
            code, _, err = self._cli("candidates", "accept", row["candidate_id"], "--path", str(tree),
                                     "--ledger", str(ledger), "--author", "e2e", "--at", AT)
            self.assertEqual(code, 0, f"{row['candidate_id']}: {err}")
        return rows

    def _pipeline(self, name):
        tree, ledger = self._fresh_run(name)
        code, _, err = self._generate(tree, ledger)
        self.assertEqual(code, 0, err)
        rows = self._accept_all(tree, ledger)
        return tree, ledger, rows

    def test_ledger_to_rules_deterministic(self):
        tree_a, ledger_a, rows_a = self._pipeline("run-a")
        tree_b, ledger_b, rows_b = self._pipeline("run-b")
        self.assertEqual(rows_a, rows_b)
        self.assertEqual(_tree_bytes(tree_a, skip=()), _tree_bytes(tree_b, skip=()))
        self.assertEqual(ledger_a.read_bytes(), ledger_b.read_bytes())
        self.assertEqual(Ledger.load(ledger_a).verify(), [])
        rules = [r for f in (tree_a / "compatibility").glob("*.rules.json") for r in json.loads(f.read_text())]
        generated = [r for r in rules if r.get("origin") == "GENERATED"]
        self.assertTrue(generated)
        self.assertTrue(all(r.get("fixer_ref") is None for r in generated))

    def test_no_new_fix_enabled(self):
        tree, _, _ = self._pipeline("run-fix")
        for path in (tree / "compatibility").glob("*.rules.json"):
            for row in json.loads(path.read_text(encoding="utf-8")):
                if row.get("origin") == "GENERATED":
                    self.assertNotEqual(row.get("maturity"), "FIX_ENABLED", row.get("id"))
                    self.assertIsNone(row.get("fixer_ref"), row.get("id"))
        for path in (tree / "candidates").glob("CR-*.json"):
            cand = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotEqual(cand["rule"].get("maturity"), "FIX_ENABLED")
            self.assertIsNone(cand["rule"].get("fixer_ref"))

    def test_rejected_candidates_do_not_block_regeneration(self):
        tree, ledger = self._fresh_run("reject-regen")
        code, _, err = self._generate(tree, ledger)
        self.assertEqual(code, 0, err)
        store_ev = tree / "candidates" / "evidence"
        first = {p.name: p.read_bytes() for p in store_ev.glob("EV-*.json")}
        self.assertTrue(first)
        _, out, _ = self._cli("candidates", "list", "--path", str(tree), "--json")
        rows = json.loads(out)
        for row in rows:
            code, _, err = self._cli("candidates", "reject", row["candidate_id"], "--path", str(tree),
                                     "--reason", "e2e")
            self.assertEqual(code, 0, err)
        records = {p.name: p.read_bytes() for p in (tree / "candidates").glob("CR-*.json")}
        shutil.copyfile(self.ledger_bytes_path, ledger)  # regenerate from the pristine ledger
        code, out, err = self._cli("candidates", "generate", "--path", str(tree), "--ledger", str(ledger),
                                   "--source", str(self.source_path), "--checked-on", "2026-11-08",
                                   "--at", CREATED, "--json")
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual(summary["existing"], len(rows), "every rejected candidate is reported as existing")
        self.assertEqual(summary["candidates"], 0, "rejected candidates are not resurrected")
        current_records = {p.name: p.read_bytes() for p in (tree / "candidates").glob("CR-*.json")}
        self.assertEqual(current_records, records, "REJECTED records must stay byte-identical")
        current = {p.name: p.read_bytes() for p in store_ev.glob("EV-*.json")}
        self.assertEqual(current, first, "regeneration must write no evidence for existing candidates")

        # A genuinely new change (one extra draft appended to the pristine ledger) still generates, under fresh ids.
        base = Ledger.load(self.ledger_bytes_path)
        keys = ("domain", "kind", "subject_key", "class", "detail", "locations", "proposed_by")
        drafts = [{k: rec[k] for k in keys} for rec in base.records()]
        # Copy a change that yields a candidate (its template matches) under a new subject, so it is a new change.
        donor = next(rec for rec in base.records() if rec["change_id"] == rows[0]["change_id"])
        drafts.append({**{k: donor[k] for k in keys}, "subject_key": "sale.demo.order.regen_extra"})
        Ledger.create(STEP, self.from_snap, self.to_snap, drafts, clock=lambda: CREATED).save(ledger)
        code, out, err = self._cli("candidates", "generate", "--path", str(tree), "--ledger", str(ledger),
                                   "--source", str(self.source_path), "--checked-on", "2026-11-08",
                                   "--at", CREATED, "--json")
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual((summary["candidates"], summary["existing"]), (1, len(rows)))
        fresh = set(store_ev.glob("EV-*.json")) - {tree / "candidates" / "evidence" / n for n in first}
        self.assertEqual(len(fresh), 1, "the new change gets exactly one fresh evidence record")
        for name, body in records.items():
            self.assertEqual((tree / "candidates" / name).read_bytes(), body, f"{name} must not change")

    def test_ai_off_by_default_no_gateway_call(self):
        tree, ledger = self._fresh_run("ai-off")
        self._generate(tree, ledger)
        code, _, err = self._cli("ai", "propose", "--path", str(tree), "--ledger", str(ledger))
        self.assertEqual(code, 2)
        self.assertIn("--ai", err)
        self.assertEqual(self.gateways, [], "no gateway may be built when AI is off")
        self.assertFalse((tree / "candidates" / "ai").exists())

    def test_ai_on_fills_only_allowed_fields(self):
        off_tree, off_ledger, _ = self._pipeline("ai-baseline")
        tree, ledger = self._fresh_run("ai-on")
        self._generate(tree, ledger)
        code, _, err = self._cli("ai", "propose", "--path", str(tree), "--ledger", str(ledger), "--ai",
                                 "--ai-provider", "fake", "--ai-model", "fake-model", "--ai-consent-send-code",
                                 "--ai-budget-job-tokens", "100000", "--ai-authorize", "fake=evidence_excerpt")
        self.assertEqual(code, 0, err)
        items = sorted((tree / "candidates" / "ai").glob("CR-*.json"))
        self.assertTrue(items)
        for path in items:
            item = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(sorted(item), AI_FIELDS)
            self.assertEqual(item["origin"], "AI_PROPOSED")
        self._accept_all(tree, ledger)
        self.assertEqual(_tree_bytes(tree), _tree_bytes(off_tree))

    def test_ai_on_without_grant_denied_names_category(self):
        tree, ledger = self._fresh_run("ai-nogrant")
        self._generate(tree, ledger)
        code, _, err = self._cli("ai", "propose", "--path", str(tree), "--ledger", str(ledger), "--ai",
                                 "--ai-provider", "fake", "--ai-model", "fake-model", "--ai-consent-send-code",
                                 "--ai-budget-job-tokens", "100000")
        self.assertEqual(code, 1)
        self.assertIn("evidence_excerpt", err)
        self.assertEqual(len(self.gateways), 1)
        self.assertEqual(self.gateways[0].provider.requests, [], "a denied request must not reach the provider")
        self.assertFalse((tree / "candidates" / "ai").exists())

    def test_kill_switch_blocks_transmission(self):
        tree, ledger = self._fresh_run("ai-kill")
        self._generate(tree, ledger)
        code, _, err = self._cli("ai", "propose", "--path", str(tree), "--ledger", str(ledger), "--ai",
                                 "--ai-provider", "fake", "--ai-model", "fake-model", "--ai-consent-send-code",
                                 "--ai-budget-job-tokens", "100000", "--ai-authorize", "fake=evidence_excerpt",
                                 "--ai-disable-external")
        self.assertEqual(code, 1)
        self.assertIn("kill switch", err)
        self.assertEqual(self.gateways, [])

    def test_validate_resulting_tree(self):
        tree, _, _ = self._pipeline("run-validate")
        code, out, err = self._cli("validate", "--path", str(tree))
        self.assertEqual(code, 0, out + err)
        self.assertIn("errors=0", out)

    def test_builtin_tree_untouched(self):
        def digest(root):
            return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
        before = digest(KNOWLEDGE_ROOT)
        self._pipeline("run-builtin-check")
        self.assertEqual(digest(KNOWLEDGE_ROOT), before)


if __name__ == "__main__":
    unittest.main()

"""TST-011-061 (REQ-KAP-016, REQ-KAP-017): `odooflux knowledge candidates ...` and `knowledge ai propose`.

Covers generate, list, accept, reject and resolve through `cli/knowledge.main` with the composition root's registries
(so `extract_toolkit` is attached, as in production). AI is exercised only with an attached gateway factory that
builds the real odooflux.ai gateway over the packaged `fake` provider. Nothing opens a socket. The built-in tree is
hash-checked: no command may write into it.
"""

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.ai.authorization import Authorizer
from odooflux.ai.gateway import GatewayConfig, build_gateway
from odooflux.ai.providers.catalog import load_catalog
from odooflux.builtins import build_registries
from odooflux.cli import kap_candidates
from odooflux.cli import knowledge as cli
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

DATA_DIRS = ("evidence", "compatibility", "official_sources")
CLOCK = lambda: "2026-11-08T00:00:00Z"  # noqa: E731
AT = "2026-11-08T10:00:00Z"
SOURCE = {"source_id": "odoo-community-17.0", "official": True, "url": "https://github.com/odoo/odoo/tree/" + "a" * 40,
          "repository": "odoo/odoo", "revision": "a" * 40, "branch": "17.0"}


def _snap(sid_hex, digest_hex):
    return {"snapshot_id": "ss-" + sid_hex, "snapshot_digest": digest_hex * 64}


def _draft(subject, kind, cls):
    return {"domain": "python_orm", "kind": kind, "subject_key": subject, "class": cls, "detail": {},
            "locations": [{"snapshot_id": "ss-0123456789ab", "path": "addons/sale/models/order.py",
                           "line": 12, "sha256": "cd" * 32}], "proposed_by": "DETERMINISTIC"}


def _tree_hash(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.tree = self.base / "tree"
        self.tree.mkdir()
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")
        self.ledger_path = self.base / "17-18.ledger.json"
        ledger = Ledger.create("17-18", _snap("111111111111", "1"), _snap("222222222222", "2"),
                               [_draft("sale.demo.order.compute", "method", "REMOVED"),
                                _draft("sale.demo.order.priority", "field", "REMOVED")], clock=CLOCK)
        ledger.save(self.ledger_path)
        self.source_path = self.base / "source.json"
        self.source_path.write_text(json.dumps(SOURCE), encoding="utf-8")
        self.registries = build_registries()
        self.factory_calls = []
        self.registries.ai_gateway_factory = self._factory

    def tearDown(self):
        self._tmp.cleanup()

    def _factory(self, config):
        """The composition root's gateway factory, here over the packaged fake provider."""
        self.factory_calls.append(config)
        script = self.base / "fake_script.json"
        script.write_text(json.dumps({"entries": [{"response": {
            "raw_text": json.dumps({"rationale": "Review the removed method.", "template_hint": ""})}}]}),
            encoding="utf-8")
        cfg = GatewayConfig(provider=config["provider"], model=config["model"],
                            grants=dict(config.get("authorizations") or {}),
                            kill_switch=bool(config.get("kill_switch")), fake_script=str(script))
        gateway = build_gateway(cfg, load_catalog(), environ={})
        return gateway, Authorizer(config.get("authorizations") or {})

    def run_cli(self, *argv, registries="default"):
        reg = self.registries if registries == "default" else registries
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), reg)
        return code, out.getvalue(), err.getvalue()

    def generate(self):
        return self.run_cli("candidates", "generate", "--path", str(self.tree), "--ledger", str(self.ledger_path),
                            "--source", str(self.source_path), "--checked-on", "2026-11-08")

    def candidate_files(self):
        return sorted((self.tree / "candidates").glob("CR-*.json"))

    def read_candidate(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))


class GenerateListTests(_Base):
    def test_generate_cli(self):
        code, out, err = self.generate()
        self.assertEqual(code, 0, err)
        files = self.candidate_files()
        self.assertTrue(files, out)
        for path in files:
            cand = self.read_candidate(path)
            self.assertEqual(cand["status"], "PROPOSED")
            self.assertIs(cand["detectors_verified"], True)
            self.assertIsNone(cand["rule"]["fixer_ref"])
            self.assertNotIn("FIX_ENABLED", json.dumps(cand))
        evidence = sorted((self.tree / "candidates" / "evidence").glob("EV-*.json"))
        self.assertEqual(len(evidence), len(files))

    def test_generate_leaves_verified_knowledge_untouched(self):
        before = _tree_hash(self.tree / "evidence") | _tree_hash(self.tree / "compatibility")
        self.generate()
        after = _tree_hash(self.tree / "evidence") | _tree_hash(self.tree / "compatibility")
        self.assertEqual(before, after)

    def test_generate_needs_toolkit(self):
        code, _, err = self.run_cli("candidates", "generate", "--path", str(self.tree), "--ledger",
                                    str(self.ledger_path), "--source", str(self.source_path),
                                    "--checked-on", "2026-11-08", registries=None)
        self.assertEqual(code, 2)
        self.assertIn("extract_toolkit", err)

    def test_refuses_builtin_tree_without_writing(self):
        before = _tree_hash(KNOWLEDGE_ROOT)
        code, _, err = self.run_cli("candidates", "generate", "--path", str(KNOWLEDGE_ROOT), "--ledger",
                                    str(self.ledger_path), "--source", str(self.source_path),
                                    "--checked-on", "2026-11-08")
        self.assertEqual(code, 2)
        self.assertIn("shipped", err)
        self.assertEqual(_tree_hash(KNOWLEDGE_ROOT), before)

    def test_second_generate_refused_while_pending(self):
        self.assertEqual(self.generate()[0], 0)
        code, _, err = self.generate()
        self.assertEqual(code, 1)
        self.assertIn("pending", err)

    def test_list_json_is_canonical(self):
        self.generate()
        code, out, _ = self.run_cli("candidates", "list", "--path", str(self.tree), "--json")
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual(sorted(r["candidate_id"] for r in rows),
                         [p.stem for p in self.candidate_files()])
        self.assertEqual(out, json.dumps(json.loads(out), sort_keys=True, indent=2) + "\n")


class AcceptRejectResolveTests(_Base):
    def setUp(self):
        super().setUp()
        self.generate()
        self.cid = self.candidate_files()[0].stem

    def accept(self, *extra):
        return self.run_cli("candidates", "accept", self.cid, "--path", str(self.tree), "--ledger",
                            str(self.ledger_path), "--author", "tester", "--at", AT, *extra)

    def test_accept_writes_rule_and_marks_candidate(self):
        code, _, err = self.accept()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read_candidate(self.tree / "candidates" / f"{self.cid}.json")["status"], "ACCEPTED")
        rules = [r for f in (self.tree / "compatibility").glob("*.rules.json") for r in json.loads(f.read_text())]
        self.assertTrue(any(r.get("origin") == "GENERATED" and r.get("maturity") in ("DRAFT", "DETECT_ONLY") for r in rules))
        self.assertEqual(Ledger.load(self.ledger_path).verify(), [])

    def test_accept_twice_refused(self):
        self.assertEqual(self.accept()[0], 0)
        code, _, err = self.accept()
        self.assertEqual(code, 1)
        self.assertIn("ACCEPTED", err)

    def test_accept_refuses_unverified_detectors(self):
        path = self.tree / "candidates" / f"{self.cid}.json"
        cand = self.read_candidate(path)
        cand["detectors_verified"] = False
        path.write_text(json.dumps(cand, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        before = _tree_hash(self.tree / "compatibility")
        code, _, err = self.accept()
        self.assertEqual(code, 1)
        self.assertIn("detectors_unverified", err)
        self.assertEqual(_tree_hash(self.tree / "compatibility"), before)

    def test_reject_records_reason_without_rule(self):
        before = _tree_hash(self.tree / "compatibility")
        code, _, _ = self.run_cli("candidates", "reject", self.cid, "--path", str(self.tree), "--reason",
                                  "not a real change")
        self.assertEqual(code, 0)
        cand = self.read_candidate(self.tree / "candidates" / f"{self.cid}.json")
        self.assertEqual((cand["status"], cand["rejected_reason"]), ("REJECTED", "not a real change"))
        self.assertEqual(_tree_hash(self.tree / "compatibility"), before)

    def test_resolve_without_recorded_conflict_refused(self):
        code, _, err = self.run_cli("candidates", "resolve", self.cid, "--path", str(self.tree), "--keep", "manual")
        self.assertEqual(code, 1)  # no recorded conflict for this candidate
        self.assertIn("no conflict", err)

    def test_unknown_candidate_is_usage_or_validation_error(self):
        code, _, _ = self.run_cli("candidates", "accept", "CR-doesnotexist", "--path", str(self.tree), "--ledger",
                                  str(self.ledger_path))
        self.assertEqual(code, 1)


class RegenerationTests(_Base):
    """Regenerating a change that already has a candidate never overwrites, resets or resurrects that record."""

    def setUp(self):
        super().setUp()
        self.pristine = self.base / "pristine-ledger.json"
        shutil.copyfile(self.ledger_path, self.pristine)  # generate and accept/reject both write the ledger
        self.assertEqual(self.generate()[0], 0)
        self.cids = [p.stem for p in self.candidate_files()]
        self.assertEqual(len(self.cids), 2)

    def regenerate(self, *extra):
        shutil.copyfile(self.pristine, self.ledger_path)
        return self.run_cli("candidates", "generate", "--path", str(self.tree), "--ledger", str(self.ledger_path),
                            "--source", str(self.source_path), "--checked-on", "2026-11-08", *extra)

    def record_bytes(self):
        return {p.name: p.read_bytes() for p in sorted((self.tree / "candidates").glob("CR-*.json"))}

    def evidence_bytes(self):
        return {p.name: p.read_bytes() for p in sorted((self.tree / "candidates" / "evidence").glob("EV-*.json"))}

    def test_regenerate_after_reject_and_accept_keeps_records_byte_identical(self):
        self.assertEqual(self.run_cli("candidates", "accept", self.cids[0], "--path", str(self.tree), "--ledger",
                                      str(self.ledger_path), "--author", "tester", "--at", AT)[0], 0)
        self.assertEqual(self.run_cli("candidates", "reject", self.cids[1], "--path", str(self.tree),
                                      "--reason", "not real")[0], 0)
        records, evidence = self.record_bytes(), self.evidence_bytes()
        code, out, err = self.regenerate("--json")
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual(summary["candidates"], 0)
        self.assertEqual(summary["existing"], 2)
        self.assertEqual(self.record_bytes(), records, "no candidate record may be rewritten")
        self.assertEqual(self.evidence_bytes(), evidence, "no evidence may be written for existing candidates")
        self.assertEqual(self.read_candidate(self.tree / "candidates" / f"{self.cids[0]}.json")["status"], "ACCEPTED")
        self.assertEqual(self.read_candidate(self.tree / "candidates" / f"{self.cids[1]}.json")["status"], "REJECTED")

    def test_regenerate_text_summary_names_existing_count(self):
        for cid in self.cids:
            self.assertEqual(self.run_cli("candidates", "reject", cid, "--path", str(self.tree), "--reason", "x")[0], 0)
        code, out, err = self.regenerate()
        self.assertEqual(code, 0, err)
        self.assertIn("2 existing", out)

    def test_regenerate_over_proposed_leaves_candidate_untouched(self):
        records = self.record_bytes()
        evidence = self.evidence_bytes()
        code, _, err = self.regenerate()
        self.assertEqual(code, 1, err)  # PROPOSED candidates are pending, so generate is refused before any write
        self.assertIn("pending", err)
        self.assertEqual(self.record_bytes(), records)
        self.assertEqual(self.evidence_bytes(), evidence)

    def test_new_change_after_rejection_gets_fresh_ids(self):
        for cid in self.cids:
            self.assertEqual(self.run_cli("candidates", "reject", cid, "--path", str(self.tree), "--reason", "x")[0], 0)
        records, evidence = self.record_bytes(), self.evidence_bytes()
        drafts = [_draft("sale.demo.order.compute", "method", "REMOVED"),
                  _draft("sale.demo.order.priority", "field", "REMOVED"),
                  _draft("sale.demo.order.name", "field", "REMOVED")]
        Ledger.create("17-18", _snap("111111111111", "1"), _snap("222222222222", "2"), drafts,
                      clock=CLOCK).save(self.ledger_path)
        code, out, err = self.run_cli("candidates", "generate", "--path", str(self.tree), "--ledger",
                                      str(self.ledger_path), "--source", str(self.source_path),
                                      "--checked-on", "2026-11-08", "--json")
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual((summary["candidates"], summary["existing"]), (1, 2))
        new = sorted(set(self.record_bytes()) - set(records))
        self.assertEqual(len(new), 1)
        for name, body in records.items():
            self.assertEqual(self.record_bytes()[name], body, f"{name} must not change")
        for name, body in evidence.items():
            self.assertEqual((self.tree / "candidates" / "evidence" / name).read_bytes(), body)
        fresh = sorted(set(self.evidence_bytes()) - set(evidence))
        self.assertEqual(len(fresh), 1)
        cand = self.read_candidate(self.tree / "candidates" / new[0])
        self.assertEqual(cand["rule"]["evidence"], [fresh[0].removesuffix(".json")])

    def test_write_candidate_refuses_overwrite_by_default(self):
        cid = self.cids[0]
        path = self.tree / "candidates" / f"{cid}.json"
        before = path.read_bytes()
        body = self.read_candidate(path)
        body["status"] = "PROPOSED"
        with self.assertRaises(ValueError) as caught:
            kap_candidates._write_candidate(self.tree, body)
        self.assertIn(cid, str(caught.exception))
        self.assertEqual(path.read_bytes(), before, "a refused overwrite writes nothing")

    def test_write_candidate_update_true_replaces_record(self):
        cid = self.cids[0]
        path = self.tree / "candidates" / f"{cid}.json"
        body = self.read_candidate(path)
        body["status"] = "REJECTED"
        kap_candidates._write_candidate(self.tree, body, update=True)
        self.assertEqual(self.read_candidate(path)["status"], "REJECTED")

    def test_write_candidate_new_id_is_written_without_update(self):
        body = self.read_candidate(self.tree / "candidates" / f"{self.cids[0]}.json")
        body["candidate_id"] = "CR-0123456789abcdef"
        kap_candidates._write_candidate(self.tree, body)
        self.assertTrue((self.tree / "candidates" / "CR-0123456789abcdef.json").is_file())


class AiProposeTests(_Base):
    def setUp(self):
        super().setUp()
        self.generate()
        self.cid = self.candidate_files()[0].stem

    def propose(self, *extra):
        return self.run_cli("ai", "propose", "--path", str(self.tree), "--ledger", str(self.ledger_path), *extra)

    def ai_on(self, *extra):
        return ("--ai", "--ai-provider", "fake", "--ai-model", "fake-model", "--ai-consent-send-code",
                "--ai-budget-job-tokens", "5000", *extra)

    def test_ai_requires_explicit_flag(self):
        before = _tree_hash(self.tree)
        code, _, err = self.propose()
        self.assertEqual(code, 2)
        self.assertIn("--ai", err)
        self.assertEqual(self.factory_calls, [])
        self.assertEqual(_tree_hash(self.tree), before)

    def test_ai_needs_consent(self):
        args = [a for a in self.ai_on() if a != "--ai-consent-send-code"]
        code, _, err = self.propose(*args)
        self.assertEqual(code, 2)
        self.assertIn("consent", err)
        self.assertEqual(self.factory_calls, [])

    def test_no_grant_denied_and_names_category(self):
        code, _, err = self.propose(*self.ai_on())
        self.assertEqual(code, 1)
        self.assertIn("evidence_excerpt", err)
        self.assertFalse((self.tree / "candidates" / "ai").exists())

    def test_kill_switch_blocks_with_no_transmission(self):
        code, _, err = self.propose(*self.ai_on("--ai-authorize", "fake=evidence_excerpt",
                                                "--ai-disable-external"))
        self.assertEqual(code, 1)
        self.assertIn("kill switch", err)
        self.assertFalse((self.tree / "candidates" / "ai").exists())

    def test_granted_proposal_stored_apart(self):
        before = self.read_candidate(self.tree / "candidates" / f"{self.cid}.json")
        code, _, err = self.propose(*self.ai_on("--ai-authorize", "fake=evidence_excerpt"))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read_candidate(self.tree / "candidates" / f"{self.cid}.json"), before)
        item = self.read_candidate(self.tree / "candidates" / "ai" / f"{self.cid}.json")
        self.assertEqual(item["origin"], "AI_PROPOSED")
        self.assertEqual(sorted(item), ["ai_proposed", "candidate_id", "change_id", "origin", "rationale",
                                        "template_hint"])

    def test_no_attached_gateway_is_usage_error(self):
        del self.registries.ai_gateway_factory
        code, _, err = self.propose(*self.ai_on("--ai-authorize", "fake=evidence_excerpt"))
        self.assertEqual(code, 2)
        self.assertIn("not attached", err)


class SourceIdentityCliTests(_Base):
    """A source spec with a local url has no repository field: identity comes from `repository` or from
    `expected_origin` (official clone). Without either the command refuses with exit 2 and writes nothing."""

    def _spec(self, name, **over):
        spec = {"source_id": "odoo-community-17.0", "official": True, "url": "local:" + str(self.base / "clone"),
                "kind": "GIT_COMMUNITY", "revision": "a" * 40, "branch": "17.0"}
        spec.update(over)
        path = self.base / name
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path

    def _generate_with(self, spec_path):
        return self.run_cli("candidates", "generate", "--path", str(self.tree), "--ledger", str(self.ledger_path),
                            "--source", str(spec_path), "--checked-on", "2026-11-08")

    def _evidence(self):
        return [self.read_candidate(p) for p in sorted((self.tree / "candidates" / "evidence").glob("EV-*.json"))]

    def test_expected_origin_gives_slug_and_origin_url(self):
        spec = self._spec("official.json", expected_origin="https://github.com/odoo/odoo")
        code, _, err = self._generate_with(spec)
        self.assertEqual(code, 0, err)
        evidence = self._evidence()
        self.assertTrue(evidence)
        for record in evidence:
            self.assertEqual(record["repository"], "odoo/odoo")
            self.assertEqual(record["url"], "https://github.com/odoo/odoo/tree/" + "a" * 40)
            self.assertIs(record["official"], True)
        self.assertNotIn(str(self.base), json.dumps(evidence))
        self.assertNotIn("local:", json.dumps(evidence))

    def test_explicit_repository_for_unofficial_source(self):
        spec = self._spec("fork.json", official=False, repository="maintainer/odoo-fork")
        code, _, err = self._generate_with(spec)
        self.assertEqual(code, 0, err)
        evidence = self._evidence()
        self.assertTrue(evidence)
        for record in evidence:
            self.assertEqual(record["repository"], "maintainer/odoo-fork")
            self.assertIs(record["official"], False)
            self.assertTrue(record["url"].startswith("source:odoo-community-17.0@"))
        for path in self.candidate_files():
            self.assertIs(self.read_candidate(path)["rule"]["review_required"], True)

    def test_no_identity_refused_with_usage_error_and_nothing_written(self):
        before = _tree_hash(self.tree)
        spec = self._spec("bare.json")
        code, out, err = self._generate_with(spec)
        self.assertEqual(code, 2, err)
        self.assertIn("repository", err)
        self.assertIn("expected_origin", err)
        self.assertNotIn(str(self.base), err)
        self.assertEqual(_tree_hash(self.tree), before)
        self.assertEqual(self.candidate_files(), [])

    def test_invalid_explicit_repository_refused_with_usage_error(self):
        before = _tree_hash(self.tree)
        for bad in ("local:/tmp/clone", "Odoo/odoo"):
            with self.subTest(repository=bad):
                code, _, err = self._generate_with(self._spec("bad.json", repository=bad))
                self.assertEqual(code, 2, err)
                self.assertIn("repository", err)
                self.assertEqual(_tree_hash(self.tree), before)



if __name__ == "__main__":
    unittest.main()

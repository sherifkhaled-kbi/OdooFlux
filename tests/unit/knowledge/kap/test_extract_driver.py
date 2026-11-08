"""TST-011-047 (REQ-KAP-011, REQ-KAP-013, REQ-KAP-004): extract driver and registry.

Uses in-memory trees written to temp directories, built into snapshots with the real `build_snapshot` and
`BlobStore`. Stub extractors keep the driver tests independent of the domain extractors (T048 to T050).
"""

import ast
import importlib
import json
import pkgutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.extract import classify as c
from odooflux.knowledge.extract import driver as d
from odooflux.knowledge.extract import domains
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.builtins import build_registries  # composition root: the document adapters the KAP tests inject
REGISTRIES = build_registries()
TOOLKIT = REGISTRIES.extract_toolkit

KINDS = ("ANALYZED", "EXCLUDED", "UNSUPPORTED", "FAILED")


class StubExtractor:
    """One fact per non-empty line. A line starting with BAD raises ParseFailure."""
    domain = "docs"  # a closed-enum domain: the accounting schema lists the allowed domains
    parser = "stub-parser"

    def handles(self, path, toolkit=None):
        return path.endswith(".stub")

    def facts(self, text, path, toolkit=None):
        out = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            if line.startswith("BAD"):
                raise d.ParseFailure("PARSE_ERROR", f"bad line {number}")
            if line.startswith("UNSUP"):
                raise d.Unsupported(f"unsupported line {number}")
            out.append({"subject_key": line.strip(), "kind": "item", "attrs": {}, "body_digest": "",
                        "line": number})
        return out


class DriverCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.store = BlobStore(self.base / "objects")

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self, name, files, revision="r1"):
        root = self.base / name
        root.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return build_snapshot(root, "src", revision, self.store, created_at="2026-01-01T00:00:00Z")

    def run_pair(self, before, after, registry=None, scope=None, limits=None):
        return d.extract_pair(before, after, scope, registry if registry is not None else [StubExtractor()],
                              store=self.store, step="01-02", limits=limits, toolkit=TOOLKIT)


class TestDriver(DriverCase):
    def test_unparsable_is_failed_not_skipped(self):
        before = self.snapshot("a", {"x/one.stub": "alpha\n"})
        after = self.snapshot("b", {"x/one.stub": "alpha\nBAD here\n", "x/two.stub": "beta\n"})
        result = self.run_pair(before, after)
        states = {f["path"]: f for f in result.accounting["files"]}
        self.assertEqual(states["x/one.stub"]["state"], "FAILED")
        self.assertEqual(states["x/one.stub"]["reason_code"], "PARSE_ERROR")
        self.assertIn("bad line 2", states["x/one.stub"]["error"])
        # the run continues: the other file is analysed
        self.assertEqual(states["x/two.stub"]["state"], "ANALYZED")
        # the failure reaches the drafts as UNKNOWN with the file as subject
        unknown = [c for c in result.drafts if c["class"] == "UNKNOWN"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]["subject_key"], "x/one.stub")
        self.assertEqual(unknown[0]["detail"]["reason"], "PARSE_FAILURE")

    def test_unsupported_content_is_visible_in_ledger(self):
        before = self.snapshot("a", {"x/one.stub": "alpha\n"})
        after = self.snapshot("b", {"x/one.stub": "alpha\nUNSUP menu\n"})
        result = self.run_pair(before, after)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("UNSUPPORTED", "NO_PARSER"))
        self.assertIn("unsupported line 2", state["error"])
        unknown = [c for c in result.drafts if c["class"] == "UNKNOWN"]
        self.assertEqual([c["subject_key"] for c in unknown], ["x/one.stub"])

    def test_no_parser_unsupported(self):
        before = self.snapshot("a", {})
        after = self.snapshot("b", {"x/notes.txt": "hello\n", "x/app.js": "let a;\n"})
        result = self.run_pair(before, after)
        states = {f["path"]: f for f in result.accounting["files"]}
        self.assertEqual((states["x/notes.txt"]["state"], states["x/notes.txt"]["reason_code"]),
                         ("UNSUPPORTED", "NO_PARSER"))
        self.assertEqual((states["x/app.js"]["state"], states["x/app.js"]["reason_code"]),
                         ("UNSUPPORTED", "NO_JS_ADAPTER"))

    def test_scope_exclusion_reason(self):
        before = self.snapshot("a", {})
        after = self.snapshot("b", {"in/one.stub": "alpha\n", "out/two.stub": "beta\n"})
        result = self.run_pair(before, after, scope=["in/*"])
        states = {f["path"]: f for f in result.accounting["files"]}
        self.assertEqual(states["in/one.stub"]["state"], "ANALYZED")
        self.assertEqual((states["out/two.stub"]["state"], states["out/two.stub"]["reason_code"]),
                         ("EXCLUDED", "OUT_OF_SCOPE_GLOB"))

    def test_too_large_is_excluded_with_reason(self):
        before = self.snapshot("a", {})
        after = self.snapshot("b", {"big.stub": "x" * 64})
        result = self.run_pair(before, after, limits={**c.load_config(), "max_file_bytes": 10})
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("EXCLUDED", "TOO_LARGE"))

    def test_accounting_invariant_and_finalized(self):
        before = self.snapshot("a", {"keep.stub": "one\n", "gone.stub": "two\n"})
        after = self.snapshot("b", {"keep.stub": "one\nthree\n", "new.txt": "x\n"})
        result = self.run_pair(before, after)
        doc = result.accounting
        self.assertEqual(sum(doc["totals"].values()), len(doc["files"]))
        self.assertEqual(len(doc["files"]), doc["independent_count"])
        self.assertEqual(doc["totals"]["PENDING"], 0)
        self.assertEqual({f["path"] for f in doc["files"]}, {"keep.stub", "gone.stub", "new.txt"})

    def test_extract_deterministic(self):
        before = self.snapshot("a", {"p.stub": "a\nb\n", "q.stub": "c\n"})
        after = self.snapshot("b", {"p.stub": "a\nz\n", "r.stub": "d\n", "n.txt": "t\n"})
        first = self.run_pair(before, after)
        second = self.run_pair(before, after)
        self.assertEqual(json.dumps(first.drafts, sort_keys=True), json.dumps(second.drafts, sort_keys=True))
        self.assertEqual(json.dumps(first.accounting, sort_keys=True), json.dumps(second.accounting, sort_keys=True))
        # drafts are ordered by (domain, kind, subject_key), the same key classify.classify_pair uses
        self.assertEqual([(c["domain"], c["kind"], c["subject_key"]) for c in first.drafts],
                         sorted((c["domain"], c["kind"], c["subject_key"]) for c in first.drafts))

    def test_no_code_execution(self):
        sentinel = self.base / "executed.marker"
        payload = f"open({str(sentinel)!r}, 'w').write('ran')\n"
        before = self.snapshot("a", {"addons/x/models/evil.py": ""})
        after = self.snapshot("b", {"addons/x/models/evil.py": payload})
        result = d.extract_pair(before, after, None, d.default_registry(), store=self.store, step="01-02", toolkit=TOOLKIT)
        self.assertFalse(sentinel.exists())
        # the file is parsed as data (ast), never run
        self.assertEqual([f["state"] for f in result.accounting["files"]], ["ANALYZED"])
        # the driver and domain modules never call eval, exec, compile or __import__
        forbidden = {"eval", "exec", "compile", "__import__"}
        package = Path(d.__file__).parent
        paths = [package / "driver.py"] + sorted((package / "domains").glob("*.py"))
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            self.assertFalse(calls & forbidden, f"{path.name} calls {calls & forbidden}")


class JsStubExtractor(StubExtractor):
    """Stands in for an adapter-backed JavaScript extractor: it handles `.js` files and models them."""
    domain = "js_owl"
    parser = "stub-js"

    def handles(self, path, toolkit=None):
        return path.endswith(".js")


class TestUnsupportedChanged(DriverCase):
    def test_changed_unsupported_files_get_unknown_drafts(self):
        before = self.snapshot("a", {"x/app.js": "let a;\n", "x/notes.txt": "old\n"})
        after = self.snapshot("b", {"x/app.js": "let a;\nlet b;\n", "x/notes.txt": "new\n"})
        result = self.run_pair(before, after)
        unknown = {c["subject_key"]: c for c in result.drafts if c["class"] == "UNKNOWN"}
        self.assertEqual(set(unknown), {"x/app.js", "x/notes.txt"})
        js = unknown["x/app.js"]
        self.assertEqual((js["domain"], js["kind"]), ("js_owl", "file"))
        self.assertEqual(js["detail"]["reason"], "UNSUPPORTED")
        self.assertIn("NO_JS_ADAPTER", js["detail"]["detail"])
        self.assertIn("changed on: from,to", js["detail"]["detail"])
        self.assertEqual({loc["snapshot_id"] for loc in js["locations"]},
                         {before["snapshot_id"], after["snapshot_id"]})
        txt = unknown["x/notes.txt"]
        self.assertIn("NO_PARSER", txt["detail"]["detail"])
        self.assertIn("changed on: from,to", txt["detail"]["detail"])
        # no extractor claims a .txt file: the catch-all domain, not "docs" (ITEM 3, was asserted nowhere before)
        self.assertEqual(txt["domain"], "other")

    def test_unclaimed_non_js_file_is_other_and_stays_unresolved(self):
        before = self.snapshot("a", {})
        after = self.snapshot("b", {"x/data.bin": "raw\n", "x/app.js": "let a;\n"})
        result = self.run_pair(before, after)
        unknown = {c["subject_key"]: c for c in result.drafts if c["class"] == "UNKNOWN"}
        self.assertEqual((unknown["x/data.bin"]["domain"], unknown["x/app.js"]["domain"]), ("other", "js_owl"))
        self.assertEqual(unknown["x/data.bin"]["class"], "UNKNOWN")
        accounted = {f["path"]: f["state"] for f in result.accounting["files"]}
        self.assertEqual(accounted, {"x/data.bin": "UNSUPPORTED", "x/app.js": "UNSUPPORTED"})

    def test_added_unsupported_file_names_only_the_to_side(self):
        before = self.snapshot("a", {})
        after = self.snapshot("b", {"x/new.js": "let a;\n"})
        result = self.run_pair(before, after)
        (draft,) = [c for c in result.drafts if c["class"] == "UNKNOWN"]
        self.assertIn("changed on: to", draft["detail"]["detail"])
        self.assertEqual([loc["snapshot_id"] for loc in draft["locations"]], [after["snapshot_id"]])

    def test_unsupported_unknown_lands_in_ledger_unresolved(self):
        before = self.snapshot("a", {})
        after = self.snapshot("b", {"x/app.js": "let a;\n"})
        result = self.run_pair(before, after)
        ledger = Ledger.create("01-02", before, after, result.drafts, clock=lambda: "2026-01-01T00:00:00Z")
        (record,) = [r for r in ledger.records() if r["subject_key"] == "x/app.js"]
        self.assertEqual((record["class"], record["disposition"]), ("UNKNOWN", "UNRESOLVED"))
        self.assertEqual(ledger.verify(), [])

    def test_unchanged_unsupported_file_has_no_record(self):
        before = self.snapshot("a", {"x/app.js": "let a;\n", "x/keep.txt": "same\n", "x/one.stub": "a\n"})
        after = self.snapshot("b", {"x/app.js": "let a;\n", "x/keep.txt": "same\n", "x/one.stub": "a\nb\n"})
        result = self.run_pair(before, after)
        self.assertEqual({f["path"] for f in result.accounting["files"]}, {"x/one.stub"})
        self.assertEqual([c for c in result.drafts if c["class"] == "UNKNOWN"], [])

    def test_supported_js_file_is_analysed_not_unknown(self):
        before = self.snapshot("a", {"x/app.js": "let a;\n"})
        after = self.snapshot("b", {"x/app.js": "let a;\nlet b;\n"})
        result = self.run_pair(before, after, registry=[JsStubExtractor()])
        self.assertEqual(result.accounting["files"][0]["state"], "ANALYZED")
        self.assertEqual([c for c in result.drafts if c["class"] == "UNKNOWN"], [])
        self.assertEqual([(c["class"], c["subject_key"]) for c in result.drafts], [("ADDED", "let b;")])


class TestDefaultRegistry(DriverCase):
    def test_default_registry_has_every_domain_module(self):
        expected = []
        for info in pkgutil.iter_modules(domains.__path__):
            module = importlib.import_module(f"{domains.__name__}.{info.name}")
            expected.extend(getattr(module, "EXTRACTORS", ()))
        self.assertTrue(expected)
        registered = [type(e) for e in d.default_registry()]
        missing = sorted({type(e).__name__ for e in expected if type(e) not in registered})
        self.assertEqual(missing, [])
        self.assertEqual(len(registered), len(expected))

    def test_default_registry_includes_js_reports_and_migrations(self):
        domains_in = {e.domain for e in d.default_registry()}
        self.assertTrue({"js_owl", "report_controller", "migration_script"} <= domains_in)


if __name__ == "__main__":
    unittest.main()

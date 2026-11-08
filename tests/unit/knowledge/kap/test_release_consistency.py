"""TST-011-082b (REQ-KAP-036, REQ-KAP-039; contracts/migration-integration.md "Resolution"): one knowledge release per
migrate run. Every knowledge reader that migrate reaches receives the root of the same handle, a reader never sees
`None` while a release is active, and a mismatched reader is detected.

The readers are instrumented with recording wrappers (monkeypatched module attributes that call the original). The
built-in case must give every reader the built-in tree.
"""

import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import odooflux.builtins as builtins_module
from odooflux.ai.integration import EscalationPass
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_active_knowledge
from odooflux.knowledge.release.builtin import builtin_digest
from odooflux.versions.registry.loader import load_version_data
from odooflux.validation.dependency.integrity import check_integrity
from odooflux.rules.xml import view_refs
from odooflux.validation.static import rng
from odooflux.validation.runtime import docker_env
from tests.unit.knowledge.kap.test_migrate_coverage import build_release, make_module, migrate

RELEASE_STEP = "17-18"
# The view rules declare a run input (target), so they run only through the opt-in path (REQ-KAP-017).
VIEW_RULES = ["--enable-rule", "*.xml.inherit-id-missing-in-target", "--enable-rule", "*.xml.xpath-anchor-missing-in-target"]
XML_VIEW = """<odoo>
  <record id="kbi_cov_view" model="ir.ui.view">
    <field name="name">kbi cov view</field>
    <field name="model">res.partner</field>
    <field name="inherit_id" ref="base.kbi_missing_view"/>
    <field name="arch" type="xml"><xpath expr="//field[@name='x']" position="after"/></field>
  </record>
</odoo>
"""


def assert_reader_roots(records: list, expected_root: Path) -> None:
    """Raise AssertionError naming every reader whose root is missing or is not `expected_root`."""
    bad = [r for r in records if r.get("root") is None or Path(r["root"]) != Path(expected_root)]
    if bad:
        raise AssertionError(f"readers without the active release root: {bad}")


def _recorder(reader: str, original, records: list, root_key: str = "knowledge_root"):
    def wrapper(*args, **kwargs):
        records.append({"reader": reader, "root": kwargs.get(root_key)})
        return original(*args, **kwargs)
    return wrapper


@contextlib.contextmanager
def instrumented(records: list, resolve_calls: list):
    """Patch every reader migrate reaches (and the resolver names) with recording wrappers."""

    def binder_wrapper(handle):
        loaded = load_active_knowledge(handle)
        tree = Path(handle.root) if handle.builtin else Path(handle.root) / "knowledge"
        records.append({"reader": "rule-binder", "root": tree, "release_id": handle.release_id,
                        "digest": handle.digest})
        return loaded

    def escalation_wrapper(layer3=None, knowledge_root=None):
        records.append({"reader": "ai-escalation", "root": knowledge_root})
        return EscalationPass(layer3=layer3, knowledge_root=knowledge_root)

    def resolve_wrapper(*args, **kwargs):
        resolve_calls.append(args or kwargs)
        return real_resolve(*args, **kwargs)

    from odooflux.cli import migrate as migrate_module
    from odooflux.knowledge.release import resolver
    real_resolve = resolver.resolve_knowledge
    patches = [
        mock.patch.object(builtins_module, "load_active_knowledge", new=binder_wrapper),
        mock.patch.object(builtins_module, "load_version_data",
                          new=_recorder("versions", load_version_data, records)),
        mock.patch.object(builtins_module, "check_integrity", new=_recorder("integrity", check_integrity, records)),
        mock.patch.object(builtins_module, "EscalationPass", new=escalation_wrapper),
        mock.patch.object(view_refs, "load_view_index",
                          new=_recorder("view-index", view_refs.load_view_index, records)),
        mock.patch.object(rng, "load_rng_map", new=_recorder("rng", rng.load_rng_map, records)),
        mock.patch.object(docker_env, "load_runtime_images",
                          new=_recorder("docker-env", docker_env.load_runtime_images, records)),
        mock.patch.object(migrate_module, "resolve_knowledge", new=resolve_wrapper),
        mock.patch.object(builtins_module, "resolve_knowledge", new=resolve_wrapper),
        mock.patch.object(resolver, "resolve_knowledge", new=resolve_wrapper),
    ]
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield


class ReleaseConsistencyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.module = make_module(self.base)
        views = self.module / "views"
        views.mkdir()
        (views / "kbi_cov_view.xml").write_text(XML_VIEW, encoding="utf-8")
        self.empty_home = self.base / "no-release"

    def tearDown(self):
        self._tmp.cleanup()

    def test_mismatched_reader_raises(self):
        """A reader that reports another root is detected by the consistency check."""
        expected = self.base / "releases" / "kr-000000000000" / "knowledge"
        other = self.base / "releases" / "kr-111111111111" / "knowledge"
        with self.assertRaises(AssertionError):
            assert_reader_roots([{"reader": "versions", "root": other}], expected)

    def test_reader_without_root_while_release_active_is_detected(self):
        """A reader called with no root (None) is detected: it would silently read the built-in tree."""
        expected = self.base / "releases" / "kr-000000000000" / "knowledge"
        with self.assertRaises(AssertionError):
            assert_reader_roots([{"reader": "view-index", "root": None}], expected)

    def test_resolution_happens_once_per_migrate(self):
        """One migrate run resolves the knowledge release exactly once (owner requirement 1)."""
        home, _rid, _digest, _dir = build_release(self.base, steps=[{"step": RELEASE_STEP,
                                                                       "completeness": "COMPLETE"}])
        records, calls = [], []
        with instrumented(records, calls):
            code, _report, _out, err = migrate(self.base, home, self.module)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(calls), 1, f"resolve_knowledge called {len(calls)} times")

    def test_active_release_every_reader_gets_the_same_root(self):
        """All readers see the root of the one handle; the report carries the same release id and digest."""
        home, rid, digest, release_dir = build_release(self.base, steps=[{"step": RELEASE_STEP,
                                                                           "completeness": "COMPLETE"}])
        records, calls = [], []
        with instrumented(records, calls):
            code, report, _out, err = migrate(self.base, home, self.module, extra=VIEW_RULES)
        self.assertEqual(code, 0, err)
        expected_tree = release_dir / "knowledge"
        readers = {r["reader"] for r in records}
        self.assertTrue({"rule-binder", "versions", "integrity", "ai-escalation", "view-index"} <= readers, readers)
        for record in records:
            if record["reader"] == "rule-binder":
                self.assertEqual((record["release_id"], record["digest"]), (rid, digest))
        assert_reader_roots(records, expected_tree)
        self.assertEqual((report["knowledge_release"]["release_id"], report["knowledge_release"]["digest"]),
                         (rid, digest))

    def test_builtin_every_reader_gets_the_builtin_tree(self):
        """No active release: every reader gets the built-in tree (None or KNOWLEDGE_ROOT, both the built-in)."""
        records, calls = [], []
        with instrumented(records, calls):
            code, report, _out, err = migrate(self.base, self.empty_home, self.module, extra=VIEW_RULES)
        self.assertEqual(code, 0, err)
        self.assertIn("view-index", {r["reader"] for r in records})
        for record in records:
            if record["reader"] == "rule-binder":
                self.assertTrue(record["release_id"] == "builtin" and record["digest"] == builtin_digest())
                continue
            self.assertIn(record["root"], (None, KNOWLEDGE_ROOT), record)
        self.assertEqual(report["knowledge_release"]["release_id"], "builtin")


if __name__ == "__main__":
    unittest.main()

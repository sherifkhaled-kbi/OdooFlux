"""TST-011-032 (REQ-KAP-006, REQ-KAP-008, REQ-KAP-009): source registry and status machine.

Covers the status transitions, forced-unofficial OCA/OpenUpgrade, the allow-list (prefix match, fail closed) and
the 40-hex revision rule for git kinds. Stdlib only, no network.
"""

import unittest

from odooflux.knowledge.acquisition import sources as s
from odooflux.knowledge.acquisition.blobstore import SourceError

REV = "1" * 40


def _spec(**overrides) -> dict:
    spec = {
        "source_id": "odoo-community-17.0",
        "kind": "GIT_COMMUNITY",
        "official": True,
        "url": "https://github.com/odoo/odoo/",
        "licence_access": "PUBLIC_OPEN",
        "licence_id": "LGPL-3.0",
        "branch": "17.0",
        "revision": REV,
        "scope": {"modules": "*", "include": ["**/*.py"], "exclude": [], "file_kinds": ["python"]},
        "retrieved_at": None,
        "checksum": None,
        "status": "DECLARED",
        "failure_reason": None,
        "required": True,
    }
    spec.update(overrides)
    return spec


class SourceRegistryTests(unittest.TestCase):
    def test_status_transitions(self):
        reg = s.SourceRegistry()
        reg.add(_spec())
        self.assertEqual(reg.get("odoo-community-17.0")["status"], "DECLARED")
        # VERIFIED cannot be reached without RETRIEVED
        with self.assertRaises(s.RegistryError):
            reg.transition("odoo-community-17.0", "VERIFIED")
        reg.transition("odoo-community-17.0", "RETRIEVED")
        reg.transition("odoo-community-17.0", "VERIFIED")
        self.assertEqual(reg.get("odoo-community-17.0")["status"], "VERIFIED")
        # VERIFIED is terminal and immutable
        for target in ("FAILED", "UNAVAILABLE", "DECLARED", "RETRIEVED"):
            with self.subTest(target=target), self.assertRaises(s.RegistryError):
                reg.transition("odoo-community-17.0", target, failure_reason="IO_ERROR")

    def test_failure_needs_reason_and_can_retry(self):
        reg = s.SourceRegistry()
        reg.add(_spec())
        with self.assertRaises(s.RegistryError):
            reg.transition("odoo-community-17.0", "FAILED")  # failure_reason is required
        reg.transition("odoo-community-17.0", "FAILED", failure_reason="REVISION_UNAVAILABLE")
        rec = reg.get("odoo-community-17.0")
        self.assertEqual((rec["status"], rec["failure_reason"]), ("FAILED", "REVISION_UNAVAILABLE"))
        reg.transition("odoo-community-17.0", "DECLARED")  # explicit retry
        reg.transition("odoo-community-17.0", "UNAVAILABLE", failure_reason="IO_ERROR")
        self.assertEqual(reg.get("odoo-community-17.0")["status"], "UNAVAILABLE")

    def test_skipped_unauthorized_is_terminal(self):
        reg = s.SourceRegistry()
        reg.add(_spec(source_id="odoo-enterprise-17.0", kind="ENTERPRISE_LOCAL", official=False,
                      url="local:/srv/enterprise", licence_access="UNKNOWN", licence_id="none"))
        reg.transition("odoo-enterprise-17.0", "SKIPPED_UNAUTHORIZED", failure_reason="AUTH_REQUIRED")
        with self.assertRaises(s.RegistryError):
            reg.transition("odoo-enterprise-17.0", "RETRIEVED")

    def test_add_requires_declared_and_closed_schema(self):
        reg = s.SourceRegistry()
        with self.assertRaises(s.RegistryError):
            reg.add(_spec(status="VERIFIED"))
        with self.assertRaises(s.RegistryError):
            reg.add(_spec(extra_field=1))
        reg.add(_spec())
        with self.assertRaises(s.RegistryError):  # duplicate source_id
            reg.add(_spec())

    def test_oca_forced_unofficial(self):
        reg = s.SourceRegistry()
        reg.add(_spec(source_id="oca-web-17.0", kind="OCA", official=True, url="local:/srv/oca-web"))
        self.assertFalse(reg.get("oca-web-17.0")["official"])
        reg.add(_spec(source_id="openupgrade-17.0", kind="OPENUPGRADE", official=True,
                      url="local:/srv/openupgrade"))
        self.assertFalse(reg.get("openupgrade-17.0")["official"])
        # the normalisation itself does not depend on the registry
        self.assertFalse(s.normalize(_spec(kind="OCA", official=True))["official"])
        # official=true is only valid for the Odoo community repos
        problems = s.validate_spec(_spec(official=True, url="https://github.com/evil/odoo/"), s.load_allow_list())
        self.assertTrue(problems)

    def test_allowlist_enforced(self):
        allow = s.load_allow_list()
        self.assertIn("https://github.com/odoo/odoo/", allow)
        s.require_allowed("https://github.com/odoo/odoo/", allow, "odoo-community-17.0")
        s.require_allowed("local:/srv/odoo", allow, "odoo-community-17.0")  # local inputs skip the allow-list
        with self.assertRaises(SourceError) as ctx:
            s.require_allowed("https://github.com/evil/odoo/", allow, "odoo-community-17.0")
        self.assertEqual(ctx.exception.code, "NOT_ALLOWLISTED")
        # prefix match must end at the slash: a look-alike repository is not allow-listed
        with self.assertRaises(SourceError):
            s.require_allowed("https://github.com/odoo/odoo-evil/", allow, "odoo-community-17.0")
        reg = s.SourceRegistry()
        with self.assertRaises(s.RegistryError):
            reg.add(_spec(url="https://github.com/evil/odoo/", official=False))

    def test_sha_required_for_git(self):
        reg = s.SourceRegistry()
        for bad in ("17.0", "1" * 39, "A" * 40, "sha256:" + "a" * 64):
            with self.subTest(revision=bad), self.assertRaises(s.RegistryError):
                reg.add(_spec(source_id="odoo-community-bad", revision=bad))
        # a directory or pack source uses a content digest instead
        reg.add(_spec(source_id="local-dir-17.0", kind="DIRECTORY", official=False, url="local:/srv/kb",
                      revision="sha256:" + "a" * 64))
        self.assertEqual(reg.get("local-dir-17.0")["revision"], "sha256:" + "a" * 64)

    def test_adapter_registry_is_data_driven(self):
        class Fake:
            kind = "DIRECTORY"

        # the registry is process-global; other modules register real adapters at import, so save and restore
        saved = s.ADAPTERS.pop("SNAPSHOT_PACK", None)
        self.assertNotIn("SNAPSHOT_PACK", s.ADAPTERS)
        try:
            s.register_adapter("SNAPSHOT_PACK", Fake())
            self.assertIs(s.ADAPTERS["SNAPSHOT_PACK"].__class__, Fake)
        finally:
            s.ADAPTERS.pop("SNAPSHOT_PACK", None)
            if saved is not None:
                s.ADAPTERS["SNAPSHOT_PACK"] = saved
        with self.assertRaises(ValueError):
            s.register_adapter("GITHUB", Fake())


if __name__ == "__main__":
    unittest.main()

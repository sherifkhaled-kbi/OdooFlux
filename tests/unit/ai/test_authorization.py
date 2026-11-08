"""TST-007-019 (FR-019): explicit authorization names the provider and the data categories."""

import unittest

from ._setup_path import SRC  # noqa: F401
from odooflux.ai.authorization import AuthorizationError, Authorizer, parse_grants

ALL = ("source_python", "source_xml", "evidence_excerpt")


class AuthorizationTests(unittest.TestCase):
    def test_missing_when_no_grant_at_all(self):
        self.assertEqual(Authorizer({}).check("alpha", "external", ("source_python",)), "authorization_missing")

    def test_provider_mismatch_when_only_another_provider_is_granted(self):
        a = Authorizer({"beta": ["source_python"]})
        self.assertEqual(a.check("alpha", "external", ("source_python",)), "authorization_provider_mismatch")

    def test_missing_names_only_the_uncovered_categories(self):
        a = Authorizer({"alpha": ["source_python"]})
        self.assertEqual(a.missing("alpha", ("source_python", "evidence_excerpt")), ("evidence_excerpt",))
        self.assertEqual(a.grants["alpha"], frozenset({"source_python"}))  # a check never widens the grant

    def test_category_denied(self):
        a = Authorizer({"alpha": ["source_python"]})
        self.assertEqual(a.check("alpha", "external", ("source_python", "evidence_excerpt")),
                         "authorization_category_denied")
        self.assertEqual(a.check("alpha", "external", ("source_xml",)), "authorization_category_denied")

    def test_granted_provider_and_categories_pass(self):
        a = Authorizer({"alpha": ALL})
        self.assertIsNone(a.check("alpha", "external", ("source_python", "evidence_excerpt")))

    def test_unknown_category_is_always_denied(self):
        a = Authorizer({"alpha": ALL})
        for cat in ("credentials", "secrets", "database_dump", "customer_data", "whole_file"):
            self.assertEqual(a.check("alpha", "external", (cat,)), "authorization_category_denied", cat)

    def test_local_and_fake_providers_need_no_grant(self):
        a = Authorizer({})
        self.assertIsNone(a.check("loc", "local", ("source_python",)))
        self.assertIsNone(a.check("fake", "fake", ("source_python",)))

    def test_request_with_no_categories_is_denied_for_external(self):
        self.assertEqual(Authorizer({"alpha": ALL}).check("alpha", "external", ()), "authorization_category_denied")

    def test_forbidden_categories_cannot_be_granted(self):
        for cat in ("credentials", "secrets", "database_dump", "customer_data"):
            with self.assertRaises(AuthorizationError) as cm:
                parse_grants(f"alpha={cat}")
            self.assertEqual(cm.exception.code, "forbidden_category")

    def test_unknown_category_in_a_grant_is_rejected(self):
        with self.assertRaises(AuthorizationError) as cm:
            parse_grants("alpha=source_cobol")
        self.assertEqual(cm.exception.code, "unknown_category")

    def test_parse_grants_merges_and_validates_shape(self):
        self.assertEqual(parse_grants(["alpha=source_python", "alpha=source_xml,evidence_excerpt", "beta=source_xml"]),
                         {"alpha": ["evidence_excerpt", "source_python", "source_xml"], "beta": ["source_xml"]})
        for bad in ("alpha", "=source_python", "alpha="):
            with self.assertRaises(AuthorizationError):
                parse_grants(bad)


if __name__ == "__main__":
    unittest.main()

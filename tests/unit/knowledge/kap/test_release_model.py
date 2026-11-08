"""TST-011-004 (REQ-KAP-022, REQ-KAP-026): release id derivation, KnowledgeHandle built-in defaults, state enum, errors."""

import unittest
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.model import (
    LOADABLE_STATES,
    KnowledgeHandle,
    KnowledgeReleaseError,
    ReleaseState,
    builtin_handle,
    release_id_from_digest,
)

DIGEST = "ab" * 32


class ReleaseIdTests(unittest.TestCase):
    def test_release_id_from_digest(self):
        self.assertEqual(release_id_from_digest(DIGEST), "kr-" + "ab" * 6)
        self.assertEqual(release_id_from_digest("0123456789abcdef" * 4), "kr-0123456789ab")
        # same digest gives the same id; a different digest gives a different id
        self.assertEqual(release_id_from_digest(DIGEST), release_id_from_digest(DIGEST))
        self.assertNotEqual(release_id_from_digest(DIGEST), release_id_from_digest("cd" * 32))
        for bad in ("", "xyz", "AB" * 32, "ab" * 31, "ab" * 33):
            with self.subTest(digest=bad[:10]):
                with self.assertRaises(ValueError):
                    release_id_from_digest(bad)

    def test_handle_builtin_defaults(self):
        handle = builtin_handle()
        self.assertIsInstance(handle, KnowledgeHandle)
        self.assertEqual(handle.root, KNOWLEDGE_ROOT)
        self.assertIsInstance(handle.root, Path)
        self.assertEqual(handle.release_id, "builtin")
        self.assertIsNone(handle.digest)
        self.assertTrue(handle.builtin)
        self.assertIsNone(handle.completeness)
        self.assertEqual(handle.steps, {})

    def test_handle_fields_for_release(self):
        handle = KnowledgeHandle(root=Path("/kb/releases/kr-x"), release_id="kr-x", digest=DIGEST, builtin=False,
                                 completeness="COMPLETE", steps={"17-18": "COMPLETE"})
        self.assertFalse(handle.builtin)
        self.assertEqual(handle.steps["17-18"], "COMPLETE")

    def test_state_enum_and_loadable(self):
        self.assertEqual({s.value for s in ReleaseState}, {"STAGED", "INSTALLED", "ACTIVE", "REMOVED"})
        self.assertEqual(LOADABLE_STATES, {ReleaseState.INSTALLED, ReleaseState.ACTIVE})

    def test_error_class(self):
        self.assertTrue(issubclass(KnowledgeReleaseError, Exception))
        with self.assertRaises(KnowledgeReleaseError):
            raise KnowledgeReleaseError("corrupt release")


if __name__ == "__main__":
    unittest.main()

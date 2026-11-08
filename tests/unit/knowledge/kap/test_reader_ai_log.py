"""TST-011-079 (REQ-KAP-036, REQ-KAP-002): the runtime log classifier and the AI escalation metadata take an optional
knowledge root; the default is the built-in tree. The AI authorization tests are not touched by this change."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.ai import integration
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.validation.runtime import log_classifier as lc

RELEASE_PATTERNS = {"schema": "runtime_log_patterns", "patterns": [
    {"id": "release.only", "class": "release_custom", "pattern": "RELEASE_ONLY_MARK",
     "version_range": {"from": "16.0", "to": "19.0"}},
]}
RELEASE_RULE = {"id": "REL-AI-1", "step": "17-18", "category": "xml", "maturity": "DETECT_ONLY",
                "ai_eligible": True, "review_required": False, "message": "release rule"}
LOG_LINE = "2024-05-01 10:00:00,000 1 ERROR db odoo.modules.loading: RELEASE_ONLY_MARK happened\n"


def _release_tree(root: Path):
    (root / "compatibility").mkdir(parents=True, exist_ok=True)
    (root / "compatibility" / "runtime_log_patterns.json").write_text(json.dumps(RELEASE_PATTERNS), encoding="utf-8")
    (root / "compatibility" / "release.rules.json").write_text(json.dumps([RELEASE_RULE]), encoding="utf-8")


class LogClassifierRootTests(unittest.TestCase):
    def test_default_path_unchanged(self):
        self.assertEqual(lc.load_patterns(), lc.load_patterns(knowledge_root=KNOWLEDGE_ROOT))
        self.assertEqual(lc.classify_text(LOG_LINE, "18.0"),
                         lc.classify_text(LOG_LINE, "18.0", knowledge_root=KNOWLEDGE_ROOT))

    def test_release_root_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _release_tree(root)
            self.assertEqual([p["id"] for p in lc.load_patterns(knowledge_root=root)], ["release.only"])
            found = lc.classify_text(LOG_LINE, "18.0", knowledge_root=root)
            self.assertEqual([(e.error_class, e.pattern_id) for e in found], [("release_custom", "release.only")])
            self.assertNotIn("release.only", [p["id"] for p in lc.load_patterns()])


class AiMetadataRootTests(unittest.TestCase):
    def test_default_path_unchanged(self):
        default = integration.EscalationPass()._metadata()
        explicit = integration.EscalationPass(knowledge_root=KNOWLEDGE_ROOT)._metadata()
        self.assertEqual(sorted(default), sorted(explicit))
        self.assertNotIn("REL-AI-1", default)

    def test_release_root_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _release_tree(root)
            metadata = integration.EscalationPass(knowledge_root=root)._metadata()
            self.assertEqual(list(metadata), ["REL-AI-1"])
            self.assertTrue(metadata["REL-AI-1"].ai_eligible)


if __name__ == "__main__":
    unittest.main()

"""TST-011-076 (REQ-KAP-036, REQ-KAP-042): the runtime image reader takes an optional knowledge root; the default is the
built-in `runtime_images.json`. No Docker is started here: only the pure image-map helpers are exercised."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.validation.runtime import docker_env as de

RELEASE_IMAGES = {
    "images": {"19.0": {"repository": "example/odoo", "tag": "19.0-release", "tag_status": "UNVERIFIED"}},
    "postgres": {"reference": "example/postgres:16", "tag_status": "UNVERIFIED"},
}


class DockerEnvReaderRootTests(unittest.TestCase):
    def test_default_path_unchanged(self):
        self.assertEqual(KNOWLEDGE_ROOT / "compatibility" / "runtime_images.json", de.IMAGES_FILE)
        self.assertEqual(de.load_runtime_images(), de.load_runtime_images(knowledge_root=KNOWLEDGE_ROOT))
        self.assertEqual(de.image_for_version("19.0"),
                         de.image_for_version("19.0", knowledge_root=KNOWLEDGE_ROOT))
        self.assertEqual(de.postgres_reference(), de.postgres_reference(knowledge_root=KNOWLEDGE_ROOT))

    def test_release_root_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "compatibility").mkdir()
            (root / "compatibility" / "runtime_images.json").write_text(json.dumps(RELEASE_IMAGES), encoding="utf-8")
            self.assertEqual(de.load_runtime_images(knowledge_root=root), RELEASE_IMAGES)
            self.assertEqual(de.image_for_version("19.0", knowledge_root=root), "example/odoo:19.0-release")
            self.assertIsNone(de.image_for_version("17.0", knowledge_root=root))
            self.assertEqual(de.postgres_reference(knowledge_root=root), "example/postgres:16")
            self.assertNotEqual(de.image_for_version("19.0"), "example/odoo:19.0-release")


if __name__ == "__main__":
    unittest.main()

"""TST-011-045 (REQ-KAP-012, REQ-KAP-011): classification of fact differences and `extract/config.json`.

Facts are built in memory: `{domain, path, subject_key, kind, attrs, body_digest, line, sha256}`. Every class the
classifier can emit has a case; RENAMED_CANDIDATE and REPLACEMENT_CANDIDATE come from `rename.py` (T046), and the
config records which stage owns which class, so the union covers the closed class enum.
"""

import json
import unittest

from odooflux.knowledge.extract import classify as c
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

FROM = {"snapshot_id": "ss-" + "ab" * 6}
TO = {"snapshot_id": "ss-" + "cd" * 6}
SHA = "1" * 64


def _fact(path, subject, kind="method", attrs=None, body="b1", line=1, domain="python_orm"):
    return {"domain": domain, "path": path, "subject_key": subject, "kind": kind, "attrs": dict(attrs or {}),
            "body_digest": body, "line": line, "sha256": SHA}


def _classify(before, after, failures=()):
    return c.classify_pair(before, after, from_snapshot_id=FROM["snapshot_id"], to_snapshot_id=TO["snapshot_id"],
                           failures=failures)


def _only(drafts):
    assert len(drafts) == 1, drafts
    return drafts[0]


class ClassifyTests(unittest.TestCase):
    def test_every_class_has_case(self):
        cases = {
            "ADDED": _classify([], [_fact("a/m.py", "res.x::method::f")]),
            "REMOVED": _classify([_fact("a/m.py", "res.x::method::f")], []),
            "SIGNATURE_CHANGED": _classify([_fact("a/m.py", "s", attrs={"args": ["a"]})],
                                           [_fact("a/m.py", "s", attrs={"args": ["a", "b"]})]),
            "BEHAVIOUR_CHANGED": _classify([_fact("a/m.py", "s", body="b1")], [_fact("a/m.py", "s", body="b2")]),
            "MOVED": _classify([_fact("a/m.py", "s")], [_fact("a/n.py", "s")]),
            "DEPRECATED": _classify([_fact("a/m.py", "s")], [_fact("a/m.py", "s", attrs={"deprecated": True})]),
            "UNKNOWN": _classify([], [], failures=[{"domain": "python_orm", "path": "a/bad.py", "sha256": SHA,
                                                    "detail": "SyntaxError"}]),
        }
        for cls, drafts in cases.items():
            with self.subTest(cls=cls):
                self.assertEqual([d["class"] for d in drafts], [cls])
        # every class of the closed enum is produced here or by rename.py (declared in config)
        config = c.load_config()
        schema = json.loads((KNOWLEDGE_ROOT / "schemas" / "change_ledger.schema.json").read_text("utf-8"))
        enum = set(schema["properties"]["entries"]["items"]["properties"]["class"]["enum"])
        covered = set(config["classes_by_stage"]["classify"]) | set(config["classes_by_stage"]["rename"])
        self.assertEqual(covered, enum)
        self.assertEqual(set(config["classes_by_stage"]["classify"]), set(cases))

    def test_signature_vs_behaviour(self):
        sig = _only(_classify([_fact("a/m.py", "s", attrs={"args": ["a"]})],
                              [_fact("a/m.py", "s", attrs={"args": ["a", "b"]}, body="b2")]))
        self.assertEqual(sig["class"], "SIGNATURE_CHANGED", "signature wins when both change")
        beh = _only(_classify([_fact("a/m.py", "s", attrs={"args": ["a"]}, body="b1")],
                              [_fact("a/m.py", "s", attrs={"args": ["a"]}, body="b2")]))
        self.assertEqual(beh["class"], "BEHAVIOUR_CHANGED")
        # a decorator is not a signature key for methods, so it is a behaviour change
        dec = _only(_classify([_fact("a/m.py", "s", attrs={"decorators": []})],
                              [_fact("a/m.py", "s", attrs={"decorators": ["api.model"]})]))
        self.assertEqual(dec["class"], "BEHAVIOUR_CHANGED")
        field = _only(_classify([_fact("a/m.py", "f", kind="field", attrs={"type": "Char"})],
                                [_fact("a/m.py", "f", kind="field", attrs={"type": "Text"})]))
        self.assertEqual(field["class"], "SIGNATURE_CHANGED")
        self.assertEqual(field["detail"]["changed"], ["type"])
        self.assertEqual(field["detail"]["from"], {"type": "Char"})
        self.assertEqual(field["detail"]["to"], {"type": "Text"})
        self.assertEqual(_classify([_fact("a/m.py", "s")], [_fact("a/m.py", "s")]), [], "no change, no draft")

    def test_moved(self):
        drafts = _classify([_fact("addons/a/models/x.py", "res.x::method::f")],
                           [_fact("addons/a/models/y.py", "res.x::method::f")])
        moved = _only(drafts)
        self.assertEqual(moved["class"], "MOVED")
        self.assertEqual(moved["locations"][0]["path"], "addons/a/models/y.py")
        self.assertEqual(moved["locations"][0]["snapshot_id"], TO["snapshot_id"])
        # moved means identical attrs and body; a body change at the new path is not a move
        drafts = _classify([_fact("addons/a/models/x.py", "res.x::method::f", body="b1")],
                           [_fact("addons/a/models/y.py", "res.x::method::f", body="b2")])
        # same change id (domain, kind, subject_key) on both sides: one ambiguous UNKNOWN, both locations kept
        self.assertEqual([d["class"] for d in drafts], ["UNKNOWN"])
        self.assertEqual(len(drafts[0]["locations"]), 2)

    def test_deprecated(self):
        drafts = _classify([_fact("a/m.py", "s")], [_fact("a/m.py", "s", attrs={"deprecated": "17.0"})])
        self.assertEqual(_only(drafts)["class"], "DEPRECATED")
        already = _classify([_fact("a/m.py", "s", attrs={"deprecated": "16.0"})],
                            [_fact("a/m.py", "s", attrs={"deprecated": "16.0"})])
        self.assertEqual(already, [], "a deprecation that was already there is not a new change")

    def test_parse_failure_is_unknown_not_skipped(self):
        drafts = _classify([], [], failures=[{"domain": "python_orm", "path": "a/bad.py", "sha256": SHA,
                                              "detail": "SyntaxError"}])
        unknown = _only(drafts)
        self.assertEqual(unknown["class"], "UNKNOWN")
        self.assertEqual(unknown["subject_key"], "a/bad.py")
        self.assertEqual(unknown["locations"][0]["snapshot_id"], TO["snapshot_id"])

    def test_duplicate_subject_is_unknown(self):
        drafts = _classify([], [_fact("a/m.py", "s"), _fact("a/m.py", "s", line=9)])
        self.assertEqual([d["class"] for d in drafts], ["UNKNOWN"])
        self.assertEqual(len(drafts[0]["locations"]), 2, "both locations are kept")

    def test_config_thresholds(self):
        config = c.load_config()
        self.assertEqual(config["rename_threshold"], 0.8)
        self.assertEqual(config["max_file_bytes"], 2 * 1024 * 1024)
        self.assertEqual(c.file_reason(10, config), None)
        self.assertEqual(c.file_reason(config["max_file_bytes"] + 1, config), "TOO_LARGE")
        self.assertIn("python_orm", config["domains"])


if __name__ == "__main__":
    unittest.main()

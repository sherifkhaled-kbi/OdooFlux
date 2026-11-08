"""TST-011-003 (REQ-KAP-023): package entry-name validator implements P01 of knowledge-package-format."""

import unittest

from odooflux.knowledge.package.limits import (
    MAX_DEPTH,
    MAX_PATH_LEN,
    EntryNameError,
    entry_key,
    validate_entry_name,
)

REJECTED = {
    "empty": "",
    "absolute": "/etc/passwd",
    "absolute_knowledge": "/knowledge/evidence/EV-001.json",
    "drive_letter": "C:/knowledge/x.json",
    "drive_letter_no_slash": "c:x.json",
    "backslash": "knowledge\\evidence\\x.json",
    "backslash_trailing": "a\\",
    "traversal_leading": "../x.json",
    "traversal_middle": "knowledge/../../etc/x.json",
    "traversal_trailing": "knowledge/..",
    "dot_segment_leading": "./x.json",
    "dot_segment_middle": "a/./b.json",
    "dot_only": ".",
    "dotdot_only": "..",
    "empty_segment_double_slash": "a//b.json",
    "empty_segment_trailing": "a/b/",
    "nul": "a\x00b.json",
    "nul_only": "\x00",
    "non_nfc": "e\u0301cole.json",
    "not_utf8_encodable": "bad\udc80name.json",
    "too_long": "a" * (MAX_PATH_LEN + 1),
    "too_deep": "/".join(["d"] * (MAX_DEPTH + 1)) + "/x.json",
}

ACCEPTED = [
    "knowledge/evidence/EV-001.json",
    "x.json",
    "provenance/sources.json",
    "integrity/SHA256SUMS",
    "knowledge/\u00e9cole.json",  # NFC precomposed
    "a" * MAX_PATH_LEN,
    "/".join(["d"] * MAX_DEPTH),  # depth exactly at the limit
]


class NameRejectionTests(unittest.TestCase):
    def test_name_rejections_table(self):
        for case, name in REJECTED.items():
            with self.subTest(case=case):
                with self.assertRaises(EntryNameError) as ctx:
                    validate_entry_name(name)
                self.assertEqual(ctx.exception.code, "P01")

    def test_valid_names_accepted(self):
        for name in ACCEPTED:
            with self.subTest(name=name[:60]):
                self.assertEqual(validate_entry_name(name), name)

    def test_nfc_and_casefold_key(self):
        # decomposed and precomposed spellings are different bytes; only NFC is accepted
        decomposed = "e\u0301cole.json"
        precomposed = "\u00e9cole.json"
        self.assertEqual(entry_key(decomposed), entry_key(precomposed))
        self.assertEqual(entry_key(precomposed), precomposed.casefold())
        with self.assertRaises(EntryNameError):
            validate_entry_name(decomposed)
        # case-folded duplicates share one key (used by P02 duplicate detection)
        self.assertEqual(entry_key("Knowledge/EV-001.json"), entry_key("knowledge/ev-001.json"))
        self.assertNotEqual(entry_key("a/b.json"), entry_key("a/c.json"))


if __name__ == "__main__":
    unittest.main()

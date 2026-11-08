"""TST-011-046 (REQ-KAP-012): rename and replacement candidate pairing.

A pair of a removed and an added subject becomes a RENAMED_CANDIDATE (or REPLACEMENT_CANDIDATE when a documentation or
migration hint names it). Candidates are never confirmed: `confirmed` is False and only a manual `confirm` may change
that (ledger rule 4). Pairing is one-to-one; anything ambiguous becomes UNKNOWN with every candidate listed. The
threshold comes from `extract/config.json`. Scores are integers (per mille) because digested JSON has no floats.
"""

import copy
import unittest

from odooflux.knowledge.extract import classify as c
from odooflux.knowledge.extract import rename as r
from odooflux.knowledge.ledger.ledger import Ledger

FROM = "ss-" + "ab" * 6
TO = "ss-" + "cd" * 6
SNAP_A = {"snapshot_id": FROM, "snapshot_digest": "ab" * 32}
SNAP_B = {"snapshot_id": TO, "snapshot_digest": "cd" * 32}
SHA = "2" * 64


def _fact(path, subject, kind="field", attrs=None, body=None, domain="python_orm"):
    return {"domain": domain, "path": path, "subject_key": subject, "kind": kind, "attrs": dict(attrs or {}),
            "body_digest": body, "line": 1, "sha256": SHA}


def _pair(before, after, config=None, hints=()):
    drafts = c.classify_pair(before, after, from_snapshot_id=FROM, to_snapshot_id=TO, config=config)
    return r.refine_candidates(drafts, before, after, config=config, hints=hints)


def _by_subject(drafts):
    return {d["subject_key"]: d for d in drafts}


AMOUNT = _fact("addons/a/models/x.py", "res.x::field::amount", attrs={"type": "Monetary"})
AMOUNT_TOTAL = _fact("addons/a/models/x.py", "res.x::field::amount_total", attrs={"type": "Monetary"})


class RenameTests(unittest.TestCase):
    def test_rename_never_confirmed(self):
        out = _pair([AMOUNT], [AMOUNT_TOTAL])
        renamed = _by_subject(out)["res.x::field::amount"]
        self.assertEqual(renamed["class"], "RENAMED_CANDIDATE")
        self.assertIs(renamed.get("confirmed", False), False)
        self.assertEqual(renamed["detail"]["to"], "res.x::field::amount_total")
        self.assertNotIn("res.x::field::amount_total", _by_subject(out), "the added side is absorbed")
        self.assertEqual(renamed["detail"]["score_milli"], 1000)
        # the ledger stores it unconfirmed, and a confirm by a manual actor is still the only way to change that
        ledger = Ledger.create("17-01", SNAP_A, SNAP_B, out)
        entry = ledger.get(ledger.unresolved()[0])
        self.assertFalse(entry["confirmed"])
        self.assertEqual(entry["class"], "RENAMED_CANDIDATE")
        # a replacement from a migration hint is also a candidate only
        removed = _fact("addons/a/models/x.py", "res.x::method::old", kind="method", attrs={"args": ["self"]})
        added = _fact("addons/a/models/x.py", "res.x::method::new", kind="method", attrs={"args": ["self", "v"]})
        rep = _pair([removed], [added], hints=[{"from": "res.x::method::old", "to": "res.x::method::new",
                                                "source": "migration"}])
        only = _by_subject(rep)["res.x::method::old"]
        self.assertEqual(only["class"], "REPLACEMENT_CANDIDATE")
        self.assertIs(only.get("confirmed", False), False)
        self.assertEqual(only["detail"]["source"], "migration")

    def test_ambiguous_rename_unknown(self):
        twin_a = _fact("addons/a/models/x.py", "res.x::field::amount_total", attrs={"type": "Monetary"})
        twin_b = _fact("addons/a/models/x.py", "res.x::field::amount_sum", attrs={"type": "Monetary"})
        out = _by_subject(_pair([AMOUNT], [twin_a, twin_b]))
        self.assertEqual(out["res.x::field::amount"]["class"], "UNKNOWN")
        self.assertEqual(out["res.x::field::amount_total"]["class"], "UNKNOWN")
        self.assertEqual(out["res.x::field::amount_sum"]["class"], "UNKNOWN")
        self.assertEqual(out["res.x::field::amount"]["detail"]["reason"], "AMBIGUOUS_RENAME")
        candidates = out["res.x::field::amount"]["detail"]["candidates"]
        self.assertEqual(sorted(candidates), ["res.x::field::amount_sum", "res.x::field::amount_total"])
        self.assertFalse(any(d["class"] in ("RENAMED_CANDIDATE", "REPLACEMENT_CANDIDATE") for d in out.values()))

    def test_threshold_from_config(self):
        partial = _fact("addons/a/models/x.py", "res.x::field::amount_total", attrs={"type": "Monetary", "x": 1})
        # attrs jaccard 1/2 and equal bodies give score 0.5 * 0.5 + 0.5 = 0.75
        default = c.load_config()
        self.assertEqual(default["rename_threshold"], 0.8)
        self.assertEqual(_by_subject(_pair([AMOUNT], [partial]))["res.x::field::amount"]["class"], "REMOVED")
        lenient = dict(default, rename_threshold=0.7)
        renamed = _by_subject(_pair([AMOUNT], [partial], config=lenient))["res.x::field::amount"]
        self.assertEqual(renamed["class"], "RENAMED_CANDIDATE")
        self.assertEqual(renamed["detail"]["score_milli"], 750)

    def test_one_to_one(self):
        first = _fact("addons/a/models/x.py", "res.x::field::one", attrs={"type": "Char"})
        second = _fact("addons/a/models/x.py", "res.x::field::two", attrs={"type": "Char"})
        target = _fact("addons/a/models/x.py", "res.x::field::both", attrs={"type": "Char"})
        out = _by_subject(_pair([first, second], [target]))
        self.assertEqual({out[k]["class"] for k in out}, {"UNKNOWN"}, "two sources, one target: nothing is paired")
        # disjoint pairs stay one-to-one
        a1 = _fact("addons/a/models/x.py", "res.x::field::p", attrs={"type": "Char"})
        b1 = _fact("addons/a/models/x.py", "res.x::field::q", attrs={"type": "Char"})
        a2 = _fact("addons/a/models/x.py", "res.x::method::m", kind="method", attrs={"args": ["a"]}, body="h1")
        b2 = _fact("addons/a/models/x.py", "res.x::method::n", kind="method", attrs={"args": ["a"]}, body="h1")
        out = _pair([a1, a2], [b1, b2])
        renamed = [d for d in out if d["class"] == "RENAMED_CANDIDATE"]
        self.assertEqual(len(renamed), 2)
        targets = [d["detail"]["to"] for d in renamed]
        self.assertEqual(len(set(targets)), len(targets), "no target is used twice")

    def test_kind_mismatch_is_never_a_rename(self):
        field = _fact("addons/a/models/x.py", "res.x::field::amount", attrs={"type": "Monetary"})
        method = _fact("addons/a/models/x.py", "res.x::method::amount_total", kind="method",
                       attrs={"type": "Monetary"})
        out = _by_subject(_pair([field], [method]))
        self.assertEqual(out["res.x::field::amount"]["class"], "REMOVED")
        self.assertEqual(out["res.x::method::amount_total"]["class"], "ADDED")


if __name__ == "__main__":
    unittest.main()

"""RC fix: the coverage recompute bundle (`coverage/inputs.json`) carries only what the coverage code reads.

A real 16 to 17 pair has ~157k ledger changes. The bundle embedded every full record (detail, history, locations with
hashes) and was written with indent=2: 237 MB, over the package validator's 64 MiB per-file limit (P05), so the release
could not be packaged at all. The coverage metrics, gates and cross-checks read only `change_id`, `class`,
`disposition`, `disposition_data.evidence_ids`, `subject_key` and the location paths, so the bundle keeps exactly
those, and is written as compact canonical JSON. The manifest built from the compact bundle equals the one built from
the full records.
"""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge import pipeline as pl
from odooflux.knowledge.coverage import manifest as cm
from odooflux.knowledge.release import canonical
from tests.unit.knowledge.kap.test_coverage_manifest import TS, _build, _data

LIMIT = 64 * 1024 * 1024


class CompactBundleTests(unittest.TestCase):
    def test_manifest_from_the_compact_bundle_equals_the_manifest_from_full_records(self):
        full = _data()
        compact = dict(full, changes=pl._compact_changes(full["changes"]))
        self.assertEqual(_build(full), _build(compact))

    def test_the_compact_bundle_still_passes_the_consistency_check(self):
        full = _data()
        compact = dict(full, changes=pl._compact_changes(full["changes"]))
        manifest = _build(compact)
        self.assertEqual(cm.check_consistency(manifest, json.loads(json.dumps(compact))), [])

    def test_only_the_fields_the_coverage_code_reads_are_kept(self):
        change = _data()["changes"][0]
        kept = pl._compact_changes([change])[0]
        self.assertEqual(sorted(kept), ["change_id", "class", "disposition", "disposition_data", "locations",
                                        "subject_key"])
        self.assertEqual(kept["disposition_data"], {"evidence_ids": change["disposition_data"]["evidence_ids"]})
        self.assertEqual(kept["locations"], [{"path": loc["path"]} for loc in change["locations"]])

    def test_duplicate_location_paths_collapse_in_a_stable_order(self):
        change = dict(_data()["changes"][0])
        change["locations"] = [{"path": p, "snapshot_id": "ss-x", "line": 1, "sha256": "a" * 64}
                               for p in ("b.py", "a.py", "b.py", "a.py")]
        self.assertEqual(pl._compact_changes([change])[0]["locations"], [{"path": "a.py"}, {"path": "b.py"}])

    def test_a_real_sized_ledger_fits_the_package_limit(self):
        base = _data()["changes"][0]
        many = [dict(base, change_id=f"CH-{i:016x}", subject_key=f"m::field::name_{i}",
                     locations=[{"path": f"addons/module_{i % 900}/models/file_{i % 40}.py", "line": i, "sha256": "f" * 64}
                                for _ in range(2)]) for i in range(157_000)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inputs.json"
            canonical.write_compact_json_file(path, {"changes": pl._compact_changes(many)})
            self.assertLess(path.stat().st_size, LIMIT * 0.6)  # headroom: the real bundle must not sit at the limit

    def test_compact_writer_is_canonical_sorted_and_refuses_floats(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            canonical.write_compact_json_file(path, {"b": [1, {"d": 2, "c": 3}], "a": "x"})
            self.assertEqual(path.read_text(encoding="utf-8"), '{"a":"x","b":[1,{"c":3,"d":2}]}\n')
            with self.assertRaises(Exception):
                canonical.write_compact_json_file(path, {"f": 1.5})


if __name__ == "__main__":
    unittest.main()

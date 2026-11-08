"""008 T029-gen (REQ-VAL-004, REQ-EVD-006): the matrix generator marks a step RUNTIME_VALIDATED only from a recorded,
valid, passing runtime run record (compatibility/runtime_runs.json). No record, a failing record or a malformed record
never marks. Behavioural verification additionally needs a usable source-side image. This tests the generator only; no
record in the shipped data claims a real run unless one was executed (see specs/008 verification log)."""

import json
import unittest

from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.matrix import OverclaimError, generate

from .helpers import copy_fixture

DIGEST = "odoo@sha256:" + "a" * 64
SRC_DIGEST = "odoo@sha256:" + "b" * 64


def record(**over):
    base = {"id": "RR-1", "step": "16-17", "source_version": "16.0", "target_version": "17.0",
            "fixture_ids": ["17.0/kbi_demo"], "image_digest": DIGEST, "source_image_digest": None,
            "date": "2026-01-02", "tool_version": "0.2.0", "result": "PASS", "behavioural": "UNAVAILABLE"}
    base.update(over)
    return base


def _seed(root):
    for step in ("15-16", "16-17"):
        (root / "compatibility" / f"{step}.research.json").write_text(json.dumps({
            "step": step, "research_status": "RESEARCH_SEEDED", "revisions": {}, "peer_reviewed": False,
            "notes": "fixture", "review_only": "none", "seeded_evidence": [], "open_gaps": [], "categories": {}}),
            encoding="utf-8")
    return root


def kb_with(*runs, raw=None):
    root = _seed(copy_fixture("valid"))
    path = root / "compatibility" / "runtime_runs.json"
    path.write_text(raw if raw is not None else json.dumps({"schema": "odooflux.runtime-runs/1", "runs": list(runs)}),
                    encoding="utf-8")
    return load_knowledge(root)


def row(text, step="16→17"):
    return next(line for line in text.splitlines() if line.startswith(f"| {step} |")).split(" | ")


class RuntimeRunMatrixTests(unittest.TestCase):
    def test_no_record_file_leaves_everything_unmarked(self):
        text = generate(load_knowledge(_seed(copy_fixture("valid"))))
        self.assertEqual(row(text)[-2].strip(), "—")
        self.assertEqual(row(text)[-1].strip(" |"), "—")

    def test_shipped_data_marks_nothing_without_a_real_run(self):
        text = generate(load_knowledge(KNOWLEDGE_ROOT))
        data = json.loads((KNOWLEDGE_ROOT / "compatibility" / "runtime_runs.json").read_text(encoding="utf-8"))
        if not any(r["result"] == "PASS" for r in data["runs"]):
            self.assertNotIn("| RUNTIME_VALIDATED |", text)

    def test_passing_record_marks_only_its_own_step(self):
        text = generate(kb_with(record()))
        self.assertEqual(row(text)[-2].strip(), "RUNTIME_VALIDATED")
        self.assertEqual(row(text, "15→16")[-2].strip(), "—")
        self.assertEqual(row(text)[-1].strip(" |"), "—")  # no source image: never behaviourally verified

    def test_failing_record_does_not_mark(self):
        text = generate(kb_with(record(result="FAIL")))
        self.assertEqual(row(text)[-2].strip(), "RUN_FAILED")

    def test_later_failure_withdraws_an_earlier_pass(self):
        text = generate(kb_with(record(), record(id="RR-2", date="2026-02-01", result="FAIL")))
        self.assertEqual(row(text)[-2].strip(), "RUN_FAILED")

    def test_malformed_record_never_marks_and_is_reported_by_validate(self):
        bad = record(image_digest="not-a-digest")
        kb = kb_with(bad)
        self.assertNotEqual(row(generate(kb))[-2].strip(), "RUNTIME_VALIDATED")
        self.assertTrue(any(f.file == "compatibility/runtime_runs.json" for f in validate_knowledge(kb)))

    def test_unparseable_file_never_marks(self):
        kb = kb_with(raw="{not json")
        self.assertNotEqual(row(generate(kb))[-2].strip(), "RUNTIME_VALIDATED")
        self.assertTrue(any(f.file == "compatibility/runtime_runs.json" for f in validate_knowledge(kb)))

    def test_missing_required_field_is_malformed(self):
        bad = record()
        del bad["fixture_ids"]
        kb = kb_with(bad)
        self.assertNotEqual(row(generate(kb))[-2].strip(), "RUNTIME_VALIDATED")
        self.assertTrue(validate_knowledge(kb))

    def test_step_must_match_versions(self):
        kb = kb_with(record(target_version="18.0"))
        self.assertNotEqual(row(generate(kb))[-2].strip(), "RUNTIME_VALIDATED")
        self.assertTrue(validate_knowledge(kb))

    def test_behavioural_needs_a_source_image(self):
        no_source = kb_with(record(behavioural="PASS", source_image_digest=None))
        self.assertTrue(validate_knowledge(no_source), "behavioural PASS without a source image is malformed")
        self.assertEqual(row(generate(no_source))[-1].strip(" |"), "—")
        ok = kb_with(record(behavioural="PASS", source_image_digest=SRC_DIGEST))
        self.assertEqual(validate_knowledge(ok), [])
        self.assertEqual(row(generate(ok))[-1].strip(" |"), "BEHAVIOURAL_VERIFIED")

    def test_unavailable_behavioural_is_not_verified(self):
        text = generate(kb_with(record(behavioural="UNAVAILABLE")))
        self.assertEqual(row(text)[-1].strip(" |"), "—")

    def test_hand_edited_cell_claiming_runtime_validated_is_refused(self):
        root = _seed(copy_fixture("valid"))
        path = root / "compatibility" / "16-17.research.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("categories", {})["runtime"] = {"status": "RUNTIME_VALIDATED", "evidence": [], "gaps": []}
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(OverclaimError, "RUNTIME_VALIDATED"):
            generate(load_knowledge(root))

    def test_valid_passing_record_validates_clean(self):
        self.assertEqual(validate_knowledge(kb_with(record())), [])


if __name__ == "__main__":
    unittest.main()

"""RC contract: `knowledge-check/1` and `knowledge-history/1` documents validate against their shipped schemas."""

import json
import unittest

from odooflux.knowledge import validator as v
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.update import report
from tests.unit.knowledge.update.test_report import RenderHistoryTests, check_block, source

SCHEMAS = KNOWLEDGE_ROOT / "schemas"
CHECK = json.loads((SCHEMAS / "knowledge_check.schema.json").read_text(encoding="utf-8"))
HISTORY = json.loads((SCHEMAS / "knowledge_history.schema.json").read_text(encoding="utf-8"))


class CheckSchemaTests(unittest.TestCase):
    def test_valid_documents(self):
        for block in (check_block(),
                      check_block(sources=[source("17.0", edition="enterprise", status="SKIPPED_NO_CREDENTIALS",
                                                  remote=None)], statuses=("NO_UPDATE",)),
                      check_block(new_versions=[{"edition": "community", "version": "18.0", "branch": "18.0",
                                                 "remote_sha": "a" * 40}])):
            self.assertEqual(v.check(json.loads(json.dumps(block)), CHECK), [])

    def test_drift_is_rejected(self):
        for mutate in (lambda d: d.update(extra=1), lambda d: d.pop("offline"),
                       lambda d: d.update(enterprise_freshness="MAYBE"),
                       lambda d: d["sources"][0].update(status="FINE"),
                       lambda d: d.update(schema="odooflux.knowledge-check/2"),
                       lambda d: d.update(affected_transitions=["16_17"])):
            doc = json.loads(json.dumps(check_block()))
            mutate(doc)
            self.assertTrue(v.check(doc, CHECK))


class HistorySchemaTests(unittest.TestCase):
    def doc(self):
        rows = report.history_rows(RenderHistoryTests("test_empty_history").entries())
        return json.loads(json.dumps(report.history_payload(rows)))

    def test_valid_documents(self):
        self.assertEqual(v.check(self.doc(), HISTORY), [])
        self.assertEqual(v.check(json.loads(json.dumps(report.history_payload([]))), HISTORY), [])

    def test_drift_is_rejected(self):
        for mutate in (lambda d: d.update(chain="unverified"), lambda d: d.update(extra=1),
                       lambda d: d["entries"][0].pop("failure_reason"),
                       lambda d: d["entries"][0].update(seq=0)):
            doc = self.doc()
            mutate(doc)
            self.assertTrue(v.check(doc, HISTORY))


if __name__ == "__main__":
    unittest.main()

"""TST-003-020 (REQ-VER-004): rules run in depends order; steps chain; L1 gates each output."""

import unittest
from dataclasses import dataclass, field

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.contracts.records import Finding, ValidationResult
from odooflux.core.engine.step_runner import Step, order_rules, run_steps


@dataclass
class R:
    key: str
    depends: tuple = ()
    contract_version: int = CONTRACT_VERSION
    seen: list = field(default_factory=list)
    log: list = field(default_factory=list)

    def detect(self, document):
        self.log.append(self.key)
        return []


class Upper:
    layer = 1

    def applies_to(self, path):
        return path.endswith(".txt")

    def validate(self, path, text):
        if "BAD" in text:
            return ValidationResult(layer=1, outcome="FAIL", reason="BAD marker")
        return ValidationResult(layer=1, outcome="PASS")


class StepRunnerTests(unittest.TestCase):
    def test_rules_run_in_depends_order(self):
        a = R("a")
        b = R("b", depends=("a",))
        c = R("c", depends=("b",))
        self.assertEqual([r.key for r in order_rules([c, a, b])], ["a", "b", "c"])

    def test_step_output_is_next_steps_input(self):
        def first(path, text):
            return text + "1"

        def second(path, text):
            return text + "2"

        outcomes = run_steps([Step("s1", [], first), Step("s2", [], second)], "f.txt", "x", [Upper()])
        self.assertEqual([o.output for o in outcomes], ["x1", "x12"])

    def test_l1_failure_stops_the_chain_and_keeps_input(self):
        outcomes = run_steps([Step("s1", [], lambda p, t: t + " BAD"), Step("s2", [], lambda p, t: t + "2")],
                             "f.txt", "x", [Upper()])
        self.assertEqual(len(outcomes), 1)
        self.assertTrue(outcomes[0].rejected)
        self.assertEqual(outcomes[0].output, "x")

    def test_raising_rule_becomes_rule_error_and_run_continues(self):
        class Boom(R):
            def detect(self, document):
                raise RuntimeError("bad plugin")

        ok = R("ok")
        outcomes = run_steps([Step("s", [Boom("boom"), ok], None)], "f.txt", "x", [])
        findings = outcomes[0].findings
        self.assertTrue(any(isinstance(f, Finding) and f.rule_id == "RULE_ERROR" for f in findings))
        self.assertEqual(ok.log, ["ok"])


if __name__ == "__main__":
    unittest.main()

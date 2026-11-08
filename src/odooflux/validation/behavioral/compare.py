"""Behavioural comparison (REQ-BIZ-002, REQ-VAL-005, FR-008; research G-R-23 and EV-368).

Parsing (per module, from the log of ``odoo -u <module> --test-enable --test-tags ...``):
- ``Starting <Class>.<method> ...`` on the module's test logger marks a test that ran. Odoo logs nothing else for a
  passing test. Research T004 relied on the stats count instead; the recorded runs show that count is cumulative
  across phases (5 for 3 tests), so it is kept as information only.
- ``ERROR``/``FAIL`` records on the module's test logger name the failed test. A subtest failure maps to its parent.
  Failures logged at install and again at post-install collapse to one outcome.
- ``skipped <Class>.<method> : <reason>`` is a skip.
- A test that ran and has no failure or skip record is a pass. A test that never started is not inferred as a pass.
- Completeness: every test of the static universe (AST scan of ``def test_*`` under the module's tests/) started.

Comparison: the six classifications of spec Key Entities. A skipped test counts as not run on that side.

L5 judgement (``judge``): see the docstring of that function.
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from odooflux.core.contracts.records import ValidationResult
from odooflux.validation.runtime.log_classifier import split_records

CLASSIFICATIONS = ("pass_both", "regression", "fixed", "fail_both", "target_only", "source_only")
FAILING = ("fail", "error")
RANK = {"pass": 0, "skip": 1, "fail": 2, "error": 3}
STARTING = re.compile(r"^Starting (\w+)\.(\w+) \.\.\.")
OUTCOME_LINE = re.compile(r"^(ERROR|FAIL): (\S+)")
SUBTEST = re.compile(r"^(?:(?:ERROR|FAIL): )?Subtest (\w+)\.(\w+)")
SKIPPED = re.compile(r"^skipped (\w+)\.(\w+)\s*:")
STATS = re.compile(r"^(\S+): (\d+) tests ")


@dataclass(frozen=True)
class ParsedTests:
    outcomes: dict                 # test id -> pass | fail | error | skip
    ran: bool                      # at least one test of the module started or reported
    complete: bool                 # every test of the static universe started
    universe: frozenset
    stats_count: Optional[int] = None
    notes: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class TestComparison:
    test_id: str
    source: Optional[str]
    target: Optional[str]
    classification: str


def scan_static_universe(module_dir, module: str) -> frozenset:
    """Test ids ``<module>.<Class>.<method>`` for every ``def test_*`` in a top-level class under tests/.

    AST only: the module's code is parsed, never imported or executed."""
    tests_dir = Path(module_dir) / "tests"
    if not tests_dir.is_dir():
        return frozenset()
    found = set()
    for file in sorted(tests_dir.rglob("*.py")):
        try:
            tree = ast.parse(file.read_text(encoding="utf-8", errors="replace"), filename=str(file))
        except (SyntaxError, ValueError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_"):
                    found.add(f"{module}.{node.name}.{item.name}")
    return frozenset(found)


def _record(outcomes: dict, test_id: str, outcome: str) -> None:
    current = outcomes.get(test_id)
    if current is None or RANK[outcome] > RANK[current]:
        outcomes[test_id] = outcome


def _test_id(module: str, dotted: str) -> Optional[str]:
    parts = dotted.split(".")
    if len(parts) < 2:
        return None
    return f"{module}.{parts[-2]}.{parts[-1]}"


def parse_test_output(log_text: str, module: str, static_universe) -> ParsedTests:
    prefix = f"odoo.addons.{module}"
    started, outcomes, notes = set(), {}, []
    stats_count = None
    for record in split_records(log_text):
        if record.logger == "odoo.tests.stats":
            found = STATS.match(record.message)
            if found and found.group(1) == module:
                stats_count = int(found.group(2))
            continue
        if not (record.logger == prefix or record.logger.startswith(prefix + ".")):
            continue
        message = record.message.strip()
        found = STARTING.match(message)
        if found:
            started.add(f"{module}.{found.group(1)}.{found.group(2)}")
            continue
        found = SKIPPED.match(message)
        if found:
            _record(outcomes, f"{module}.{found.group(1)}.{found.group(2)}", "skip")
            continue
        found = SUBTEST.match(message)
        if found:
            _record(outcomes, f"{module}.{found.group(1)}.{found.group(2)}", "fail")
            continue
        found = OUTCOME_LINE.match(message)
        if found and record.level in ("ERROR", "CRITICAL"):
            test_id = _test_id(module, found.group(2))
            if test_id:
                _record(outcomes, test_id, "error" if found.group(1) == "ERROR" else "fail")
    universe = frozenset(static_universe)
    executed = started | set(outcomes)
    for test_id in universe:
        if test_id in started and test_id not in outcomes:
            outcomes[test_id] = "pass"
    ran = bool(executed)
    if stats_count is not None and universe and stats_count != len(universe):
        notes.append(f"stats count {stats_count} differs from the {len(universe)} static tests (information only)")
    return ParsedTests(outcomes=outcomes, ran=ran, complete=ran and universe <= executed, universe=universe,
                       stats_count=stats_count, notes=tuple(notes))


def _status(outcome: Optional[str]) -> Optional[str]:
    if outcome in (None, "skip"):
        return None
    return "pass" if outcome == "pass" else "fail"


def compare(source_outcomes: dict, target_outcomes: dict) -> list:
    comparisons = []
    for test_id in sorted(set(source_outcomes) | set(target_outcomes)):
        source, target = _status(source_outcomes.get(test_id)), _status(target_outcomes.get(test_id))
        if source is None and target is None:
            continue
        if source is None:
            classification = "target_only"
        elif target is None:
            classification = "source_only"
        elif source == "pass" and target == "pass":
            classification = "pass_both"
        elif source == "fail" and target == "fail":
            classification = "fail_both"
        elif source == "pass":
            classification = "regression"
        else:
            classification = "fixed"
        comparisons.append(TestComparison(test_id=test_id, source=source_outcomes.get(test_id),
                                          target=target_outcomes.get(test_id), classification=classification))
    return comparisons


def classification_counts(comparisons) -> dict:
    counts = {name: [] for name in CLASSIFICATIONS}
    for comparison in comparisons:
        counts[comparison.classification].append(comparison.test_id)
    return {name: sorted(ids) for name, ids in counts.items()}


def _ran_tests(parsed: ParsedTests) -> list:
    return [t for t, o in parsed.outcomes.items() if o in ("pass",) + FAILING]


def judge(target: ParsedTests, source: Optional[ParsedTests] = None, *, source_reason: str = "") -> ValidationResult:
    """L5 result (layer 5).

    - No test methods at all: SKIPPED, reason ``no_tests``.
    - Target tests did not start: FAIL, ``tests_not_run``.
    - No baseline (no source runtime or the source tests did not run): any failing target test is FAIL, since a
      failure cannot be attributed to the change without a baseline. Otherwise PASS with ``coverage = partial``.
    - Baseline: a regression (passes on the source, fails on the target) or a target-only failing test is FAIL,
      naming the tests. Otherwise PASS with ``coverage = full`` when both sides ran every static test and at least one
      target test ran. Failures present on both sides are pre-existing and do not fail the layer.
    """
    if not target.universe and not target.outcomes:
        return ValidationResult(layer=5, outcome="SKIPPED", reason="no_tests")
    if not target.ran:
        return ValidationResult(layer=5, outcome="FAIL", coverage="partial",
                                reason="tests_not_run: the target test run started no test of the module")
    if source is not None and not source.ran:
        source, source_reason = None, source_reason or "the source test run started no test"
    if source is None:
        return _judge_without_baseline(target, source_reason or "source runtime not available")
    return _judge_with_baseline(target, source)


def _judge_without_baseline(target: ParsedTests, reason: str) -> ValidationResult:
    failing = sorted(t for t, o in target.outcomes.items() if o in FAILING)
    note = f"no baseline ({reason}); coverage partial"
    if failing:
        return ValidationResult(layer=5, outcome="FAIL", coverage="partial",
                                reason=f"{len(failing)} failing target test(s) without a baseline, pre-existing "
                                       f"status unknown: {', '.join(failing)}; {note}")
    ran = _ran_tests(target)
    if not ran:
        return ValidationResult(layer=5, outcome="SKIPPED", reason="no_tests")
    return ValidationResult(layer=5, outcome="PASS", coverage="partial",
                            reason=f"{len(ran)} target test(s) passed; {note}")


def _judge_with_baseline(target: ParsedTests, source: ParsedTests) -> ValidationResult:
    comparisons = compare(source.outcomes, target.outcomes)
    counts = classification_counts(comparisons)
    target_only_failing = sorted(c.test_id for c in comparisons
                                 if c.classification == "target_only" and c.target in FAILING)
    coverage = "full" if (source.complete and target.complete) else "partial"
    if counts["regression"] or target_only_failing:
        parts = []
        if counts["regression"]:
            parts.append(f"regression: {len(counts['regression'])} test(s) pass on the source and fail on the "
                         f"target: {', '.join(counts['regression'])}")
        if target_only_failing:
            parts.append(f"target_only_failure: {', '.join(target_only_failing)}")
        return ValidationResult(layer=5, outcome="FAIL", coverage=coverage, reason="; ".join(parts))
    ran = _ran_tests(target)
    if not ran:
        return ValidationResult(layer=5, outcome="SKIPPED", reason="no_tests")
    detail = (f"{len(ran)} target test(s) ran; no regression; {len(counts['fail_both'])} failed on both versions "
              f"(pre-existing)")
    if coverage == "partial":
        detail += "; the static test universe was not fully executed on both sides"
    return ValidationResult(layer=5, outcome="PASS", coverage=coverage, reason=detail)

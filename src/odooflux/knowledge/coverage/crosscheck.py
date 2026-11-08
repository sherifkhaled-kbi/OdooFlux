"""Cross-checks against independent sources (REQ-KAP-033; coverage-and-gates contract, cross-checks table).

Each function returns one item `{id, status, benchmark_id, benchmark_size, detail}` plus an optional `recall` object
`{found, referenced, benchmark_id, benchmark_size}`. Statuses: PASS, FAIL, NOT_RUN (input absent), NOT_MEASURED
(no recall possible: no referenced items, or no named benchmark). `recall_entry` refuses to build a recall without a
named benchmark, so no recall figure is ever unnamed. Recall is reported only for XC-UPGRADE, XC-REGR and XC-BENCH.
"""

from odooflux.knowledge.extract.accounting import STATES

__all__ = ["CrossCheckError", "recall_entry", "run_crosschecks", "xc_upgrade", "xc_indep", "xc_kb", "xc_regr",
           "xc_bench", "CHECK_IDS"]

CHECK_IDS = ("XC-UPGRADE", "XC-INDEP", "XC-KB", "XC-REGR", "XC-BENCH")


class CrossCheckError(ValueError):
    """A recall or cross-check input was refused."""


def recall_entry(found: int, referenced: int, benchmark_id, benchmark_size: int) -> dict:
    """A recall figure. Refused without a named benchmark (the writer never emits an unnamed recall)."""
    if not benchmark_id or not str(benchmark_id).strip():
        raise CrossCheckError("recall needs a named benchmark_id")
    if referenced < 1 or found < 0 or found > referenced:
        raise CrossCheckError(f"invalid recall counts {found}/{referenced}")
    return {"found": found, "referenced": referenced, "benchmark_id": benchmark_id, "benchmark_size": benchmark_size}


def _item(check_id, status, detail, benchmark_id=None, benchmark_size=None, recall=None) -> dict:
    item = {"id": check_id, "status": status, "benchmark_id": benchmark_id, "benchmark_size": benchmark_size,
            "detail": detail}
    if recall is not None:
        item["recall"] = recall
    return item


def _not_run(check_id: str, why: str) -> dict:
    return _item(check_id, "NOT_RUN", why)


def _subjects(changes) -> set:
    return {c["subject_key"] for c in changes}


def xc_upgrade(referenced, changes, step: str) -> dict:
    """Renames and removals referenced by the upgrade scripts between the two revisions must appear as ledger changes
    (any class). Recall is found/referenced against the named benchmark `upgrade-scripts:<step>`."""
    if referenced is None:
        return _not_run("XC-UPGRADE", "no upgrade scripts supplied")
    benchmark = f"upgrade-scripts:{step}"
    wanted = sorted({r["subject_key"] for r in referenced})
    if not wanted:
        return _item("XC-UPGRADE", "NOT_MEASURED", "no rename or removal referenced; recall undefined", benchmark, 0)
    seen = _subjects(changes)
    found = [s for s in wanted if s in seen]
    status = "PASS" if len(found) == len(wanted) else "FAIL"
    recall = recall_entry(len(found), len(wanted), benchmark, len(wanted))
    missing = sorted(set(wanted) - set(found))
    detail = f"{len(found)} of {len(wanted)} referenced changes in the ledger"
    if missing:
        detail += f"; missing: {', '.join(missing[:5])}"
    return _item("XC-UPGRADE", status, detail, benchmark, len(wanted), recall)


def xc_indep(documents) -> dict:
    """Per pair: the number of files equals `independent_count`, and the state totals equal the per-file states."""
    if documents is None:
        return _not_run("XC-INDEP", "no accounting documents supplied")
    if not documents:
        return _not_run("XC-INDEP", "no pairs to compare")
    problems = []
    for doc in documents:
        pair = doc["pair"]["step"]
        counts = {state: 0 for state in STATES}
        for item in doc["files"]:
            counts[item["state"]] += 1
        if counts != {s: doc["totals"].get(s) for s in STATES}:
            problems.append(f"{pair}: totals differ from file states")
        if len(doc["files"]) != doc["independent_count"]:
            problems.append(f"{pair}: {len(doc['files'])} files, independent count {doc['independent_count']}")
    if problems:
        return _item("XC-INDEP", "FAIL", "; ".join(problems))
    return _item("XC-INDEP", "PASS", f"{len(documents)} pair(s): file counts equal the independent count")


def xc_kb(rules, changes, not_observed) -> dict:
    """Each existing KB rule's subject is seen in the ledger, or listed as NOT_OBSERVED with a non-empty reason."""
    if rules is None:
        return _not_run("XC-KB", "no existing KB rules supplied")
    seen = _subjects(changes)
    reasons = dict(not_observed or {})
    unexplained = []
    for rule in rules:
        subject = rule["subject_key"]
        if subject in seen:
            continue
        if str(reasons.get(subject) or "").strip():
            continue
        unexplained.append(f"{rule['rule_id']}:{subject}")
    if unexplained:
        return _item("XC-KB", "FAIL", f"not observed without reason: {', '.join(sorted(unexplained)[:5])}")
    return _item("XC-KB", "PASS", f"{len(rules)} KB rule subject(s) seen or reasoned")


def xc_regr(regression_file, ids, linked) -> dict:
    """Every known regression id has a ledger or rule link. Recall named `regression:<file>`."""
    if regression_file is None:
        return _not_run("XC-REGR", "no regression list supplied")
    benchmark = f"regression:{regression_file}"
    wanted = sorted(set(ids))
    if not wanted:
        return _item("XC-REGR", "NOT_MEASURED", "regression list is empty; recall undefined", benchmark, 0)
    have = set(linked)
    found = [i for i in wanted if i in have]
    status = "PASS" if len(found) == len(wanted) else "FAIL"
    recall = recall_entry(len(found), len(wanted), benchmark, len(wanted))
    return _item("XC-REGR", status, f"{len(found)} of {len(wanted)} regressions linked", benchmark, len(wanted),
                 recall)


def xc_bench(benchmark) -> dict:
    """Benchmark expected changes found. `benchmark` is `{benchmark_id, expected[], found[]}`. Without a name the
    result is NOT_MEASURED and carries no recall."""
    name = benchmark.get("benchmark_id")
    expected = sorted(set(benchmark.get("expected", [])))
    seen = set(benchmark.get("found", []))
    found = [s for s in expected if s in seen]
    if not name:
        return _item("XC-BENCH", "NOT_MEASURED", f"{len(found)} of {len(expected)} found; no named benchmark, "
                     "recall not reported", None, len(expected))
    if not expected:
        return _item("XC-BENCH", "NOT_MEASURED", "benchmark has no expected changes; recall undefined", name, 0)
    status = "PASS" if len(found) == len(expected) else "FAIL"
    recall = recall_entry(len(found), len(expected), name, len(expected))
    return _item("XC-BENCH", status, f"{len(found)} of {len(expected)} benchmark changes found", name, len(expected),
                 recall)


def run_crosschecks(inputs: dict) -> list:
    """All five checks, in order. Keys: `upgrade` ({step, referenced}), `accounting` (documents), `changes` (ledger
    entries), `kb` ({rules, not_observed}), `regression` ({file, ids, linked}), `benchmarks` (list). A missing input
    gives NOT_RUN for that check. XC-BENCH yields one item per benchmark, or one NOT_RUN item when none is given."""
    upgrade = inputs.get("upgrade")
    changes = inputs.get("changes", [])
    kb = inputs.get("kb")
    regression = inputs.get("regression")
    items = [
        xc_upgrade(upgrade.get("referenced") if upgrade else None, changes, upgrade["step"]) if upgrade
        else _not_run("XC-UPGRADE", "no upgrade scripts supplied"),
        xc_indep(inputs.get("accounting")),
        xc_kb(kb.get("rules") if kb else None, changes, kb.get("not_observed") if kb else None),
        xc_regr(regression["file"], regression.get("ids", []), regression.get("linked", [])) if regression
        else _not_run("XC-REGR", "no regression list supplied"),
    ]
    benchmarks = inputs.get("benchmarks") or []
    if benchmarks:
        items += [xc_bench(b) for b in benchmarks]
    else:
        items.append(_not_run("XC-BENCH", "no named benchmark set supplied"))
    return items

"""``odooflux support-statement``: the generated support statement (T007; REQ-VER-003, REQ-EVD-006; SC-005; FC A-9).

A version path is ``supported`` only when every step of it is ``RULES_TESTED`` (matrix "Rules" column) and the target is
``RUNTIME_VALIDATED`` (a recorded passing runtime run for the step that ends at the target). The rule is never relaxed
here. ``experimental`` means every step has research and runnable rules but the supported rule is not met;
everything else is ``unsupported``. Paths whose steps rest on the PROVISIONAL validation corpus (ADR-019) carry that label.

The output depends only on the knowledge data and the golden fixture index, never on time, so it is reproducible.
Exit codes: 0 written or in sync, 1 drift under ``--check``, 2 usage error, 3 tool error.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.knowledge import runtime_runs
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge

REPO_ROOT = KNOWLEDGE_ROOT.parents[2]
DEFAULT_OUT = REPO_ROOT / "docs" / "planning" / "SUPPORT_STATEMENT.md"
FIXTURE_INDEX = REPO_ROOT / "tests" / "golden_fixtures" / "INDEX.json"
RUNNABLE = ("DETECT_ONLY", "FIX_ENABLED")
SEEDED = ("RESEARCH_SEEDED", "RESEARCHED", "RULES_DRAFTED", "RULES_TESTED", "RUNTIME_VALIDATED")
# Backlog items that grow this statement (docs/planning/KNOWLEDGE_BASE_BACKLOG.md).
PENDING_BACKLOG = ("KB-006-SC002", "KB-006-SC003", "KB-008-T029r", "KB-010-SUP")


@dataclass
class StepFacts:
    step: str  # "17-18"
    research: str
    rules: str  # the matrix "Rules" status
    runtime: str  # RUNTIME_VALIDATED, RUN_FAILED or the dash
    runnable_rules: int
    provisional: bool = False


@dataclass
class PathRow:
    source: str
    target: str
    status: str  # supported | experimental | unsupported
    reasons: list = field(default_factory=list)
    provisional: bool = False


def classify_path(source: str, target: str, steps: list) -> PathRow:
    """Apply the support rule to the steps of one path (ordered, source first)."""
    reasons = []
    for facts in steps:
        if facts.rules != "RULES_TESTED":
            reasons.append(f"step {facts.step} rules are {facts.rules}, not RULES_TESTED")
    last = steps[-1] if steps else None
    if last is None or last.runtime != "RUNTIME_VALIDATED":
        reasons.append(f"target {target} is {last.runtime if last else 'not covered'}, not RUNTIME_VALIDATED")
    provisional = any(f.provisional for f in steps)
    if not reasons:
        status = "supported"
    elif all(f.research in SEEDED and f.runnable_rules > 0 for f in steps) and steps:
        status = "experimental"
    else:
        status = "unsupported"
        for facts in steps:
            if facts.runnable_rules == 0:
                reasons.append(f"step {facts.step} has no runnable rule")
            if facts.research not in SEEDED:
                reasons.append(f"step {facts.step} has no research ({facts.research})")
    return PathRow(source, target, status, reasons, provisional)


def _major(version: str) -> int:
    return int(version.split(".")[0])


def provisional_steps(index_path: Path = FIXTURE_INDEX) -> set:
    """Steps (``17-18``) covered only by fixtures whose authority is PROVISIONAL (ADR-019)."""
    try:
        index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    steps = set()
    for fixture in index.get("fixtures", []):
        if fixture.get("authority") == "PROVISIONAL":
            for target in fixture.get("targets", []):
                steps.add(f"{_major(fixture['source_version'])}-{_major(target)}")
    return steps


def step_facts_from(kb, provisional: set) -> dict:
    """Step key -> StepFacts for every research record."""
    runnable = {}
    for rule in kb.rules:
        if rule.get("maturity") in RUNNABLE:
            runnable[rule["step"]] = runnable.get(rule["step"], 0) + 1
    out = {}
    for step, record in kb.research.items():
        rules_cell = record.get("categories", {}).get("rules", {}).get("status", "NOT_ASSESSED")
        out[step] = StepFacts(step=step, research=record.get("research_status", "NOT_ASSESSED"), rules=rules_cell,
                              runtime=runtime_runs.runtime_status(kb, step), runnable_rules=runnable.get(step, 0),
                              provisional=step in provisional)
    return out


def _knowledge(knowledge_root=None):
    """The knowledge data to compute from: the built-in tree, or a release's `knowledge/` tree (REQ-KAP-036)."""
    return load_knowledge() if knowledge_root is None else load_knowledge(knowledge_root)


def build_rows(kb=None, index_path: Path = FIXTURE_INDEX, *, knowledge_root=None) -> tuple:
    """``(rows, step_facts)``: one row per ordered version pair (source < target) the registry knows."""
    kb = kb or _knowledge(knowledge_root)
    facts = step_facts_from(kb, provisional_steps(index_path))
    majors = sorted(_major(v["id"]) for v in kb.versions)
    names = {_major(v["id"]): v["id"] for v in kb.versions}
    rows = []
    for i, src in enumerate(majors):
        for dst in majors[i + 1:]:
            chain = [f"{n}-{n + 1}" for n in range(src, dst)]
            steps = [facts.get(key) or StepFacts(key, "NOT_ASSESSED", "NOT_ASSESSED", "—", 0) for key in chain]
            rows.append(classify_path(names[src], names[dst], steps))
    return rows, [facts[k] for k in sorted(facts, key=lambda s: tuple(int(p) for p in s.split("-")))]


def _arrow(row) -> str:
    return f"{row.source} → {row.target}"


def render(rows: list, step_facts: list, pending: tuple = PENDING_BACKLOG) -> str:
    out = ["# Support Statement\n\n",
           "GENERATED by `odooflux support-statement` from the knowledge data (`src/odooflux/knowledge/`) and the golden "
           "fixture index. Do not edit by hand; run `odooflux support-statement --check` to detect drift.\n\n",
           "A path is **supported** only when every step is `RULES_TESTED` and the target is `RUNTIME_VALIDATED` "
           "(SC-005). **Experimental** means every step has research and runnable rules, but the supported rule is not "
           "met. **Unsupported** means a step lacks research or runnable rules. A `PROVISIONAL` label means the path "
           "rests on the provisional validation corpus (ADR-019): fixtures and expected output produced to test framework "
           "mechanics, not approved migration truth.\n\n"]
    counts = {s: sum(1 for r in rows if r.status == s) for s in ("supported", "experimental", "unsupported")}
    out.append("Paths: " + ", ".join(f"{n} {s}" for s, n in counts.items()) + f" (of {len(rows)}).\n\n")
    out.append("## Supported paths\n\n")
    supported = [r for r in rows if r.status == "supported"]
    if not supported:
        out.append("No path is supported. No step is `RULES_TESTED` in the compatibility matrix and no step has a "
                   "recorded passing runtime run.\n\n")
    else:
        out.append("| Path | Label |\n|---|---|\n")
        out += [f"| {_arrow(r)} | {'PROVISIONAL' if r.provisional else ''} |\n" for r in supported]
        out.append("\n")
    out.append("## Step facts\n\n| Step | Research | Rules | Runtime | Runnable rules | Corpus |\n|---|---|---|---|---|---|\n")
    for f in step_facts:
        out.append(f"| {f.step.replace('-', '→')} | {f.research} | {f.rules} | {f.runtime} | {f.runnable_rules} | "
                   f"{'PROVISIONAL' if f.provisional else '—'} |\n")
    out.append("\n## All paths\n\n| Path | Status | Label | Reasons |\n|---|---|---|---|\n")
    for r in rows:
        reasons = "; ".join(r.reasons) if r.reasons else "all steps RULES_TESTED, target RUNTIME_VALIDATED"
        out.append(f"| {_arrow(r)} | {r.status} | {'PROVISIONAL' if r.provisional else ''} | {reasons} |\n")
    out.append("\n## Not yet supported (knowledge pending)\n\n")
    out.append("These paths are not supported. They wait for Knowledge Base work tracked in "
               "[KNOWLEDGE_BASE_BACKLOG.md](KNOWLEDGE_BASE_BACKLOG.md): " + ", ".join(f"`{k}`" for k in pending)
               + ". Nothing is removed or cancelled; the list shrinks only when the matrix data says so.\n\n")
    out.append("| Path | Status | Label | Missing |\n|---|---|---|---|\n")
    for r in rows:
        if r.status != "supported":
            out.append(f"| {_arrow(r)} | {r.status} | {'PROVISIONAL' if r.provisional else ''} | "
                       f"{'; '.join(r.reasons)} |\n")
    out.append("\n## Verification limits\n\n"
               "- `RULES_TESTED` and `RUNTIME_VALIDATED` come from the matrix data and the recorded runtime run file, "
               "not from this tool's own judgement.\n"
               "- A run whose source side has no usable image never counts as behaviourally verified.\n"
               "- Static layers L1 to L3 do not prove install or runtime behaviour; they are limits stated in each report.\n"
               "- Provisional-corpus results test the framework only. A human reviewer has not approved them "
               "(register: `docs/reviews/FINAL_HUMAN_REVIEW_REGISTER.md`).\n")
    return "".join(out)


def generate_text(kb=None, index_path: Path = FIXTURE_INDEX, *, knowledge_root=None) -> str:
    rows, facts = build_rows(kb, index_path, knowledge_root=knowledge_root)
    return render(rows, facts)


def build_parser():
    parser = argparse.ArgumentParser(prog="odooflux support-statement", description="Generate the support statement")
    parser.add_argument("--out", default=str(DEFAULT_OUT), metavar="FILE")
    parser.add_argument("--check", action="store_true", help="exit 1 when FILE differs from the generated text")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    out = Path(args.out)
    if not FIXTURE_INDEX.is_file():
        # The PROVISIONAL labels come from the fixture index, which is not part of the wheel: refuse instead of
        # writing a statement that silently lacks them.
        print("ERROR: support-statement is a release-process command and needs a source checkout "
              f"({FIXTURE_INDEX} not found).", file=sys.stderr)
        return 2
    try:
        text = generate_text()
    except Exception as exc:  # a data error must not look like drift
        print(f"ERROR: could not generate the support statement: {exc}", file=sys.stderr)
        return 3
    if args.check:
        if out.is_file() and out.read_text(encoding="utf-8") == text:
            print(f"{out} is up to date")
            return 0
        print(f"{out} is out of date; run: odooflux support-statement --out {out}")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

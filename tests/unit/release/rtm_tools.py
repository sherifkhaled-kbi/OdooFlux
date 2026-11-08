"""RTM parser and release-gate checker (T005; REQ-TST-005, REQ-TST-002; FC A-8).

Reads ``docs/planning/REQUIREMENTS_TRACEABILITY_MATRIX.md``, ``specs/*/tasks.md`` tags, the test sources and
``docs/planning/KNOWLEDGE_BASE_BACKLOG.md``. A requirement passes the gate when one of these holds:

* ``TESTED``: a test file under ``tests/`` cites one of the requirement's ``TST-nnn-nnn`` ids (taken from the task
  lines that name the requirement) or the requirement id itself;
* ``DEFERRED_KB`` (A-8): the matrix "Release gate data" table lists the requirement with at least one backlog id, and
  every listed id exists in the backlog. A requirement with no test and no backlog id fails;
* ``RECORD``: the "Verification records" table points at an existing file that contains the stated anchor text.

``TESTED`` here means a mapped test exists in the suite; whether it passes is the suite result, gated separately.
Requirements whose every citing test file is opt-in (skipped without an environment switch) are reported as warnings,
and as failures with ``strict``. Nothing here records approval.

Usage: ``python tests/unit/release/rtm_tools.py [--strict] [--root DIR]`` (exit 1 on any failure).
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REQ_RE = re.compile(r"\bREQ-[A-Z]+-\d{3}\b")
TST_RE = re.compile(r"\bTST-\d{3}-\d{3}\b")
FINDING_RE = re.compile(r"\bF-[A-Z]+-\d+\b")
KB_RE = re.compile(r"\bKB-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b")
DEFERRED_TAG_RE = re.compile(r"\[DEFERRED_KB(?::([^\]]*))?\]")
TASK_RE = re.compile(r"^- \[(?P<mark>[ xX])\] (?P<id>T\d+)\b")
OPT_IN_MARKERS = ("skipUnless(", "skipIf(", "@unittest.skip", "self.skipTest(")

STATUSES = ("TESTED", "DEFERRED_KB", "RECORD", "UNMAPPED")
REPO = Path(__file__).resolve().parents[3]
RTM_PATH = "docs/planning/REQUIREMENTS_TRACEABILITY_MATRIX.md"
BACKLOG_PATH = "docs/planning/KNOWLEDGE_BASE_BACKLOG.md"


@dataclass
class Task:
    feature: str
    id: str
    done: bool
    line: str
    reqs: set
    tsts: set
    findings: set
    deferred_tags: list  # backlog ids named by [DEFERRED_KB: ...] tags; [] item "" when the tag has no id


@dataclass
class ReqResult:
    req: str
    status: str
    tests: list = field(default_factory=list)
    kb_ids: list = field(default_factory=list)
    record: str = ""
    notes: list = field(default_factory=list)


@dataclass
class RtmResult:
    rows: list
    failures: list
    warnings: list

    @property
    def ok(self) -> bool:
        return not self.failures

    def counts(self) -> dict:
        out = {s: 0 for s in STATUSES}
        for row in self.rows:
            out[row.status] += 1
        return out


def parse_rtm(text: str) -> list:
    """Requirement ids of the "Matrix" table, in order (the gate-data tables below it are not requirements)."""
    return [row[0] for row in _table(text, "Matrix") if REQ_RE.fullmatch(row[0])]


def _table(text: str, heading: str) -> list:
    """Rows (lists of cells) of the first table after the ``## heading`` line; empty when the heading is absent."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == f"## {heading}".lower()), None)
    if start is None:
        return []
    rows = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("|") and not re.match(r"^\|[\s\-:|]+\|$", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[1:] if rows else []  # drop the header row


def parse_gate_data(text: str) -> tuple:
    """``(deferred, records)``: REQ -> [KB ids] from "Release gate data"; REQ -> (path, anchor) from
    "Verification records"."""
    deferred, records = {}, {}
    for row in _table(text, "Release gate data"):
        if len(row) >= 3 and REQ_RE.fullmatch(row[0]) and row[1].strip("` ") == "DEFERRED_KB":
            deferred[row[0]] = KB_RE.findall(row[2])
    for row in _table(text, "Verification records"):
        if len(row) >= 3 and REQ_RE.fullmatch(row[0]):
            records[row[0]] = (row[1].strip("` "), row[2].strip("` "))
    return deferred, records


def parse_tasks(specs_dir: Path) -> list:
    tasks = []
    for path in sorted(Path(specs_dir).glob("*/tasks.md")):
        feature = path.parent.name
        for line in path.read_text(encoding="utf-8").splitlines():
            m = TASK_RE.match(line)
            if not m:
                continue
            tags = []
            for tag in DEFERRED_TAG_RE.finditer(line):
                ids = KB_RE.findall(tag.group(1) or "")
                tags.extend(ids or [""])
            tasks.append(Task(feature, m.group("id"), m.group("mark") in "xX", line, set(REQ_RE.findall(line)),
                              set(TST_RE.findall(line)), set(FINDING_RE.findall(line)), tags))
    return tasks


def backlog_ids(text: str) -> set:
    return set(re.findall(r"^\| (KB-[A-Za-z0-9\-]+) \|", text, re.M))


@dataclass
class Citations:
    tst: dict  # id -> {relative file}
    req: dict
    finding: dict
    opt_in: set  # files carrying a skip marker


def scan_tests(tests_dir: Path) -> Citations:
    tests_dir = Path(tests_dir)
    cites = Citations({}, {}, {}, set())
    for path in sorted(tests_dir.rglob("*.py")):
        if path.name == "rtm_tools.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(tests_dir.parent).as_posix()
        if any(marker in text for marker in OPT_IN_MARKERS):
            cites.opt_in.add(rel)
        for pattern, bucket in ((TST_RE, cites.tst), (REQ_RE, cites.req), (FINDING_RE, cites.finding)):
            for key in set(pattern.findall(text)):
                bucket.setdefault(key, set()).add(rel)
    return cites


def check_rtm(root: Path = REPO, *, strict: bool = False) -> RtmResult:
    root = Path(root)
    rtm_text = (root / RTM_PATH).read_text(encoding="utf-8")
    reqs = parse_rtm(rtm_text)
    tasks = parse_tasks(root / "specs")
    cites = scan_tests(root / "tests")
    backlog = backlog_ids((root / BACKLOG_PATH).read_text(encoding="utf-8")) if (root / BACKLOG_PATH).is_file() \
        else set()
    deferred, records = parse_gate_data(rtm_text)
    req_tsts: dict = {}
    for task in tasks:
        for req in task.reqs:
            req_tsts.setdefault(req, set()).update(task.tsts)
    failures, warnings, rows = [], [], []
    for req in reqs:
        row = ReqResult(req, "UNMAPPED")
        files = set()
        for tst in sorted(req_tsts.get(req, ())):
            if tst in cites.tst:
                row.tests.append(tst)
                files |= cites.tst[tst]
        if req in cites.req:
            files |= cites.req[req]
            row.tests.append(req)
        kb_ids = deferred.get(req, [])
        unknown = [k for k in kb_ids if k not in backlog]
        if req in deferred and not kb_ids:
            failures.append(f"{req}: DEFERRED_KB without a backlog id")
        for kb in unknown:
            failures.append(f"{req}: backlog id {kb} is not in {BACKLOG_PATH}")
        row.kb_ids = kb_ids
        record = records.get(req)
        record_ok = False
        if record:
            record_file = root / record[0]
            record_ok = record_file.is_file() and record[1] in record_file.read_text(encoding="utf-8", errors="replace")
            if not record_ok:
                failures.append(f"{req}: verification record {record[0]!r} missing or lacks anchor {record[1]!r}")
            else:
                row.record = f"{record[0]}#{record[1]}"
        if row.tests:
            row.status = "TESTED"
            if kb_ids and not unknown:
                row.notes.append("partial: " + ", ".join(kb_ids) + " deferred to the Knowledge Base backlog")
            if files and files <= cites.opt_in:
                msg = f"{req}: every mapped test file is opt-in or skippable ({', '.join(sorted(files))})"
                (failures if strict else warnings).append(msg)
        elif kb_ids and not unknown:
            row.status = "DEFERRED_KB"
        elif record_ok:
            row.status = "RECORD"
        else:
            failures.append(f"{req}: no passing mapped test, no DEFERRED_KB backlog id, no verification record")
        rows.append(row)
    for task in tasks:  # a task tagged DEFERRED_KB must name a real backlog id, and its REQs must be declared
        if not task.done or task.deferred_tags:
            for tag in task.deferred_tags:
                if tag == "":
                    failures.append(f"{task.feature}:{task.id}: [DEFERRED_KB] tag without a backlog id")
                elif tag not in backlog:
                    failures.append(f"{task.feature}:{task.id}: backlog id {tag} is not in {BACKLOG_PATH}")
                else:
                    for req in sorted(task.reqs):
                        if tag not in deferred.get(req, []):
                            warnings.append(f"{task.feature}:{task.id}: {req} defers to {tag} but the matrix gate "
                                            f"data does not list it")
    return RtmResult(rows, failures, warnings)


def resolved_findings(tasks: list) -> dict:
    """Finding id -> ["<feature>:<task>"] for findings named on completed (``[X]``) tasks."""
    resolved: dict = {}
    for task in tasks:
        if task.done:
            for fid in task.findings:
                resolved.setdefault(fid, []).append(f"{task.feature}:{task.id}")
    return resolved


def check_regression_citations(root: Path = REPO) -> list:
    """Resolved finding ids with no test file under ``tests/`` that cites them (REQ-TST-005, FR-002)."""
    root = Path(root)
    resolved = resolved_findings(parse_tasks(root / "specs"))
    cites = scan_tests(root / "tests")
    return sorted(fid for fid in resolved if fid not in cites.finding)


def format_report(result: RtmResult) -> str:
    out = ["RTM release gate (A-8)", "counts: " + ", ".join(f"{k}={v}" for k, v in result.counts().items())]
    for row in result.rows:
        if row.status != "TESTED" or row.notes:
            out.append(f"  {row.req}: {row.status} {' '.join(row.kb_ids)} {'; '.join(row.notes)}".rstrip())
    out += [f"FAIL {m}" for m in result.failures] + [f"WARN {m}" for m in result.warnings]
    out.append("RESULT: " + ("PASS" if result.ok else "FAIL"))
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RTM completeness check")
    parser.add_argument("--root", default=str(REPO))
    parser.add_argument("--strict", action="store_true", help="opt-in-only mappings fail")
    args = parser.parse_args(argv)
    result = check_rtm(Path(args.root), strict=args.strict)
    missing = check_regression_citations(Path(args.root))
    print(format_report(result))
    if missing:
        print("FAIL resolved findings without a citing regression test: " + ", ".join(missing))
    return 0 if result.ok and not missing else 1


if __name__ == "__main__":
    sys.exit(main())

"""Benchmark runner (T011; REQ-PRF-001, REQ-PRF-004; contracts/benchmark-protocol.md).

``python tests/benchmarks/run_benchmarks.py --modes serial,parallel,incremental`` generates the deterministic corpus
(``corpus_gen.py``), runs each mode N times (default 5) as a child process, and reports the median wall time, peak RSS
of the largest process of the run, files parsed and the report digest. It fails (exit 1) when

* a median exceeds its budget in ``budgets.json``,
* a median wall time or peak RSS regresses by more than 20 % against ``baseline.json``,
* the report digests of the modes differ, or the incremental re-run parses any file.

Results go to ``results/<date>-<sha>.json`` (never customer data: the corpus is synthetic). ``--record-baseline`` writes
the medians to ``baseline.json``. The reference machine is described in ``REFERENCE_MACHINE.md``; on another machine the
numbers are not comparable and ``--no-enforce`` reports without failing.
"""

import argparse
import hashlib
import json
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

try:
    from . import corpus_gen
except ImportError:  # run as a script: python tests/benchmarks/run_benchmarks.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import corpus_gen

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parents[1]
MODES = ("serial", "parallel", "incremental")
METRICS = ("wall_s", "peak_rss_mib")
REGRESSION_LIMIT = 0.20
IDENTITY_KEYS = {"run_id", "run_log", "rollback_cmd"}


def median(values):
    return statistics.median(values)


def report_digest(report: dict, roots=()) -> str:
    """SHA-256 of the report with run identity and absolute roots removed (no timing field exists in report v1)."""
    text = json.dumps(report, sort_keys=True)
    for root in sorted((str(r) for r in roots), key=len, reverse=True):
        text = text.replace(root, "<ROOT>")
    data = json.loads(text)

    def scrub(node):
        if isinstance(node, dict):
            return {k: scrub(v) for k, v in node.items() if k not in IDENTITY_KEYS}
        if isinstance(node, list):
            return [scrub(v) for v in node]
        return node

    return hashlib.sha256(json.dumps(scrub(data), sort_keys=True).encode("utf-8")).hexdigest()


def _budget_index(budgets: dict) -> dict:
    return {(row["metric"], row["mode"]): row for row in budgets.get("budgets", [])}


def validate_budgets(budgets: dict) -> list:
    """Problems with a budgets file: every metric and mode needs a value, a baseline reference and an approver field."""
    problems = []
    index = _budget_index(budgets)
    for mode in MODES:
        for metric in METRICS:
            if (metric, mode) not in index:
                problems.append(f"no budget for {metric} in mode {mode}")
    if ("files_parsed", "incremental") not in index:
        problems.append("no budget for files_parsed in mode incremental")
    for (metric, mode), row in index.items():
        for key in ("value", "baseline_ref", "headroom_factor", "approved_by", "date", "rationale"):
            if row.get(key) in (None, ""):
                problems.append(f"{metric}/{mode}: missing {key}")
    return problems


def check_budgets(results: dict, budgets: dict) -> list:
    index = _budget_index(budgets)
    failures = []
    for mode, data in sorted(results.items()):
        for metric, field in (("wall_s", "median_wall_s"), ("peak_rss_mib", "peak_rss_mib"), ("files_parsed",
                                                                                              "files_parsed")):
            value = data.get(field)
            if value is None:
                continue
            row = index.get((metric, mode))
            if row is None:
                failures.append(f"{mode}: no budget for {metric}")
            elif value > row["value"]:
                failures.append(f"{mode}: {metric} {value} exceeds the budget {row['value']}")
    return failures


def check_regression(results: dict, baseline) -> list:
    if not baseline:
        return ["no stored baseline: run with --record-baseline on the reference machine"]
    failures = []
    for mode, data in sorted(results.items()):
        base = baseline["modes"].get(mode)
        if base is None:
            failures.append(f"{mode}: not in the stored baseline")
            continue
        for field in ("median_wall_s", "peak_rss_mib"):
            now, then = data.get(field), base.get(field)
            if now is not None and then and now > then * (1 + REGRESSION_LIMIT):
                failures.append(f"{mode}: {field} {now} regressed more than 20 % against the baseline {then}")
    return failures


def check_digests(results: dict) -> list:
    digests = {mode: data.get("report_digest") for mode, data in results.items()}
    reference = digests.get("serial") or next(iter(digests.values()), None)
    failures = [f"{mode}: report digest differs from serial" for mode, d in sorted(digests.items()) if d != reference]
    incremental = results.get("incremental", {})
    if incremental.get("files_parsed") not in (None, 0):
        failures.append(f"incremental: re-parsed {incremental['files_parsed']} files on an unchanged corpus")
    return failures


def machine_profile() -> dict:
    cpu = ""
    try:
        cpu = next(l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines()
                   if l.startswith("model name"))
    except (OSError, StopIteration):
        cpu = platform.processor()
    mem = ""
    try:
        kib = int(next(l.split()[1] for l in Path("/proc/meminfo").read_text().splitlines()
                       if l.startswith("MemTotal")))
        mem = f"{kib / 1048576:.1f} GiB"
    except (OSError, StopIteration, ValueError):
        pass
    return {"cpu": cpu, "cores": os.cpu_count(), "memory": mem, "os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version()}


def git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True,
                             timeout=10)
        return out.stdout.strip() or "nogit"
    except (OSError, subprocess.SubprocessError):
        return "nogit"


_WRAPPER = (
    "import json,resource,subprocess,sys,time\n"
    "t=time.perf_counter()\n"
    "p=subprocess.run(sys.argv[1:],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)\n"
    "w=time.perf_counter()-t\n"
    "k=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss\n"
    "import re\n"
    "m=re.search(r'Incremental: (\\d+) analysed, (\\d+) skipped, (\\d+) files parsed',p.stdout)\n"
    "print(json.dumps({'wall':w,'rss_kib':k,'code':p.returncode,'parsed':int(m.group(3)) if m else None,"
    "'tail':p.stdout[-800:]}))\n")


def run_once(corpus: Path, state: Path, report: Path, mode: str, jobs: int) -> dict:
    cmd = [sys.executable, str(REPO / "odooflux.py"), "--addons-path", str(corpus), "--from-version", "14",
           "--no-color", "--state-dir", str(state), "--report-format", "json", "--report", str(report),
           "--fail-on", "none"]
    if mode == "parallel":
        cmd += ["--jobs", str(jobs)]
    if mode == "incremental":
        cmd += ["--incremental"]
    proc = subprocess.run([sys.executable, "-c", _WRAPPER, *cmd], capture_output=True, text=True, cwd=tempfile.gettempdir())
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    return {"wall_s": data["wall"], "peak_rss_mib": data["rss_kib"] / 1024, "code": data["code"],
            "parsed": data["parsed"], "tail": data["tail"]}


def benchmark(corpus: Path, modes, runs: int, jobs: int) -> dict:
    results = {}
    roots = [str(corpus)]
    for mode in modes:
        state = Path(tempfile.mkdtemp(prefix="odooflux-bench-state-"))
        report = state / "report.json"
        samples = []
        if mode == "incremental":  # prime the index with one untimed run, then time re-runs of the unchanged corpus
            run_once(corpus, state, report, mode, jobs)
        for _ in range(runs):
            if mode != "incremental":
                shutil.rmtree(state, ignore_errors=True)
                state.mkdir(parents=True)
            sample = run_once(corpus, state, report, mode, jobs)
            if sample["code"] != 0:
                raise RuntimeError(f"{mode}: run exited with {sample['code']}: {sample['tail']}")
            samples.append(sample)
        data = json.loads(report.read_text(encoding="utf-8"))
        results[mode] = {
            "runs": [round(s["wall_s"], 3) for s in samples],
            "median_wall_s": round(median([s["wall_s"] for s in samples]), 3),
            "peak_rss_mib": round(max(s["peak_rss_mib"] for s in samples), 1),
            "files_parsed": samples[-1]["parsed"],
            "report_digest": report_digest(data, roots + [str(state)]),
        }
        shutil.rmtree(state, ignore_errors=True)
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OdooFlux benchmark runner")
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--modules", type=int, default=corpus_gen.DEFAULT_MODULES)
    parser.add_argument("--seed", type=int, default=corpus_gen.DEFAULT_SEED)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--jobs", type=int, default=0, help="workers for parallel mode (0 = one per CPU)")
    parser.add_argument("--out", default=str(BENCH / "results"))
    parser.add_argument("--budgets", default=str(BENCH / "budgets.json"))
    parser.add_argument("--baseline", default=str(BENCH / "baseline.json"))
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--no-enforce", action="store_true", help="report only; exit 0 whatever the numbers")
    args = parser.parse_args(argv)
    modes = [m for m in args.modes.split(",") if m]
    jobs = args.jobs or (os.cpu_count() or 1)
    corpus_dir = Path(tempfile.mkdtemp(prefix="odooflux-bench-corpus-"))
    try:
        info = corpus_gen.generate(corpus_dir, modules=args.modules, seed=args.seed)
        results = benchmark(corpus_dir, modes, args.runs, jobs)
    finally:
        shutil.rmtree(corpus_dir, ignore_errors=True)
    machine = machine_profile()
    payload = {"corpus_id": info["corpus_id"], "seed": args.seed, "corpus_digest": info["digest"],
               "machine_profile": machine, "jobs": jobs, "runs_per_mode": args.runs, "modes": results}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{date.today().isoformat()}-{git_sha()}.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({m: {k: v for k, v in d.items() if k != "runs"} for m, d in results.items()}, indent=2))
    print(f"results: {target}")
    if args.record_baseline:
        Path(args.baseline).write_text(json.dumps(
            {"corpus_id": info["corpus_id"], "machine_profile": machine, "modes": {
                m: {k: d[k] for k in ("median_wall_s", "peak_rss_mib", "files_parsed")} for m, d in results.items()}},
            indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"baseline recorded: {args.baseline}")
        return 0
    failures = check_digests(results)
    budgets_file, baseline_file = Path(args.budgets), Path(args.baseline)
    if budgets_file.is_file():
        budgets = json.loads(budgets_file.read_text(encoding="utf-8"))
        failures += validate_budgets(budgets) + check_budgets(results, budgets)
        if budgets.get("corpus_id") != info["corpus_id"]:
            failures.append(f"budgets are for corpus {budgets.get('corpus_id')}, this run used {info['corpus_id']}")
    else:
        failures.append(f"no budgets file at {budgets_file}")
    baseline = json.loads(baseline_file.read_text(encoding="utf-8")) if baseline_file.is_file() else None
    failures += check_regression(results, baseline)
    for message in failures:
        print(f"FAIL {message}")
    print("RESULT: " + ("PASS" if not failures else "FAIL"))
    return 0 if (not failures or args.no_enforce) else 1


if __name__ == "__main__":
    sys.exit(main())

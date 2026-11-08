"""Process-pool executor with deterministic merge, and the serial/incremental module loop (T012, T013; REQ-PRF-003).

Analysis and dry-run modules are independent, so they run in worker processes (``concurrent.futures`` with the ``fork``
start method: the workers inherit the registries and run context, nothing is pickled outward). Results are merged in
plan order, whatever order the workers finish in: ``on_module`` callbacks, run-log events and checkpoints happen in the
order a serial run would produce. Workers write nothing; their run-log events are buffered and replayed by the parent.

A worker that raises blocks its own module (``BLOCKED``, with the error). A worker process that dies breaks the pool;
each module that had no result is then retried alone in a fresh single-worker pool, so only the module that kills its
worker ends up ``BLOCKED`` ("worker died").

Fix mode never runs in parallel: promotion, backup and the per-module checkpoint are ordered writes (REQ-SAF-005).
Where ``fork`` is unavailable the run is serial."""

import concurrent.futures as futures
import copy
import multiprocessing
import os
from pathlib import Path

from odooflux.utils import parsecount

PARALLEL_MODES = ("analyze", "dry_run")
_CTX: dict = {}  # set in the parent before the pool forks


def resolve_jobs(jobs) -> int:
    """``0`` means one worker per CPU; negative values are rejected."""
    jobs = int(jobs)
    if jobs < 0:
        raise ValueError("--jobs must be 0 (all CPUs) or a positive number")
    return (os.cpu_count() or 1) if jobs == 0 else jobs


def can_parallelise(mode: str, jobs: int) -> bool:
    return jobs > 1 and mode in PARALLEL_MODES and hasattr(os, "fork")


class BufferedLog:
    """Stands in for the run log in a worker: records events for the parent to append in order."""

    def __init__(self):
        self.events = []

    def append(self, event: str, **fields) -> None:
        self.events.append([event, fields])


class WorkerRun:
    """The part of a run directory a read-only module pass uses."""

    def __init__(self, run_id: str, reversible: bool):
        self.run_id = run_id
        self.reversible = reversible
        self.log = BufferedLog()
        self.backup_dir = Path("<read-only>")  # path arithmetic only; analysis never writes a backup


def _analyse(entry: dict, options, registries, layer3, run_ctx, run_id: str, reversible: bool) -> dict:
    """One module, read-only. Returns ``{"entry": ..., "events": [...], "parsed": n}`` or ``{"error": ...}``."""
    from odooflux.core.orchestrator.run import _process_module  # late: run imports this module
    stub = WorkerRun(run_id, reversible)
    before = parsecount.snapshot()
    work = copy.deepcopy(entry)
    try:
        _process_module(stub, work, options, registries, layer3, run_ctx)
    except Exception as exc:  # the module is blocked, the run goes on
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"entry": work, "events": stub.log.events, "parsed": parsecount.snapshot() - before}


def _work(index: int) -> dict:
    ctx = _CTX
    return _analyse(ctx["entries"][index], ctx["options"], ctx["registries"], ctx["layer3"], ctx["run_ctx"],
                    ctx["run_id"], ctx["reversible"])


def _pool(workers: int):
    return futures.ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("fork"))


def _blocked(entry: dict, options, run, reason: str) -> dict:
    """A result for a module that has no worker result."""
    from odooflux.core.orchestrator.run import report_to_dict
    from odooflux.rules.shared.legacy_rules import MigrationReport
    report = MigrationReport(module_path=entry["path"], from_version=options.from_version,
                             to_version=options.to_version, reversible=run.reversible)
    report.blocked, report.block_reason = True, reason
    work = copy.deepcopy(entry)
    work.update(status="BLOCKED", report=report_to_dict(report))
    return {"entry": work, "events": [["module_blocked", {"module": entry["name"], "reason": reason}]], "parsed": 0}


def _results(pending: list, entries: list, jobs: int, options, run):
    """Yield ``(index, result)`` in plan order for the cache misses in *pending* (indices into *entries*).

    ``result`` is None when the pool broke before that module produced one; the caller retries it alone."""
    workers = min(jobs, max(len(pending), 1))
    with _pool(workers) as pool:
        submitted = [(i, pool.submit(_work, i)) for i in pending]
        for i, future in submitted:
            try:
                result = future.result()
            except futures.process.BrokenProcessPool:
                yield i, None
                continue
            if "error" in result:
                result = _blocked(entries[i], options, run, f"worker failed: {result['error']}")
            yield i, result


def process_modules(run, state: dict, options, registries, layer3, run_ctx, *, jobs: int = 1, index=None,
                    on_module=None, hook=None) -> None:
    """Process every unfinished module: serial or pooled, with the incremental index when given.

    Called by ``run_pipeline`` for read-only runs that ask for ``jobs > 1`` or an index."""
    from odooflux.core.orchestrator.run import DONE_STATES, _process_module
    entries = state["modules"]
    use_index = index is not None and options.mode in PARALLEL_MODES
    if use_index:
        index.prepare(run_ctx, registries)
    keys, cached, pending = {}, {}, []
    for i, entry in enumerate(entries):
        if entry["status"] in DONE_STATES:
            continue
        if use_index:
            keys[i] = index.key(entry, options, run_ctx)
            hit = index.lookup(entry, keys[i])
            if hit is not None:
                cached[i] = hit
                continue
        pending.append(i)
    results = {}
    if can_parallelise(options.mode, jobs) and len(pending) > 1:
        _CTX.update(entries=entries, options=options, registries=registries, layer3=layer3, run_ctx=run_ctx,
                    run_id=run.run_id, reversible=run.reversible)
        try:
            retry = []
            for i, result in _results(pending, entries, jobs, options, run):
                if result is None:
                    retry.append(i)
                else:
                    results[i] = result
            for i in retry:  # a worker died: find out which module is to blame, alone
                with _pool(1) as pool:
                    try:
                        result = pool.submit(_work, i).result()
                    except futures.process.BrokenProcessPool:
                        result = _blocked(entries[i], options, run, "worker died while analysing this module")
                if "error" in result:
                    result = _blocked(entries[i], options, run, f"worker failed: {result['error']}")
                results[i] = result
        finally:
            _CTX.clear()
    for i, entry in enumerate(entries):
        if entry["status"] in DONE_STATES:
            continue
        entry["status"] = "WORKING"
        if i in cached:
            outcome = cached[i]
        elif i in results:
            outcome = results[i]
        else:  # serial
            outcome = _analyse(entry, options, registries, layer3, run_ctx, run.run_id, run.reversible)
            if "error" in outcome:
                outcome = _blocked(entry, options, run, f"worker failed: {outcome['error']}")
        entry.update(outcome["entry"])
        for event, fields in outcome["events"]:
            run.log.append(event, **fields)
        if use_index and i not in cached:
            index.parsed += outcome.get("parsed", 0)
        if use_index and i not in cached and outcome["entry"].get("status") != "BLOCKED":
            index.store(entry, keys[i], {"entry": json_safe(outcome["entry"]), "events": outcome["events"]})
        run.save_module(entry)
        if on_module is not None:
            on_module(entry)
        if hook is not None:
            hook(entry["name"])
    if use_index:
        index.save()


def json_safe(entry: dict) -> dict:
    import json
    return json.loads(json.dumps(entry))

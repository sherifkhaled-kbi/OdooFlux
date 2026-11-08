"""TST-011-089 (REQ-KAP-029, REQ-KAP-044, SC-K05): scripted acceptance of `specs/011-knowledge-acquisition-pipeline/quickstart.md`.

Every `odooflux knowledge ...` / `odooflux migrate ...` line of the corrected quickstart is executed here, in order, through
the real composition root (`odooflux.builtins.main`, the function behind the `odooflux` entry point) with `socket.socket` and
`socket.create_connection` patched to fail and counted. No AI, no Docker, no network. All state lives in one temporary
directory; the built-in knowledge tree is only read (copied from), never written.

Substitutions forced by the synthetic corpus (`tests/fixtures/kap/make_synth_repo.py` has 16.0 and 17.0 only):
- the quickstart pair 17-18 runs as the synthetic pair 16-17 (from = odoo-community-16.0, to = odoo-community-17.0);
- the quickstart's two `source add` lines run as step 1a (from source) and step 1b (to source);
- `migrate` runs 16 -> 17 on a copy of tests/golden_fixtures/17.0/kbi_demo without expected/.

Step outcomes are collected, not raised one by one: every step runs, a failing or blocked step is reported with its exit
code and output, and the flow passes only when every step is PASS. A step that depends on a failed step is BLOCKED.

Classification of quickstart lines that do NOT work as written (before this task's fixes; the test runs the corrected text):

| Quickstart line (as originally written) | Step | Classification | Cause |
|---|---|---|---|
| `source add --file sources.json` (two sources in one file) | 1a, 1b | DOCUMENTATION DEFECT | `source add` takes one spec object per call; a list is refused ("spec file must hold one JSON object") |
| `source acquire` | 1c | works | exit 0; exit 4 with a missing pinned SHA (see row 3d) |
| `extract --from --to --step 17-18` | 1e | DOCUMENTATION DEFECT | `--blobs DIR` and `--out DIR` are required and missing from the line |
| (pair 17-18 itself) | 1e | FIXTURE DEFECT | the synthetic corpus has no 18.0 repository; run as 16-17 |
| `ledger list --unresolved` | 1f | DOCUMENTATION DEFECT | no such flag (exit 2); real: `--ledger FILE --disposition UNRESOLVED` |
| `candidates generate --step 17-18` | 1g | IMPLEMENTATION DEFECT + DOCUMENTATION DEFECT | the flag `--step` does not exist and `--path/--ledger/--source/--checked-on` are required (doc). Implementation: a source spec with no `repository` used the `local:` URL as repository and failed the evidence schema (exit 1). FIXED in T089: the identity is `repository` or the slug of `expected_origin`; otherwise exit 2. |
| `candidates accept --all-valid` | 1i | DOCUMENTATION DEFECT | no bulk verb or flag (exit 2 "CR-ID required"); real: one `accept CR-ID` per candidate. Runs once 1g passes. |
| `rule create --from-file my-rule.json` | 1j | DOCUMENTATION DEFECT | `--path TREE` is required and missing from the line |
| `release build --dry-run` | 1k | DOCUMENTATION DEFECT | `--plan FILE` is required and missing (exit 2) |
| `release build` | 1l | DOCUMENTATION DEFECT | `--plan FILE` missing; and the line says it prints the 8 metrics, which only `coverage show` prints |
| `coverage show --release <kr-id>` | 1m | works | needs `--kb-home` (or `ODOOFLUX_KB_HOME`) |
| `package export <kr-id> -o odoo-17-18.ofkp` | 1n | works | |
| `package validate ... --expect-digest <sha256>` | 2a | DOCUMENTATION DEFECT | the flag takes the package `release_digest`, not the sha256 of the file (the file sha256 is refused, exit 3, P06) |
| `package import ... --activate` | 2b | DOCUMENTATION DEFECT | refused (exit 3, P10) for a release built from the built-in tree; `--downgrade-unverified` is required (intended, INTEGRATION_NOTES note 4) |
| `release list` | 2c | works | |
| `migrate <paths> --source 17.0 --target 18.0` | 2d | DOCUMENTATION DEFECT + FIXTURE DEFECT | positional paths, `--source`, `--target` do not exist (`--module`, `--from-version`, `--to-version`); the synthetic release covers 16-17 only |
| `release rollback` ("back to the previous release or built-in") | 2e | DOCUMENTATION DEFECT | rollback needs a previous release (exit 1 otherwise); the built-in is `release deactivate` (step 2f) |
| (section 3 table rows) | 3a-3e | works | exit codes and refusals as the table says |

Corrections made to quickstart.md are limited to these lines, the section 3 table is kept, and section 4 is unchanged.

Section 4 of the quickstart (unit and integration test commands) is not executed here, by its own rule (the full suite is not
run during KAP task execution; the live tests are opt-in). Those lines are listed in EXCLUDED_DOC_LINES with the reason.
"""

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from odooflux import builtins
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from tests.fixtures.kap import make_synth_repo as synth

REPO = Path(__file__).resolve().parents[3]
QUICKSTART = REPO / "specs" / "011-knowledge-acquisition-pipeline" / "quickstart.md"
GOLDEN = REPO / "tests" / "golden_fixtures" / "17.0" / "kbi_demo"
CREATED = "2026-11-08T10:00:00Z"
CREATED_2 = "2026-11-08T11:00:00Z"
CHECKED_ON = "2026-11-08"
FROM_ID, TO_ID = "odoo-community-16.0", "odoo-community-17.0"
RULE_ROW = {"id": "12-13.python.qs-probe", "step": "12-13", "category": "python_orm",
            "detector_ref": "odooflux.rules.python.generic:flag_decorator",
            "params": {"decorator": "api.qs_probe_unique"}, "risk": "LOW", "severity": "WARNING",
            "maturity": "DETECT_ONLY", "file_kinds": ["python"], "message": "probe", "suggestion": "probe"}
DATA_DIRS = ("evidence", "compatibility", "official_sources")
ORIGIN = "https://github.com/odoo/odoo"  # the official origin an official local clone must verify against
FORK_REPOSITORY = "maintainer/odoo-fork"  # explicit identity for an unofficial source
GIT_ENV = {"PATH": os.environ.get("PATH", ""), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "LC_ALL": "C"}

# Quickstart line (normalised: text before " #", stripped) -> the step that runs it.
STEP_FOR_LINE = {
    "odooflux knowledge source add --file ksrc-17.json --kb-home $KB": "1a",
    "odooflux knowledge source add --file ksrc-18.json --kb-home $KB": "1b",
    "odooflux knowledge source acquire --kb-home $KB": "1c",
    "odooflux knowledge source show odoo-community-17.0 --json": "1d",
    "odooflux knowledge extract --from $KB/snapshots/<snap17>.json --to $KB/snapshots/<snap18>.json --step 17-18 "
    "--blobs $KB/snapshots --out $WORK/ledger --kb-home $KB": "1e",
    "odooflux knowledge ledger list --ledger $WORK/ledger/17-18.ledger.json --disposition UNRESOLVED": "1f",
    "odooflux knowledge candidates generate --path $WORK/tree --ledger $WORK/ledger/17-18.ledger.json "
    "--source ksrc-17.json --checked-on 2026-11-08 --author maintainer": "1g",
    "odooflux knowledge candidates generate --path $WORK/tree --ledger $WORK/ledger/17-18.ledger.json "
    "--source ksrc-17-unofficial.json --checked-on 2026-11-08 --author maintainer": "1g",
    "odooflux knowledge candidates list --path $WORK/tree --json": "1h",
    "odooflux knowledge candidates accept <CR-ID> --path $WORK/tree --ledger $WORK/ledger/17-18.ledger.json "
    "--author maintainer": "1i",
    "odooflux knowledge rule create --path $WORK/tree --from-file my-rule.json --evidence EV-ID --author maintainer": "1j",
    "odooflux knowledge release build --plan build-plan.json --dry-run --kb-home $KB": "1k",
    "odooflux knowledge release build --plan build-plan.json --kb-home $KB": "1l",
    "odooflux knowledge coverage show --release <kr-id> --kb-home $KB": "1m",
    "odooflux knowledge package export <kr-id> -o odoo-17-18.ofkp --kb-home $KB": "1n",
    "odooflux knowledge package validate odoo-17-18.ofkp --expect-digest <release_digest>": "2a",
    "odooflux knowledge package import odoo-17-18.ofkp --activate --downgrade-unverified --kb-home $KB2": "2b",
    "odooflux knowledge release list --kb-home $KB2": "2c",
    "odooflux migrate --module <module-dir> --from-version 17 --to-version 18 --kb-home $KB2 --report report.json "
    "--report-format json": "2d",
    "odooflux knowledge release rollback --kb-home $KB2": "2e",
    "odooflux knowledge release deactivate --kb-home $KB2": "2f",
}
# Section 3 table rows (first column, as written in the quickstart) -> step.
STEP_FOR_TABLE_ROW = {
    "`package import` of an archive with `../x`": "3a",
    "import a package whose FIX_ENABLED rule has no official evidence": "3b",
    "`source fetch ID` without `--allow-network`": "3c",
    "pinned SHA absent from the clone": "3d",
    "`release remove <active-id>`": "3e",
}
# Section 4 lines: not executed by T089 (see module docstring).
EXCLUDED_DOC_LINES = {
    "python -m unittest discover -s tests/unit/knowledge/kap -v": "full KAP unit suite is not run during T089",
    "python -m unittest discover -s tests/integration/kap -v": "full KAP integration folder is not run during T089",
    "ODOOFLUX_KAP_CLONES=/path/to/clones ODOOFLUX_KAP_LIVE_TESTS=1 python -m unittest tests.integration.kap.test_live_sources":
        "opt-in live test; T089 sets no opt-in variable",
}
STEP_IDS = {"1a", "1b", "1c", "1d", "1e", "1f", "1g", "1h", "1i", "1j", "1k", "1l", "1m", "1n",
            "2a", "2b", "2b0", "2c", "2d", "2e", "2f", "3a", "3b", "3c", "3d", "3e"}
METRIC_RE = re.compile(r"^M[1-8] ", re.MULTILINE)


def _spec(sid, url, revision, branch, official=False):
    spec = {"source_id": sid, "kind": "GIT_COMMUNITY", "official": False, "url": url, "licence_access": "PUBLIC_OPEN",
            "licence_id": "LGPL-3", "branch": branch, "revision": revision,
            "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []}, "retrieved_at": None,
            "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True}
    if official:  # a local clone is official only through expected_origin, verified at acquisition
        spec.update({"official": True, "expected_origin": ORIGIN})
    return spec


def _normalise(line: str) -> str:
    return line.split(" #", 1)[0].strip()


def _quickstart_odooflux_lines() -> list:
    """Every `odooflux ...` command line in the quickstart code blocks (sections 1 to 3)."""
    lines = []
    for raw in QUICKSTART.read_text(encoding="utf-8").splitlines():
        text = _normalise(raw)
        if text.startswith("odooflux "):
            lines.append(text)
    return lines


class QuickstartAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.net = mock.MagicMock(side_effect=AssertionError("network is disabled"))
        cls._patches = [mock.patch.object(socket, "socket", cls.net),
                        mock.patch.object(socket, "create_connection", cls.net),
                        mock.patch.dict(os.environ, {"ODOOFLUX_KB_HOME": str(cls.base / "env-kb-home-unused")})]
        for patch in cls._patches:
            patch.start()

    @classmethod
    def tearDownClass(cls):
        for patch in reversed(cls._patches):
            patch.stop()
        cls._tmp.cleanup()

    def setUp(self):
        self.rows = []  # (step, status, detail)
        self.net.reset_mock()

    # ----- step helpers -------------------------------------------------------------------------------------------
    def _cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = builtins.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def _record(self, step, ok, detail):
        self.rows.append((step, "PASS" if ok else "FAIL", detail))
        return ok

    def _run(self, step, argv, want=0):
        code, out, err = self._cli(*argv)
        text = (out + err).strip().splitlines()
        tail = " | ".join(text[-3:])[:400]
        self._record(step, code == want, f"exit {code} (want {want}): {tail}")
        return code, out, err

    def _check(self, step, cond, detail):
        return self._record(step, bool(cond), detail)

    def _blocked(self, step, why):
        self.rows.append((step, "BLOCKED", why))

    def _section(self, name, fn):
        try:
            fn()
        except Exception as exc:  # a crashed section is a failure of its steps, reported with the section name
            self.rows.append((name, "FAIL", f"section crashed: {type(exc).__name__}: {exc}"))

    # ----- the flow -------------------------------------------------------------------------------------------------
    def test_quickstart_commands_succeed_offline(self):
        """Variant A (the quickstart as written): official local clone, identity from expected_origin."""
        self._flow(official=True)

    def test_quickstart_variant_unofficial_explicit_repository(self):
        """Variant B: unofficial source, identity from an explicit `repository` in its candidate source file."""
        self._flow(official=False)

    def _flow(self, *, official):
        self.official = official
        self.repository = "odoo/odoo" if official else FORK_REPOSITORY
        self.maint = self.base / ("maint-official" if official else "maint-unofficial")
        self.kb = self.maint / "kb"
        self.work = self.maint
        self.registry = self.maint / "sources.json"
        self.tree = self.maint / "tree"
        self.ledger = self.maint / "ledger" / "16-17.ledger.json"
        self.pkg = self.maint / "odoo-17-18.ofkp"
        self._section("section 1", self._section1)
        if self.official:  # variant B stops after candidate generation: see _section1
            self._section("section 2", self._section2)
            self._section("section 3", self._section3)
        self._check("socket", self.net.call_count == 0, f"socket calls during the flow: {self.net.call_count}")
        if self.official:
            executed = {step for step, _, _ in self.rows}
            missing = sorted(STEP_IDS - executed)
            self._check("coverage", not missing, f"steps not reached: {missing}")
        bad = [row for row in self.rows if row[1] != "PASS"]
        report = "\n".join(f"{step:>10} {status:<8} {detail}" for step, status, detail in self.rows)
        self.assertEqual(bad, [], f"quickstart flow not fully passing:\n{report}")

    def _section1(self):
        self.maint.mkdir(parents=True, exist_ok=True)
        repo = synth.build_synth_repo(self.maint / "repo")
        self.repo = repo
        if self.official:  # the clone's origin must verify against expected_origin
            subprocess.run(["git", "-C", repo.path, "remote", "add", "origin", ORIGIN], check=True,
                           capture_output=True, env=GIT_ENV)
        local = "local:" + repo.path
        self.from_spec = self.maint / "ksrc-17-from.json"
        self.to_spec = self.maint / "ksrc-17.json"
        self.from_spec.write_text(json.dumps(_spec(FROM_ID, local, repo.from_sha, "16.0", official=self.official)), encoding="utf-8")
        self.to_spec.write_text(json.dumps(_spec(TO_ID, local, repo.to_sha, "17.0", official=self.official)), encoding="utf-8")
        # The candidate source file for `candidates generate --source`. Official: the registered spec itself.
        # Unofficial: the same spec plus an explicit `repository` (the registry schema does not take `repository`).
        self.candidate_source = self.to_spec
        if not self.official:
            self.candidate_source = self.maint / "ksrc-17-unofficial.json"
            self.candidate_source.write_text(json.dumps({**json.loads(self.to_spec.read_text(encoding="utf-8")),
                                                         "repository": FORK_REPOSITORY}), encoding="utf-8")
        KB = ["--kb-home", str(self.kb), "--registry", str(self.registry)]
        self._run("1a", ["knowledge", "source", "add", "--file", str(self.from_spec), *KB])
        self._run("1b", ["knowledge", "source", "add", "--file", str(self.to_spec), *KB])
        self._run("1c", ["knowledge", "source", "acquire", *KB])
        snaps = {}
        for name, sid in (("from", FROM_ID), ("to", TO_ID)):
            _, out, _ = self._run("1d", ["knowledge", "source", "show", sid, "--json", *KB])
            snaps[name] = json.loads(out).get("snapshot_id") if out.strip() else None
        self._check("1d", all(snaps.values()), f"snapshot ids: {snaps}")
        snap_dir = self.kb / "snapshots"
        ledger_dir = self.maint / "ledger"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        self._run("1e", ["knowledge", "extract", "--from", str(snap_dir / f"{snaps['from']}.json"),
                         "--to", str(snap_dir / f"{snaps['to']}.json"), "--step", "16-17",
                         "--blobs", str(snap_dir), "--out", str(ledger_dir), "--kb-home", str(self.kb)])
        self._check("1e", self.ledger.exists(), f"ledger written: {self.ledger.exists()}")
        _, out, _ = self._run("1f", ["knowledge", "ledger", "list", "--ledger", str(self.ledger),
                                     "--disposition", "UNRESOLVED"])
        self._check("1f", "UNRESOLVED" in out, "unresolved changes listed")
        self._stage_tree()
        code, _, _ = self._run("1g", ["knowledge", "candidates", "generate", "--path", str(self.tree),
                                      "--ledger", str(self.ledger), "--source", str(self.candidate_source),
                                      "--checked-on", CHECKED_ON, "--author", "maintainer"])
        _, out, _ = self._run("1h", ["knowledge", "candidates", "list", "--path", str(self.tree), "--json"])
        if not self.official:
            # Variant B: the explicit repository names every evidence record; no local path or local: url is written.
            # Accept and the release build are not run here: evidence from an unofficial url is refused by the
            # allow-list check (E002) at release build, a known limit recorded in quickstart.md.
            records = [json.loads(p.read_text(encoding="utf-8"))
                       for p in sorted((self.tree / "candidates" / "evidence").glob("EV-*.json"))]
            text = json.dumps(records)
            self._check("1g", bool(records) and all(r["repository"] == FORK_REPOSITORY and r["official"] is False
                                                    for r in records) and "local:" not in text
                        and str(self.maint) not in text,
                        f"{len(records)} unofficial evidence record(s) name {FORK_REPOSITORY}, no local path")
            return
        if code != 0:
            self._blocked("1i", "1g failed (IMPLEMENTATION DEFECT): no candidates to accept")
        else:
            rows = json.loads(out or "[]")
            self._check("1i", bool(rows), f"{len(rows)} candidates to accept")
            for row in rows:
                self._run("1i", ["knowledge", "candidates", "accept", row["candidate_id"], "--path", str(self.tree),
                                 "--ledger", str(self.ledger), "--author", "maintainer", "--at", CREATED])
        rule_file = self.maint / "my-rule.json"
        rule_file.write_text(json.dumps(RULE_ROW), encoding="utf-8")
        self._run("1j", ["knowledge", "rule", "create", "--path", str(self.tree), "--from-file", str(rule_file),
                         "--evidence", "EV-001", "--author", "maintainer"])
        plan = self._plan(repo, label="qs-maint", created_at=CREATED)
        plan_file = self.maint / "build-plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        self._build_dry_run(plan_file)
        _, out, _ = self._run("1l", ["knowledge", "release", "build", "--plan", str(plan_file), "--kb-home", str(self.kb)])
        self.release_id = (re.search(r"^release (kr-\w+)$", out, re.MULTILINE) or [None, None])[1]
        self._check("1l", self.release_id is not None and "completeness" in out, f"release id printed: {self.release_id}")
        if self.release_id is None:
            return
        self.release_dir = self.kb / "releases" / self.release_id
        _, out, _ = self._run("1m", ["knowledge", "coverage", "show", "--release", self.release_id, "--kb-home", str(self.kb)])
        self._check("1m", len(METRIC_RE.findall(out)) == 8 and "completeness" in out and "recall" not in out.lower(),
                    f"eight metrics with fractions: {len(METRIC_RE.findall(out))}")
        self.pkg.parent.mkdir(parents=True, exist_ok=True)
        self._run("1n", ["knowledge", "package", "export", self.release_id, "-o", str(self.pkg), "--kb-home", str(self.kb)])
        self.release_digest = json.loads((self.release_dir / "release.json").read_text(encoding="utf-8"))["release_digest"]

    def _build_dry_run(self, plan_file):
        _, out, _ = self._run("1k", ["knowledge", "release", "build", "--plan", str(plan_file), "--dry-run",
                                     "--kb-home", str(self.kb)])
        steps = re.findall(r"^(\d\d) ", out, re.MULTILINE)
        self._check("1k", steps == [f"{i:02d}" for i in range(1, 18)] and "outcome PLAN" in out,
                    f"{len(steps)} planned steps")

    def _stage_tree(self):
        """A working tree (copy of the read-only built-in data folders) for candidates and manual rules."""
        self.tree.mkdir(parents=True, exist_ok=True)
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")

    def _plan(self, repo, *, label, created_at):
        local = "local:" + repo.path
        return {"label": label, "created_at": created_at, "checked_on": CHECKED_ON, "author": "maintainer",
                "sources": [_spec(FROM_ID, local, repo.from_sha, "16.0", official=self.official), _spec(TO_ID, local, repo.to_sha, "17.0", official=self.official)],
                "pairs": [{"step": "16-17", "from": FROM_ID, "to": TO_ID}],
                "source_meta": {FROM_ID: {"repository": self.repository}, TO_ID: {"repository": self.repository}}}

    def _section2(self):
        if getattr(self, "release_id", None) is None:
            self._blocked("2a", "section 1 release build did not produce a release")
            return
        self._run("2a", ["knowledge", "package", "validate", str(self.pkg), "--expect-digest", self.release_digest,
                         "--kb-home", str(self.base / "k-validate")])
        file_sha = hashlib.sha256(self.pkg.read_bytes()).hexdigest()
        code, _, _ = self._cli("knowledge", "package", "validate", str(self.pkg), "--expect-digest", file_sha,
                               "--kb-home", str(self.base / "k-validate"))
        self._check("2a", code == 3, f"file sha256 is not the expected digest (exit {code}, want 3)")
        k1 = self.base / "k1"
        code, _, err = self._cli("knowledge", "package", "import", str(self.pkg), "--kb-home", str(k1))
        self._check("2b0", code == 3 and "P10" in err and not (k1 / "active.json").exists(),
                    f"as written (no --downgrade-unverified): exit {code}, P10 named, nothing active")
        self.k2 = self.base / "k2"
        self._run("2b", ["knowledge", "package", "import", str(self.pkg), "--activate", "--downgrade-unverified",
                         "--kb-home", str(self.k2)])
        active = json.loads((self.k2 / "active.json").read_text(encoding="utf-8"))
        self.installed_id = active["release_id"]
        _, out, _ = self._run("2c", ["knowledge", "release", "list", "--kb-home", str(self.k2)])
        self._check("2c", re.search(rf"^{self.installed_id} +ACTIVE", out, re.MULTILINE) is not None, "release listed ACTIVE")
        self._migrate_on(self.k2)
        self._rollback_chain()
        self._run("2f", ["knowledge", "release", "deactivate", "--kb-home", str(self.k2)])
        self._check("2f", not (self.k2 / "active.json").exists(), "active pointer removed (built-in knowledge)")

    def _migrate_on(self, home):
        module = self.base / "migrate" / "kbi_demo"
        shutil.copytree(GOLDEN, module, ignore=shutil.ignore_patterns("expected"))
        report = self.base / "migrate" / "report.json"
        code, _, err = self._cli("migrate", "--module", str(module), "--kb-home", str(home),
                                 "--state-dir", str(self.base / "migrate" / "state"), "--from-version", "16",
                                 "--to-version", "17", "--report", str(report), "--report-format", "json")
        self._record("2d", code in (0, 1) and report.exists(), f"migrate exit {code} (0 or 1 expected): {err[-200:]}")
        if report.exists():
            block = json.loads(report.read_text(encoding="utf-8")).get("knowledge_release", {})
            active = json.loads((home / "active.json").read_text(encoding="utf-8"))
            self._check("2d", block.get("release_id") == active["release_id"] and block.get("digest") == active["digest"]
                        and block.get("builtin") is False,
                        f"report release id {block.get('release_id')} digest {str(block.get('digest'))[:12]}...")

    def _rollback_chain(self):
        """Two installed releases (the built one and a second build of the same plan): rollback restores the first.
        Before the second activation there is no previous release, so the same command is refused (exit 1)."""
        self._run("2e", ["knowledge", "release", "rollback", "--kb-home", str(self.k2)], want=1)
        self._second_release()

    def _second_release(self):
        plan = self._plan(self.repo, label="qs-maint-2", created_at=CREATED_2)
        plan_file = self.maint / "build-plan-2.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        _, out, _ = self._cli("knowledge", "release", "build", "--plan", str(plan_file), "--kb-home", str(self.kb))
        second = (re.search(r"^release (kr-\w+)$", out, re.MULTILINE) or [None, None])[1]
        if second is None:
            self._blocked("2e", "second release build failed; rollback not run")
            return
        pkg2 = self.maint / "second.ofkp"
        self._cli("knowledge", "package", "export", second, "-o", str(pkg2), "--kb-home", str(self.kb))
        k5 = self.base / "k5"
        self._cli("knowledge", "package", "import", str(self.pkg), "--activate", "--downgrade-unverified", "--kb-home", str(k5))
        first_id = json.loads((k5 / "active.json").read_text(encoding="utf-8"))["release_id"]
        self._cli("knowledge", "package", "import", str(pkg2), "--activate", "--downgrade-unverified", "--kb-home", str(k5))
        self._check("2e", json.loads((k5 / "active.json").read_text(encoding="utf-8"))["previous"], "second activation keeps a previous")
        self._run("2e", ["knowledge", "release", "rollback", "--kb-home", str(k5)])
        self._check("2e", json.loads((k5 / "active.json").read_text(encoding="utf-8"))["release_id"] == first_id,
                    "rollback re-activated the first release")
        self.k5 = k5
        self.k5_active = first_id

    def _section3(self):
        # 3a: traversal archive refused with exit 3, nothing installed
        bad = self.base / "bad.ofkp"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("../x", "escape")
            zf.writestr("package.json", "{}")
        k4 = self.base / "k4"
        self._run("3a", ["knowledge", "package", "import", str(bad), "--kb-home", str(k4)], want=3)
        installed = list((k4 / "releases").iterdir()) if (k4 / "releases").exists() else []
        self._check("3a", installed == [] and not (k4 / "active.json").exists() and not (self.base / "x").exists(),
                    "nothing installed, no file written outside")
        # 3b: FIX_ENABLED without official evidence refused; --downgrade-unverified caps it
        if getattr(self, "release_id", None) is None:
            self._blocked("3b", "section 1 release build did not produce a release")
            return
        k6 = self.base / "k6"
        code, _, err = self._cli("knowledge", "package", "import", str(self.pkg), "--kb-home", str(k6))
        installed = list((k6 / "releases").iterdir()) if (k6 / "releases").exists() else []
        self._check("3b", code == 3 and "P10" in err and installed == [] and not (k6 / "active.json").exists(),
                    f"refused without downgrade: exit {code}, P10 named, nothing installed")
        self._run("3b", ["knowledge", "package", "import", str(self.pkg), "--downgrade-unverified", "--kb-home", str(k6)])
        fix = [r.get("id") for path in (k6 / "releases").glob("*/knowledge/compatibility/*.rules.json")
               for r in json.loads(path.read_text(encoding="utf-8")) if r.get("maturity") == "FIX_ENABLED"]
        self._check("3b", fix == [], f"FIX_ENABLED rules left after the cap: {fix}")
        # 3c: source fetch without --allow-network: exit 2, no socket
        before = self.net.call_count
        self._run("3c", ["knowledge", "source", "fetch", FROM_ID, "--registry", str(self.registry),
                         "--kb-home", str(self.kb)], want=2)
        self._check("3c", self.net.call_count == before, "no socket call for the refused fetch")
        # 3d: pinned SHA absent from the clone: exit 4, no substitute, nothing snapshotted
        repo_dir = self.maint / "repo"
        absent = _spec("odoo-missing-17.0", "local:" + str(repo_dir), "0" * 40, "17.0")
        absent_file = self.base / "absent.json"
        absent_file.write_text(json.dumps(absent), encoding="utf-8")
        reg = self.base / "absent-sources.json"
        home = self.base / "absent-home"
        self._cli("knowledge", "source", "add", "--file", str(absent_file), "--registry", str(reg), "--kb-home", str(home))
        code, out, _ = self._cli("knowledge", "source", "acquire", "--registry", str(reg), "--kb-home", str(home))
        snaps = list((home / "snapshots").glob("ss-*.json")) if (home / "snapshots").exists() else []
        self._check("3d", code == 4 and "REVISION_UNAVAILABLE" in out and snaps == [],
                    f"exit {code} (want 4), no snapshot written: {snaps == []}")
        # 3e: removing the active release is refused
        if getattr(self, "k5", None) is not None:
            self._run("3e", ["knowledge", "release", "remove", self.k5_active, "--kb-home", str(self.k5)], want=1)
            _, out, _ = self._cli("knowledge", "release", "list", "--kb-home", str(self.k5))
            self._check("3e", re.search(rf"^{self.k5_active} +ACTIVE", out, re.MULTILINE) is not None,
                        "active release still ACTIVE")
        else:
            self._blocked("3e", "section 2 second release not set up")

    # ----- the documentation cross-check --------------------------------------------------------------------------
    def test_every_quickstart_command_has_a_step(self):
        lines = _quickstart_odooflux_lines()
        self.assertTrue(lines, "quickstart.md has no odooflux command lines")
        unmapped = [line for line in lines if line not in STEP_FOR_LINE]
        self.assertEqual(unmapped, [], "quickstart command lines without a test step")
        stale = [line for line in STEP_FOR_LINE if line not in lines]
        self.assertEqual(stale, [], "test step mappings for lines the quickstart no longer has")
        self.assertTrue(set(STEP_FOR_LINE.values()) <= STEP_IDS, "mapping names an unknown step")
        text = QUICKSTART.read_text(encoding="utf-8")
        for row in STEP_FOR_TABLE_ROW:
            self.assertIn(f"| {row} |", text, f"section 3 row not in quickstart: {row}")
        section4 = [_normalise(line) for line in QUICKSTART.read_text(encoding="utf-8").splitlines()
                    if line.startswith(("python -m unittest", "ODOOFLUX_KAP_CLONES"))]
        self.assertEqual(set(section4) - set(EXCLUDED_DOC_LINES), set(), "section 4 line neither run nor excluded")


if __name__ == "__main__":
    unittest.main()

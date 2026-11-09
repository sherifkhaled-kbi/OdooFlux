"""Feature 012 (packaging): the update workflows, the migrate fix and the offline guarantees, run from an installed wheel.

Opt-in (slow: builds a wheel, a venv and synthetic git repositories): ``ODOOFLUX_PACKAGING_INSTALL=1``. The wheel is built
offline from a copy of the project and installed with ``--no-index --no-deps`` into a clean venv. Every CLI call runs from
a temporary directory outside the repository, with a fresh kb-home (``ODOOFLUX_KB_HOME``).

How the update reaches local sources (no production hook is added):
  * ``odooflux`` (the console script, ``odooflux.builtins:main``) runs unchanged for every offline command and for migrate.
  * Online update verbs run through a test-side driver (``runner.py``, written to a temporary directory, never shipped). It
    calls the same entry point and replaces only the module attribute ``odooflux.cli.kap_update._run_update``, which the
    module documents as the test seam. The replacement calls the installed ``orchestrator.run_update`` with the seams that
    tests/integration/kap already use: ``catalog`` (a two-version catalog built from the wheel's catalog.json),
    ``ls_remote`` (remote metadata read from a configuration file), ``transport_for`` (local bare repositories) and
    ``fetch`` (the production ``remote_git.fetch_commit``, given a local transport). The CLI argument parsing, token
    resolution, kb-home resolution, rendering and exit codes are the installed code.
  * Why not the plain CLI: the CLI passes no source seam. ``remote_git`` builds its git environment from scratch (only PATH,
    HOME and the proxy variables survive), fixes its own ``-c`` options, requires an https identity under the allow-list,
    and accepts a local transport only through the Python ``transport_url`` argument. So no environment variable or git
    configuration can point the real CLI at a local repository.

Offline proof: every CLI process runs with a ``sitecustomize`` guard on ``PYTHONPATH`` that refuses every socket connect,
name lookup and network-capable subprocess, and appends each attempt to ``ODOOFLUX_GUARD_LOG``. Online runs allow ``git``
only when no argument is a network URL (``git remote`` configuration excepted), and git's own ``GIT_ALLOW_PROTOCOL`` is
``https:file``, so the only transport is a local path. Offline commands and migrate must leave the log empty.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.fixtures.kap import make_synth_repo as synth

from . import _wheel

CATALOG_MEMBER = "odooflux/knowledge/update/catalog.json"
COM_REPO = "https://github.com/odoo/odoo.git"
ENT_REPO = "https://github.com/odoo/enterprise.git"
TOKEN = "dummy-enterprise-token-0123456789"  # a fake value; never a credential

GUARD = '''\
"""Packaging-test network guard (loaded through PYTHONPATH). Every refused attempt is appended to ODOOFLUX_GUARD_LOG."""
import os
import re
import socket
import subprocess

_LOG = os.environ.get("ODOOFLUX_GUARD_LOG")
_LOCAL_GIT = os.environ.get("ODOOFLUX_GUARD_ALLOW_LOCAL_GIT") == "1"
_NETWORK_BINARIES = frozenset({"git", "ssh", "scp", "sftp", "curl", "wget"})
_NETWORK_URL = re.compile("^(https?|ssh|git|ftp)://|^[A-Za-z0-9._-]+@[^/ ]+:", re.IGNORECASE)
_GIT_WITH_VALUE = frozenset({"-c", "-C", "--git-dir", "--work-tree", "--namespace"})


def _refuse(what):
    if _LOG:
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write(what + chr(10))
    raise OSError("network disabled by the packaging test guard: " + what)


def _connect(self, *args, **kwargs):
    _refuse("socket.connect")


def _connect_ex(self, *args, **kwargs):
    _refuse("socket.connect_ex")


def _getaddrinfo(*args, **kwargs):
    _refuse("socket.getaddrinfo")


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo


def _git_subcommand(argv):
    i = 1
    while i < len(argv):
        arg = str(argv[i])
        if arg in _GIT_WITH_VALUE:
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            return arg, [str(x) for x in argv[i + 1:]]
    return "", []


_popen_init = subprocess.Popen.__init__


def _popen_init_guarded(self, args, *rest, **kwargs):
    argv = args if isinstance(args, (list, tuple)) else [args]
    name = os.path.basename(str(argv[0])) if argv else ""
    if name == "git" and _LOCAL_GIT:
        sub, tail = _git_subcommand(argv)
        if sub != "remote" and any(_NETWORK_URL.match(x) for x in tail):
            _refuse("subprocess git " + sub + " with a network URL")
    elif name in _NETWORK_BINARIES:
        _refuse("subprocess " + name)
    return _popen_init(self, args, *rest, **kwargs)


subprocess.Popen.__init__ = _popen_init_guarded
'''

# Test-side driver, written to a temporary directory and run with the installed interpreter. See the module docstring.
RUNNER = '''\
"""Test-side driver for the installed CLI (not shipped). Usage: runner.py CONFIG.json CLI_ARGS..."""
import json
import os
import sys


def main():
    with open(sys.argv[1], encoding="utf-8") as handle:
        config = json.load(handle)
    from odooflux import builtins
    from odooflux.cli import kap_update
    from odooflux.knowledge.update import catalog as catalog_mod
    from odooflux.knowledge.update import orchestrator
    from odooflux.knowledge.update import remote_git

    catalog = catalog_mod.load_catalog(config["catalog"])

    def _log(entry):
        with open(config["calls_log"], "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + chr(10))

    def ls_remote(repository, *, offline=False, credentials=None):
        _log({"op": "ls_remote", "repository": repository, "credentials": credentials is not None})
        if repository == config["enterprise_repo"] and credentials is not None and config.get("reject_enterprise"):
            raise remote_git.RemoteGitError("AUTH_FAILED", None, "the remote rejected the credentials")
        heads = config["heads"].get(repository)
        if heads is None:
            raise remote_git.RemoteGitError("UNAVAILABLE", None, "no such remote in the test configuration")
        return dict(heads)

    def transport_for(source_id):
        kind = "enterprise" if source_id.startswith("odoo-enterprise-") else "community"
        return config["transports"][kind]

    def fetch(url, **kwargs):
        if config.get("kill_on_fetch") and kwargs.get("branch") == config["kill_on_fetch"]:
            _log({"op": "fetch-killed", "branch": kwargs.get("branch")})
            os._exit(137)  # an interrupted acquisition: no cleanup, no result
        _log({"op": "fetch", "branch": kwargs.get("branch"), "credentials": kwargs.get("credentials") is not None})
        return remote_git.fetch_commit(url, **kwargs)

    def run_update(kb_home, **kwargs):
        return orchestrator.run_update(kb_home, catalog=catalog, ls_remote=ls_remote, fetch=fetch,
                                       transport_for=transport_for, fault_at=config.get("fault_at"), **kwargs)

    # `knowledge check` reads the same two-version catalog, and discovery.check resolves its default lister at call time.
    kap_update.load_catalog = lambda *args, **kwargs: catalog
    remote_git.ls_remote_heads = ls_remote
    kap_update._run_update = run_update
    raise SystemExit(builtins.main(sys.argv[2:]))


if __name__ == "__main__":
    main()
'''

# ----- synthetic sources (copied from tests/integration/kap/test_autofix_e2e.py and test_update_orchestrator.py) --------

HELPERS_16 = '''"""Synthetic helpers (16.0)."""

RATE = 2


def old_round(value):
    """Round to two places."""
    return round(value, 2)


def plain_old(value):
    return round(value, 2)


def const_old(value):
    return round(value * RATE, 2)


def diff_old(value):
    """Round to two places."""
    return round(value, 2)


def legacy_sum(a, b):
    return a + b
'''

HELPERS_17 = '''"""Synthetic helpers (17.0)."""
import warnings

RATE = 2


def new_round(value):
    """Round to two places. Replaces ``old_round``."""
    return round(value, 2)


def plain_new(value):
    return round(value, 2)


def const_new(value):
    """Replaces ``const_old``."""
    return round(value * RATE, 2)


def diff_new(value):
    """Replaces ``diff_old``."""
    return round(value, 3)


def new_sum(a, b):
    return a + b


def legacy_sum(a, b):
    """Deprecated alias of new_sum."""
    warnings.warn("legacy_sum is deprecated", DeprecationWarning, stacklevel=2)
    return new_sum(a, b)
'''

API_16 = '''"""Synthetic api helpers (16.0)."""


def multi(method):
    """Identity decorator kept for compatibility."""
    return method


def tracked(method):
    method.tracked = True
    return method


def model(method):
    return method
'''

API_17 = '''"""Synthetic api helpers (17.0)."""


def model(method):
    return method
'''

ODOO_16 = {"odoo/tools/helpers.py": HELPERS_16, "odoo/api.py": API_16}
ODOO_17 = {"odoo/tools/helpers.py": HELPERS_17, "odoo/api.py": API_17}

MODULE_MANIFEST = "{'name': 'fix_fixture', 'version': '17.0.1.0.0', 'depends': [], 'installable': True}\n"
SALE_BEFORE = '''from odoo import api
from odoo.api import multi
from odoo.tools.helpers import legacy_sum, old_round


class SaleFixture(object):
    @multi
    def action(self, x):
        """Mentions old_round in a docstring."""
        note = "old_round is replaced"  # comment: old_round
        return legacy_sum(old_round(x), 1)
'''
SALE_AFTER = '''from odoo import api
from odoo.api import multi
from odoo.tools.helpers import new_sum, new_round


class SaleFixture(object):
    def action(self, x):
        """Mentions old_round in a docstring."""
        note = "old_round is replaced"  # comment: old_round
        return new_sum(new_round(x), 1)
'''
SHADOW = '''from odoo.tools.helpers import old_round


def old_round(x):
    return x
'''


def _two_version_repo(dest: Path):
    """A 16.0 -> 17.0 Community repository: the synthetic trees plus the `odoo/` pairs above."""
    dest.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="wf-repo-"))
    try:
        home, template = scratch / "home", scratch / "template"
        home.mkdir()
        template.mkdir()
        init_env = synth._git_env(home, template, "")
        subprocess.run(["git", "init", "-q", str(dest)], env=init_env, check=True, capture_output=True)
        git_dir = dest / ".git"
        parent, shas = None, {}
        for version, trees in (("16.0", {**synth._TREE_16, **ODOO_16}), ("17.0", {**synth._TREE_17, **ODOO_17})):
            env = synth._git_env(home, template, synth._DATES[version])
            tree = synth._write_tree(git_dir, env, trees)
            args = ["commit-tree", tree, "-m", synth._MESSAGES[version]] + (["-p", parent] if parent else [])
            sha = synth._run(args, env, git_dir)
            synth._run(["update-ref", f"refs/heads/{version}", sha], env, git_dir)
            shas[version] = sha
            parent = sha
        synth._run(["symbolic-ref", "HEAD", "refs/heads/17.0"], init_env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"path": str(dest), "from_sha": shas["16.0"], "to_sha": shas["17.0"]}


def _enterprise_tree(tree: dict) -> dict:
    """The synthetic tree with the addon renamed to sale_ent (its manifest depends only on a Community module that exists)."""
    import re

    out = {}
    for path, text in tree.items():
        new_path = path.replace("sale_demo", "sale_ent")
        new_text = text.replace("sale_demo", "sale_ent")
        if path.endswith("__manifest__.py"):
            new_text = re.sub(r"'depends': \[[^\]]*\]", "'depends': ['sale_demo']", new_text)
        out[new_path] = new_text
    return out


def _enterprise_repo(dest: Path) -> dict:
    """Two-commit Enterprise clone (16.0 and 17.0 branches). Returns {version: sha}."""
    dest.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="wf-ent-"))
    try:
        home, template = scratch / "home", scratch / "template"
        home.mkdir()
        template.mkdir()
        init_env = synth._git_env(home, template, "")
        subprocess.run(["git", "init", "-q", str(dest)], env=init_env, check=True, capture_output=True)
        git_dir = dest / ".git"
        parent, shas = None, {}
        for version, tree in (("16.0", synth._TREE_16), ("17.0", synth._TREE_17)):
            env = synth._git_env(home, template, synth._DATES[version])
            tree_sha = synth._write_tree(git_dir, env, _enterprise_tree(tree))
            args = ["commit-tree", tree_sha, "-m", synth._MESSAGES[version]] + (["-p", parent] if parent else [])
            sha = synth._run(args, env, git_dir)
            synth._run(["update-ref", f"refs/heads/{version}", sha], env, git_dir)
            shas[version] = sha
            parent = sha
        synth._run(["symbolic-ref", "HEAD", "refs/heads/17.0"], init_env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return shas


def _repin_community(repo: str, from_sha: str) -> str:
    """A new 17.0 commit with the same tree and a new message: a changed revision of the same content."""
    scratch = Path(tempfile.mkdtemp(prefix="wf-repin-"))
    try:
        env = synth._git_env(scratch, scratch, "1720000000 +0000")
        git_dir = Path(repo) / ".git"
        tree = synth._run(["rev-parse", "17.0^{tree}"], env, git_dir)
        sha = synth._run(["commit-tree", tree, "-m", "Synthetic 17.0 target (re-pinned, same tree)",
                          "-p", from_sha], env, git_dir)
        synth._run(["update-ref", "refs/heads/17.0", sha], env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return sha


def _bare_copy(source: Path, dest: Path) -> str:
    """A local bare repository with every branch of `source`. Used only as the transport of a fetch."""
    scratch = Path(tempfile.mkdtemp(prefix="wf-bare-"))
    try:
        env = synth._git_env(scratch, scratch, "")
        subprocess.run(["git", "clone", "--bare", "-q", "--no-hardlinks", str(source), str(dest)],
                       env=env, check=True, capture_output=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return str(dest)


def _module(root: Path) -> Path:
    """A fresh custom module (the fixture of the fix run) under `root`."""
    mod = root / "fix_fixture"
    (mod / "models").mkdir(parents=True)
    (mod / "__manifest__.py").write_text(MODULE_MANIFEST, encoding="utf-8")
    (mod / "models" / "__init__.py").write_text("from . import sale\nfrom . import shadow\n", encoding="utf-8")
    (mod / "models" / "sale.py").write_text(SALE_BEFORE, encoding="utf-8")
    (mod / "models" / "shadow.py").write_text(SHADOW, encoding="utf-8")
    return mod


# ----- small helpers ------------------------------------------------------------------------------------------------------


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _tree(root: Path) -> dict:
    """relative path -> sha256 of the file bytes, or None for a directory. Covers the whole tree."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        out[rel] = None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@unittest.skipUnless(os.environ.get("ODOOFLUX_PACKAGING_INSTALL") == "1",
                     "opt-in: set ODOOFLUX_PACKAGING_INSTALL=1 (builds a wheel and a venv)")
@unittest.skipIf(_wheel.tooling_gap(), _wheel.tooling_gap() or "n/a")
class WheelWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="odooflux-workflows-wheel-"))
        venv = cls.work / "venv"
        made = subprocess.run([sys.executable, "-m", "venv", str(venv)], capture_output=True, text=True)
        if made.returncode:
            raise RuntimeError("cannot create a venv with pip (ensurepip unavailable): " + made.stderr[-300:])
        cls.py = venv / "bin" / "python"
        cls.exe = venv / "bin" / "odooflux"
        cls.wheel = _wheel.build_wheel()
        done = subprocess.run([str(cls.py), "-m", "pip", "install", "--no-index", "--no-deps", str(cls.wheel)],
                              capture_output=True, text=True, env=_clean_env())
        if done.returncode:
            raise RuntimeError("install failed:\n" + done.stdout[-1500:] + done.stderr[-1500:])
        cls.guard_dir = cls.work / "guard"
        cls.guard_dir.mkdir()
        (cls.guard_dir / "sitecustomize.py").write_text(GUARD, encoding="utf-8")
        cls.runner_dir = cls.work / "runner"
        cls.runner_dir.mkdir()
        (cls.runner_dir / "runner.py").write_text(RUNNER, encoding="utf-8")
        cls.outside = cls.work / "outside"
        cls.outside.mkdir()
        # The catalog is taken from the installed artifact itself, so the test drives the packaged catalog's entries.
        cls.packaged_catalog = zipfile.ZipFile(cls.wheel).read(CATALOG_MEMBER)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="wf-", dir=self.work))
        self.kb = self.dir / "kb-home"
        self.guard_log = self.dir / "guard.log"
        self.calls = self.dir / "calls.jsonl"
        self.cfg_path = self.dir / "runner-config.json"
        self.community = _two_version_repo(self.dir / "community")
        ent = _enterprise_repo(self.dir / "enterprise")
        doc = json.loads(self.packaged_catalog.decode("utf-8"))
        doc["entries"] = [e for e in doc["entries"] if e["version"] in ("16.0", "17.0")]
        catalog = self.dir / "catalog.json"
        catalog.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.config = {
            "catalog": str(catalog),
            "calls_log": str(self.calls),
            "enterprise_repo": ENT_REPO,
            "heads": {COM_REPO: {"16.0": self.community["from_sha"], "17.0": self.community["to_sha"]},
                      ENT_REPO: {"16.0": ent["16.0"], "17.0": ent["17.0"]}},
            "transports": {"community": _bare_copy(Path(self.community["path"]), self.dir / "community.git"),
                           "enterprise": _bare_copy(self.dir / "enterprise", self.dir / "enterprise.git")},
            "reject_enterprise": False,
            "kill_on_fetch": None,
            "fault_at": None,
        }
        self.module_root = self.dir / "fixture"
        self.module = _module(self.module_root)

    # --- helpers ---------------------------------------------------------------------------------------------------------

    def _env(self, *, local: bool, token=None, extra=None) -> dict:
        env = _clean_env()
        for key in ("ODOOFLUX_OFFLINE", "ODOOFLUX_ENTERPRISE_TOKEN", "ODOOFLUX_ENTERPRISE_TOKEN_FILE"):
            env.pop(key, None)
        env.update(ODOOFLUX_KB_HOME=str(self.kb), PYTHONPATH=str(self.guard_dir),
                   ODOOFLUX_GUARD_LOG=str(self.guard_log), ODOOFLUX_GUARD_ALLOW_LOCAL_GIT="1" if local else "0")
        if token is not None:
            env["ODOOFLUX_ENTERPRISE_TOKEN"] = token
        env.update(extra or {})
        return env

    def _run(self, *args, local=False, token=None, extra=None):
        """`local=True` runs the update verbs through the test driver; otherwise the installed console script runs as is."""
        env = self._env(local=local, token=token, extra=extra)
        if local:
            self.cfg_path.write_text(json.dumps(self.config, sort_keys=True), encoding="utf-8")
            argv = [str(self.py), str(self.runner_dir / "runner.py"), str(self.cfg_path), *map(str, args)]
        else:
            argv = [str(self.exe), *map(str, args)]
        return subprocess.run(argv, cwd=self.outside, capture_output=True, text=True, env=env, timeout=900)

    def _json(self, proc, returncode=0):
        """The parsed stdout. `returncode=None` skips the exit-code assertion (the outcome is asserted by the caller)."""
        if returncode is not None:
            self.assertEqual(proc.returncode, returncode, proc.stdout[-1500:] + proc.stderr[-1500:])
        try:
            return json.loads(proc.stdout)
        except ValueError:
            self.fail("stdout is not JSON: " + proc.stdout[-800:] + proc.stderr[-800:])

    def _update(self, *, token=None, returncode=0):
        return self._json(self._run("knowledge", "update", "--json", local=True, token=token), returncode)

    def _status(self):
        return self._json(self._run("knowledge", "status", "--json"))

    def _history(self):
        payload = self._json(self._run("knowledge", "history", "--json"))
        self.assertEqual(payload["chain"], "verified", payload)
        return payload

    def _active(self):
        return self._status()["release_id"]

    def _release_tree(self, release_id):
        return _tree(self.kb / "releases" / release_id)

    def _call_log(self):
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines() if line]

    def _assert_no_network_attempt(self):
        attempts = self.guard_log.read_text(encoding="utf-8") if self.guard_log.exists() else ""
        self.assertEqual(attempts, "", "a network call was attempted: " + attempts)

    def _assert_no_token(self, proc=None):
        for path in self.kb.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN.encode(), path.read_bytes(), f"token value in {path.relative_to(self.kb)}")
        if proc is not None:
            self.assertNotIn(TOKEN, proc.stdout + proc.stderr)

    def _repin(self):
        """Move the Community 17.0 branch to a new commit with the same tree, and publish it to a new bare copy."""
        new_sha = _repin_community(self.community["path"], self.community["to_sha"])
        self.community["to_sha"] = new_sha
        self.config["transports"]["community"] = _bare_copy(Path(self.community["path"]),
                                                            self.dir / f"community-{new_sha[:8]}.git")
        self.config["heads"][COM_REPO]["17.0"] = new_sha
        return new_sha

    def _migrate(self, module, *, fix=True, report=None, extra=None):
        work = Path(tempfile.mkdtemp(prefix="wf-migrate-", dir=self.dir))
        argv = ["migrate", "--module", str(module), "--kb-home", str(self.kb), "--state-dir", str(work / "state"),
                "--from-version", "16", "--to-version", "17"]
        if fix:
            argv.append("--fix")
        if report is not None:
            argv += ["--report", str(report), "--report-format", "json"]
        return self._run(*argv, extra=extra)

    # --- the guard -------------------------------------------------------------------------------------------------------

    def test_guard_refuses_a_socket_connect_in_this_environment(self):
        probe = subprocess.run([str(self.py), "-c", "import socket; socket.create_connection(('127.0.0.1', 9))"],
                               cwd=self.outside, capture_output=True, text=True, env=self._env(local=False))
        self.assertNotEqual(probe.returncode, 0, "the network guard did not refuse a connect")
        self.assertIn("network disabled", probe.stderr)
        # create_connection resolves the host name before it connects, so the first refusal is the lookup.
        lines = self.guard_log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines and all(line.startswith("socket.") for line in lines), lines)

    # --- A: fresh Community install, status, migrate --fix ----------------------------------------------------------------

    def test_a_fresh_community_install_then_status_then_migrate_fix(self):
        first = self._update()
        self.assertEqual(first["outcome"], "ACTIVE", first.get("reasons"))
        self.assertIsNone(first["previous_release"])
        self.assertEqual(first["enterprise"]["status"], "SKIPPED_NO_CREDENTIALS")
        remotes = [c["repository"] for c in self._call_log() if c["op"] == "ls_remote"]
        self.assertEqual(set(remotes), {COM_REPO}, "no Enterprise remote is read without a token")

        self.assertEqual(self._active(), first["new_release"])
        self.assertEqual([e["outcome"] for e in self._history()["entries"]], ["ACTIVE"])

        work = self.dir / "migrate-a"
        work.mkdir()
        report = work / "report.json"
        proc = self._migrate(self.module, report=report)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((self.module / "models" / "sale.py").read_text(encoding="utf-8"), SALE_AFTER)
        self.assertEqual((self.module / "models" / "shadow.py").read_text(encoding="utf-8"), SHADOW)
        self.assertEqual((self.module / "__manifest__.py").read_text(encoding="utf-8"), MODULE_MANIFEST)
        applied = _read_json(report)["summary"]["edits"]["applied"]
        self.assertGreater(applied, 0)
        self._assert_no_network_attempt()

    # --- B: Community plus Enterprise with a fake authorized token --------------------------------------------------------

    def test_b_community_plus_enterprise_with_fake_authorized_credentials(self):
        proc = self._run("knowledge", "update", "--json", local=True, token=TOKEN)
        result = self._json(proc)
        self.assertEqual(result["outcome"], "ACTIVE", result.get("reasons"))
        self.assertEqual(result["enterprise"]["status"], "ACQUIRED")
        self.assertEqual(result["enterprise"]["freshness"], "FRESH")
        meta = _read_json(self.kb / "releases" / result["new_release"] / "release.json")
        self.assertEqual(meta["confidentiality"], "internal")
        self.assertEqual(len(meta["sources"]), 4)
        self.assertIn([ENT_REPO, True], [[c["repository"], c["credentials"]] for c in self._call_log()
                                         if c["op"] == "ls_remote"], "the Enterprise remote was read with the token")
        self.assertEqual(self._active(), result["new_release"])
        self._history()
        self._assert_no_token(proc)

    # --- C: incremental update after a new commit in a source repository --------------------------------------------------

    def test_c_incremental_update_after_a_new_source_commit(self):
        first = self._update()
        self.assertEqual(first["outcome"], "ACTIVE", first.get("reasons"))
        rid1 = first["new_release"]
        before = self._release_tree(rid1)

        new_sha = self._repin()
        check = self._json(self._run("knowledge", "check", "--json", local=True), returncode=None)
        self.assertIn("KNOWLEDGE_UPDATE_AVAILABLE", check["statuses"], check)
        self.assertNotIn("NO_UPDATE", check["statuses"], check)

        # A fault at the pointer switch rolls the candidate back: the previous release stays active.
        self.config["fault_at"] = "pointer"
        faulted = self._update(returncode=3)
        self.assertEqual(faulted["outcome"], "ROLLED_BACK", faulted.get("reasons"))
        self.assertEqual(self._active(), rid1)
        self.config["fault_at"] = None

        second = self._update()
        self.assertEqual(second["outcome"], "ACTIVE", second.get("reasons"))
        self.assertNotEqual(second["new_release"], rid1)
        self.assertEqual(second["previous_release"], rid1)
        self.assertEqual(self._active(), second["new_release"])
        self.assertEqual(self._release_tree(rid1), before, "the previous release is unchanged")
        self.assertIn({"op": "fetch", "branch": "17.0", "credentials": False}, self._call_log(),
                      "the changed Community revision was fetched")
        self.assertEqual([e["outcome"] for e in self._history()["entries"]], ["ACTIVE", "ROLLED_BACK", "ACTIVE"])

    # --- D: failure recovery -----------------------------------------------------------------------------------------------

    def test_d1_invalid_source_keeps_the_previous_release_active(self):
        first = self._update()
        self.assertEqual(first["outcome"], "ACTIVE", first.get("reasons"))
        rid1 = first["new_release"]
        before = self._release_tree(rid1)

        self.config["heads"][COM_REPO]["17.0"] = "a" * 40  # a branch that names a commit the repository does not have
        bad = self._json(self._run("knowledge", "update", "--json", local=True), returncode=None)
        self.assertNotIn(bad["outcome"], ("ACTIVE", "NOOP"), bad)
        self.assertEqual(self._active(), rid1)
        self.assertEqual(self._release_tree(rid1), before)

        self.config["heads"][COM_REPO]["17.0"] = self.community["to_sha"]  # the source is valid again
        self.config["heads"].pop(COM_REPO)  # ...then the Community remote becomes unreachable
        unreachable = self._json(self._run("knowledge", "update", "--json", local=True), returncode=None)
        self.assertNotIn(unreachable["outcome"], ("ACTIVE",), unreachable)
        self.assertEqual(self._active(), rid1)
        self.assertEqual(self._release_tree(rid1), before)
        self._assert_no_network_attempt()

    def test_d2_wrong_credentials_auth_failed_keeps_the_previous_release_active(self):
        first = self._json(self._run("knowledge", "update", "--json", local=True, token=TOKEN))
        self.assertEqual(first["outcome"], "ACTIVE", first.get("reasons"))
        rid1 = first["new_release"]
        before = self._release_tree(rid1)

        self.config["reject_enterprise"] = True
        rejected = self._json(self._run("knowledge", "update", "--json", local=True, token=TOKEN))
        self.assertEqual(rejected["enterprise"]["status"], "AUTH_FAILED")
        self.assertEqual(self._active(), rid1, rejected)
        self.assertEqual(self._release_tree(rid1), before)
        self._assert_no_token(None)

        # With a Community change, the update is still published; the rejected Enterprise sources are carried and reported.
        self._repin()
        carried = self._json(self._run("knowledge", "update", "--json", local=True, token=TOKEN))
        self.assertEqual(carried["outcome"], "ACTIVE", carried.get("reasons"))
        self.assertEqual(carried["enterprise"]["status"], "AUTH_FAILED")
        self.assertEqual(carried["enterprise"]["freshness"], "STALE_UNVERIFIED")
        self.assertEqual(self._release_tree(rid1), before)
        self._assert_no_token(None)

    def test_d3_corrupted_active_release_is_not_used_or_repaired(self):
        first = self._update()
        self.assertEqual(first["outcome"], "ACTIVE", first.get("reasons"))
        rid1 = first["new_release"]
        victim = sorted((self.kb / "releases" / rid1 / "knowledge" / "compatibility").glob("*.rules.json"))[0]
        corrupted = victim.read_bytes() + b" "
        victim.write_bytes(corrupted)

        status = self._run("knowledge", "status", "--json")
        self.assertNotEqual(status.returncode, 0, "a corrupted active release reads as healthy: " + status.stdout)

        self._repin()
        result = self._json(self._run("knowledge", "update", "--json", local=True), returncode=None)
        self.assertNotIn(result["outcome"], ("ACTIVE", "NOOP"), result)
        # `status` refuses the corrupted release, so the pointer is read from its file.
        pointer = _read_json(self.kb / "active.json")["release_id"]
        self.assertEqual(pointer, rid1)
        self.assertEqual(victim.read_bytes(), corrupted, "the corrupted file was rewritten by the update")

    def test_d4_interrupted_acquisition_keeps_the_previous_release_and_a_retry_recovers(self):
        first = self._update()
        self.assertEqual(first["outcome"], "ACTIVE", first.get("reasons"))
        rid1 = first["new_release"]
        before = self._release_tree(rid1)
        self._repin()

        self.config["kill_on_fetch"] = "17.0"
        killed = self._run("knowledge", "update", "--json", local=True)
        self.assertEqual(killed.returncode, 137, killed.stdout + killed.stderr)
        self.assertEqual(self._active(), rid1)
        self.assertEqual(self._release_tree(rid1), before)
        self.assertIn("fetch-killed", [c["op"] for c in self._call_log()])

        self.config["kill_on_fetch"] = None
        retry = self._update()
        self.assertEqual(retry["outcome"], "ACTIVE", retry.get("reasons"))
        self.assertEqual(retry["previous_release"], rid1)
        self.assertEqual(self._active(), retry["new_release"])
        self.assertEqual([e["outcome"] for e in self._history()["entries"]], ["ACTIVE", "ACTIVE"])

    # --- E: no-op update, offline check and update, zero-network migrate --------------------------------------------------

    def test_e1_second_update_is_a_noop_with_no_new_release_and_no_fetch(self):
        first = self._update()
        self.assertEqual(first["outcome"], "ACTIVE", first.get("reasons"))
        releases = sorted(p.name for p in (self.kb / "releases").iterdir())
        fetches_before = sum(1 for c in self._call_log() if c["op"] == "fetch")

        second = self._update()
        self.assertEqual(second["outcome"], "NOOP", second.get("reasons"))
        self.assertEqual(sorted(p.name for p in (self.kb / "releases").iterdir()), releases)
        self.assertEqual(self._active(), first["new_release"])
        self.assertEqual(sum(1 for c in self._call_log() if c["op"] == "fetch"), fetches_before)
        self.assertEqual([e["outcome"] for e in self._history()["entries"]], ["NOOP", "ACTIVE"])  # newest first

    def test_e2_offline_check_and_update_make_no_network_call_and_change_nothing(self):
        first = self._update()
        self.assertEqual(first["outcome"], "ACTIVE", first.get("reasons"))
        rid1 = first["new_release"]
        self._repin()
        before = _tree(self.kb)

        check = self._run("knowledge", "check", "--offline", "--json")
        self.assertEqual(check.returncode, 4, check.stdout + check.stderr)
        self.assertIn("CHECK_UNAVAILABLE", json.loads(check.stdout)["statuses"])
        env_check = self._run("knowledge", "check", "--json", extra={"ODOOFLUX_OFFLINE": "1"})
        self.assertEqual(env_check.returncode, 4, env_check.stdout + env_check.stderr)
        self.assertEqual(_tree(self.kb), before, "an offline check wrote to the kb-home")

        update = self._run("knowledge", "update", "--offline", "--json")
        payload = json.loads(update.stdout)
        self.assertNotIn(payload["outcome"], ("ACTIVE",), payload)
        self.assertEqual(self._active(), rid1)
        self.assertEqual(sorted(p.name for p in (self.kb / "releases").iterdir()), [rid1])
        self._assert_no_network_attempt()

    def test_e3_migrate_makes_no_network_call_even_with_a_token_in_the_environment(self):
        first = self._update()
        self.assertEqual(first["outcome"], "ACTIVE", first.get("reasons"))
        proc = self._run("migrate", "--module", str(self.module), "--kb-home", str(self.kb),
                         "--state-dir", str(self.dir / "migrate-e3"), "--from-version", "16", "--to-version", "17",
                         "--fix", extra={"ODOOFLUX_ENTERPRISE_TOKEN": TOKEN})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((self.module / "models" / "sale.py").read_text(encoding="utf-8"), SALE_AFTER)
        self._assert_no_network_attempt()
        self.assertNotIn(TOKEN, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()

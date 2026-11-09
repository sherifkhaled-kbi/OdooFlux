"""Feature 012 Wave 3d (FC A-10): the update catalog, the new schemas and the knowledge update verbs work from an installed wheel.

Opt-in (slow: builds a wheel and a venv): ``ODOOFLUX_PACKAGING_INSTALL=1``. The wheel is built offline from a copy of the
project, installed with ``--no-index --no-deps`` into a clean venv, and every CLI call runs from a temporary directory
outside the repository with a fresh kb-home (``ODOOFLUX_KB_HOME``).

Offline proof: the CLI runs with a ``sitecustomize`` guard on ``PYTHONPATH`` that refuses every socket connect, name
lookup and git/ssh/curl subprocess, and appends each attempt to a log. The guard is first checked with a probe that must
be refused and logged; every offline command must then leave that log empty.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from . import _wheel

CATALOG_MEMBER = "odooflux/knowledge/update/catalog.json"
NEW_SCHEMAS = ("fix_certification", "inventory", "update_report", "knowledge_status")
UPDATE_VERBS = ("check", "update", "status", "history")

GUARD = '''\
"""Packaging-test network guard (loaded through PYTHONPATH). Each attempt is logged to ODOOFLUX_GUARD_LOG and refused."""
import os
import socket
import subprocess

_LOG = os.environ.get("ODOOFLUX_GUARD_LOG")
_NETWORK_BINARIES = frozenset({"git", "ssh", "scp", "sftp", "curl", "wget"})


def _refuse(what):
    if _LOG:
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write(what + "\\n")
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

_popen_init = subprocess.Popen.__init__


def _popen_init_guarded(self, args, *rest, **kwargs):
    argv = args if isinstance(args, (list, tuple)) else [args]
    name = os.path.basename(str(argv[0])) if argv else ""
    if name in _NETWORK_BINARIES:
        _refuse("subprocess " + name)
    return _popen_init(self, args, *rest, **kwargs)


subprocess.Popen.__init__ = _popen_init_guarded
'''

# Digest and file facts of a catalog, computed by a bare interpreter (-I: no cwd, no PYTHONPATH, no user site).
CATALOG_FACTS = '''\
import hashlib
import json
import sys
if len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1])
from odooflux.knowledge.update import catalog as c
cat = c.load_catalog()
with open(c.CATALOG_PATH, "rb") as handle:
    sha = hashlib.sha256(handle.read()).hexdigest()
print(json.dumps({"file": c.__file__, "digest": cat.digest, "editions": list(cat.editions()),
                  "community": list(cat.versions("community")), "enterprise": list(cat.versions("enterprise")),
                  "catalog_sha256": sha}))
'''


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


@unittest.skipUnless(os.environ.get("ODOOFLUX_PACKAGING_INSTALL") == "1",
                     "opt-in: set ODOOFLUX_PACKAGING_INSTALL=1 (builds a wheel and a venv)")
@unittest.skipIf(_wheel.tooling_gap(), _wheel.tooling_gap() or "n/a")
class WheelUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="odooflux-update-wheel-"))
        venv = cls.work / "venv"
        made = subprocess.run([sys.executable, "-m", "venv", str(venv)], capture_output=True, text=True)
        if made.returncode:
            raise unittest.SkipTest("cannot create a venv with pip (ensurepip unavailable): " + made.stderr[-300:])
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
        cls.outside = cls.work / "outside"
        cls.outside.mkdir()
        checkout = subprocess.run([sys.executable, "-I", "-c", CATALOG_FACTS, str(_wheel.REPO / "src")],
                                  cwd=cls.outside, capture_output=True, text=True, env=_clean_env())
        if checkout.returncode:
            raise RuntimeError("checkout catalog facts failed: " + checkout.stderr[-1500:])
        cls.checkout_facts = json.loads(checkout.stdout)

    def setUp(self):
        self.kb = Path(tempfile.mkdtemp(prefix="kb-home-", dir=self.work))
        self.log = self.work / "guard.log"
        self.log.unlink(missing_ok=True)

    def _env(self) -> dict:
        env = _clean_env()
        for key in ("ODOOFLUX_OFFLINE", "ODOOFLUX_ENTERPRISE_TOKEN", "ODOOFLUX_ENTERPRISE_TOKEN_FILE"):
            env.pop(key, None)
        env.update(ODOOFLUX_KB_HOME=str(self.kb), PYTHONPATH=str(self.guard_dir), ODOOFLUX_GUARD_LOG=str(self.log))
        return env

    def _run(self, *args):
        return subprocess.run([str(self.exe), *map(str, args)], cwd=self.outside, capture_output=True, text=True,
                              env=self._env(), timeout=300)

    def _assert_no_network_attempt(self):
        attempts = self.log.read_text(encoding="utf-8") if self.log.exists() else ""
        self.assertEqual(attempts, "", "a network call was attempted: " + attempts)

    def _assert_kb_empty(self):
        self.assertEqual(sorted(p.name for p in self.kb.iterdir()), [], "the kb-home was written to")

    # (a) the wheel ships the catalog and the new schemas, byte-identical to the checkout
    def test_wheel_ships_catalog_and_new_schemas(self):
        names = _wheel.wheel_names(self.wheel)
        expected = [CATALOG_MEMBER] + [f"odooflux/knowledge/schemas/{s}.schema.json" for s in NEW_SCHEMAS]
        self.assertEqual([n for n in expected if n not in names], [])
        with zipfile.ZipFile(self.wheel) as zf:
            for member in expected:
                source = _wheel.REPO / "src" / member
                self.assertEqual(hashlib.sha256(zf.read(member)).hexdigest(),
                                 hashlib.sha256(source.read_bytes()).hexdigest(), member)

    # (b) the update verbs and their help
    def test_update_verbs_help_exit_zero(self):
        for verb in UPDATE_VERBS:
            with self.subTest(verb=verb):
                proc = self._run("knowledge", verb, "--help")
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn("usage", proc.stdout.lower())

    # (c) offline behaviour with a fresh kb-home
    def test_guard_is_active_in_the_installed_environment(self):
        probe = subprocess.run([str(self.py), "-c", "import socket; socket.create_connection(('127.0.0.1', 9))"],
                               cwd=self.outside, capture_output=True, text=True, env=self._env())
        self.assertNotEqual(probe.returncode, 0, "the network guard did not refuse a connect")
        self.assertIn("network disabled", probe.stderr)
        self.assertTrue(self.log.exists(), "the refused connect was not logged")

    def test_status_reports_builtin_knowledge(self):
        proc = self._run("knowledge", "status", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema"], "odooflux.knowledge-status/1")
        self.assertEqual(payload["kind"], "built-in")
        self.assertIsNone(payload["release_id"])
        self.assertGreater(payload["rules"]["total"], 0)
        self._assert_no_network_attempt()
        self._assert_kb_empty()

    def test_history_is_an_empty_verified_chain(self):
        proc = self._run("knowledge", "history", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["chain"], "verified")
        self.assertEqual(payload["entries"], [])
        self._assert_no_network_attempt()
        self._assert_kb_empty()

    def test_check_offline_is_check_unavailable(self):
        proc = self._run("knowledge", "check", "--offline", "--json")
        self.assertEqual(proc.returncode, 4, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("CHECK_UNAVAILABLE", payload["statuses"])
        self.assertTrue(payload["offline"])
        self.assertEqual(payload["catalog_digest"], self.checkout_facts["digest"])
        self._assert_no_network_attempt()
        self._assert_kb_empty()

    def test_update_offline_dry_run_is_blocked_and_writes_nothing(self):
        proc = self._run("knowledge", "update", "--offline", "--dry-run", "--json")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["outcome"], "BLOCKED")
        self.assertEqual(payload["plan"]["blocking_reason"], "CHECK_UNAVAILABLE")
        self.assertTrue(payload["dry_run"])
        self._assert_no_network_attempt()
        self._assert_kb_empty()

    # (d) the catalog loaded from the installed package
    def test_installed_catalog_matches_the_checkout(self):
        proc = subprocess.run([str(self.py), "-I", "-c", CATALOG_FACTS], cwd=self.outside, capture_output=True,
                              text=True, env=_clean_env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        installed = json.loads(proc.stdout)
        self.assertIn("site-packages", installed["file"])
        self.assertNotIn(str(_wheel.REPO), installed["file"])
        self.assertEqual(installed["digest"], self.checkout_facts["digest"])
        self.assertEqual(installed["catalog_sha256"], self.checkout_facts["catalog_sha256"])
        self.assertEqual(installed["editions"], ["community", "enterprise"])
        self.assertTrue(installed["community"])
        self.assertEqual(installed["community"], installed["enterprise"])

    # (e) the main command still works
    def test_migrate_help(self):
        proc = self._run("migrate", "--help")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()

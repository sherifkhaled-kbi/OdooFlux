"""Feature 012 / T02 and Addendum A2/A3: hardened remote git discovery and acquisition (remote_git.py).

All tests use a local bare repository as the transport (the `transport_url` test seam) or a recording runner. No test
contacts the network. Tokens are dummy values.
Run: PYTHONPATH=src python3 -m unittest discover -s tests/unit/knowledge/update -p 'test_remote_git.py' -t .
"""

import fcntl
import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.blobstore import SourceError
from odooflux.knowledge.acquisition.sources import load_allow_list, normalize_origin
from odooflux.knowledge.update import credentials as cred
from odooflux.knowledge.update import remote_git as rg
from odooflux.knowledge.update.credentials import Token

IDENTITY = "https://github.com/odoo/odoo"  # canonical identity, under the shipped allow-list
IDENTITY_INPUT = "https://github.com/odoo/odoo/"
ENTERPRISE = "https://github.com/odoo/enterprise"
ENTERPRISE_INPUT = "https://github.com/odoo/enterprise/"
TOKEN = "tok-TEST-1234567890"  # dummy value
NO_SHA = "1" * 40  # well-formed, present in no repository
ALLOWED_ENV_KEYS = {"PATH", "HOME", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_ATTR_NOSYSTEM",
                    "GIT_TERMINAL_PROMPT", "GIT_ALLOW_PROTOCOL", "GIT_NO_REPLACE_OBJECTS", "LC_ALL"}


def _git(args, cwd=None, home=None):
    """Test-side git call with a clean environment (global config disabled)."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": home or str(cwd or "/"), "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
    proc = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, env=env,
                          capture_output=True, check=True)
    return proc.stdout.decode("utf-8").strip()


def _make_commit(work: Path, message: str) -> str:
    (work / "f.txt").write_text(message, encoding="utf-8")
    _git(["add", "f.txt"], cwd=work)
    _git(["commit", "-q", "-m", message], cwd=work)
    return _git(["rev-parse", "HEAD"], cwd=work)


def _key(identity: str) -> str:
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


@contextmanager
def _env(**extra):
    """os.environ replaced by PATH plus *extra* (ODOOFLUX_* and proxy variables are absent)."""
    values = {"PATH": os.environ.get("PATH", "")}
    values.update(extra)
    with mock.patch.dict(os.environ, values, clear=True):
        yield


class _Recorder:
    """A runner seam: records (argv, env) of each call and returns a canned result."""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr
        self.calls = []
        self.stub = None

    def __call__(self, argv, *, env, cwd, timeout):
        self.calls.append((list(argv), dict(env)))
        stub = env.get("GIT_ASKPASS")
        if stub:
            self.stub = {"path": stub, "exists": os.path.exists(stub),
                         "text": Path(stub).read_text(encoding="utf-8") if os.path.exists(stub) else "",
                         "mode": stat.S_IMODE(os.stat(stub).st_mode) if os.path.exists(stub) else None,
                         "dir_mode": stat.S_IMODE(os.stat(os.path.dirname(stub)).st_mode)}
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def _no_process(*args, **kwargs):
    raise AssertionError("a subprocess must not start here")


class _Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="rg-test-")
        self.root = Path(self._tmp)
        self.work = self.root / "work"
        self.work.mkdir()
        _git(["init", "-q", "--template="], cwd=self.work)
        _git(["symbolic-ref", "HEAD", "refs/heads/16.0"], cwd=self.work)
        self.sha = _make_commit(self.work, "first")
        self.source = self.root / "source.git"
        _git(["init", "-q", "--bare", "--template=", str(self.source)])
        _git(["push", "-q", str(self.source), "16.0:refs/heads/16.0"], cwd=self.work)
        self.cache = self.root / "cache"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def base_dir(self, identity=IDENTITY) -> Path:
        """`<cache>/<id16>`: the per-identity directory that holds the final entries and the tmp-* directories."""
        return self.cache / _key(identity)

    def final_dir(self, sha=None, identity=IDENTITY) -> Path:
        return self.base_dir(identity) / (sha or self.sha)

    def tmp_entries(self, identity=IDENTITY):
        base = self.base_dir(identity)
        if not base.exists():
            return []
        return sorted(p.name for p in base.iterdir() if p.name.startswith("tmp-"))


class NetworkGateTests(_Fixture):
    def test_network_allowed_matrix(self):
        with mock.patch.dict(os.environ, {"ODOOFLUX_OFFLINE": ""}):
            self.assertTrue(rg.network_allowed(False))
            self.assertFalse(rg.network_allowed(True))
        for value in ("1", "true", "YES", "Yes", "TRUE"):
            with mock.patch.dict(os.environ, {"ODOOFLUX_OFFLINE": value}):
                self.assertFalse(rg.network_allowed(False), value)
        for value in ("0", "false", "no", ""):
            with mock.patch.dict(os.environ, {"ODOOFLUX_OFFLINE": value}):
                self.assertTrue(rg.network_allowed(False), value)

    def test_offline_never_starts_a_subprocess(self):
        def forbidden(*args, **kwargs):
            self.fail(f"subprocess invoked while offline: {args[0] if args else kwargs}")

        for env_value, offline in (("", True), ("1", False), ("TRUE", False), ("yes", False)):
            with self.subTest(env=env_value, offline=offline), \
                    mock.patch.dict(os.environ, {"ODOOFLUX_OFFLINE": env_value}), \
                    mock.patch.object(rg.subprocess, "run", side_effect=forbidden), \
                    mock.patch.object(rg.subprocess, "Popen", side_effect=forbidden):
                with self.assertRaises(rg.NetworkDisabled):
                    rg.ls_remote_heads(IDENTITY_INPUT, offline=offline, transport_url=str(self.source))
                with self.assertRaises(rg.NetworkDisabled):
                    rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, offline=offline,
                                    transport_url=str(self.source))
        self.assertFalse(self.cache.exists())

    def test_offline_never_reads_token_or_ca_bundle(self):
        """The gate runs first: no token file/env and no CA setting is read while offline."""
        missing = str(self.root / "no-such-token-file")
        with _env(ODOOFLUX_ENTERPRISE_TOKEN_FILE=missing, ODOOFLUX_CA_BUNDLE="relative/ca.pem"), \
                mock.patch.object(cred, "resolve_enterprise_token", side_effect=AssertionError("token read")), \
                mock.patch.object(cred, "resolve_ca_bundle", side_effect=AssertionError("CA read")), \
                mock.patch.object(rg.subprocess, "Popen", side_effect=_no_process):
            with self.assertRaises(rg.NetworkDisabled):
                rg.ls_remote_heads(ENTERPRISE_INPUT, offline=True, transport_url=str(self.source))
            with self.assertRaises(rg.NetworkDisabled):
                rg.fetch_commit(ENTERPRISE_INPUT, "16.0", self.sha, self.cache, offline=True,
                                transport_url=str(self.source), credentials=Token(TOKEN))
            with self.assertRaises(rg.NetworkDisabled):
                rg.fetch_commit(ENTERPRISE_INPUT, "16.0", self.sha, self.cache, offline=True)


class ValidateRemoteTests(_Fixture):
    def test_canonical_identity_is_returned(self):
        self.assertEqual(rg.validate_remote(IDENTITY_INPUT), IDENTITY)
        self.assertEqual(rg.validate_remote("https://GitHub.com/odoo/odoo.git/"), IDENTITY)
        self.assertEqual(rg.validate_remote(ENTERPRISE_INPUT), ENTERPRISE)

    def test_rejections(self):
        cases = [
            ("http://github.com/odoo/odoo/", "NOT_ALLOWLISTED"),
            ("git@github.com:odoo/odoo.git", "NOT_ALLOWLISTED"),
            ("https://user:secret@github.com/odoo/odoo/", "AUTH_REQUIRED"),
            ("https://ghp_abcdefghijklmnopqrstuvwxyz0123456789@github.com/odoo/odoo/", "AUTH_REQUIRED"),
            ("https://evil.example/odoo/odoo/", "NOT_ALLOWLISTED"),
            ("https://github.com/odoo/odoo.evil/", "NOT_ALLOWLISTED"),
            ("-https://github.com/odoo/odoo/", "IO_ERROR"),
            ("https://github.com/odoo/odoo/ x", "IO_ERROR"),
            ("https://github.com/odoo/odoo/\n", "IO_ERROR"),
            ("https://github.com/odoo/odoo/\t", "IO_ERROR"),
            ("https://github.com/odoo/odoo/../../evil", "IO_ERROR"),
            ("https://github.com/odoo/odoo/%2e%2e/evil", "IO_ERROR"),
            ("https://github.com/odoo/odoo/?x=1", "IO_ERROR"),
            ("", "IO_ERROR"),
        ]
        for url, code in cases:
            with self.subTest(url=url):
                with self.assertRaises(SourceError) as ctx:
                    rg.validate_remote(url)
                self.assertEqual(ctx.exception.code, code)
                self.assertNotIn("secret", ctx.exception.message)

    def test_explicit_allow_list_is_honoured(self):
        self.assertEqual(rg.validate_remote(IDENTITY_INPUT, allow_list=["https://github.com/odoo/odoo/"]), IDENTITY)
        with self.assertRaises(SourceError) as ctx:
            rg.validate_remote(IDENTITY_INPUT, allow_list=[])
        self.assertEqual(ctx.exception.code, "NOT_ALLOWLISTED")

    def test_identity_is_checked_even_with_transport_seam(self):
        with mock.patch.object(rg.subprocess, "Popen", side_effect=AssertionError("must not run")), \
                mock.patch.object(rg.subprocess, "run", side_effect=AssertionError("must not run")):
            with self.assertRaises(SourceError) as ctx:
                rg.ls_remote_heads("https://evil.example/x/", transport_url=str(self.source))
        self.assertEqual(ctx.exception.code, "NOT_ALLOWLISTED")

    def test_transport_seam_rejects_non_local_paths(self):
        for transport in ("-x", "relative/path", "file:///tmp", "https://github.com/odoo/odoo", str(self.root / "missing")):
            with self.subTest(transport=transport):
                with self.assertRaises(SourceError) as ctx:
                    rg.ls_remote_heads(IDENTITY_INPUT, transport_url=transport)
                self.assertEqual(ctx.exception.code, "IO_ERROR")


class LsRemoteTests(_Fixture):
    def test_returns_branch_and_sha(self):
        heads = rg.ls_remote_heads(IDENTITY_INPUT, transport_url=str(self.source))
        self.assertEqual(heads, {"16.0": self.sha})

    def test_runner_sees_scrubbed_environment_and_fixed_argv(self):
        captured = {}

        def runner(argv, *, env, cwd, timeout):
            captured.update(argv=argv, env=env, cwd=cwd, timeout=timeout)
            return subprocess.CompletedProcess(argv, 0, b"")

        hostile = {"GIT_SSH_COMMAND": "evil", "GIT_ASKPASS": "evil", "SSH_ASKPASS": "evil", "GIT_DIR": "/evil",
                   "GIT_CONFIG_PARAMETERS": "'url.x.insteadOf=y'", "GIT_PROXY_COMMAND": "evil",
                   "HTTPS_PROXY": "http://proxy.example:3128", "ODOOFLUX_GIT_SECRET": TOKEN}
        with mock.patch.dict(os.environ, hostile):
            self.assertEqual(rg.ls_remote_heads(IDENTITY_INPUT, runner=runner, timeout=7), {})
        env = captured["env"]
        self.assertLessEqual(set(env), ALLOWED_ENV_KEYS | {"HTTPS_PROXY"})
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(env["GIT_ALLOW_PROTOCOL"], "https")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(captured["timeout"], 7)
        argv = captured["argv"]
        self.assertEqual(argv[0], "git")
        self.assertIn("core.hooksPath=" + os.devnull, argv)
        self.assertIn("credential.helper=", argv)
        self.assertIn("http.sslVerify=true", argv)
        self.assertEqual(argv[-5:], ["ls-remote", "--heads", "--refs", "--", IDENTITY])

    def test_oversized_output_is_rejected(self):
        def runner(argv, *, env, cwd, timeout):
            return subprocess.CompletedProcess(argv, 0, b"a" * (rg.MAX_LS_REMOTE_BYTES + 1))

        with self.assertRaises(SourceError) as ctx:
            rg.ls_remote_heads(IDENTITY_INPUT, runner=runner)
        self.assertEqual(ctx.exception.code, "IO_ERROR")

    def test_too_many_lines_is_rejected(self):
        lines = b"".join(b"%s\trefs/heads/b%d\n" % (self.sha.encode(), i) for i in range(rg.MAX_LS_REMOTE_LINES + 1))

        def runner(argv, *, env, cwd, timeout):
            return subprocess.CompletedProcess(argv, 0, lines)

        with self.assertRaises(SourceError) as ctx:
            rg.ls_remote_heads(IDENTITY_INPUT, runner=runner)
        self.assertEqual(ctx.exception.code, "IO_ERROR")

    def test_malformed_lines_are_rejected(self):
        bad = [
            b"%s\trefs/heads/16.0\n" % self.sha.upper().encode(),  # uppercase hex
            b"abc\trefs/heads/16.0\n",  # short sha
            b"%s\trefs/tags/v1\n" % self.sha.encode(),  # not a branch
            b"%s refs/heads/16.0\n" % self.sha.encode(),  # space, not tab
            b"%s\trefs/heads/-evil\n" % self.sha.encode(),  # option-like branch
            b"%s\trefs/heads/a..b\n" % self.sha.encode(),  # dot-dot branch
            b"%s\trefs/heads/16.0\n\n" % self.sha.encode(),  # blank line
            b"%s\trefs/heads/16.0\n%s\trefs/heads/16.0\n" % (self.sha.encode(), self.sha.encode()),  # duplicate
            b"\xff\xfe\n",  # not ascii
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                def runner(argv, *, env, cwd, timeout, payload=payload):
                    return subprocess.CompletedProcess(argv, 0, payload)

                with self.assertRaises(SourceError) as ctx:
                    rg.ls_remote_heads(IDENTITY_INPUT, runner=runner)
                self.assertEqual(ctx.exception.code, "IO_ERROR")

    def test_nonzero_exit_is_io_error_and_timeout_is_unavailable(self):
        def failing(argv, *, env, cwd, timeout):
            return subprocess.CompletedProcess(argv, 128, b"")

        def timing_out(argv, *, env, cwd, timeout):
            raise subprocess.TimeoutExpired(argv, timeout)

        with self.assertRaises(SourceError) as ctx:
            rg.ls_remote_heads(IDENTITY_INPUT, runner=failing)
        self.assertEqual(ctx.exception.code, "IO_ERROR")
        with self.assertRaises(SourceError) as ctx:
            rg.ls_remote_heads(IDENTITY_INPUT, runner=timing_out)
        self.assertEqual(ctx.exception.code, "UNAVAILABLE")

    def test_empty_advertisement_is_empty_mapping(self):
        def runner(argv, *, env, cwd, timeout):
            return subprocess.CompletedProcess(argv, 0, b"")

        self.assertEqual(rg.ls_remote_heads(IDENTITY_INPUT, runner=runner), {})


class FetchCommitTests(_Fixture):
    def test_fetch_by_sha_produces_verifiable_cache(self):
        repo = rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        self.assertEqual(repo, self.final_dir())
        self.assertEqual(_git(["-C", str(repo), "rev-parse", "--verify", f"{self.sha}^{{commit}}"]), self.sha)
        self.assertEqual(_git(["-C", str(repo), "remote", "get-url", "origin"]), IDENTITY)
        self.assertFalse((repo / "f.txt").exists(), "no working tree may be checked out")
        hooks = repo / ".git" / "hooks"
        self.assertFalse(hooks.exists() and any(hooks.iterdir()), "the managed repository must have no hooks")
        self.assertEqual(self.tmp_entries(), [], "no temporary directory may remain after a successful fetch")

    def test_shipped_identity_check_is_satisfiable(self):
        repo = rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        adapter = GitLocalAdapter(kind="GIT_COMMUNITY", allow_list=load_allow_list())
        spec = {"source_id": "t", "expected_origin": IDENTITY, "kind": "GIT_COMMUNITY", "url": f"local:{repo}",
                "revision": self.sha, "official": True}
        self.assertEqual(adapter._verified_origin(str(repo), spec), normalize_origin(IDENTITY))
        self.assertEqual(adapter._check(spec)[0]["reason_code"], "OK")

    def test_wrong_sha_fails_closed_and_leaves_no_entry(self):
        with self.assertRaises(SourceError) as ctx:
            rg.fetch_commit(IDENTITY_INPUT, "16.0", NO_SHA, self.cache, transport_url=str(self.source))
        self.assertEqual(ctx.exception.code, "REVISION_UNAVAILABLE")
        self.assertFalse(self.final_dir(NO_SHA).exists())
        self.assertEqual(self.tmp_entries(), [], "a failing fetch removes its own temporary directory")

    def test_failure_after_good_fetch_keeps_shared_entry(self):
        good = rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        with self.assertRaises(SourceError):
            rg.fetch_commit(IDENTITY_INPUT, "16.0", NO_SHA, self.cache, transport_url=str(self.source))
        self.assertTrue(good.is_dir(), "a failing fetch must never delete the shared final directory")
        self.assertEqual(_git(["-C", str(good), "rev-parse", "--verify", f"{self.sha}^{{commit}}"]), self.sha)
        self.assertEqual(self.tmp_entries(), [])

    def test_valid_final_entry_is_reused_without_fetching(self):
        first = rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        real = rg._run_bounded

        def no_fetch(argv, **kwargs):
            if "fetch" in argv:
                raise AssertionError("a verified final entry must be reused, not fetched again")
            return real(argv, **kwargs)

        with mock.patch.object(rg, "_run_bounded", side_effect=no_fetch):
            again = rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        self.assertEqual(again, first)

    def test_corrupt_final_entry_is_replaced(self):
        final = self.final_dir()
        final.mkdir(parents=True)
        (final / "garbage").write_text("not a repository", encoding="utf-8")
        repo = rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        self.assertEqual(repo, final)
        self.assertEqual(_git(["-C", str(repo), "rev-parse", "--verify", f"{self.sha}^{{commit}}"]), self.sha)
        self.assertFalse((final / "garbage").exists())

    def test_malformed_arguments_are_refused_before_git(self):
        with mock.patch.object(rg.subprocess, "Popen", side_effect=AssertionError("must not run")):
            for branch, sha, code in (("16.x", self.sha, "IO_ERROR"), ("../16.0", self.sha, "IO_ERROR"),
                                      ("16.0", self.sha.upper(), "REVISION_UNAVAILABLE"),
                                      ("16.0", "main", "REVISION_UNAVAILABLE"),
                                      ("16.0", "-" + self.sha[1:], "REVISION_UNAVAILABLE")):
                with self.subTest(branch=branch, sha=sha):
                    with self.assertRaises(SourceError) as ctx:
                        rg.fetch_commit(IDENTITY_INPUT, branch, sha, self.cache, transport_url=str(self.source))
                    self.assertEqual(ctx.exception.code, code)

    def test_size_bound_stops_fetch_and_leaves_no_entry(self):
        with self.assertRaises(SourceError) as ctx:
            rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source), max_bytes=1)
        self.assertEqual(ctx.exception.code, "IO_ERROR")
        self.assertIn("bound", ctx.exception.message)
        self.assertFalse(self.final_dir().exists())
        self.assertEqual(self.tmp_entries(), [])

    def test_timeout_is_unavailable_and_leaves_no_entry(self):
        def timing_out(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

        with mock.patch.object(rg, "_run_bounded", side_effect=timing_out):
            with self.assertRaises(SourceError) as ctx:
                rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        self.assertEqual(ctx.exception.code, "UNAVAILABLE")
        self.assertFalse(self.final_dir().exists())
        self.assertEqual(self.tmp_entries(), [])

    def test_fetch_uses_low_speed_limits(self):
        seen = []
        real = rg._run_bounded

        def spy(argv, **kwargs):
            seen.append(list(argv))
            return real(argv, **kwargs)

        with mock.patch.object(rg, "_run_bounded", side_effect=spy):
            rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        fetch = [argv for argv in seen if "fetch" in argv]
        self.assertEqual(len(fetch), 1)
        self.assertIn("http.lowSpeedLimit=1000", fetch[0])
        self.assertIn("http.lowSpeedTime=60", fetch[0])


class CacheConcurrencyTests(_Fixture):
    """Lock, temporary directories, stale cleanup, and the in-flight size guard (Addendum A3)."""

    @staticmethod
    def _in_thread(fn):
        out = {}

        def run():
            try:
                out["value"] = fn()
            except BaseException as exc:  # recorded and asserted by the test
                out["error"] = exc

        thread = threading.Thread(target=run)
        thread.start()
        return thread, out

    def test_concurrent_fetch_of_same_sha_both_succeed(self):
        first, out_a = self._in_thread(lambda: rg.fetch_commit(
            IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source)))
        second, out_b = self._in_thread(lambda: rg.fetch_commit(
            IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source)))
        first.join(60)
        second.join(60)
        self.assertNotIn("error", out_a)
        self.assertNotIn("error", out_b)
        self.assertEqual(out_a["value"], self.final_dir())
        self.assertEqual(out_b["value"], self.final_dir())
        self.assertEqual(_git(["-C", str(self.final_dir()), "rev-parse", "--verify", f"{self.sha}^{{commit}}"]),
                         self.sha)
        self.assertEqual(self.tmp_entries(), [])

    def test_failing_concurrent_fetch_does_not_delete_successful_entry(self):
        good, out_good = self._in_thread(lambda: rg.fetch_commit(
            IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source)))
        bad, out_bad = self._in_thread(lambda: rg.fetch_commit(
            IDENTITY_INPUT, "16.0", NO_SHA, self.cache, transport_url=str(self.source)))
        good.join(60)
        bad.join(60)
        self.assertNotIn("error", out_good)
        self.assertIsInstance(out_bad.get("error"), SourceError)
        self.assertEqual(out_bad["error"].code, "REVISION_UNAVAILABLE")
        self.assertEqual(_git(["-C", str(self.final_dir()), "rev-parse", "--verify", f"{self.sha}^{{commit}}"]),
                         self.sha)
        self.assertEqual(self.tmp_entries(), [])

    def test_interrupted_fetch_leaves_no_tmp_and_no_final(self):
        with self.assertRaises(SourceError):
            rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source),
                            max_bytes=1, poll_interval=0.01)
        self.assertEqual(self.tmp_entries(), [])
        self.assertFalse(self.final_dir().exists())

    def test_size_guard_terminates_the_git_process_group(self):
        real_kill = rg._kill_group
        with mock.patch.object(rg, "_kill_group", side_effect=real_kill) as kill:
            with self.assertRaises(SourceError) as ctx:
                rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source),
                                max_bytes=1, poll_interval=0.01)
        self.assertEqual(ctx.exception.code, "IO_ERROR")
        self.assertIn("stopped", ctx.exception.message)
        self.assertTrue(kill.called, "the watcher must signal the git process group")

    def test_lock_busy_is_io_error_without_any_process(self):
        base_root = self.cache
        base_root.mkdir(parents=True)
        fd = os.open(base_root / f"{_key(IDENTITY)}.lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with mock.patch.object(rg.subprocess, "Popen", side_effect=_no_process):
                with self.assertRaises(SourceError) as ctx:
                    rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source),
                                    lock_wait=0.2)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        self.assertEqual(ctx.exception.code, "IO_ERROR")
        self.assertIn("cache busy", ctx.exception.message)

    def test_stale_tmp_directories_are_removed_under_the_lock(self):
        base = self.base_dir()
        base.mkdir(parents=True)
        stale = base / "tmp-stale"
        stale.mkdir()
        now = time.time()
        os.utime(stale, (now, now))
        fresh = base / "tmp-fresh"
        fresh.mkdir()
        # the injected clock sits two hours ahead: `tmp-stale` (mtime = now) is older than the bound, `tmp-fresh` too
        rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source),
                        clock=lambda: now + 7200)
        self.assertFalse(stale.exists())
        self.assertFalse(fresh.exists())
        self.assertEqual(self.tmp_entries(), [])

    def test_recent_tmp_directories_are_kept(self):
        base = self.base_dir()
        base.mkdir(parents=True)
        recent = base / "tmp-recent"
        recent.mkdir()
        rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source),
                        clock=time.time)
        self.assertTrue(recent.is_dir(), "a directory younger than the bound belongs to a live writer and stays")

    def test_symlinked_final_entry_is_not_followed(self):
        base = self.base_dir()
        base.mkdir(parents=True)
        target = self.root / "elsewhere"
        target.mkdir()
        os.symlink(target, self.final_dir())
        repo = rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        self.assertFalse(repo.is_symlink())
        self.assertTrue((repo / ".git").is_dir())
        self.assertTrue(target.is_dir(), "the symlink target outside the cache must not be touched")


class HostileInputTests(_Fixture):
    def test_hooks_in_source_never_run(self):
        marker = self.root / "hook-ran"
        hooks = self.source / "hooks"
        hooks.mkdir(exist_ok=True)
        names = ("reference-transaction", "post-update", "pre-fetch", "post-fetch", "post-checkout")
        for name in names:
            path = hooks / name
            path.write_text(f"#!/bin/sh\necho ran >> '{marker}'\n", encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # control: a real hook fires on a ref update in the source repository, so the hook is live
        _git(["-C", str(self.source), "update-ref", "refs/heads/control", self.sha])
        self.assertTrue(marker.exists(), "control hook did not fire; the test would prove nothing")
        _git(["-C", str(self.source), "update-ref", "-d", "refs/heads/control"])
        marker.unlink()

        self.assertEqual(rg.ls_remote_heads(IDENTITY_INPUT, transport_url=str(self.source)), {"16.0": self.sha})
        rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        self.assertFalse(marker.exists(), "a hook in the source repository ran during acquisition")

    def test_malicious_global_config_is_ignored(self):
        evil_work = self.root / "evil-work"
        evil_work.mkdir()
        _git(["init", "-q", "--template="], cwd=evil_work)
        _git(["symbolic-ref", "HEAD", "refs/heads/16.0"], cwd=evil_work)
        evil_sha = _make_commit(evil_work, "evil")
        evil_source = self.root / "evil.git"
        _git(["init", "-q", "--bare", "--template=", str(evil_source)])
        _git(["push", "-q", str(evil_source), "16.0:refs/heads/16.0"], cwd=evil_work)
        self.assertNotEqual(evil_sha, self.sha)

        evil_home = self.root / "evil-home"
        evil_home.mkdir()
        rewrite = f'[url "{evil_source}"]\n\tinsteadOf = {self.source}\n'
        global_cfg = self.root / "evil.gitconfig"
        global_cfg.write_text(rewrite, encoding="utf-8")
        (evil_home / ".gitconfig").write_text(rewrite, encoding="utf-8")
        (evil_home / ".config" / "git").mkdir(parents=True)
        (evil_home / ".config" / "git" / "config").write_text(rewrite, encoding="utf-8")

        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(global_cfg), "HOME": str(evil_home),
                                          "XDG_CONFIG_HOME": str(evil_home / ".config")}):
            heads = rg.ls_remote_heads(IDENTITY_INPUT, transport_url=str(self.source))
            repo = rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        self.assertEqual(heads, {"16.0": self.sha})
        self.assertEqual(_git(["-C", str(repo), "rev-parse", "--verify", f"{self.sha}^{{commit}}"]), self.sha)

    def test_fetched_repo_contains_no_evil_commit(self):
        repo = rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        objects = _git(["-C", str(repo), "cat-file", "--batch-all-objects", "--batch-check=%(objectname)"])
        self.assertIn(self.sha, objects.split())


class ScrubbedEnvTests(unittest.TestCase):
    def test_env_is_built_from_scratch(self):
        with mock.patch.dict(os.environ, {"GIT_SSH_COMMAND": "evil", "SSH_AUTH_SOCK": "/s", "NO_PROXY": "x"}):
            env = rg._git_env("https")
        self.assertNotIn("GIT_SSH_COMMAND", env)
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertEqual(env["NO_PROXY"], "x")
        self.assertEqual(env["GIT_NO_REPLACE_OBJECTS"], "1")


class EnterpriseCredentialTests(_Fixture):
    """Credential scoping (Addendum A2): attached only for the Enterprise identity, never in argv, URL or disk."""

    def test_community_call_never_receives_the_token(self):
        rec = _Recorder(stdout=b"")
        with _env(ODOOFLUX_GIT_SECRET=TOKEN, ODOOFLUX_ENTERPRISE_TOKEN=TOKEN):
            rg.ls_remote_heads(IDENTITY_INPUT, runner=rec, credentials=Token(TOKEN))
        self.assertEqual(len(rec.calls), 1)
        argv, env = rec.calls[0]
        self.assertEqual(set(env), ALLOWED_ENV_KEYS, "the community child environment must be exactly the scrubbed set")
        self.assertNotIn("GIT_ASKPASS", env)
        self.assertNotIn(cred.ENV_SECRET, env)
        self.assertNotIn(TOKEN, " ".join(argv))
        self.assertNotIn(TOKEN, " ".join(f"{k}={v}" for k, v in env.items()))
        self.assertNotIn("http.followRedirects=false", argv)
        self.assertIsNone(rec.stub)

    def test_community_fetch_child_environment_is_exact(self):
        real = rg._run_bounded
        seen = []

        def spy(argv, **kwargs):
            seen.append((list(argv), dict(kwargs["env"])))
            return real(argv, **kwargs)

        with _env(), mock.patch.object(rg, "_run_bounded", side_effect=spy):
            rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source),
                            credentials=Token(TOKEN))
        self.assertTrue(seen)
        for argv, env in seen:
            self.assertEqual(set(env), ALLOWED_ENV_KEYS)
            self.assertNotIn(TOKEN, " ".join(argv))
            self.assertNotIn(TOKEN, " ".join(env.values()))

    def test_enterprise_without_token_is_auth_required_before_any_process(self):
        with mock.patch.object(rg.subprocess, "Popen", side_effect=_no_process), \
                mock.patch.object(rg.subprocess, "run", side_effect=_no_process):
            with self.assertRaises(SourceError) as ctx:
                rg.ls_remote_heads(ENTERPRISE_INPUT, transport_url=str(self.source))
            self.assertEqual(ctx.exception.code, "AUTH_REQUIRED")
            with self.assertRaises(SourceError) as ctx:
                rg.fetch_commit(ENTERPRISE_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
            self.assertEqual(ctx.exception.code, "AUTH_REQUIRED")
        self.assertFalse(self.cache.exists(), "no cache may be touched when credentials are missing")

    def test_enterprise_with_token_gets_askpass_and_secret_env(self):
        rec = _Recorder(stdout=b"")
        rg.ls_remote_heads(ENTERPRISE_INPUT, runner=rec, credentials=Token(TOKEN))
        argv, env = rec.calls[0]
        self.assertEqual(env["ODOOFLUX_GIT_SECRET"], TOKEN)
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertIn("GIT_ASKPASS", env)
        stub = rec.stub
        self.assertTrue(stub["exists"], "the askpass stub must exist during the call")
        self.assertEqual(stub["mode"], 0o700)
        self.assertEqual(stub["dir_mode"], 0o700)
        self.assertNotIn(TOKEN, stub["text"], "the askpass stub must not contain the token")
        self.assertFalse(os.path.exists(env["GIT_ASKPASS"]), "the stub is removed after the call")
        self.assertNotIn(TOKEN, " ".join(argv))
        self.assertIn("credential.helper=", argv)
        self.assertIn("http.followRedirects=false", argv)
        self.assertEqual(argv[-1], ENTERPRISE, "the URL is the credential-free identity")

    def test_enterprise_fetch_with_token_keeps_token_out_of_argv_config_and_disk(self):
        real = rg._run_bounded
        seen = []

        def spy(argv, **kwargs):
            seen.append((list(argv), dict(kwargs["env"])))
            return real(argv, **kwargs)

        with mock.patch.object(rg, "_run_bounded", side_effect=spy):
            repo = rg.fetch_commit(ENTERPRISE_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source),
                                   credentials=Token(TOKEN))
        self.assertEqual(_git(["-C", str(repo), "rev-parse", "--verify", f"{self.sha}^{{commit}}"]), self.sha)
        carriers = [env for _, env in seen if cred.ENV_SECRET in env]
        self.assertEqual(len(carriers), 1, "only the fetch child receives the secret")
        for argv, env in seen:
            self.assertNotIn(TOKEN, " ".join(argv))
        for path in self.cache.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN.encode(), path.read_bytes(), f"token found in {path.name}")
            self.assertNotIn(TOKEN, path.name)
        self.assertEqual(_git(["-C", str(repo), "remote", "get-url", "origin"]), ENTERPRISE)

    def test_enterprise_ls_remote_with_token_on_real_transport(self):
        heads = rg.ls_remote_heads(ENTERPRISE_INPUT, transport_url=str(self.source), credentials=Token(TOKEN))
        self.assertEqual(heads, {"16.0": self.sha})

    def test_token_is_scrubbed_from_every_raised_message(self):
        samples = [
            (b"fatal: Authentication failed for 'https://github.com/odoo/enterprise/' " + TOKEN.encode(), "AUTH_FAILED"),
            (b"could not read Username for 'x': " + TOKEN.encode(), "AUTH_REQUIRED"),
            (b"fatal: unable to access: Could not resolve host " + TOKEN.encode(), "UNAVAILABLE"),
            (b"weird output mentioning " + TOKEN.encode(), "IO_ERROR"),
        ]
        for stderr, code in samples:
            with self.subTest(stderr=stderr[:30]):
                rec = _Recorder(returncode=128, stderr=stderr)
                with self.assertRaises(SourceError) as ctx:
                    rg.ls_remote_heads(ENTERPRISE_INPUT, runner=rec, credentials=Token(TOKEN))
                self.assertEqual(ctx.exception.code, code)
                for text in (str(ctx.exception), ctx.exception.message, repr(ctx.exception)):
                    self.assertNotIn(TOKEN, text)

    def test_token_is_scrubbed_from_fetch_failures(self):
        def failing(argv, **kwargs):
            if "fetch" in argv:
                return subprocess.CompletedProcess(argv, 128, b"", b"fatal: Authentication failed " + TOKEN.encode())
            return real(argv, **kwargs)

        real = rg._run_bounded
        with mock.patch.object(rg, "_run_bounded", side_effect=failing):
            with self.assertRaises(SourceError) as ctx:
                rg.fetch_commit(ENTERPRISE_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source),
                                credentials=Token(TOKEN))
        self.assertEqual(ctx.exception.code, "AUTH_FAILED")
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertNotIn(TOKEN, repr(ctx.exception))

    def test_non_token_credentials_are_refused(self):
        with self.assertRaises(TypeError):
            rg.ls_remote_heads(ENTERPRISE_INPUT, credentials=TOKEN, transport_url=str(self.source))

    def test_classification_table(self):
        cases = [
            (b"could not read Username for 'https://github.com': terminal prompts disabled", False, "AUTH_REQUIRED"),
            (b"could not read Password for 'https://x': terminal prompts disabled", False, "AUTH_REQUIRED"),
            (b"could not read Password for 'https://x': terminal prompts disabled", True, "AUTH_FAILED"),
            (b"fatal: Authentication failed for 'https://github.com/odoo/enterprise/'", True, "AUTH_FAILED"),
            (b"remote: Invalid username or password.", True, "AUTH_FAILED"),
            (b"fatal: The requested URL returned error: 401", False, "AUTH_FAILED"),
            (b"error: RPC failed; HTTP 403 curl 22", False, "AUTH_FAILED"),
            (b"remote: Repository not found.", True, "AUTH_FAILED"),
            (b"remote: Repository not found.", False, None),
            (b"fatal: unable to access: Could not resolve host: github.com", False, "UNAVAILABLE"),
            (b"fatal: unable to access: Failed to connect to github.com port 443", False, "UNAVAILABLE"),
            (b"fatal: unable to access: Connection refused", False, "UNAVAILABLE"),
            (b"fatal: unable to access: Connection timed out after 30000 milliseconds", False, "UNAVAILABLE"),
            (b"error: The requested URL returned error: 503", False, "UNAVAILABLE"),
            (b"fatal: unable to access: The requested URL returned error: 502", True, "UNAVAILABLE"),
            (b"fatal: something unrelated", False, None),
            (b"", False, None),
        ]
        for stderr, attached, expected in cases:
            with self.subTest(stderr=stderr, attached=attached):
                self.assertEqual(rg.classify_git_stderr(stderr, attached=attached), expected)

    def test_classified_outcomes_map_to_codes_through_run(self):
        for stderr, attached, code in ((b"Could not resolve host: github.com", False, "UNAVAILABLE"),
                                       (b"HTTP 401", False, "AUTH_FAILED")):
            with self.subTest(stderr=stderr):
                rec = _Recorder(returncode=128, stderr=stderr)
                with self.assertRaises(SourceError) as ctx:
                    rg.ls_remote_heads(IDENTITY_INPUT, runner=rec)
                self.assertEqual(ctx.exception.code, code)

    def test_remote_error_codes_are_source_errors(self):
        err = rg.RemoteGitError("AUTH_FAILED", None, "rejected")
        self.assertIsInstance(err, SourceError)
        self.assertEqual(err.code, "AUTH_FAILED")
        self.assertEqual(str(err), "AUTH_FAILED: rejected")
        with self.assertRaises(ValueError):
            rg.RemoteGitError("NOT_A_CODE", None, "x")


class CaBundleTests(_Fixture):
    def setUp(self):
        super().setUp()
        self.ca = self.root / "corp-ca.pem"
        self.ca.write_text("-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n", encoding="utf-8")

    def test_ca_bundle_maps_to_git_ssl_cainfo_for_that_call_only(self):
        rec = _Recorder(stdout=b"")
        with _env(ODOOFLUX_CA_BUNDLE=str(self.ca)):
            rg.ls_remote_heads(IDENTITY_INPUT, runner=rec)
        argv, env = rec.calls[0]
        self.assertEqual(env["GIT_SSL_CAINFO"], str(self.ca))
        self.assertNotIn("http.sslverify=false", " ".join(argv).lower())
        self.assertIn("http.sslVerify=true", argv)
        rec2 = _Recorder(stdout=b"")
        with _env():
            rg.ls_remote_heads(IDENTITY_INPUT, runner=rec2)
        self.assertNotIn("GIT_SSL_CAINFO", rec2.calls[0][1], "the mapping must not persist between calls")

    def test_invalid_ca_bundle_is_io_error_before_any_process(self):
        directory = self.root / "a-directory"
        directory.mkdir()
        for value in ("relative/ca.pem", str(self.root / "missing.pem"), str(directory), " " + str(self.ca)):
            with self.subTest(value=value):
                rec = _Recorder(stdout=b"")
                with _env(ODOOFLUX_CA_BUNDLE=value):
                    with self.assertRaises(SourceError) as ctx:
                        rg.ls_remote_heads(IDENTITY_INPUT, runner=rec)
                self.assertEqual(ctx.exception.code, "IO_ERROR")
                self.assertEqual(rec.calls, [])

    def test_ca_bundle_applies_to_fetch(self):
        real = rg._run_bounded
        seen = []

        def spy(argv, **kwargs):
            seen.append((list(argv), dict(kwargs["env"])))
            return real(argv, **kwargs)

        with _env(ODOOFLUX_CA_BUNDLE=str(self.ca)), mock.patch.object(rg, "_run_bounded", side_effect=spy):
            rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        fetch = [env for argv, env in seen if "fetch" in argv]
        self.assertEqual(len(fetch), 1)
        self.assertEqual(fetch[0].get("GIT_SSL_CAINFO"), str(self.ca))
        others = [env for argv, env in seen if "fetch" not in argv]
        self.assertTrue(others and all("GIT_SSL_CAINFO" not in env for env in others),
                        "local git calls (init, rev-parse, remote) never need the CA mapping")


if __name__ == "__main__":
    unittest.main()

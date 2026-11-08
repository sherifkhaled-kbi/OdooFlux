"""TST-011-035 (REQ-SEC-001, REQ-KAP-007): the git-local adapter is allow-listed for `subprocess` in the customer-code
guard only because it runs read-only git plumbing against a local clone with a hardened call. This pins that contract."""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.acquisition import sources as s
from odooflux.knowledge.acquisition.adapters import git_local
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError

SOURCE = Path(git_local.__file__).read_text(encoding="utf-8")
READ_ONLY_PLUMBING = {"cat-file", "rev-parse", "remote", "ls-tree"}
ALLOW = s.load_allow_list()
ORIGIN = "https://github.com/odoo/odoo"
# the complete environment the adapter may pass to git; PATH is the only value taken from the caller's environment
ALLOWED_ENV = {"PATH", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_ATTR_NOSYSTEM", "GIT_CEILING_DIRECTORIES",
               "GIT_TERMINAL_PROMPT", "LC_ALL"}
GIT_ARGV_PREFIX = ["git", "-c", "core.fsmonitor=false"]


def _committed_repo(root: Path):
    """A one-commit clone whose origin is the official GitHub URL (no network is ever used). Returns (path, sha)."""
    repo = root / "clone"
    repo.mkdir()
    env = {"PATH": os.environ.get("PATH", ""), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "LC_ALL": "C", "GIT_AUTHOR_NAME": "kap", "GIT_AUTHOR_EMAIL": "kap@example.invalid",
           "GIT_COMMITTER_NAME": "kap", "GIT_COMMITTER_EMAIL": "kap@example.invalid"}

    def run(*args):
        return subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True, text=True, check=True,
                              timeout=120).stdout

    run("init", "-q")
    (repo / "addons").mkdir()
    (repo / "addons" / "sale_demo.py").write_text("x = 1\n", encoding="utf-8")
    run("add", "-A")
    run("-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
    run("remote", "add", "origin", ORIGIN)
    return repo, run("rev-parse", "HEAD").strip()


def _spec(url: str, revision: str, *, official: bool = False) -> dict:
    spec = {
        "source_id": "odoo-community-17.0", "kind": "GIT_COMMUNITY", "official": official, "url": url,
        "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3.0", "branch": "17.0", "revision": revision,
        "scope": {"modules": "*", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }
    if official:
        spec["expected_origin"] = ORIGIN
    return spec


class GitLocalReadOnlyTests(unittest.TestCase):
    def test_only_read_only_plumbing_commands_are_used(self):
        used = set(re.findall(r'self\._git\(\s*[a-z_]+,\s*\["([a-z-]+)"', SOURCE))
        self.assertTrue(used, "no git subcommand found: the pattern needs updating")
        self.assertLessEqual(used, READ_ONLY_PLUMBING, f"unexpected git subcommands: {sorted(used - READ_ONLY_PLUMBING)}")

    def test_remote_use_is_get_url_only(self):
        for match in re.finditer(r'\["remote",\s*([^\]]*)\]', SOURCE):
            self.assertTrue(match.group(1).strip().startswith('"get-url"'), match.group(0))

    def test_call_is_hardened(self):
        for needle in ('shell=False', '"GIT_CONFIG_NOSYSTEM": "1"', '"GIT_CONFIG_GLOBAL": os.devnull',
                       '"GIT_TERMINAL_PROMPT": "0"', 'core.fsmonitor=false'):
            self.assertIn(needle, SOURCE)
        self.assertNotIn("os.environ.copy()", SOURCE)  # the environment is built from scratch, not inherited
        self.assertEqual(1, SOURCE.count("subprocess.run("))

    def test_subprocess_surface_is_one_hardened_call(self):
        self.assertEqual(set(re.findall(r"\bsubprocess\.(\w+)", SOURCE)), {"run", "TimeoutExpired"})
        self.assertEqual(SOURCE.count("import subprocess"), 1)
        self.assertNotRegex(SOURCE, r"shell\s*=\s*True")
        for banned in ("Popen", "check_output", "check_call", "os.system", "os.popen", "os.exec", "os.spawn"):
            self.assertNotIn(banned, SOURCE)
        self.assertEqual(SOURCE.count("os.environ"), 1)
        self.assertIn('"PATH": os.environ.get("PATH", "")', SOURCE)

    def test_every_call_has_the_fixed_argv_shape_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha = _committed_repo(Path(tmp))
            calls, real_run = [], subprocess.run

            def spy(argv, **kwargs):
                calls.append((list(argv), kwargs))
                return real_run(argv, **kwargs)

            adapter = GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW)
            store = BlobStore(Path(tmp) / "store")
            with mock.patch.object(subprocess, "run", side_effect=spy), \
                    mock.patch.dict(os.environ, {"ODOOFLUX_SENTINEL": "leak", "GIT_DIR": "/nowhere"}):
                adapter.probe(_spec("local:" + str(repo), sha))
                adapter.snapshot(_spec("local:" + str(repo), sha), store, created_at="2026-01-01T00:00:00Z")
                official = _spec("local:" + str(repo), sha, official=True)
                adapter.probe(official)
                adapter.snapshot(official, store, created_at="2026-01-01T00:00:00Z")
        self.assertTrue(calls)
        subcommands = set()
        for argv, kwargs in calls:
            self.assertEqual(argv[:3], GIT_ARGV_PREFIX)
            self.assertEqual(argv.count("-C"), 1)
            self.assertEqual(argv[argv.index("-C") + 1], str(repo))  # the resolved repository, only after -C
            subcommand = argv[argv.index("-C") + 2]
            subcommands.add(subcommand)
            self.assertIn(subcommand, READ_ONLY_PLUMBING)
            self.assertIs(kwargs.get("shell", False), False)
            self.assertLessEqual(set(kwargs["env"]), ALLOWED_ENV)
            self.assertNotIn("ODOOFLUX_SENTINEL", kwargs["env"])
            self.assertNotIn("GIT_DIR", kwargs["env"])
            self.assertEqual(kwargs["env"]["PATH"], os.environ.get("PATH", ""))
            self.assertEqual(kwargs["timeout"], git_local.GIT_TIMEOUT)
        self.assertEqual(subcommands, READ_ONLY_PLUMBING)

    def test_option_like_inputs_are_refused_before_any_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha = _committed_repo(Path(tmp))
            adapter = GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW)
            store = BlobStore(Path(tmp) / "store")
            bad_revisions = ["--upload-pack=x", "-h", "--output=/tmp/x", "--", sha + "\n", sha + "\0", sha.upper(),
                             sha[:39], "HEAD", "main", "v1.0", sha + " --all"]
            bad_urls = ["local:-x", "local:-" + str(repo), "local:" + str(repo) + "\n", "local:", "local:" + tmp + "/nope"]
            with mock.patch.object(subprocess, "run", side_effect=AssertionError("git was spawned")):
                for revision in bad_revisions:
                    with self.subTest(revision=revision):
                        spec = _spec("local:" + str(repo), revision)
                        probe = adapter.probe(spec)
                        self.assertEqual((probe["available"], probe["reason_code"]), (False, "REVISION_UNAVAILABLE"))
                        with self.assertRaises(SourceError) as ctx:
                            adapter.snapshot(spec, store)
                        self.assertEqual(ctx.exception.code, "REVISION_UNAVAILABLE")
                for url in bad_urls:
                    with self.subTest(url=url):
                        probe = adapter.probe(_spec(url, sha))
                        self.assertEqual((probe["available"], probe["reason_code"]), (False, "IO_ERROR"))
                        with self.assertRaises(SourceError) as ctx:
                            adapter.snapshot(_spec(url, sha), store)
                        self.assertEqual(ctx.exception.code, "IO_ERROR")

    def test_object_ids_from_ls_tree_must_be_40_hex_before_cat_file(self):
        seen = []

        def fake_git(self_, repo, args, source_id, input_bytes=None):
            seen.append(list(args))
            if args[:2] == ["cat-file", "-e"]:
                return b""
            if args[0] == "ls-tree":
                return b"100644 blob --batch-all-objects\tnotes.txt\0"
            raise AssertionError("cat-file --batch must not run for a bad object id")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(GitLocalAdapter, "_git", fake_git):
            adapter = GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW)
            with self.assertRaises(SourceError) as ctx:
                adapter.snapshot(_spec("local:" + tmp, "a" * 40), BlobStore(Path(tmp) / "store"))
        self.assertEqual(ctx.exception.code, "IO_ERROR")
        self.assertNotIn(["cat-file", "--batch"], seen)


if __name__ == "__main__":
    unittest.main()

"""REQ-SEC-001 (REQ-KAP-007): a hostile local clone cannot run code through the git-local adapter.

The clone's own `.git/config`, `.gitattributes`, hook directories and executables are attacker-controlled. Every known
code-execution hook that could plausibly fire during git plumbing is set to a script that appends a marker line. The
adapter's probe and snapshot must finish normally (or fail with a closed code) and the marker must never appear.
Repositories are built with the local git binary; nothing here touches the network.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition import sources as s
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError

GIT = shutil.which("git")
ORIGIN = "https://github.com/odoo/odoo"
ALLOW = s.load_allow_list()
GIT_NAMED_EXECUTABLES = ("git-evil", "git-remote-ext")
# every hook name git defines; installed both under core.hooksPath and under .git/hooks
HOOK_NAMES = (
    "applypatch-msg", "pre-applypatch", "post-applypatch", "pre-commit", "pre-merge-commit", "prepare-commit-msg",
    "commit-msg", "post-commit", "pre-rebase", "post-checkout", "post-merge", "pre-push", "pre-receive", "update",
    "proc-receive", "post-receive", "post-update", "reference-transaction", "push-to-checkout", "pre-auto-gc",
    "post-rewrite", "sendemail-validate", "fsmonitor-watchman", "post-index-change",
)
SETUP_ENV = {
    "PATH": os.environ.get("PATH", ""),
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "LC_ALL": "C",
    "GIT_AUTHOR_NAME": "kap", "GIT_AUTHOR_EMAIL": "kap@example.invalid",
    "GIT_COMMITTER_NAME": "kap", "GIT_COMMITTER_EMAIL": "kap@example.invalid",
}


def _run(args, cwd, input_text=None) -> str:
    """Test-side git call (setup only). Hooks are disabled for commits made before the hostile config exists."""
    proc = subprocess.run(["git", *args], cwd=str(cwd), env=SETUP_ENV, input=input_text, capture_output=True,
                          text=True, check=True, timeout=120)
    return proc.stdout


def _script(path: Path, marker: Path):
    """An executable that records that it ran. Writes nothing else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho fired:$0 >> '{marker}'\n", encoding="utf-8")
    path.chmod(0o755)


def _commit_repo(root: Path, marker: Path) -> tuple:
    """A plain one-commit repository (no hostile configuration yet). Returns (path, commit sha). The `git-*`
    executables are tracked, so they are part of the pinned tree."""
    repo = root / "evil"
    (repo / "addons").mkdir(parents=True)
    _run(["init", "-q"], repo)
    (repo / "addons" / "sale_demo.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "notes.txt").write_text("plain notes\n", encoding="utf-8")
    (repo / ".gitattributes").write_text("*.txt filter=evil diff=evil\n", encoding="utf-8")
    for name in GIT_NAMED_EXECUTABLES:
        _script(repo / name, marker)
    _run(["add", "-A"], repo)
    _run(["-c", "commit.gpgsign=false", "-c", f"core.hooksPath={os.devnull}", "commit", "-q", "-m", "init"], repo)
    return repo, _run(["rev-parse", "HEAD"], repo).strip()


def _hostile_repo(root: Path, marker: Path, *, hooks: str, origin: str = ORIGIN) -> tuple:
    """A clone whose config and files try every known code-execution route. `hooks` is `hooksPath` (hooks from a
    core.hooksPath directory) or `dotgit` (hooks from .git/hooks). `origin` may contain `{evil}`."""
    root.mkdir(parents=True, exist_ok=True)
    repo, sha = _commit_repo(root, marker)
    evil = root / "tools" / "evil.sh"
    _script(evil, marker)
    _run(["remote", "add", "origin", origin.replace("{evil}", str(evil))], repo)
    config = {
        "core.fsmonitor": str(evil),
        "core.pager": str(evil),
        "core.editor": str(evil),
        "core.sshCommand": str(evil),
        "core.askPass": str(evil),
        "diff.external": str(evil),
        "diff.evil.textconv": str(evil),
        "filter.evil.clean": str(evil),
        "filter.evil.smudge": str(evil),
        "credential.helper": str(evil),
        "gpg.program": str(evil),
        "uploadpack.packObjectsHook": str(evil),
        "core.alternateRefsCommand": str(evil),
        "core.gitProxy": str(evil),
        "protocol.ext.allow": "always",
    }
    if hooks == "hooksPath":
        hooks_dir = root / "hooks"
        for name in HOOK_NAMES:
            _script(hooks_dir / name, marker)
        config["core.hooksPath"] = str(hooks_dir)
    elif hooks == "dotgit":
        for name in HOOK_NAMES:
            _script(repo / ".git" / "hooks" / name, marker)
    else:
        raise ValueError(hooks)
    for key, value in config.items():
        _run(["config", "--local", key, value], repo)
    return repo, sha


def _spec(repo, revision, *, official: bool, expected=None) -> dict:
    spec = {
        "source_id": "odoo-community-17.0", "kind": "GIT_COMMUNITY", "official": official,
        "url": "local:" + str(repo), "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3.0", "branch": "17.0",
        "revision": revision, "scope": {"modules": "*", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }
    if expected is not None:
        spec["expected_origin"] = expected
    return spec


class HostileRepoTests(unittest.TestCase):
    def setUp(self):
        if GIT is None:
            self.skipTest("git is not installed")
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.marker = self.root / "PWNED"
        self.adapter = GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW)

    def tearDown(self):
        self._dir.cleanup()

    def _assert_no_marker(self):
        if self.marker.exists():
            self.fail("hostile code ran: " + self.marker.read_text(encoding="utf-8"))

    def test_probe_and_snapshot_run_no_hostile_code(self):
        for mode in ("hooksPath", "dotgit"):
            with self.subTest(hooks=mode):
                repo, sha = _hostile_repo(self.root / mode, self.marker, hooks=mode)
                store = BlobStore(self.root / mode / "store")

                plain = _spec(repo, sha, official=False)
                self.assertEqual(self.adapter.probe(plain)["reason_code"], "OK")
                snap = self.adapter.snapshot(plain, store, created_at="2026-01-01T00:00:00Z")
                self.assertEqual(
                    [e["path"] for e in snap["entries"]],
                    [".gitattributes", "addons/sale_demo.py", "git-evil", "git-remote-ext", "notes.txt"])
                self.assertNotIn("origin_url", snap)
                self._assert_no_marker()

                verified = _spec(repo, sha, official=True, expected=ORIGIN)
                self.assertEqual(self.adapter.probe(verified)["reason_code"], "OK")
                snap = self.adapter.snapshot(verified, store, created_at="2026-01-01T00:00:00Z")
                self.assertIn("github.com/odoo/odoo", snap["origin_url"])
                self.assertEqual(snap["revision"], sha)
                self._assert_no_marker()

    def test_positive_control_hostile_config_fires_for_ordinary_git(self):
        """Control for the tests above: the same clone DOES run hostile code when git runs a command that reads the
        working tree and diffs (fsmonitor, external diff, filters). Without this, 'never fired' would prove nothing."""
        repo, _ = _hostile_repo(self.root / "control", self.marker, hooks="hooksPath")
        _run(["status", "--porcelain"], repo)
        _run(["log", "-p", "-1"], repo)
        self.assertTrue(self.marker.exists(), "the hostile fixture is inert; the other tests prove nothing")

    def test_snapshot_content_is_the_pinned_tree_not_a_replacement(self):
        repo, sha = _commit_repo(self.root, self.marker)
        # a refs/replace/<commit> entry in an untrusted clone must not change what the pinned commit contains
        blob = _run(["hash-object", "-w", "--stdin"], repo, input_text="evil replacement\n").strip()
        tree = _run(["mktree"], repo, input_text=f"100644 blob {blob}\tsale_demo.py\n").strip()
        replacement = _run(["commit-tree", tree, "-m", "replacement"], repo).strip()
        _run(["replace", sha, replacement], repo)
        spec = _spec(repo, sha, official=False)
        snap = self.adapter.snapshot(spec, BlobStore(self.root / "store"), created_at="2026-01-01T00:00:00Z")
        by_path = {e["path"]: e for e in snap["entries"]}
        self.assertEqual(sorted(by_path), [".gitattributes", "addons/sale_demo.py", "git-evil",
                                         "git-remote-ext", "notes.txt"])
        self.assertEqual(by_path["addons/sale_demo.py"]["sha256"],
                         hashlib.sha256(b"x = 1\n").hexdigest())

    def test_remote_get_url_prints_and_never_invokes_transport(self):
        root = self.root / "ext"
        repo, sha = _hostile_repo(root, self.marker, hooks="hooksPath", origin="ext::{evil}")
        evil = root / "tools" / "evil.sh"
        out = self.adapter._git(str(repo), ["remote", "get-url", "origin"], "odoo-src").decode("utf-8")
        self.assertEqual(out.strip(), "ext::" + str(evil))
        self._assert_no_marker()
        official = _spec(repo, sha, official=True, expected=ORIGIN)
        probe = self.adapter.probe(official)
        self.assertEqual((probe["available"], probe["reason_code"]), (False, "OFFICIAL_IDENTITY_UNVERIFIED"))
        with self.assertRaises(SourceError) as ctx:
            self.adapter.snapshot(official, BlobStore(self.root / "store"))
        self.assertEqual(ctx.exception.code, "OFFICIAL_IDENTITY_UNVERIFIED")
        self._assert_no_marker()

    def test_insteadof_rewrite_is_printed_not_executed(self):
        root = self.root / "rewrite"
        repo, sha = _commit_repo(root, self.marker)
        evil = root / "tools" / "evil.sh"
        _script(evil, self.marker)
        _run(["remote", "add", "origin", "https://example.invalid/odoo"], repo)
        _run(["config", "--local", f"url.ext::{evil}.insteadOf", "https://example.invalid/"], repo)
        _run(["config", "--local", "protocol.ext.allow", "always"], repo)
        official = _spec(repo, sha, official=True, expected="https://example.invalid/odoo")
        probe = self.adapter.probe(official)
        self.assertEqual((probe["available"], probe["reason_code"]), (False, "OFFICIAL_IDENTITY_UNVERIFIED"))
        self._assert_no_marker()

    @unittest.expectedFailure
    def test_known_gap_insteadof_cannot_forge_official_identity(self):
        """KNOWN GAP, not fixed. `git remote get-url` prints the insteadOf-rewritten URL, so a clone whose stored
        origin is an ext:: URL can pass official identity. Fixing it needs the raw remote URL, which is a `git config`
        call outside the documented command set. Remove the expectedFailure marker when that changes."""
        repo, sha = _commit_repo(self.root / "spoof", self.marker)
        evil = self.root / "spoof" / "tools" / "evil.sh"
        _script(evil, self.marker)
        _run(["remote", "add", "origin", "ext::" + str(evil)], repo)
        _run(["config", "--local", "url.https://github.com/odoo/odoo.insteadOf", "ext::" + str(evil)], repo)
        _run(["config", "--local", "protocol.ext.allow", "always"], repo)
        probe = self.adapter.probe(_spec(repo, sha, official=True, expected=ORIGIN))
        self.assertEqual(probe["reason_code"], "OFFICIAL_IDENTITY_UNVERIFIED")
        self._assert_no_marker()


if __name__ == "__main__":
    unittest.main()

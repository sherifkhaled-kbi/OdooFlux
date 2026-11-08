"""TST-085 (REQ-KAP-044, REQ-KAP-009): opt-in live source tests, each with an offline counterpart.

Live tests never run by default. Each one is gated by an environment variable and reuses the same helper as its
offline counterpart, so the code path is covered without any network or Docker access:
- test_live_clone_acquire: `ODOOFLUX_KAP_CLONES=<path to a real odoo clone>` and `ODOOFLUX_KAP_CLONE_REV=<40-hex
  commit present in that clone>`. The pin is read from the environment only; no SHA is hardcoded. Offline:
  test_offline_clone_acquire on the synthetic repository from `tests/fixtures/kap/make_synth_repo.py`.
- test_live_fetch_checksum: `ODOOFLUX_KAP_LIVE_TESTS=1`, `ODOOFLUX_KAP_FETCH_URL=<allow-listed https URL>`,
  `ODOOFLUX_KAP_FETCH_SHA256=<expected digest>`. Offline: test_offline_fetch_checksum uses an injected opener that
  reads a local file, with sockets patched to fail.
- test_live_docker_skipped_by_default: `ODOOFLUX_KAP_DOCKER_TESTS=1` only runs `docker version` through the
  existing DockerEnvironment probe. No container is started. Offline: test_docker_gate_offline uses a fake runner.
"""

import hashlib
import io
import os
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.acquisition import fetch as fetch_mod
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.validation.runtime.docker_env import CommandResult, DockerEnvironment
from tests.fixtures.kap.make_synth_repo import build_synth_repo

GIT = shutil.which("git")
ALLOW = ["https://github.com/odoo/odoo/", "https://github.com/odoo/documentation/"]
PAYLOAD = b"synthetic release archive bytes\n"
CLONES_ENV = "ODOOFLUX_KAP_CLONES"
REV_ENV = "ODOOFLUX_KAP_CLONE_REV"
LIVE_ENV = "ODOOFLUX_KAP_LIVE_TESTS"
FETCH_URL_ENV = "ODOOFLUX_KAP_FETCH_URL"
FETCH_SHA_ENV = "ODOOFLUX_KAP_FETCH_SHA256"
DOCKER_ENV = "ODOOFLUX_KAP_DOCKER_TESTS"


def _clone_spec(url: str, revision: str) -> dict:
    return {
        "source_id": "kap-live-clone", "kind": "GIT_COMMUNITY", "official": False, "url": url,
        "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3", "branch": None, "revision": revision,
        "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }


def _acquire_clone(clone_path, revision: str, store_root: Path) -> dict:
    """Shared by the live and offline clone tests: pinned snapshot through the git-local adapter."""
    adapter = GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW)
    spec = _clone_spec("local:" + str(clone_path), revision)
    probe = adapter.probe(spec)
    if not probe["available"]:
        raise SourceError(probe["reason_code"], spec["source_id"], probe["detail"])
    return adapter.snapshot(spec, BlobStore(store_root))


class _LocalBody(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _LocalOpener:
    """Stands in for the network: serves a local file for any URL and records the requests."""

    def __init__(self, path):
        self.path = Path(path)
        self.requested = []

    def open(self, url, timeout=None):
        self.requested.append(url)
        return _LocalBody(self.path.read_bytes())


def _fetch_checked(url: str, expected_sha256, store: BlobStore, opener=None, allow_network=True) -> dict:
    """Shared by the live and offline fetch tests."""
    spec = {"source_id": "kap-live-fetch", "url": url}
    return fetch_mod.fetch(spec, store, allow_network=allow_network, expected_sha256=expected_sha256,
                           opener=opener, allow_list=ALLOW)


def _docker_reachability(runner=None):
    """Runs the existing probe only when ODOOFLUX_KAP_DOCKER_TESTS=1. Returns None when the gate is closed."""
    if os.environ.get(DOCKER_ENV) != "1":
        return None
    return DockerEnvironment(runner=runner).available()


def _no_socket(*args, **kwargs):
    raise AssertionError("network access attempted in an offline test")


def _live_fetch_ready() -> bool:
    return os.environ.get(LIVE_ENV) == "1" and bool(os.environ.get(FETCH_URL_ENV)) and \
        bool(os.environ.get(FETCH_SHA_ENV))


class LiveSourcesTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get(CLONES_ENV) and os.environ.get(REV_ENV) and GIT,
                         f"opt-in: set {CLONES_ENV} and {REV_ENV} (real odoo clone and a pinned commit in it)")
    def test_live_clone_acquire(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = _acquire_clone(os.environ[CLONES_ENV], os.environ[REV_ENV], Path(tmp) / "store")
        self.assertEqual(snap["revision"], os.environ[REV_ENV])
        self.assertTrue(snap["entries"])
        self.assertRegex(snap["snapshot_digest"], r"^[0-9a-f]{64}$")

    @unittest.skipUnless(_live_fetch_ready(),
                         f"opt-in: set {LIVE_ENV}=1, {FETCH_URL_ENV} and {FETCH_SHA_ENV} (never run by default)")
    def test_live_fetch_checksum(self):
        expected = os.environ[FETCH_SHA_ENV]
        with tempfile.TemporaryDirectory() as tmp:
            result = _fetch_checked(os.environ[FETCH_URL_ENV], expected, BlobStore(Path(tmp) / "store"))
        self.assertEqual(result["sha256"], expected)

    @unittest.skipUnless(os.environ.get(DOCKER_ENV) == "1",
                         f"opt-in: set {DOCKER_ENV}=1 (only runs `docker version`; starts no container)")
    def test_live_docker_skipped_by_default(self):
        ok, detail = _docker_reachability()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(detail, str)


class OfflineCounterpartTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    @unittest.skipUnless(GIT, "git is not installed; the offline clone test builds a synthetic repository")
    def test_offline_clone_acquire(self):
        repo = build_synth_repo(self.base / "synth")
        with mock.patch.object(socket, "socket", _no_socket), \
                mock.patch.object(socket, "create_connection", _no_socket):
            snap = _acquire_clone(repo.path, repo.from_sha, self.base / "store")
        self.assertEqual(snap["revision"], repo.from_sha)
        # the same pin acquired twice gives the same digest (deterministic snapshot)
        with mock.patch.object(socket, "socket", _no_socket):
            again = _acquire_clone(repo.path, repo.from_sha, self.base / "store2")
        self.assertEqual(snap.get("snapshot_digest"), again.get("snapshot_digest"))

    def test_offline_fetch_checksum(self):
        payload_file = self.base / "payload.bin"
        payload_file.write_bytes(PAYLOAD)
        digest = hashlib.sha256(PAYLOAD).hexdigest()
        url = "https://github.com/odoo/odoo/archive/synthetic.tar.gz"
        store = BlobStore(self.base / "store")
        opener = _LocalOpener(payload_file)
        with mock.patch.object(socket, "socket", _no_socket), \
                mock.patch.object(socket, "create_connection", _no_socket):
            result = _fetch_checked(url, digest, store, opener=opener)
            self.assertEqual(result["sha256"], digest)
            self.assertTrue(Path(store.path_for(digest)).exists())
            self.assertEqual(opener.requested, [url])
            # a wrong expected digest is refused and nothing is stored under the actual digest
            other = self.base / "store-mismatch"
            bad_store = BlobStore(other)
            with self.assertRaises(SourceError) as ctx:
                _fetch_checked(url, "0" * 64, bad_store, opener=_LocalOpener(payload_file))
            self.assertEqual(ctx.exception.code, "CHECKSUM_MISMATCH")
            self.assertFalse(Path(bad_store.path_for(digest)).exists())
            # the network gate is still closed without the explicit flag
            with self.assertRaises(SourceError) as ctx:
                _fetch_checked(url, digest, store, opener=_LocalOpener(payload_file), allow_network=False)
            self.assertEqual(ctx.exception.code, "NETWORK_DISABLED")

    def test_docker_gate_offline(self):
        calls = []

        def runner(argv, timeout=None):
            calls.append(list(argv))
            return CommandResult(0, "27.0\n", "")

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DOCKER_ENV, None)
            self.assertIsNone(_docker_reachability(runner=runner))
            self.assertEqual(calls, [])  # gate closed: the probe is never reached
        with mock.patch.dict(os.environ, {DOCKER_ENV: "1"}), mock.patch.object(shutil, "which", return_value="/x/d"):
            ok, detail = _docker_reachability(runner=runner)
        self.assertTrue(ok)
        self.assertEqual(calls, [["docker", "version", "--format", "{{.Server.Version}}"]])  # nothing else run


if __name__ == "__main__":
    unittest.main()

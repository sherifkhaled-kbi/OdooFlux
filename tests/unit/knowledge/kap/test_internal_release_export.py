"""Feature 012 W3-Y: internal and Enterprise-derived releases never leave the machine.

Owner-approved trust model: a release is INTERNAL when release.json has top-level `confidentiality: "internal"`; a
release that holds Enterprise-derived material (GIT_ENTERPRISE or ENTERPRISE_LOCAL sources, `confidentiality:
"enterprise"`, legacy `enterprise_derived: true`, evidence or snapshot manifests naming such a source) is refused the
same way. Export refuses with EXPORT_REFUSED, the importer refuses with P12 before anything is staged, and `package
validate` reports P12. There is no override: `export_package` has no include parameter and the CLI has no flag.

Packages are built with the real builder for public trees. Internal trees are sealed here with the validator's digest
rule (release_digest over release.json minus release_id and release_digest), because the public manifest writer does
not carry top-level fields. Importer and validator cases use hand-built packages, so the refusal is exercised on the
bytes an attacker would supply, not on a tree the exporter would have produced.
"""

import hashlib
import inspect
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import odooflux
from odooflux.cli.kap_common import EXIT_PACKAGE_REJECTED
from odooflux.cli.knowledge import main as knowledge_main
from odooflux.knowledge.package.archive import MANIFEST_NAME as PACKAGE_MANIFEST, PackageError
from odooflux.knowledge.package.builder import PACKAGE_FORMAT, SUMS_NAME, _zip_bytes_to, export_package, sums_text
from odooflux.knowledge.package.importer import import_package
from odooflux.knowledge.package.validate import validate_package
from odooflux.knowledge.release.canonical import digest_obj, write_json_file
from odooflux.knowledge.release.manifest import MANIFEST_NAME as RELEASE_MANIFEST, build_manifest, require_intact, \
    write_release_manifest
from odooflux.knowledge.release.model import ReleaseState, release_id_from_digest
from odooflux.knowledge.release.store import ensure_layout, set_release_state

ENT_ID = "odoo-enterprise-17.0"
ENT_SNAPSHOT = "snapshots/ss-0123456789ab.json"
META = {
    "label": "community-17.0-18.0-2026.11",
    "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}
PUBLIC_FILES = {
    "knowledge/evidence/EV-001.json": b'{"id": "EV-001", "status": "VERIFIED", "source_id": "odoo-community-17.0"}\n',
    "knowledge/compatibility/versions.json": b'{"versions": []}\n',
    "coverage/coverage-manifest.json": b'{"items": []}\n',
    "provenance/sources.json": b'{"sources": []}\n',
}
# provenance/sources.json is the release writer's list of entries (provenance.py write_provenance).
ENTERPRISE_PROVENANCE = json.dumps([{
    "source_id": ENT_ID, "kind": "GIT_ENTERPRISE", "url": "https://example.invalid/enterprise", "revision": "17.0",
    "snapshot_digest": "ab" * 32, "snapshot_id": "ss-0123456789ab", "official": False, "status": "VERIFIED",
}], indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _seal(root: Path, *, files: dict = None, meta: dict = None, extra: dict = None) -> Path:
    """Write `files`, then a release.json that carries `extra` top-level fields, sealed with the validator's digest rule."""
    root.mkdir(parents=True, exist_ok=True)
    for rel, data in (PUBLIC_FILES if files is None else files).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = build_manifest(root, META if meta is None else meta)
    manifest.update(extra or {})
    body = {key: value for key, value in manifest.items() if key not in ("release_id", "release_digest")}
    manifest["release_digest"] = digest_obj(body)
    manifest["release_id"] = release_id_from_digest(manifest["release_digest"])
    write_json_file(root / RELEASE_MANIFEST, manifest)
    require_intact(root)
    return root


def _listing(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        out[rel] = None if path.is_dir() else path.read_bytes()
    return out


def _hand_package(path: Path, root: Path, *, declared: bool = False) -> Path:
    """A `.ofkp` built by hand from a release tree: every release file, package.json and SHA256SUMS. `declared` sets
    package.json `contains_enterprise_derived` to true, which a legacy exporter could have written."""
    release = json.loads((root / RELEASE_MANIFEST).read_text(encoding="utf-8"))
    members = {}
    for item in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = item.relative_to(root).as_posix()
        if rel != "state.json":
            members[rel] = item.read_bytes()
    entries = [{"path": rel, "sha256": hashlib.sha256(members[rel]).hexdigest(), "size": len(members[rel])}
               for rel in sorted(members, key=lambda n: n.encode("utf-8"))]
    framework = release["framework"]
    package = {
        "format": PACKAGE_FORMAT, "release_id": release["release_id"], "release_digest": release["release_digest"],
        "created_with": "odooflux hand-built", "entries": entries, "entry_count": len(entries),
        "total_size": sum(e["size"] for e in entries),
        "compat": {"min_framework": framework["min_framework"], "max_framework": framework["max_framework"],
                   "schemas": release["schema_versions"]},
        "contains_enterprise_derived": declared, "redaction_scan": {"status": "PASSED", "scanner_version": "1"},
    }
    all_members = [(PACKAGE_MANIFEST, (json.dumps(package, indent=2, sort_keys=True) + "\n").encode("utf-8")),
                   (SUMS_NAME, sums_text(entries))] + sorted(members.items())
    all_members.sort(key=lambda item: item[0].encode("utf-8"))
    _zip_bytes_to(path, all_members)
    return path


class TestInternalReleaseExport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _refused(self, root: Path, out: Path) -> PackageError:
        before = _listing(self.tmp)
        with self.assertRaises(PackageError) as ctx:
            export_package(root, out)
        self.assertEqual(ctx.exception.code, "EXPORT_REFUSED")
        self.assertFalse(out.exists())
        self.assertEqual(_listing(self.tmp), before, "a refused export must write nothing")
        return ctx.exception

    def test_internal_manifest_refused(self):
        root = _seal(self.tmp / "internal", extra={"confidentiality": "internal"})
        exc = self._refused(root, self.tmp / "out" / "internal.ofkp")
        self.assertIn("internal", exc.detail)

    def test_forged_release_without_confidentiality_refused(self):
        # The release says nothing about confidentiality, but its provenance names an Enterprise source.
        root = _seal(self.tmp / "forged", files={**PUBLIC_FILES, "provenance/sources.json": ENTERPRISE_PROVENANCE})
        self.assertNotIn("confidentiality", json.loads((root / RELEASE_MANIFEST).read_text(encoding="utf-8")))
        self._refused(root, self.tmp / "out" / "forged.ofkp")

    def test_enterprise_confidentiality_on_release_source_refused(self):
        meta = {**META, "sources": [{"source_id": ENT_ID, "revision": "17.0", "snapshot_digest": "ab" * 32,
                                     "official": False, "status": "VERIFIED", "confidentiality": "enterprise"}]}
        root = _seal(self.tmp / "release-source", meta=meta)
        self._refused(root, self.tmp / "out" / "release-source.ofkp")

    def test_evidence_only_reference_refused(self):
        # No release or provenance record marks the source; only an evidence row names the Enterprise id.
        evidence = json.dumps({"id": "EV-002", "status": "VERIFIED", "source_id": ENT_ID}).encode("utf-8") + b"\n"
        root = _seal(self.tmp / "evidence", files={**PUBLIC_FILES, "knowledge/evidence/EV-002.json": evidence})
        self._refused(root, self.tmp / "out" / "evidence.ofkp")

    def test_unparseable_record_naming_enterprise_refused(self):
        # Not JSON, so it cannot be read as a record; its raw bytes still name an Enterprise source.
        broken = b'{"id": "EV-003", "source_id": "odoo-enterprise-17.0", "status": '
        root = _seal(self.tmp / "broken", files={**PUBLIC_FILES, "knowledge/evidence/EV-003.json": broken})
        self._refused(root, self.tmp / "out" / "broken.ofkp")

    def test_enterprise_snapshot_manifest_refused(self):
        cases = {
            "marked by kind": {"source_id": "local-src", "kind": "GIT_ENTERPRISE", "revision": "17.0", "entries": []},
            "named by Enterprise id": {"source_id": ENT_ID, "revision": "17.0", "entries": []},
        }
        for index, (label, snapshot) in enumerate(cases.items()):
            with self.subTest(label):
                files = {**PUBLIC_FILES, ENT_SNAPSHOT: json.dumps(snapshot).encode("utf-8") + b"\n"}
                root = _seal(self.tmp / f"snap-{index}", files=files)
                exc = self._refused(root, self.tmp / "out" / "snap.ofkp")
                # The message names no snapshot path or file name.
                self.assertNotIn("snapshots/", str(exc))
                self.assertNotIn("ss-0123456789ab", str(exc))
                self.assertNotIn(str(root), str(exc))

    def test_public_snapshot_manifest_still_allowed(self):
        snapshot = json.dumps({"source_id": "odoo-community-17.0", "revision": "17.0", "entries": []}).encode() + b"\n"
        root = _seal(self.tmp / "public-snap", files={**PUBLIC_FILES, ENT_SNAPSHOT: snapshot})
        info = export_package(root, self.tmp / "public-snap.ofkp")
        self.assertFalse(info.contains_enterprise_derived)

    def test_export_has_no_include_parameter(self):
        params = inspect.signature(export_package).parameters
        self.assertFalse(any("enterprise" in name for name in params), list(params))
        root = _seal(self.tmp / "param", extra={"confidentiality": "internal"})
        with self.assertRaises(TypeError):
            export_package(root, self.tmp / "p.ofkp", include_enterprise_derived=True)
        self.assertFalse((self.tmp / "p.ofkp").exists())

    def test_no_include_flag_in_source_tree(self):
        src = Path(odooflux.__file__).resolve().parent
        hits = [p.relative_to(src).as_posix() for p in src.rglob("*.py")
                if "include-enterprise" in p.read_text(encoding="utf-8") or "include_enterprise" in p.read_text(encoding="utf-8")]
        self.assertEqual(hits, [])

    def test_cli_rejects_old_flag(self):
        home = self.tmp / "kb"
        out = self.tmp / "cli.ofkp"
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = knowledge_main(["package", "export", "kr-000000000000", "-o", str(out), "--kb-home", str(home),
                                   "--include-enterprise-derived"])
        self.assertEqual(code, 2)  # argparse usage error
        self.assertIn("unrecognized arguments", err.getvalue())
        self.assertFalse(out.exists())

    def test_cli_refuses_installed_internal_release(self):
        home = self.tmp / "kb"
        ensure_layout(home)
        root = _seal(self.tmp / "installed", extra={"confidentiality": "internal"})
        release_id = json.loads((root / RELEASE_MANIFEST).read_text(encoding="utf-8"))["release_id"]
        shutil.copytree(root, home / "releases" / release_id)
        set_release_state(home, release_id, ReleaseState.INSTALLED)
        out = self.tmp / "out" / "cli.ofkp"
        before = _listing(self.tmp)
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = knowledge_main(["package", "export", release_id, "-o", str(out), "--kb-home", str(home)])
        self.assertEqual(code, EXIT_PACKAGE_REJECTED)
        self.assertIn("EXPORT_REFUSED", err.getvalue())
        self.assertFalse(out.exists())
        self.assertFalse((self.tmp / "out").exists())
        self.assertEqual(_listing(self.tmp), before)

    def test_public_export_unchanged(self):
        root = self.tmp / "public"
        for rel, data in PUBLIC_FILES.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
        write_release_manifest(root, META)
        first = export_package(root, self.tmp / "a.ofkp")
        second = export_package(root, self.tmp / "b.ofkp")
        self.assertEqual(first.sha256, second.sha256)
        self.assertFalse(first.contains_enterprise_derived)
        package = json.loads(_read_member(self.tmp / "a.ofkp", PACKAGE_MANIFEST))
        self.assertIs(package["contains_enterprise_derived"], False)
        # A public release that explicitly says so exports too.
        marked = _seal(self.tmp / "marked", extra={"confidentiality": "public"})
        info = export_package(marked, self.tmp / "marked.ofkp")
        self.assertFalse(info.contains_enterprise_derived)

    def test_importer_refuses_internal_package_before_staging(self):
        root = _seal(self.tmp / "internal", extra={"confidentiality": "internal"})
        package = _hand_package(self.tmp / "internal.ofkp", root)
        home = ensure_layout(self.tmp / "kb")
        before = _listing(home)
        with self.assertRaises(PackageError) as ctx:
            import_package(package, home)
        self.assertEqual(ctx.exception.code, "P12")
        self.assertEqual(_listing(home), before, "kb-home must be unchanged; nothing staged")
        self.assertEqual(list((home / "staging").iterdir()), [])
        self.assertNotIn(str(self.tmp), str(ctx.exception))

    def test_importer_refuses_declared_enterprise_package(self):
        root = _seal(self.tmp / "declared")
        package = _hand_package(self.tmp / "declared.ofkp", root, declared=True)
        home = ensure_layout(self.tmp / "kb")
        before = _listing(home)
        with self.assertRaises(PackageError) as ctx:
            import_package(package, home)
        self.assertEqual(ctx.exception.code, "P12")
        self.assertEqual(_listing(home), before)

    def test_importer_error_names_no_enterprise_snapshot(self):
        files = {**PUBLIC_FILES, ENT_SNAPSHOT: json.dumps({"source_id": ENT_ID, "entries": []}).encode() + b"\n"}
        root = _seal(self.tmp / "snap-internal", files=files, extra={"confidentiality": "internal"})
        package = _hand_package(self.tmp / "snap-internal.ofkp", root)
        home = ensure_layout(self.tmp / "kb")
        with self.assertRaises(PackageError) as ctx:
            import_package(package, home)
        self.assertEqual(ctx.exception.code, "P12")
        message = str(ctx.exception)
        self.assertNotIn("snapshots/", message)
        self.assertNotIn("ss-0123456789ab", message)

    def test_validate_reports_p12(self):
        root = _seal(self.tmp / "internal", extra={"confidentiality": "internal"})
        package = _hand_package(self.tmp / "internal.ofkp", root)
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        with self.assertRaises(PackageError) as ctx:
            validate_package(package, scratch)
        self.assertEqual(ctx.exception.code, "P12")
        self.assertEqual(list(scratch.iterdir()), [])
        home = ensure_layout(self.tmp / "kb")
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = knowledge_main(["package", "validate", str(package), "--kb-home", str(home)])
        self.assertEqual(code, EXIT_PACKAGE_REJECTED)
        self.assertIn("P12", err.getvalue())


def _read_member(archive: Path, name: str) -> str:
    import zipfile
    with zipfile.ZipFile(archive) as zf:
        return zf.read(name).decode("utf-8")


if __name__ == "__main__":
    unittest.main()

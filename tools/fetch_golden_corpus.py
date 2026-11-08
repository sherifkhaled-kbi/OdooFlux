#!/usr/bin/env python3
"""Fetch the version-pinned golden-corpus INPUT modules listed in knowledge/golden_corpus/manifest.json.

Stdlib only. Files are downloaded from raw.githubusercontent.com at pinned commit SHAs and
verified against the manifest sha256. Layout: <dest>/<version>/<addon>/<path within addon>.

    python3 tools/fetch_golden_corpus.py [DEST]          # download + verify
    python3 tools/fetch_golden_corpus.py --check [DEST]  # offline: verify files already in DEST
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "knowledge" / "golden_corpus" / "manifest.json"
DEFAULT_DEST = "/tmp/odooflux-golden-corpus"


def load_manifest(path=MANIFEST):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def target_path(dest, entry, file):
    prefix = f"addons/{entry['addon']}/"
    return Path(dest) / entry["version"] / entry["addon"] / file["path"][len(prefix):]


def iter_files(manifest, dest):
    for entry in manifest["entries"]:
        for f in entry["files"]:
            yield entry, f, target_path(dest, entry, f)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def check(manifest, dest):
    bad = 0
    for _, f, p in iter_files(manifest, dest):
        if not p.is_file():
            print(f"MISSING {p}")
            bad += 1
        elif sha256(p.read_bytes()) != f["sha256"]:
            print(f"MISMATCH {p}")
            bad += 1
    return bad


def fetch(manifest, dest):
    bad = 0
    for entry, f, p in iter_files(manifest, dest):
        if p.is_file() and sha256(p.read_bytes()) == f["sha256"]:
            continue
        url = f"https://raw.githubusercontent.com/{entry['repository']}/{entry['revision']}/{f['path']}"
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 (fixed https host)
            data = r.read()
        if sha256(data) != f["sha256"]:
            print(f"MISMATCH {url}")
            bad += 1
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dest", nargs="?", default=DEFAULT_DEST)
    ap.add_argument("--check", action="store_true", help="verify existing files only; no network")
    ap.add_argument("--manifest", default=str(MANIFEST))
    a = ap.parse_args(argv)
    m = load_manifest(a.manifest)
    bad = check(m, a.dest) if a.check else fetch(m, a.dest)
    print("FAILED" if bad else "OK", f"({bad} problem(s))" if bad else "")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

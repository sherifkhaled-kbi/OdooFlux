"""Package compatibility checks (P07; REQ-KAP-047; contracts/knowledge-package-format.md "Reader rules").

A package is loadable only when its `format` is known, the running framework lies in
`[min_framework, max_framework]`, and every declared schema family is one this framework knows at the declared
version. Anything else is a P07 rejection. No partial acceptance.
"""

import re

from odooflux import __version__
from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import PACKAGE_FORMAT
from odooflux.knowledge.release.manifest import FORMAT as RELEASE_FORMAT

# Schema families and the versions this framework can read.
KNOWN_SCHEMAS = {"evidence": ("1",), "rule_metadata": ("1",)}
KNOWN_FORMATS = frozenset({PACKAGE_FORMAT})
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_version(text) -> tuple:
    """`X.Y.Z` as an int tuple. Anything else raises ValueError (callers turn it into P07)."""
    if not isinstance(text, str):
        raise ValueError("version is not a string")
    match = _VERSION.match(text)
    if not match:
        raise ValueError(f"version {text!r} is not X.Y.Z")
    return tuple(int(part) for part in match.groups())


def _reject(detail: str) -> PackageError:
    return PackageError("P07", detail, "package.json")


def check_compat(manifest, running_version: str = None) -> None:
    """Raise P07 unless `manifest` (package.json) is readable by the running framework."""
    running = parse_version(running_version or __version__)
    if not isinstance(manifest, dict):
        raise _reject("package manifest is not a JSON object")
    if manifest.get("format") not in KNOWN_FORMATS:
        raise _reject(f"unknown or newer package format {manifest.get('format')!r}")
    compat = manifest.get("compat")
    if not isinstance(compat, dict):
        raise _reject("package has no compat section")
    try:
        minimum = parse_version(compat.get("min_framework"))
        maximum = None if compat.get("max_framework") is None else parse_version(compat.get("max_framework"))
    except ValueError as exc:
        raise _reject(str(exc)) from None
    if running < minimum:
        raise _reject(f"package needs framework >= {compat.get('min_framework')}, running {running_version or __version__}")
    if maximum is not None and running > maximum:
        raise _reject(f"package supports framework <= {compat.get('max_framework')}, running {running_version or __version__}")
    schemas = compat.get("schemas")
    if not isinstance(schemas, dict):
        raise _reject("compat.schemas must be an object")
    for family, version in sorted(schemas.items()):
        if version not in KNOWN_SCHEMAS.get(family, ()):
            raise _reject(f"unknown schema family or version: {family} {version!r}")


def check_release_format(release) -> None:
    """P07 for the release manifest: format must be the one this framework writes."""
    if not isinstance(release, dict) or release.get("format") != RELEASE_FORMAT:
        raise PackageError("P07", f"release manifest format is not {RELEASE_FORMAT}", "release.json")

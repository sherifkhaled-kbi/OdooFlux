"""Golden-fixture index and copy helpers (REQ-TST-003).

``tests/golden_fixtures/INDEX.json`` is ``{"schema": 1, "fixtures": [...]}``. Entry fields: ``id``, ``source_version``
(``"17.0"``), ``module`` (directory name), ``path`` (module directory relative to the fixtures root), ``targets``
(list of ``"M.0"``), ``evidence``, ``findings``, ``authority`` (``"PROVISIONAL"`` or ``"BASELINE"``) and
``input_digest`` (SHA-256 of the module directory, excluding ``expected/`` and ``PROVISIONAL.md``).
"""

import json
import shutil
from pathlib import Path

from tests._support.digest import digest_hex

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "golden_fixtures"
INDEX_PATH = FIXTURES_ROOT / "INDEX.json"
EXCLUDED = ("expected", "PROVISIONAL.md")


def load_index(path=INDEX_PATH) -> list:
    return json.loads(Path(path).read_text(encoding="utf-8"))["fixtures"]


def entry(fixture_id: str) -> dict:
    for item in load_index():
        if item["id"] == fixture_id:
            return item
    raise KeyError(fixture_id)


def module_dir(item: dict) -> Path:
    return FIXTURES_ROOT / item["path"]


def input_digest(item: dict) -> str:
    """Digest of the fixture module as tests see it (without expected outputs and the marker)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / item["module"]
        shutil.copytree(module_dir(item), target, ignore=shutil.ignore_patterns(*EXCLUDED))
        return digest_hex(target)


def copy_fixture(fixture_id: str, tmp) -> Path:
    """Copy the module of *fixture_id* to ``<tmp>/<module>`` (no expected outputs) and return that path."""
    item = entry(fixture_id)
    target = Path(tmp) / item["module"]
    shutil.copytree(module_dir(item), target, ignore=shutil.ignore_patterns(*EXCLUDED))
    return target

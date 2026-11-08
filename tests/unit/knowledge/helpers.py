import shutil
import tempfile
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge

GOLDEN = Path(__file__).resolve().parents[3] / "tests" / "golden_fixtures" / "knowledge"
SHIPPED = KNOWLEDGE_ROOT


def copy_fixture(name: str) -> Path:
    """Copy a golden knowledge fixture to a temp directory and return it (tests may mutate the copy)."""
    tmp = Path(tempfile.mkdtemp()) / name
    shutil.copytree(GOLDEN / name, tmp)
    return tmp


def codes(root: Path) -> set:
    from odooflux.knowledge.checks import validate_knowledge
    return {f.code for f in validate_knowledge(load_knowledge(root))}

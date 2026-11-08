"""Regenerate the golden report models: PYTHONPATH=src python3 -m tests.golden_fixtures.reports.build_goldens

The scenario states live in tests/unit/reporting/fixtures.py. Goldens are synthetic mechanics fixtures: they carry
no migration truth. test_goldens.py fails when the committed files drift from the generator."""

import json
from pathlib import Path

from tests.unit.reporting.helpers import build
from tests.unit.reporting import fixtures

HERE = Path(__file__).resolve().parent


def main() -> None:
    for name in fixtures.scenarios():
        text = json.dumps(build(name), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
        (HERE / f"{name}.json").write_text(text, encoding="utf-8")
        print("wrote", name)


if __name__ == "__main__":
    main()

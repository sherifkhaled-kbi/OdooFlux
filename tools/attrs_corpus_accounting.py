#!/usr/bin/env python3
"""Maintainer script (not shipped): bucket every ``attrs`` occurrence of a module tree (AF-8).

Usage: ``.venv/bin/python tools/attrs_corpus_accounting.py <root> [--json OUT] [--top N] [--module-context]``

With ``--module-context`` the fixer gets the module context of a run (``ModuleViews``: the sibling module directories of
each module), as ``--experimental-fixes`` gives it; by default each document is accounted alone.

Prints converted / refused (by reason) / not visited (by location) and the residual. Exits 1 when the buckets do not
add up to the total or the residual is not zero. Reads files only; no network. Logic: ``odooflux.rules.experimental.
attrs_accounting``.
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from odooflux.rules.experimental import attrs_accounting as acc  # noqa: E402
from odooflux.rules.experimental.xml_modifiers import ModuleViews  # noqa: E402


def _print(accounting, top: int) -> None:
    totals = accounting.totals
    print(f"XML files: {accounting.xml_files}   files with occurrences: {len(accounting.files)}   "
          f"parse errors: {len(accounting.parse_errors)}")
    print(f"occurrences (total):        {totals.occurrences}   "
          f"(of which inherited <attribute name=\"attrs\"> sites: {totals.structural})")
    print(f"  converted:                {totals.converted}   (of which inherited sites: {totals.converted_structural})")
    refused = sum(totals.refused.values())
    print(f"  refused:                  {refused}")
    for reason, count in totals.refused.most_common(top):
        print(f"      {reason:<34} {count}")
    other = sum(totals.not_visited.values())
    print(f"  not visited / unsupported: {other}")
    for where, count in totals.not_visited.most_common(top):
        print(f"      {where:<34} {count}")
    print(f"  unreconciled (residual):  {totals.unreconciled}")
    print(f"identity converted+refused+not_visited+unreconciled == total: {acc.check(accounting)}")
    if accounting.non_xml_matches:
        extra = ", ".join(f"{s}={n}" for s, n in accounting.non_xml_matches.most_common())
        print(f"informational, non-XML files (outside the universe): {extra}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="directory tree to scan (e.g. a corpus of module directories)")
    parser.add_argument("--json", dest="json_out", help="write the full accounting to this file")
    parser.add_argument("--top", type=int, default=20, help="rows per breakdown table")
    parser.add_argument("--module-context", action="store_true",
                        help="pass the run's module context (sibling module views) to the fixer")
    args = parser.parse_args(argv)
    accounting = acc.account_tree(args.root, ModuleViews() if args.module_context else None)
    _print(accounting, args.top)
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(acc.to_dict(accounting), indent=2, sort_keys=True) + "\n",
                                               encoding="utf-8")
    return 0 if acc.check(accounting) else 1


if __name__ == "__main__":
    sys.exit(main())

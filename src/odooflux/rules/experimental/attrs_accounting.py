"""Occurrence accounting for the experimental ``attrs`` fixer over a file tree (AF-8, roadmap WS7).

Every occurrence of an ``attrs`` view attribute is placed in exactly one bucket:

* ``converted``: the fixer converted the element (``Plan.converted``);
* ``refused``: the fixer refused it, keyed by reason (``Plan.refused``);
* ``not_visited``: the fixer never looks at it, keyed by where it sits (comment, CDATA section, processing
  instruction, DOCTYPE, attribute value, text content) or by the file being unparseable;
* ``unreconciled``: the residual ``candidates - converted - refused``. It is zero when the fixer visits every
  candidate the parser reports. A non-zero value is a defect to investigate, not an expected bucket.

Occurrence sites:

* (a) an ``attrs`` attribute on a parsed start tag;
* (b) an ``<attribute name="attrs">`` element (the inherited-view form handled by AF-6). A raw text match does not
  exist for it, so a regex-only count misses it;
* (c) a raw ``\\sattrs\\s*=`` text match that is not an (a) site. These are the occurrences a regex count sees and
  the fixer never does (comments, CDATA, attribute values, text).

A file the XML parser rejects has no structure: every raw match in it goes to ``not_visited["unparsed-file"]``, and
structural sites (b) are not counted for it.

The module is pure: it reads the documents it is given and writes nothing. ``account_tree`` reads files under a root
directory (``*.xml``, sorted, paths relative to the root) and is the only function that touches the file system.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.core.engine.documents import Document
from odooflux.parsers.xml import document as xmldoc
from odooflux.rules.experimental import xml_modifiers as xm

RAW_ATTRS = re.compile(r"\sattrs\s*=")
UNPARSED = "unparsed-file"
FIXER_ERROR = "fixer-error"
NON_XML_LIMIT = 5 * 1024 * 1024


@dataclass
class FileAccounting:
    path: str
    occurrences: int = 0
    converted: int = 0
    refused: Counter = field(default_factory=Counter)
    not_visited: Counter = field(default_factory=Counter)
    unreconciled: int = 0
    structural: int = 0  # candidate sites that are <attribute name="attrs"> (AF-6, inherited views)
    converted_structural: int = 0
    parse_error: str | None = None

    @property
    def bucket_sum(self) -> int:
        return self.converted + sum(self.refused.values()) + sum(self.not_visited.values()) + self.unreconciled

    def add(self, other: "FileAccounting") -> None:
        self.occurrences += other.occurrences
        self.converted += other.converted
        self.refused.update(other.refused)
        self.not_visited.update(other.not_visited)
        self.unreconciled += other.unreconciled
        self.structural += other.structural
        self.converted_structural += other.converted_structural


@dataclass
class Accounting:
    totals: FileAccounting = field(default_factory=lambda: FileAccounting(path="*"))
    files: list = field(default_factory=list)  # FileAccounting for every XML file with an occurrence or a parse error
    xml_files: int = 0
    parse_errors: list = field(default_factory=list)  # (path, error)
    non_xml_matches: Counter = field(default_factory=Counter)  # informational, outside the universe


def _location(xdoc, position: int) -> str:
    """Where a raw match that is not a parsed ``attrs`` attribute sits."""
    for span in xdoc.comments:
        if span.start <= position < span.end:
            return "in-comment"
    for span in xdoc.cdata_sections:
        if span.start <= position < span.end:
            return "in-cdata"
    for span in xdoc.processing_instructions:
        if span.start <= position < span.end:
            return "in-processing-instruction"
    if xdoc.doctype is not None and xdoc.doctype.start <= position < xdoc.doctype.end:
        return "in-doctype"
    for element in xdoc.elements:
        if element.start_tag_span.start <= position < element.start_tag_span.end:
            return "in-attribute-value"
    return "in-text"


def account_document(document: Document, views=None) -> FileAccounting:
    """Bucket every ``attrs`` occurrence of one document. Pure: the fixer is called with no edit context. ``views`` is
    the optional module context (``xml_modifiers.ModuleViews``) that a run would pass to the fixer."""
    acc = FileAccounting(path=document.path)
    raw_positions = [m.start() + 1 for m in RAW_ATTRS.finditer(document.text)]  # offset of the name "attrs"
    xdoc = xmldoc.parse(document)
    if xdoc.parse_error is not None:
        acc.parse_error = xdoc.parse_error
        acc.occurrences = len(raw_positions)
        acc.not_visited[UNPARSED] = len(raw_positions)
        return acc

    # One candidate per element, chosen as the fixer chooses (xm._candidate_start): the start-tag attrs attribute,
    # else an <attribute name="attrs"> element of an inherited view (site kind "structural").
    attr_sites = {element.get_attr("attrs").name_span.start
                  for element in xdoc.elements if element.get_attr("attrs") is not None}
    structural = [element for element in xdoc.elements
                  if element.get_attr("attrs") is None and element.tag == "attribute"
                  and element.get_attr("name") is not None and element.get_attr("name").value == "attrs"]
    candidates = len(attr_sites) + len(structural)
    acc.structural = len(structural)

    for position in raw_positions:
        if position not in attr_sites:
            acc.not_visited[_location(xdoc, position)] += 1
    acc.occurrences = candidates + sum(acc.not_visited.values())

    try:
        kwargs = {} if views is None else {"views": views}  # the default call stays exactly as it was
        plan = xm.plan_attrs(document, **kwargs)
    except Exception as exc:  # the fixer must not hide a file: every candidate in it is reported as not visited
        acc.not_visited[f"{FIXER_ERROR}:{type(exc).__name__}"] += candidates
        acc.unreconciled = 0
        return acc

    acc.converted = len(plan.converted)
    # The fixer records a structural (<attribute name="attrs">) site under its tag "attribute"; a start-tag site on
    # an element named "attribute" is refused "malformed-attribute" and is never converted, so this is exact.
    acc.converted_structural = sum(1 for conversion in plan.converted if conversion.element == "attribute")
    for refusal in plan.refused:
        acc.refused[refusal.reason] += 1
    acc.unreconciled = candidates - acc.converted - sum(acc.refused.values())
    return acc


def account_tree(root, views=None) -> Accounting:
    """Account every ``*.xml`` file under ``root`` (sorted by relative posix path) and count raw matches in other
    text files as an informational figure outside the universe. ``views`` (optional) is the module context; the
    fixer sees each file by its absolute path, so the module directories beside it can be found."""
    root = Path(root).resolve()
    result = Accounting()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        if path.suffix != ".xml":
            if len(raw) <= NON_XML_LIMIT and b"\0" not in raw:
                matches = len(RAW_ATTRS.findall(raw.decode("utf-8", errors="replace")))
                if matches:
                    result.non_xml_matches[path.suffix or "(none)"] += matches
            continue
        result.xml_files += 1
        per_file = account_document(Document.from_bytes(str(path), raw), views)
        if per_file.parse_error is not None:
            result.parse_errors.append((relative, per_file.parse_error))
        if per_file.occurrences or per_file.parse_error is not None:
            per_file.path = relative
            result.files.append(per_file)
        result.totals.add(per_file)
    return result


def check(accounting: Accounting) -> bool:
    """True when the buckets add up to the total and no residual is left."""
    totals = accounting.totals
    return totals.unreconciled == 0 and totals.bucket_sum == totals.occurrences


def to_dict(accounting: Accounting) -> dict:
    totals = accounting.totals
    return {
        "xml_files": accounting.xml_files,
        "occurrences": totals.occurrences,
        "converted": totals.converted,
        "refused": dict(sorted(totals.refused.items())),
        "refused_total": sum(totals.refused.values()),
        "not_visited": dict(sorted(totals.not_visited.items())),
        "not_visited_total": sum(totals.not_visited.values()),
        "unreconciled": totals.unreconciled,
        "structural_sites": totals.structural,
        "converted_structural": totals.converted_structural,
        "identity_holds": check(accounting),
        "parse_errors": [{"path": p, "error": e} for p, e in accounting.parse_errors],
        "non_xml_matches_informational": dict(sorted(accounting.non_xml_matches.items())),
        "files": [{"path": f.path, "occurrences": f.occurrences, "converted": f.converted,
                   "refused": dict(sorted(f.refused.items())), "not_visited": dict(sorted(f.not_visited.items())),
                   "unreconciled": f.unreconciled} for f in accounting.files],
    }

"""Security extractor (T049; REQ-KAP-011; diff-extractor contract, Domains and facts: security).

- `security/ir.model.access.csv`: one `access` fact per row, keyed by the row id. `attrs` hold name, model and group
  (signature); the permission columns are in `body_digest`, so a permission change is BEHAVIOUR_CHANGED.
- `security/*.xml` records of `ir.rule` (`rule`), `res.groups` (`group`) and `ir.model.access` (`access`): `attrs`
  hold the target model; `body_digest` is the canonical digest of all `field` children.

Other CSV files and other record models are `Unsupported`; a malformed CSV row is a `ParseFailure`.
"""

import csv
import hashlib
import io
import json
import os

from odooflux.knowledge.extract.domains import xml_views as xv
from odooflux.knowledge.extract.driver import ParseFailure, Unsupported

__all__ = ["SecurityExtractor", "EXTRACTORS"]

ACCESS_FILE = "ir.model.access.csv"
ACCESS_ATTRS = ("name", "model_id:id", "group_id:id")
XML_KINDS = {"ir.rule": "rule", "res.groups": "group", "ir.model.access": "access"}


def _digest_obj(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()


class SecurityExtractor:
    domain = "security"
    parser = "csv/xml"

    def handles(self, path: str, toolkit=None) -> bool:
        xml_ok = toolkit is not None and path.endswith(".xml")
        return "security" in path.split("/")[:-1] and (path.endswith(".csv") or xml_ok)

    def facts(self, text: str, path: str, toolkit=None) -> list:
        if path.endswith(".csv"):
            return self._csv_facts(text, path)
        return self._xml_facts(text, path, toolkit)

    def _csv_facts(self, text: str, path: str) -> list:
        name = os.path.basename(path)
        if name != ACCESS_FILE:
            raise Unsupported(f"security csv {name} is not modelled")
        reader = csv.reader(io.StringIO(text, newline=""))
        try:
            header = next(reader)
        except StopIteration:
            raise ParseFailure("PARSE_ERROR", "empty access csv") from None
        except csv.Error as exc:
            raise ParseFailure("PARSE_ERROR", str(exc)) from exc
        if "id" not in header:
            raise ParseFailure("PARSE_ERROR", "access csv has no id column")
        out = []
        try:
            for row in reader:
                if not row or not any(cell.strip() for cell in row):
                    continue
                if len(row) != len(header):
                    raise ParseFailure("PARSE_ERROR", f"line {reader.line_num}: {len(row)} fields, "
                                                      f"expected {len(header)}")
                values = dict(zip(header, row))
                if not values["id"]:
                    raise ParseFailure("PARSE_ERROR", f"line {reader.line_num}: empty id")
                perms = sorted((k, v) for k, v in values.items() if k != "id" and k not in ACCESS_ATTRS)
                attrs = {"name": values.get("name"), "model": values.get("model_id:id"),
                         "group": values.get("group_id:id")}
                out.append(xv.fact(values["id"], "access", attrs, _digest_obj(perms), reader.line_num))
        except csv.Error as exc:
            raise ParseFailure("PARSE_ERROR", f"line {reader.line_num}: {exc}") from exc
        return out

    def _xml_facts(self, text: str, path: str, toolkit=None) -> list:
        doc = xv.parse_or_fail(text, path, toolkit)
        xv.top_level_check(doc)
        out = []
        for record in xv.find(doc, tag="record"):
            model = xv.attr_value(record, "model")
            kind = XML_KINDS.get(model)
            if kind is None:
                raise Unsupported(f"record of model {model} at line {xv.line_of(doc, record)} is not modelled")
            record_id = xv.attr_value(record, "id")
            if not record_id:
                raise ParseFailure("PARSE_ERROR", f"record at line {xv.line_of(doc, record)} has no id")
            fields = {}
            for item in xv.child_fields(doc, record):
                fields[xv.attr_value(item, "name")] = xv.canon(xv.fragment(doc, item))
            target = xv.field_named(doc, record, "model_id") or xv.field_named(doc, record, "model")
            target_name = None
            if target is not None:
                target_name = xv.ref_of(target) or xv.text_of(doc, target)
            out.append(xv.fact(record_id, kind, {"model": target_name}, _digest_obj(fields),
                               xv.line_of(doc, record)))
        return out


EXTRACTORS = (SecurityExtractor(),)

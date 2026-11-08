"""Data (CSV) extractor (T050; REQ-KAP-011; diff-extractor contract, Domains and facts: data).

Handles `.csv` files under a `data/` directory (security CSVs belong to the security extractor). The model is the
file name without `.csv`, as in Odoo's CSV loader. One `record` fact per row, keyed `model::id`; the other columns
are in `body_digest`, so a changed row is BEHAVIOUR_CHANGED. A missing id column or a malformed row is a ParseFailure.
"""

import csv
import hashlib
import io
import json
import os

from odooflux.knowledge.extract.driver import ParseFailure
from odooflux.knowledge.extract.domains.xml_views import fact

__all__ = ["DataExtractor", "EXTRACTORS"]


class DataExtractor:
    domain = "data"
    parser = "csv"

    def handles(self, path: str, toolkit=None) -> bool:
        parts = path.split("/")[:-1]
        return path.endswith(".csv") and "data" in parts and "security" not in parts

    def facts(self, text: str, path: str, toolkit=None) -> list:
        model = os.path.basename(path)[: -len(".csv")]
        reader = csv.reader(io.StringIO(text, newline=""))
        try:
            header = next(reader)
        except StopIteration:
            raise ParseFailure("PARSE_ERROR", "empty data csv") from None
        except csv.Error as exc:
            raise ParseFailure("PARSE_ERROR", str(exc)) from exc
        if "id" not in header:
            raise ParseFailure("PARSE_ERROR", "data csv has no id column")
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
                cells = json.dumps(sorted((k, v) for k, v in values.items() if k != "id"))
                digest = hashlib.sha256(cells.encode("utf-8")).hexdigest()
                out.append(fact(f"{model}::{values['id']}", "record", {}, digest, reader.line_num))
        except csv.Error as exc:
            raise ParseFailure("PARSE_ERROR", f"line {reader.line_num}: {exc}") from exc
        return out


EXTRACTORS = (DataExtractor(),)

"""TST-006-035 (REQ-PY-002): analysing a module of at least 50 files with the legacy tables and every bound
metadata rule takes under 10 seconds.

No golden module of that size exists yet (the golden trees are human reviewed), so the module is generated
here: Python models, views, ACL CSV, JavaScript and a manifest, with constructs that the rules report."""

import tempfile
import time
import unittest
from pathlib import Path

from odooflux.builtins import build_registries
from odooflux.core.engine.documents import Document
from odooflux.core.orchestrator.module_plan import plan_module
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import BindingError, bind_rule

from ..unit import _setup  # noqa: F401  (src first on sys.path)

BUDGET_SECONDS = 10.0
MIN_FILES = 50
KINDS = {".py": "python", ".xml": "xml", ".csv": "csv", ".js": "javascript"}


def build_module(root: Path, models: int = 16) -> int:
    (root / "models").mkdir(parents=True)
    (root / "views").mkdir()
    (root / "security").mkdir()
    (root / "static" / "src" / "js").mkdir(parents=True)
    data = ["security/ir.model.access.csv"]
    (root / "models" / "__init__.py").write_text("".join(f"from . import m{i}\n" for i in range(models)))
    (root / "__init__.py").write_text("from . import models\n")
    access = ["id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink"]
    for i in range(models):
        (root / "models" / f"m{i}.py").write_text(
            "from odoo import api, fields, models\n\n\n"
            f"class M{i}(models.Model):\n    _name = 'perf.m{i}'\n    name = fields.Char(size=64)\n"
            "    total = fields.Float(compute='_total')\n\n"
            "    @api.multi\n    @api.depends('name')\n    def _total(self):\n"
            "        for rec in self:\n            rec.total = len(rec.name or '')\n\n"
            "    def write(self, vals):\n        return super().write(vals)\n\n"
            "    def name_get(self):\n        return [(r.id, r.name) for r in self.sudo()]\n")
        (root / "views" / f"v{i}.xml").write_text(
            '<odoo>\n  <record id="v%d" model="ir.ui.view">\n    <field name="name">v%d</field>\n'
            '    <field name="model">perf.m%d</field>\n    <field name="arch" type="xml">\n'
            '      <tree><field name="name" attrs="{\'invisible\': [(\'name\', \'=\', False)]}"/></tree>\n'
            '    </field>\n  </record>\n</odoo>\n' % (i, i, i))
        (root / "static" / "src" / "js" / f"a{i}.js").write_text(
            '/** @odoo-module **/\nimport { useService } from "@web/core/utils/hooks";\n'
            'export function setup() { return useService("rpc"); }\n')
        access.append(f"a{i},a{i},model_perf_m{i},,1,1,1,1")
        data.append(f"views/v{i}.xml")
    (root / "security" / "ir.model.access.csv").write_text("\n".join(access) + "\n")
    (root / "__manifest__.py").write_text(repr(
        {"name": "perf", "version": "14.0.1.0.0", "depends": ["base"], "data": data, "installable": True}))
    return sum(1 for p in root.rglob("*") if p.is_file())


def bound_rules() -> list:
    rules = []
    for meta in load_knowledge().rules:
        try:
            rules.append((meta, bind_rule(meta, BINDABLE_MODULES)))
        except BindingError:
            continue
    return rules


class RulesPerfTests(unittest.TestCase):
    def test_module_of_fifty_files_is_analysed_in_under_ten_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "perf"
            files = build_module(root)
            self.assertGreaterEqual(files, MIN_FILES)
            rules = bound_rules()
            start = time.perf_counter()
            analysis, _edits = plan_module(root, 14, 19, build_registries(), compute_edits=False)
            findings = 0
            for path in sorted(root.rglob("*")):
                kind = "manifest" if path.name == "__manifest__.py" else KINDS.get(path.suffix)
                if not path.is_file() or kind is None:
                    continue
                document = Document.from_bytes(str(path), path.read_bytes())
                for meta, rule in rules:
                    if kind in meta.get("file_kinds", []):
                        findings += len(rule.detect(document))
            elapsed = time.perf_counter() - start
        self.assertGreater(len(analysis.issues), 0)
        self.assertGreater(findings, 0)
        self.assertLess(elapsed, BUDGET_SECONDS, f"{files} files took {elapsed:.2f}s")
        print(f"rules perf: {files} files, {len(rules)} bound rules, {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()

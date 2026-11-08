"""Generate N synthetic Odoo modules with a fixed seed (R-09). Each module has ~30 files:
models, views, a manifest, a JS file, and an ACL. Usage: python generate_repo.py OUT [N] [SEED]."""

import random
import sys
from pathlib import Path

MODEL = '''# -*- coding: utf-8 -*-
from odoo import models, fields, api


class {cls}(models.Model):
    _name = '{name}.model{idx}'
    _description = 'Generated {idx}'

    name = fields.Char(string='Name {idx}', size={size})
    amount = fields.Float(string='Amount')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')

    @api.multi
    def action_{idx}(self):
        return True
'''

VIEW = '''<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_{name}_{idx}_form" model="ir.ui.view">
        <field name="name">{name}.{idx}.form</field>
        <field name="model">{name}.model{idx}</field>
        <field name="arch" type="xml">
            <form>
                <group>
                    <field name="name"/>
                    <field name="amount"/>
                </group>
            </form>
        </field>
    </record>
</odoo>
'''

MANIFEST = '''# -*- coding: utf-8 -*-
{{
    'name': 'Generated {name}',
    'version': '14.0.1.0.0',
    'depends': ['base'],
    'data': [{data}],
    'installable': True,
}}
'''

JS = "odoo.define('{name}.widget{idx}', function (require) {{\n    var Widget = require('web.Widget');\n    return Widget.extend({{}});\n}});\n"


def generate(out: Path, modules: int = 300, seed: int = 20260106) -> list:
    rng = random.Random(seed)
    created = []
    for n in range(modules):
        name = f"gen_mod_{n:03d}"
        root = out / name
        (root / "models").mkdir(parents=True, exist_ok=True)
        (root / "views").mkdir(exist_ok=True)
        (root / "static" / "src" / "js").mkdir(parents=True, exist_ok=True)
        (root / "security").mkdir(exist_ok=True)
        data = []
        for idx in range(10):
            size = rng.choice([16, 32, 64, 128])
            (root / "models" / f"m{idx}.py").write_text(
                MODEL.format(cls=f"M{n}x{idx}", name=name, idx=idx, size=size), encoding="utf-8")
            (root / "views" / f"v{idx}.xml").write_text(
                VIEW.format(name=name, idx=idx), encoding="utf-8")
            data.append(f"'views/v{idx}.xml'")
        for idx in range(8):
            (root / "static" / "src" / "js" / f"w{idx}.js").write_text(
                JS.format(name=name, idx=idx), encoding="utf-8")
        (root / "security" / "ir.model.access.csv").write_text(
            "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
            f"access_{name},{name},model_{name},base.group_user,1,1,1,0\n", encoding="utf-8")
        (root / "__manifest__.py").write_text(MANIFEST.format(name=name, data=", ".join(data)), encoding="utf-8")
        created.append(root)
    return created


if __name__ == "__main__":
    target = Path(sys.argv[1])
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 20260106
    target.mkdir(parents=True, exist_ok=True)
    print(f"generated {len(generate(target, count, seed))} modules in {target}")

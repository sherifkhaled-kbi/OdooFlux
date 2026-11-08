"""Deterministic benchmark corpus (T001, REQ-PRF-001; contracts/benchmark-protocol.md).

``python tests/benchmarks/corpus_gen.py OUT --seed 1 --modules 300 --files-per-module 30`` writes a corpus of
synthetic Odoo 14.0 modules. Every file is derived from the golden fixture ``p0_kbi_demo_v14`` by renaming; the only
randomness comes from ``random.Random(seed)``, so a seed fixes every byte. No customer code is used.

Layout per module (30 files): ``__manifest__.py``, ``__init__.py``, ``models/__init__.py``, 9 models, 9 views,
``data/data.xml``, 7 JavaScript files and one ACL CSV.
"""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

DEFAULT_SEED = 1
DEFAULT_MODULES = 300
DEFAULT_FILES_PER_MODULE = 30
MODELS = 9
VIEWS = 9
JS_FILES = 7
FIXED_FILES = 5  # manifest, __init__, models/__init__, data.xml, ACL

_FIXTURE = Path(__file__).resolve().parents[1] / "golden_fixtures" / "p0_kbi_demo_v14"
TEMPLATE_SOURCES = (_FIXTURE / "models" / "demo.py", _FIXTURE / "views" / "demo_views.xml",
                    _FIXTURE / "static" / "src" / "js" / "demo.js",
                    _FIXTURE / "security" / "ir.model.access.csv")

DATA_XML = '''<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <record id="{name}_seed_{idx}" model="ir.config_parameter">
            <field name="key">{name}.setting{idx}</field>
            <field name="value">{value}</field>
        </record>
    </data>
</odoo>
'''

MANIFEST = """# -*- coding: utf-8 -*-
{{
    'name': 'Generated {name}',
    'version': '14.0.1.0.{patch}',
    'summary': 'Synthetic benchmark module {name}',
    'depends': ['base'],
    'data': [{data}],
    'installable': True,
}}
"""


def planned_file_count(modules: int, files_per_module: int) -> int:
    return modules * files_per_module


def _templates() -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in TEMPLATE_SOURCES}


def _model(template: str, name: str, n: int, idx: int, rng: random.Random) -> str:
    text = (template.replace("kbi.demo", f"{name}.m{idx}").replace("KbiDemo", f"Gen{n}x{idx}")
            .replace("KBI Demo", f"Generated {name} {idx}"))
    text = text.replace("size=64", f"size={rng.choice([16, 32, 64, 128])}")
    if rng.random() < 0.5:
        text += f"\n    amount_{idx} = fields.Float(string='Amount {idx}')\n"
    return text


def _view(template: str, name: str, idx: int) -> str:
    return (template.replace("kbi_demo", f"{name}_{idx}").replace("kbi.demo", f"{name}.m{idx}")
            .replace("KBI Demo", f"Generated {name} {idx}"))


def _js(template: str, name: str, idx: int) -> str:
    return template.replace("kbi_demo.demo", f"{name}.w{idx}").replace("kbi_demo", name).replace(
        "KbiDemoWidget", f"Gen{idx}Widget").replace("/data", f"/data{idx}")


def digest_files(files) -> str:
    """SHA-256 over sorted ``relative path NUL sha256`` lines of ``(relative, bytes)`` pairs."""
    outer = hashlib.sha256()
    for rel, data in sorted(files):
        outer.update(f"{rel}\0{hashlib.sha256(data).hexdigest()}\n".encode("utf-8"))
    return outer.hexdigest()


def corpus_digest(root: Path) -> str:
    root = Path(root)
    return digest_files((p.relative_to(root).as_posix(), p.read_bytes()) for p in root.rglob("*") if p.is_file())


def generate(out: Path, modules: int = DEFAULT_MODULES, files_per_module: int = DEFAULT_FILES_PER_MODULE,
             seed: int = DEFAULT_SEED) -> dict:
    """Write the corpus to *out*. Returns ``{corpus_id, seed, modules, files, digest}``."""
    if files_per_module != MODELS + VIEWS + JS_FILES + FIXED_FILES:
        raise ValueError(f"files_per_module must be {MODELS + VIEWS + JS_FILES + FIXED_FILES} for this layout")
    out = Path(out)
    rng = random.Random(seed)
    tpl = _templates()
    model_tpl, view_tpl = tpl["demo.py"], tpl["demo_views.xml"]
    js_tpl, acl_tpl = tpl["demo.js"], tpl["ir.model.access.csv"]
    files = []
    for n in range(modules):
        name = f"gen_mod_{n:03d}"
        content = {"__init__.py": "from . import models\n"}
        names = [f"m{i}" for i in range(MODELS)]
        content["models/__init__.py"] = "".join(f"from . import {m}\n" for m in names)
        for i in range(MODELS):
            content[f"models/m{i}.py"] = _model(model_tpl, name, n, i, rng)
        data = []
        for i in range(VIEWS):
            content[f"views/v{i}.xml"] = _view(view_tpl, name, i)
            data.append(f"'views/v{i}.xml'")
        content["data/data.xml"] = DATA_XML.format(name=name, idx=0, value=rng.randint(0, 10 ** 6))
        data.append("'data/data.xml'")
        for i in range(JS_FILES):
            content[f"static/src/js/w{i}.js"] = _js(js_tpl, name, i)
        content["security/ir.model.access.csv"] = acl_tpl.replace("kbi_demo_user", f"{name}_user").replace(
            "kbi.demo", name).replace("model_kbi_demo", f"model_{name}_m0")
        data.append("'security/ir.model.access.csv'")
        content["__manifest__.py"] = MANIFEST.format(name=name, patch=rng.randint(0, 9), data=", ".join(data))
        for rel, text in content.items():
            target = out / name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            data_bytes = text.encode("utf-8")
            target.write_bytes(data_bytes)
            files.append((f"{name}/{rel}", data_bytes))
    return {"corpus_id": f"synthetic-seed{seed}-m{modules}x{files_per_module}", "seed": seed, "modules": modules,
            "files": len(files), "digest": digest_files(files)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate the deterministic benchmark corpus")
    parser.add_argument("out")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--modules", type=int, default=DEFAULT_MODULES)
    parser.add_argument("--files-per-module", type=int, default=DEFAULT_FILES_PER_MODULE)
    args = parser.parse_args(argv)
    info = generate(Path(args.out), args.modules, args.files_per_module, args.seed)
    print(json.dumps(info, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Deterministic synthetic Odoo addon repository for feature 011 tests.

Builds a git repository in a caller-supplied empty directory using git plumbing
only (hash-object, update-index, write-tree, commit-tree, update-ref). No network,
no working-tree checkout, no user configuration: author, committer, dates and
environment are fixed, so commit SHAs are identical across runs.

The version pair 16.0 -> 17.0 has two commits (one per version, branches
``16.0`` and ``17.0``, ``HEAD`` on ``17.0``). Known changes are listed in
``EXPECTED_CHANGES`` and are encoded in the file contents below.
"""

import copy
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ADDON = "addons/sale_demo"

_AUTHOR_NAME = "KAP Synthetic"
_AUTHOR_EMAIL = "synthetic@example.invalid"
_DATES = {"16.0": "1700000000 +0000", "17.0": "1710000000 +0000"}
_MESSAGES = {"16.0": "Synthetic 16.0 baseline", "17.0": "Synthetic 17.0 target"}

_MANIFEST_16 = """{
    'name': 'Sale Demo',
    'version': '16.0.1.0.0',
    'category': 'Sales',
    'depends': ['base', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/sale_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sale_demo/static/src/js/demo_widget.js',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
}
"""

_MANIFEST_17 = _MANIFEST_16.replace("'16.0.1.0.0'", "'17.0.1.0.0'").replace(
    "'depends': ['base', 'sale'],", "'depends': ['base', 'sale', 'account'],"
)

_SALE_ORDER_16 = '''from odoo import api, fields, models


class SaleDemoOrder(models.Model):
    _name = 'sale.demo.order'
    _description = 'Sale Demo Order'

    name = fields.Char(string='Name')
    amount = fields.Float(string='Amount')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')

    def compute_total(self, tax=0.0):
        return self.amount * (1.0 + tax)

    def check_amount(self):
        return self.amount > 0

    def compute_legacy_total(self):
        return self.amount

    def get_amount_old(self):
        """Return the amount."""
        return self.amount
'''

_SALE_ORDER_17 = '''import warnings

from odoo import api, fields, models


class SaleDemoOrder(models.Model):
    _name = 'sale.demo.order'
    _description = 'Sale Demo Order'

    name = fields.Char(string='Name')
    amount = fields.Float(string='Amount')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    priority = fields.Integer(string='Priority', default=0)

    def compute_total(self, tax=0.0, currency=None):
        return self.amount * (1.0 + tax)

    def check_amount(self):
        return self.amount >= 0

    def compute_legacy_total(self):
        warnings.warn('compute_legacy_total is deprecated', DeprecationWarning)
        return self.amount

    def get_amount(self):
        """Return the amount.

        .. versionchanged:: 17.0
           Replaces ``get_amount_old``.
        """
        return self.amount
'''

_UTILS = '''def format_reference(prefix, number):
    return '%s-%05d' % (prefix, number)
'''

_BROKEN_17 = '''from odoo import models


class BrokenHooks(models.AbstractModel):
    _name = 'sale.demo.broken.hooks'

    def hook(self:
        return None
'''

_VIEW_16 = '''<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_sale_demo_form" model="ir.ui.view">
        <field name="name">sale.demo.order.form</field>
        <field name="model">sale.demo.order</field>
        <field name="arch" type="xml">
            <form>
                <sheet>
                    <field name="name"/>
                    <field name="amount"/>
                </sheet>
            </form>
        </field>
    </record>
</odoo>
'''

_VIEW_17 = _VIEW_16.replace(
    '                    <field name="amount"/>\n',
    '                    <field name="amount"/>\n                    <field name="priority"/>\n',
)

_ACL_HEADER = "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
_ACL_USER = "access_sale_demo_order_user,sale.demo.order user,model_sale_demo_order,base.group_user,1,0,0,0\n"
_ACL_MANAGER = "access_sale_demo_order_manager,sale.demo.order manager,model_sale_demo_order,base.group_system,1,1,1,1\n"

_JS_16 = '''/** @odoo-module **/

export const DemoWidget = {
    name: "demo_widget",
    render() {
        return "demo";
    },
};
'''

_JS_17 = _JS_16 + '''
export const DemoBadge = {
    name: "demo_badge",
};
'''

_MIGRATE_17 = '''def migrate(cr, version):
    cr.execute("UPDATE sale_demo_order SET priority = 0 WHERE priority IS NULL")
'''

_MODELS_INIT_16 = "from . import sale_order\nfrom . import legacy_utils\n"
_MODELS_INIT_17 = "from . import sale_order\nfrom . import sale_utils\n"
_ADDON_INIT = "from . import models\n"

_ADDON_INIT_PATH = f"{ADDON}/__init__.py"

_TREE_16 = {
    f"{ADDON}/__init__.py": _ADDON_INIT,
    f"{ADDON}/__manifest__.py": _MANIFEST_16,
    f"{ADDON}/models/__init__.py": _MODELS_INIT_16,
    f"{ADDON}/models/sale_order.py": _SALE_ORDER_16,
    f"{ADDON}/models/legacy_utils.py": _UTILS,
    f"{ADDON}/views/sale_views.xml": _VIEW_16,
    f"{ADDON}/security/ir.model.access.csv": _ACL_HEADER + _ACL_USER,
    f"{ADDON}/static/src/js/demo_widget.js": _JS_16,
}

_TREE_17 = {
    f"{ADDON}/__init__.py": _ADDON_INIT,
    f"{ADDON}/__manifest__.py": _MANIFEST_17,
    f"{ADDON}/models/__init__.py": _MODELS_INIT_17,
    f"{ADDON}/models/sale_order.py": _SALE_ORDER_17,
    f"{ADDON}/models/sale_utils.py": _UTILS,
    f"{ADDON}/models/broken_hooks.py": _BROKEN_17,
    f"{ADDON}/views/sale_views.xml": _VIEW_17,
    f"{ADDON}/security/ir.model.access.csv": _ACL_HEADER + _ACL_USER + _ACL_MANAGER,
    f"{ADDON}/static/src/js/demo_widget.js": _JS_17,
    f"{ADDON}/migrations/17.0.1.0.0/post-migrate.py": _MIGRATE_17,
}

# Known changes between 16.0 and 17.0. ``kind`` is the git-level change;
# ``class_hint`` is the diff-extractor class where the contract defines one.
EXPECTED_CHANGES = (
    {"file_change": "M", "kind": "modified", "path": f"{ADDON}/__manifest__.py", "domain": "manifest",
     "subject": "version", "detail": "16.0.1.0.0 -> 17.0.1.0.0", "class_hint": None},
    {"file_change": "M", "kind": "modified", "path": f"{ADDON}/__manifest__.py", "domain": "manifest",
     "subject": "depends", "detail": "adds 'account'", "class_hint": None},
    {"file_change": "M", "kind": "added", "path": f"{ADDON}/models/sale_order.py", "domain": "python_orm",
     "subject": "sale.demo.order.priority", "detail": "field priority added", "class_hint": "ADDED"},
    {"file_change": "M", "kind": "modified", "path": f"{ADDON}/models/sale_order.py", "domain": "python_orm",
     "subject": "sale.demo.order.compute_total", "detail": "signature gains currency=None",
     "class_hint": "SIGNATURE_CHANGED"},
    {"file_change": "M", "kind": "modified", "path": f"{ADDON}/models/sale_order.py", "domain": "python_orm",
     "subject": "sale.demo.order.check_amount", "detail": "body '> 0' -> '>= 0'",
     "class_hint": "BEHAVIOUR_CHANGED"},
    {"file_change": "M", "kind": "modified", "path": f"{ADDON}/models/sale_order.py", "domain": "python_orm",
     "subject": "sale.demo.order.compute_legacy_total", "detail": "warnings.warn(DeprecationWarning) added",
     "class_hint": "DEPRECATED"},
    {"file_change": "M", "kind": "removed", "path": f"{ADDON}/models/sale_order.py", "domain": "python_orm",
     "subject": "sale.demo.order.get_amount_old", "detail": "method removed; replaced by get_amount",
     "class_hint": "REPLACEMENT_CANDIDATE"},
    {"file_change": "M", "kind": "added", "path": f"{ADDON}/models/sale_order.py", "domain": "python_orm",
     "subject": "sale.demo.order.get_amount", "detail": "method added; documented as replacing get_amount_old",
     "class_hint": "REPLACEMENT_CANDIDATE"},
    {"file_change": "R", "kind": "rename", "path": f"{ADDON}/models/sale_utils.py", "old_path": f"{ADDON}/models/legacy_utils.py",
     "domain": "python_orm", "subject": "format_reference", "detail": "identical content, renamed",
     "class_hint": "MOVED"},
    {"file_change": "A", "kind": "unparsable", "path": f"{ADDON}/models/broken_hooks.py", "domain": "python_orm",
     "subject": f"{ADDON}/models/broken_hooks.py", "detail": "syntax error; must surface as FAILED:PARSE_ERROR",
     "class_hint": "UNKNOWN"},
    {"file_change": "M", "kind": "modified", "path": f"{ADDON}/views/sale_views.xml", "domain": "xml_view",
     "subject": "view_sale_demo_form", "detail": "arch gains <field name=\"priority\"/>",
     "class_hint": "BEHAVIOUR_CHANGED"},
    {"file_change": "M", "kind": "modified", "path": f"{ADDON}/security/ir.model.access.csv", "domain": "security",
     "subject": "access_sale_demo_order_manager", "detail": "access row added", "class_hint": "ADDED"},
    {"file_change": "M", "kind": "modified", "path": f"{ADDON}/static/src/js/demo_widget.js", "domain": "js_owl",
     "subject": "DemoBadge", "detail": "export added", "class_hint": "ADDED"},
    {"file_change": "A", "kind": "added", "path": f"{ADDON}/migrations/17.0.1.0.0/post-migrate.py", "domain": "migration_script",
     "subject": "migrate", "detail": "post-migrate script references sale_demo_order", "class_hint": "ADDED"},
)


@dataclass
class SynthRepo:
    path: str
    from_ref: str
    to_ref: str
    from_sha: str
    to_sha: str
    expected_changes: list = field(default_factory=list)


def _git_env(home: Path, template: Path, date: str) -> dict:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TEMPLATE_DIR": str(template),
        "LC_ALL": "C",
        "GIT_AUTHOR_NAME": _AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": _AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": _AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": _AUTHOR_EMAIL,
    }
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    return env


def _run(args, env, git_dir, input_bytes=None):
    result = subprocess.run(
        ["git", "--git-dir", str(git_dir), *args],
        env=env, input=input_bytes, capture_output=True, check=True,
    )
    return result.stdout.decode("utf-8").strip()


def _write_tree(git_dir: Path, env: dict, files: dict) -> str:
    index = git_dir / "synth-index"
    tree_env = dict(env, GIT_INDEX_FILE=str(index))
    _run(["read-tree", "--empty"], tree_env, git_dir)
    lines = []
    for path in sorted(files):
        blob = _run(["hash-object", "-w", "--stdin"], env, git_dir,
                    input_bytes=files[path].encode("utf-8"))
        lines.append(f"100644 {blob}\t{path}\n")
    _run(["update-index", "--index-info"], tree_env, git_dir, input_bytes="".join(lines).encode("utf-8"))
    tree = _run(["write-tree"], tree_env, git_dir)
    index.unlink()
    return tree


def build_synth_repo(dest) -> SynthRepo:
    """Build the synthetic 16.0 -> 17.0 repository in ``dest`` (must be empty or absent).

    Raises RuntimeError when git is not installed.
    """
    if shutil.which("git") is None:
        raise RuntimeError("git is not installed; cannot build the synthetic repository")
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"destination must be empty: {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    # Isolated home and template dir: no user config, hooks or templates leak in.
    scratch = Path(tempfile.mkdtemp(prefix="kap-synth-"))
    try:
        home = scratch / "home"
        template = scratch / "template"
        home.mkdir()
        template.mkdir()
        init_env = _git_env(home, template, "")
        subprocess.run(["git", "init", "-q", str(dest)], env=init_env, check=True, capture_output=True)
        git_dir = dest / ".git"

        parent = None
        shas = {}
        for version, files in (("16.0", _TREE_16), ("17.0", _TREE_17)):
            env = _git_env(home, template, _DATES[version])
            tree = _write_tree(git_dir, env, files)
            args = ["commit-tree", tree, "-m", _MESSAGES[version]]
            if parent:
                args += ["-p", parent]
            sha = _run(args, env, git_dir)
            _run(["update-ref", f"refs/heads/{version}", sha], env, git_dir)
            shas[version] = sha
            parent = sha

        _run(["symbolic-ref", "HEAD", "refs/heads/17.0"], init_env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    return SynthRepo(
        path=str(dest),
        from_ref="16.0",
        to_ref="17.0",
        from_sha=shas["16.0"],
        to_sha=shas["17.0"],
        expected_changes=copy.deepcopy(list(EXPECTED_CHANGES)),
    )

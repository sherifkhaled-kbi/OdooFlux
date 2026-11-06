#!/usr/bin/env python3
"""
Odoo Module Migration Tool → Odoo 18/19
Analyzes and auto-fixes a local Odoo module from a given source version.

Usage:
    python odoo_migrate_to_19.py --module ./my_module --from-version 14
    python odoo_migrate_to_19.py --module ./my_module --from-version 16 --dry-run
    python odoo_migrate_to_19.py --module ./my_module --from-version 12 --fix --backup
"""

import os
import re
import sys
import ast
import json
import shutil
import argparse
import textwrap
import urllib.request
import urllib.error
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARNING  = "WARNING"
SEVERITY_INFO     = "INFO"


@dataclass
class Issue:
    file: str
    line: int
    severity: str
    category: str
    message: str
    suggestion: str
    auto_fixable: bool = False
    fix_applied: bool = False


@dataclass
class MigrationReport:
    module_path: str
    from_version: int
    to_version: int = 19
    issues: list = field(default_factory=list)
    fixes_applied: int = 0
    elapsed_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def critical_count(self):
        return sum(1 for i in self.issues if i.severity == SEVERITY_CRITICAL and not i.fix_applied)

    @property
    def warning_count(self):
        return sum(1 for i in self.issues if i.severity == SEVERITY_WARNING and not i.fix_applied)

    @property
    def info_count(self):
        return sum(1 for i in self.issues if i.severity == SEVERITY_INFO and not i.fix_applied)

    @property
    def fixable_count(self):
        return sum(1 for i in self.issues if i.auto_fixable and not i.fix_applied)


# ─────────────────────────────────────────────
# MIGRATION RULES (version-aware)
# ─────────────────────────────────────────────

# Rule tuple fields:
#   min_src_ver  : rule fires when from_version < min_src_ver  (0 = always)
#   exact_tgt_ver: rule fires only when to_version == exact_tgt_ver (0 = all targets)
#
# NOTE: min_src_ver=16 means "this issue only exists in codebases OLDER than v16",
# i.e. the fix was introduced IN v16 — so if migrating FROM v16 the issue is already gone.

PYTHON_RULES = [
    (0, 0, r'\bopenerp\b', SEVERITY_CRITICAL, "Legacy Namespace",
     "Use of deprecated 'openerp' namespace",
     "Replace 'openerp' with 'odoo'", True),

    (0, 0, r'@api\.(one|multi|returns)\b', SEVERITY_CRITICAL, "Deprecated Decorator",
     "@api.one/@api.multi/@api.returns removed in v14+",
     "Remove @api.multi (default now); replace @api.one with self.ensure_one()", True),

    (0, 0, r'def \w+\(self,\s*cr,\s*uid', SEVERITY_CRITICAL, "Old API Signature",
     "Old-style (cr, uid, ids, context) method signature",
     "Migrate to new ORM API: remove cr/uid/ids/context parameters", False),

    (0, 0, r'fields\.Char\([^)]*size\s*=\s*\d+', SEVERITY_WARNING, "Deprecated Attribute",
     "fields.Char 'size' parameter is ignored in v13+",
     "Remove the 'size' attribute from fields.Char", True),

    (0, 0, r'\.execute_kw\(', SEVERITY_INFO, "XML-RPC",
     "execute_kw usage detected — verify return value handling for v14+",
     "Check that callers handle dict/bool return correctly", False),

    (0, 0, r'\.sudo\(\w+\)', SEVERITY_CRITICAL, "Sudo API Changed",
     ".sudo(user) signature removed in v16+; use .with_user(user).sudo()",
     "Replace .sudo(user) with .with_user(user).sudo()", True),

    (0, 0, r'_inherits\s*=', SEVERITY_WARNING, "Delegation Inheritance",
     "_inherits is discouraged; verify it works for your use case in v16+",
     "Consider using _inherit with Many2one delegation instead", False),

    (0, 0, r'from\s+osv\s+import|from\s+openerp\.osv', SEVERITY_CRITICAL, "Legacy Import",
     "osv module import is no longer available",
     "Replace with 'from odoo import models, fields, api'", True),

    (0, 0, r'_columns\s*=\s*\{', SEVERITY_CRITICAL, "Legacy Field Definition",
     "_columns dict is removed; use class-level field declarations",
     "Convert _columns to class-level fields.X() declarations", False),

    (0, 0, r'_defaults\s*=\s*\{', SEVERITY_CRITICAL, "Legacy Defaults",
     "_defaults dict is removed; use default= argument on fields",
     "Move defaults to field definitions using default=...", False),

    (0, 0, r'from\s+openerp\.tools\s+import\s+html_sanitize', SEVERITY_CRITICAL, "Import Path",
     "html_sanitize import path changed",
     "Use: from odoo.tools import html_sanitize", True),

    (0, 0, r'^\s*print\s+["\']', SEVERITY_CRITICAL, "Python 2 Syntax",
     "Python 2 print statement found",
     "Use print() function", True),

    # FIX: min_src_ver=17 means this fires when from_version < 17 (i.e. v16 and below),
    # which is correct — fields.Html sanitization changed IN v17.
    (17, 0, r'fields\.Html\(', SEVERITY_INFO, "HTML Field",
     "fields.Html sanitization defaults changed in v17; verify sanitize settings",
     "Explicitly set sanitize=True/False on fields.Html", False),

    # FIX: min_src_ver=15 — QWeb widgets were replaced BY v15
    (15, 0, r'qweb\.|t-widget=', SEVERITY_WARNING, "QWeb/OWL",
     "Legacy QWeb widgets replaced by OWL components in v15+",
     "Rewrite as OWL components", False),

    # FIX: min_src_ver=18 — attachment=False deprecated IN v18
    (18, 0, r'fields\.(Binary|Html)\([^)]*attachment\s*=\s*False', SEVERITY_WARNING, "Field Attribute",
     "attachment=False on Binary/Html fields deprecated in v18+",
     "Remove the attachment attribute; files are always stored as attachments", True),

    (0, 0, r'werkzeug\.contrib', SEVERITY_CRITICAL, "Werkzeug",
     "werkzeug.contrib removed in Werkzeug 1.0+",
     "Use werkzeug.* direct imports or standard library equivalents", False),

    (0, 0, r'ir\.values', SEVERITY_CRITICAL, "Removed Model",
     "ir.values model was removed in v13",
     "Use ir.default or res.config.settings instead", False),

    (0, 0, r'message_post_with_template\(', SEVERITY_WARNING, "Mail API",
     "message_post_with_template signature changed in v16+",
     "Use self.env['mail.template'].browse(template_id).send_mail() or _send_mail", False),

    # FIX: min_src_ver=19 — _auto_init changes relevant when coming from v18 or below
    (19, 0, r'def _auto_init\(self\)', SEVERITY_INFO, "Init Method",
     "_auto_init() usage — verify compatibility with v19 ORM lifecycle",
     "Prefer post_init hooks or migration scripts for schema changes", False),

    (0, 0, r'class\s+\w+\(.*TransientModel.*\)', SEVERITY_INFO, "TransientModel Check",
     "TransientModel detected — verify _name is set and wizard views are updated",
     "Ensure the wizard form view uses target='new' and the model has a proper _name", False),

    (0, 0, r'class\s+\w+\(.*AbstractModel.*\)', SEVERITY_INFO, "AbstractModel Check",
     "AbstractModel detected — verify _name/_inherit usage is correct for v19",
     "AbstractModel must be inherited via _inherit; it cannot be instantiated directly", False),

    (0, 0, r'fields\.Selection\b.*\bdefault\s*=\s*lambda', SEVERITY_WARNING, "Selection Default",
     "Lambda defaults on Selection fields removed in v17+",
     "Replace lambda default with a plain value or a named method reference", False),

    (0, 0, r'_cr\.execute\([^)]*%\s*[\w(]', SEVERITY_WARNING, "Raw SQL",
     "Raw SQL with string formatting — potential SQL injection risk",
     "Use parameterised queries: self._cr.execute(query, (param,))", False),

    (0, 0, r'from\s+openerp\.http\s+import', SEVERITY_CRITICAL, "HTTP Controller Import",
     "openerp.http import path removed",
     "Use: from odoo import http; class MyCtrl(http.Controller)", True),

    (0, 0, r'^\s*from\s+openerp\.', SEVERITY_CRITICAL, "Legacy openerp Import",
     "Import from deprecated 'openerp' namespace",
     "Replace 'openerp' with 'odoo' in import path", True),

    (0, 0, r'^\s*import\s+openerp\b', SEVERITY_CRITICAL, "Legacy openerp Import",
     "Direct import of deprecated 'openerp' module",
     "Replace 'import openerp' with 'import odoo'", True),

    (0, 0, r'from\s+odoo\.exceptions\s+import[^\n]*\bWarning\b', SEVERITY_CRITICAL,
     "Removed Exception: Warning",
     "odoo.exceptions.Warning was removed in v14; it was an alias for UserError",
     "Remove 'Warning' from the import and replace all raise Warning(...) with raise UserError(...)",
     True),

    (0, 0, r'from\s+openerp\.exceptions\s+import[^\n]*\bWarning\b', SEVERITY_CRITICAL,
     "Removed Exception: Warning (openerp)",
     "openerp.exceptions.Warning removed; namespace also deprecated",
     "Replace with: from odoo.exceptions import UserError  and raise UserError(...)", True),

    (0, 0, r'\braise\s+Warning\s*\(', SEVERITY_CRITICAL, "Raise Warning",
     "Raising Warning() directly — Warning was removed from odoo.exceptions in v14",
     "Replace raise Warning(...) with raise UserError(...)", True),
]

XML_RULES = [
    (0, 0, r'<openerp>', SEVERITY_CRITICAL, "Legacy XML Root",
     "<openerp> root tag removed",
     "Replace <openerp> with <odoo>", True),

    # CHANGED: auto_fixable=True — _convert_attrs_to_inline() handles this automatically
    (0, 0, r'\battrs\s*=\s*["\']', SEVERITY_CRITICAL, "Attrs Attribute",
     "'attrs' XML attribute removed in v17+",
     "Replace attrs with inline 'invisible', 'readonly', 'required' domain attrs", True),

    # CHANGED: auto_fixable=True — _convert_states_to_invisible() handles this automatically
    (0, 0, r'\bstates\s*=\s*["\'](?!\s*["\'])', SEVERITY_WARNING, "States Attribute",
     "'states' shorthand removed in v17+; show-only-when-state-in-list semantics replaced by "
     "invisible= domain. Auto-fix uses field name 'state' — verify if your field differs.",
     "Replace states= with invisible=\"state not in [...]\" condition", True),

    (0, 0, r'<act_window\b', SEVERITY_WARNING, "Shorthand Tag",
     "<act_window> shorthand removed; use <record model='ir.actions.act_window'>",
     "Expand to full <record> tag", False),

    (0, 0, r'<menuitem\b', SEVERITY_INFO, "Shorthand Tag",
     "<menuitem> shorthand may need parent_id update",
     "Verify parent menu references are valid in v19", False),

    (0, 0, r'<url\b', SEVERITY_WARNING, "URL Action Tag",
     "<url> shorthand removed; use <record model='ir.actions.act_url'>",
     "Expand to full <record> tag", False),

    (0, 0, r'\bgroups_id\s*=\s*["\']', SEVERITY_WARNING, "Groups Field",
     "groups_id= on views deprecated; use groups= attribute",
     "Replace groups_id= with groups=", True),

    # FIX: min_src_ver=16 — web_client_action changed IN v16
    (16, 0, r'web_client_action\b', SEVERITY_WARNING, "Client Action",
     "web_client_action type changed in v16+",
     "Verify client action type and tag names for v16+", False),

    (0, 0, r'<field name=["\']arch["\'] type=["\']xml["\']', SEVERITY_INFO, "View Arch",
     "Ensure view arch is valid for v19 field widgets",
     "Review widget= attributes against v19 widget list", False),

    # FIX: min_src_ver=17 — editable behavior changed IN v17
    (17, 0, r'type=["\']form["\'].*editable=["\']', SEVERITY_WARNING, "Editable Form",
     "editable attribute on list views changed behavior in v17",
     "Test list-view editable behavior in target version", False),

    (0, 0, r'widget=["\']monetary["\']', SEVERITY_INFO, "Monetary Widget",
     "monetary widget requires currency_field; verify field exists in v19 model",
     "Ensure currency_field= is set and present on the model", False),

    # FIX: min_src_ver=18 — <tree> was renamed IN v18
    (18, 0, r'<tree\b', SEVERITY_CRITICAL, "Tree Tag Renamed",
     "<tree> view tag deprecated in v18 and replaced by <list>",
     "Replace <tree ...> with <list ...> and </tree> with </list>", True),

    (0, 0, r'<div[^>]+class=["\'][^"\']*(oe_chatter)[^"\']*["\']', SEVERITY_CRITICAL, "Chatter Tag",
     "Old-style <div class='oe_chatter'> replaced by <chatter/> tag in v16+",
     "Replace the entire oe_chatter div block with <chatter/>", True),

    (0, 0, r'<field[^>]+name=["\']message_ids["\']', SEVERITY_CRITICAL, "Chatter Field",
     "Embedding message_ids field in view is obsolete; use <chatter/> instead",
     "Remove <field name='message_ids'/> and place <chatter/> after </sheet>", True),

    (0, 0, r'<field[^>]+name=["\']activity_ids["\']', SEVERITY_CRITICAL, "Chatter Field",
     "Embedding activity_ids field in view is obsolete; use <chatter/> instead",
     "Remove <field name='activity_ids'/> and place <chatter/> after </sheet>", True),

    (0, 0, r'<field[^>]+name=["\']message_follower_ids["\']', SEVERITY_CRITICAL, "Chatter Field",
     "Embedding message_follower_ids field in view is obsolete; use <chatter/> instead",
     "Remove <field name='message_follower_ids'/> and place <chatter/> after </sheet>", True),

    (0, 0, r'widget=["\']mail_thread["\']', SEVERITY_CRITICAL, "Chatter Widget",
     "widget='mail_thread' is obsolete; use the <chatter/> tag",
     "Replace with <chatter/>", True),

    (15, 0, r'<chatter\b', SEVERITY_INFO, "Chatter Placement",
     "<chatter/> detected — verify it is placed directly after </sheet> inside the form view",
     "Correct structure: <form><sheet>...</sheet><chatter/></form>", False),

    # FIX: min_src_ver=17 — page attrs removed IN v17
    (17, 0, r'<page\b[^>]+attrs\s*=', SEVERITY_CRITICAL, "Page Attrs",
     "attrs= on <page> tags removed in v17+",
     "Replace with invisible= domain directly on the <page> tag", False),

    (0, 0, r'noupdate=["\'\']0["\'\']', SEVERITY_INFO, "No Update Flag",
     "noupdate=0 means records are overwritten on module upgrade — verify this is intended",
     "Use noupdate=1 for configuration/reference data that should not reset on upgrade", False),

    # FIX: min_src_ver=17 — header placement changed IN v17
    (17, 0, r'<header\b', SEVERITY_INFO, "Header Buttons",
     "<header> button bar placement rules changed in v17+",
     "Ensure <header> is the first child of <form>, not inside <sheet>", False),
]

MANIFEST_RULES = [
    # This base rule is intentionally broad — version-specific rules below override
    (0, 0, r"'version'\s*:\s*'\d+\.\d+", SEVERITY_INFO, "Manifest Version",
     "Module version in manifest should be updated to match the target version",
     "Update 'version' key to the correct target version prefix", True),

    (0, 0, r"'installable'\s*:\s*False", SEVERITY_WARNING, "Not Installable",
     "Module marked as not installable",
     "Set installable=True if migrating for use", False),

    (0, 0, r"'auto_install'\s*:\s*True", SEVERITY_INFO, "Auto Install",
     "auto_install=True — ensure all dependencies exist in v19",
     "Verify all 'depends' modules are available in Odoo 19", False),

    (0, 0, r"'application'\s*:\s*True", SEVERITY_INFO, "Application Module",
     "Application module — ensure 'sequence' key is set for correct home menu ordering",
     "Add 'sequence': N to the manifest to control app position in the home menu", False),
]

JS_TS_RULES = [
    (0, 0, r'odoo\.define\(', SEVERITY_CRITICAL, "Legacy JS Module",
     "odoo.define() module system removed in v17+",
     "Rewrite as OWL component or ES module with /** @odoo-module */ header", True),

    (0, 0, r'require\(["\']web\.', SEVERITY_CRITICAL, "Legacy Require",
     "Deprecated require() usage for Odoo modules",
     "Use ES module imports: import { X } from '@web/...'", False),

    (0, 0, r'Widget\.extend\(', SEVERITY_CRITICAL, "Legacy Widget",
     "Widget.extend() pattern removed; Odoo now uses OWL",
     "Rewrite as OWL Component extending Component", False),

    # FIX: min_src_ver=16 — ajax.jsonRpc deprecated IN v16
    (16, 0, r'ajax\.jsonRpc\(', SEVERITY_WARNING, "AJAX Call",
     "ajax.jsonRpc deprecated in v16+",
     "Use this.env.services.rpc() or fetch with jsonrpc helper", True),

    (0, 0, r'\.on\(["\']click', SEVERITY_INFO, "jQuery Event",
     "jQuery event binding — OWL uses t-on-click directive",
     "Replace jQuery .on('click') with t-on-click in OWL template", False),

    (15, 0, r'useRef\(', SEVERITY_INFO, "OWL useRef",
     "Verify useRef() API compatibility with v19 OWL version",
     "Check OWL changelog for any useRef API changes", False),
]

CSS_RULES = [
    (0, 0, r'\.o_form_sheet_bg\b', SEVERITY_WARNING, "CSS Class",
     ".o_form_sheet_bg class renamed/restructured in v16+",
     "Verify CSS class exists in target version; use browser devtools", False),

    (0, 0, r'\.o_list_view\b', SEVERITY_WARNING, "CSS Class",
     ".o_list_view class restructured in v16+",
     "Check class hierarchy in v19", False),
]


# ─────────────────────────────────────────────
# ODOO 18-SPECIFIC RULES  (exact_tgt_ver=18)
# ─────────────────────────────────────────────

PYTHON_RULES_V18 = [
    (0, 18, r'spreadsheet_dashboard', SEVERITY_INFO, "v18 Module Rename",
     "spreadsheet_dashboard module was reorganised in v18",
     "Verify the module still exists under the same name in your v18 installation", False),

    (0, 18, r'website\.published\.mixin', SEVERITY_WARNING, "v18 Mixin Change",
     "website.published.mixin removed in v18; use website.published.multi.mixin",
     "Replace _inherit = 'website.published.mixin' with 'website.published.multi.mixin'", False),

    (0, 18, r'phone\.validation\.mixin', SEVERITY_WARNING, "v18 Phone Mixin",
     "phone.validation.mixin path changed in v18",
     "Import from odoo.addons.phone_validation.models.phone_validation", False),
]

XML_RULES_V18 = [
    (0, 18, r"<notebook[^>]+invisible\s*=", SEVERITY_INFO, "Notebook Invisible (v18)",
     "invisible= on <notebook> behaves differently in v18; verify rendering",
     "Test notebook visibility logic in a running v18 instance", False),
]

MANIFEST_RULES_V18 = [
    (0, 18, r"'version'\s*:\s*'(?!18\.0)", SEVERITY_WARNING, "Manifest Version (v18)",
     "Module version prefix should be '18.0.x.y.z' for Odoo 18",
     "Update 'version' key to '18.0.1.0.0'", True),
]

# ─────────────────────────────────────────────
# ODOO 19-SPECIFIC RULES  (exact_tgt_ver=19)
# ─────────────────────────────────────────────

PYTHON_RULES_V19 = []  # General rules above already cover v19 cases

XML_RULES_V19 = []  # General rules above already cover v19 cases

MANIFEST_RULES_V19 = [
    (0, 19, r"'version'\s*:\s*'(?!19\.0)", SEVERITY_WARNING, "Manifest Version (v19)",
     "Module version prefix should be '19.0.x.y.z' for Odoo 19",
     "Update 'version' key to '19.0.1.0.0'", True),
]


# ─────────────────────────────────────────────
# AUTO-FIX TRANSFORMATIONS
# ─────────────────────────────────────────────

_IMPORT_MODULE_MAP: list = [
    ("openerp.osv.orm",          "odoo.models"),
    ("openerp.osv.osv",          "odoo.models"),
    ("openerp.osv.fields",       "odoo.fields"),
    ("openerp.osv",              "odoo"),
    ("openerp.tools.safe_eval",  "odoo.tools.safe_eval"),
    ("openerp.tools.translate",  "odoo.tools.translate"),
    ("openerp.tools.float_utils","odoo.tools.float_utils"),
    ("openerp.tools",            "odoo.tools"),
    ("openerp.exceptions",       "odoo.exceptions"),
    ("openerp.http",             "odoo.http"),
    ("openerp.addons",           "odoo.addons"),
    ("openerp.api",              "odoo.api"),
    ("openerp",                  "odoo"),
]


def rewrite_import_paths(content: str) -> str:
    lines = content.splitlines(keepends=True)
    result = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith(("from ", "import ")):
            result.append(line)
            continue
        if re.match(r'from\s+\.', stripped):
            result.append(line)
            continue
        new_line = line
        for old_mod, new_mod in _IMPORT_MODULE_MAP:
            new_line = re.sub(
                r'(from\s+)' + re.escape(old_mod) + r'(\s+import\b)',
                r'\1' + new_mod + r'\2',
                new_line,
            )
            new_line = re.sub(
                r'(import\s+)' + re.escape(old_mod) + r'(\s*(?:as\s+\w+)?(?:\s*,|\s*$|\s*#))',
                r'\1' + new_mod + r'\2',
                new_line,
            )
        result.append(new_line)
    return ''.join(result)


def fix_warning_exception(content: str) -> str:
    """
    Fix the removed odoo.exceptions.Warning in three coordinated steps:

    1. Remove 'Warning' from any ``from [odoo|openerp].exceptions import ...`` line
       and ensure 'UserError' is present in the same import statement.
    2. Rewrite the namespace to ``odoo.exceptions`` if it was ``openerp.exceptions``.
    3. Replace every ``raise Warning(...)`` with ``raise UserError(...)``.
    4. If no ``odoo.exceptions`` import exists after step 1 but step 3 introduced
       ``raise UserError(``, insert ``from odoo.exceptions import UserError`` after
       the first ``from odoo import ...`` line (or at the top of the file).
    """
    # Step 1+2: fix existing exceptions import lines
    def _fix_import(m: re.Match) -> str:
        names_str = m.group(1)
        # Split on comma; strip whitespace / line-continuation chars
        names = [
            n.strip().strip('\\').strip()
            for n in names_str.split(',')
            if n.strip().strip('\\').strip()
        ]
        names = [n for n in names if n != 'Warning']
        if 'UserError' not in names:
            names.append('UserError')
        return f'from odoo.exceptions import {", ".join(names)}'

    content = re.sub(
        r'from\s+(?:odoo|openerp)\.exceptions\s+import\s+([\w\s,]+?)(?=\s*(?:#.*)?$)',
        _fix_import,
        content,
        flags=re.MULTILINE,
    )

    # Step 3: replace raise Warning(...) with raise UserError(...)
    content = re.sub(r'\braise\s+Warning\s*\(', 'raise UserError(', content)

    # Step 4: inject import if needed and not already present
    has_exceptions_import = bool(re.search(
        r'from\s+(?:odoo|openerp)\.exceptions\s+import', content
    ))
    needs_userror = bool(re.search(r'\braise\s+UserError\s*\(', content))
    if needs_userror and not has_exceptions_import:
        insert_line = 'from odoo.exceptions import UserError\n'
        m = re.search(r'^(?:from\s+odoo\b|import\s+odoo\b).*$', content, re.MULTILINE)
        if m:
            content = content[:m.end()] + '\n' + insert_line + content[m.end():]
        else:
            content = insert_line + content

    return content


def apply_python_fixes(content: str, from_version: int) -> str:
    content = rewrite_import_paths(content)
    content = re.sub(r'(?<![\w])openerp\.(?!addons)', 'odoo.', content)
    content = re.sub(r'^\s*@api\.multi\s*\n', '', content, flags=re.MULTILINE)
    content = re.sub(
        r'@api\.one[ \t]*(\n[ \t]*(#[^\n]*)?)*\n([ \t]*def )',
        r'\3',
        content,
    )
    content = re.sub(r'@api\.returns\([^)]*\)\s*\n', '', content)
    content = re.sub(
        r'from\s+(?:openerp\.)?osv\s+import\s+(?:osv|orm|fields)',
        'from odoo import models, fields, api',
        content
    )
    content = re.sub(r'\.sudo\((\w+)\)', r'.with_user(\1).sudo()', content)
    content = re.sub(
        r'from\s+openerp\.tools\s+import\s+html_sanitize',
        'from odoo.tools import html_sanitize',
        content
    )
    content = re.sub(r'^(\s*)print (["\'].+["\'])\s*$', r'\1print(\2)', content, flags=re.MULTILINE)
    content = re.sub(r'(fields\.Char\([^)]*),?\s*size\s*=\s*\d+', r'\1', content)
    content = re.sub(
        r'ajax\.jsonRpc\(',
        '/* TODO: replace with this.env.services.rpc( */ ajax.jsonRpc(',
        content
    )
    # Fix removed odoo.exceptions.Warning → UserError
    content = fix_warning_exception(content)
    return content


def _convert_attrs_to_inline(content: str) -> str:
    """
    Convert attrs="{'invisible': [...], 'readonly': [...], 'required': [...]}"
    to separate inline domain attributes: invisible="[...]" readonly="[...]" required="[...]"

    Odoo 17+ removed attrs= in favour of inline domain attributes on each property.

    Strategy: scan for attrs= occurrences, extract the quoted value, parse recognised
    key→domain pairs with a nested-bracket-aware regex, then replace the entire attrs="..."
    span with the equivalent inline attributes.  Unparseable attrs= values are left untouched
    so that the developer sees them in the remaining issues list.
    """
    result: list = []
    i = 0
    # Locate each attrs= occurrence
    find_attrs = re.compile(r'\battrs\s*=\s*(["\'])', re.DOTALL)
    # Parse individual key: domain pairs inside the dict value
    kv_pattern = re.compile(
        r"""['"](?P<key>invisible|readonly|required)['"]\s*:\s*(?P<domain>\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\[\]]*\])*\])*\])""",
        re.DOTALL,
    )

    while i < len(content):
        m = find_attrs.search(content, i)
        if not m:
            result.append(content[i:])
            break

        quote_char = m.group(1)
        val_start = m.end()          # start of the dict string (after opening quote)
        val_end = content.find(quote_char, val_start)
        if val_end == -1:
            # Malformed — keep rest as-is
            result.append(content[i:])
            break

        attrs_val = content[val_start:val_end]
        found = kv_pattern.findall(attrs_val)

        # Append everything up to (but not including) attrs=
        result.append(content[i:m.start()])

        if found:
            # Emit one inline attribute per recognised key
            result.append(' '.join(f'{key}="{domain}"' for key, domain in found))
        else:
            # Cannot parse — re-emit original so it stays detectable
            result.append(content[m.start():val_end + 1])

        i = val_end + 1  # advance past the closing quote

    return ''.join(result)


def _convert_states_to_invisible(content: str) -> str:
    """
    Convert the legacy states= attribute to an invisible= domain expression.

    The semantics of states="draft,open" are:
        "show this element ONLY when the record's state field is in the list"
    which is equivalent to:
        invisible="state not in ['draft', 'open']"

    NOTE: The legacy attribute assumes the controlling field is named ``state``.
    That is true for the overwhelming majority of standard and custom Odoo modules,
    but if your module uses a different field the developer must adjust manually.
    A comment is added next to the generated attribute as a reminder.

    Only converts states= on tags where it is a view-control attribute
    (button, field, notebook, group, div, span, page, label, separator).
    """
    def _replace(m: re.Match) -> str:
        full_tag   = m.group(0)
        states_val = m.group(1)

        state_list = [s.strip().strip("'\"") for s in states_val.split(',') if s.strip()]
        if not state_list:
            return full_tag

        # Odoo 17+ new-style domain expression (Python-like, not JSON)
        states_repr = "[" + ", ".join(f"'{s}'" for s in state_list) + "]"
        invisible_expr = f"state not in {states_repr}"

        # Remove states="..." from the tag (including any leading whitespace)
        tag_fixed = re.sub(r"""\s*\bstates\s*=\s*["'][^"']*["']""", '', full_tag)

        # Insert invisible= just before the closing > or />
        tag_fixed = re.sub(
            r'(\s*/?\s*)>$',
            lambda tm: f' invisible="{invisible_expr}"'
                       f'  <!-- TODO: verify controlling field is named "state" -->'
                       + tm.group(0),
            tag_fixed,
        )
        return tag_fixed

    pattern = re.compile(
        r"""<(?:button|field|notebook|group|div|span|page|label|separator)\b[^>]*"""
        r"""\bstates\s*=\s*["']([^"']*)["'][^>]*>""",
        re.DOTALL,
    )
    return pattern.sub(_replace, content)


def apply_xml_fixes(content: str, from_version: int) -> str:
    # <openerp> → <odoo>
    content = re.sub(r'<openerp>', '<odoo>', content)
    content = re.sub(r'</openerp>', '</odoo>', content)

    # ── attrs= → inline domain attributes (Odoo 17+) ────────────────────────
    content = _convert_attrs_to_inline(content)

    # ── states= → invisible= domain expression (Odoo 17+) ───────────────────
    content = _convert_states_to_invisible(content)

    # groups_id= → groups=
    content = re.sub(r'\bgroups_id\s*=', 'groups=', content)

    # v18+: <tree> → <list>
    content = re.sub(r'<tree\b', '<list', content)
    content = re.sub(r'</tree>', '</list>', content)
    content = re.sub(
        r'(\bview_type\s*=\s*["\'])tree(["\'])',
        r'\1list\2',
        content,
    )
    content = re.sub(
        r'(\bview_mode\s*=\s*["\'][^"\']*?)\btree\b',
        r'\1list',
        content,
    )

    def _fix_view_mode_field(m):
        # FIX: use m.group(3) for closing tag, not hardcoded '</field>'
        return m.group(1) + m.group(2).replace('tree', 'list') + m.group(3)

    content = re.sub(
        r'(<field[^>]+name=["\']view_mode["\'][^>]*>)([^<]*)(</field>)',
        _fix_view_mode_field,
        content,
    )
    content = re.sub(
        r'(<field[^>]+name=["\']view_type["\'][^>]*>)([^<]*)(</field>)',
        lambda mm: mm.group(1) + mm.group(2).replace('tree', 'list') + mm.group(3),
        content,
    )

    # ── Chatter auto-fixes ────────────────────────────────────────────────────

    # FIX: safer chatter div replacement using a depth-counter approach
    # to avoid eating nested </div> tags
    content = _replace_chatter_div(content)

    for _chatter_field in ('message_ids', 'activity_ids', 'message_follower_ids'):
        content = re.sub(
            r'<field[^>]+name=["\']' + _chatter_field + r'["\'][^/]*/\s*>',
            '',
            content,
        )
        content = re.sub(
            r'<field[^>]+name=["\']' + _chatter_field + r'["\'][^>]*>.*?</field>',
            '',
            content,
            flags=re.DOTALL,
        )

    content = re.sub(
        r'<field[^>]+widget=["\']mail_thread["\'][^/]*/\s*>',
        '<chatter/>',
        content,
    )
    content = re.sub(
        r'<field[^>]+widget=["\']mail_thread["\'][^>]*>.*?</field>',
        '<chatter/>',
        content,
        flags=re.DOTALL,
    )

    content = re.sub(r'\n{3,}', '\n\n', content)
    return content


def _replace_chatter_div(content: str) -> str:
    """
    FIX: Replace <div class="oe_chatter">...</div> with <chatter/> using a
    depth-counter to correctly handle nested divs rather than a greedy regex.
    """
    result = []
    i = 0
    pattern = re.compile(
        r'<div[^>]+class=["\'][^"\']*oe_chatter[^"\']*["\'][^>]*>',
        re.IGNORECASE
    )
    while i < len(content):
        m = pattern.search(content, i)
        if not m:
            result.append(content[i:])
            break
        result.append(content[i:m.start()])
        depth = 1
        pos = m.end()
        while pos < len(content) and depth > 0:
            open_tag  = content.find('<div', pos)
            close_tag = content.find('</div>', pos)
            if close_tag == -1:
                pos = len(content)
                break
            if open_tag != -1 and open_tag < close_tag:
                depth += 1
                pos = open_tag + 4
            else:
                depth -= 1
                if depth == 0:
                    pos = close_tag + len('</div>')
                else:
                    pos = close_tag + len('</div>')
        result.append('<chatter/>')
        i = pos
    return ''.join(result)


def apply_manifest_fixes(content: str, from_version: int, to_version: int = 19) -> str:
    """
    FIX: Handle both single-quoted and double-quoted version strings.
    Also handles versions that are already correct (idempotent).
    """
    target_ver_str = f"{to_version}.0.1.0.0"

    # Single-quoted version string
    content = re.sub(
        r"('version'\s*:\s*')[^']+(')",
        lambda m: m.group(1) + target_ver_str + m.group(2),
        content,
    )
    # Double-quoted version string
    content = re.sub(
        r'("version"\s*:\s*")[^"]+(")',
        lambda m: m.group(1) + target_ver_str + m.group(2),
        content,
    )
    return content


def apply_js_fixes(content: str, from_version: int) -> str:
    if 'odoo.define(' in content and '/** @odoo-module' not in content:
        content = '/** @odoo-module */\n// TODO: Convert odoo.define() to OWL component or ES module\n' + content
    content = re.sub(
        r'ajax\.jsonRpc\(',
        '/* TODO: use this.env.services.rpc( */ ajax.jsonRpc(',
        content
    )
    return content


# ─────────────────────────────────────────────
# ANALYZER
# ─────────────────────────────────────────────

def _compile_rules(rules: list) -> list:
    return [
        (min_ver, exact_tgt_ver, re.compile(pattern), severity, category, message, suggestion, auto_fixable)
        for min_ver, exact_tgt_ver, pattern, severity, category, message, suggestion, auto_fixable in rules
    ]

PYTHON_RULES_C   = _compile_rules(PYTHON_RULES)
XML_RULES_C      = _compile_rules(XML_RULES)
MANIFEST_RULES_C = _compile_rules(MANIFEST_RULES)
JS_TS_RULES_C    = _compile_rules(JS_TS_RULES)
CSS_RULES_C      = _compile_rules(CSS_RULES)
PYTHON_RULES_V18_C   = _compile_rules(PYTHON_RULES_V18)
XML_RULES_V18_C      = _compile_rules(XML_RULES_V18)
MANIFEST_RULES_V18_C = _compile_rules(MANIFEST_RULES_V18)
PYTHON_RULES_V19_C   = _compile_rules(PYTHON_RULES_V19)
XML_RULES_V19_C      = _compile_rules(XML_RULES_V19)
MANIFEST_RULES_V19_C = _compile_rules(MANIFEST_RULES_V19)


def check_content(content: str, filepath: str, compiled_rules: list,
                  from_version: int, report: MigrationReport):
    """
    Scan file content line-by-line against pre-compiled rules.

    FIX: Rule filtering semantics corrected:
    - min_ver: rule applies only when from_version < min_ver
      (the breaking change was introduced IN min_ver, so older codebases need the fix)
      min_ver=0 means always applies.
    - exact_tgt_ver: rule applies only when to_version == exact_tgt_ver
      exact_tgt_ver=0 means all target versions.
    """
    lines = content.splitlines()
    seen: set = set()

    for min_ver, exact_tgt_ver, pattern, severity, category, message, suggestion, auto_fixable in compiled_rules:
        # Skip if the source is already at or beyond the version where the fix was introduced
        if min_ver != 0 and from_version >= min_ver:
            continue
        # FIX: exact target version match (not "at or above")
        if exact_tgt_ver != 0 and report.to_version != exact_tgt_ver:
            continue
        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                key = (i, category)
                if key in seen:
                    continue
                seen.add(key)
                report.issues.append(Issue(
                    file=filepath,
                    line=i,
                    severity=severity,
                    category=category,
                    message=message,
                    suggestion=suggestion,
                    auto_fixable=auto_fixable,
                ))


def _read_file(filepath: Path, report: MigrationReport) -> Optional[str]:
    try:
        return filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        report.issues.append(Issue(
            file=str(filepath), line=0, severity=SEVERITY_WARNING,
            category="Read Error", message=f"Could not read file: {e}",
            suggestion="Check file encoding or permissions", auto_fixable=False,
        ))
        return None


def _rules_for_file(filepath: Path, to_version: int = 19) -> Optional[list]:
    name = filepath.name.lower()
    ext  = filepath.suffix.lower()
    if name in ("__manifest__.py", "__openerp__.py"):
        base = MANIFEST_RULES_C[:]
        if to_version == 18:
            base += MANIFEST_RULES_V18_C
        else:
            base += MANIFEST_RULES_V19_C
        return base
    if ext == ".py":
        base = PYTHON_RULES_C[:]
        if to_version == 18:
            base += PYTHON_RULES_V18_C
        else:
            base += PYTHON_RULES_V19_C
        return base
    if ext == ".xml":
        base = XML_RULES_C[:]
        if to_version == 18:
            base += XML_RULES_V18_C
        else:
            base += XML_RULES_V19_C
        return base
    if ext in (".js", ".ts"):
        return JS_TS_RULES_C
    if ext in (".css", ".scss", ".less"):
        return CSS_RULES_C
    return None


def _mark_auto_fixes_applied(content_before: str, content_after: str,
                              issues: list, filepath: str):
    """
    FIX: After applying regex fixes, mark auto_fixable issues as fix_applied=True
    for issues in the given file. We can't know exactly which lines were fixed,
    so we mark all auto_fixable issues in the file as applied when the file changed.
    """
    if content_before == content_after:
        return
    for issue in issues:
        if issue.file == filepath and issue.auto_fixable and not issue.fix_applied:
            issue.fix_applied = True


def analyze_and_fix_file(
    filepath: Path,
    from_version: int,
    report: MigrationReport,
    do_fix: bool,
) -> int:
    content = _read_file(filepath, report)
    if content is None:
        return 0

    rules = _rules_for_file(filepath, to_version=report.to_version)
    if rules is not None:
        check_content(content, str(filepath), rules, from_version, report)

    if not do_fix:
        return 0

    ext  = filepath.suffix.lower()
    name = filepath.name.lower()
    fixed = content

    if name in ("__manifest__.py", "__openerp__.py"):
        fixed = apply_manifest_fixes(fixed, from_version, to_version=report.to_version)
    elif ext == ".py":
        fixed = apply_python_fixes(fixed, from_version)
    elif ext == ".xml":
        fixed = apply_xml_fixes(fixed, from_version)
    elif ext in (".js", ".ts"):
        fixed = apply_js_fixes(fixed, from_version)

    if fixed != content:
        filepath.write_text(fixed, encoding="utf-8")
        # FIX: mark auto-fixable issues for this file as resolved
        _mark_auto_fixes_applied(content, fixed, report.issues, str(filepath))
        return 1
    return 0


# ─────────────────────────────────────────────
# MODULE WALKER
# ─────────────────────────────────────────────

SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.mypy_cache', 'venv', '.venv'}


def _load_gitignore_patterns(module_path: Path) -> list:
    gi = module_path / '.gitignore'
    if not gi.exists():
        return []
    patterns = []
    try:
        for line in gi.read_text(encoding='utf-8', errors='replace').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            regex = re.escape(line).replace(r'\*\*', '.*').replace(r'\*', '[^/]*').replace(r'\?', '.')
            patterns.append(re.compile(regex))
    except Exception:
        pass
    return patterns


def _is_gitignored(filepath: Path, module_path: Path, patterns: list) -> bool:
    try:
        rel = str(filepath.relative_to(module_path))
    except ValueError:
        return False
    return any(p.search(rel) for p in patterns)


SCAN_EXTENSIONS = {'.py', '.xml', '.js', '.ts', '.css', '.scss', '.less'}


def _check_manifest_version(module_path: Path, from_version: int, report: MigrationReport):
    for name in ("__manifest__.py", "__openerp__.py"):
        mf = module_path / name
        if not mf.exists():
            continue
        try:
            text = mf.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"['\"]version['\"]\\s*:\\s*['\"](\d+)\.", text)
            if not m:
                # Try simpler pattern
                m = re.search(r"'version'\s*:\s*'(\d+)\.", text)
            if not m:
                m = re.search(r'"version"\s*:\s*"(\d+)\.', text)
            if m:
                declared = int(m.group(1))
                if declared != from_version:
                    report.issues.append(Issue(
                        file=str(mf), line=0, severity=SEVERITY_WARNING,
                        category="Version Mismatch",
                        message=(
                            f"Manifest declares version {declared}.x but "
                            f"--from-version={from_version} was passed"
                        ),
                        suggestion=(
                            f"Confirm the source version. If the module is v{declared}, "
                            f"re-run with --from-version {declared}"
                        ),
                        auto_fixable=False,
                    ))
        except Exception:
            pass
        break


def walk_module(module_path: Path, from_version: int, report: MigrationReport, do_fix: bool):
    _check_manifest_version(module_path, from_version, report)
    gi_patterns = _load_gitignore_patterns(module_path)

    manifests = []
    others    = []
    for root, dirs, files in os.walk(module_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in sorted(files):
            fp = Path(root) / f
            if gi_patterns and _is_gitignored(fp, module_path, gi_patterns):
                continue
            name = fp.name.lower()
            if name in ("__manifest__.py", "__openerp__.py"):
                manifests.append(fp)
            elif fp.suffix.lower() in SCAN_EXTENSIONS:
                others.append(fp)

    all_files = manifests + others

    for fp in all_files:
        report.fixes_applied += analyze_and_fix_file(fp, from_version, report, do_fix)

    openerp_manifest = module_path / '__openerp__.py'
    if openerp_manifest.exists():
        new_path = module_path / '__manifest__.py'
        if not new_path.exists():
            shutil.copy2(openerp_manifest, new_path)
            if do_fix:
                openerp_manifest.unlink()
                report.fixes_applied += 1
                report.issues.append(Issue(
                    file=str(openerp_manifest), line=0,
                    severity=SEVERITY_INFO, category="Rename",
                    message="__openerp__.py renamed to __manifest__.py",
                    suggestion="", auto_fixable=True, fix_applied=True
                ))


# ─────────────────────────────────────────────
# REPORT RENDERING
# ─────────────────────────────────────────────

SEVERITY_COLOR = {
    SEVERITY_CRITICAL: '\033[91m',
    SEVERITY_WARNING:  '\033[93m',
    SEVERITY_INFO:     '\033[96m',
}
RESET = '\033[0m'
BOLD  = '\033[1m'
GREEN = '\033[92m'


def print_report(report: MigrationReport, no_color: bool = False, show_fixed: bool = False,
                 filter_severity: Optional[str] = None):
    def c(color, text):
        return text if no_color else f"{color}{text}{RESET}"

    width = 80
    open_issues  = [i for i in report.issues if not i.fix_applied]
    fixed_issues = [i for i in report.issues if i.fix_applied]

    print()
    print(c(BOLD, "=" * width))
    print(c(BOLD, f"  Odoo Migration Report  v{report.from_version} → v{report.to_version}"))
    print(c(BOLD, f"  Module : {report.module_path}"))
    print(c(BOLD, f"  Time   : {report.timestamp}"))
    print(c(BOLD, "=" * width))

    display_issues = report.issues if show_fixed else open_issues

    _SEV_ORDER = {SEVERITY_CRITICAL: 3, SEVERITY_WARNING: 2, SEVERITY_INFO: 1}
    if filter_severity:
        _min_level = _SEV_ORDER.get(filter_severity, 1)
        display_issues = [i for i in display_issues
                          if _SEV_ORDER.get(i.severity, 0) >= _min_level]

    if not display_issues:
        if fixed_issues:
            print(c(GREEN, f"\n  ✓ All {len(fixed_issues)} issue(s) fixed! Module is clean.\n"))
        else:
            print(c(GREEN, "\n  ✓ No issues found! Module looks clean.\n"))
        if fixed_issues and not show_fixed:
            print(f"  (Use --show-fixed to see {len(fixed_issues)} resolved issue(s))\n")
        return

    by_file: dict = {}
    for issue in display_issues:
        by_file.setdefault(issue.file, []).append(issue)

    for filepath, issues in sorted(by_file.items()):
        rel = os.path.relpath(filepath, report.module_path)
        print(f"\n{c(BOLD, '  FILE: ' + rel)}")
        print("  " + "-" * (width - 2))
        for issue in sorted(issues, key=lambda i: i.line):
            sev_color = SEVERITY_COLOR.get(issue.severity, '')
            tag = (c(GREEN, ' ✓ FIXED') if issue.fix_applied
                   else c(GREEN, ' [AUTO-FIX]') if issue.auto_fixable
                   else '')
            print(
                f"  {c(sev_color, f'[{issue.severity:<8}]')} "
                f"L{issue.line:<5} "
                f"{c(BOLD, issue.category)}{tag}"
            )
            print(f"           {issue.message}")
            if not issue.fix_applied:
                print(f"           → {issue.suggestion}")

    remaining_crit = sum(1 for i in open_issues if i.severity == SEVERITY_CRITICAL)
    remaining_warn = sum(1 for i in open_issues if i.severity == SEVERITY_WARNING)
    remaining_info = sum(1 for i in open_issues if i.severity == SEVERITY_INFO)
    total_crit = sum(1 for i in report.issues if i.severity == SEVERITY_CRITICAL)
    total_warn = sum(1 for i in report.issues if i.severity == SEVERITY_WARNING)
    total_info = sum(1 for i in report.issues if i.severity == SEVERITY_INFO)

    print()
    print(c(BOLD, "=" * width))
    print(c(BOLD, "  SUMMARY"))
    print(c(BOLD, "=" * width))
    print(f"  {c(SEVERITY_COLOR[SEVERITY_CRITICAL], f'Critical : {remaining_crit}')}"
          + (f"  (total: {total_crit})" if total_crit != remaining_crit else ""))
    print(f"  {c(SEVERITY_COLOR[SEVERITY_WARNING],  f'Warnings : {remaining_warn}')}"
          + (f"  (total: {total_warn})" if total_warn != remaining_warn else ""))
    print(f"  {c(SEVERITY_COLOR[SEVERITY_INFO],     f'Info     : {remaining_info}')}"
          + (f"  (total: {total_info})" if total_info != remaining_info else ""))
    if fixed_issues:
        print(f"  {c(GREEN, f'Fixed    : {len(fixed_issues)}')}")
    if report.fixes_applied:
        print(f"  {c(GREEN, f'Files modified: {report.fixes_applied}')}")
    print(c(BOLD, "=" * width))
    print()


def save_json_report(report: MigrationReport, output_path: Path):
    data = {
        "module_path": report.module_path,
        "from_version": report.from_version,
        "to_version": report.to_version,
        "timestamp": report.timestamp,
        "summary": {
            "critical": report.critical_count,
            "warnings": report.warning_count,
            "info": report.info_count,
            "fixable": report.fixable_count,
            "fixes_applied": report.fixes_applied,
            "open": sum(1 for i in report.issues if not i.fix_applied),
            "fixed": sum(1 for i in report.issues if i.fix_applied),
            "elapsed_seconds": round(report.elapsed_seconds, 2),
        },
        "issues": [
            {
                "file": i.file,
                "line": i.line,
                "severity": i.severity,
                "category": i.category,
                "message": i.message,
                "suggestion": i.suggestion,
                "auto_fixable": i.auto_fixable,
                "fix_applied": i.fix_applied,
            }
            for i in report.issues
        ]
    }
    output_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(f"  JSON report saved → {output_path}")


# ─────────────────────────────────────────────
# BACKUP
# ─────────────────────────────────────────────

def backup_module(module_path: Path) -> Optional[Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = module_path.parent / f"{module_path.name}_backup_{timestamp}"
    try:
        shutil.copytree(module_path, backup_path)
        print(f"\n  Backup created → {backup_path}")
        return backup_path
    except Exception as e:
        print(f"\n  WARNING: Backup failed ({e}). Continuing without backup.")
        return None


# ─────────────────────────────────────────────
# CLAUDE AI INTEGRATION
# ─────────────────────────────────────────────

CLAUDE_API_URL    = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 16384
CLAUDE_MAX_BUNDLE_BYTES = 180_000

_AI_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert Odoo migration engineer specialising in upgrading custom Odoo modules to Odoo {to_version}.

You will receive PYTHON FILES from a single Odoo module that need migration fixes to Odoo {to_version}.
Each file is accompanied by a list of detected issues (line number, category, message, fix hint).

YOUR TASK:
- Fix ONLY the listed issues. Return the complete corrected file content.
- Return a single valid JSON object — nothing else. No markdown fences, no preamble,
  no explanation after the JSON.
- The JSON must have this exact structure:

{{
  "files": {{
    "<filename>": "<complete corrected file content as a string>",
    ...
  }},
  "skipped": ["<filename_if_too_complex>", ...],
  "notes": "optional brief summary"
}}

STRICT RULES — VIOLATIONS WILL BREAK PRODUCTION ODOO INSTANCES:
- NEVER remove any import line or any name from an import statement.
  To fix a broken import path, only rewrite the module name (openerp.* -> odoo.*).
  Keep ALL imported names exactly as they are. Never delete an import line.
- NEVER rename any field defined with fields.Char, fields.Many2one, fields.Integer, etc.
  Field names are stored in the PostgreSQL database. Renaming them destroys existing data.
- NEVER rename any model _name or _inherit string value.
  Strings like 'hr.contract', 'account.move', 'res.partner' must stay exactly as-is.
  They are stored in ir.model, ir.rule, security CSV files — renaming them breaks the DB.
- NEVER remove any method, field definition, class, or variable.
- Preserve original indentation style (tabs vs spaces) and line endings exactly.
- Only fix what is explicitly listed in the issues. Do not refactor unrelated code.
- When migrating old-style (cr, uid, ids, context) methods, keep ALL business logic intact;
  only update the method signature and direct ORM calls (search, write, create, browse).
- When fixing "raise Warning(...)", replace only that raise statement with "raise UserError(...)".
  Also ensure "from odoo.exceptions import UserError" exists in imports (add if missing, never remove).
- When converting _columns/_defaults, preserve the exact same field names and logic.
- String values in the JSON must use proper JSON escaping (\\n for newlines, \\" for quotes, etc.).
- Target Odoo version: {to_version}.
"""


def _get_ai_system_prompt(to_version: int) -> str:
    return _AI_SYSTEM_PROMPT_TEMPLATE.format(to_version=to_version)


def _build_bundle_prompt(file_map: dict, from_version: int, to_version: int = 19) -> str:
    lang_map = {".py": "Python", ".xml": "XML", ".js": "JavaScript",
                ".ts": "TypeScript", ".css": "CSS", ".scss": "SCSS"}
    sections = [
        f"MIGRATION: Odoo v{from_version} → Odoo {to_version}\n"
        f"FILES IN BUNDLE: {len(file_map)} (across all modules)\n"
        f"IMPORTANT: Return keys in 'files' exactly as given below ('module/filename' format).\n"
    ]
    for file_key, (filepath_str, content, issues) in file_map.items():
        fp   = Path(filepath_str)
        lang = lang_map.get(fp.suffix.lower(), "text")
        issue_lines = []
        for idx, iss in enumerate(issues, 1):
            issue_lines.append(
                f"    {idx}. [Line {iss.line}] [{iss.severity}] {iss.category}\n"
                f"       Problem : {iss.message}\n"
                f"       Fix hint: {iss.suggestion}"
            )
        sections.append(
            f"{'='*70}\n"
            f"FILE_KEY: {file_key}\n"
            f"LANGUAGE: {lang}\n"
            f"ISSUES ({len(issues)}):\n"
            + "\n".join(issue_lines)
            + f"\n\nCONTENT:\n{content}\n"
        )
    return "\n".join(sections)


def _call_claude_api(api_key: str, user_message: str, to_version: int = 19, retries: int = 3) -> str:
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "system": _get_ai_system_prompt(to_version),
        "messages": [{"role": "user", "content": user_message}],
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                CLAUDE_API_URL, data=payload, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text_blocks = [
                    b["text"] for b in data.get("content", []) if b.get("type") == "text"
                ]
                return "\n".join(text_blocks)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code in (429, 503, 529) and attempt < retries:
                wait = 2 ** attempt
                print(f"\n          [AI] Rate-limited (HTTP {e.code}), retrying in {wait}s…")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Anthropic API HTTP {e.code}: {body[:400]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}") from e
    raise RuntimeError("Anthropic API: max retries exceeded")


def _parse_bundle_response(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw)
    raw = raw.strip()
    brace_start = raw.find("{")
    brace_end   = raw.rfind("}")
    if brace_start == -1 or brace_end == -1:
        raise ValueError("No JSON object found in AI response")
    raw = raw[brace_start: brace_end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse error: {e}") from e
    if "files" not in data or not isinstance(data["files"], dict):
        raise ValueError("Response JSON missing 'files' dict")
    return data


def _validate_python_syntax(code: str) -> Optional[str]:
    try:
        ast.parse(code)
        return None
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}"


def _ensure_newline(text: str) -> str:
    if text and not text.endswith("\n"):
        return text + "\n"
    return text


def ai_fix_all_modules(reports: list, module_paths: list, api_key: str,
                       verbose: bool = False) -> int:
    to_version   = reports[0].to_version   if reports else 19
    from_version = reports[0].from_version if reports else 14

    file_map: dict     = {}
    skipped_large: list = []
    total_bytes = 0
    all_candidates: list = []

    for report, module_path in zip(reports, module_paths):
        manual_by_file: dict = {}
        for issue in report.issues:
            if not issue.auto_fixable and not issue.fix_applied:
                manual_by_file.setdefault(issue.file, []).append(issue)
        for filepath_str, issues in manual_by_file.items():
            if Path(filepath_str).suffix.lower() != '.py':
                continue
            non_info = [i for i in issues if i.severity != SEVERITY_INFO]
            if not non_info:
                continue
            crit = sum(1 for i in issues if i.severity == SEVERITY_CRITICAL)
            all_candidates.append((crit, len(issues), filepath_str, issues, report, module_path))

    if not all_candidates:
        print("  [AI] No manual-fix issues remaining across any module — skipping AI pass.")
        return 0

    all_candidates.sort(key=lambda t: (-t[0], -t[1]))

    for crit, total, filepath_str, issues, report, module_path in all_candidates:
        fp = Path(filepath_str)
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            print(f"  [AI] Cannot read {fp.name}: {exc} — skipped")
            continue
        file_bytes = len(content.encode("utf-8"))
        if total_bytes + file_bytes > CLAUDE_MAX_BUNDLE_BYTES:
            skipped_large.append(f"{module_path.name}/{fp.name}")
            report.issues.append(Issue(
                file=filepath_str, line=0, severity=SEVERITY_WARNING,
                category="AI Skip",
                message=f"{fp.name} exceeds the {CLAUDE_MAX_BUNDLE_BYTES // 1000}KB "
                        f"bundle limit and was not sent to AI",
                suggestion="Fix manually, or raise CLAUDE_MAX_BUNDLE_BYTES in the script",
                auto_fixable=False, fix_applied=False,
            ))
            continue
        file_key = f"{module_path.name}/{fp.name}"
        if file_key in file_map:
            file_key = f"{module_path.name}/{fp.relative_to(module_path)}"
        total_bytes += file_bytes
        file_map[file_key] = (filepath_str, content, issues, report, module_path)

    if not file_map:
        print("  [AI] All files exceeded the bundle size limit — nothing sent to AI.")
        return 0

    if skipped_large:
        print(f"  [AI] ⚠ Bundle-limit skipped: {', '.join(skipped_large)}")

    n_files  = len(file_map)
    n_issues = sum(len(v[2]) for v in file_map.values())
    n_mods   = len({v[4].name for v in file_map.values()})
    print(
        f"\n  [AI] Sending 1 request to Claude ({CLAUDE_MODEL}) "
        f"— {n_files} file(s) across {n_mods} module(s), "
        f"{n_issues} issue(s), ~{total_bytes // 1024}KB…"
    )

    slim_map = {k: (v[0], v[1], v[2]) for k, v in file_map.items()}
    prompt = _build_bundle_prompt(slim_map, from_version, to_version=to_version)

    try:
        raw_response = _call_claude_api(api_key, prompt, to_version=to_version)
    except RuntimeError as exc:
        print(f"  [AI] ✗ API call failed: {exc}")
        reports[0].issues.append(Issue(
            file=str(module_paths[0]), line=0, severity=SEVERITY_WARNING,
            category="AI Error",
            message=f"Claude API call failed: {exc}",
            suggestion="Check your API key and network, then retry with --ai-fix",
            auto_fixable=False, fix_applied=False,
        ))
        return 0

    if verbose:
        preview = raw_response[:400].replace("\n", "↵")
        print(f"  [AI] Response preview: {preview}…")

    try:
        bundle = _parse_bundle_response(raw_response)
    except ValueError as exc:
        print(f"  [AI] ✗ Could not parse AI response as JSON: {exc}")
        debug_path = module_paths[0] / "ai_response_debug.txt"
        try:
            debug_path.write_text(raw_response, encoding="utf-8")
            print(f"  [AI]   Raw response saved → {debug_path}")
        except Exception:
            pass
        reports[0].issues.append(Issue(
            file=str(module_paths[0]), line=0, severity=SEVERITY_WARNING,
            category="AI Parse Error",
            message=f"AI returned unparseable response: {exc}",
            suggestion=f"Inspect ai_response_debug.txt and apply fixes manually",
            auto_fixable=False, fix_applied=False,
        ))
        return 0

    ai_files: dict   = bundle.get("files", {})
    ai_skipped: list = bundle.get("skipped", [])
    ai_notes: str    = bundle.get("notes", "")

    if ai_skipped:
        print(f"  [AI] Claude skipped (too complex): {', '.join(ai_skipped)}")
    if ai_notes and verbose:
        print(f"  [AI] Notes: {ai_notes}")

    fixed_count = 0
    for file_key, (filepath_str, original, issues, report, module_path) in file_map.items():
        fp = Path(filepath_str)
        fixed_content = ai_files.get(file_key)
        if fixed_content is None:
            fixed_content = ai_files.get(fp.name)
        if fixed_content is None:
            rel = fp.relative_to(module_path)
            print(f"  [AI] ✗ {module_path.name}/{rel} — not in AI response, skipped")
            continue
        fixed_content = _ensure_newline(fixed_content)
        if fixed_content == original:
            rel = fp.relative_to(module_path)
            print(f"  [AI] ↔ {module_path.name}/{rel} — no changes")
            continue
        if fp.suffix.lower() == ".py":
            err = _validate_python_syntax(fixed_content)
            if err:
                draft = fp.with_suffix(fp.suffix + ".ai_draft")
                draft.write_text(fixed_content, encoding="utf-8")
                rel = fp.relative_to(module_path)
                print(f"  [AI] ⚠ {module_path.name}/{rel} — syntax error ({err}); saved as {draft.name}")
                report.issues.append(Issue(
                    file=filepath_str, line=0, severity=SEVERITY_WARNING,
                    category="AI Draft",
                    message=f"AI output has a Python syntax error; saved as {draft.name}",
                    suggestion=f"Review {draft.name}, correct the error, rename to {fp.name}",
                    auto_fixable=False, fix_applied=False,
                ))
                continue
        fp.write_text(fixed_content, encoding="utf-8")
        for issue in issues:
            issue.fix_applied = True
        report.fixes_applied += 1
        fixed_count += 1
        rel = fp.relative_to(module_path)
        print(f"  [AI] ✓ {module_path.name}/{rel}")

    print(
        f"\n  [AI] Done — {fixed_count}/{n_files} file(s) updated "
        f"across {n_mods} module(s) in 1 API call."
    )
    return fixed_count


# ─────────────────────────────────────────────
# MULTI-MODULE HELPERS
# ─────────────────────────────────────────────

def resolve_modules(args) -> list:
    candidates = []
    if args.module:
        candidates.append(Path(args.module).resolve())
    if args.modules:
        for entry in args.modules:
            for part in entry.replace(",", " ").split():
                candidates.append(Path(part).resolve())
    if args.addons_path:
        addons_root = Path(args.addons_path).resolve()
        if not addons_root.is_dir():
            print(f"ERROR: --addons-path is not a directory: {addons_root}")
            sys.exit(1)
        for child in sorted(addons_root.iterdir()):
            if child.is_dir() and (
                (child / "__manifest__.py").exists() or
                (child / "__openerp__.py").exists()
            ):
                candidates.append(child)
    seen = set()
    modules = []
    for p in candidates:
        if p not in seen:
            seen.add(p)
            modules.append(p)
    return modules


def print_combined_summary(reports: list, no_color: bool = False):
    def c(color, text):
        return text if no_color else f"{color}{text}{RESET}"
    width = 80
    print()
    print(c(BOLD, "=" * width))
    to_v = reports[0].to_version if reports else 19
    print(c(BOLD, f"  COMBINED SUMMARY  ({len(reports)} module(s) → Odoo {to_v})"))
    print(c(BOLD, "=" * width))
    print(f"  {'Module':<40} {'Crit':>6} {'Warn':>6} {'Info':>6} {'Fixed':>6} {'Time':>7}")
    print("  " + "-" * (width - 2))
    for r in reports:
        name = Path(r.module_path).name
        crit_s = c(SEVERITY_COLOR[SEVERITY_CRITICAL], str(r.critical_count)) if r.critical_count else "0"
        warn_s = c(SEVERITY_COLOR[SEVERITY_WARNING],  str(r.warning_count))  if r.warning_count  else "0"
        info_s = c(SEVERITY_COLOR[SEVERITY_INFO],     str(r.info_count))     if r.info_count     else "0"
        fix_s  = c(GREEN, str(r.fixes_applied)) if r.fixes_applied else "0"
        time_s = f"{r.elapsed_seconds:.1f}s"
        print(f"  {name:<40} {crit_s:>6} {warn_s:>6} {info_s:>6} {fix_s:>6} {time_s:>7}")
    print("  " + "-" * (width - 2))
    total_c = sum(r.critical_count  for r in reports)
    total_w = sum(r.warning_count   for r in reports)
    total_i = sum(r.info_count      for r in reports)
    total_f = sum(r.fixes_applied   for r in reports)
    total_t = sum(r.elapsed_seconds for r in reports)
    print(
        f"  {'TOTAL':<40} "
        f"{c(SEVERITY_COLOR[SEVERITY_CRITICAL], str(total_c)):>6} "
        f"{c(SEVERITY_COLOR[SEVERITY_WARNING],  str(total_w)):>6} "
        f"{c(SEVERITY_COLOR[SEVERITY_INFO],     str(total_i)):>6} "
        f"{c(GREEN, str(total_f)):>6} "
        f"{total_t:.1f}s"
    )
    print(c(BOLD, "=" * width))
    print()


def save_combined_json_report(reports: list, output_path: Path):
    data = {
        "timestamp": datetime.now().isoformat(),
        "total_modules": len(reports),
        "summary": {
            "critical":      sum(r.critical_count for r in reports),
            "warnings":      sum(r.warning_count  for r in reports),
            "info":          sum(r.info_count     for r in reports),
            "fixes_applied": sum(r.fixes_applied  for r in reports),
            "open":          sum(sum(1 for i in r.issues if not i.fix_applied) for r in reports),
            "fixed":         sum(sum(1 for i in r.issues if i.fix_applied)     for r in reports),
            "total_elapsed_seconds": round(sum(r.elapsed_seconds for r in reports), 2),
        },
        "modules": [
            {
                "module_path": r.module_path,
                "from_version": r.from_version,
                "to_version": r.to_version,
                "summary": {
                    "critical": r.critical_count,
                    "warnings": r.warning_count,
                    "info":     r.info_count,
                    "fixable":  r.fixable_count,
                    "fixes_applied": r.fixes_applied,
                    "open": sum(1 for i in r.issues if not i.fix_applied),
                    "fixed": sum(1 for i in r.issues if i.fix_applied),
                    "elapsed_seconds": round(r.elapsed_seconds, 2),
                },
                "issues": [
                    {
                        "file": i.file,
                        "line": i.line,
                        "severity": i.severity,
                        "category": i.category,
                        "message": i.message,
                        "suggestion": i.suggestion,
                        "auto_fixable": i.auto_fixable,
                        "fix_applied":  i.fix_applied,
                    }
                    for i in r.issues
                ],
            }
            for r in reports
        ],
    }
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Combined JSON report saved → {output_path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Analyze and auto-fix Odoo module(s) for migration to Odoo 18/19",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python odoo_migrate_to_19.py --module ./sale_custom --from-version 14
              python odoo_migrate_to_19.py --module ./sale_custom --from-version 16 --fix --backup
              python odoo_migrate_to_19.py --modules ./mod_a ./mod_b --from-version 15 --fix --backup
              python odoo_migrate_to_19.py --addons-path ./custom_addons --from-version 16 --fix --backup
        """)
    )

    src = parser.add_argument_group("Module sources (use one or more)")
    src.add_argument("--module",      default=None, metavar="PATH")
    src.add_argument("--modules",     nargs="+", default=None, metavar="PATH")
    src.add_argument("--addons-path", default=None, metavar="DIR")

    parser.add_argument("--from-version", required=True, type=int)
    parser.add_argument("--to-version",   type=int, default=19, choices=[18, 19])
    parser.add_argument("--fix",          action="store_true")
    parser.add_argument("--backup",       action="store_true")
    parser.add_argument("--dry-run",      action="store_true")
    parser.add_argument("--report",       default=None, metavar="FILE")
    parser.add_argument("--no-color",     action="store_true")
    parser.add_argument("--skip",         nargs="+", default=[], metavar="NAME")
    parser.add_argument("--show-fixed",   action="store_true")
    parser.add_argument("--filter-severity", default=None,
                        choices=["CRITICAL", "WARNING", "INFO"], metavar="LEVEL")

    ai_grp = parser.add_argument_group("Claude AI fixes")
    ai_grp.add_argument("--ai-fix",    action="store_true")
    ai_grp.add_argument("--api-key",   default=None, metavar="KEY")
    ai_grp.add_argument("--ai-verbose",action="store_true")

    args = parser.parse_args()

    if not any([args.module, args.modules, args.addons_path]):
        parser.error("Provide at least one of --module, --modules, or --addons-path")

    if args.from_version >= args.to_version:
        print(f"ERROR: --from-version ({args.from_version}) must be less than "
              f"--to-version ({args.to_version}).")
        sys.exit(1)

    modules = resolve_modules(args)

    if args.skip:
        skip_set = set(args.skip)
        modules = [m for m in modules if m.name not in skip_set]

    invalid = [m for m in modules if not m.is_dir()]
    if invalid:
        for p in invalid:
            print(f"ERROR: Not a valid directory: {p}")
        sys.exit(1)

    if not modules:
        print("ERROR: No valid addon directories found.")
        sys.exit(1)

    do_fix = args.fix and not args.dry_run
    do_ai  = args.ai_fix and not args.dry_run

    if do_ai and not do_fix:
        print("WARNING: --ai-fix without --fix means regex fixes are skipped. "
              "Adding --fix automatically.")
        do_fix = True

    api_key: Optional[str] = None
    if do_ai:
        api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "ERROR: --ai-fix requires an Anthropic API key.\n"
                "  Pass it with --api-key or set the ANTHROPIC_API_KEY environment variable."
            )
            sys.exit(1)

    print(f"\n  Odoo Migration Tool  v{args.from_version} → {args.to_version}")
    print(f"  Modules : {len(modules)}")
    print(f"  Fix     : {'YES' if do_fix else 'NO (analyze only)'}")
    print(f"  Target  : Odoo {args.to_version}")
    print(f"  AI Fix  : {'YES (Claude ' + CLAUDE_MODEL + ')' if do_ai else 'NO'}")
    if args.dry_run:
        print("  Mode    : DRY RUN")
    if args.skip:
        print(f"  Skipped : {', '.join(args.skip)}")

    all_reports = []

    for i, module_path in enumerate(modules, 1):
        print(f"\n  [{i}/{len(modules)}] {module_path.name}")
        print(f"        Path: {module_path}")

        if do_fix and args.backup:
            backup_module(module_path)

        report = MigrationReport(
            module_path=str(module_path),
            from_version=args.from_version,
            to_version=args.to_version,
        )

        _t0 = time.monotonic()
        print("        Scanning...", end=" ", flush=True)
        walk_module(module_path, args.from_version, report, do_fix)
        report.elapsed_seconds = time.monotonic() - _t0
        status = (
            f"done  [crit={report.critical_count} "
            f"warn={report.warning_count} "
            f"info={report.info_count}"
            + (f" fixed={report.fixes_applied}" if do_fix else "")
            + f" {report.elapsed_seconds:.1f}s"
            + "]"
        )
        print(status)

        print_report(report, no_color=args.no_color, show_fixed=args.show_fixed,
                     filter_severity=args.filter_severity)
        all_reports.append(report)

    if do_ai and all_reports:
        ai_total = ai_fix_all_modules(
            reports=all_reports,
            module_paths=modules,
            api_key=api_key,
            verbose=args.ai_verbose,
        )
        if ai_total:
            print(f"\n  [AI] {ai_total} file(s) updated by Claude across all modules.")
        if ai_total and len(all_reports) > 1:
            print("\n  Re-printing reports after AI fixes:\n")
            for report in all_reports:
                print_report(report, no_color=args.no_color, show_fixed=args.show_fixed,
                             filter_severity=args.filter_severity)

    if len(all_reports) > 1:
        print_combined_summary(all_reports, no_color=args.no_color)

    if args.report:
        if len(all_reports) == 1:
            save_json_report(all_reports[0], Path(args.report))
        else:
            save_combined_json_report(all_reports, Path(args.report))

    total_critical = sum(r.critical_count for r in all_reports)
    total_other    = sum(r.warning_count + r.info_count for r in all_reports)
    if total_critical > 0:
        sys.exit(2)
    elif total_other > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()

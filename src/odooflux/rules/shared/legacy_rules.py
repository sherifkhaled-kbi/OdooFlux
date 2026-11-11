"""Legacy rule tables and fixers, moved unchanged from the P0 script (FR-021, R-07)."""

import io
import re
import ast
import textwrap
import tokenize
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# DATA STRUCTURES
# ─────────────────────────────────────────────

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARNING  = "WARNING"
SEVERITY_INFO     = "INFO"


STATUS_OPEN = "OPEN"
STATUS_FIXED = "FIXED"
STATUS_REJECTED = "REJECTED"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"


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
    evidence: list = field(default_factory=list)
    rejection_reason: str = ""
    maturity: str = ""  # knowledge-rule findings only (DETECT_ONLY / FIX_ENABLED); '' for legacy rows
    review_required: bool = False
    column: int = 0  # 1-based column of the match when the source gives one; 0 = not known (never guessed)

    @property
    def status(self) -> str:
        if self.fix_applied:
            return STATUS_FIXED
        if self.rejection_reason:
            return STATUS_REJECTED
        if not self.auto_fixable:
            return STATUS_NEEDS_REVIEW
        return STATUS_OPEN


@dataclass
class MigrationReport:
    module_path: str
    from_version: int
    to_version: int = 19
    issues: list = field(default_factory=list)
    fixes_applied: int = 0
    elapsed_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    reversible: bool = True  # False when --no-backup was used
    blocked: bool = False  # backup or write failure: the module was not written
    block_reason: str = ""
    actions: list = field(default_factory=list)  # [done: bool, text: str] file-level actions
    planned_files: list = field(default_factory=list)  # dry run: files that would change
    written_files: list = field(default_factory=list)

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

    @property
    def fixed_count(self):
        return sum(1 for i in self.issues if i.status == STATUS_FIXED)

    @property
    def rejected_count(self):
        return sum(1 for i in self.issues if i.status == STATUS_REJECTED)

    def open_findings(self, min_severity: str) -> int:
        """Open or review findings at or above *min_severity* (drives --fail-on)."""
        rank = {SEVERITY_INFO: 1, SEVERITY_WARNING: 2, SEVERITY_CRITICAL: 3}
        return sum(1 for i in self.issues
                   if i.status in (STATUS_OPEN, STATUS_NEEDS_REVIEW)
                   and rank[i.severity] >= rank[min_severity])


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
    (12, 0, r'\bopenerp\b', SEVERITY_CRITICAL, "Legacy Namespace",
     "Use of deprecated 'openerp' namespace",
     "Replace 'openerp' with 'odoo'", True),

    (0, 0, r'@api\.multi\b', SEVERITY_CRITICAL, "Deprecated Decorator",
     "@api.multi removed in 13.0 (EV-101); the default method type replaces it",
     "Remove @api.multi", True),

    # Detect-only (F-PY-4): removing @api.one changes per-record semantics.
    (0, 0, r'@api\.one\b', SEVERITY_CRITICAL, "Deprecated Decorator",
     "@api.one removed in 13.0 (EV-101); per-record semantics do not carry over automatically",
     "Rewrite as a loop over self, or call self.ensure_one(); not auto-fixed", False),

    # Removal applies only to v19 targets, where the decorator no longer exists (EV-102).
    (0, 19, r'@api\.returns\b', SEVERITY_CRITICAL, "Deprecated Decorator",
     "@api.returns removed in v19 (EV-102)",
     "Remove the decorator (applied by --fix for v19 targets)", True),

    (0, 0, r'@api\.returns\b', SEVERITY_WARNING, "Returns Semantics (review)",
     "@api.returns changes return-value handling when removed in v19 (EV-102)",
     "Review callers of this method and its return values before upgrading to v19", False),

    (0, 0, r'def \w+\(self,\s*cr,\s*uid', SEVERITY_CRITICAL, "Old API Signature",
     "Old-style (cr, uid, ids, context) method signature",
     "Migrate to new ORM API: remove cr/uid/ids/context parameters", False),

    (0, 0, r'fields\.Char\([^)]*size\s*=\s*\d+', SEVERITY_WARNING, "Deprecated Attribute",
     "fields.Char 'size' parameter is ignored in v13+",
     "Remove the 'size' attribute from fields.Char", True),

    (0, 0, r'\.execute_kw\(', SEVERITY_INFO, "XML-RPC",
     "execute_kw usage detected — verify return value handling for v14+",
     "Check that callers handle dict/bool return correctly", False),

    # Positional .sudo(user) is rewritten only for source <= 12 (EV-103): this rule fires only then.
    (13, 0, r'\.sudo\((?!True\b|False\b)\w+\)', SEVERITY_CRITICAL, "Sudo API Changed",
     "positional .sudo(user) was replaced by .with_user(user).sudo() in 13.0 (EV-103)",
     "Replace .sudo(user) with .with_user(user).sudo()", True),

    (0, 0, r'\.sudo\(\w+\)', SEVERITY_WARNING, "Sudo API Changed",
     "sudo(flag) takes a boolean from 13.0; a positional user needs .with_user(user).sudo() (EV-103)",
     "Verify the argument; positional users are not rewritten above 12.0", False),

    (0, 0, r'_inherits\s*=', SEVERITY_WARNING, "Delegation Inheritance",
     "_inherits is discouraged; verify it works for your use case in v16+",
     "Consider using _inherit with Many2one delegation instead", False),

    (0, 0, r'from\s+osv\s+import|from\s+openerp\.osv', SEVERITY_CRITICAL, "Legacy Import",
     "osv module import is no longer available",
     "Replace with 'from odoo import models, fields, api'", True),

    (12, 0, r'_columns\s*=\s*\{', SEVERITY_CRITICAL, "Legacy Field Definition",
     "_columns dict is removed; use class-level field declarations",
     "Convert _columns to class-level fields.X() declarations", False),

    (12, 0, r'_defaults\s*=\s*\{', SEVERITY_CRITICAL, "Legacy Defaults",
     "_defaults dict is removed; use default= argument on fields",
     "Move defaults to field definitions using default=...", False),

    (12, 0, r'from\s+openerp\.tools\s+import\s+html_sanitize', SEVERITY_CRITICAL, "Import Path",
     "html_sanitize import path changed",
     "Use: from odoo.tools import html_sanitize", True),

    (12, 0, r'^\s*print\s+["\']', SEVERITY_CRITICAL, "Python 2 Syntax",
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

    (12, 0, r'ir\.values', SEVERITY_CRITICAL, "Removed Model",
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

    (12, 0, r'from\s+openerp\.http\s+import', SEVERITY_CRITICAL, "HTTP Controller Import",
     "openerp.http import path removed",
     "Use: from odoo import http; class MyCtrl(http.Controller)", True),

    (12, 0, r'^\s*from\s+openerp\.', SEVERITY_CRITICAL, "Legacy openerp Import",
     "Import from deprecated 'openerp' namespace",
     "Replace 'openerp' with 'odoo' in import path", True),

    (12, 0, r'^\s*import\s+openerp\b', SEVERITY_CRITICAL, "Legacy openerp Import",
     "Direct import of deprecated 'openerp' module",
     "Replace 'import openerp' with 'import odoo'", True),

    (0, 0, r'from\s+odoo\.exceptions\s+import[^\n]*\bWarning\b', SEVERITY_CRITICAL,
     "Removed Exception: Warning",
     "odoo.exceptions.Warning is deprecated in 14.0–16.0 and removed in 17.0 (EV-110)",
     "Remove 'Warning' from the import and replace all raise Warning(...) with raise UserError(...)",
     True),

    (12, 0, r'from\s+openerp\.exceptions\s+import[^\n]*\bWarning\b', SEVERITY_CRITICAL,
     "Removed Exception: Warning (openerp)",
     "openerp.exceptions.Warning is deprecated in 14.0–16.0 and removed in 17.0 (EV-110); the namespace is also deprecated",
     "Replace with: from odoo.exceptions import UserError  and raise UserError(...)", True),

    (0, 0, r'\braise\s+Warning\s*\(', SEVERITY_CRITICAL, "Raise Warning",
     "Raising Warning() directly: odoo.exceptions.Warning is deprecated in 14.0–16.0 and removed in 17.0 (EV-110)",
     "Replace raise Warning(...) with raise UserError(...)", True),

    # Rows derived from the community article "Odoo Migration Decoded 16->17->18->19" (Medium). The article is NOT
    # official Odoo documentation and could not be retrieved (HTTP 403). Each row states its evidence status here:
    #   verified-official: confirmed by the official Odoo or Python source cited in the comment;
    #   contradicted:      official evidence differs from the article; the gate or severity was corrected or lowered;
    #   unverified:        no official evidence found; the gate is marked "gate unverified".
    # verified-official: 17.0 models.py name_get() warns "Since 17.0, deprecated method, read display_name instead";
    # 17.0 ORM changelog, entry "Odoo Online 16.4". The replacement is the display_name field, not _compute_display_name.
    (17, 0, r'def name_get\(', SEVERITY_WARNING, "name_get Deprecated",
     "name_get() is deprecated in Odoo 17.0 (DeprecationWarning); read the display_name field instead",
     "Read the display_name field instead of calling name_get()", False),

    # contradicted for 17: 17.0 and 18.0 models.py define a public read_group() with no deprecation note.
    # verified-official: the ORM changelog marks read_group() deprecated in its "Odoo Online 18.2" entry (in the 19.0
    # docs) and points backend code to _read_group(). Gate moved from 17 to the 19 target.
    (0, 19, r'(?<!_)\bread_group\s*\(', SEVERITY_WARNING, "read_group Deprecated",
     "read_group() is deprecated for backend use in Odoo 19.0 (ORM changelog, Odoo Online 18.2 entry)",
     "Use _read_group() for backend code and verify the call against the 19.0 source", False),

    # verified-official: 16.0 mail_thread.py message_post passes body through unchanged; 17.0 escapes a plain str body
    # (escape(body)) and keeps Markup unescaped. The 17 gate is confirmed by that difference.
    (17, 0, r'\bbody\s*=\s*f?["\'][^"\']*<', SEVERITY_WARNING, "HTML Body Not Markup",
     "HTML passed as a plain string to body= is escaped by message_post() from Odoo 17.0 and shows as text",
     "Wrap trusted HTML in Markup(...) from markupsafe; leave untrusted values as plain strings", False),

    # contradicted for the article's CRITICAL/17 claim: 17.0 odoo/__init__.py itself imports Command from odoo.fields,
    # so the path still works there. Kept as INFO for all source versions; the gate was removed.
    (0, 0, r'from\s+odoo\.fields\s+import\b[^\n]*\bCommand\b', SEVERITY_INFO, "Command Import Path",
     "Command imported from odoo.fields still works in Odoo 17.0; this is not an error",
     "Optional: import Command from odoo (from odoo import Command)", False),

    # verified-official: 16.0 loading.py calls post_init_hook(cr, registry); 17.0 loading.py calls post_init_hook(env).
    (17, 0, r'def post_init_hook\(cr,\s*registry', SEVERITY_CRITICAL, "post_init_hook Signature",
     "post_init_hook(cr, registry) is the 16.0 signature; Odoo 17.0 calls post_init_hook(env)",
     "Change the signature to def post_init_hook(env)", False),

    # verified-official (Python, not Odoo-specific): Python 3.12 what's new, PEP 632.
    (0, 0, r'^\s*(?:import\s+distutils\b|from\s+distutils\b)', SEVERITY_WARNING, "distutils Removed",
     "distutils was removed from the standard library in Python 3.12 (PEP 632); not an Odoo-specific change",
     "Replace distutils with setuptools, packaging or a standard-library equivalent", False),

    # verified-official (Python, not Odoo-specific): Python 3.12 what's new, Deprecated section.
    (0, 0, r'\.utcnow\(\)', SEVERITY_INFO, "utcnow Deprecated",
     "datetime.utcnow() is deprecated since Python 3.12; not an Odoo-specific change",
     "Use datetime.now(timezone.utc) or an aware datetime", False),

    # verified-official: the 19.0 branch odoo/upgrade_code/18.1-02-route-jsonrpc.py rewrites type="json" to "jsonrpc" in
    # controllers. The 18.0 HTTP docs list only 'json' and 'http', so the rename lands in 18.1; both targets are kept.
    (0, 18, r"@http\.route\([^)]*\btype\s*=\s*['\"]json['\"]", SEVERITY_WARNING, "Route type json",
     "type='json' route is renamed to 'jsonrpc' by Odoo's 18.1 upgrade script (the 18.0 docs list only 'json')",
     "Change type='json' to type='jsonrpc' in controllers", False),

    (0, 19, r"@http\.route\([^)]*\btype\s*=\s*['\"]json['\"]", SEVERITY_WARNING, "Route type json",
     "type='json' route is renamed to 'jsonrpc' by Odoo's 18.1 upgrade script",
     "Change type='json' to type='jsonrpc' in controllers; verify against the 19.0 source", False),

    # verified-official: 16.0 models.py defines invalidate_cache() and flush() with DeprecationWarning ("use
    # invalidate_model(), invalidate_recordset() or env.invalidate_all()" / "use flush_model(), flush_recordset() or
    # env.flush_all()"); 17.0 models.py defines neither method (https://raw.githubusercontent.com/odoo/odoo/16.0/odoo/models.py
    # and .../17.0/odoo/models.py). Gate kept at from < 17.
    (17, 0, r'\.invalidate_cache\(', SEVERITY_WARNING, "invalidate_cache Renamed",
     "invalidate_cache() is deprecated in Odoo 16.0 and not defined in 17.0; use invalidate_model() or "
     "invalidate_recordset()",
     "Replace with invalidate_model() or invalidate_recordset() (or env.invalidate_all())", False),

    # verified-official: same evidence as invalidate_cache(); flush() is deprecated in 16.0 and not a model method in 17.0.
    (17, 0, r'\.flush\(\)', SEVERITY_WARNING, "flush Renamed",
     "flush() is deprecated in Odoo 16.0 and not defined as a model method in 17.0; use flush_model() or "
     "flush_recordset()",
     "Replace with flush_model() or flush_recordset() (or env.flush_all())", False),

    # contradicted: 17.0 ir_actions_report.py defines _render_qweb_pdf with no deprecation note. Kept as INFO.
    (17, 0, r'\b_render_qweb_pdf\(', SEVERITY_INFO, "_render_qweb_pdf Deprecated",
     "_render_qweb_pdf() is still defined in Odoo 17.0 without a deprecation notice (article claim not confirmed)",
     "No change is needed for 17.0 unless the article's claim is confirmed against your target source", False),
]

XML_RULES = [
    (0, 0, r'<openerp>', SEVERITY_CRITICAL, "Legacy XML Root",
     "<openerp> root tag removed",
     "Replace <openerp> with <odoo>", True),

    # Detect-only (F-XML-2, EV-109): no converter exists until P4; attrs is never rewritten.
    (0, 0, r'\battrs\s*=\s*["\']', SEVERITY_CRITICAL, "Attrs Attribute",
     "'attrs' XML attribute removed in v17+ (EV-109)",
     "Rewrite as a Python expression, e.g. invisible=\"state == 'done'\"; automatic conversion is planned for a later release",
     False),

    # D2: not auto-fixable by the legacy fixer (it rewrites only with a verified state field, which a plain run
    # never has). The experimental registry fixes it on request (--experimental-fixes).
    (0, 0, r'\bstates\s*=\s*["\'](?!\s*["\'])', SEVERITY_WARNING, "States Attribute",
     "'states' shorthand removed in v17+; show-only-when-state-in-list semantics replaced by "
     "invisible= domain. The field name 'state' is assumed — verify it on the view's model.",
     "Replace states= with invisible=\"state not in [...]\" condition", False),

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

    # D4 / PA-2: the <tree> -> <list> change is placed at v18 by the community article, and <tree> is valid for a v17
    # target, so a 16 -> 17 run gets no <tree> finding. Two rows keep the "from < 18" gate for the 18 and 19 targets.
    # verified-official: the 18.0 branch odoo/upgrade_code/17.5-01-tree-to-list.py converts <tree> to <list> (17.5 -> 18.0
    # transition), so the v18 gate is confirmed by an official upgrade script (https://raw.githubusercontent.com/odoo/odoo/18.0/odoo/upgrade_code/17.5-01-tree-to-list.py).
    (18, 18, r'<tree\b', SEVERITY_CRITICAL, "Tree Tag Renamed",
     "<tree> view tag deprecated in v18 and replaced by <list>",
     "Replace <tree ...> with <list ...> and </tree> with </list>", True),

    (18, 19, r'<tree\b', SEVERITY_CRITICAL, "Tree Tag Renamed",
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

    # Rows derived from the community article "Odoo Migration Decoded 16->17->18->19" (Medium); status per row as in
    # PYTHON_RULES. t-raw: verified-official (17.0 QWeb docs). The article's 17 gate is contradicted (deprecated since 15.0);
    # t-raw still works, so WARNING for all sources.
    (0, 0, r'\bt-raw\s*=', SEVERITY_WARNING, "t-raw Deprecated",
     "t-raw is deprecated since Odoo 15.0 (QWeb docs); it still works and never escapes its content",
     "Replace t-raw with t-out on a markupsafe.Markup value", False),

    # contradicted: the 17.0, 18.0 and 19.0 QWeb docs call t-esc an alias of t-out and "Not yet formally deprecated".
    # Kept as INFO for the 18 target only; the article's warning is not confirmed.
    (0, 18, r'\bt-esc\s*=', SEVERITY_INFO, "t-esc Deprecated",
     "t-esc is an alias of t-out and not formally deprecated in the Odoo 18.0 QWeb docs (article warning not confirmed)",
     "t-out is the documented directive and escapes by default; t-esc still works", False),

    # gate unverified: no official 18.0 evidence found; the article is the only source for this row. Severity is INFO
    # because no official Odoo breaking change was found for inline scripts; the article's flag is not a confirmed break.
    (0, 18, r'<script\b', SEVERITY_INFO, "Inline Script in QWeb",
     "Inline <script> in a view or QWeb template is flagged for v18 by a community article; no official Odoo 18.0 breaking change was found (unverified)",
     "Move the script into an asset bundle; verify against the 18.0 source", False),

    # verified-official: 18.0 odoo/addons/web/static/src/views/kanban/kanban_arch_parser.js line 11 says '"kanban-box" is
    # deprecated' and line 153 warns at runtime; the replacement is a "card" template. 17.0 has only a NOTE comment. 19.0
    # reads only "card" (see the 18-19 KB rule). Gate kept at the 18 target.
    (0, 18, r'''t-name\s*=\s*["']kanban-box["']''', SEVERITY_WARNING, "kanban-box Template Renamed",
     "kanban-box template name is deprecated in Odoo 18.0 in favour of a 'card' template",
     "Rename the kanban-box template to t-name=\"card\"", False),
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
     "Rewrite as OWL component or ES module with /** @odoo-module */ header", False),

    (0, 0, r'require\(["\']web\.', SEVERITY_CRITICAL, "Legacy Require",
     "Deprecated require() usage for Odoo modules",
     "Use ES module imports: import { X } from '@web/...'", False),

    (0, 0, r'Widget\.extend\(', SEVERITY_CRITICAL, "Legacy Widget",
     "Widget.extend() pattern removed; Odoo now uses OWL",
     "Rewrite as OWL Component extending Component", False),

    # FIX: min_src_ver=16 — ajax.jsonRpc deprecated IN v16
    (16, 0, r'ajax\.jsonRpc\(', SEVERITY_WARNING, "AJAX Call",
     "ajax.jsonRpc deprecated in v16+",
     "Use this.env.services.rpc() or fetch with jsonrpc helper", False),

    (0, 0, r'\.on\(["\']click', SEVERITY_INFO, "jQuery Event",
     "jQuery event binding — OWL uses t-on-click directive",
     "Replace jQuery .on('click') with t-on-click in OWL template", False),

    (15, 0, r'useRef\(', SEVERITY_INFO, "OWL useRef",
     "Verify useRef() API compatibility with v19 OWL version",
     "Check OWL changelog for any useRef API changes", False),

    # Row derived from the community article "Odoo Migration Decoded 16->17->18->19" (Medium); community evidence, NOT
    # official Odoo documentation. gate unverified: no official evidence found for this v18 claim. Severity is INFO because
    # no official Odoo breaking change was found; the article's CSP flag is not a confirmed break.
    (0, 18, r'createElement\(\s*["\']script["\']', SEVERITY_INFO, "Script Injection (CSP)",
     "Runtime creation of a script element is flagged for v18 by a community article (CSP compatibility); no official Odoo 18.0 breaking change was found (unverified)",
     "Load the script through an asset bundle instead of injecting it at runtime", False),
]

CSS_RULES = [
    (0, 0, r'\.o_form_sheet_bg\b', SEVERITY_WARNING, "CSS Class",
     ".o_form_sheet_bg class renamed/restructured in v16+",
     "Verify CSS class exists in target version; use browser devtools", False),

    (0, 0, r'\.o_list_view\b', SEVERITY_WARNING, "CSS Class",
     ".o_list_view class restructured in v16+",
     "Check class hierarchy in v19", False),
]

# Rows derived from the community article "Odoo Migration Decoded 16->17->18->19" (Medium); community evidence, NOT
# official Odoo documentation. Applied in addition to CSS_RULES for .scss files only (see _rules_for_file).
# contradicted for Odoo 17.0: its assets compile SCSS with libsass (odoo/addons/base/models/assetsbundle.py), not dart-sass.
# The Dart Sass deprecations are real (sass-lang.com): @import deprecated since Dart Sass 1.80.0; '/' division replaced by
# math.div (1.33.0). Severity lowered to INFO for all targets.
SCSS_RULES = [
    (0, 0, r'^\s*@import\s', SEVERITY_INFO, "SCSS @import",
     "@import is deprecated in Dart Sass since 1.80.0 (removal in 3.0.0); Odoo 17.0 compiles SCSS with libsass",
     "If the asset is compiled with Dart Sass, check the import and consider @use", False),

    (0, 0, r'\$[\w-]+\s*/\s*\d|\b\d+(\.\d+)?(px|em|rem)\s*/\s*\d', SEVERITY_INFO, "SCSS Division",
     "Division with '/' is deprecated in Dart Sass (math.div since 1.33.0); Odoo 17.0 compiles SCSS with libsass",
     "If the asset is compiled with Dart Sass, replace a / b with math.div(a, b)", False),
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


def _decorator_spans(content: str, attr: str) -> list:
    """
    1-based (first_row, last_row) spans of whole-line ``@api.<attr>`` decorators (F-PY-1).

    Located with tokenize, so multi-line argument lists are covered. Returns [] when the source
    cannot be tokenized; the validation gate then guards the output.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
    except (tokenize.TokenError, SyntaxError):
        return []
    spans = []
    for i, tok in enumerate(tokens):
        if tok.type != tokenize.OP or tok.string != '@':
            continue
        if tok.line[:tok.start[1]].strip():
            continue  # not the first token on its line
        if [t.string for t in tokens[i + 1:i + 4]] != ['api', '.', attr]:
            continue
        end_row = tokens[i + 3].end[0]
        j = i + 4
        if j < len(tokens) and tokens[j].type == tokenize.OP and tokens[j].string == '(':
            depth = 0
            for k in range(j, len(tokens)):
                if tokens[k].type == tokenize.OP and tokens[k].string == '(':
                    depth += 1
                elif tokens[k].type == tokenize.OP and tokens[k].string == ')':
                    depth -= 1
                    if depth == 0:
                        end_row = tokens[k].end[0]
                        break
        spans.append((tok.start[0], end_row))
    return spans


def _remove_decorators(content: str, attr: str) -> str:
    """Delete whole lines of ``@api.<attr>`` decorators; comments and indentation of the rest stay."""
    spans = _decorator_spans(content, attr)
    if not spans:
        return content
    drop = {row for first, last in spans for row in range(first, last + 1)}
    return ''.join(line for row, line in enumerate(content.splitlines(keepends=True), 1)
                   if row not in drop)


def _kwarg_span(content: str, start: int, end: int) -> tuple:
    """
    Widen a ``name=value`` span to remove exactly one comma: the following one, or the preceding
    one when the keyword is last. A line left blank by the removal is removed with it.
    """
    m = re.match(r'[ \t\r\n]*,[ \t]*', content[end:])
    if m:
        end += m.end()
    else:
        m = re.search(r',[ \t\r\n]*$', content[:start])
        if m:
            start = m.start()
    line_start = content.rfind('\n', 0, start) + 1
    line_end = content.find('\n', end)
    line_end = len(content) if line_end == -1 else line_end
    if content[line_start:start].strip() == '' and content[end:line_end].strip() == '':
        start, end = line_start, min(line_end + 1, len(content))
    return start, end


def _remove_char_size_kwargs(content: str) -> str:
    """
    Remove ``size=<int>`` keyword arguments of ``fields.Char(...)`` calls (F-PY-2, R-06).

    Located with tokenize, so the removal is comma-aware and works on continuation lines. Other
    calls and assignments named ``size`` are never touched.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
    except (tokenize.TokenError, SyntaxError):
        return content
    line_starts = [0]
    for line in content.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))

    def offset(pos):
        return line_starts[pos[0] - 1] + pos[1]

    sig = [t for t in tokens if t.type not in (tokenize.NL, tokenize.COMMENT)]
    stack, spans = [], []
    for i, tok in enumerate(sig):
        if tok.type == tokenize.OP and tok.string in ('(', '[', '{'):
            stack.append(i)
            continue
        if tok.type == tokenize.OP and tok.string in (')', ']', '}'):
            if stack:
                stack.pop()
            continue
        if not (tok.type == tokenize.NAME and tok.string == 'size' and stack):
            continue
        open_i = stack[-1]
        if not (sig[open_i].string == '(' and open_i >= 3
                and [t.string for t in sig[open_i - 3:open_i]] == ['fields', '.', 'Char']):
            continue
        if i < 1 or sig[i - 1].string not in ('(', ','):
            continue  # not a keyword argument
        if i + 2 >= len(sig) or sig[i + 1].string != '=' or sig[i + 2].type != tokenize.NUMBER:
            continue
        spans.append(_kwarg_span(content, offset(tok.start), offset(sig[i + 2].end)))
    for start, end in sorted(spans, reverse=True):
        content = content[:start] + content[end:]
    return content


def apply_python_fixes(content: str, from_version: int, to_version: int = 19) -> str:
    content = rewrite_import_paths(content)
    content = re.sub(r'(?<![\w])openerp\.(?!addons)', 'odoo.', content)
    content = _remove_decorators(content, 'multi')
    if to_version >= 19:
        content = _remove_decorators(content, 'returns')  # removed in 19.0 (EV-102)
    content = re.sub(
        r'from\s+(?:openerp\.)?osv\s+import\s+(?:osv|orm|fields)',
        'from odoo import models, fields, api',
        content
    )
    if from_version <= 12:
        # .sudo(user) -> .with_user(user).sudo() only for source 12 and older (EV-103).
        content = re.sub(r'\.sudo\((?!True\b|False\b)(\w+)\)', r'.with_user(\1).sudo()', content)
    content = re.sub(
        r'from\s+openerp\.tools\s+import\s+html_sanitize',
        'from odoo.tools import html_sanitize',
        content
    )
    content = re.sub(r'^(\s*)print (["\'].+["\'])\s*$', r'\1print(\2)', content, flags=re.MULTILINE)
    content = _remove_char_size_kwargs(content)
    # Fix removed odoo.exceptions.Warning -> UserError
    content = fix_warning_exception(content)
    return content


_STATES_TAG = re.compile(
    r"""<(?P<name>button|field|notebook|group|div|span|page|label|separator)\b"""
    r"""(?P<body>(?:"[^"]*"|'[^']*'|[^>"'])*)>"""  # quoted values may contain '>' (D6)
)
_STATES_ATTR = re.compile(r"""\sstates\s*=\s*(["'])([^"']*)\1""")
_INVISIBLE_ATTR = re.compile(r"""\sinvisible\s*=""")
_ATTRS_ATTR = re.compile(r"""\sattrs\s*=""")


def _convert_states_to_invisible(content: str) -> str:
    """
    Convert the legacy states= attribute to an invisible= domain expression.

    states="draft,open" means "show only when the record's state is in the list", which is
    equivalent to invisible="state not in ['draft', 'open']". The controlling field is assumed to
    be ``state``, so the caller must have verified that the view's model has one (D2); this function
    is never reached otherwise.

    A tag that already has invisible= or attrs= is left untouched: its finding stays open (F-XML-4),
    or the experimental fixer decides it (one editor per element). No comment is written into the
    tag (F-XML-1).
    """
    def _replace(m: re.Match) -> str:
        body = m.group("body")
        states = _STATES_ATTR.search(body)
        if states is None:
            return m.group(0)
        if _INVISIBLE_ATTR.search(body) or _ATTRS_ATTR.search(body):
            return m.group(0)

        state_list = [s.strip().strip("'\"") for s in states.group(2).split(',') if s.strip()]
        if not state_list:
            return m.group(0)

        # Odoo 17+ new-style domain expression (Python-like, not JSON)
        states_repr = "[" + ", ".join(f"'{s}'" for s in state_list) + "]"
        invisible_expr = f"state not in {states_repr}"

        # Splice states="..." out by position (a similar string inside another value is not matched)
        remaining = body[:states.start()] + body[states.end():]
        # Insert invisible= before the closing "/" of a self-closing tag, or at the end of the tag
        remaining = re.sub(
            r'(\s*/?)$',
            lambda tm: f' invisible="{invisible_expr}"' + tm.group(1),
            remaining,
            count=1,
        )
        return f"<{m.group('name')}{remaining}>"

    return _STATES_TAG.sub(_replace, content)


def _well_formed(text: str) -> bool:
    try:
        ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return False
    return True


def apply_xml_fixes(content: str, from_version: int, to_version: int = 19, *,
                    verified_state_field: bool = False) -> str:
    """
    Legacy XML fixes. Conversions that Odoo 18 introduced (<tree> -> <list>, view_type/view_mode
    'tree' -> 'list', the chatter block) run only for to_version >= 18; the others run for every target.

    ``verified_state_field`` (D2): states= is rewritten only when the caller has verified that the view's
    model has a ``state`` field. Without it states= is left as written, for the experimental fixer or review.

    D6: if the rewritten text is not well-formed XML, the original text is returned unchanged.
    """
    fixed = _apply_xml_rewrites(content, to_version, verified_state_field)
    if fixed != content and not _well_formed(fixed):
        return content
    return fixed


def _apply_xml_rewrites(content: str, to_version: int, verified_state_field: bool) -> str:
    # <openerp> → <odoo>
    content = re.sub(r'<openerp>', '<odoo>', content)
    content = re.sub(r'</openerp>', '</odoo>', content)

    # ── states= → invisible= domain expression (Odoo 17+; only with a verified state field, D2) ──
    if verified_state_field:
        content = _convert_states_to_invisible(content)

    # groups_id= → groups=
    content = re.sub(r'\bgroups_id\s*=', 'groups=', content)

    if to_version >= 18:
        # v18+: <tree> → <list>
        content = re.sub(r'<tree\b', '<list', content)
        content = re.sub(r'</tree(\s*)>', r'</list\1>', content)
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

        # ── Chatter auto-fixes (v18+) ─────────────────────────────────────────

        # FIX: safer chatter div replacement using a depth-counter approach
        # to avoid eating nested </div> tags
        content = _replace_chatter_div(content)

        # Self-closing fields are matched by "/>" (a "/" inside an attribute value does not stop the match), and
        # the paired form must not end on a self-closing start tag, or it would consume the next </field> (D6).
        for _chatter_field in ('message_ids', 'activity_ids', 'message_follower_ids'):
            content = re.sub(
                r'<field\b[^>]*?\sname=["\']' + _chatter_field + r'["\'][^>]*?/\s*>',
                '',
                content,
            )
            content = re.sub(
                r'<field\b[^>]*?\sname=["\']' + _chatter_field + r'["\'][^>]*?(?<!/)>.*?</field>',
                '',
                content,
                flags=re.DOTALL,
            )

        content = re.sub(
            r'<field\b[^>]*?\swidget=["\']mail_thread["\'][^>]*?/\s*>',
            '<chatter/>',
            content,
        )
        content = re.sub(
            r'<field\b[^>]*?\swidget=["\']mail_thread["\'][^>]*?(?<!/)>.*?</field>',
            '<chatter/>',
            content,
            flags=re.DOTALL,
        )

    content = re.sub(r'\n{3,}', '\n\n', content)
    return content


_DIV_TOKEN = re.compile(r"""<div\b(?:"[^"]*"|'[^']*'|[^>"'])*?(/?)>|</div\s*>""", re.IGNORECASE)
_CHATTER_DIV = re.compile(r'<div[^>]+class=["\'][^"\']*oe_chatter[^"\']*["\'][^>]*>', re.IGNORECASE)


def _matching_div_end(content: str, pos: int):
    """End offset of the </div> that closes the element opened just before ``pos``, or None if unbalanced.
    Only real <div> tags count: <divider/> and other names that start with "div" do not (D6)."""
    depth = 1
    for token in _DIV_TOKEN.finditer(content, pos):
        if token.group(0).startswith('</'):
            depth -= 1
        elif not token.group(1):  # an opening tag; "<div/>" is self-closing and changes nothing
            depth += 1
        if depth == 0:
            return token.end()
    return None


def _replace_chatter_div(content: str) -> str:
    """
    Replace <div class="oe_chatter">...</div> with <chatter/>. The end of the block is found with a depth
    counter over <div> tags, so nested divs are handled and a self-closing chatter div is replaced on its own.
    A block whose end cannot be found is left exactly as written.
    """
    result = []
    i = 0
    while True:
        m = _CHATTER_DIV.search(content, i)
        if m is None:
            result.append(content[i:])
            break
        result.append(content[i:m.start()])
        end = m.end() if m.group(0).endswith('/>') else _matching_div_end(content, m.end())
        if end is None:
            result.append(m.group(0))
            i = m.end()
            continue
        result.append('<chatter/>')
        i = end
    return ''.join(result)


def apply_manifest_fixes(content: str, from_version: int, to_version: int = 19) -> str:
    """
    Replace only the major prefix of the module version (FR-009):
    '14.0.2.3.1' -> '19.0.2.3.1'. Single- and double-quoted values are both handled.
    """
    return re.sub(
        r"""((['"])version\2\s*:\s*(['"]))\d+(?=\.0[.'"])""",
        lambda m: f"{m.group(1)}{to_version}",
        content,
    )


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
SCSS_RULES_C     = _compile_rules(SCSS_RULES)
PYTHON_RULES_V18_C   = _compile_rules(PYTHON_RULES_V18)
XML_RULES_V18_C      = _compile_rules(XML_RULES_V18)
MANIFEST_RULES_V18_C = _compile_rules(MANIFEST_RULES_V18)
PYTHON_RULES_V19_C   = _compile_rules(PYTHON_RULES_V19)
XML_RULES_V19_C      = _compile_rules(XML_RULES_V19)
MANIFEST_RULES_V19_C = _compile_rules(MANIFEST_RULES_V19)


MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")
_MANIFEST_LICENSE_KEY = re.compile(r"""['"]license['"]\s*:""")


def check_content(content: str, filepath: str, compiled_rules: list,
                  from_version: int, report: MigrationReport):
    """
    Scan file content line-by-line against pre-compiled rules.

    - min_ver: rule applies only when from_version < min_ver (the breaking change was introduced
      IN min_ver, so older codebases need the fix). min_ver=0 means always applies.
    - exact_tgt_ver: rule applies only when to_version == exact_tgt_ver (0 = all targets).
    """
    lines = content.splitlines()
    seen: set = set()

    # File-level check. contradicted: the Odoo 17.0 manifest docs give 'license' a default of LGPL-3, so a missing key is
    # not an error and the article's "expected from v17" gate is not kept. Reported as INFO for every source version.
    if Path(filepath).name.lower() in MANIFEST_NAMES \
            and not _MANIFEST_LICENSE_KEY.search(content):
        report.issues.append(Issue(
            file=filepath, line=1, severity=SEVERITY_INFO, category="License Missing",
            message="No 'license' key in the manifest; Odoo 17.0 documents a default of LGPL-3",
            suggestion="Set 'license' explicitly if the module is not LGPL-3",
            auto_fixable=False,
        ))

    for min_ver, exact_tgt_ver, pattern, severity, category, message, suggestion, auto_fixable in compiled_rules:
        if min_ver != 0 and from_version >= min_ver:
            continue
        if exact_tgt_ver != 0 and report.to_version != exact_tgt_ver:
            continue
        for i, line in enumerate(lines, 1):
            match = pattern.search(line)
            if match:
                key = (i, category)
                if key in seen:
                    continue
                seen.add(key)
                report.issues.append(Issue(
                    file=filepath,
                    line=i,
                    column=match.start() + 1,  # the match start on this line, 1-based (PA-5)
                    severity=severity,
                    category=category,
                    message=message,
                    suggestion=suggestion,
                    auto_fixable=auto_fixable,
                    evidence=re.findall(r'EV-\d+', message),
                ))


def scan_content(content: str, filepath: str, from_version: int, to_version: int) -> list:
    """Findings for *content*, returned without touching any report (used for re-scans)."""
    scratch = MigrationReport(module_path="", from_version=from_version, to_version=to_version)
    rules = _rules_for_file(Path(filepath), to_version=to_version)
    if rules is not None:
        check_content(content, filepath, rules, from_version, scratch)
    return scratch.issues


def _read_file(filepath: Path, report: MigrationReport) -> Optional[str]:
    """Read a file as UTF-8. Undecodable files are reported and never rewritten (edge case)."""
    try:
        raw = filepath.read_bytes()
    except OSError as e:
        report.issues.append(Issue(
            file=str(filepath), line=0, severity=SEVERITY_WARNING,
            category="Read Error", message=f"Could not read file: {e}",
            suggestion="Check file permissions", auto_fixable=False,
        ))
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        report.issues.append(Issue(
            file=str(filepath), line=0, severity=SEVERITY_WARNING,
            category="Encoding",
            message=f"Not valid UTF-8 (byte {e.start}); the file was not rewritten",
            suggestion="Convert the file to UTF-8, then re-run", auto_fixable=False,
        ))
        return None


def _rules_for_file(filepath: Path, to_version: int = 19) -> Optional[list]:
    name = filepath.name.lower()
    ext  = filepath.suffix.lower()
    if name in MANIFEST_NAMES:
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
    if ext == ".scss":
        return CSS_RULES_C + SCSS_RULES_C
    if ext in (".css", ".less"):
        return CSS_RULES_C
    return None



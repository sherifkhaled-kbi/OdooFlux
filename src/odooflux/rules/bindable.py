"""Generic rule modules that rule metadata may bind (REQ-PY-003, REQ-XML-003).

Metadata refers to them as ``module:function``. The loader (``rules.shared.loader``) is core code and takes
this table as an argument, so it never imports rule modules itself.
"""

from odooflux.rules.assets import generic as assets_generic
from odooflux.rules.javascript import generic as javascript_generic
from odooflux.rules.manifest import files as manifest_files
from odooflux.rules.manifest import hygiene as manifest_hygiene
from odooflux.rules.models import renamed as models_renamed
from odooflux.rules.owl import generic as owl_generic
from odooflux.rules.python import certified as python_certified
from odooflux.rules.python import generic as python_generic
from odooflux.rules.python import sql_constraints as python_sql_constraints
from odooflux.rules.security import acl_csv as security_acl_csv
from odooflux.rules.security import field_refs as security_field_refs
from odooflux.rules.security import record_rules as security_record_rules
from odooflux.rules.qweb import generic as qweb_generic
from odooflux.rules.xml import generic as xml_generic
from odooflux.rules.xml import view_mode as xml_view_mode
from odooflux.rules.xml import view_refs as xml_view_refs
from odooflux.rules.xml import view_types as xml_view_types

BINDABLE_MODULES = {
    "odooflux.rules.models.renamed": models_renamed,
    "odooflux.rules.owl.generic": owl_generic,
    "odooflux.rules.assets.generic": assets_generic,
    "odooflux.rules.javascript.generic": javascript_generic,
    "odooflux.rules.manifest.hygiene": manifest_hygiene,
    "odooflux.rules.manifest.files": manifest_files,
    "odooflux.rules.python.certified": python_certified,
    "odooflux.rules.python.generic": python_generic,
    "odooflux.rules.python.sql_constraints": python_sql_constraints,
    "odooflux.rules.xml.generic": xml_generic,
    "odooflux.rules.xml.view_mode": xml_view_mode,
    "odooflux.rules.xml.view_refs": xml_view_refs,
    "odooflux.rules.xml.view_types": xml_view_types,
    "odooflux.rules.qweb.generic": qweb_generic,
    "odooflux.rules.security.field_refs": security_field_refs,
    "odooflux.rules.security.acl_csv": security_acl_csv,
    "odooflux.rules.security.record_rules": security_record_rules,
}

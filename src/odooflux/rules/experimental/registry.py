"""Registry of experimental fixers (roadmap AD-1): shipped rule id -> fixer, bound per run on request.

The knowledge base is not touched: a registry entry never changes a row's maturity, never certifies anything and is
never read by ``fix_row_trusted``, ``promote`` or activation. ``bind_rule`` attaches the fixer to the existing detector
only when the run asks for experimental fixes; the same fixer reference resolves through ``MODULES`` here, not through
the ordinary bindable table, so a plain metadata row cannot reach it.
"""

from dataclasses import dataclass, field

from odooflux.rules.experimental import xml_modifiers

MODULES = {"odooflux.rules.experimental.xml_modifiers": xml_modifiers}
# VR-1: the run's module context (sibling modules of the addons root), created once per run by the orchestrator
MODULE_VIEWS = xml_modifiers.ModuleViews


@dataclass(frozen=True)
class ExperimentalFix:
    rule_id: str
    fixer_ref: str  # module:function, resolved through MODULES
    explain: object  # (document, views=None) -> Plan with converted and refused records; pure, no edits
    description: str
    params: dict = field(default_factory=dict)  # extra keyword params for the bound functions (none today)
    step: str = ""  # the rule step key (N-M) this fixer converts; a row of any other step is never offered it


ENTRIES = {
    "16-17.xml.attrs-removed": ExperimentalFix(
        rule_id="16-17.xml.attrs-removed",
        fixer_ref="odooflux.rules.experimental.xml_modifiers:convert_attrs",
        explain=xml_modifiers.explain_attrs,
        description="attrs= to invisible/readonly/required for the strict subset (plain form, literal non-falsy "
                    "leaves, & | ! only); everything else refused with a reason",
        step="16-17"),
    "16-17.xml.states-attribute-removed": ExperimentalFix(
        rule_id="16-17.xml.states-attribute-removed",
        fixer_ref="odooflux.rules.experimental.xml_modifiers:convert_states",
        explain=xml_modifiers.explain_states,
        description="states= to invisible=\"state not in [...]\" when the element has no invisible and no attrs",
        step="16-17"),
}

"""One sample plugin per registry kind (TST-003-024). Loaded with --plugin contract.samples.sample_plugins:PLUGIN."""

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.contracts.plugins import PluginEntry
from odooflux.core.contracts.records import Finding, OdooVersion, ValidationResult


class SampleRule:
    key = "sample.todo"
    contract_version = CONTRACT_VERSION
    step = "*"
    depends = ()

    def detect(self, document):
        out = []
        for number, line in enumerate(document.text.splitlines(), 1):
            if "SAMPLE_TODO" in line:
                out.append(Finding(rule_id="SAMPLE_RULE", path=document.path, line=number,
                                   severity="WARNING", message="sample marker found",
                                   suggestion="remove the marker"))
        return out


class SampleValidator:
    key = "sample.reject"
    contract_version = CONTRACT_VERSION
    layer = 1

    def applies_to(self, path):
        return path.endswith(".py")

    def validate(self, path, text):
        if "REJECT_ME" in text:
            return ValidationResult(layer=1, outcome="FAIL", reason="sample validator rejects REJECT_ME")
        return ValidationResult(layer=1, outcome="PASS")


class SampleParser:
    key = "sample"
    contract_version = CONTRACT_VERSION

    def parse(self, text):
        return None


class SampleRuntime:
    key = "sample-runtime"
    contract_version = CONTRACT_VERSION

    def available(self):
        return False


class SampleAI:
    key = "sample-ai"
    contract_version = CONTRACT_VERSION

    def complete(self, prompt, *, api_key, to_version):
        return ""


class SampleRenderer:
    key = "sample-text"
    contract_version = CONTRACT_VERSION

    def render(self, report):
        return f"SAMPLE {report['run']['mode']}\n"


PLUGIN = [
    PluginEntry("rules", SampleRule()),
    PluginEntry("validators", SampleValidator()),
    PluginEntry("parsers", SampleParser()),
    PluginEntry("runtimes", SampleRuntime()),
    PluginEntry("ai_providers", SampleAI()),
    PluginEntry("renderers", SampleRenderer()),
    PluginEntry("versions", OdooVersion("20.0")),
]

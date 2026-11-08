"""Document-level adapters for the knowledge extraction domains (feature 011, REQ-ARC-001).

Core packages cannot import adapters, so the composition root (`builtins`) builds one `ExtractToolkit` and
attaches it to the registries as `registries.extract_toolkit`. The extract driver, the domain extractors and
the CLI receive it as a parameter. This module lives in `parsers` (the adapter layer) and imports only
`parsers.*` and core.

- `python_document(text, path)`: a span-bearing `PythonDocument` (`.tree`, `.parse_error`, `.raw_tokens`).
- `xml_document(text, path)`: a span-bearing `XmlDocument` (`.elements`, `.text`, `.parse_error`).
- `javascript_available()` / `javascript()`: the optional tree-sitter adapter. Imported lazily; `available()`
  is False without the `js` extra or when `ODOOFLUX_DISABLE_JS_ADAPTER` masks it.
- `detectors`: detector ref (`module:function`) -> bindable rule module, built by `detector_table` from
  `BINDABLE_MODULES` and validated at construction. Template `detector_ref` values are checked against it.

Nothing here executes target code. Parsers only read text.
"""

import inspect

from odooflux.knowledge.candidates.templates import FIXER_PREFIXES, check_detector_table, detector_shape_problem
from odooflux.parsers.python.document import parse as _parse_python
from odooflux.parsers.xml.document import parse as _parse_xml


def detector_table(bindable_modules) -> dict:
    """The bindable detector table built from the explicit `bindable_modules` mapping (module name -> module, the
    `BINDABLE_MODULES` shape): detector ref `module:function` -> that module. A detector is a public function defined
    in the listed module, not a fixer, whose parameters after the first two are keyword-only (the T056 rule). Only the
    listed modules are inspected; no filesystem or package scanning."""
    table = {}
    for module_name in sorted(bindable_modules):
        module = bindable_modules[module_name]
        for name, obj in sorted(vars(module).items()):
            if name.startswith(("_",) + FIXER_PREFIXES) or not inspect.isfunction(obj):
                continue
            if obj.__module__ != module.__name__ or detector_shape_problem(f"{module_name}:{name}", obj):
                continue
            table[f"{module_name}:{name}"] = module
    return table


class ToolkitUnavailable(RuntimeError):
    """A requested adapter is not available in this installation (for example the optional JS extra)."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class ExtractToolkit:
    def __init__(self, detectors=None):
        self.detectors = dict(detectors or {})
        check_detector_table(self.detectors)  # composition time: a malformed entry raises, naming its ref

    def python_document(self, text: str, path: str = ""):
        return _parse_python(text, path)

    def xml_document(self, text: str, path: str = "<memory>"):
        return _parse_xml(text, path=path)

    def javascript_available(self) -> bool:
        from odooflux.parsers.javascript import treesitter_adapter
        return treesitter_adapter.available()

    def javascript(self):
        """The tree-sitter adapter module (`parse(text)` returns a tree). Raises ToolkitUnavailable."""
        if not self.javascript_available():
            raise ToolkitUnavailable("NO_JS_ADAPTER", "the optional tree-sitter JavaScript adapter is not available")
        from odooflux.parsers.javascript import treesitter_adapter
        return treesitter_adapter

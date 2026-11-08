"""Shared helpers for the AI tests: fixture loading, toy rule, a recording/raising transport."""

import json
from pathlib import Path

from tests.unit._setup import SRC  # noqa: F401  (src/ first on sys.path)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ai"


def script(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def corpus(name: str) -> str:
    return (FIXTURES / "corpus" / name).read_text(encoding="utf-8")


def test_catalog(extra_providers: dict | None = None) -> dict:
    """A catalog made of fake model names: the tests never depend on a real model identifier."""
    providers = {
        "alpha": {"type": "external", "adapter": "openai_compatible", "endpoint": "https://alpha.invalid/v1",
                  "credential_env": "ALPHA_KEY",
                  "models": [{"id": "m-one", "context_window": 8000, "max_output": 1000,
                              "structured_output": True, "tool_calling": False,
                              "pricing": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}},
                             {"id": "m-nopricing", "context_window": 8000, "max_output": 1000}]},
        "beta": {"type": "external", "adapter": "anthropic", "endpoint": "https://beta.invalid/v1/messages",
                 "credential_env": "BETA_KEY", "models": [{"id": "b-one", "context_window": 8000,
                                                             "max_output": 1000}]},
        "loc": {"type": "local", "adapter": "openai_compatible", "endpoint": "http://127.0.0.1:1/v1",
                "models": [{"id": "l-one", "context_window": 4000, "max_output": 500}]},
        "fake": {"type": "fake", "adapter": "fake", "models": [{"id": "fake-model", "context_window": 100000,
                                                                "max_output": 4000, "structured_output": True}]},
    }
    providers.update(extra_providers or {})
    return {"schema": "odooflux.ai-catalog/1", "providers": providers}


# ---- toy rules used by escalation tests (rule metadata is test data, not Knowledge Base content) ----

import ast  # noqa: E402
from dataclasses import dataclass  # noqa: E402

from odooflux.ai.escalation import FindingRef, RuleMeta  # noqa: E402

EVIDENCE = ({"id": "EV-TOY-1", "excerpt": "old_api was replaced by new_api (test evidence)"},)
TOY_METAS = {
    "toy.old-api": RuleMeta("toy.old-api", ai_eligible=True, has_fix=False, evidence=EVIDENCE,
                            docs="Replace old_api with new_api."),
    "toy.legacy-defaults": RuleMeta("toy.legacy-defaults", ai_eligible=True, has_fix=False, evidence=EVIDENCE),
    "toy.review": RuleMeta("toy.review", ai_eligible=True, has_fix=False, evidence=EVIDENCE,
                           review_required=True),
}


@dataclass(frozen=True)
class Seen:
    rule_id: str
    line: int


def toy_rescan(path: str, text: str) -> list:
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        if "old_api(" in line:
            out.append(Seen("toy.old-api", no))
        if "legacy_call(" in line:
            out.append(Seen("toy.review", no))
        if "legacy_defaults" in line:
            out.append(Seen("toy.legacy-defaults", no))
    return out


def toy_findings(path: str, text: str) -> list:
    return [FindingRef(id=f"{s.rule_id}:{s.line}", rule_id=s.rule_id, path=path, line=s.line, message="m")
            for s in toy_rescan(path, text)]


def python_validate(path: str, text: str):
    """The L1 stand-in: (validator, reason) on failure, else None."""
    try:
        ast.parse(text)
    except SyntaxError as exc:
        return ("python-syntax", str(exc.msg))
    return None

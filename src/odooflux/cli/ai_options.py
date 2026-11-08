"""CLI options for optional AI assistance (feature 007, ADR-017). Pure argument handling.

This module imports nothing from ``odooflux.ai``: the core never loads a provider. It validates what can be
checked without the model catalog (consent, provider and model named, job budget) and returns a plain
configuration that the registered escalation pass interprets. AI stays off unless ``--ai`` is given.
"""

from dataclasses import asdict, dataclass, field
from typing import Optional

CONSENT_FLAG = "--ai-consent-send-code"
ENV_KILL_SWITCH = "ODOOFLUX_AI_DISABLE_EXTERNAL"
ENV_FAKE_SCRIPT = "ODOOFLUX_AI_FAKE_SCRIPT"
_TRUE = ("1", "true", "yes", "on")


@dataclass
class AIConfig:
    enabled: bool = False
    provider_type: str = "external"  # default provider type (ADR-017); AI is still off until --ai
    provider: str = ""
    model: str = ""
    consent_send_code: bool = False
    authorizations: dict = field(default_factory=dict)  # provider -> sorted list of data categories
    kill_switch: bool = False
    endpoint: str = ""
    catalog_paths: list = field(default_factory=list)
    budget_job_tokens: Optional[int] = None
    budget_module_tokens: Optional[int] = None
    budget_file_tokens: Optional[int] = None
    budget_request_tokens: Optional[int] = None
    budget_job_cost: Optional[float] = None
    max_retries: int = 2
    timeout_s: float = 60.0
    use_cache: bool = True
    clear_cache: bool = False
    secrets_file: str = ""
    fake_script: str = ""

    def to_dict(self) -> dict:
        """JSON-able copy for the run state. Never holds a credential."""
        return asdict(self)


def add_ai_arguments(parser) -> None:
    group = parser.add_argument_group("AI assistance (optional; off unless --ai)")
    group.add_argument("--ai", action="store_true", help="enable provider-neutral AI assistance")
    group.add_argument("--ai-provider", default=None, metavar="NAME")
    group.add_argument("--ai-model", default=None, metavar="ID", help="a model id from the provider catalog")
    group.add_argument("--ai-provider-type", default="external", choices=["external", "local"],
                       help="default: external")
    group.add_argument(CONSENT_FLAG, action="store_true", dest="ai_consent_send_code",
                       help="consent to sending minimised source regions to the selected provider")
    group.add_argument("--ai-authorize", action="append", default=[], metavar="PROVIDER=CAT[,CAT]",
                       help="authorize a provider for data categories (source_python, source_xml, "
                            "evidence_excerpt); repeatable")
    group.add_argument("--ai-disable-external", action="store_true",
                       help=f"kill switch: block all external transmission (also {ENV_KILL_SWITCH}=1)")
    group.add_argument("--ai-endpoint", default=None, metavar="URL", help="override the provider endpoint")
    group.add_argument("--ai-catalog", action="append", default=[], metavar="FILE",
                       help="model catalog JSON to merge over the packaged one; repeatable")
    group.add_argument("--ai-budget-job-tokens", type=int, default=None, metavar="N")
    group.add_argument("--ai-budget-module-tokens", type=int, default=None, metavar="N")
    group.add_argument("--ai-budget-file-tokens", type=int, default=None, metavar="N")
    group.add_argument("--ai-budget-request-tokens", type=int, default=None, metavar="N")
    group.add_argument("--ai-budget-job-cost", type=float, default=None, metavar="AMOUNT",
                       help="needs pricing configured for the model")
    group.add_argument("--ai-max-retries", type=int, default=2, metavar="N")
    group.add_argument("--ai-timeout", type=float, default=60.0, metavar="SECONDS")
    group.add_argument("--ai-no-cache", action="store_true")
    group.add_argument("--ai-clear-cache", action="store_true")
    group.add_argument("--ai-secrets-file", default=None, metavar="FILE",
                       help="KEY=VALUE credentials file outside the scanned paths")


def parse_authorizations(values) -> tuple:
    """``["p=a,b"]`` -> ({"p": ["a", "b"]}, error or None)."""
    grants: dict = {}
    for value in values or []:
        provider, sep, cats = value.partition("=")
        categories = sorted({c.strip() for c in cats.split(",") if c.strip()})
        if not sep or not provider.strip() or not categories:
            return {}, f"--ai-authorize expects PROVIDER=CATEGORY[,CATEGORY], got {value!r}"
        grants.setdefault(provider.strip(), set()).update(categories)
    return {p: sorted(c) for p, c in grants.items()}, None


def resolve_ai(args, environ) -> tuple:
    """Return ``(AIConfig, error)``. ``error`` is a message for the usage-error exit code (2), else None."""
    cfg = AIConfig(
        enabled=bool(getattr(args, "ai", False)),
        provider_type=getattr(args, "ai_provider_type", "external") or "external",
        provider=(getattr(args, "ai_provider", None) or "").strip(),
        model=(getattr(args, "ai_model", None) or "").strip(),
        consent_send_code=bool(getattr(args, "ai_consent_send_code", False)),
        kill_switch=bool(getattr(args, "ai_disable_external", False))
        or str(environ.get(ENV_KILL_SWITCH, "")).strip().lower() in _TRUE,
        endpoint=getattr(args, "ai_endpoint", None) or "",
        catalog_paths=list(getattr(args, "ai_catalog", []) or []),
        budget_job_tokens=getattr(args, "ai_budget_job_tokens", None),
        budget_module_tokens=getattr(args, "ai_budget_module_tokens", None),
        budget_file_tokens=getattr(args, "ai_budget_file_tokens", None),
        budget_request_tokens=getattr(args, "ai_budget_request_tokens", None),
        budget_job_cost=getattr(args, "ai_budget_job_cost", None),
        max_retries=getattr(args, "ai_max_retries", 2),
        timeout_s=getattr(args, "ai_timeout", 60.0),
        use_cache=not getattr(args, "ai_no_cache", False),
        clear_cache=bool(getattr(args, "ai_clear_cache", False)),
        secrets_file=getattr(args, "ai_secrets_file", None) or "",
        fake_script=environ.get(ENV_FAKE_SCRIPT, ""))
    grants, bad = parse_authorizations(getattr(args, "ai_authorize", []))
    cfg.authorizations = grants
    if getattr(args, "ai_fix", False) and cfg.kill_switch:
        return cfg, ("--ai-fix sends whole files to an external provider and is blocked while the kill switch is on "
                     f"(--ai-disable-external or {ENV_KILL_SWITCH}=1)")
    if not cfg.enabled:
        return cfg, None
    if getattr(args, "ai_fix", False):
        return cfg, "--ai and --ai-fix are exclusive: --ai-fix is the legacy whole-file Anthropic path"
    if bad:
        return cfg, bad
    if not cfg.consent_send_code:
        return cfg, (f"--ai needs {CONSENT_FLAG}: source regions are sent to the selected provider only "
                     "after you consent explicitly")
    if not cfg.provider:
        return cfg, "--ai needs --ai-provider (OdooFlux never picks a provider for you)"
    if not cfg.model:
        return cfg, "--ai needs --ai-model (a model id from the provider catalog)"
    if cfg.budget_job_tokens is None:
        return cfg, "--ai needs --ai-budget-job-tokens (the job budget is mandatory when AI is enabled)"
    for name in ("budget_job_tokens", "budget_module_tokens", "budget_file_tokens", "budget_request_tokens"):
        value = getattr(cfg, name)
        if value is not None and value <= 0:
            return cfg, f"--ai-{name.replace('_', '-')} must be positive"
    if cfg.max_retries < 0 or cfg.timeout_s <= 0:
        return cfg, "--ai-max-retries must be >= 0 and --ai-timeout must be > 0"
    return cfg, None
